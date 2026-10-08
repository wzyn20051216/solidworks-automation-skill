"""@brief Golden Workflow Reliability Eval Runner（deterministic，不调 LLM / 不联网）。

运行方式：``python tests/evals/runner.py``（仓库现有脚本风格）。

把 Scenario 拆成 Nominal / Robustness / Safety 三组口径：
- Nominal：正常业务（happy / warning），用于 first-pass target 比较；
- Robustness：recovery / fault_injection / guardrail，用 expected_outcome_accuracy 衡量；
- Safety：假成功候选的 incidence / detection / escaped。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from . import fixtures
    from .metrics import RECOVERABLE_ACTIONS, compute_metrics, scenario_category
    from .schemas import AttemptSpec, EvalRecord, EvalReport, EvalScenario
except ImportError:  # 脚本模式（python tests/evals/runner.py）时的兜底
    import fixtures  # type: ignore
    from metrics import RECOVERABLE_ACTIONS, compute_metrics, scenario_category  # type: ignore
    from schemas import AttemptSpec, EvalRecord, EvalReport, EvalScenario  # type: ignore

GOLDEN_WORKFLOWS = ROOT / "golden-workflows.yaml"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "reports"
SCHEMA_VERSION = "2.0"


def load_golden_workflows(path: str | Path | None = None) -> dict[str, Any]:
    """@brief 读取 golden-workflows.yaml（唯一 Golden Workflow 真源）。"""
    source = Path(path) if path else GOLDEN_WORKFLOWS
    return json.loads(source.read_text(encoding="utf-8"))


def _scenario(
    workflow_id: str,
    suffix: str,
    type_: str,
    name: str,
    caps: list[str],
    arts: list[str],
    terminal: str,
    attempts: list[AttemptSpec],
    max_retries: int = 2,
    capability_facade: Any = None,
    operation_id: str | None = None,
) -> EvalScenario:
    return EvalScenario(
        scenario_id=f"{workflow_id}:{suffix}",
        name=name,
        type=type_,
        workflow_id=workflow_id,
        must_review=True,
        max_retries=max_retries,
        max_tool_calls=3,
        expected_capabilities=list(caps),
        required_artifacts=list(arts),
        expected_terminal_status=terminal,
        attempts=attempts,
        capability_facade=capability_facade,
        operation_id=operation_id,
        category=scenario_category(type_),
    )


def build_scenarios(payload: dict[str, Any] | None = None) -> list[EvalScenario]:
    """@brief 从 golden-workflows.yaml 派生场景：每 workflow 3 类 + 7 个跨切面场景。"""
    workflows = (payload or load_golden_workflows()).get("workflows", [])
    scenarios: list[EvalScenario] = []
    for workflow in workflows:
        wid = workflow["id"]
        caps = list(workflow.get("capabilities") or [])
        arts = list(workflow.get("required_artifacts") or [])
        scenarios.append(_scenario(wid, "happy", "happy", f"{wid} 正常路径", caps, arts, "completed", [
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), reviewer=fixtures.pass_reviewer()),
        ]))
        scenarios.append(_scenario(wid, "verification-failure", "verification_failure", f"{wid} 验证失败", caps, arts, "failed", [
            AttemptSpec(handler=fixtures.success_handler(fixtures.incomplete_result()), reviewer=fixtures.fail_reviewer()),
        ]))
        scenarios.append(_scenario(wid, "transient-recovery", "transient_recovery", f"{wid} 瞬时失败恢复", caps, arts, "completed", [
            AttemptSpec(handler=fixtures.fail_handler(TimeoutError("slow")), requires_review=False),
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), reviewer=fixtures.pass_reviewer()),
        ]))
    scenarios.extend(_cross_cutting_scenarios())
    return scenarios


def _cross_cutting_scenarios() -> list[EvalScenario]:
    """@brief 跨切面可靠性场景（backend fallback / gap / policy / user action / ...）。"""
    arts = ["step", "preview", "review_report"]
    caps = ["part_and_features"]
    fallback_facade = fixtures.FakeCapabilityFacade(
        candidates=[
            {"backend": "solidworks-com-pywin32", "priority": 10},
            {"backend": "solidworks-com-comtypes", "priority": 20},
        ]
    )

    def sc(suffix, type_, name, terminal, attempts, max_retries=2, facade=None, operation_id=None):
        return _scenario(
            "system", suffix, type_, name, caps, arts, terminal, attempts,
            max_retries=max_retries, capability_facade=facade, operation_id=operation_id,
        )

    return [
        sc("backend-fallback", "backend_fallback", "后端回退", "completed", [
            AttemptSpec(handler=fixtures.fail_handler(fixtures.SolidWorksConnectionError("conn")), requires_review=False),
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), reviewer=fixtures.pass_reviewer()),
        ], facade=fallback_facade, operation_id="solidworks_standard_automation"),
        sc("capability-gap", "capability_gap", "能力缺口", "failed", [
            AttemptSpec(handler=fixtures.fail_handler(fixtures.UnsupportedFeatureError("no support")), requires_review=False),
        ]),
        sc("policy-block", "policy_block", "策略阻塞", "blocked", [
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), policy_blocked=True),
        ]),
        sc("user-action", "user_action_required", "需要用户操作", "blocked", [
            AttemptSpec(handler=fixtures.fail_handler(fixtures.DependencyInstallDeclined("declined")), requires_review=False),
        ]),
        sc("retry-exhausted", "retry_exhausted", "重试耗尽", "failed", [
            AttemptSpec(handler=fixtures.fail_handler(TimeoutError("slow")), requires_review=False),
        ], max_retries=0),
        sc("reviewer-blocked", "reviewer_blocked", "Reviewer 阻塞", "blocked", [
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), reviewer=fixtures.blocked_reviewer()),
        ]),
        sc("warning", "warning", "警告等待人工复核", "blocked", [
            AttemptSpec(handler=fixtures.success_handler(fixtures.ok_result(arts)), reviewer=fixtures.warn_reviewer()),
        ]),
    ]


def _terminal_status(assessment: Any, handler_called: bool) -> str:
    """@brief 把 Execution Core 的 RunStatus 映射回 Eval 终态（含 user_action/block → blocked）。"""
    if not handler_called:
        return "blocked"
    if assessment is None:
        return "failed"
    run_status = assessment.run_context.status.value
    if run_status == "completed":
        return "completed"
    if run_status == "blocked":
        return "blocked"
    decision = assessment.recovery_decision.decision if assessment.recovery_decision else None
    if decision in {"user_action_required", "block"}:
        return "blocked"
    return "failed"


def run_scenario(scenario: EvalScenario) -> EvalRecord:
    """@brief 用 Execution Core + 脚本化恢复执行一个场景，收集事实。"""
    from core.execution import execute_with_core

    start = time.monotonic()
    recovery_decisions: list[str] = []
    attempt_count = 0
    tool_call_count = 0
    handler_called = False
    handler_success = False
    verification_status: str | None = None
    artifacts_present: list[str] = []
    notes: list[str] = []
    last_assessment: Any = None

    capability_id = scenario.expected_capabilities[0] if scenario.expected_capabilities else None

    for attempt in scenario.attempts:
        attempt_count += 1
        if attempt.policy_blocked:
            notes.append("策略阻塞：未执行 handler")
            break
        tool_call_count += 1
        handler_called = True
        last_assessment = execute_with_core(
            handler=attempt.handler,
            handler_arg=None,
            run_id=scenario.scenario_id,
            tool_name=scenario.type,
            capability_id=capability_id,
            operation_id=scenario.operation_id,
            requires_review=attempt.requires_review,
            reviewer=attempt.reviewer,
            reviewer_result=attempt.reviewer_result,
            capability_facade=scenario.capability_facade,
            max_retries=scenario.max_retries,
        )
        handler_success = last_assessment.execution_result.success
        if last_assessment.verification_result is not None:
            verification_status = last_assessment.verification_result.status.value
        if isinstance(last_assessment.raw_result, dict):
            artifacts_present = fixtures.artifacts_from_result(last_assessment.raw_result)
        decision = last_assessment.recovery_decision
        if decision is not None:
            recovery_decisions.append(decision.decision)
            if decision.decision not in RECOVERABLE_ACTIONS:
                break  # 不可恢复决策，结束脚本化恢复
        else:
            break  # 无恢复决策（成功），结束

    terminal = _terminal_status(last_assessment, handler_called)
    false_completion = bool(handler_success and verification_status in {"FAIL", "BLOCKED"})

    return EvalRecord(
        scenario_id=scenario.scenario_id,
        workflow_id=scenario.workflow_id,
        scenario_type=scenario.type,
        handler_success=handler_success,
        handler_called=handler_called,
        verification_status=verification_status,
        recovery_decisions=recovery_decisions,
        attempt_count=attempt_count,
        tool_call_count=tool_call_count,
        duration_ms=int((time.monotonic() - start) * 1000),
        terminal_status=terminal,
        false_completion=false_completion,
        artifacts_present=artifacts_present,
        category=scenario.category,
        expected_terminal_status=scenario.expected_terminal_status,
        notes=notes,
    )


def run_eval(payload: dict[str, Any] | None = None) -> EvalReport:
    """@brief 执行全部场景并按分组汇总指标。"""
    workflows = payload or load_golden_workflows()
    scenarios = build_scenarios(workflows)
    records = [run_scenario(scenario) for scenario in scenarios]
    metrics = compute_metrics(records)
    target = float(workflows.get("target_first_pass_rate", 0.90))
    # target 只与 Nominal first-pass 比较，不再与全部 37 场景混合比较。
    nominal_first_pass = metrics["nominal"].get("first_pass_success_rate")
    target_status = "PASS" if (nominal_first_pass is not None and nominal_first_pass >= target) else "BELOW_TARGET"
    return EvalReport(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        workflow_count=len(workflows.get("workflows", [])),
        scenario_count=len(records),
        target_first_pass_rate=target,
        first_pass_target_status=target_status,
        metrics=metrics,
        scenarios=records,
    )


def _pct(value: Any) -> str:
    """@brief 把 0..1 比例格式化为百分比，None 显示 N/A。"""
    return "N/A" if value is None else f"{float(value) * 100:.1f}%"


def render_summary(report: EvalReport) -> str:
    """@brief 控制台摘要（分 Nominal / Robustness / Safety / Overall）。"""
    n = report.metrics["nominal"]
    r = report.metrics["robustness"]
    s = report.metrics["safety"]
    o = report.metrics["overall"]
    return "\n".join([
        "Golden Workflow Reliability Eval",
        "",
        "## Nominal Reliability",
        f"Nominal Scenarios:            {n['scenario_count']}",
        f"Nominal Task Success Rate:    {_pct(n['task_success_rate'])}",
        f"Nominal First Pass Success:   {_pct(n['first_pass_success_rate'])}",
        f"Target First Pass:            {report.target_first_pass_rate:.0%}",
        f"Target Status:                {report.first_pass_target_status}",
        f"Average Tool Calls:           {n['average_tool_calls']}",
        f"Average Duration:             {n['average_duration_ms']} ms",
        "",
        "## Robustness",
        f"Robustness Scenarios:         {r['scenario_count']}",
        f"Expected Outcome Accuracy:    {_pct(r['expected_outcome_accuracy'])}",
        f"Recovery Success Rate:        {_pct(r['recovery_success_rate'])}",
        f"Failure Detection Rate:       {_pct(r['failure_detection_rate'])}",
        f"Policy Block Accuracy:        {_pct(r['policy_block_accuracy'])}",
        f"Capability Gap Detection:     {_pct(r['capability_gap_detection_rate'])}",
        f"Backend Fallback Accuracy:    {_pct(r['backend_fallback_decision_accuracy'])}",
        "",
        "## Safety",
        f"Raw Handler False-Positive:   {_pct(s['raw_false_completion_incidence'])}",
        f"False-Completion Detection:   {_pct(s['false_completion_detection_rate'])}",
        f"Escaped False Completion:     {_pct(s['escaped_false_completion_rate'])}",
        "",
        "## Overall Diagnostic",
        f"Overall Scenario Count:       {o['scenario_count']}",
        f"Overall Raw Completion Rate:  {_pct(o['raw_task_completion_rate'])}",
    ])


def render_markdown(report: EvalReport) -> str:
    """@brief 生成 Markdown 报告（分 Nominal / Robustness / Safety / Overall）。"""
    n = report.metrics["nominal"]
    r = report.metrics["robustness"]
    s = report.metrics["safety"]
    o = report.metrics["overall"]
    lines = [
        "# Golden Workflow Reliability Eval",
        "",
        f"- Workflows: {report.workflow_count}",
        f"- Scenarios: {report.scenario_count}",
        "",
        "## Nominal Reliability",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Nominal Scenarios | {n['scenario_count']} |",
        f"| Nominal Task Success Rate | {_pct(n['task_success_rate'])} |",
        f"| Nominal First Pass Success Rate | {_pct(n['first_pass_success_rate'])} |",
        f"| Target First Pass | {report.target_first_pass_rate:.0%} |",
        f"| Target Status | **{report.first_pass_target_status}** |",
        f"| Average Tool Calls | {n['average_tool_calls']} |",
        f"| Average Duration | {n['average_duration_ms']} ms |",
        "",
        "## Robustness",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Robustness Scenarios | {r['scenario_count']} |",
        f"| Expected Outcome Accuracy | {_pct(r['expected_outcome_accuracy'])} |",
        f"| Recovery Success Rate | {_pct(r['recovery_success_rate'])} |",
        f"| Failure Detection Rate | {_pct(r['failure_detection_rate'])} |",
        f"| Policy Block Accuracy | {_pct(r['policy_block_accuracy'])} |",
        f"| Capability Gap Detection | {_pct(r['capability_gap_detection_rate'])} |",
        f"| Backend Fallback Decision Accuracy | {_pct(r['backend_fallback_decision_accuracy'])} |",
        f"| Reviewer Block Detection | {_pct(r['reviewer_block_detection_rate'])} |",
        f"| Retry Exhaustion Accuracy | {_pct(r['retry_exhaustion_accuracy'])} |",
        "",
        "## Safety",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Raw Handler False-Positive Incidence | {_pct(s['raw_false_completion_incidence'])} |",
        f"| False-Completion Detection Rate | {_pct(s['false_completion_detection_rate'])} |",
        f"| Escaped False Completion Rate | {_pct(s['escaped_false_completion_rate'])} |",
        "",
        "## Overall Diagnostic",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Overall Scenario Count | {o['scenario_count']} |",
        f"| Overall Raw Task Completion Rate | {_pct(o['raw_task_completion_rate'])} |",
        f"| Overall Average Tool Calls | {o['average_tool_calls']} |",
        f"| Overall Average Duration | {o['average_duration_ms']} ms |",
        "",
        "> `Overall Raw Task Completion Rate` 仅作诊断，不用于 target 判断。",
        "",
        "## Per Scenario",
        "",
        "| Scenario | Category | Type | Terminal | Expected | Correct | Tool Calls |",
        "|---|---|---|---|---|---|---|",
    ]
    for sc in report.scenarios:
        correct = "yes" if sc.terminal_status == sc.expected_terminal_status else "no"
        lines.append(
            f"| {sc.scenario_id} | {sc.category} | {sc.scenario_type} | {sc.terminal_status} | "
            f"{sc.expected_terminal_status} | {correct} | {sc.tool_call_count} |"
        )
    return "\n".join(lines) + "\n"


def write_reports(report: EvalReport, output_dir: str | Path | None = None) -> tuple[Path, Path]:
    """@brief 写入 eval_report.json 与 eval_report.md，返回两个路径。"""
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "eval_report.json"
    md_path = output_dir / "eval_report.md"
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden Workflow Reliability Eval")
    parser.add_argument("--workflows", type=Path, default=None, help="可选 golden-workflows.yaml 路径")
    parser.add_argument("--output-dir", type=Path, default=None, help="报告输出目录（默认 tests/evals/reports）")
    args = parser.parse_args(argv)

    payload = load_golden_workflows(args.workflows) if args.workflows else load_golden_workflows()
    report = run_eval(payload)
    json_path, md_path = write_reports(report, args.output_dir)
    print(render_summary(report))
    print()
    print(f"eval_report.json: {json_path}")
    print(f"eval_report.md: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
