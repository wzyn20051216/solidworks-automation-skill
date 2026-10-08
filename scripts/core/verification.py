"""@brief Verification Adapter —— 把既有 Reviewer 结果统一成 VerificationResult。

本模块**不**实现任何 CAD / 几何 / 工程图 / 文件事实检查，也不重建 Artifact Ledger
或重写 Reviewer Gate。它只做三件事：

1. 调用既有 Reviewer（通过注入的 callable，或直接接收已有 Review 结果）；
2. 把不同 Reviewer 的返回格式标准化为统一状态；
3. 生成统一的 :class:`~core.state.VerificationResult`。

职责边界：

- Reviewer 负责「检查」；本 Adapter 只负责「把检查结果翻译成统一语言」。
- ``Tool Success != Task Success`` 由调用方（后续 Execution Core）联合
  ``execution.success`` 与 ``VerificationResult`` 判定；本模块不据此做决策。
- 是否需要 Review 由 ``core.capability.requires_review`` 决定；本模块不读能力配置。
- 不做 Recovery / retry / backend fallback / 自动修复。

安全原则：**无法验证 ≠ PASS**。Reviewer 缺失、异常、返回未知状态时，一律安全
降级为 ``BLOCKED``，并保留 ``reason`` / ``error_code`` 供后续 Recovery 使用。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from .state import VerificationResult, VerificationStatus
from .trace import emit

# 已确认的历史返回格式 → 统一状态。全部来自仓库现有 Reviewer 的正式字段，或 V2
# 明确要求的别名；未收录的字符串一律由 normalize_status 安全降级为 BLOCKED。
_STATUS_MAP: dict[str, VerificationStatus] = {
    # 已确认的 Review 顶层 status 字段
    "pass": VerificationStatus.PASS,
    "warn": VerificationStatus.WARN,
    "warning": VerificationStatus.WARN,
    "review_required": VerificationStatus.WARN,
    "fail": VerificationStatus.FAIL,
    "failed": VerificationStatus.FAIL,
    "blocked": VerificationStatus.BLOCKED,
    # V2 明确要求的工具/证据层别名
    "passed": VerificationStatus.PASS,
    "ok": VerificationStatus.PASS,
    "success": VerificationStatus.PASS,
    "error": VerificationStatus.FAIL,
    "invalid": VerificationStatus.FAIL,
    "unsupported": VerificationStatus.BLOCKED,
    "unavailable": VerificationStatus.BLOCKED,
    "manual_required": VerificationStatus.BLOCKED,
}

# BLOCKED > FAIL > WARN > PASS
_STATUS_PRIORITY: dict[VerificationStatus, int] = {
    VerificationStatus.BLOCKED: 3,
    VerificationStatus.FAIL: 2,
    VerificationStatus.WARN: 1,
    VerificationStatus.PASS: 0,
}

# 这些 severity 视为非关键/信息性，即使 status=fail 也不升级为 FAIL（降为 WARN）。
_NON_BLOCKING_SEVERITY = frozenset(
    {"p2", "low", "info", "informational", "optional", "note", "debug"}
)

# 最终状态 → Trace 事件类型（沿用 Phase 2 的 append-only 事件 schema，通过
# verification_status 字段承载真实状态；warned/blocked 为 Phase 3 追加的事件名）。
_STATUS_EVENT: dict[VerificationStatus, str] = {
    VerificationStatus.PASS: "verification.passed",
    VerificationStatus.FAIL: "verification.failed",
    VerificationStatus.WARN: "verification.warned",
    VerificationStatus.BLOCKED: "verification.blocked",
}


def normalize_status(value: Any) -> VerificationStatus:
    """@brief 把历史状态字符串归一化为 VerificationStatus，未知值安全降级 BLOCKED。"""
    if isinstance(value, VerificationStatus):
        return value
    if value is None or str(value).strip() == "":
        return VerificationStatus.BLOCKED
    return _STATUS_MAP.get(str(value).strip().lower(), VerificationStatus.BLOCKED)


def aggregate_statuses(statuses: Iterable[VerificationStatus | str]) -> VerificationStatus:
    """@brief 按 BLOCKED > FAIL > WARN > PASS 确定性聚合，空集合安全降级 BLOCKED。"""
    normalized = [normalize_status(item) for item in statuses]
    if not normalized:
        return VerificationStatus.BLOCKED
    return max(normalized, key=lambda item: _STATUS_PRIORITY[item])


def check_status(check: Mapping[str, Any]) -> VerificationStatus:
    """@brief 归一化单个 Check，尊重 severity/required/optional，信息性失败降级 WARN。"""
    status = normalize_status(check.get("status"))
    if status == VerificationStatus.FAIL:
        severity = str(check.get("severity") or "").strip().lower()
        if severity in _NON_BLOCKING_SEVERITY:
            return VerificationStatus.WARN
        if check.get("optional") is True or check.get("required") is False:
            return VerificationStatus.WARN
    return status


def aggregate_checks(checks: Iterable[Mapping[str, Any]]) -> VerificationStatus:
    """@brief 聚合一组原始 Check 为统一状态（尊重 severity/required）。"""
    normalized = [check_status(item) for item in checks if isinstance(item, Mapping)]
    return aggregate_statuses(normalized)


def _coerce_results(value: Any) -> list[Mapping[str, Any]]:
    """@brief 把 reviewer 返回值（dict / list / None）归一化为结果列表。"""
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _status_from_result(result: Mapping[str, Any]) -> VerificationStatus:
    """@brief 从单个 Review 结果取正式 status 字段，兼容 run_review 的 evaluation.status。"""
    raw = result.get("status")
    if raw is None and isinstance(result.get("evaluation"), Mapping):
        raw = result["evaluation"].get("status")
    return normalize_status(raw)


def _result_reason(status: VerificationStatus, results: list[Mapping[str, Any]]) -> str | None:
    """@brief 取聚合后最终状态对应的 reason/message，无则返回 None。"""
    if status == VerificationStatus.PASS:
        return None
    for result in results:
        if _status_from_result(result) != status:
            continue
        for key in ("reason", "message", "error_code", "manual_review_reason"):
            value = result.get(key)
            if value:
                return str(value)
    return None


def _result_error_code(status: VerificationStatus, results: list[Mapping[str, Any]]) -> str | None:
    """@brief 取聚合后最终状态对应的 error_code。"""
    if status == VerificationStatus.PASS:
        return None
    for result in results:
        if _status_from_result(result) != status:
            continue
        value = result.get("error_code")
        if value:
            return str(value)
    return None


def _dedup_artifacts(items: Iterable[Any]) -> list[dict[str, Any]]:
    """@brief 合并交付物列表并按 path 去重，保留顺序。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        path = record.get("path")
        if path is not None:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
        result.append(record)
    return result


def _trace_event(
    event_type: str,
    trace_dir: Any,
    *,
    run_id: str | None,
    step_id: str | None,
    capability_id: str | None,
    status: VerificationStatus | None,
    message: str = "",
    data: Mapping[str, Any] | None = None,
) -> None:
    """@brief 写 Trace 事件；观测失败绝不能影响验证结果。"""
    if trace_dir is None:
        return
    try:
        emit(
            trace_dir,
            event_type,
            run_id=run_id or None,
            step_id=step_id,
            capability_id=capability_id,
            verification_status=status.value if status is not None else None,
            message=message,
            data=data,
        )
    except Exception:
        # 可观测性不应成为业务成功的前置依赖。
        pass


def _execution_summary(execution: Any) -> dict[str, Any] | None:
    """@brief 从 execution 提取最小上下文摘要（仅用于 Trace，不做判定）。"""
    if execution is None:
        return None
    if isinstance(execution, Mapping):
        return {"success": execution.get("success"), "error_code": execution.get("error_code")}
    if hasattr(execution, "success"):
        return {"success": execution.success, "error_code": getattr(execution, "error_code", None)}
    return None


def verify(
    *,
    capability_id: str | None = None,
    execution: Any = None,
    reviewer: Callable[[], Any] | None = None,
    reviewer_result: Any = None,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    trace_dir: Any = None,
    run_id: str | None = None,
    step_id: str | None = None,
) -> VerificationResult:
    """@brief 调用 Reviewer 并把结果统一为 VerificationResult（薄入口）。

    :param reviewer: 零参 callable，返回单个 Review 结果 dict、结果 list，或 None。
                     生产环境传入真实 Reviewer（如 evaluate_ledger），测试注入 Fake。
    :param reviewer_result: 直接传入既有 Review 结果（dict / list），替代 reviewer。
    :param artifacts: 既有 Artifact Ledger 事实（path/exists/size/hash/kind）。
    :param evidence: 既有 Evidence 引用，原样挂到 VerificationResult.evidence。
    :param trace_dir: 可选 queue 目录；提供时写入 verification.* 事件（失败不影响结果）。
    """
    _trace_event(
        "verification.started",
        trace_dir,
        run_id=run_id,
        step_id=step_id,
        capability_id=capability_id,
        status=None,
        message="开始验证",
        data=_execution_summary(execution),
    )

    results: list[Mapping[str, Any]] = []
    reviewer_error: Exception | None = None
    if reviewer_result is not None:
        # 既有 Review 结果优先：Worker/Handler 已产生 reviewer_result 时不再重复调用 Reviewer。
        results = _coerce_results(reviewer_result)
    elif reviewer is not None:
        try:
            results = _coerce_results(reviewer())
        except Exception as exc:  # noqa: BLE001 - Reviewer 异常必须安全降级，不能冒泡。
            reviewer_error = exc

    if reviewer_error is not None:
        verdict = VerificationResult(
            status=VerificationStatus.BLOCKED,
            reason=f"Reviewer 执行失败: {type(reviewer_error).__name__}",
            checks=[{"id": "verification_reviewer_error", "status": "blocked", "message": str(reviewer_error)}],
            error_code="reviewer_error",
            manual_review_required=False,
        )
        _trace_event(
            _STATUS_EVENT[verdict.status],
            trace_dir,
            run_id=run_id,
            step_id=step_id,
            capability_id=capability_id,
            status=verdict.status,
            message=verdict.reason or "",
        )
        return verdict

    if not results:
        verdict = VerificationResult(
            status=VerificationStatus.BLOCKED,
            reason="未配置 Reviewer 且无既有 Review 结果，无法完成验证",
            error_code="verification_unavailable",
        )
        _trace_event(
            _STATUS_EVENT[verdict.status],
            trace_dir,
            run_id=run_id,
            step_id=step_id,
            capability_id=capability_id,
            status=verdict.status,
            message=verdict.reason or "",
        )
        return verdict

    status = aggregate_statuses(_status_from_result(result) for result in results)
    checks: list[dict[str, Any]] = []
    for result in results:
        for key in ("checks", "issues"):
            for item in result.get(key) or []:
                if isinstance(item, Mapping):
                    checks.append(dict(item))
    if checks:
        status = aggregate_statuses((status, aggregate_checks(checks)))

    merged_artifacts = _dedup_artifacts(
        [*(artifacts or [])]
        + [item for result in results for item in (result.get("artifacts") or [])]
    )
    merged_evidence = [*(evidence or [])] + [
        item for result in results for item in (result.get("evidence") or []) if isinstance(item, Mapping)
    ]
    manual_review_required = status == VerificationStatus.WARN or any(
        bool(result.get("manual_review_required") or result.get("manualReviewRequired"))
        for result in results
    )

    verdict = VerificationResult(
        status=status,
        reason=_result_reason(status, results),
        checks=checks,
        artifacts=merged_artifacts,
        evidence=merged_evidence,
        manual_review_required=manual_review_required,
        error_code=_result_error_code(status, results),
    )
    _trace_event(
        _STATUS_EVENT[verdict.status],
        trace_dir,
        run_id=run_id,
        step_id=step_id,
        capability_id=capability_id,
        status=verdict.status,
        message=verdict.reason or ("验证通过" if verdict.status == VerificationStatus.PASS else ""),
    )
    return verdict


__all__ = [
    "aggregate_checks",
    "aggregate_statuses",
    "check_status",
    "normalize_status",
    "verify",
]
