const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(
  path.join(__dirname, "../apps/workbench-ui/node_modules/playwright"),
);

const baseUrl = process.env.CAD_STUDIO_UI_URL || "http://127.0.0.1:5174";
const output = path.resolve(__dirname, "../output/live-visual-e2e");

async function launchBrowser() {
  try {
    return await chromium.launch({ headless: true });
  } catch {
    return chromium.launch({ headless: true, channel: "chrome" });
  }
}

async function assertContained(page, selector) {
  const overflow = await page.locator(selector).evaluate((element) => ({
    horizontal: element.scrollWidth > element.clientWidth + 1,
    vertical: element.scrollHeight > element.clientHeight + 1,
  }));
  if (overflow.horizontal || overflow.vertical) {
    throw new Error(`${selector} overflows: ${JSON.stringify(overflow)}`);
  }
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await launchBrowser();
  try {
    const hud = await browser.newPage({ viewport: { width: 420, height: 300 } });
    await hud.goto(`${baseUrl}/?window=live&demo=complete`, {
      waitUntil: "networkidle",
    });
    await hud.waitForSelector(".live-hud");
    const hudText = await hud.locator(".live-hud").innerText();
    if (!hudText.includes("完成") && !hudText.includes("搞定")) {
      throw new Error(`HUD completion text missing: ${hudText}`);
    }
    await assertContained(hud, ".live-hud");
    await hud.screenshot({ path: path.join(output, "live-hud-420x300.png") });

    await hud.setViewportSize({ width: 320, height: 220 });
    await assertContained(hud, ".live-hud");
    await hud.screenshot({ path: path.join(output, "live-hud-320x220.png") });

    const main = await browser.newPage({ viewport: { width: 1440, height: 980 } });
    await main.goto(baseUrl, { waitUntil: "networkidle" });
    const now = new Date().toISOString();
    await main.evaluate(({ now }) => {
      localStorage.setItem(
        "cad-studio.settings.v1",
        JSON.stringify({
          defaultWallpaperVersion: 1,
          visualMode: true,
          showLiveHud: true,
        }),
      );
      localStorage.setItem(
        "cad-studio.queue.v1",
        JSON.stringify([
          {
            schemaVersion: "2.0",
            id: "job-live-visual-e2e",
            runId: "run-live-visual-e2e",
            kind: "agent_task",
            title: "阶梯轴可视化建模",
            detail: "SolidWorks 2026 · SLDPRT / STEP",
            status: "passed",
            progress: 100,
            stage: "delivery",
            createdAt: now,
            updatedAt: now,
            requestedBy: "e2e",
            createdByAppVersion: "e2e",
            projectId: "project-default",
            conversationId: "conversation-live-visual-e2e",
            uiConfig: { agentChat: true, visualMode: true },
            capabilities: ["part_and_features", "visual_live_execution"],
            reviewGate: { status: "pass", checks: [] },
            result: {
              message: "交付文件已生成",
              outputPath: "D:/demo/idler_shaft.SLDPRT",
              features: [{ name: "Boss-Extrude1" }, { name: "Cut-Extrude1" }],
            },
            artifacts: [
              {
                kind: "sldprt",
                path: "D:/demo/idler_shaft.SLDPRT",
                exists: true,
              },
            ],
          },
        ]),
      );
    }, { now });
    await main.reload({ waitUntil: "networkidle" });
    await main.waitForSelector(".live-execution-strip");
    await main.waitForSelector(".live-delivery-card");
    const mainText = await main.locator(".live-delivery-card").innerText();
    if (!mainText.includes("本轮交付完成") || !mainText.includes("idler_shaft.SLDPRT")) {
      throw new Error(`Delivery card content mismatch: ${mainText}`);
    }
    await main.locator(".agent-console").evaluate((element) => {
      element.scrollIntoView({ block: "center" });
    });
    await assertContained(main, ".live-execution-strip");
    await assertContained(main, ".live-delivery-card");
    await main.screenshot({
      path: path.join(output, "main-live-execution.png"),
      fullPage: true,
    });

    console.log(
      JSON.stringify({
        hud: [path.join(output, "live-hud-420x300.png"), path.join(output, "live-hud-320x220.png")],
        main: path.join(output, "main-live-execution.png"),
      }),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
