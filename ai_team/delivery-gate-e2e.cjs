/** @file delivery-gate-e2e.cjs
 *  @brief 用真实 Chromium 验证交付门禁、版本记录与响应式布局。
 */
const { chromium } = require("../apps/workbench-ui/node_modules/playwright");
const fs = require("fs");
const http = require("http");
const path = require("path");

const repo = path.resolve(__dirname, "..");
const dist = path.join(repo, "apps", "workbench-ui", "dist");
const output = path.join(repo, "output", "playwright", "delivery-gate");
const queueKey = "cad-studio.queue.v1";
const mimeTypes = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4" };

function testJob(status = "review_required") {
  const now = "2026-08-01T19:40:00+08:00";
  const manualReviewRequired = status !== "passed";
  return {
    schemaVersion: "2.0",
    id: "delivery-gate-e2e",
    runId: "run-current",
    kind: "delivery_package",
    title: "安装板工程图交付",
    detail: "验证模型、工程图、BOM、预览和复核报告交付闭环",
    status,
    progress: 100,
    createdAt: now,
    updatedAt: now,
    requestedBy: "e2e",
    createdByAppVersion: "0.3.1",
    projectId: "project-default",
    expectedOutput: "STEP / DWG / BOM / PNG / 复核报告",
    requiredArtifacts: ["model", "drawing", "bom", "preview", "report"],
    artifacts: [
      { kind: "model", path: "D:/delivery/v2/install-plate.step", exists: true, producedThisRun: true, sizeBytes: 12000, sha256: "model-v2" },
      { kind: "drawing", path: "D:/delivery/v2/install-plate.dwg", exists: true, producedThisRun: true, sizeBytes: 37000, sha256: "drawing-v2" },
      { kind: "bom", path: "D:/delivery/v2/install-plate-bom.csv", exists: true, producedThisRun: true, sizeBytes: 960, sha256: "bom-v2" },
      { kind: "preview", path: "D:/delivery/v2/install-plate.png", exists: true, producedThisRun: true, sizeBytes: 19000, sha256: "preview-v2" },
      { kind: "report", path: "D:/delivery/v2/review-report.json", exists: true, producedThisRun: true, sizeBytes: 2400, sha256: "report-v2" },
    ],
    artifactLedgerPath: "D:/delivery/v2/artifact-ledger.json",
    reviewGatePath: "D:/delivery/v2/review-report.json",
    reviewGate: { status: manualReviewRequired ? "warning" : "pass", checks: [{ id: "artifacts", status: "pass", message: "本轮产物完整" }] },
    drawingEvidence: { status: "pass", stage: "review", manual_review_required: manualReviewRequired },
    bomEvidence: { status: "pass", stage: "review", manual_review_required: manualReviewRequired },
    artifactRelations: [
      { from: "D:/delivery/v2/install-plate.step", to: "D:/delivery/v2/install-plate.dwg", type: "生成工程图" },
      { from: "D:/delivery/v2/install-plate.dwg", to: "D:/delivery/v2/install-plate.png", type: "导出预览" },
    ],
    backendDiagnostics: {
      autocad_dotnet: { backend: "autocad_dotnet", status: "pilot", stage: "review", limitations: ["AutoCAD 2024 白名单命令"] },
      autocad_com: { backend: "autocad_com", status: "blocked", stage: "preflight", error_code: "AUTOCAD_COM_UNSTABLE" },
    },
    runHistory: [{
      runId: "run-v1",
      status: "failed",
      updatedAt: "2026-08-01T18:30:00+08:00",
      artifacts: [
        { kind: "model", path: "D:/delivery/v1/install-plate.step", exists: true, producedThisRun: true, sha256: "model-v1" },
        { kind: "drawing", path: "D:/delivery/v1/install-plate.dwg", exists: true, producedThisRun: true, sha256: "drawing-v1" },
      ],
      error: "工程图尺寸需要复核",
    }],
    retryPolicy: { previousRunId: "run-v1", retryFromStage: "drawing-bom", scope: "failed_stage_and_downstream", preservePreviousArtifacts: true, overwrite: false },
    reviewDecision: status === "passed" ? "approved" : undefined,
  };
}

function createServer() {
  return http.createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
    const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const target = path.resolve(dist, relative);
    if (!target.startsWith(path.resolve(dist)) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, { "Content-Type": `${mimeTypes[path.extname(target)] || "application/octet-stream"}; charset=utf-8` });
    fs.createReadStream(target).pipe(response);
  });
}

async function inspect(page, baseUrl, width, height, status, screenshotName, mutateJob) {
  await page.setViewportSize({ width, height });
  const job = testJob(status);
  mutateJob?.(job);
  await page.addInitScript(([key, value]) => localStorage.setItem(key, JSON.stringify([value])), [queueKey, job]);
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const deliveryButton = page.getByRole("button", { name: "交付", exact: true });
  await deliveryButton.waitFor({ state: "visible", timeout: 15_000 });
  await deliveryButton.click();
  await page.locator(".delivery-gate").waitFor({ state: "visible" });
  await page.screenshot({ path: path.join(output, screenshotName), fullPage: true });
  return page.evaluate(() => ({
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    disposition: [...document.querySelector(".delivery-gate")?.classList || []],
    gateText: document.querySelector(".delivery-gate")?.textContent || "",
    retryText: document.querySelector(".delivery-heading-actions")?.textContent || "",
    versionText: document.querySelector(".delivery-versions")?.textContent || "",
    diagnosticText: document.querySelector(".delivery-diagnostics")?.textContent || "",
    traceRows: document.querySelectorAll(".delivery-trace-row").length,
    previewCount: document.querySelectorAll(".cad-preview").length,
  }));
}

async function main() {
  if (!fs.existsSync(path.join(dist, "index.html"))) throw new Error("请先执行 npm run build");
  fs.mkdirSync(output, { recursive: true });
  const server = createServer();
  await new Promise((resolve, reject) => server.listen(0, "127.0.0.1", resolve).once("error", reject));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("无法取得临时 UI 端口");
  const baseUrl = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ reducedMotion: "reduce" });
    const desktop = await inspect(await context.newPage(), baseUrl, 1440, 900, "review_required", "delivery-review-1440x900.png");
    const compact = await inspect(await context.newPage(), baseUrl, 760, 900, "passed", "delivery-ready-760x900.png");
    const incomplete = await inspect(await context.newPage(), baseUrl, 1024, 800, "passed", "delivery-incomplete-1024x800.png", (job) => {
      job.artifacts = job.artifacts.filter((artifact) => artifact.kind !== "bom");
    });
    const result = { desktop, compact, incomplete };
    fs.writeFileSync(path.join(output, "metrics.json"), JSON.stringify(result, null, 2));
    if (desktop.overflowX || compact.overflowX) throw new Error("交付页存在横向溢出");
    if (!desktop.disposition.includes("review_required") || !desktop.gateText.includes("等待人工复核")) throw new Error("待复核门禁未正确显示");
    if (desktop.gateText.includes("本轮可交付")) throw new Error("待复核任务被错误标成可交付");
    if (!desktop.retryText.includes("从工程图与 BOM重新生成")) throw new Error("局部重跑阶段未显示");
    if (!desktop.versionText.includes("run-v1") || !desktop.diagnosticText.includes("AUTOCAD_COM_UNSTABLE")) throw new Error("版本或后端诊断缺失");
    if (!compact.disposition.includes("ready") || !compact.gateText.includes("本轮可交付")) throw new Error("已批准任务未显示可交付");
    if (!incomplete.disposition.includes("incomplete") || !incomplete.gateText.includes("缺少要求产物：bom")) throw new Error("缺少 BOM 的任务被错误标成可交付");
    if (desktop.traceRows !== 2 || compact.traceRows !== 2) throw new Error("产物关系未完整显示");
    if (desktop.previewCount !== 1 || compact.previewCount !== 1) throw new Error("交付页重复渲染了文件预览");
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
