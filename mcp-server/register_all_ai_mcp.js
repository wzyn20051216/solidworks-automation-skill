#!/usr/bin/env node

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const DEFAULT_CLIENTS = ['codex', 'claude-code', 'claude-desktop', 'cursor', 'windsurf'];

function parseArgs(argv) {
  const options = {
    name: 'solidworks',
    server: path.join(__dirname, 'server.py'),
    python: process.env.PYTHON || 'python',
    clients: DEFAULT_CLIENTS,
    installDependencies: false,
    backup: true,
    createMissingConfig: true,
    strict: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => {
      index += 1;
      if (index >= argv.length) {
        throw new Error(`Missing value for ${arg}`);
      }
      return argv[index];
    };

    if (arg === '--name') options.name = next();
    else if (arg === '--server') options.server = next();
    else if (arg === '--python') options.python = next();
    else if (arg === '--clients') options.clients = parseClientList(next());
    else if (arg === '--install-dependencies') options.installDependencies = true;
    else if (arg === '--no-backup') options.backup = false;
    else if (arg === '--only-existing-configs') options.createMissingConfig = false;
    else if (arg === '--strict') options.strict = true;
    else if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }

  options.server = path.resolve(options.server);
  return options;
}

function parseClientList(value) {
  if (!value || value.toLowerCase() === 'all') {
    return DEFAULT_CLIENTS;
  }

  const aliases = {
    claude: ['claude-code', 'claude-desktop'],
    all: DEFAULT_CLIENTS,
  };
  const result = [];
  for (const rawName of value.split(',')) {
    const name = rawName.trim().toLowerCase();
    const mapped = aliases[name] || [name];
    for (const client of mapped) {
      if (!DEFAULT_CLIENTS.includes(client)) {
        throw new Error(`Unsupported client: ${client}`);
      }
      if (!result.includes(client)) {
        result.push(client);
      }
    }
  }
  return result;
}

function printHelp() {
  console.log(`
Usage:
  node register_all_ai_mcp.js [options]

Options:
  --name <name>                 MCP server name. Default: solidworks
  --server <path>               Absolute or relative path to server.py
  --python <command-or-path>    Python command or executable path
  --clients <list|all>          Comma list: codex,claude-code,claude-desktop,cursor,windsurf
  --install-dependencies        Install mcp-server/requirements.txt first
  --only-existing-configs       Do not create missing JSON config directories
  --no-backup                   Do not create .bak files before JSON writes
  --strict                      Exit non-zero when any selected client fails
`);
}

function run(command, args, options = {}) {
  const useShell = options.shell !== undefined
    ? options.shell
    : !(path.isAbsolute(command) && fs.existsSync(command));
  const result = spawnSync(command, args, {
    cwd: options.cwd || process.cwd(),
    encoding: 'utf8',
    shell: useShell,
    stdio: options.quiet ? 'pipe' : 'inherit',
  });

  return {
    status: result.status === null ? 1 : result.status,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
    error: result.error,
  };
}

function commandExists(command) {
  if (path.isAbsolute(command) && fs.existsSync(command)) {
    return true;
  }

  const probe = process.platform === 'win32'
    ? spawnSync('where.exe', [command], { encoding: 'utf8', stdio: 'pipe' })
    : spawnSync('command', ['-v', command], { encoding: 'utf8', stdio: 'pipe', shell: true });
  return probe.status === 0;
}

function resolvePython(candidate) {
  const candidates = [
    candidate,
    process.env.PYTHON,
    'python',
    'py',
    'python3',
  ].filter(Boolean);

  const seen = new Set();
  for (const command of candidates) {
    if (seen.has(command)) continue;
    seen.add(command);

    const args = command === 'py'
      ? ['-3', '-c', 'import sys; print(sys.executable)']
      : ['-c', 'import sys; print(sys.executable)'];
    const result = run(command, args, { quiet: true });
    if (result.status === 0) {
      const executable = result.stdout.trim();
      return executable || command;
    }
  }

  throw new Error('Python was not found. Install Python 3.8+ and retry.');
}

function ensureServerReady(options, pythonCommand) {
  if (!fs.existsSync(options.server)) {
    throw new Error(`MCP server not found: ${options.server}`);
  }

  const requirementsPath = path.join(path.dirname(options.server), 'requirements.txt');
  if (options.installDependencies) {
    if (!fs.existsSync(requirementsPath)) {
      throw new Error(`Requirements file not found: ${requirementsPath}`);
    }
    console.log('Installing Python dependencies...');
    const pip = run(pythonCommand, ['-m', 'pip', 'install', '-r', requirementsPath]);
    if (pip.status !== 0) {
      throw new Error('Failed to install Python dependencies.');
    }
  }

  console.log('Checking MCP server syntax...');
  const check = run(pythonCommand, ['-m', 'py_compile', options.server]);
  if (check.status !== 0) {
    throw new Error('MCP server syntax check failed.');
  }
}

function registerCodex(options, pythonCommand) {
  if (!commandExists('codex')) {
    return skipped('codex', 'codex command not found');
  }

  const exists = run('codex', ['mcp', 'get', options.name], { quiet: true }).status === 0;
  if (exists) {
    const remove = run('codex', ['mcp', 'remove', options.name], { quiet: true });
    if (remove.status !== 0) {
      return failed('codex', 'failed to remove existing server');
    }
  }

  const add = run('codex', ['mcp', 'add', options.name, '--', pythonCommand, options.server], { quiet: true });
  if (add.status !== 0) {
    return failed('codex', add.stderr.trim() || 'codex mcp add failed');
  }

  return installed('codex', 'registered with codex mcp add');
}

function registerClaudeCode(options, pythonCommand) {
  if (!commandExists('claude')) {
    return skipped('claude-code', 'claude command not found');
  }

  const exists = run('claude', ['mcp', 'get', options.name], { quiet: true }).status === 0;
  if (exists) {
    const remove = run('claude', ['mcp', 'remove', options.name], { quiet: true });
    if (remove.status !== 0) {
      return failed('claude-code', 'failed to remove existing server');
    }
  }

  const add = run('claude', ['mcp', 'add', '--scope', 'user', options.name, '--', pythonCommand, options.server], { quiet: true });
  if (add.status !== 0) {
    return failed('claude-code', add.stderr.trim() || 'claude mcp add failed');
  }

  return installed('claude-code', 'registered with claude mcp add --scope user');
}

function registerJsonClient(client, configPath, options, pythonCommand) {
  const dir = path.dirname(configPath);
  if (!fs.existsSync(configPath) && !options.createMissingConfig && !fs.existsSync(dir)) {
    return skipped(client, `config directory not found: ${dir}`);
  }

  fs.mkdirSync(dir, { recursive: true });

  let config = {};
  if (fs.existsSync(configPath)) {
    const raw = fs.readFileSync(configPath, 'utf8').trim();
    if (raw) {
      try {
        config = JSON.parse(raw);
      } catch (error) {
        return failed(client, `invalid JSON: ${configPath}`);
      }
    }

    if (options.backup) {
      const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
      fs.copyFileSync(configPath, `${configPath}.bak-${stamp}`);
    }
  }

  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    return failed(client, `config root is not an object: ${configPath}`);
  }

  config.mcpServers = config.mcpServers && typeof config.mcpServers === 'object'
    ? config.mcpServers
    : {};
  config.mcpServers[options.name] = {
    command: pythonCommand,
    args: [options.server],
  };

  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  return installed(client, `updated ${configPath}`);
}

function getClientConfigPath(client) {
  const home = os.homedir();
  const appData = process.env.APPDATA || path.join(home, 'AppData', 'Roaming');

  if (client === 'claude-desktop') {
    if (process.platform === 'darwin') {
      return path.join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json');
    }
    if (process.platform === 'win32') {
      return path.join(appData, 'Claude', 'claude_desktop_config.json');
    }
    return path.join(home, '.config', 'Claude', 'claude_desktop_config.json');
  }

  if (client === 'cursor') {
    return path.join(home, '.cursor', 'mcp.json');
  }

  if (client === 'windsurf') {
    return path.join(home, '.codeium', 'windsurf', 'mcp_config.json');
  }

  throw new Error(`No JSON config path for ${client}`);
}

function installed(client, detail) {
  return { client, status: 'installed', detail };
}

function skipped(client, detail) {
  return { client, status: 'skipped', detail };
}

function failed(client, detail) {
  return { client, status: 'failed', detail };
}

function printResult(result) {
  const icon = result.status === 'installed' ? 'OK'
    : result.status === 'skipped' ? 'SKIP'
      : 'FAIL';
  console.log(`[${icon}] ${result.client}: ${result.detail}`);
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const pythonCommand = resolvePython(options.python);

  console.log(`MCP server: ${options.server}`);
  console.log(`Python: ${pythonCommand}`);

  ensureServerReady(options, pythonCommand);

  const results = [];
  for (const client of options.clients) {
    if (client === 'codex') {
      results.push(registerCodex(options, pythonCommand));
    } else if (client === 'claude-code') {
      results.push(registerClaudeCode(options, pythonCommand));
    } else {
      results.push(registerJsonClient(client, getClientConfigPath(client), options, pythonCommand));
    }
  }

  console.log('\nRegistration summary:');
  results.forEach(printResult);

  const failedCount = results.filter(result => result.status === 'failed').length;
  const installedCount = results.filter(result => result.status === 'installed').length;
  if ((options.strict && failedCount > 0) || installedCount === 0) {
    process.exitCode = 1;
  }
}

try {
  main();
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exit(1);
}
