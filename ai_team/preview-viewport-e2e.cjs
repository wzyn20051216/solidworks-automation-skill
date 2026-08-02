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

function previewSceneFixture() {
  return {
    schemaVersion: "1.0",
    kind: "dxf-scene",
    sourceArtifact: "preview-viewport.dxf",
    units: "mm",
    bounds: { minX: 0, minY: 0, maxX: 120, maxY: 82 },
    layers: [
      { name: "FRAME", color: "#25312f", count: 1, visible: true },
      { name: "HOLES", color: "#176c65", count: 2, visible: true },
      { name: "DIMENSIONS", color: "#b36b22", count: 1, visible: true },
    ],
    entities: [
      { id: "frame", kind: "polyline", layer: "FRAME", color: "#25312f", points: [[0, 0], [120, 0], [120, 70], [0, 70], [0, 0]], evidenceRefs: ["drawing:gb-frame"] },
      { id: "hole-a", kind: "circle", layer: "HOLES", color: "#176c65", points: Array.from({ length: 49 }, (_, index) => [30 + Math.cos(index / 48 * Math.PI * 2) * 6, 35 + Math.sin(index / 48 * Math.PI * 2) * 6]) },
      { id: "hole-b", kind: "circle", layer: "HOLES", color: "#176c65", points: Array.from({ length: 49 }, (_, index) => [90 + Math.cos(index / 48 * Math.PI * 2) * 6, 35 + Math.sin(index / 48 * Math.PI * 2) * 6]) },
      { id: "dim", kind: "dimension", layer: "DIMENSIONS", color: "#b36b22", text: "120", points: [[12, 78]], evidenceRefs: ["dimension:overall-width"] },
    ],
  };
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

function fallbackJob() {
  const now = "2026-08-02T20:10:00+08:00";
  return {
    schemaVersion: "2.0",
    id: "preview-webgl-fallback-e2e",
    runId: "run-preview-fallback-current",
    kind: "delivery_package",
    title: "WebGL 回退验收",
    detail: "验证模型预览无法创建 WebGL 上下文时显示本轮 PNG",
    status: "review_required",
    progress: 100,
    createdAt: now,
    updatedAt: now,
    requestedBy: "e2e",
    createdByAppVersion: "0.3.1",
    projectId: "project-default",
    expectedOutput: "PNG / 复核报告",
    requiredArtifacts: ["preview", "report"],
    previewManifest: "preview-fallback-manifest.json",
    artifacts: [
      { kind: "preview", type: "preview", format: "json", path: "preview-fallback-manifest.json", exists: true, producedThisRun: true, sha256: "fallback-manifest-fixture" },
      { kind: "preview_image", type: "preview", format: "png", path: "preview-fallback.png", exists: true, producedThisRun: true, sha256: "fallback-png-fixture" },
      { kind: "report", path: "preview-fallback-review.json", exists: true, producedThisRun: true, sha256: "fallback-report-fixture" },
    ],
    reviewGatePath: "preview-fallback-review.json",
    reviewGate: { status: "warning", checks: [{ id: "fallback", status: "pass", message: "PNG 回退来自当前任务" }] },
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
  const metrics = await page.evaluate(() => {
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
  const rawDxfRow = page.locator(".artifact-row").filter({ hasText: "preview-viewport.dxf" });
  await rawDxfRow.click();
  await page.waitForFunction(() => document.querySelector(".cad-preview-status-line")?.textContent?.includes("3 个图层"), null, { timeout: 20_000 });
  metrics.workerStatusText = await page.locator(".cad-preview-status-line").textContent();
  return metrics;
}

async function paintedPixels(page, selector) {
  return page.locator(selector).evaluate((canvas) => {
    const context = canvas.getContext("2d");
    const sample = context?.getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    if (!sample) return painted;
    for (let index = 0; index < sample.length; index += 4) {
      const r = sample[index], g = sample[index + 1], b = sample[index + 2];
      if (!(r > 240 && g > 245 && b > 240)) painted += 1;
    }
    return painted;
  });
}

async function inspectShowcase(page, baseUrl, width, height, screenshotName) {
  await page.setViewportSize({ width, height });
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "帮助", exact: true }).click();
  const showcase = page.locator(".preview-showcase");
  await showcase.waitFor({ state: "visible", timeout: 20_000 });
  const select = showcase.locator("select");
  const options = await select.locator("option").evaluateAll((items) => items.map((item) => ({ value: item.value, label: item.textContent || "" })));
  const paintedByScene = {};
  for (const option of options) {
    await select.selectOption(option.value);
    await showcase.locator(".cad-preview-status-line").filter({ hasText: "可交互" }).waitFor({ state: "visible", timeout: 20_000 });
    paintedByScene[option.value] = await paintedPixels(page, ".preview-showcase .cad-preview-dxf");
  }
  await page.screenshot({ path: path.join(output, screenshotName), fullPage: true });
  return page.evaluate((expectedLabels) => ({
    overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    demoText: document.querySelector(".preview-showcase .cad-preview-status-line")?.textContent || "",
    labels: expectedLabels,
    previewCount: document.querySelectorAll(".preview-showcase .cad-preview").length,
  }), options.map((option) => option.label)).then((metrics) => ({ ...metrics, paintedByScene }));
}

async function inspectWebGlFallback(page, baseUrl) {
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.addInitScript(([key, value]) => {
    localStorage.setItem(key, JSON.stringify([value]));
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function patchedGetContext(type, ...args) {
      if (String(type).toLowerCase().includes("webgl")) return null;
      return original.call(this, type, ...args);
    };
  }, [queueKey, fallbackJob()]);
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "交付", exact: true }).click();
  const preview = page.locator(".delivery-preview-stage .cad-preview");
  await preview.locator("img").waitFor({ state: "visible", timeout: 20_000 });
  await preview.locator(".cad-preview-status-line").filter({ hasText: "PNG 回退" }).waitFor({ state: "visible", timeout: 20_000 });
  await page.screenshot({ path: path.join(output, "preview-webgl-fallback-1280x820.png"), fullPage: true });
  return preview.evaluate((element) => ({
    statusText: element.querySelector(".cad-preview-status-line")?.textContent || "",
    source: element.querySelector(".cad-preview-status-line em")?.textContent || "",
    imagePath: element.querySelector("img")?.getAttribute("src") || "",
    naturalWidth: element.querySelector("img")?.naturalWidth || 0,
    hasCanvas: Boolean(element.querySelector("canvas")),
  }));
}

async function main() {
  if (!fs.existsSync(path.join(dist, "index.html"))) throw new Error("请先执行 npm run build");
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(dist, "preview-viewport.dxf"), dxfFixture());
  fs.writeFileSync(path.join(dist, "preview-viewport-manifest.json"), JSON.stringify({
    previewVersion: "1.0",
    sourceArtifact: "preview-viewport.dxf",
    previewArtifact: "preview-viewport.scene.json",
    fallbackImage: "",
    mode: "delivery-preview",
    isDemo: false,
    units: "mm",
    evidenceRefs: ["drawing:gb-frame", "hole-table:mounting"],
    generatedAt: "2026-08-02T20:00:00+08:00",
    sha256: "manifest-fixture",
  }, null, 2));
  fs.writeFileSync(path.join(dist, "preview-viewport.scene.json"), JSON.stringify(previewSceneFixture(), null, 2));
  fs.writeFileSync(path.join(dist, "preview-fallback-manifest.json"), JSON.stringify({
    previewVersion: "1.0",
    sourceArtifact: "preview-fallback.step",
    previewArtifact: "preview-fallback.glb",
    fallbackImage: "preview-fallback.png",
    mode: "delivery-preview",
    isDemo: false,
    units: "mm",
    generatedAt: "2026-08-02T20:10:00+08:00",
    sha256: "fallback-manifest-fixture",
  }, null, 2));
  fs.writeFileSync(path.join(dist, "preview-fallback.glb"), Buffer.from("invalid-glb-for-webgl-fallback"));
  fs.writeFileSync(path.join(dist, "preview-fallback.png"), Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGNg+M+ABzDhkxyGBgYAAL8AAf9m8Z8AAAAASUVORK5CYII=", "base64"));
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
    const showcaseDesktop = await inspectShowcase(await context.newPage(), baseUrl, 1440, 900, "preview-showcase-1440x900.png");
    const showcaseCompact = await inspectShowcase(await context.newPage(), baseUrl, 760, 900, "preview-showcase-760x900.png");
    const showcaseMobile = await inspectShowcase(await context.newPage(), baseUrl, 390, 844, "preview-showcase-390x844.png");
    const fallbackContext = await browser.newContext({ reducedMotion: "reduce" });
    const webGlFallback = await inspectWebGlFallback(await fallbackContext.newPage(), baseUrl);
    await fallbackContext.close();
    const result = { desktop, compact, showcaseDesktop, showcaseCompact, showcaseMobile, webGlFallback };
    fs.writeFileSync(path.join(output, "metrics.json"), JSON.stringify(result, null, 2));
    if (desktop.overflowX || compact.overflowX) throw new Error("预览页存在横向溢出");
    if (desktop.previewCount !== 1 || compact.previewCount !== 1) throw new Error("交付页预览器数量不正确");
    if (!desktop.statusText.includes("真实产物") || !desktop.statusText.includes("可交互")) throw new Error("预览来源或状态未正确显示");
    if (!desktop.workerStatusText?.includes("3 个图层") || !compact.workerStatusText?.includes("3 个图层")) throw new Error("原始 DXF Worker 回退链路未通过");
    if (!desktop.layerText.includes("FRAME") || !desktop.layerText.includes("HOLES") || !desktop.layerText.includes("DIMENSIONS")) throw new Error("DXF 图层未显示完整");
    if (!desktop.evidenceText.includes("drawing:gb-frame")) throw new Error("Evidence Graph 引用未显示");
    if (desktop.painted < 1000 || compact.painted < 1000) throw new Error("DXF canvas 像素检查为空或过少");
    for (const showcase of [showcaseDesktop, showcaseCompact, showcaseMobile]) {
      if (showcase.overflowX) throw new Error("演示检视台存在横向溢出");
      if (showcase.previewCount !== 1 || showcase.labels.length !== 7) throw new Error("演示检视台样例数量不正确");
      if (!showcase.demoText.includes("演示数据") || !showcase.demoText.includes("可交互")) throw new Error("演示数据标记或状态缺失");
      if (Object.values(showcase.paintedByScene).some((painted) => painted < 400)) throw new Error("演示样例 Canvas 为空或绘制像素过少");
    }
    if (!webGlFallback.statusText.includes("PNG 回退") || webGlFallback.source !== "真实产物") throw new Error("WebGL 失败后未保留真实产物来源并回退 PNG");
    if (!webGlFallback.imagePath.includes("preview-fallback.png") || webGlFallback.naturalWidth < 1 || webGlFallback.hasCanvas) throw new Error("WebGL PNG 回退图未正确显示");
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
