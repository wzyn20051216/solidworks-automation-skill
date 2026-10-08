# V2 Evaluation —— Golden Workflow Reliability Eval

## 1. 为什么需要 Eval

V2 的目标是「让已有能力执行得更可靠」。要做到这一点，不能只靠主观判断，而需要一套
**可重复、可量化、可 CI** 的可靠性基准，回答：

1. 正常任务到底成功了多少？（Nominal Task Success Rate）
2. 有多少正常任务第一次就成功？（Nominal First Pass Success Rate）
3. 失败以后能不能恢复？（Recovery Success Rate）
4. 系统能不能正确识别注入的故障？（Failure Detection / Expected Outcome Accuracy）
5. 有没有「Tool 说成功但 Verification 失败，最终却仍被当作成功」的**假成功泄漏**？（Escaped False Completion Rate）

这些数字可信，因为它来自 **deterministic 的 Execution Core + Fake Handler/Reviewer**，
不受模型随机性、网络、真机 CAD 环境影响。

## 2. Golden Workflow 是什么

`golden-workflows.yaml` 是 Golden Workflow 的**唯一真源**（`schema_version: 1.0`），
包含 `target_first_pass_rate` 与 10 个 workflow。Eval **直接从该文件派生场景**，不复制
内容、不新增第二份配置。现有字段继续工作。

## 3. Scenario 分类（benchmark_group）

Eval 场景必须按**口径**拆分，绝不能把故意失败的 Scenario 与正常业务 Scenario 混在
同一个分母里。分类由 scenario type **deterministic** 确定：

| category | scenario types | 用途 |
|---|---|---|
| `nominal` | happy | 正常业务，用于 first-pass target 比较 |
| `recovery` | transient_recovery、backend_fallback | 失败后脚本化恢复 |
| `fault_injection` | verification_failure、reviewer_blocked、retry_exhausted | 故意注入故障，验证检测能力 |
| `guardrail` | warning、policy_block、user_action_required、capability_gap | 验证门禁/人工复核阻断正确性 |

## 4. Metrics 定义

### Nominal（只针对 nominal scenarios）

| 指标 | 定义 |
|---|---|
| nominal_task_success_rate | nominal 中 `terminal == completed` 的比例 |
| nominal_first_pass_success_rate | nominal 中 `completed` 且 1 次 attempt 且无 recovery 的比例 |
| nominal_average_tool_calls / duration | nominal 子集的均值 |

`target_first_pass_rate`（0.90）**只与 nominal_first_pass_success_rate 比较**。

### Robustness（recovery / fault_injection / guardrail）

| 指标 | 定义 |
|---|---|
| expected_outcome_accuracy | `terminal == expected_terminal_status` 的比例（Robustness 最重要的指标） |
| recovery_success_rate | recovery 类别中 `completed` 的比例 |
| failure_detection_rate | fault_injection 中 `terminal != completed` 的比例（正确检测出注入的失败） |
| policy_block_accuracy | policy_block 中 `terminal == blocked` 的比例 |
| capability_gap_detection_rate | capability_gap 中 `terminal == failed` 的比例 |
| backend_fallback_decision_accuracy | backend_fallback 中 `terminal == completed` 的比例 |
| reviewer_block_detection_rate | reviewer_blocked 中 `terminal == blocked` 的比例 |
| retry_exhaustion_accuracy | retry_exhausted 中 `terminal == failed` 的比例 |

注意：**policy block 的正确结果就是 BLOCKED，capability gap 的正确结果就是 FAIL/REPLAN**，
它们**不是 task failure**，而是「正确处理」。因此 Robustness 用 `expected_outcome_accuracy`
而非 `task success` 衡量。

### Safety（假成功）

| 指标 | 定义 |
|---|---|
| raw_false_completion_incidence | Handler 报 success 且 Verification FAIL/BLOCKED / Handler 报 success 数。**可以高**，因为 fault-injection 故意制造这种情况。 |
| false_completion_detection_rate | 被 Verification 正确拦截的注入假成功候选 / 注入的假成功候选总数。目标趋近 100%。 |
| escaped_false_completion_rate | Handler 报 success 且 Verification FAIL/BLOCKED 且最终仍 `completed` 的比例。目标 **0**。 |

### Overall（诊断，不用于 target）

| 指标 | 定义 |
|---|---|
| overall_scenario_count | 总场景数 |
| overall_raw_task_completion_rate | 全量 `terminal == completed` 比例（仅诊断） |

## 5. False Completion 精确定义（修正后）

严格区分三层：

- **raw false positive**（Handler 假阳性）= `handler_success AND verification ∈ {FAIL, BLOCKED}`。
  这是「底层执行产生了假成功候选」的**发生率**，fault-injection 场景天然偏高，**不是系统的假成功泄漏率**。
- **detection rate**（检测率）= 注入的假成功候选中被 Verification 正确拦截的比例。**高 = Verification 有效**。
- **escaped rate**（泄漏率）= 假成功候选最终仍被当作 `completed` 的比例。**这才是真正的假成功泄漏**，目标为 0。

旧版把这三者混为一个 `false_completion_rate`（33.3%），会把「Verification 正确拦截了
11 个假成功候选」误读成「系统有 33.3% 假成功泄漏」。

## 6. 旧算法问题（为什么 59.5% / 29.7% / 33.3% 失真）

Phase 6 的旧算法把 37 个场景（10 happy + 10 verification_failure + 10 transient_recovery
+ 7 跨切面）**混在同一个分母**里算 first-pass 与 false completion：

- **29.7% first-pass**：10 个 happy + 1 个 warning 首次成功，除以全部 37（含故意失败场景），
  因此远低于真实业务首通率，且被拿去与 90% target 比较 → 误报 BELOW_TARGET。
- **33.3% false completion**：10 verification_failure + 1 reviewer_blocked 是**人为注入**的
  假成功候选，被 Verification 正确拦截；旧算法把它算成「假成功发生率」而非「泄漏率」，
  实际 escaped（泄漏）为 **0%**。

当前基线 v3：warning 归入人工复核 guardrail，不能宣称任务完成。`nominal_first_pass = 100%`（10/10）→ 与 90% target 比较 → **PASS**；
`escaped_false_completion = 0%` → 无假成功泄漏。
37 场景的原始完成比例为 21/37（56.8%），只供诊断；此前 11/11 和 59.5% 是将 warning 计入成功的历史口径。

## 7. deterministic fixture 设计

不调用 LLM / Web / 真机。Fake Handler（`success_handler`/`fail_handler`）、Fake Reviewer
（`pass/warn/fail/blocked/crash_reviewer`）、Fake Capability Facade、与
`core.recovery._EXCEPTION_KIND` 对齐的异常类型。Recovery 后续结果通过脚本化多 attempt
模拟（不修改生产 Worker 自动 retry）。

## 8. 如何运行 Eval

```powershell
python tests/evals/runner.py
```

输出 `eval_report.json` + `eval_report.md`（默认 `tests/evals/reports/`，已 gitignore）。

## 9. 如何读报告

报告分四块：Nominal Reliability（正常业务成功率 + target 比较）、Robustness（正确处理率 +
检测率）、Safety（假成功 incidence/detection/escaped）、Overall Diagnostic（仅诊断）。

- `Nominal First Pass Success Rate` vs `Target` → `PASS/BELOW_TARGET`。
- `Escaped False Completion Rate` → 必须 0。
- `Expected Outcome Accuracy` → Robustness 正确处理的综合指标。

## 10. 当前 Eval 不覆盖什么

- 真实 SolidWorks / AutoCAD 执行（由真机回归覆盖）。
- 真实 LLM Planning / Tool Calling 质量、模型对比、token 成本、LLM judge。
- 网络 / 外部 API。

## 11. 未来 Live Agent Eval 如何扩展

Phase 6/7.5 只测 **Execution Reliability**（deterministic）。未来可加 Live Agent Eval
（真实 Codex/Claude 走真实 Skill + Worker），复用同一套 `EvalRecord` / `metrics` /
`EvalReport`，只替换 `run_scenario` 的 handler 为真实 Agent 调用。
