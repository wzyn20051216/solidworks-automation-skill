const { chromium } = require("../apps/workbench-ui/node_modules/playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const repo = path.resolve(__dirname, "..");
const version = JSON.parse(fs.readFileSync(path.join(repo, "apps", "workbench-ui", "src-tauri", "tauri.conf.json"), "utf8")).version;
const portableRoot = process.env.CAD_STUDIO_PORTABLE_ROOT
  || path.join(repo, "release-output", `CAD-Studio-${version}-Windows-x64`);
const executable = path.join(portableRoot, "CAD Studio.exe");
const isolatedHome = path.join(repo, "release-output", "e2e-home");
const queue = path.join(repo, "release-output", "e2e-queue");
const webviewData = path.join(repo, "release-output", "e2e-webview2");

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitUntil(check, label, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch {}
    await sleep(250);
  }
  throw new Error(`timeout: ${label}`);
}

async function main() {
  if (!fs.existsSync(executable)) throw new Error(`便携版程序不存在: ${executable}`);
  fs.rmSync(isolatedHome, { recursive: true, force: true });
  fs.rmSync(queue, { recursive: true, force: true });
  fs.rmSync(webviewData, { recursive: true, force: true });
  fs.mkdirSync(isolatedHome, { recursive: true });
  fs.mkdirSync(queue, { recursive: true });

  const app = spawn(executable, [], {
    cwd: portableRoot,
    env: {
      ...process.env,
      CODEX_HOME: path.join(isolatedHome, ".codex"),
      CAD_STUDIO_QUEUE_DIR: queue,
      WEBVIEW2_USER_DATA_FOLDER: webviewData,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9227",
    },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitUntil(async () => {
      try {
        return (await fetch("http://127.0.0.1:9227/json/version")).ok;
      } catch {
        return false;
      }
    }, "portable Tauri CDP start");
    browser = await chromium.connectOverCDP("http://127.0.0.1:9227");
    const page = browser.contexts()[0].pages()[0];
    await page.waitForTimeout(2_000);
    const invoke = (command, args = {}) => page.evaluate(
      ([activeCommand, activeArgs]) => window.__TAURI_INTERNALS__.invoke(activeCommand, activeArgs),
      [command, args],
    );
    const runtime = await invoke("runtime_health");
    const normalizedRoot = String(runtime.skillRoot || "").replace(/^\\\\\?\\/, "").replace(/\\/g, "/").toLowerCase();
    const expectedRoot = path.join(portableRoot, "skill").replace(/\\/g, "/").toLowerCase();
    if (normalizedRoot !== expectedRoot) {
      throw new Error(`便携版没有使用同目录 skill: actual=${runtime.skillRoot}, expected=${expectedRoot}`);
    }
    for (const required of [
      "SKILL.md",
      "apps/desktop/cad_workbench/queue_worker.py",
      "apps/desktop/cad_workbench/schemas/automation_job.schema.json",
      "examples/08_mini_fan_motion_assembly.py",
      "mcp-server/server.py",
      "mcp-server/register_all_ai_mcp.ps1",
      "subskills/autocad-automation/SKILL.md",
    ]) {
      if (!fs.existsSync(path.join(portableRoot, "skill", ...required.split("/")))) {
        throw new Error(`便携版缺少资源: ${required}`);
      }
    }
    const started = await invoke("start_worker", { repoPath: "", enableCodex: false, codexFullAccess: false });
    if (!started.running || !started.pid) throw new Error(`内置 worker 启动失败: ${JSON.stringify(started)}`);
    const stopped = await invoke("stop_worker");
    if (stopped.running) throw new Error(`worker 未停止: ${JSON.stringify(stopped)}`);
    console.log(JSON.stringify({ skillRoot: runtime.skillRoot, python: runtime.python, workerStarted: started, workerStopped: stopped }, null, 2));
  } finally {
    if (browser) await browser.close().catch(() => {});
    app.kill("SIGKILL");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
