"""@brief Eval Runner 单元测试（scenario 执行、report 输出、golden-workflows 兼容）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from evals.runner import (  # noqa: E402
    build_scenarios,
    load_golden_workflows,
    render_markdown,
    run_eval,
    run_scenario,
    write_reports,
)


def test_load_golden_workflows_old_format_compatible():
    payload = load_golden_workflows()
    assert payload["schema_version"] == "1.0"
    assert "target_first_pass_rate" in payload
    assert len(payload["workflows"]) == 10
    for workflow in payload["workflows"]:
        assert {"id", "capabilities", "required_artifacts"} <= set(workflow)


def test_build_scenarios_derives_from_golden():
    scenarios = build_scenarios(load_golden_workflows())
    assert len(scenarios) == 37
    happy = [s for s in scenarios if s.type == "happy"]
    assert len(happy) == 10
    golden_ids = {w["id"] for w in load_golden_workflows()["workflows"]}
    assert {s.workflow_id for s in happy} == golden_ids
    types = {s.type for s in scenarios}
    assert {
        "happy",
        "verification_failure",
        "transient_recovery",
        "backend_fallback",
        "capability_gap",
        "policy_block",
        "user_action_required",
        "retry_exhausted",
        "reviewer_blocked",
        "warning",
    } <= types


def test_scenario_categories_deterministic():
    scenarios = build_scenarios(load_golden_workflows())
    by_type = {s.type: s.category for s in scenarios}
    assert by_type["happy"] == "nominal"
    assert by_type["warning"] == "guardrail"
    assert by_type["transient_recovery"] == "recovery"
    assert by_type["backend_fallback"] == "recovery"
    assert by_type["verification_failure"] == "fault_injection"
    assert by_type["reviewer_blocked"] == "fault_injection"
    assert by_type["retry_exhausted"] == "fault_injection"
    assert by_type["policy_block"] == "guardrail"
    assert by_type["user_action_required"] == "guardrail"
    assert by_type["capability_gap"] == "guardrail"


def test_run_scenario_happy():
    happy = next(s for s in build_scenarios(load_golden_workflows()) if s.type == "happy")
    record = run_scenario(happy)
    assert record.category == "nominal"
    assert record.expected_terminal_status == "completed"
    assert record.terminal_status == "completed"
    assert record.handler_success is True
    assert record.verification_status == "PASS"
    assert record.recovery_decisions == []
    assert record.false_completion is False


def test_run_scenario_verification_failure_false_completion():
    scenario = next(s for s in build_scenarios(load_golden_workflows()) if s.type == "verification_failure")
    record = run_scenario(scenario)
    assert record.category == "fault_injection"
    assert record.terminal_status == "failed"
    assert record.handler_success is True
    assert record.verification_status == "FAIL"
    assert record.false_completion is True  # raw 假成功候选（被正确拦截）


def test_run_scenario_transient_recovery():
    scenario = next(s for s in build_scenarios(load_golden_workflows()) if s.type == "transient_recovery")
    record = run_scenario(scenario)
    assert record.category == "recovery"
    assert record.terminal_status == "completed"
    assert record.recovery_decisions == ["retry"]
    assert record.attempt_count == 2


def test_run_scenario_policy_blocked_handler_not_called():
    scenario = next(s for s in build_scenarios(load_golden_workflows()) if s.type == "policy_block")
    record = run_scenario(scenario)
    assert record.category == "guardrail"
    assert record.handler_called is False
    assert record.terminal_status == "blocked"
    assert record.expected_terminal_status == "blocked"


def test_run_eval_report_grouped_metrics():
    report = run_eval()
    assert report.workflow_count == 10
    assert report.scenario_count == 37
    assert report.target_first_pass_rate == 0.90
    # 修正后：target 只与 Nominal first-pass 比较 → PASS
    assert report.first_pass_target_status == "PASS"
    assert report.metrics["nominal"]["first_pass_success_rate"] == 1.0
    assert report.metrics["safety"]["escaped_false_completion_rate"] == 0.0
    assert report.metrics["robustness"]["expected_outcome_accuracy"] == 1.0
    # Overall raw completion 仅诊断，不用于 target
    assert report.metrics["overall"]["raw_task_completion_rate"] == 0.5676


def test_write_reports_json_and_markdown(tmp_path):
    report = run_eval()
    json_path, md_path = write_reports(report, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["workflow_count"] == 10
    assert data["scenario_count"] == 37
    assert "nominal" in data["metrics"]
    assert "robustness" in data["metrics"]
    assert "safety" in data["metrics"]
    md = md_path.read_text(encoding="utf-8")
    assert "Nominal Reliability" in md
    assert "Robustness" in md
    assert "Safety" in md
    assert "Escaped False Completion" in md


def test_render_markdown_contains_grouped_metrics():
    md = render_markdown(run_eval())
    assert "Nominal First Pass Success Rate" in md
    assert "Escaped False Completion Rate" in md
    assert "Expected Outcome Accuracy" in md


def test_deterministic():
    report1 = run_eval()
    report2 = run_eval()
    stable = ("task_success_rate", "first_pass_success_rate")
    for key in stable:
        assert report1.metrics["nominal"][key] == report2.metrics["nominal"][key], key
    assert report1.metrics["safety"] == report2.metrics["safety"]
    assert report1.metrics["robustness"] == report2.metrics["robustness"]
    assert [s.terminal_status for s in report1.scenarios] == [s.terminal_status for s in report2.scenarios]
    assert [s.recovery_decisions for s in report1.scenarios] == [s.recovery_decisions for s in report2.scenarios]
