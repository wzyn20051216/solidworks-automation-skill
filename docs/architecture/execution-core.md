# V2 Execution Core —— 内部可靠执行层

> 定位：Execution Core 是 **内部实现**，不是用户入口、不是 daemon、不是独立 Runtime 服务、
> 不是第四个入口，也不替代 Codex / Claude 的上层 Planning。

## 1. Motivation

V2 之前，可靠执行思想已经散落在 Skill、MCP、Worker、Reviewer、Artifact Ledger 等模块中
（能力门禁、后端路由、策略审批、租约、心跳、stale 恢复、文件事实复核、几何证据、JSONL 事件流），
但**没有收敛成一个统一、可复用、可测试的执行可靠性层**。

V2 把这些已有能力工程化为一个轻量执行层，核心原则：

> AI 可以自由思考，但执行必须受控、可验证、可恢复、可追踪。

## 2. Architecture

```
LLM Agent (Codex / Claude / Cursor / OpenClaw)
  ↓
Skill / MCP / CAD Studio（三个用户入口，保持不变）
  ↓
Execution Core（scripts/core/）
  ├─ State（state.py）
  ├─ Capability Facade（capability.py）
  ├─ Trace（trace.py）
  ├─ Verification Adapter（verification.py）
  ├─ Recovery Decision（recovery.py）
  └─ Execution Orchestration（execution.py）
  ↓
Backend Router（scripts/capabilities.py + capabilities.yaml）
  ↓
Tools / MCP / Scripts（Python COM / C# PIA / OCCT / ...）
  ↓
External CAD Software
  ↓
Verification → Recovery Decision → Artifacts / Evidence / Trace
```

**术语统一**（不要混用 Runtime Manager / Agent Engine / Workflow Engine / Orchestrator Core）：

- **Skill** = 领域知识、能力说明、SOP、开放能力规则
- **MCP** = 标准化 Tool Protocol
- **Capability Registry** = `capabilities.yaml` + adapter
- **Backend Router** = 根据能力 / 环境 / 版本选择执行后端
- **Execution Core** = Execution Reliability Layer（本质上是 lightweight Agent Runtime）
- **Worker** = Job Processor
- **Reviewer** = Result Verification
- **Artifact Ledger** = Delivery Facts（最终交付事实）
- **Trace** = Execution History（执行过程历史）
- **Golden Workflow Eval** = Reliability Benchmark

## 3. State（`state.py`）

轻量执行状态模型，**不与 CAD Studio Queue Schema 强绑定**，可被 Worker / MCP / CLI 复用。
不实现复杂 FSM，只做最小转换白名单（拦截 `FAILED → COMPLETED`、`BLOCKED → COMPLETED` 等）。

- `RunStatus`：created / running / verifying / retrying / blocked / failed / completed
- `StepStatus`：pending / running / success / failed / verifying / retrying / blocked
- `VerificationStatus`：PASS / WARN / FAIL / BLOCKED
- `RunContext` / `StepRecord` / `ExecutionResult` / `VerificationResult` / `RecoveryDecision`

全部 JSON 可序列化、带 `schema_version`；只存 `arguments_summary` / `result_summary` 摘要，
不存完整 Prompt / API Key / 秘密 / 无必要绝对路径。

## 4. Capability Facade（`capability.py`）

**不是新 Registry**，而是 `scripts/capabilities.py` + `capabilities.yaml` 的薄 Adapter：

- `get_capability` / `get_capability_status` / `get_operation_route`
- `resolve_backend`（直接委托 `resolve_operation_backend`）
- `get_backend_candidates` / `requires_review` / `capability_gap`

`capabilities.yaml` 仍是唯一能力真源，未新增 `tool_registry.yaml` 等第二份配置。

## 5. Execution（`execution.py`）

`execute_with_core(...)` 是 orchestration glue，串起：

```
RunContext + StepRecord
  → Existing Handler（原样调用，raw_result 保留）
  → ExecutionResult（最小归一化，异常原样交还）
  →（requires_review 时）Verification Adapter
  →（失败/blocked 时）Recovery Decision
  → Trace
  → ExecutionAssessment（sidecar）
```

**不负责**：Queue claim / lease / heartbeat / approval / policy / stale 恢复 / Ledger 实现 /
Reviewer 实现 / Backend Router 实现 / 真正 retry / 真正切换 backend / replan / 联网。

## 6. Verification（`verification.py`）

Verification Adapter 只做「把检查结果翻译成统一语言」：

- `verify(...)` 调用既有 Reviewer（注入 callable 或接收既有 result），输出统一 `VerificationResult`；
- 归一化历史状态：`pass/warn/warning/review_required → PASS/WARN`、`fail/failed → FAIL`、
  `blocked → BLOCKED`，未知安全降级 `BLOCKED`；
- 聚合规则：`BLOCKED > FAIL > WARN > PASS`，尊重 `severity` / `required` / `optional`；
- **`reviewer_result` 优先于 `reviewer`**，避免同一 Review 事实重复执行。

核心规则：**Tool / Handler 返回 success ≠ 任务成功**。需要 Review 的能力只有 Verification
PASS 且 `manual_review_required=false` 后才允许最终完成；WARN / FAIL / BLOCKED 和待人工复核结果均不能进入 completed。结构化执行结果的必要布尔标记为 false 时直接失败，类型不明确或关键证据为 null 时 blocked；顶层 PASS 也不能覆盖 required check 的 FAIL。

## 7. Recovery Decision（`recovery.py`）

只回答「发生这种失败后，下一步应该采取什么动作」，**不执行动作**。

- `ErrorKind`（10 类）：transient / invalid_argument / environment_missing / tool_unavailable /
  backend_unavailable / verification_failed / user_action_required / policy_blocked / capability_gap / fatal
- `classify_error(...)` 确定性优先级：显式 error_kind → 结构化 error_code → 既有 Result 状态
  （policy > capability > verification > execution）→ 异常类型 → message 关键词 → 未知归 FATAL
- `decide(...)` → `RecoveryDecision`（retry / fallback_backend / replan_required /
  user_action_required / block / fail），retry 有上限（`DEFAULT_MAX_RETRIES = 2`）

**重要：Recovery Decision ≠ Recovery Execution。** 当前版本只产生决策并记录，
**未默认开启自动 retry / fallback / replan**；动作由 Worker / 上层 Agent 决定是否执行。

安全默认：不确定 → BLOCK / FAIL / REPLAN，绝不默认 retry。`POLICY_BLOCKED → block`，
Recovery 不允许绕过 Policy Gate。

## 8. Trace（`trace.py`）

复用现有 `queue/events/` 的 append-only JSONL，**不新建独立 Trace 存储**：

- 事件：`run.started / step.started / tool.called / tool.succeeded / tool.failed /
  verification.* / recovery.* / run.completed / run.failed / run.blocked`；
- additive schema：`run_id / trace_id / step_id / parent_step_id / ...` 全可选，旧事件仍可读；
- `redact` 兜底脱敏（prompt / api_key / token / secret / ...）；
- Trace 写入失败不影响执行结果（可观测性是旁路能力）。

职责分离：**Artifact Ledger = 最终交付事实；Trace = 执行过程历史**，禁止重叠。

## 9. Worker Integration（最小侵入）

`queue_worker.process_job` 继续复用现有 Handler 与 Review Gate：

```
Job → Policy / Approval（仍在 Execution Core 之前）
    → Execution Core 包裹 Existing Handler
    → Existing Reviewer Gate（仍只发生一次）
    → Verification Adapter + Recovery Decision（复核结果进入既有 Gate）
    → 既有终态映射（passed / review_required / failed / blocked / cancelled）
```

- Policy / Approval / Cancellation / claim lock / lease / heartbeat / stale recovery / quarantine
  **全部未动**；
- Existing Handler 仍是唯一真实执行实现；
- Queue / Worker / Reviewer / Artifact Ledger 均未重写；
- 新增 `executionAssessment` / `verificationAssessment` / `recoveryDecision` 为 optional sidecar。
- Worker 调用 Core 时延迟完成，等既有 Review Gate 结束后统一 Queue 与 Core 的终态，避免 Core 先 completed、Queue 后 failed。

## 10. Capability Gap

找不到能力 / 后端时返回结构化 `CAPABILITY_GAP`（`agent_resolution_required`），把控制权
交还上层 Agent。**Execution Core 不联网、不自动生成工具**；上层 Agent 依据 SKILL.md 继续：

```
references → official API / SDK → alternate backend → minimal implementation → verification
```

`Tool Missing != Capability Missing`：Capability 存在但 Tool 不可用 → `replan_required`
（上层 Agent 尝试 Tool Composition）；Capability 本身缺失 → `CAPABILITY_GAP`。

## 11. Reliability Eval（`tests/evals/`）

`golden-workflows.yaml` 是 Golden Workflow 唯一真源。Eval 派生 37 个 deterministic scenario，
按口径分组（nominal / recovery / fault_injection / guardrail），用 Fake Handler/Reviewer 验证
执行控制逻辑。指标分四组：Nominal / Robustness / Safety / Overall Diagnostic。
详见 [`v2-evaluation.md`](v2-evaluation.md) 与 [`v2-regression-report.md`](v2-regression-report.md)。

## 12. Compatibility

- Skill 使用方式、原有 60 个 MCP Tool Name / Input Schema、CLI 命令和 Queue Schema 保持兼容；新增只读产物工具与可选 HTTP 传输；
- `capabilities.yaml` 仍唯一真源，`golden-workflows.yaml` 向后兼容；
- 新增字段全部 additive / optional；
- 2026-10-08 的方案 B 修复执行事实、草图/阵列和资源生命周期；验收范围为 SolidWorks 2026，详见 [`scheme-b-reliability.md`](scheme-b-reliability.md)。
