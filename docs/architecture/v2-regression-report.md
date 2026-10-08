# V2 Regression Report & Reliability Baseline

> 此文保留 Phase 7/7.5 的历史记录。2026-10-08 后使用基线 v3：nominal 10/10，warning 阻断等待人工复核；当前验证结果见 [`scheme-b-reliability.md`](scheme-b-reliability.md)。

> 阶段：Phase 7（Full Regression + Baseline Freeze）+ Phase 7.5（Evaluation Semantics Correction）
> 结论：V2 未造成任何回归；Eval 口径已修正（Nominal/Robustness/Safety 分离）；Baseline 已按修正后口径冻结。

## 1. V2 架构版本

- Execution Core：`scripts/core/`（state / capability / trace / verification / recovery / execution）
- 内部执行链：`State → Capability Facade → Trace → Verification Adapter → Recovery Decision → Execution Core`
- 三个用户入口保持不变：Skill / MCP / CAD Studio
- 全 V2 对既有文件的修改仅一处：`apps/desktop/cad_workbench/queue_worker.py`（+58 / −1）

## 2. Regression Matrix

| Subsystem | Tests | Result | Environment |
|---|---|---|---|
| Core State / Capability / Trace | 36 | PASS | CI-safe |
| Core Verification / Recovery / Execution | 62 | PASS | CI-safe |
| Golden Eval（metrics / runner / baseline） | 27 | PASS | CI-safe |
| Worker / Reviewer / Ledger / Policy / Health / Orchestrator | 94 | PASS | CI-safe |
| 其他单元（sw/mcp/design/dfm/routing/fea/headless/drawing/subskills/…） | 521 | PASS | CI-safe |
| Release Check（内嵌 Skill 打包） | 1 | SKIP | 需先运行 `sync_bundled_skill.py` |
| **pytest 合计** | **740 passed / 1 skipped** | **0 failed** | CI-safe |
| SolidWorks 真机回归（`solidworks_*_regression.py`） | — | NOT RUN | Windows + SolidWorks |
| AutoCAD 真机回归（`autocad_*_regression.py`） | — | NOT RUN | Windows + AutoCAD |
| CAD Studio 周回归（`cad_studio_weekly_regression.py`） | — | NOT RUN | Windows + CAD |
| CalculiX 外部求解器（`calculix_*_regression.py`） | — | NOT RUN | CalculiX |

> 真机/外部求解器回归由 `.github/workflows/windows-cad-regression.yml`（自托管 Windows + CAD）单独执行。

## 3. Backward Compatibility

| 项 | 结果 |
|---|---|
| A. Skill（SKILL.md 使用方式） | 未修改，完全不变 |
| B. MCP（Tool Name / Input Schema / 启动方式） | 未修改，完全不变 |
| C. CLI（`cad_studio.py` 命令） | 未修改，完全不变 |
| D. CAD Studio（旧 Queue Job / 旧事件 / Worker 状态语义） | 旧 Job 无 sidecar 字段仍正常；旧事件无 run_id/step_id 仍可读；Worker 终态语义未破坏 |
| E. capabilities.yaml | 仍为唯一能力真源，未修改 |
| F. golden-workflows.yaml | 保持旧格式兼容，未修改 |

## 4. Official Eval Metrics（Phase 7.5 修正后口径）

`python tests/evals/runner.py`（完整 37 scenario set，分四组口径）：

### Nominal Reliability（11 nominal scenarios）

| 指标 | 值 |
|---|---|
| Nominal Scenarios | 11 |
| Nominal Task Success Rate | 100.0% |
| Nominal First Pass Success Rate | 100.0% |
| Target First Pass | 90% |
| **Target Status** | **PASS** |
| Average Tool Calls | 1.0 |
| Average Duration | 0.0 ms |

### Robustness（26 robustness scenarios）

| 指标 | 值 |
|---|---|
| Robustness Scenarios | 26 |
| Expected Outcome Accuracy | 100.0% |
| Recovery Success Rate | 100.0% |
| Failure Detection Rate | 100.0% |
| Policy Block Accuracy | 100.0% |
| Capability Gap Detection | 100.0% |
| Backend Fallback Decision Accuracy | 100.0% |
| Reviewer Block Detection | 100.0% |
| Retry Exhaustion Accuracy | 100.0% |

### Safety

| 指标 | 值 |
|---|---|
| Raw Handler False-Positive Incidence | 33.3%（fault-injection 故意注入） |
| False-Completion Detection Rate | 100.0% |
| **Escaped False Completion Rate** | **0.0%** |

### Overall Diagnostic（不用于 target）

| 指标 | 值 |
|---|---|
| Overall Scenario Count | 37 |
| Overall Raw Task Completion Rate | 59.5%（仅诊断） |
| Overall Average Tool Calls | 1.27 |

## 5. Reliability Baseline（Phase 7.5 修正后）

已冻结到 `tests/evals/baseline.json`（`schema_version: 2.0`，`baseline_version: 2`）：

- `nominal_metrics`：11 scenarios / task_success 1.0 / first_pass 1.0
- `robustness_metrics`：26 scenarios / expected_outcome_accuracy 1.0 / recovery 1.0 / detection 1.0
- `safety_metrics`：raw_false_positive 0.3333 / detection 1.0 / **escaped 0.0**
- `overall_diagnostic_metrics`：37 scenarios / raw completion 0.5946

**Release Guard**（`tests/test_eval_baseline.py`）：
- `nominal_first_pass_success_rate >= target_first_pass_rate`（1.0 ≥ 0.90 ✅）
- `escaped_false_completion_rate == 0` ✅
- `expected_outcome_accuracy` 不劣化 ✅

## 6. CI-safe / Live-test 边界

- **CI-safe**：全部 pytest 测试（Windows CI + pywin32/comtypes，无需真实 CAD 二进制）。
- **CAD-live**：SolidWorks / AutoCAD / CAD Studio 真机回归脚本（非 `test_*.py`，不经 pytest 收集）。
- **external-solver**：CalculiX 回归脚本。

## 7. 已知限制与口径说明

- Eval 是 **Deterministic Execution Reliability Benchmark**（Fake Handler/Reviewer），
  **不是**真实用户成功率、真实 SolidWorks 全场景成功率、真实 Codex 智能水平或生产 SLA。
- duration ≈ 0ms（fake handler 瞬时），待 Live Agent Eval 才有真实耗时。
- `Overall Raw Task Completion Rate`（59.5%）仅诊断，不用于 target。
- **Phase 7.5 语义修正**：旧算法把 nominal 与 fault-injection 混在同一分母，导致
  - 29.7% first-pass（被拿去与 90% 比较 → 误报 BELOW_TARGET）；
  - 33.3% false completion（实为「Verification 正确拦截 11 个注入假成功候选」，非泄漏率）。
  修正后 nominal first-pass = 100%（PASS），escaped false completion = 0%。
- `test_release_check` skip：需先运行 `python scripts/sync_bundled_skill.py`。

## 8. 发现的问题

**无生产代码 bug。** Phase 7.5 发现并修正的是 **Eval 语义口径问题**（指标混合统计），
已通过「分类 + 分组指标 + 假成功三层定义」解决，未触碰任何生产执行代码。

## 9. Production Code 是否发生变化

全 V2 仅修改 1 个既有文件：`apps/desktop/cad_workbench/queue_worker.py`（+58/−1，Phase 5
最小接入）。Phase 6–7.5 未修改任何生产代码（只改 `tests/evals/*`、`tests/test_eval_*`、docs）。

核心模块行数（无膨胀，职责单一）：state 373 / capability 125 / trace 166 / verification 295 /
recovery 432 / execution 255。未吸收 Worker / Planner / Reviewer / Router 逻辑。

## 10. 是否可以进入 V2 Documentation Freeze

**可以（待确认）。** V2 已完成：架构审计 → 状态/能力/Trace → 验证适配 → 恢复决策 →
执行编排 + Worker 最小接入 → 可靠性 Eval → 回归 + Baseline 冻结 → Eval 语义修正。
下一步进入 Phase 8（Documentation Freeze：补 `docs/architecture/execution-core.md` +
README 一句话说明）。
