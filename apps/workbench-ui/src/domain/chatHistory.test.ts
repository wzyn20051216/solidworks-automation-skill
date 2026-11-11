import { expect, test } from "vitest";
import type { AgentChatMessage } from "../types";
import { chatHistoryForPrompt } from "./chatHistory";

test("CLI 诊断不会占满下一轮对话的上下文", () => {
  const history = [
    { role: "assistant", content: "CLI 失败。" + "诊断".repeat(15000) },
    { role: "user", content: "请读取孔径。" },
  ] as AgentChatMessage[];
  const prompt = chatHistoryForPrompt(history);
  expect(prompt).toContain("AI: CLI 失败。");
  expect(prompt).toContain("用户: 请读取孔径。");
  expect(prompt.length).toBeLessThan(1300);
  expect(history[0].content.length).toBeGreaterThan(24000);
});
