"""@brief Execution Core —— 内部编排层（orchestration glue，不是新 Worker/Queue/Agent）。

把 Phase 2~4 的 State / Verification / Recovery / Trace 串成一条内部执行链：

    RunContext + StepRecord
      → Existing Handler（原样调用）
      → ExecutionResult（最小归一化，保留 raw result）
      →（requires_review 时）Verification Adapter
      →（失败/blocked 时）Recovery Decision
      → Trace

本模块**不**负责：Queue claim / lease / heartbeat / approval / policy / stale 恢复 /
Artifact Ledger 实现 / Reviewer 实现 / Backend Router 实现 / 真正 retry / 真正切换
backend / replan / 联网。这些仍由 Worker 与既有模块负责。

兼容优先：Handler 异常被捕获进 ``ExecutionAssessment.exception`` 后由调用方原样
``raise``，保证既有 Worker 的 ``except`` 三路语义完全不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .recovery import ErrorKind, classify_error, decide
from .state import (
    ExecutionResult,
    RecoveryDecision,
    RunContext,
    RunStatus,
    StepRecord,
    StepStatus,
    VerificationResult,
    VerificationStatus,
)
from .trace import emit
from .verification import verify
from .capability import requires_review as registry_requires_review


def normalize_tool_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验显式执行事实；保留历史结果字段，不将失败标记渲染成成功。
    @param raw 既有工具或 Handler 的结构化结果。
    @return 兼容原字段的结果；失败时附加稳定错误码和失败字段。
    """
    payload = dict(raw)
    flags = ["success", "saved", "exported", "rebuild_ok"]
    if payload.get("dry_run") is not True:
        flags.extend(("feature_created", "motor_feature_created", "component_added", "mate_created"))
    failed = [name for name in flags if payload.get(name) is False]
    uncertain = [name for name in flags if name in payload and payload[name] is not None and not isinstance(payload[name], bool)]
    uncertain.extend(name for name in ("feature_created", "rebuild_ok") if name in payload and payload[name] is None)
    if payload.get("output_path") and "saved" in payload and payload["saved"] is None:
        uncertain.append("saved")
    if failed:
        payload.update(status="error", success=False,
                       error_code=payload.get("error_code") or "TOOL_OPERATION_FAILED",
                       failed_fields=failed)
        payload.setdefault("message", "必要执行步骤失败: " + ", ".join(failed))
    elif uncertain:
        payload.update(status="blocked", success=False, error_code="TOOL_RESULT_UNVERIFIED", unverified_fields=uncertain)
    return payload


def _extract_message(raw: Any) -> str:
    """@brief 从 handler 结果提取简短 message（不复制完整 result）。"""
    if isinstance(raw, Mapping):
        return str(raw.get("message") or raw.get("summary") or "")
    if raw is None:
        return ""
    return str(raw)[:500]


def _extract_outputs(raw: Any) -> list[Any]:
    """@brief 从 handler 结果提取 output 引用（最小归一化）。"""
    if isinstance(raw, Mapping):
        outputs = raw.get("outputs") or raw.get("artifacts") or []
        return list(outputs) if isinstance(outputs, (list, tuple)) else []
    if raw is None:
        return []
    return [raw]


def _extract_error_code(raw: Any) -> str | None:
    """@brief 从 handler 结果提取结构化 error_code。"""
    if isinstance(raw, Mapping):
        return raw.get("error_code") or raw.get("errorCode")
    return None


def _exception_summary(exception: BaseException | None) -> dict[str, Any] | None:
    """@brief 只保留异常类型/消息/错误码，不存完整堆栈。"""
    if exception is None:
        return None
    return {
        "type": type(exception).__name__,
        "message": str(exception)[:500],
        "code": getattr(exception, "code", None),
    }


@dataclass
class ExecutionAssessment:
    """@brief Execution Core 返回的内部执行评估结果（sidecar，不影响既有 Queue 语义）。"""

    run_context: RunContext
    step: StepRecord
    execution_result: ExecutionResult
    raw_result: Any = None
    exception: BaseException | None = None
    verification_result: VerificationResult | None = None
    recovery_decision: RecoveryDecision | None = None
    requires_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        """@brief 轻量序列化（不复制 raw_result / 完整异常）。"""
        return {
            "run_id": self.run_context.run_id,
            "status": self.run_context.status.value,
            "requires_review": self.requires_review,
            "step": self.step.to_dict(),
            "execution": self.execution_result.to_dict(),
            "verification": self.verification_result.to_dict() if self.verification_result else None,
            "recovery": self.recovery_decision.to_dict() if self.recovery_decision else None,
            "exception": _exception_summary(self.exception),
        }


def _trace(
    event_type: str,
    trace_dir: Any,
    *,
    run_id: str | None,
    step_id: str | None,
    capability_id: str | None,
    message: str = "",
    data: Mapping[str, Any] | None = None,
) -> None:
    """@brief 写 Trace 事件；观测失败绝不能影响执行。"""
    if trace_dir is None:
        return
    try:
        emit(
            trace_dir,
            event_type,
            run_id=run_id or None,
            step_id=step_id,
            capability_id=capability_id,
            message=message,
            data=data,
        )
    except Exception:
        pass


def execute_with_core(
    *,
    handler: Callable[[Any], Any],
    handler_arg: Any = None,
    run_id: str,
    step_id: str | None = None,
    tool_name: str = "",
    capability_id: str | None = None,
    operation_id: str | None = None,
    requires_review: bool = False,
    reviewer: Callable[[], Any] | None = None,
    reviewer_result: Any = None,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    capability_facade: Any = None,
    max_retries: int | None = None,
    trace_dir: Any = None,
    defer_completion: bool = False,
) -> ExecutionAssessment:
    """@brief 串起 State + Handler + Verification + Recovery + Trace，返回评估结果。

    :param handler: 现有 handler（唯一真实执行实现），签名 ``handler(job)``。
    :param reviewer: 可选零参 callable；requires_review 时若未提供 reviewer_result 才调用。
    :param reviewer_result: 既有 Review 结果（dict/list）；提供时不重复调用 reviewer。
    """
    if operation_id or capability_id:
        required = registry_requires_review(operation_id=operation_id, capability_id=capability_id)
        requires_review = requires_review or required is not False
    step_id = step_id or f"{run_id}:step0"
    run = RunContext(run_id=run_id, goal="", trace_id=run_id)
    step = StepRecord(
        step_id=step_id,
        tool_name=tool_name,
        capability_id=capability_id,
        backend=None,
        status=StepStatus.PENDING,
    )
    run.steps.append(step)
    run.current_step = step_id

    _trace("run.started", trace_dir, run_id=run_id, step_id=None, capability_id=capability_id)
    _trace("step.started", trace_dir, run_id=run_id, step_id=step_id, capability_id=capability_id)

    run.transition(RunStatus.RUNNING)
    step.transition(StepStatus.RUNNING)
    _trace("tool.called", trace_dir, run_id=run_id, step_id=step_id, capability_id=capability_id, message=tool_name)

    raw_result: Any = None
    exception: BaseException | None = None
    recovery_decision: RecoveryDecision | None = None
    execution_result: ExecutionResult
    try:
        raw_result = handler(handler_arg)
    except Exception as exc:  # noqa: BLE001 - 捕获后交还调用方，保持既有 except 语义。
        exception = exc
        kind = classify_error(exception=exc) or ErrorKind.FATAL
        execution_result = ExecutionResult(
            success=False,
            message=str(exc),
            error_code=getattr(exc, "code", None) or type(exc).__name__,
            error_kind=kind.value,
            retryable=kind == ErrorKind.TRANSIENT,
        )
        step.transition(StepStatus.FAILED)
        step.error_code = execution_result.error_code
        step.retryable = execution_result.retryable
        run.transition(RunStatus.FAILED)
        _trace("tool.failed", trace_dir, run_id=run_id, step_id=step_id, capability_id=capability_id,
               message=str(exc), data={"error_code": execution_result.error_code})
        recovery_decision = decide(
            exception=exc,
            operation_id=operation_id,
            capability_id=capability_id,
            capability_facade=capability_facade,
            max_retries=max_retries,
            trace_dir=trace_dir,
            run_id=run_id,
            step_id=step_id,
        )
    else:
        payload = normalize_tool_payload(raw_result) if isinstance(raw_result, Mapping) else None
        failed = raw_result is None or raw_result is False or (
            payload is not None and (payload.get("success") is False or
            str(payload.get("status", "")).lower() in {"error", "fail", "failed", "blocked", "unavailable"})
        )
        execution_result = ExecutionResult(
            success=not failed,
            message=_extract_message(raw_result),
            outputs=_extract_outputs(raw_result),
            error_code=_extract_error_code(payload or {}) or ("TOOL_RESULT_UNAVAILABLE" if failed else None),
        )
        if failed:
            blocked = payload is not None and payload.get("status") == "blocked"
            step.transition(StepStatus.BLOCKED if blocked else StepStatus.FAILED)
            run.transition(RunStatus.BLOCKED if blocked else RunStatus.FAILED)
            step.error_code = execution_result.error_code
            recovery_decision = decide(execution_result=execution_result.to_dict(),
                operation_id=operation_id, capability_id=capability_id,
                capability_facade=capability_facade, max_retries=max_retries,
                trace_dir=trace_dir, run_id=run_id, step_id=step_id)
        _trace("tool.failed" if failed else "tool.succeeded", trace_dir, run_id=run_id, step_id=step_id, capability_id=capability_id,
               message=execution_result.message)

    verification_result: VerificationResult | None = None
    manual_required = isinstance(raw_result, Mapping) and bool(raw_result.get("manual_review_required") or raw_result.get("manualReviewRequired"))
    requires_review = requires_review or manual_required or (isinstance(raw_result, Mapping) and raw_result.get("status") == "review_required")
    if requires_review and execution_result.success and not defer_completion:
        run.transition(RunStatus.VERIFYING)
        step.transition(StepStatus.VERIFYING)
        verification_result = verify(
            reviewer=reviewer,
            reviewer_result=reviewer_result,
            artifacts=artifacts,
            evidence=evidence,
            capability_id=capability_id,
            trace_dir=trace_dir,
            run_id=run_id,
            step_id=step_id,
        )
        step.verification = verification_result
        verification_result.manual_review_required |= manual_required
        if verification_result.status == VerificationStatus.FAIL:
            step.transition(StepStatus.FAILED)
            run.transition(RunStatus.FAILED)
            recovery_decision = decide(
                verification_result=verification_result.to_dict(),
                operation_id=operation_id,
                capability_id=capability_id,
                capability_facade=capability_facade,
                max_retries=max_retries,
                trace_dir=trace_dir,
                run_id=run_id,
                step_id=step_id,
            )
        elif verification_result.status != VerificationStatus.PASS or verification_result.manual_review_required:
            step.transition(StepStatus.BLOCKED)
            run.transition(RunStatus.BLOCKED)
            recovery_decision = decide(
                error_kind=ErrorKind.USER_ACTION_REQUIRED if verification_result.manual_review_required else None,
                verification_result=verification_result.to_dict(),
                operation_id=operation_id,
                capability_id=capability_id,
                capability_facade=capability_facade,
                max_retries=max_retries,
                trace_dir=trace_dir,
                run_id=run_id,
                step_id=step_id,
            )
        else:  # 仅明确 PASS 且无需人工复核，才可以完成。
            step.transition(StepStatus.SUCCESS)
            run.transition(RunStatus.COMPLETED)
    elif execution_result.success:
        step.transition(StepStatus.SUCCESS)
        if not defer_completion:
            run.transition(RunStatus.COMPLETED)

    # 仅在完整链模式（requires_review）下补 run 终态事件；Worker 模式由 Worker 自身写终态。
    if requires_review:
        final_event = {
            RunStatus.COMPLETED: "run.completed",
            RunStatus.FAILED: "run.failed",
            RunStatus.BLOCKED: "run.blocked",
        }.get(run.status)
        if final_event:
            _trace(final_event, trace_dir, run_id=run_id, step_id=step_id, capability_id=capability_id,
                   message=verification_result.reason or "" if verification_result else "")

    return ExecutionAssessment(
        run_context=run,
        step=step,
        execution_result=execution_result,
        raw_result=raw_result,
        exception=exception,
        verification_result=verification_result,
        recovery_decision=recovery_decision,
        requires_review=requires_review,
    )


__all__ = ["ExecutionAssessment", "execute_with_core", "normalize_tool_payload"]
