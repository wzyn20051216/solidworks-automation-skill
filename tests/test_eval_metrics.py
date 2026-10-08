"""@brief Eval metrics 正确性单元测试（deterministic，分 Nominal/Robustness/Safety 口径）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from evals.metrics import compute_metrics, scenario_category  # noqa: E402
from evals.schemas import EvalRecord  # noqa: E402


def _record(
    terminal="completed",
    handler_success=True,
    verification=None,
    recovery=(),
    attempts=1,
    tool_calls=1,
    duration=10,
    category="nominal",
    expected="completed",
    handler_called=True,
    scenario_type="happy",
):
    return EvalRecord(
        scenario_id="s",
        workflow_id=None,
        scenario_type=scenario_type,
        handler_success=handler_success,
        handler_called=handler_called,
        verification_status=verification,
        recovery_decisions=list(recovery),
        attempt_count=attempts,
        tool_call_count=tool_calls,
        duration_ms=duration,
        terminal_status=terminal,
        false_completion=False,
        artifacts_present=[],
        category=category,
        expected_terminal_status=expected,
    )


def test_scenario_category_mapping():
    assert scenario_category("happy") == "nominal"
    assert scenario_category("warning") == "guardrail"
    assert scenario_category("transient_recovery") == "recovery"
    assert scenario_category("backend_fallback") == "recovery"
    assert scenario_category("verification_failure") == "fault_injection"
    assert scenario_category("reviewer_blocked") == "fault_injection"
    assert scenario_category("retry_exhausted") == "fault_injection"
    assert scenario_category("policy_block") == "guardrail"
    assert scenario_category("user_action_required") == "guardrail"
    assert scenario_category("capability_gap") == "guardrail"


def test_nominal_metrics_only_nominal():
    records = [
        _record("completed", category="nominal", attempts=1),
        _record("failed", category="fault_injection", handler_success=False, expected="failed"),
    ]
    metrics = compute_metrics(records)
    assert metrics["nominal"]["scenario_count"] == 1
    assert metrics["nominal"]["task_success_rate"] == 1.0
    assert metrics["nominal"]["first_pass_success_rate"] == 1.0


def test_nominal_first_pass_distinguishes_recovery():
    records = [
        _record("completed", category="nominal", attempts=1, recovery=()),
        _record("completed", category="nominal", attempts=2, recovery=("retry",)),
    ]
    metrics = compute_metrics(records)
    assert metrics["nominal"]["first_pass_success_rate"] == 0.5
    assert metrics["nominal"]["task_success_rate"] == 1.0


def test_policy_block_correct_handling_counts_success():
    # policy block 正确结果就是 blocked，不应因未 completed 而算失败。
    records = [
        _record("blocked", category="guardrail", expected="blocked", handler_success=False, handler_called=False, scenario_type="policy_block")
    ]
    metrics = compute_metrics(records)
    assert metrics["robustness"]["expected_outcome_accuracy"] == 1.0
    assert metrics["robustness"]["policy_block_accuracy"] == 1.0


def test_capability_gap_correct_handling():
    records = [_record("failed", category="guardrail", expected="failed", handler_success=False, scenario_type="capability_gap")]
    metrics = compute_metrics(records)
    assert metrics["robustness"]["capability_gap_detection_rate"] == 1.0


def test_raw_false_positive_not_escaped():
    # handler success + FAIL + final failed → raw true, escaped false
    records = [_record("failed", handler_success=True, verification="FAIL", category="fault_injection", expected="failed")]
    metrics = compute_metrics(records)
    assert metrics["safety"]["raw_false_completion_incidence"] == 1.0
    assert metrics["safety"]["escaped_false_completion_rate"] == 0.0


def test_escaped_false_completion_true():
    # handler success + FAIL + final completed → escaped true（真实泄漏，生产 bug 才会发生）
    records = [_record("completed", handler_success=True, verification="FAIL")]
    metrics = compute_metrics(records)
    assert metrics["safety"]["escaped_false_completion_rate"] == 1.0


def test_false_completion_detection_rate():
    records = [_record("failed", handler_success=True, verification="FAIL", category="fault_injection")]
    metrics = compute_metrics(records)
    assert metrics["safety"]["false_completion_detection_rate"] == 1.0


def test_failure_detection_rate():
    records = [_record("failed", handler_success=False, category="fault_injection", expected="failed")]
    metrics = compute_metrics(records)
    assert metrics["robustness"]["failure_detection_rate"] == 1.0


def test_recovery_success_rate():
    records = [_record("completed", category="recovery", attempts=2, recovery=("retry",))]
    metrics = compute_metrics(records)
    assert metrics["robustness"]["recovery_success_rate"] == 1.0


def test_empty_records_returns_empty():
    assert compute_metrics([]) == {}
