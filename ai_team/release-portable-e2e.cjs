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
const releaseOutput = path.resolve(repo, "release-output");

/** @brief 限制端到端测试清理范围，避免误删工作区外目录。 */
function assertSafeTestPath(target) {
  const resolved = path.resolve(target);
  if (path.dirname(resolved) !== releaseOutput) throw new Error(`拒绝清理测试目录: ${resolved}`);
}

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

/** @brief 有界等待就绪；程序退出或无法启动时立即报告，保留最后的连接错误。 */
async function waitUntil(check, label, timeout = 90_000, health = () => null) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    const failure = health();
    if (failure) throw new Error(`${label}: ${failure}`);
    try {
      const value = await check();
      if (value) return value;
    } catch (error) { lastError = error; }
    await sleep(250);
  }
  throw new Error(`timeout: ${label}${lastError ? `; last error: ${lastError.message}` : ""}`);
}

/** @brief 选取首个可交互 page；CDP 刚连上时 contexts() 可能为空或 page 尚未注册。 */
function firstPage(browser) {
  for (const context of browser.contexts()) {
    const [candidate] = context.pages();
    if (candidate) return candidate;
  }
  return null;
}

async function main() {
  if (!fs.existsSync(executable)) throw new Error(`便携版程序不存在: ${executable}`);
  [isolatedHome, queue, webviewData].forEach(assertSafeTestPath);
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
    stdio: ["ignore", "pipe", "pipe"],
  });
  let launchError;
  let output = "";
  const record = (data) => { output = (output + data.toString("utf8")).slice(-32_768); };
  app.stdout.on("data", record);
  app.stderr.on("data", record);
  app.on("error", (error) => { launchError = error; });
  const health = () => launchError?.message
    || (app.exitCode !== null ? `process exited with code ${app.exitCode}` : null)
    || (app.signalCode ? `process exited with signal ${app.signalCode}` : null);
  let browser;
  try {
    await waitUntil(async () => {
      return (await fetch("http://127.0.0.1:9227/json/version", { signal: AbortSignal.timeout(1_000) })).ok;
    }, "portable Tauri CDP start", 90_000, health);
    browser = await chromium.connectOverCDP("http://127.0.0.1:9227");
    // @brief CDP 端口就绪时 WebView2 的 page target 可能尚未注册；
    //        必须先有界等待首个 page 出现，否则 contexts()[0].pages()[0] 为 undefined。
    const page = await waitUntil(() => firstPage(browser), "portable Tauri page", 60_000, health);
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
      "scripts/sw_live_preview.py",
      "examples/08_mini_fan_motion_assembly.py",
      "mcp-server/server.py",
      "mcp-server/register_all_ai_mcp.ps1",
      "subskills/autocad-automation/SKILL.md",
    ]) {
      if (!fs.existsSync(path.join(portableRoot, "skill", ...required.split("/")))) {
        throw new Error(`便携版缺少资源: ${required}`);
      }
    }
    const previewJob = { id: "job-preview-smoke", runId: "run-preview-smoke" };
    const previewBytes = async (args) => page.evaluate(async (input) => {
      const response = await window.__TAURI_INTERNALS__.invoke("read_solidworks_preview", input);
      return Array.from(new Uint8Array(response));
    }, args);
    const jobFile = path.join(queue, `${previewJob.id}.json`);
    const frameDir = path.join(queue, "solidworks-live", previewJob.id);
    const frameFile = path.join(frameDir, `${previewJob.runId}.png`);
    const fixture = {
      ...previewJob,
      schemaVersion: "1.0",
      kind: "agent_task",
      title: "SolidWorks 预览验收",
      projectId: (await invoke("read_app_store", { namespace: "settings" }))?.activeProjectId ?? "project-default",
      progress: 10,
      updatedAt: new Date().toISOString(),
      status: "running",
      uiConfig: { cadRuntime: { application: "solidworks", localCadAutomation: true } },
    };
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR6QAAAAASUVORK5CYII=", "base64");
    fs.writeFileSync(jobFile, JSON.stringify(fixture));
    fs.mkdirSync(frameDir, { recursive: true });
    fs.writeFileSync(frameFile, png);
    try {
      const preview = page.getByRole("region", { name: "SolidWorks 实时预览" });
      const rendered = preview.getByRole("img");
      await rendered.waitFor({ state: "visible", timeout: 15_000 });
      await waitUntil(() => rendered.evaluate((img) => img.naturalWidth > 0), "SolidWorks preview image decoded", 5_000, health);
      if (!Buffer.from(await previewBytes(previewJob)).equals(png)) {
        throw new Error("SolidWorks 实时预览没有返回当前任务的二进制帧");
      }
      if ((await previewBytes({ ...previewJob, runId: "run-preview-old" })).length) {
        throw new Error("SolidWorks 实时预览接受了错误的运行 ID");
      }
      fs.unlinkSync(frameFile);
      if ((await previewBytes(previewJob)).length) {
        throw new Error("SolidWorks 实时预览在帧清理后返回了旧数据");
      }
      await preview.getByRole("status").filter({ hasText: "预览不可用" }).waitFor({ state: "visible", timeout: 5_000 });
    } finally {
      fs.rmSync(frameFile, { force: true });
      fs.rmSync(jobFile, { force: true });
    }
    const started = await invoke("start_worker", { repoPath: "", enableCodex: false, codexFullAccess: false });
    if (!started.running || !started.pid) throw new Error(`内置 worker 启动失败: ${JSON.stringify(started)}`);
    const stopped = await invoke("stop_worker");
    if (stopped.running) throw new Error(`worker 未停止: ${JSON.stringify(stopped)}`);
    console.log(JSON.stringify({
      skillRoot: runtime.skillRoot,
      python: runtime.python,
      solidworksPreview: { imageDecoded: true, wrongRunRejected: true, unavailableOnRemoval: true },
      workerStarted: started,
      workerStopped: stopped,
    }, null, 2));
  } catch (error) {
    // @brief 只记录启动状态和自身输出，不转储含签名密钥的进程环境。
    fs.writeFileSync(path.join(releaseOutput, "e2e-diagnostics.json"), JSON.stringify({
      executable, pid: app.pid, exitCode: app.exitCode, signalCode: app.signalCode,
      error: error.message, launchError: launchError?.message,
    }, null, 2), "utf8");
    fs.writeFileSync(path.join(releaseOutput, "e2e-diagnostics.log"), output, "utf8");
    throw error;
  } finally {
    if (browser) await browser.close().catch(() => {});
    app.kill("SIGKILL");
  }
}

module.exports = { waitUntil, firstPage };
if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
