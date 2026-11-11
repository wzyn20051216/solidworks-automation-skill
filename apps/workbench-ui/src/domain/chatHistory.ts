import type { AgentChatMessage } from "../types";

export function chatHistoryForPrompt(history: AgentChatMessage[]) {
  const maxMessageLength = 1200;
  return history.slice(-8).map(({ role, content }) => {
    const label = role === "user" ? "用户" : role === "assistant" ? "AI" : "系统";
    const excerpt = content.length > maxMessageLength ? `${content.slice(0, maxMessageLength)}…` : content;
    return `${label}: ${excerpt}`;
  }).join("\n");
}
