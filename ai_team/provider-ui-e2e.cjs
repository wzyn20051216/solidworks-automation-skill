const { chromium } = require("../apps/workbench-ui/node_modules/playwright");
const { spawn } = require("child_process");
const path = require("path");

const repo = path.resolve(__dirname, "..");
const executable = process.env.CAD_STUDIO_E2E_EXE
  || path.join(repo, "apps", "workbench-ui", "src-tauri", "target", "debug", "cad-studio.exe");
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitUntil(check, label, timeout = 20_000) {
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
  const app = spawn(executable, [], {
    cwd: repo,
    env: {
      ...process.env,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9226",
    },
    stdio: "ignore",
  });
  let browser;
  try {
    await waitUntil(async () => {
      try {
        return (await fetch("http://127.0.0.1:9226/json/version")).ok;
      } catch {
        return false;
      }
    }, "Tauri CDP start", 20_000);

    browser = await chromium.connectOverCDP("http://127.0.0.1:9226");
    const page = browser.contexts()[0].pages()[0];
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.waitForTimeout(4_500);
    const invoke = (command, args = {}) =>
      page.evaluate(
        ([activeCommand, activeArgs]) => window.__TAURI_INTERNALS__.invoke(activeCommand, activeArgs),
        [command, args],
      );
    const runtime = await invoke("runtime_health");
    if (process.env.CAD_STUDIO_EXPECT_BUNDLED_SKILL === "1") {
      const normalizedSkillRoot = String(runtime.skillRoot || "").replace(/\\/g, "/").toLowerCase();
      if (!normalizedSkillRoot.endsWith("/skill")) {
        throw new Error(`发布版没有使用内置 skill: ${runtime.skillRoot}`);
      }
    }

    const directSync = await invoke("sync_cc_switch_config");
    const counts = Object.fromEntries(
      ["codex", "claude", "gemini", "opencode"].map((provider) => [
        provider,
        directSync.providersByAgent?.[provider]?.length || 0,
      ]),
    );
    if (counts.codex < 7 || counts.claude < 10 || counts.gemini < 2 || counts.opencode < 1) {
      throw new Error(`CC Switch 路由读取不完整: ${JSON.stringify(counts)}`);
    }
    if (!directSync.databasePath?.endsWith("cc-switch.db")) {
      throw new Error(`未使用 CC Switch SQLite: ${directSync.databasePath}`);
    }
    const serialized = JSON.stringify(directSync);
    if (serialized.includes("OPENAI_API_KEY") || serialized.includes("ANTHROPIC_API_KEY")) {
      throw new Error("同步结果包含凭据字段");
    }

    await page.getByRole("button", { name: "设置", exact: true }).click();
    const claudeCard = page.locator(".agent-provider-grid button").filter({ hasText: "Claude Code" });
    await waitUntil(async () => !(await claudeCard.isDisabled()), "Claude provider enabled");
    await claudeCard.click();
    await page.getByRole("button", { name: "读取 CC Switch 状态", exact: true }).click();
    await waitUntil(
      async () => (await page.locator(".api-sync-row span").innerText()).includes("10 个 Claude Code 路由"),
      "Claude CC Switch sync",
    );
    const claudeRows = await page.locator(".provider-row").count();
    const claudeText = await page.locator(".provider-list").innerText();
    if (claudeRows !== counts.claude || claudeText.includes("未检测到 Key")) {
      throw new Error(`Claude 路由 UI 异常: rows=${claudeRows}`);
    }

    await page.getByRole("button", { name: "建模", exact: true }).click();
    const executor = await page.locator(".runtime-line").filter({ hasText: "Executor" }).locator("strong").innerText();
    const runButton = await page.locator(".bridge-run").innerText();
    const corner = await page.locator(".main-window").evaluate((element) => ({
      borderTopLeftRadius: getComputedStyle(element).borderTopLeftRadius,
      overflowX: getComputedStyle(element).overflowX,
    }));
    const toolbar = await page.locator(".app-toolbar").evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        backgroundColor: style.backgroundColor,
        borderTopWidth: style.borderTopWidth,
        borderRightWidth: style.borderRightWidth,
        borderBottomWidth: style.borderBottomWidth,
        borderLeftWidth: style.borderLeftWidth,
        boxShadow: style.boxShadow,
      };
    });
    if (executor !== "Claude Code" || !runButton.includes("Claude Code")) {
      throw new Error(`Claude 文案未联动: executor=${executor}, button=${runButton}`);
    }
    if (corner.borderTopLeftRadius !== "0px" || corner.overflowX !== "hidden") {
      throw new Error(`主窗口无框布局未生效: ${JSON.stringify(corner)}`);
    }
    if (
      toolbar.backgroundColor !== "rgba(0, 0, 0, 0)" ||
      [toolbar.borderTopWidth, toolbar.borderRightWidth, toolbar.borderBottomWidth, toolbar.borderLeftWidth].some((value) => value !== "0px") ||
      toolbar.boxShadow !== "none"
    ) {
      throw new Error(`顶栏仍存在容器边框: ${JSON.stringify(toolbar)}`);
    }

    await page.getByRole("button", { name: "设置", exact: true }).click();
    const codexCard = page.locator(".agent-provider-grid button").filter({ hasText: "Codex" }).first();
    await codexCard.click();
    await page.getByRole("button", { name: "读取 CC Switch 状态", exact: true }).click();
    await waitUntil(
      async () => (await page.locator(".api-sync-row span").innerText()).includes("7 个 Codex 路由"),
      "Codex CC Switch sync",
    );
    const activeCodexRoute = await page.locator(".provider-row.active strong").first().innerText();
    if (activeCodexRoute !== "5555") {
      throw new Error(`Codex 当前路由识别错误: ${activeCodexRoute}`);
    }

    const providerLabels = {};
    for (const [providerName, expectedExecutor] of [
      ["Gemini CLI", "Gemini CLI"],
      ["OpenCode", "OpenCode"],
    ]) {
      await page.getByRole("button", { name: "设置", exact: true }).click();
      const providerCard = page.locator(".agent-provider-grid button").filter({ hasText: providerName }).first();
      await waitUntil(async () => !(await providerCard.isDisabled()), `${providerName} provider enabled`);
      await providerCard.click();
      await page.getByRole("button", { name: "建模", exact: true }).click();
      const providerExecutor = await page.locator(".runtime-line").filter({ hasText: "Executor" }).locator("strong").innerText();
      const providerButton = await page.locator(".bridge-run").innerText();
      if (providerExecutor !== expectedExecutor || !providerButton.includes(expectedExecutor)) {
        throw new Error(`${providerName} 文案未联动: executor=${providerExecutor}, button=${providerButton}`);
      }
      providerLabels[providerName] = { executor: providerExecutor, button: providerButton };
    }

    await page.screenshot({ path: path.join(repo, "ai_team", "ui_review", "provider-sync-desktop.png") });
    console.log(JSON.stringify({ counts, executor, runButton, providerLabels, corner, toolbar, activeCodexRoute, skillRoot: runtime.skillRoot, errors }, null, 2));
  } finally {
    if (browser) await browser.close().catch(() => {});
    app.kill();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
