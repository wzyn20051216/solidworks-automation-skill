# 多 Agent Provider 架构

## 目标

CAD Studio 面向不同用户环境，不绑定单一模型或 CLI。所有 Provider 共用一份 CAD 任务协议、审批策略、知识检索、产物账本和复核门禁，差异只保留在命令编译与结果解析层。

```text
用户任务
  -> UnifiedAutomationJob
  -> Policy Gate
  -> Provider Adapter
  -> Codex / Claude Code / Gemini CLI / OpenCode
  -> UnifiedAgentResult
  -> Artifact Ledger
  -> CAD/B-Rep/Motion Reviewer Gate
  -> 本地交付目录
```

## Provider 状态不能混用

界面和日志必须分别表达以下状态：

| 状态 | 证据 | 能否表述为已连接 |
|---|---|---|
| 未安装 | 找不到 CLI 入口或 `--version` 失败 | 否 |
| 已安装 | `--version` 成功 | 否 |
| 认证失败 | 官方认证状态命令返回失败 | 否 |
| 认证待验证 | CLI 没有低成本认证查询命令 | 否，首个真实任务验证 |
| 认证已验证 | 官方认证命令成功 | 可以表述为认证已验证 |
| 执行已验证 | 真实任务按统一协议返回结构化结果 | 可以表述为该次任务执行成功 |

CLI 存在、环境变量存在、CC Switch 中有 Provider 配置，都不能单独证明模型请求可用。Provider 自报成功也不能证明 SolidWorks/AutoCAD 产物正确。

## 统一任务协议

任务类型使用 `agent_task`，执行器使用 `agent`：

```json
{
  "kind": "agent_task",
  "executor": "agent",
  "objective": "创建带沉孔和半圆槽的安装板",
  "skillPath": "C:/Users/user/.codex/skills/solidworks-automation/SKILL.md",
  "uiConfig": {
    "agentRuntime": {
      "provider": "claude",
      "providerName": "Claude Code",
      "protocol": "claude-print-v1",
      "model": ""
    }
  }
}
```

旧的 `codex_task`、`executor=codex` 只作为兼容入口，进入 Worker 后仍归一到同一执行流程。

## 统一结果协议

每个 Provider 最终必须生成以下字段：

```json
{
  "summary": "本轮做了什么",
  "changedFiles": [],
  "verification": [],
  "risks": [],
  "nextSteps": []
}
```

统一结果只是 Agent 执行记录，不是 CAD 验收证据。机械交付仍需独立的文件哈希、B-Rep 尺寸、孔槽定位、预览图、Motion 结果和人工复核记录。

## 当前 Adapter

| Provider | 协议 ID | 非交互入口 | 结构化输出来源 |
|---|---|---|---|
| Codex | `codex-exec-v1` | `codex exec` | `--output-schema` + 输出文件 |
| Claude Code | `claude-print-v1` | `claude -p` | `--output-format json` + `--json-schema` |
| Gemini CLI | `gemini-headless-v1` | `gemini -p` | JSON response 包装层 |
| OpenCode | `opencode-jsonl-v1` | `opencode run` | JSONL 文本事件 |

实现位于：

- `apps/desktop/cad_workbench/agent_providers.py`
- `apps/desktop/cad_workbench/queue_worker.py`
- `apps/workbench-ui/src-tauri/src/lib.rs`

## 新增 Provider 的步骤

1. 在 `SUPPORTED_PROVIDER_IDS` 和前端 `AgentProviderId` 中登记稳定 ID。
2. 只使用该 CLI 官方文档确认的非交互参数，不凭记忆猜选项。
3. 在 `build_provider_command()` 中把统一任务编译为 Provider 命令。
4. 在 `parse_provider_result()` 中解析原生包装层，最终强制收敛到统一结果字段。
5. 增加安装、认证、超时、非 JSON、缺字段和取消任务测试。
6. 在桌面健康检查中区分安装、认证和执行验证，不新增含糊的“已连接”布尔值。
7. 真实执行最小探针，确认退出码、stdout/stderr、取消和超时行为。

## 可观察执行过程

软件可以展示计划、公开步骤、工具调用、审批、日志、文件变化和复核结果。不要承诺或伪造模型隐藏思维链；用户真正需要的是可审计的执行轨迹和可继续追问的对话上下文。

## 安全边界

- Provider Adapter 不直接暴露任意 Python、PowerShell 或 VBA 工具。
- CAD COM 调用串行化，避免多个 Agent 同时操作同一桌面会话。
- 外部网络、云 RAG 和危险本地 CAD 操作进入 Policy Gate。
- API Key 不写入任务 JSON、日志或前端持久化；只记录脱敏状态或环境变量名。
- Provider 输出必须经过 schema、Artifact Ledger 和 Reviewer Gate，不能直接宣布交付成功。
