/**
 * @brief 安装器的安全边界测试（2026-10-28 重写后新增）。
 *
 * 锁定三条不可回退的行为：
 *   1. 目标目录已存在且不是本仓库检出时，**拒绝安装且不删除任何文件**；
 *   2. 自动模式只装到已存在的 skills 目录，**绝不凭空创建**目录；
 *   3. 非 Windows 平台默认拒绝。
 *
 * 全部用例不访问网络：涉及 clone/pull 的分支只用 dry-run 或注入的判定函数验证。
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  REPO_URL,
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
} = require('../install.js');

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'install-safety-'));
}

// ---------------------------------------------------------------- 参数解析

test('默认参数：自动模式、安装依赖、会注册 MCP，可显式关闭依赖安装', () => {
  const options = parseArgs([]);
  assert.equal(options.targets, null);
  assert.equal(options.installDeps, true);
  assert.equal(parseArgs(['--no-install-deps']).installDeps, false);
  assert.equal(options.registerMcp, true);
  assert.equal(options.forceReinstall, false);
  assert.equal(options.dryRun, false);
});

test('--target 解析单个与 all', () => {
  assert.deepEqual(parseArgs(['--target', 'claude']).targets, ['claude']);
  assert.deepEqual(parseArgs(['--target', 'claude,codex']).targets, ['claude', 'codex']);
  const all = parseArgs(['--target', 'all']).targets;
  assert.ok(all.includes('claude') && all.includes('cursor') && all.length >= 5);
});

test('未知客户端、未知参数、缺值都直接报错', () => {
  assert.throws(() => parseArgs(['--target', 'vscode']), /未知客户端/);
  assert.throws(() => parseArgs(['--nope']), /未知参数/);
  assert.throws(() => parseArgs(['--target']), /需要一个值/);
  assert.throws(() => parseArgs(['--target', '--dry-run']), /需要一个值/);
});

test('只选择可运行的 Python 3.10+ 并返回解释器路径', () => {
  const calls = [];
  const run = (name, args) => {
    calls.push([name, args]);
    return name === 'py' ? { status: 0, stdout: 'C:\\Python312\\python.exe\n' } : { status: 1, stdout: '' };
  };
  assert.equal(detectPython(run, {}), 'C:\\Python312\\python.exe');
  assert.ok(calls[0][1].join(' ').includes('sys.version_info < (3, 10)'));
});

test('缺少 Python 时只使用用户级官方 winget 包，失败不会假装成功', () => {
  const calls = [];
  const run = (name, args) => { calls.push([name, args]); return { status: 0 }; };
  assert.equal(bootstrapPython('win32', run, () => 'C:\\Python312\\python.exe'), 'C:\\Python312\\python.exe');
  assert.ok(calls[1][1].includes('Python.Python.3.12'));
  assert.ok(calls[1][1].includes('user'));
  assert.equal(bootstrapPython('win32', () => ({ status: 1 }), () => 'unexpected'), null);
});

test('依赖安装使用用户目录并准确报告失败', () => {
  const calls = [];
  const run = (name, args) => {
    calls.push([name, args]);
    return args.includes('-c') ? { status: 0, stdout: '0\n' } : { status: 1 };
  };
  const result = installDependencies('C:\\skill', () => 'C:\\Python312\\python.exe', () => null, run);
  assert.equal(result.ok, false);
  assert.ok(calls[1][1].includes('--user'));
  assert.ok(calls[1][1].includes('--no-input'));
  assert.ok(calls[2][1].includes('--index-url'));
  assert.ok(calls[2][1].includes('https://pypi.org/simple'));
});

test('MCP 注册复用已选择的 Python，失败时返回失败且不重复安装依赖', () => {
  const root = tempDir();
  fs.mkdirSync(path.join(root, 'mcp-server'));
  fs.writeFileSync(path.join(root, 'mcp-server', 'register_all_ai_mcp.js'), '');
  const calls = [];
  const run = (name, args) => { calls.push([name, args]); return { status: 1 }; };
  const ok = registerMcp([{ client: 'codex', targetDir: root }], { installDeps: true, dryRun: false }, 'C:\\Python312\\python.exe', run);
  assert.equal(ok, false);
  assert.ok(calls[0][1].includes('--python'));
  assert.ok(!calls[0][1].includes('--install-dependencies'));
});

// ---------------------------------------------------------------- 目标选择

test('自动模式只选已存在的目录，绝不创建', () => {
  const existing = path.join('home', '.claude', 'skills');
  const targets = selectTargets('home', null, candidate => candidate === existing);
  assert.equal(targets.length, 1);
  assert.equal(targets[0].client, 'claude');
  assert.equal(targets[0].create, false);
});

test('自动模式一个都没检测到就返回空（不再 bootstrap 目录）', () => {
  assert.deepEqual(selectTargets('home', null, () => false), []);
});

test('显式 --target 允许创建并标记 create', () => {
  const targets = selectTargets('home', ['cursor'], () => false);
  assert.equal(targets.length, 1);
  assert.equal(targets[0].client, 'cursor');
  assert.equal(targets[0].create, true);
});

// ---------------------------------------------------------------- 平台守卫

test('Windows 直接放行', () => {
  assert.equal(assertPlatform('win32', false), null);
});

test('非 Windows 默认拒绝，加 flag 才放行并给出限制说明', () => {
  assert.throws(() => assertPlatform('linux', false), /只在 Windows 上可用/);
  const note = assertPlatform('linux', true);
  assert.match(note, /仅开放格式/);
});

// ---------------------------------------------------------------- 目录判定

test('远端地址归一化忽略 .git 与尾斜杠和大小写', () => {
  const expected = normalizeRemote(REPO_URL);
  assert.equal(normalizeRemote(`${REPO_URL}/`), expected);
  assert.equal(normalizeRemote('https://github.com/WZYN20051216/solidworks-automation-skill'), expected);
  assert.notEqual(normalizeRemote('https://github.com/other/repo.git'), expected);
});

test('inspectTarget 区分 absent / foreign / managed / foreign-remote', () => {
  const root = tempDir();
  const owned = path.join(root, 'owned');
  fs.mkdirSync(path.join(owned, '.git'), { recursive: true });
  const plain = path.join(root, 'plain');
  fs.mkdirSync(plain, { recursive: true });

  assert.equal(inspectTarget(path.join(root, 'missing'), null).state, 'absent');
  assert.equal(inspectTarget(plain, null).state, 'foreign');
  assert.equal(inspectTarget(owned, () => REPO_URL).state, 'managed');
  assert.equal(inspectTarget(owned, () => 'https://github.com/other/repo.git').state, 'foreign-remote');
  assert.equal(inspectTarget(owned, () => '').state, 'foreign');
});

test('备份目录名带时间戳后缀', () => {
  assert.equal(backupDirName('/x/solidworks-automation', '20261028T091500'),
    '/x/solidworks-automation.bak-20261028T091500');
});

// ---------------------------------------------------------------- 拒绝覆盖（核心回归）

test('目标是非 git 目录时拒绝安装，且不改动任何文件', () => {
  const root = tempDir();
  const target = path.join(root, 'solidworks-automation');
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, 'my-local-notes.md'), 'hand written', 'utf8');

  const result = installToDir(target, { dryRun: false, forceReinstall: false }, 'stamp');

  assert.equal(result.ok, false);
  assert.equal(result.action, 'refused');
  assert.match(result.message, /不会删除/);
  assert.ok(fs.existsSync(path.join(target, 'my-local-notes.md')), '用户文件必须原样保留');
});

test('--force-reinstall 在 dry-run 下给出备份计划，同样不动文件', () => {
  const root = tempDir();
  const target = path.join(root, 'solidworks-automation');
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, 'keep.txt'), 'x', 'utf8');

  const result = installToDir(target, { dryRun: true, forceReinstall: true }, 'stamp');

  assert.equal(result.ok, true);
  assert.equal(result.action, 'backup+clone');
  assert.match(result.message, /\.bak-stamp/);
  assert.ok(fs.existsSync(path.join(target, 'keep.txt')));
});

test('目标不存在时 dry-run 只报告计划，不创建目录', () => {
  const root = tempDir();
  const target = path.join(root, 'solidworks-automation');

  const result = installToDir(target, { dryRun: true, forceReinstall: false }, 'stamp');

  assert.equal(result.ok, true);
  assert.equal(result.action, 'clone');
  assert.equal(fs.existsSync(target), false);
});
