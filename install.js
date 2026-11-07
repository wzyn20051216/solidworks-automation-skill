#!/usr/bin/env node
/**
 * @file SolidWorks Automation Skill 安装器。
 *
 * 设计原则（2026-10-28 重写，修复此前会静默删除用户目录的缺陷）：
 *   1. 绝不删除用户已有目录。目标已存在且不是本仓库的 git 检出时默认拒绝并说明；
 *      只有显式 --force-reinstall 才把旧目录**重命名**为 <dir>.bak-<时间戳> 后再安装。
 *   2. 不猜客户端。默认只装到「已经存在 skills 目录」的客户端，且绝不凭空创建目录；
 *      要装到指定客户端用 --target。一个都没检测到时给出可复制的命令，而不是替你创建。
 *   3. 自动配置依赖和注册 MCP；可通过参数关闭，失败必须明确报告。
 *   4. 先给计划再动手。--dry-run 只打印将要执行的动作，不写盘。
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const SKILL_NAME = 'solidworks-automation';
const REPO_URL = 'https://github.com/wzyn20051216/solidworks-automation-skill.git';
const MIN_NODE_MAJOR = 20;
const OFFICIAL_PYPI_INDEX = 'https://pypi.org/simple';

/** @brief 支持的客户端 -> 其 skills 目录（相对 home 的路径片段）。 */
const CLIENT_SKILL_DIRS = {
  claude: ['.claude', 'skills'],
  codex: ['.codex', 'skills'],
  cursor: ['.cursor', 'skills'],
  openclaw: ['.openclaw', 'skills'],
  agents: ['.agents', 'skills'],
};

/** @brief 安装成功后用于 MCP 注册的优先顺序。 */
const CLIENT_PRIORITY = ['codex', 'claude', 'agents', 'openclaw', 'cursor'];

const EXIT_OK = 0;
const EXIT_FAILED = 1;
const EXIT_USAGE = 2;

const USAGE = `
用法: node install.js [选项]

选项:
  --target <列表>        装到指定客户端，逗号分隔: claude,codex,cursor,openclaw,agents,all
                         省略时只装到「已存在 skills 目录」的客户端，不会创建目录
  --install-deps         安装 Python 依赖（默认开启，兼容旧参数）
  --no-install-deps      不自动安装 Python 依赖
  --no-register-mcp      跳过 MCP 配置注册（默认会注册，覆盖前自动备份 .bak-时间戳）
  --force-reinstall      目标目录已存在且非本仓库检出的，先改名备份再安装（不删除）
  --allow-non-windows    允许在非 Windows 平台安装（仅开放格式能力可用）
  --dry-run              只打印计划，不写盘、不执行
  -h, --help             显示本帮助

退出码: 0 成功 / 1 有目标安装失败 / 2 用法或环境不允许
`.trim();

/** @brief 解析命令行；未知参数直接报错，避免拼写错误被静默忽略。 */
function parseArgs(argv) {
  const options = {
    targets: null,
    installDeps: true,
    registerMcp: true,
    forceReinstall: false,
    allowNonWindows: false,
    dryRun: false,
    help: false,
  };
  const known = Object.keys(CLIENT_SKILL_DIRS);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--target' || arg === '--targets') {
      const raw = argv[index + 1];
      if (!raw || raw.startsWith('-')) throw new Error(`${arg} 需要一个值`);
      index += 1;
      const names = raw.split(',').map(item => item.trim()).filter(Boolean);
      if (names.length === 0) throw new Error(`${arg} 不能为空`);
      if (names.includes('all')) {
        options.targets = known.slice();
        continue;
      }
      const unknown = names.filter(name => !known.includes(name));
      if (unknown.length > 0) {
        throw new Error(`未知客户端: ${unknown.join(', ')}（可用: ${known.join(', ')}, all）`);
      }
      options.targets = names;
    } else if (arg === '--install-deps') {
      options.installDeps = true;
    } else if (arg === '--no-install-deps') {
      options.installDeps = false;
    } else if (arg === '--no-register-mcp') {
      options.registerMcp = false;
    } else if (arg === '--force-reinstall') {
      options.forceReinstall = true;
    } else if (arg === '--allow-non-windows') {
      options.allowNonWindows = true;
    } else if (arg === '--dry-run') {
      options.dryRun = true;
    } else if (arg === '-h' || arg === '--help') {
      options.help = true;
    } else if (arg.startsWith('-')) {
      throw new Error(`未知参数: ${arg}`);
    }
  }
  return options;
}

/**
 * @brief 解析要安装到哪些客户端。
 * @details 显式 --target 时按请求返回（允许创建目录）；
 *          自动模式只返回**已存在** skills 目录的客户端，绝不创建。
 */
function selectTargets(homeDir, requested, exists = fs.existsSync) {
  const explicit = Array.isArray(requested) && requested.length > 0;
  const names = explicit ? requested : Object.keys(CLIENT_SKILL_DIRS);
  const selected = [];
  for (const client of names) {
    const skillsDir = path.join(homeDir, ...CLIENT_SKILL_DIRS[client]);
    if (explicit) {
      selected.push({ client, skillsDir, create: !exists(skillsDir) });
    } else if (exists(skillsDir)) {
      selected.push({ client, skillsDir, create: false });
    }
  }
  return selected;
}

/** @brief 非 Windows 平台守卫：默认拒绝，明确加 --allow-non-windows 才继续。 */
function assertPlatform(platform, allowNonWindows) {
  if (platform === 'win32') return null;
  if (allowNonWindows) {
    return `当前平台是 ${platform}：SolidWorks COM 相关能力不可用，仅开放格式（DXF/STEP 等）可尝试。`;
  }
  throw new Error(
    `当前平台是 ${platform}，SolidWorks COM 只在 Windows 上可用。`
    + '若只想用开放格式能力，请加 --allow-non-windows 重试。',
  );
}

/** @brief 归一化远端地址，用于判断目录是否由本仓库安装。 */
function normalizeRemote(url) {
  // @brief 先去尾部斜杠再摘 .git：顺序反过来会让 "...skill.git/" 漏掉后缀。
  return String(url || '')
    .trim()
    .replace(/\/+$/, '')
    .replace(/\.git$/, '')
    .toLowerCase();
}

/**
 * @brief 判断目标目录现状。
 * @returns {{state: 'absent'|'managed'|'foreign'|'foreign-remote', remote?: string}}
 *   absent         目标不存在，可直接安装
 *   managed        是来自本仓库的 git 检出，可安全 git pull
 *   foreign        存在但不是 git 目录（用户手放/解压），**不得删除**
 *   foreign-remote 是 git 仓库但远端不是本仓库，**不得删除**
 */
function inspectTarget(targetDir, readRemote, exists = fs.existsSync) {
  if (!exists(targetDir)) return { state: 'absent' };
  if (!exists(path.join(targetDir, '.git'))) return { state: 'foreign' };
  const remote = typeof readRemote === 'function' ? readRemote(targetDir) : '';
  if (!remote) return { state: 'foreign' };
  const state = normalizeRemote(remote) === normalizeRemote(REPO_URL) ? 'managed' : 'foreign-remote';
  return { state, remote };
}

/** @brief 备份目录名：同名 + .bak-时间戳。 */
function backupDirName(targetDir, stamp) {
  return `${targetDir}.bak-${stamp}`;
}

function runGit(args, cwd) {
  return execFileSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

function readRemoteUrl(targetDir) {
  try {
    return runGit(['config', '--get', 'remote.origin.url'], targetDir);
  } catch (error) {
    return '';
  }
}

/** @brief 找到 Python 3.10+ 的实际解释器路径，包括当前用户安装目录。 */
function detectPython(run = spawnSync, env = process.env) {
  const userPython = env.LOCALAPPDATA
    ? path.join(env.LOCALAPPDATA, 'Programs', 'Python', 'Python312', 'python.exe') : null;
  for (const candidate of [env.PYTHON, 'python', 'py', 'python3', userPython].filter(Boolean)) {
    const probe = run(candidate, ['-c', 'import sys; sys.exit(2) if sys.version_info < (3, 10) else print(sys.executable)'],
      { encoding: 'utf8', stdio: 'pipe', timeout: 5000 });
    if (probe.status === 0 && probe.stdout.trim()) return probe.stdout.trim();
  }
  return null;
}

/** @brief Windows 缺少 Python 时仅尝试当前用户的官方 winget 包。 */
function bootstrapPython(platform = process.platform, run = spawnSync, detect = detectPython) {
  if (platform !== 'win32') return null;
  const available = run('winget', ['--version'], { encoding: 'utf8', stdio: 'pipe', timeout: 10000 });
  if (available.status !== 0) return null;
  console.log('  📦 未找到 Python 3.10+，尝试通过 winget 为当前用户安装 Python 3.12...');
  const result = run('winget', ['install', '--id', 'Python.Python.3.12', '--exact', '--source', 'winget',
    '--scope', 'user', '--silent', '--disable-interactivity', '--accept-package-agreements', '--accept-source-agreements'],
  { stdio: 'inherit', timeout: 300000, windowsHide: true });
  return result.status === 0 ? detect() : null;
}

function timestamp() {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '');
}

/** @brief 浅克隆：只要工作树，不拉全部历史，减少目录体积。 */
function cloneInto(targetDir) {
  try {
    fs.mkdirSync(path.dirname(targetDir), { recursive: true });
    runGit(['clone', '--depth', '1', REPO_URL, targetDir]);
    return true;
  } catch (error) {
    console.error(`  ❌ git clone 失败: ${String(error.message).split('\n')[0]}`);
    console.error('  提示：需要本机可用的 git，以及对 GitHub 的网络访问。');
    return false;
  }
}

/** @brief 安装（或更新）单个客户端目录。返回 {ok, action, message}。 */
function installToDir(targetDir, options, stamp) {
  const current = inspectTarget(targetDir, readRemoteUrl);

  if (current.state === 'managed') {
    if (options.dryRun) {
      return { ok: true, action: 'pull', message: `[dry-run] git pull --ff-only ${targetDir}` };
    }
    try {
      runGit(['pull', '--ff-only'], targetDir);
      return { ok: true, action: 'pull', message: `已更新 ${targetDir}` };
    } catch (error) {
      // @brief 关键修复：更新失败只报告，绝不删除目录。用户可能在其中保留了自己的改动。
      return {
        ok: false,
        action: 'pull-failed',
        message: `更新失败（未改动任何文件）: ${targetDir}\n`
          + '    该目录由本仓库安装，但 git pull 未能快进。请进入该目录自行检查（git status / git log）；'
          + '确认无本地改动后可用 --force-reinstall 重装（旧目录会改名为 .bak-时间戳 保留）。',
      };
    }
  }

  if (current.state === 'foreign' || current.state === 'foreign-remote') {
    if (!options.forceReinstall) {
      const detail = current.state === 'foreign-remote' ? `远端为 ${current.remote}` : '不是 git 仓库';
      return {
        ok: false,
        action: 'refused',
        message: `已存在同名目录且不是本仓库的安装（${detail}）: ${targetDir}\n`
          + '    为避免覆盖你的文件，安装器不会删除它。请先移走或改名，'
          + '或加 --force-reinstall（旧目录会改名为 .bak-时间戳 保留）。',
      };
    }
    const backup = backupDirName(targetDir, stamp);
    if (options.dryRun) {
      return { ok: true, action: 'backup+clone', message: `[dry-run] 备份 ${targetDir} -> ${backup} 后重装` };
    }
    fs.renameSync(targetDir, backup);
    const cloned = cloneInto(targetDir);
    return {
      ok: cloned,
      action: 'backup+clone',
      message: cloned ? `已备份为 ${backup} 并重新安装` : `已备份为 ${backup}，但重新安装失败`,
    };
  }

  if (options.dryRun) return { ok: true, action: 'clone', message: `[dry-run] git clone --depth 1 -> ${targetDir}` };
  const cloned = cloneInto(targetDir);
  return { ok: cloned, action: 'clone', message: cloned ? `已安装 ${targetDir}` : `安装失败 ${targetDir}` };
}

function dependencyCommand(primaryDir) {
  return `cd "${primaryDir}" && python -m pip install -r requirements.txt -r mcp-server/requirements.txt`;
}

function installDependencies(primaryDir, detect = detectPython, bootstrap = bootstrapPython, run = spawnSync) {
  const python = detect() || bootstrap();
  if (!python) {
    console.log('  ⚠️  未找到 python，请手动执行:');
    console.log(`     ${dependencyCommand(primaryDir)}`);
    return { ok: false, python: null };
  }
  const args = ['-m', 'pip', 'install', '--no-input', '--disable-pip-version-check', '-r', 'requirements.txt', '-r', 'mcp-server/requirements.txt'];
  const virtualEnv = run(python, ['-c', 'import sys; print(int(sys.prefix != sys.base_prefix))'], { encoding: 'utf8', stdio: 'pipe', timeout: 5000 });
  if (virtualEnv.status === 0 && virtualEnv.stdout.trim() === '0') args.push('--user');
  let result = run(python, args, { cwd: primaryDir, stdio: 'inherit', timeout: 300000, windowsHide: true });
  if (result.status !== 0) {
    console.log('  ↻ 当前 pip 索引未完成安装，回退官方 PyPI 重试...');
    result = run(python, [...args, '--index-url', OFFICIAL_PYPI_INDEX], {
      cwd: primaryDir,
      stdio: 'inherit',
      timeout: 300000,
      windowsHide: true,
    });
  }
  if (result.status !== 0) {
    console.log('  ⚠️  依赖安装未成功，请手动执行:');
    console.log(`     ${dependencyCommand(primaryDir)}`);
    return { ok: false, python };
  }
  return { ok: true, python };
}

function registerMcp(installedDirs, options, python, run = spawnSync) {
  const ordered = CLIENT_PRIORITY
    .map(client => installedDirs.find(item => item.client === client))
    .filter(Boolean);
  const primary = ordered[0] || installedDirs[0];
  const registerScript = path.join(primary.targetDir, 'mcp-server', 'register_all_ai_mcp.js');
  if (!fs.existsSync(registerScript)) {
    console.log(`  ⚠️  未找到 MCP 注册脚本: ${registerScript}`);
    return false;
  }
  const args = [registerScript];
  if (python) args.push('--python', python);
  if (options.dryRun) {
    console.log(`  [dry-run] node ${args.join(' ')}`);
    return true;
  }
  console.log('  🔌 注册 MCP 配置（覆盖前自动备份 .bak-时间戳）...');
  const result = run('node', args, { stdio: 'inherit', timeout: 300000, windowsHide: true });
  if (result.status !== 0) {
    console.log('  ⚠️  MCP 自动注册未完全成功，可稍后手动执行:');
    console.log(`     node "${registerScript}"`);
    return false;
  }
  return true;
}

function main(argv) {
  let options;
  try {
    options = parseArgs(argv);
  } catch (error) {
    console.error(`❌ ${error.message}`);
    console.error(`\n${USAGE}`);
    return EXIT_USAGE;
  }
  if (options.help) {
    console.log(USAGE);
    return EXIT_OK;
  }

  const nodeMajor = Number.parseInt(process.versions.node.split('.')[0], 10);
  if (nodeMajor < MIN_NODE_MAJOR) {
    console.error(`❌ 需要 Node.js ${MIN_NODE_MAJOR}+，当前 ${process.versions.node}`);
    return EXIT_USAGE;
  }

  try {
    const platformNote = assertPlatform(process.platform, options.allowNonWindows);
    if (platformNote) console.log(`⚠️  ${platformNote}`);
  } catch (error) {
    console.error(`❌ ${error.message}`);
    return EXIT_USAGE;
  }

  const homeDir = os.homedir();
  const targets = selectTargets(homeDir, options.targets);
  console.log(`目标客户端: ${targets.length === 0 ? '（无）' : targets.map(item => item.client).join(', ')}`);
  if (options.dryRun) console.log('模式: dry-run（不会写入任何文件）');

  if (targets.length === 0) {
    console.error('\n❌ 没有检测到任何 skills 目录，且安装器不会替你创建。');
    console.error('   请显式指定客户端后重试，例如:');
    console.error('     node install.js --target claude');
    console.error(`   （支持: ${Object.keys(CLIENT_SKILL_DIRS).join(', ')}, all）`);
    return EXIT_USAGE;
  }

  const stamp = timestamp();
  const installedDirs = [];
  const failures = [];
  for (const target of targets) {
    const targetDir = path.join(target.skillsDir, SKILL_NAME);
    console.log(`\n📁 ${target.client}: ${targetDir}`);
    const result = installToDir(targetDir, options, stamp);
    console.log(`  ${result.ok ? '✅' : '❌'} ${result.message}`);
    if (result.ok) {
      installedDirs.push({ client: target.client, targetDir });
    } else {
      failures.push({ client: target.client, message: result.message });
    }
  }

  if (installedDirs.length > 0 && !options.dryRun) {
    const primaryDir = installedDirs[0].targetDir;
    let python = null;
    if (options.installDeps) {
      console.log('\n📦 安装 Python 依赖...');
      const result = installDependencies(primaryDir);
      python = result.python;
      if (!result.ok) failures.push({ client: 'Python 依赖', message: '依赖安装未成功' });
    } else {
      console.log('\n📦 已关闭 Python 依赖自动安装，可手动执行:');
      console.log(`   ${dependencyCommand(primaryDir)}`);
    }
    if (options.registerMcp) {
      console.log('\n🔌 MCP 注册');
      if (!registerMcp(installedDirs, options, python)) failures.push({ client: 'MCP 注册', message: '自动注册未完成' });
    }
  }

  console.log(`\n结果: 成功 ${installedDirs.length} / 目标 ${targets.length}`);
  if (failures.length > 0) {
    console.error('未完成:');
    failures.forEach(item => console.error(`  - ${item.client}`));
    return EXIT_FAILED;
  }
  return EXIT_OK;
}

module.exports = {
  CLIENT_SKILL_DIRS,
  REPO_URL,
  MIN_NODE_MAJOR,
  parseArgs,
  selectTargets,
  assertPlatform,
  normalizeRemote,
  inspectTarget,
  backupDirName,
  installToDir,
  detectPython,
  bootstrapPython,
  installDependencies,
  registerMcp,
};

if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}
