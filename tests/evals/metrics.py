"""@brief Eval 指标计算（纯函数、deterministic）。

把 Scenario 拆成 Nominal / Robustness / Safety 三组口径，不再把故意失败的
fault-injection / guardrail Scenario 与正常业务 Scenario 混在同一个分母里。

指标口径见 docs/architecture/v2-evaluation.md。
"""
from __future__ import annotations

from typing import Sequence

try:
    from .schemas import EvalRecord
except ImportError:  # 以顶层 evals 包导入时的兜底
    from schemas import EvalRecord

#: 视为「发生过恢复」的决策动作。
RECOVERABLE_ACTIONS = frozenset({"retry", "fallback_backend", "replan_required"})

#: 这些验证结论下，系统没有证据证明任务真正完成。
FALSE_COMPLETION_VERDICTS = frozenset({"FAIL", "BLOCKED"})

#: benchmark group（分类必须是 deterministic，由 runner 按 scenario type 确定）。
NOMINAL_TYPES = frozenset({"happy"})
RECOVERY_TYPES = frozenset({"transient_recovery", "backend_fallback"})
FAULT_INJECTION_TYPES = frozenset({"verification_failure", "reviewer_blocked", "retry_exhausted"})
GUARDRAIL_TYPES = frozenset({"policy_block", "user_action_required", "capability_gap", "warning"})


def scenario_category(scenario_type: str) -> str:
    """@brief 按 scenario type 返回 benchmark group（deterministic）。"""
    if scenario_type in NOMINAL_TYPES:
        return "nominal"
    if scenario_type in RECOVERY_TYPES:
        return "recovery"
    if scenario_type in FAULT_INJECTION_TYPES:
        return "fault_injection"
    if scenario_type in GUARDRAIL_TYPES:
        return "guardrail"
    return "nominal"


def _rate(subset: list[EvalRecord], predicate) -> float | None:
    """@brief 子集命中比例；空子集返回 None。"""
    if not subset:
        return None
    return round(sum(1 for record in subset if predicate(record)) / len(subset), 4)


def _average(values: list[int], subset: list[EvalRecord], field: str) -> float | None:
    if not subset:
        return None
    total = sum(getattr(record, field) for record in subset)
    return round(total / len(subset), 3 if field == "tool_call_count" else 1)


def compute_metrics(records: Sequence[EvalRecord]) -> dict[str, dict[str, float | int | None]]:
    """@brief 返回分组指标：nominal / robustness / safety / overall。"""
    records = list(records)
    if not records:
        return {}

    nominal = [r for r in records if r.category == "nominal"]
    recovery = [r for r in records if r.category == "recovery"]
    fault = [r for r in records if r.category == "fault_injection"]
    guardrail = [r for r in records if r.category == "guardrail"]
    robustness = recovery + fault + guardrail

    # ---- Nominal（正常业务）----
    nominal_metrics = {
        "scenario_count": len(nominal),
        "task_success_rate": _rate(nominal, lambda r: r.terminal_status == "completed"),
        "first_pass_success_rate": _rate(
            nominal,
            lambda r: r.terminal_status == "completed" and r.attempt_count == 1 and not r.recovery_decisions,
        ),
        "average_tool_calls": _average([], nominal, "tool_call_count"),
        "average_duration_ms": _average([], nominal, "duration_ms"),
    }

    # ---- Robustness（故障注入 / recovery / guardrail）----
    robustness_metrics = {
        "scenario_count": len(robustness),
        "expected_outcome_accuracy": _rate(robustness, lambda r: r.terminal_status == r.expected_terminal_status),
        "recovery_success_rate": _rate(recovery, lambda r: r.terminal_status == "completed"),
        "failure_detection_rate": _rate(fault, lambda r: r.terminal_status != "completed"),
        "policy_block_accuracy": _rate(
            [r for r in guardrail if r.scenario_type == "policy_block"],
            lambda r: r.terminal_status == "blocked",
        ),
        "capability_gap_detection_rate": _rate(
            [r for r in guardrail if r.scenario_type == "capability_gap"],
            lambda r: r.terminal_status == "failed",
        ),
        "backend_fallback_decision_accuracy": _rate(
            [r for r in recovery if r.scenario_type == "backend_fallback"],
            lambda r: r.terminal_status == "completed",
        ),
        "reviewer_block_detection_rate": _rate(
            [r for r in fault if r.scenario_type == "reviewer_blocked"],
            lambda r: r.terminal_status == "blocked",
        ),
        "retry_exhaustion_accuracy": _rate(
            [r for r in fault if r.scenario_type == "retry_exhausted"],
            lambda r: r.terminal_status == "failed",
        ),
    }

    # ---- Safety（假成功）----
    handler_success = [r for r in records if r.handler_success]
    false_candidates = [r for r in handler_success if r.verification_status in FALSE_COMPLETION_VERDICTS]
    injected_false = [r for r in fault if r.handler_success and r.verification_status in FALSE_COMPLETION_VERDICTS]
    detected = [r for r in injected_false if r.terminal_status != "completed"]
    escaped = [r for r in false_candidates if r.terminal_status == "completed"]
    safety_metrics = {
        "raw_false_completion_incidence": round(len(false_candidates) / len(handler_success), 4) if handler_success else None,
        "false_completion_detection_rate": round(len(detected) / len(injected_false), 4) if injected_false else None,
        "escaped_false_completion_rate": round(len(escaped) / len(false_candidates), 4) if false_candidates else None,
    }

    # ---- Overall（诊断，不用于 target 判断）----
    overall_metrics = {
        "scenario_count": len(records),
        "raw_task_completion_rate": round(sum(1 for r in records if r.terminal_status == "completed") / len(records), 4),
        "average_tool_calls": _average([], records, "tool_call_count"),
        "average_duration_ms": _average([], records, "duration_ms"),
    }

    return {
        "nominal": nominal_metrics,
        "robustness": robustness_metrics,
        "safety": safety_metrics,
        "overall": overall_metrics,
    }
