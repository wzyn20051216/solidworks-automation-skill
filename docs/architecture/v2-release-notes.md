# V2 Release Notes (Draft)

> SolidWorks Automation Skill V2 —— 内部可靠性架构升级。

## Added

- **Execution Core**（`scripts/core/`）：把 State / Capability / Trace / Verification / Recovery
  串成一条内部执行链，包裹现有 Handler 执行。
- **State model**（`state.py`）：轻量 Run/Step/Execution/Verification/Recovery 状态模型。
- **Capability Facade**（`capability.py`）：复用 `capabilities.yaml` 唯一真源的薄适配层。
- **Verification Adapter**（`verification.py`）：把既有 Reviewer 结果统一为 PASS/WARN/FAIL/BLOCKED。
- **Recovery Decision Layer**（`recovery.py`）：10 类错误分类 + 6 类恢复决策（只决策，不默认执行）。
- **Trace integration**（`trace.py`）：复用 `queue/events/` 的 append-only 执行历史。
- **Golden Workflow Reliability Eval**（`tests/evals/`）：deterministic 可靠性基准。

## Preserved

- 现有 Skill 使用方式、MCP Tool Name / Input Schema、CLI 命令、CAD Studio Queue 状态语义全部不变。
- Worker / Reviewer / Artifact Ledger / Policy Gate 均未重写。
- `capabilities.yaml` 仍唯一能力真源，`golden-workflows.yaml` 向后兼容。
- 新增字段全部 additive / optional。

## Metrics（Deterministic Execution Reliability Benchmark，37 scenarios）

| 指标 | 值 |
|---|---|
| Nominal First-Pass Success | 100% (10/10，基线 v3) |
| Nominal Task Success | 100% |
| Failure Detection | 100% |
| Policy Block Accuracy | 100% |
| Capability Gap Accuracy | 100% |
| Backend Fallback Decision Accuracy | 100% |
| False-Completion Detection | 100% |
| Escaped False-Completion | 0% |

## Limitations

- 2026-10-08 方案 B 将 warning/manual review 改为 blocked，补充 SolidWorks 2026 真机草图、阵列、文档归属和远程产物验收，详见 [`scheme-b-reliability.md`](scheme-b-reliability.md)。旧版本不在当前支持与验收范围。

- 上述 benchmark 是 **synthetic / deterministic**（Fake Handler/Reviewer + 故障注入），
  **不是**真实用户成功率、真实 SolidWorks 全场景成功率、LLM 智能水平或生产 SLA。
- Execution Core 不做自动 LLM Planning（上层 Agent 继续负责 Planning）。
- 不做自动 Web / API 能力发现（Capability Gap 交还上层 Agent）。
- Recovery 只做**决策**，自动 retry / fallback / replan 动作仍由 Worker / 上层 Agent 控制，未默认开启。

## Docs

- [`docs/architecture/execution-core.md`](execution-core.md)
- [`docs/architecture/v2-evaluation.md`](v2-evaluation.md)
- [`docs/architecture/v2-regression-report.md`](v2-regression-report.md)
- [`docs/architecture/v2-audit.md`](v2-audit.md)
