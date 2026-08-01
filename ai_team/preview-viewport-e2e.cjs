/** @file preview-viewport-e2e.cjs
 *  @brief 用真实 Chromium 验证 CAD JS 预览清单、DXF Worker、图层面板和 canvas 非空。
 */
const { chromium } = require("../apps/workbench-ui/node_modules/playwright");
const fs = require("fs");
const http = require("http");
const path = require("path");

const repo = path.resolve(__dirname, "..");
const dist = path.join(repo, "apps", "workbench-ui", "dist");
const output = path.join(repo, "output", "playwright", "preview-viewport");
const queueKey = "cad-studio.queue.v1";
const mimeTypes = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4", ".json": "application/json", ".dxf": "text/plain" };

function dxfFixture() {
  return `0
SECTION
2
ENTITIES
0
LINE
8
FRAME
10
0
20
0
11
120
21
0
0
LINE
8
FRAME
10
120
20
0
11
120
21
70
0
LINE
8
FRAME
10
120
20
70
11
0
21
70
0
LINE
8
FRAME
10
0
20
70
11
0
21
0
0
CIRCLE
8
HOLES
10
30
20
35
40
6
0
CIRCLE
8
HOLES
10
90
20
35
40
6
0
TEXT
8
DIMENSIONS
10
12
20
82
1
GB/T INSTALL PLATE 120x70
0
ENDSEC
0
EOF
`;
}

function testJob() {
  const now = "2026-08-02T20:00:00+08:00";
  return {
    schemaVersion: "2.0",
    id: "preview-viewport-e2e",
    runId: "run-preview-current",
    kind: "delivery_package",
    title: "DXF 预览清单验收",
    detail: "验证 preview.json 到 DXF 场景的浏览器预览链路",
    status: "review_required",
    progress: 100,
    createdAt: now,
    updatedAt: now,
    requestedBy: "e2e",
    createdByAppVersion: "0.3.1",
    projectId: "project-default",
    expectedOutput: "DXF / PNG / 复核报告",
    requiredArtifacts: ["drawing", "preview", "report"],
    previewManifest: "preview-viewport-manifest.json",
    artifacts: [
      { kind: "drawing", path: "preview-viewport.dxf", exists: true, producedThisRun: true, sizeBytes: 1024, sha256: "dxf-fixture" },
      { kind: "preview", type: "preview", format: "json", path: "preview-viewport-manifest.json", exists: true, producedThisRun: true, interactive: true, sha256: "manifest-fixture" },
      { kind: "report", path: "preview-viewport-review.json", exists: true, producedThisRun: true, sha256: "report-fixture" },
    ],
    reviewGatePath: "preview-viewport-review.json",
    reviewGate: { status: "warning", checks: [{ id: "preview", status: "pass", message: "预览清单已生成" }] },
    drawingEvidence: { status: "pass", stage: "review", manual_review_required: true },
    artifactRelations: [{ from: "preview-viewport.dxf", to: "preview-viewport-manifest.json", type: "生成预览清单" }],
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

async function inspect(page, baseUrl, width, height, screenshotName) {
  await page.setViewportSize({ width, height });
  await page.addInitScript(([key, value]) => localStorage.setItem(key, JSON.stringify([value])), [queueKey, testJob()]);
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "交付", exact: true }).click();
  await page.locator(".cad-preview-dxf").waitFor({ state: "visible", timeout: 20_000 });
  await page.waitForFunction(() => document.querySelector(".cad-preview-status-line")?.textContent?.includes("可交互"), null, { timeout: 20_000 });
  await page.screenshot({ path: path.join(output, screenshotName), fullPage: true });
  return page.evaluate(() => {
    const canvas = document.querySelector(".cad-preview-dxf");
    const ctx = canvas?.getContext("2d");
    const sample = ctx?.getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    if (sample) {
      for (let index = 0; index < sample.length; index += 4) {
        const r = sample[index], g = sample[index + 1], b = sample[index + 2];
        if (!(r > 240 && g > 245 && b > 240)) painted += 1;
      }
    }
    return {
      overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      previewCount: document.querySelectorAll(".cad-preview").length,
      layerText: document.querySelector(".layer-list")?.textContent || "",
      statusText: document.querySelector(".cad-preview-status-line")?.textContent || "",
      evidenceText: document.querySelector(".cad-preview-evidence")?.textContent || "",
      painted,
    };
  });
}

async function main() {
  if (!fs.existsSync(path.join(dist, "index.html"))) throw new Error("请先执行 npm run build");
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(dist, "preview-viewport.dxf"), dxfFixture());
  fs.writeFileSync(path.join(dist, "preview-viewport-manifest.json"), JSON.stringify({
    previewVersion: "1.0",
    sourceArtifact: "preview-viewport.dxf",
    previewArtifact: "preview-viewport.dxf",
    fallbackImage: "",
    mode: "delivery-preview",
    isDemo: false,
    units: "mm",
    evidenceRefs: ["drawing:gb-frame", "hole-table:mounting"],
    generatedAt: "2026-08-02T20:00:00+08:00",
    sha256: "manifest-fixture",
  }, null, 2));
  const server = createServer();
  await new Promise((resolve, reject) => server.listen(0, "127.0.0.1", resolve).once("error", reject));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("无法取得临时 UI 端口");
  const baseUrl = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ reducedMotion: "reduce" });
    const desktop = await inspect(await context.newPage(), baseUrl, 1440, 900, "preview-dxf-1440x900.png");
    const compact = await inspect(await context.newPage(), baseUrl, 760, 900, "preview-dxf-760x900.png");
    const result = { desktop, compact };
    fs.writeFileSync(path.join(output, "metrics.json"), JSON.stringify(result, null, 2));
    if (desktop.overflowX || compact.overflowX) throw new Error("预览页存在横向溢出");
    if (desktop.previewCount !== 1 || compact.previewCount !== 1) throw new Error("交付页预览器数量不正确");
    if (!desktop.statusText.includes("真实产物") || !desktop.statusText.includes("可交互")) throw new Error("预览来源或状态未正确显示");
    if (!desktop.layerText.includes("FRAME") || !desktop.layerText.includes("HOLES") || !desktop.layerText.includes("DIMENSIONS")) throw new Error("DXF 图层未显示完整");
    if (!desktop.evidenceText.includes("drawing:gb-frame")) throw new Error("Evidence Graph 引用未显示");
    if (desktop.painted < 1000 || compact.painted < 1000) throw new Error("DXF canvas 像素检查为空或过少");
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
