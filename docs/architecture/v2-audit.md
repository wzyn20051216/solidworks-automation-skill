# SolidWorks Automation Skill V2 架构审计报告

> 版本：Phase 1（架构审计）
> 状态：**历史快照**。本报告是 Phase 1 的审计结论，Phase 2–8 已按其方案落地；
> 文中"待确认后进入 Phase 2"等时点表述不再代表当前状态。
> 当前能力状态以 `capabilities.yaml` 为准，发布就绪性以 PR #43 与发布阻断清单为准。
> 范围：仓库 `wzyn20051216/solidworks-automation-skill` 主分支完整阅读
> 原则：先审计、不修改代码；本文档只陈述事实与最小改造方案，不包含任何已落地代码。

---

## 0. 审计范围与方法

已完整阅读：

- 顶层文档：`README.md`、`SKILL.md`、`SUBSKILLS.md`、`capabilities.yaml`、`golden-workflows.yaml`
- 路由/能力：`scripts/capabilities.py`、`scripts/backend_router.py`、`references/language-backend-routing.md`
- 审查/自检：`scripts/sw_review.py`、`scripts/sw_preflight.py`
- 桌面运行时：`apps/desktop/cad_workbench/` 下 `queue_worker.py`、`reviewer_gate.py`、`artifact_ledger.py`、`worker_health.py`、`agent_contracts.py`、`agent_providers.py`、`knowledge_retrieval.py`、`engineering_orchestrator.py`、`core.py`
- MCP：`mcp-server/server.py`（约 3500 行）、`mcp-server/README.md`
- CLI：`scripts/cad_studio.py`
- 文档：`docs/agent-framework/enterprise-agent-control-plane.md`、`docs/product-mvp-spec.md`、`docs/skill-map.md`
- 测试：`tests/fakes.py`、`tests/test_cad_reliability.py`、`tests/test_workbench_queue_worker.py` 等测试目录全景
- 打包/CI：`pyproject.toml`、`scripts/sync_bundled_skill.py`、`.github/workflows/windows-cad-regression.yml`

审计结论：**本项目已经拥有远超一般 Skill 的可靠执行思想**——能力真源、后端路由、策略门禁、队列租约、心跳、stale 恢复、Artifact Ledger、Reviewer Gate、JSONL 事件流、几何证据都已存在，只是**分散在多个模块里，没有收敛成一个统一、可复用、可测试的 "Execution Core"**。V2 的本质是把这些已有能力**工程化为一个轻量执行可靠性层**，而不是重写、不是新增用户入口、更不是做通用 Agent Framework。

---

## 1. 当前真实架构

### 1.1 历史入口分层（当前产品策略：Skill/MCP 主产品，桌面端可选）

| 入口 | 落点 | 用户操作 |
|---|---|---|
| **Skill** | `SKILL.md` + `scripts/` + `references/` + `subskills/` | 安装后对 Codex / Claude / Cursor / OpenClaw 说话，Agent 读 SOP 并调用脚本 |
| **MCP** | `mcp-server/server.py`（FastMCP + Pydantic，stdio） | 安装后 Agent 自动 Tool Calling |
| **CAD Studio** | `apps/workbench-ui/`（React+Tauri 前端）+ `apps/desktop/cad_workbench/`（Python worker）+ `scripts/cad_studio.py`（队列 CLI） | 图形界面提交任务 / CLI 操作队列 |

> 注意：`scripts/cad_studio.py` 的 `doctor/run/status/retry/cancel/...` 子命令是 **CAD Studio 的附属 CLI**，不是第四个用户入口。V2 的 debug/eval 命令（若需要）应挂在这里，而不是新建 CLI。

### 1.2 模块职责现状（与 V2 统一概念对照）

| V2 统一概念 | 当前实现 | 成熟度 |
|---|---|---|
| Skill（知识/SOP/开放规则） | `SKILL.md`、`SUBSKILLS.md`、`subskills/*`、`references/*` | 强 |
| MCP（协议） | `mcp-server/server.py`（约 60 工具，白名单、串行） | 强 |
| Capability Registry | `capabilities.yaml` + `scripts/capabilities.py` | **强（唯一真源已存在）** |
| Backend Router | `scripts/capabilities.py::resolve_operation_backend` + `backend_router.py` | **强（已存在）** |
| Execution Core | **无独立模块**，逻辑散落在 `queue_worker.py` / `sw_review.py` / `reviewer_gate.py` | **缺失（V2 目标）** |
| Worker | `queue_worker.py`（lease/heartbeat/cancel/stale/quarantine） | 强 |
| Reviewer | `sw_review.py`（CAD 几何）+ `reviewer_gate.py`（文件事实）+ DFM/Routing/工程图证据 | 强 |
| Artifact Ledger | `artifact_ledger.py`（SHA-256、producedThisRun） | 强 |
| Trace | `queue_worker.py::append_event`（JSONL，job 级）+ stdout/stderr 日志 | 部分（job 级，无 run/step 统一模型） |
| Golden Workflow Eval | `golden-workflows.yaml`（仅静态校验，无执行基准） | **缺失（V2 目标）** |

---

## 2. 当前真实调用链路

### 2.1 Skill 链路（Agent 直接执行脚本）

```
LLM Agent (Codex/Claude/OpenClaw)
  └─ 读 SKILL.md / SUBSKILLS.md / subskills/*/SKILL.md（SOP 与路由）
       ├─ python scripts/sw_preflight.py（依赖/SolidWorks 门禁，含用户授权安装）
       ├─ python scripts/backend_router.py --operation ...（只读后端选择）
       ├─ python scripts/sw_capability_probe.py（能力/类型库探测）
       └─ 执行 scripts/sw_*.py（sw_connect / sw_part / sw_assembly / sw_export / sw_motion ...）
            └─ sw_review.run_review()（多视角预览 + review_report.json + 几何/B-Rep 证据）
                 └─ 能力缺口：references/api-lookup.md → 官方 API Help/SDK → alternate backend → 最小实现 → 真机 → Review → 沉淀
```

关键点：Skill 链路的执行由**上层 Agent 直接驱动**，没有本地 Runtime 拦截。可靠执行的约束主要靠 **SKILL.md 的规则文本**（"结果自审查""未封装 API 规则""不得只报告保存成功"）落到 Agent 行为上。这意味着 **Execution Core 无法直接改写 Skill 路径**，它只能作为 Worker / MCP 的底层公共能力逐步复用；Skill 路径继续靠 SOP 文本 + `sw_review.py` 作为 Reviewer 指令。

### 2.2 MCP 链路（串行白名单工具）

```
Agent → MCP tool call
  └─ server.py @mcp.tool(...) → def solidworks_*/cadstudio_*/design_spec_*
       └─ _run_locked(op, format, load_automation, timeout=300s)
            ├─ _sw_lock.acquire(timeout)   # 全局 RLock，SolidWorks COM 串行
            ├─ _load_automation_modules()  # 惰性加载 sw_*.py
            ├─ _coinitialize()             # COM 线程初始化
            └─ op() → scripts/sw_*.py → _result(json|markdown)
                 └─ 异常 → _tool_error(结构化 status/error_type/message/suggestion)
```

关键点：MCP 已经**严格串行 + 锁超时 + 结构化错误 + 惰性加载 + `solidworks_recover` 模态对话框诊断**。这是最稳定的模块，V2 明确**不动**。

### 2.3 CAD Studio 链路（Worker + 门禁 + 账本 + 复核）

```
UI/CLI → 写 Job JSON 到 queue 目录
  └─ queue_worker.process_queue
       ├─ recover_stale_jobs()                 # lease 过期恢复 / 取消 / 坏任务隔离
       ├─ acquire_lock()（文件锁 + lease）      # 跨进程串行 + 领取
       └─ process_job()
            ├─ _capability_block_reasons()      # capabilities.yaml 能力门禁
            ├─ require_policy_approval()        # Policy Gate（危险操作人工审批）
            ├─ mark_job_claimed() → running → heartbeat/lease/cancel
            ├─ handler 分发：mock | dfm_review | codex_task | agent_task
            │    └─ run_agent_job()
            │         ├─ engineering_orchestrator（阶段 DAG 规划 + RetryPolicy）
            │         ├─ knowledge_retrieval（本地 RAG）
            │         └─ 子进程 Agent CLI + 心跳/续租/超时/取消
            ├─ write_artifact_ledger()           # 交付事实 + SHA-256 + producedThisRun
            └─ write_reviewer_gate()             # 文件级复核
                 └─ 终态：passed / review_required / failed / blocked / cancelled
  └─ write_worker_health()
```

关键点：**CAD Studio Worker 已经是事实上的 "Execution Runtime"**——它有 queue、policy gate、capability gate、ledger、reviewer gate、heartbeat、stale recovery、JSONL 事件流。V2 的 Execution Core 应作为这一链路里 "handler → verification → recovery decision" 的**统一抽象**，而不是另起炉灶替代 Queue/Worker/Ledger。

---

## 3. 已存在且可直接复用的能力盘点

### 3.1 Retry（分散、非统一）

| 位置 | 机制 |
|---|---|
| `scripts/sw_macro_guard.py` | VBA 宏校验失败重试 1–2 次 + 本地模板兜底（立方体/圆柱/拉伸/草图） |
| `scripts/sw_assembly.py::add_component` | `AddComponent4` 失败 → `AddComponent5` 重试（SW2024 中文版） |
| `scripts/sw_connect.py` / `sw_part.py` | 中英文基准面名称兜底切换 |
| `queue_worker.py` | `QUEUE_WRITE_RETRIES=24` 原子文件替换退避（Windows 文件锁） |
| `engineering_orchestrator.py::RetryPolicy` | 阶段级 `max_attempts/strategy/retryable_failures/fallback`（**规划层，非执行层**） |

结论：重试思想已存在，但**没有结构化错误分类驱动的执行层重试**。V2 的 Recovery Engine 要把它统一为「分类 → 决策」，而不是再写一个 `try/except/retry 3`。

### 3.2 Review / Verification（强，双层级互补）

- **CAD 几何层**：`scripts/sw_review.py` — `run_review` / `evaluate_review_report` / `collect_geometry_measurements` / `validate_hole_positions` / `inspect_pdf_text_layout` / `review_drawing_layout`；输出 `pass/warn/fail` + `manual_review_required` + `retryable`。
- **文件事实层**：`reviewer_gate.py::evaluate_ledger` — 文件存在/非空/SHA-256/格式特征（STEP/STL/DXF/PDF/DWG 头标记）+ 规格一致性（外形三元尺寸、孔径）。
- **领域证据层**：`dfm_review.py`、`routing_review.py`、`sw_drawing_review.py`、FEA 证据、工程图子技能 `drawing_review.py`。

结论：**Reviewer 已经很强，严禁重造。** Execution Core 的 Verification Adapter 只做「调用现有 Review + 解释结果 + 决定状态」。

### 3.3 Routing（强，唯一真源已存在）

`scripts/capabilities.py` 已提供：`load_capabilities`、`capability_index`、`backend_index`、`operation_route_index`、`resolve_operation_backend`、`capability_level`、`unattended_allowed`、`capability_snapshot`、`backend_route_snapshot`。

`resolve_operation_backend` 已实现：语义过滤（automation_equivalent/exact_native...）、版本 blocker（`KNOWN_HOST_REVISION_BLOCKER`）、加载项/许可证要求（`MISSING_RUNTIME_REQUIREMENT`）、候选优先级、`unavailable`（无兼容后端）。

结论：**Backend Router 已完整。** `scripts/core/capability.py` 只能是 Adapter/Facade，绝不能复制这套逻辑。

### 3.4 Trace / Logs（job 级 JSONL 已存在）

`queue_worker.py` 已有：
- `append_event()` → `queue/events/{job_id}.jsonl`，事件名如 `run.claimed` / `step.started` / `run.heartbeat` / `run.blocked` / `run.failed` / `run.passed` / `policy.approval_required` / `artifact.ledger_written` / `review.gate_completed`。
- `logs/{job_id}.stdout.log` / `.stderr.log`。

结论：JSONL 事件流已存在，但**是 job 维度、无统一 `run_id/trace_id/step_id/parent_step_id` 模型**，且与 Artifact Ledger 的职责边界在文档上未固化。V2 Trace 复用现有 `queue/` 目录与 JSONL 追加语义，补上统一 step 维度。

### 3.5 Queue State / Worker Health（强）

`queue_worker.py`：`read_job/write_job`（原子）、`acquire_lock/release_lock`（OS 文件锁 + lease）、`recover_stale_jobs`、`quarantine_bad_job`、`mark_job_claimed`、`refresh_job_heartbeat`、`request_cancel`、取消标记、`watch_queue`。
`worker_health.py`：`write_worker_health`、`count_jobs`、`health_level`（healthy/attention/warning/error）。

Job 终态：`passed / review_required / failed / cancelled / blocked`；非可执行态：`approval_required`。

结论：**Queue 与 Worker 是稳定的、不可替代的。** Execution Core 不替代它们。

### 3.6 Artifact Ledger（强）

`artifact_ledger.py`：`sha256_file`、`collect_artifact_paths`、`describe_artifact`（exists/size/sha256/**producedThisRun** via baseline snapshot）、`build_artifact_ledger`、`write_artifact_ledger`。

结论：**Artifact Ledger = 交付事实**，已完整。Trace 不许复制它。

### 3.7 Error Handling（弱，无结构化分类）

现状：`sw_preflight` 有 `DependencyInstallDeclined`/`SolidWorksNotInstalledError`；MCP 有 `_tool_error` 结构化 payload；`queue_worker` 有 `JobCancelled`/`JobBlocked`/兜底 `except Exception → failed`。

缺失：**没有 `TRANSIENT/INVALID_ARGUMENT/ENVIRONMENT_MISSING/TOOL_UNAVAILABLE/BACKEND_UNAVAILABLE/VERIFICATION_FAILED/USER_ACTION_REQUIRED/POLICY_BLOCKED/CAPABILITY_GAP/FATAL` 分类**，也没有对应的统一 `RecoveryDecision`。

### 3.8 Policy Gate（强）

`agent_contracts.py`：`DANGEROUS_CAPABILITIES`、`policy_reasons`、`require_policy_approval`、`is_policy_approved`（批准范围复核：批准后原因变化会重新拦截）。

结论：Policy Gate 已权威。Execution Core 的 `POLICY_BLOCKED` 分类只能尊重它，**Runtime 不得绕过**。

### 3.9 Capability Gap 开放机制（Skill 层已有，代码层缺失）

现状：**完全在 SKILL.md / references 文本层**：
- `SKILL.md` "未封装 API 规则"：现有能力不足 → 查 `references/api-lookup.md` → 官方 API Help / 本地 SDK → `references/language-backend-routing.md` 找 alternate backend → 最小实现 → 真机运行 → `sw_review.py` → 沉淀。
- `references/api-lookup.md` 给出查证模板、最小验证脚本要求、沉淀规则。

缺失：**没有结构化的 `CAPABILITY_GAP` 返回值**。`resolve_operation_backend` 返回的是 `blocked/UNKNOWN_OPERATION_ROUTE` 或 `unavailable/NO_COMPATIBLE_BACKEND_AVAILABLE`，语义接近但不等价于「这是能力缺口、交还上层 Agent 解决」。

---

## 4. capabilities.yaml 当前承担职责（唯一真源）

`capabilities.yaml`（`schema_version: 1.0`）实际承担 **四类职责**：

1. **能力成熟度清单**（`capabilities[]`，29 项）：`id/level/backends/verified_versions/dependencies/limitations/allowed_modes`（部分含 `skills`/`mcp_tools`）。level ∈ {verified, pilot, reference_only, not_implemented}。
2. **后端目录**（`backend_catalog`，10 项）：`language/runtime/suitable_for/limitations`。
3. **原子操作路由**（`operation_routes`，14 项）：`id/capability_ids/candidates[{backend,semantics,priority}]/review_required/blocked_revisions/requires/notes/blocked_reason`。
4. **版本矩阵事实**（`verified_versions.solidworks/autocad`）。

**关键结论：`capabilities.yaml` 已经是 Capability 的唯一真源，且承担了「能力门禁 + 后端路由 + 版本矩阵」三重职责。** V2 严禁新增 `tool_registry.yaml` 等重复配置。若要扩展，只允许加**可选**字段（`risk_level / review_required / preferred_backend / fallback_backends / retry_policy / timeout / side_effects`），且 `scripts/capabilities.py::load_capabilities` 的校验必须对缺失字段保持向后兼容。

---

## 5. 重复风险与过度设计风险

### 5.1 已存在的重复（V2 不得再复制）

1. **能力表重复**：`engineering_orchestrator.py::CAPABILITIES` 内嵌了一份能力映射（含 `CapabilityLevel`/skills/mcp_tools），与 `capabilities.yaml` 有重叠。这是历史存在的事实，**V2 不去重构它**，但新增代码不得再造第三份能力表。
2. **`resolve_operation_backend` 已实现路由**：任何「重新实现后端选择」都是重复造轮子。

### 5.2 V2 必须避免的重复

1. 再造 `tool_registry.yaml / runtime_capabilities.yaml / agent_capabilities.json`。
2. 再造一套 Reviewer（`sw_review.py` + `reviewer_gate.py` 已够）。
3. 再造一套 Artifact Ledger（Trace 只记录过程，不记录交付事实）。
4. 再造一套 Fake/Mock 系统（`tests/fakes.py` 已有统一 COM 替身，Eval 应复用/邻接）。
5. 再造一套 Golden Workflow（`golden-workflows.yaml` 已存在，只缺执行基准）。

### 5.3 过度设计风险（重点提醒）

1. **做成通用 Agent Framework**：Planner/Executor/Reviewer/Manager/Supervisor 多 Agent 套娃。本项目上层 Agent 已负责 Planning，Execution Core 只做 Execute/Observe/Verify/Recover/Trace。
2. **复杂状态机**：RunStatus/StepStatus 用轻量 Enum 即可，不要搞 DAG 状态机/事件溯源。
3. **独立 Trace Server / Runtime daemon**：Trace 是 append-only JSONL 落到现有 `queue/`，绝不启动额外服务。
4. **Runtime 自己联网**：第一版 V2 不做 Web/API Discovery；能力缺口交还上层 Agent。
5. **MCP 全量重包装**：60+ 工具、COM 锁、Pydantic schema 都是稳定的，Execution Core 作为底层能力逐步复用，绝不反向重写。
6. **命名造词**：只用「Execution Core」一个词，禁止 Runtime Engine / Orchestrator / Workflow Engine / Agent Engine 等近义词混用。

---

## 6. V2 最小改造方案

### 6.1 新增内部模块（`scripts/core/`，不是用户入口）

```
scripts/core/
├── __init__.py
├── state.py        # 轻量状态模型（JSON 可序列化、带 version）
├── capability.py   # Adapter/Facade，复用 scripts/capabilities.py + capabilities.yaml
├── trace.py        # append-only JSONL Trace，复用 queue 目录
├── recovery.py     # ErrorKind 分类 + RecoveryDecision 映射
└── execution.py    # Execution Core facade：Execute → Observe → Verify → Recover → Trace
```

`sync_bundled_skill.py` 已按整个 `scripts/` 目录同步，新增 `scripts/core/` 会自动进入桌面 bundle，无需改打包脚本。

### 6.2 各模块要点

**`state.py`**
- `RunStatus`：CREATED / RUNNING / VERIFYING / RETRYING / BLOCKED / FAILED / COMPLETED
- `StepStatus`：PENDING / RUNNING / SUCCESS / FAILED / VERIFYING / RETRYING / BLOCKED
- `RunContext`（run_id/trace_id/goal/status/started_at/finished_at/current_step/steps/artifacts/evidence/errors/retry_count/metadata）
- `StepRecord`（step_id/parent_step_id/tool_name/capability_id/backend/status/started_at/finished_at/duration_ms/arguments_summary/result_summary/error_code/retryable/artifacts/evidence/verification）
- `ExecutionResult` / `VerificationResult` / `RecoveryDecision`
- 约束：JSON 可序列化；schema 有 version；**不与 CAD Studio Queue Schema 强绑定**；可被 Worker/MCP/CLI 复用；**不复制现有 Job 对象**；不存 API Key/完整 Prompt/秘密/无必要绝对路径。

**`capability.py`（Facade）**
- 提供：`get_capability` / `get_operation_route` / `resolve_backend` / `requires_review` / `get_capability_status` / `get_backend_candidates`
- 全部委托 `scripts/capabilities.py`，零逻辑复制。

**`trace.py`**
- 追加 JSONL；事件：`run.created / step.started / tool.called / tool.succeeded / tool.failed / verification.started / verification.passed / verification.failed / recovery.retry / recovery.backend_fallback / capability.gap / run.blocked / run.failed / run.completed`
- 复用现有 `queue/` 运行目录（优先 `queue/events/` 或新增 `queue/trace/`，Phase 2 定，倾向复用 events 目录避免新概念）；**禁止写仓库根目录**。

**`recovery.py`**
- `ErrorKind`：TRANSIENT / INVALID_ARGUMENT / ENVIRONMENT_MISSING / TOOL_UNAVAILABLE / BACKEND_UNAVAILABLE / VERIFICATION_FAILED / USER_ACTION_REQUIRED / POLICY_BLOCKED / CAPABILITY_GAP / FATAL
- `RecoveryDecision`：RETRY / FALLBACK_BACKEND / REPLAN_REQUIRED / USER_ACTION_REQUIRED / BLOCK / FAIL
- 规则：TRANSIENT→有限 retry；INVALID_ARGUMENT→交还上层 Agent；BACKEND_UNAVAILABLE→backend_router fallback；ENVIRONMENT_MISSING→有合法 fallback 才 fallback 否则 blocked；VERIFICATION_FAILED→禁止 success→repair/replan；USER_ACTION_REQUIRED→blocked；POLICY_BLOCKED→尊重 Policy Gate 不可绕过；FATAL→failed。
- retry 必须有上限、可追踪、可测试、防死循环。

**`execution.py`（核心门禁）**
- 确立「Tool Success != Task Success」：`requires_review` 的能力必须 Execute→Verification→PASS→COMPLETED；Verification FAIL 禁止 COMPLETED，必须进入 Recovery/Replan/Blocked/Failed 之一。
- 只做多 Step 执行 + 统一 Trace + 状态决策，不写复杂 Planner。

### 6.3 Golden Workflow Eval（`tests/evals/`）

- 复用 `golden-workflows.yaml`（保持 `target_first_pass_rate` 兼容），可选新增 `must_review/max_retries/max_tool_calls/expected_capabilities/required_artifacts`。
- 三类测试：Happy Path / Failure Path（Tool success→Artifact 缺失→Verification Fail→禁止 Completed）/ Recovery Path（Primary Backend Fail→Fallback→Success→Verification Pass）；额外 Capability Gap。
- 统计：Task Success Rate / First Pass Success Rate / Retry Rate / Recovery Success Rate / **False Completion Rate**（执行层报成功但 Verifier 判失败的比例）/ Average Tool Calls / Average Duration。
- 输出：`eval_report.json` + `eval_report.md`。
- CI 不要求真实 SolidWorks；用 Fake Backend / Mock Tool / Mock Reviewer（复用/邻接 `tests/fakes.py`）。

---

## 7. 计划修改文件

| 文件 | 改动 | 阶段 |
|---|---|---|
| `docs/architecture/v2-audit.md` | 本审计报告（新增） | Phase 1 ✅ |
| `scripts/core/__init__.py` | 新增 | Phase 2 |
| `scripts/core/state.py` | 新增状态模型 | Phase 2 |
| `scripts/core/capability.py` | 新增 Facade | Phase 2 |
| `scripts/core/trace.py` | 新增 JSONL Trace | Phase 2 |
| `scripts/core/recovery.py` | 新增错误分类与恢复决策 | Phase 4 |
| `scripts/core/execution.py` | 新增 Execution Core facade | Phase 3–4 |
| `scripts/core/verification.py`（如独立）或并入 execution.py | Verification Adapter（复用 sw_review + reviewer_gate） | Phase 3 |
| `tests/test_core_state.py` 等 | 状态转换/Retry 上限/fallback/POLICY_BLOCKED/CAPABILITY_GAP/Trace JSONL 等单测 | Phase 2–4 |
| `tests/evals/runner.py`（当时拟名 `golden_workflow_eval.py`） | Golden Workflow Eval + eval_report 输出；实际落地为 `runner.py` + `metrics.py` + `baseline.json` | Phase 6 |
| `golden-workflows.yaml` | 仅追加**可选**字段（must_review/max_retries/...），旧 workflow 不改 | Phase 6 |
| `apps/desktop/cad_workbench/queue_worker.py` | 最小侵入：在 handler 与 ledger/reviewer 之间接入 Execution Context + Verification + Recovery Decision，**不重写** | Phase 5 |
| `scripts/cad_studio.py` | （可选）挂 `inspect-trace` / `eval` 到 debug 子命令；非必需可跳过 | Phase 8 |
| `capabilities.yaml` | （可选）仅追加可选字段 risk_level/review_required/...；默认可推迟 | Phase 2 可选 |
| `docs/architecture/execution-core.md` | 新增技术文档 | Phase 8 |
| `README.md` | 用户侧只加一句「V2 内部加入可靠执行、自动验证和失败恢复，无需额外启动服务」 | Phase 8 |

---

## 8. 明确不会修改的模块

| 模块 | 理由 |
|---|---|
| `mcp-server/server.py` | 60+ 工具、Pydantic schema、`_sw_lock` 串行、锁超时、`_coinitialize`、`_run_locked`、`solidworks_recover` 全部稳定；SolidWorks COM 必须继续串行，禁止第二套锁 |
| `scripts/sw_*.py`（COM 封装：sw_connect/sw_part/sw_assembly/sw_export/sw_motion/sw_drawing/sw_hole_features/sw_measure/sw_edge_select/sw_document_data/sw_delivery/sw_appearance/sw_session/sw_macro_guard...） | 已真机回归的稳定能力，只复用不改写 |
| `scripts/capabilities.py` + `scripts/backend_router.py` | 路由逻辑已完整，作为真源复用 |
| `apps/desktop/cad_workbench/reviewer_gate.py` | Reviewer Gate 已完整 |
| `apps/desktop/cad_workbench/artifact_ledger.py` | Artifact Ledger 已完整 |
| `apps/desktop/cad_workbench/worker_health.py` | Worker Health 已完整 |
| `apps/desktop/cad_workbench/agent_contracts.py` | Policy Gate 已权威 |
| `apps/desktop/cad_workbench/agent_providers.py` | Provider Adapter 稳定 |
| `apps/desktop/cad_workbench/knowledge_retrieval.py` | RAG 稳定 |
| `apps/desktop/cad_workbench/engineering_orchestrator.py` | 阶段 DAG 稳定（其内嵌能力表是历史事实，V2 不重构） |
| `apps/workbench-ui/`（前端） | 用户界面不变 |
| `SKILL.md` / `SUBSKILLS.md` / 全部 `subskills/*` | 用户 SOP 不变；开放能力机制文本保留 |
| `install.js` / `manifest.json` / `package.json` / `setup.py` / `pyproject.toml` / 注册器脚本 | 安装与打包不变 |
| `scripts/sync_bundled_skill.py` | 已按目录同步 `scripts/`，自动包含 `scripts/core/`，无需改 |

> `queue_worker.py` 是**唯一**计划最小修改的运行时代码，且只做「在既有 handler→ledger→reviewer 边界接入 Execution Core」的最小侵入，不重写其 Queue/Lease/Heartbeat/Policy Gate 逻辑。

---

## 9. 关键兼容性约束（V2 全程红线）

1. 不新增用户入口、不新增启动服务（runtime/executor/orchestrator/trace server/eval server 均禁止）。
2. `capabilities.yaml` 继续是唯一能力真源；只允许追加可选字段。
3. MCP Tool Name / Input Schema 零破坏；SolidWorks COM 串行锁零破坏。
4. Policy Gate / Approval 权威不可被 Runtime 绕过。
5. Worker Health / Heartbeat / Stale Recovery / Artifact Ledger 继续工作。
6. 运行时数据（Trace/Log/Artifact）只写 `queue/ logs/ artifacts/` 等现有运行目录，不写源码仓库根目录。
7. CI 不要求真实 SolidWorks；真机回归保持单独自托管执行。
8. 最终用户仍只需「安装 → 对 AI 说话 → 得到可信结果」。

---

## 10. 核心结论

- **当前项目已经是半个 "Execution Runtime"**：queue、policy gate、capability gate、backend router、reviewer gate、artifact ledger、JSONL 事件流、stale recovery、heartbeat 全部齐备。
- **V2 真正要新增的最小模块只有 5 个文件**：`state.py` / `capability.py`(facade) / `trace.py` / `recovery.py` / `execution.py`，外加 `verification` 的薄 adapter 和 Golden Workflow Eval。
- **真正的工程价值**在于：把「Tool Success ≠ Task Success」「结构化错误分类→恢复决策」「统一 run/step Trace」「能力缺口结构化返回」这四条**目前散落、隐式、依赖 Prompt 文本**的可靠执行思想，收敛成**可复用、可单测、可量化**的轻量执行可靠性层。
- **最大的风险不是写不出来，而是写多了**：任何一个「再造能力表 / 再造 Reviewer / 再造 Ledger / 再造多 Agent / 再造锁 / 再启动一个服务」的动作都会把一次「内部可靠性升级」变成「过度设计」。因此每个 Phase 都要做三查：是否重复造轮子、是否破坏兼容、是否新增了用户复杂度。

---

## 11. Phase 2 入口前待确认事项（请求用户拍板）

1. **Trace 落盘位置**：复用现有 `queue/events/{job_id}.jsonl`（扩展 schema 加 step_id），还是新增 `queue/trace/{run_id}.jsonl`？审计建议：**复用 `queue/events/` 目录**，在事件中补 `schema_version`、`run_id/trace_id/step_id/parent_step_id`，避免新增顶层概念。
2. **Verification Adapter 是否独立成 `scripts/core/verification.py`**：审计建议独立，职责单一（复用 sw_review + reviewer_gate），也可并入 execution.py。默认建议独立。
3. **Phase 5 Worker 接入深度**：是否本轮就把 `queue_worker.process_job` 接入 Execution Core，还是先把 `scripts/core/` 立住、Worker 接入留到回归稳定后再做？审计建议：**按顺序 Phase 5 做最小接入**，且只包裹 handler→verification→recovery 边界。
4. **capabilities.yaml 可选字段**：是否本轮就追加 `risk_level/review_required/...` 可选字段，还是完全不动 YAML、只靠 facade 读取现有字段？审计建议：**Phase 2 默认不动 YAML**，facade 先复用现有字段，确有必要再加可选字段。

以上四点确认后即可进入 Phase 2（State + Capability Adapter + Trace）。
