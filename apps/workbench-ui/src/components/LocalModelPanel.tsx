import { invoke } from "@tauri-apps/api/core";
import { useState } from "react";
import { isTauriRuntime } from "../persistence";

type Mode = "chat" | "plan";
type Message = { role: "user" | "assistant"; content: string };
type Plan = { summary: string; assumptions: string[]; steps: string[]; checks: string[] };
type Reply = { kind: "chat"; text: string } | { kind: "plan"; plan: Plan };

export function LocalModelPanel() {
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [mode, setMode] = useState<Mode>("chat");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState<"probe" | "infer" | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const desktop = isTauriRuntime();

  async function checkConnection() {
    if (busy || !desktop) return;
    setBusy("probe");
    setError("");
    setConnected(false);
    try {
      const available = await invoke<string[]>("lmstudio_models");
      setModels(available);
      setModel((selected) => available.includes(selected) ? selected : available[0] ?? "");
      setConnected(true);
    } catch (failure) {
      setModels([]);
      setModel("");
      setError(String(failure));
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    const text = input.trim();
    if (busy || !model || !text || !desktop) return;
    setBusy("infer");
    setError("");
    if (mode === "plan") setPlan(null);
    const user: Message = { role: "user", content: text };
    const encoder = new TextEncoder();
    const history: Message[] = [user];
    let budget = 12_000 - encoder.encode(text).length;
    if (mode === "chat") {
      for (let i = messages.length - 2; i >= 0 && history.length < 9; i -= 2) {
        const turn = messages.slice(i, i + 2);
        budget -= turn.reduce((total, message) => total + encoder.encode(message.content).length, 0);
        if (budget < 0) break;
        history.unshift(...turn);
      }
    }
    try {
      const reply = await invoke<Reply>("lmstudio_infer", { request: { model, mode, messages: history } });
      if (reply.kind === "chat") {
        const assistant: Message = { role: "assistant", content: reply.text };
        setMessages((current) => [...current, user, assistant].slice(-20));
      } else {
        setPlan(reply.plan);
      }
      setInput("");
    } catch (failure) {
      setError(String(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <details className="agent-console local-model-panel">
      <summary>LM Studio 本地问答与任务规划</summary>
      <p>请先在 LM Studio 启动本地 API 服务。这里生成回答或待执行计划，CAD 操作请在 AI 执行对话中发起。</p>
      <div className="queue-actions local-model-controls">
        <button type="button" disabled={!desktop || busy !== null} onClick={() => void checkConnection()}>
          {busy === "probe" ? "正在检查…" : "检查连接"}
        </button>
        <span role="status">{!desktop ? "请在 CAD Studio 桌面端使用" : connected ? models.length ? "已获取模型列表" : "已连接，请在 LM Studio 加载对话模型" : "尚未确认连接"}</span>
        <label>模型 <select value={model} disabled={!models.length || busy !== null} onChange={(event) => setModel(event.target.value)}>
          {!models.length && <option value="">暂无模型</option>}
          {models.map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <label>模式 <select value={mode} disabled={busy !== null} onChange={(event) => setMode(event.target.value === "plan" ? "plan" : "chat")}>
          <option value="chat">问答</option>
          <option value="plan">任务规划</option>
        </select></label>
        <button type="button" disabled={busy !== null || (!messages.length && !plan)} onClick={() => { setMessages([]); setPlan(null); setError(""); }}>
          清空本地记录
        </button>
      </div>
      {error && <div className="queue-error" role="alert">{error}</div>}
      {mode === "chat" && messages.length > 0 && (
        <div className="chat-thread" aria-label="LM Studio 对话记录" aria-live="polite">
          {messages.map((message, index) => (
            <div key={index} className={`chat-bubble ${message.role}`}>
              <span>{message.role === "user" ? "你" : "LM Studio"}</span>
              <p>{message.content}</p>
            </div>
          ))}
        </div>
      )}
      {mode === "plan" && plan && (
        <div className="chat-bubble assistant" aria-live="polite">
          <strong>待执行计划</strong>
          <p>{plan.summary}</p>
          {plan.assumptions.length > 0 && <><strong>待确认事项</strong><ul>{plan.assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
          <strong>执行步骤</strong>
          <ol>{plan.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
          <strong>验收条件</strong>
          <ul>{plan.checks.map((check, i) => <li key={i}>{check}</li>)}</ul>
        </div>
      )}
      <form className="agent-input-row" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <textarea
          aria-label={mode === "plan" ? "规划目标" : "本地问题"}
          placeholder={mode === "plan" ? "例如：规划一个 80×40 mm 安装板的建模与验收" : "例如：装配配合为什么会过定义？"}
          maxLength={3000}
          value={input}
          disabled={busy === "infer"}
          onChange={(event) => setInput(event.target.value)}
        />
        <button type="submit" disabled={!model || !input.trim() || busy !== null} aria-busy={busy === "infer"}>
          {busy === "infer" ? "本地模型处理中…" : mode === "plan" ? "生成计划" : "发送问题"}
        </button>
      </form>
    </details>
  );
}
