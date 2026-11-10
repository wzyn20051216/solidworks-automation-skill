const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("../apps/workbench-ui/node_modules/playwright");
const { waitUntil, firstPage } = require("./release-portable-e2e.cjs");

const repo = path.resolve(__dirname, "..");
const output = path.join(repo, "release-output");
const { version } = require("../apps/workbench-ui/src-tauri/tauri.conf.json");
const previous = "2.1.0";
const oldInstallerSha = "7bec698b17f71dd3805b143f0f789612bf2ae3385513d5ff5f85dc8efb09ce19";
const candidate = path.join(output, `CAD-Studio-${version}-Setup-x64.exe`);
const namespace = "release-upgrade-e2e";
const fixture = { project: "Upgrade fixture", settings: { units: "mm" } };

function run(program, args, options = {}) {
  const result = spawnSync(program, args, {
    encoding: "utf8", windowsHide: true, timeout: 120_000, ...options,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${path.basename(program)} failed: ${result.stderr}`);
  return result;
}

function install(installer, folder) {
  // NSIS expects /D to be the last argument and its path to be unquoted.
  run(installer, ["/S", `/D=${folder}`], { windowsVerbatimArguments: true });
  assert(fs.existsSync(path.join(folder, "cad-studio.exe")), "installed app missing");
}

async function withApp(folder, scratch, expectedVersion, check) {
  const port = 9234;
  const app = spawn(path.join(folder, "cad-studio.exe"), [], {
    cwd: folder,
    windowsHide: true,
    env: {
      ...process.env,
      CAD_STUDIO_QUEUE_DIR: path.join(scratch, "queue"),
      WEBVIEW2_USER_DATA_FOLDER: fs.mkdtempSync(path.join(scratch, "webview-")),
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}`,
    },
  });
  let launchError;
  app.on("error", (error) => { launchError = error; });
  app.stdout.resume();
  app.stderr.resume();
  const health = () => launchError?.message || (app.exitCode === null ? null : `app exited ${app.exitCode}`);
  const cdp = `http://127.0.0.1:${port}`;
  let browser;
  try {
    await waitUntil(async () => (await fetch(`${cdp}/json/version`, { signal: AbortSignal.timeout(1000) })).ok, "installed app CDP", 60_000, health);
    browser = await chromium.connectOverCDP(cdp);
    const page = await waitUntil(() => firstPage(browser), "installed app page", 60_000, health);
    await page.waitForFunction(() => typeof window.__TAURI_INTERNALS__?.invoke === "function");
    const invoke = (command, args = {}) => page.evaluate(
      ([name, payload]) => window.__TAURI_INTERNALS__.invoke(name, payload),
      [command, args],
    );
    assert.equal(await invoke("plugin:app|version"), expectedVersion);
    if (expectedVersion === version) {
      await page.getByText("LM Studio 本地问答与任务规划", { exact: true }).waitFor({ timeout: 20_000 });
    }
    await check(invoke);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (app.pid && app.exitCode === null) {
      app.kill();
      await waitUntil(() => app.exitCode !== null || app.signalCode, "installed app stop", 10_000);
    }
  }
}

function verifyMissingUv(scratch) {
  const bundle = path.join(output, `SolidWorks-Automation-Skill-${version}.mcpb`);
  const bundleDir = path.join(scratch, "bundle");
  run("python", ["-m", "zipfile", "-e", bundle, bundleDir]);
  const manifest = JSON.parse(fs.readFileSync(path.join(bundleDir, "manifest.json"), "utf8"));
  assert.equal(manifest.version, version);
  const config = manifest.server.mcp_config;
  assert.equal(config.command, "powershell.exe");
  const system32 = path.join(process.env.SystemRoot, "System32");
  const emptyProfile = fs.mkdtempSync(path.join(scratch, "no-uv-"));
  const result = spawnSync(
    path.join(system32, "WindowsPowerShell", "v1.0", "powershell.exe"),
    config.args.map((arg) => arg.replace("${__dirname}", bundleDir)),
    {
      cwd: emptyProfile, encoding: "utf8", windowsHide: true, timeout: 20_000,
      env: { ...process.env, PATH: system32, USERPROFILE: emptyProfile },
    },
  );
  if (result.error) throw result.error;
  assert.equal(result.status, 127, result.stderr);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /winget install --id astral-sh\.uv -e/);
  assert.match(result.stderr, /exit and reopen your MCP client/);
  console.log("Built MCPB: absent uv returns actionable guidance on stderr (exit 127).");
}

async function main() {
  assert(process.platform === "win32" && process.env.GITHUB_ACTIONS === "true"
    && process.env.RUNNER_ENVIRONMENT === "github-hosted", "Use a disposable GitHub-hosted Windows runner.");
  const scratch = fs.mkdtempSync(path.join(process.env.RUNNER_TEMP, "cad-release-"));
  const folder = path.join(scratch, "CAD Studio");
  verifyMissingUv(scratch);
  assert(!fs.existsSync(folder));
  install(candidate, folder);
  await withApp(folder, scratch, version, async (invoke) => {
    assert.equal(await invoke("read_app_store", { namespace }), null);
  });
  run(path.join(folder, "uninstall.exe"), ["/S"]);
  console.log(`Fresh installation and startup of ${version}: PASS.`);

  const download = await fetch(
    `https://github.com/wzyn20051216/solidworks-automation-skill/releases/download/v${previous}/CAD-Studio-${previous}-Setup-x64.exe`,
    { signal: AbortSignal.timeout(60_000) },
  );
  assert(download.ok, `published previous installer HTTP ${download.status}`);
  const bytes = Buffer.from(await download.arrayBuffer());
  assert.equal(createHash("sha256").update(bytes).digest("hex"), oldInstallerSha);
  const oldInstaller = path.join(scratch, `CAD-Studio-${previous}-Setup-x64.exe`);
  fs.writeFileSync(oldInstaller, bytes, { flag: "wx" });
  install(oldInstaller, folder);
  await withApp(folder, scratch, previous, async (invoke) => {
    await invoke("write_app_store", { namespace, payload: fixture });
  });
  install(candidate, folder);
  await withApp(folder, scratch, version, async (invoke) => {
    assert.deepEqual(await invoke("read_app_store", { namespace }), fixture);
  });
  run(path.join(folder, "uninstall.exe"), ["/S"]);
  console.log(`Published ${previous} → ${version}: in-place upgrade, application data and startup verified.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
