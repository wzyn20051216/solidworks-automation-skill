"""@brief Recovery Decision Layer —— 失败后下一步该做什么的**纯确定性决策**。

本模块只回答一个问题：发生这种失败后，下一步应该采取什么动作。它**不执行**任何
动作：不自动 retry、不重跑 Tool、不切换 Backend、不重规划、不改模型、不调 Reviewer、
不联网。真正的动作执行留给 Phase 5 的 Worker / Existing Handler。

职责：
- ``classify_error`` 把散落的失败语义统一为 10 类 ``ErrorKind``；
- ``decide`` 把 ErrorKind + 上下文映射为 ``RecoveryDecision``（复用 Phase 2 模型）。

安全默认：**不确定 → BLOCK / FAIL / REPLAN，绝不默认 retry**。
未知错误保守归为 ``FATAL``；绝不把未知异常当 transient。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from . import capability as _capability_facade
from .state import RecoveryDecision, VerificationStatus
from .trace import emit
from .verification import check_status, normalize_status

#: retry 预算的保守默认值（不允许 3/5/无限）。
DEFAULT_MAX_RETRIES = 2


class ErrorKind(str, Enum):
    """@brief 执行层错误类别（不是具体 CAD 错误码全集）。"""

    TRANSIENT = "transient"
    INVALID_ARGUMENT = "invalid_argument"
    ENVIRONMENT_MISSING = "environment_missing"
    TOOL_UNAVAILABLE = "tool_unavailable"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    VERIFICATION_FAILED = "verification_failed"
    USER_ACTION_REQUIRED = "user_action_required"
    POLICY_BLOCKED = "policy_blocked"
    CAPABILITY_GAP = "capability_gap"
    FATAL = "fatal"


# 已确认的历史 error_code → ErrorKind（全部来自仓库现有 Reviewer / Router / Worker
# 的真实字段）。key 统一小写；未收录的 error_code 不在此猜测，继续走更低优先级层。
_ERROR_CODE_KIND: dict[str, ErrorKind] = {
    "sw_file_not_found": ErrorKind.INVALID_ARGUMENT,
    "sw_file_requires_repair": ErrorKind.USER_ACTION_REQUIRED,
    "sw_file_future_version": ErrorKind.USER_ACTION_REQUIRED,
    "sw_low_resources": ErrorKind.USER_ACTION_REQUIRED,
    "sw_file_application_busy": ErrorKind.USER_ACTION_REQUIRED,
    "sw_file_load_failed": ErrorKind.TOOL_UNAVAILABLE,
    "sw_document_state_unavailable": ErrorKind.USER_ACTION_REQUIRED,
    "sw_instance_mismatch": ErrorKind.USER_ACTION_REQUIRED,
    "sw_pack_and_go_timeout": ErrorKind.USER_ACTION_REQUIRED,
    "sw_pack_and_go_worker_protocol": ErrorKind.USER_ACTION_REQUIRED,
    "sw_document_budget": ErrorKind.USER_ACTION_REQUIRED,
    "sw_process_state_unavailable": ErrorKind.USER_ACTION_REQUIRED,
    "sw_instance_not_ready": ErrorKind.USER_ACTION_REQUIRED,
    "sw_version_mismatch": ErrorKind.USER_ACTION_REQUIRED,
    # TRANSIENT
    "occt_timeout": ErrorKind.TRANSIENT,
    "drawing_pdf_text_parse_failed": ErrorKind.TRANSIENT,
    "autocad_com_unstable": ErrorKind.TRANSIENT,
    # INVALID_ARGUMENT
    "invalid_neutral_document": ErrorKind.INVALID_ARGUMENT,
    "dfm_unknown_process": ErrorKind.INVALID_ARGUMENT,
    "dfm_invalid_profile": ErrorKind.INVALID_ARGUMENT,
    "dfm_invalid_brep_evidence": ErrorKind.INVALID_ARGUMENT,
    "dfm_missing_inputs": ErrorKind.INVALID_ARGUMENT,
    "advanced_geometry_invalid_plan": ErrorKind.INVALID_ARGUMENT,
    "fea_convergence_invalid_request": ErrorKind.INVALID_ARGUMENT,
    "sketch_not_active": ErrorKind.INVALID_ARGUMENT,
    "drawing_spec_blocked": ErrorKind.INVALID_ARGUMENT,
    "routing_document_invalid": ErrorKind.INVALID_ARGUMENT,
    "operation_required": ErrorKind.INVALID_ARGUMENT,
    # ENVIRONMENT_MISSING
    "fea_solver_missing": ErrorKind.ENVIRONMENT_MISSING,
    "dotnet_sdk_missing": ErrorKind.ENVIRONMENT_MISSING,
    "autocad_not_found": ErrorKind.ENVIRONMENT_MISSING,
    "winget_missing": ErrorKind.ENVIRONMENT_MISSING,
    "windows_required": ErrorKind.ENVIRONMENT_MISSING,
    "advanced_geometry_runtime_missing": ErrorKind.ENVIRONMENT_MISSING,
    "drawing_pdf_text_parser_missing": ErrorKind.ENVIRONMENT_MISSING,
    "drawing_bom_template_missing": ErrorKind.ENVIRONMENT_MISSING,
    "missing_runtime_requirement": ErrorKind.ENVIRONMENT_MISSING,
    "occt_dependency_or_capability_missing": ErrorKind.ENVIRONMENT_MISSING,
    "dfm_brep_evidence_required": ErrorKind.ENVIRONMENT_MISSING,
    "autocad_core_console_prerequisite_missing": ErrorKind.ENVIRONMENT_MISSING,
    # TOOL_UNAVAILABLE
    "sketch_autodimension_call_failed": ErrorKind.TOOL_UNAVAILABLE,
    "autocad_script_command_failed": ErrorKind.TOOL_UNAVAILABLE,
    # BACKEND_UNAVAILABLE
    "no_compatible_backend_available": ErrorKind.BACKEND_UNAVAILABLE,
    "no_language_substitution": ErrorKind.BACKEND_UNAVAILABLE,
    "autocad_dotnet_runtime_not_verified": ErrorKind.BACKEND_UNAVAILABLE,
    "advanced_geometry_backend_unverified": ErrorKind.BACKEND_UNAVAILABLE,
    "occt_result_missing": ErrorKind.BACKEND_UNAVAILABLE,
    # VERIFICATION_FAILED
    "fea_result_frd_missing": ErrorKind.VERIFICATION_FAILED,
    "fea_convergence_case_failed": ErrorKind.VERIFICATION_FAILED,
    "drawing_final_pdf_required": ErrorKind.VERIFICATION_FAILED,
    "drawing_structure_evidence_missing": ErrorKind.VERIFICATION_FAILED,
    "drawing_semantic_evidence_incomplete": ErrorKind.VERIFICATION_FAILED,
    "drawing_review_findings": ErrorKind.VERIFICATION_FAILED,
    "autocad_dotnet_evidence_invalid": ErrorKind.VERIFICATION_FAILED,
    # USER_ACTION_REQUIRED
    "solidworks_busy_timeout": ErrorKind.USER_ACTION_REQUIRED,
    "known_host_revision_blocker": ErrorKind.USER_ACTION_REQUIRED,
    # POLICY_BLOCKED
    "script_command_not_allowed": ErrorKind.POLICY_BLOCKED,
    # CAPABILITY_GAP
    "unknown_operation_route": ErrorKind.CAPABILITY_GAP,
    "fea_elmer_adapter_not_implemented": ErrorKind.CAPABILITY_GAP,
    "drawing_spec_capability_unsupported": ErrorKind.CAPABILITY_GAP,
    # FATAL
    "occt_geometry_failed": ErrorKind.FATAL,
    "autocad_dotnet_build_failed": ErrorKind.FATAL,
    "drawing_sheet_setup_failed": ErrorKind.FATAL,
    "drawing_view_create_failed": ErrorKind.FATAL,
}

# 明确异常类型 → ErrorKind（按类型名匹配，再按 isinstance 兜底）。
_EXCEPTION_KIND: dict[str, ErrorKind] = {
    "TimeoutError": ErrorKind.TRANSIENT,
    "SolidWorksNotInstalledError": ErrorKind.ENVIRONMENT_MISSING,
    "DependencyInstallDeclined": ErrorKind.USER_ACTION_REQUIRED,
    "SolidWorksConnectionError": ErrorKind.BACKEND_UNAVAILABLE,
    "DesignSpecError": ErrorKind.INVALID_ARGUMENT,
    "DfmProfileError": ErrorKind.INVALID_ARGUMENT,
    "UnsupportedFeatureError": ErrorKind.CAPABILITY_GAP,
    "ModuleNotFoundError": ErrorKind.ENVIRONMENT_MISSING,
    "ImportError": ErrorKind.ENVIRONMENT_MISSING,
}

# 通用 message 关键词（最低优先级，仅针对仓库真实存在的措辞）。
_MESSAGE_HINTS: tuple[tuple[str, ErrorKind], ...] = (
    ("timeout", ErrorKind.TRANSIENT),
    ("超时", ErrorKind.TRANSIENT),
    ("unstable", ErrorKind.TRANSIENT),
    ("不稳定", ErrorKind.TRANSIENT),
    ("not installed", ErrorKind.ENVIRONMENT_MISSING),
    ("未检测到", ErrorKind.ENVIRONMENT_MISSING),
    ("not found", ErrorKind.ENVIRONMENT_MISSING),
    ("license", ErrorKind.USER_ACTION_REQUIRED),
    ("许可证", ErrorKind.USER_ACTION_REQUIRED),
    ("approval", ErrorKind.POLICY_BLOCKED),
    ("审批", ErrorKind.POLICY_BLOCKED),
    ("not allowed", ErrorKind.POLICY_BLOCKED),
    ("unsupported", ErrorKind.CAPABILITY_GAP),
    ("not implemented", ErrorKind.CAPABILITY_GAP),
    ("不支持", ErrorKind.CAPABILITY_GAP),
)

# BLOCKED 细分关键词（不含 transient，避免把 blocked 误判成 transient）。
_BLOCKED_HINTS: tuple[tuple[str, ErrorKind], ...] = (
    ("license", ErrorKind.USER_ACTION_REQUIRED),
    ("许可证", ErrorKind.USER_ACTION_REQUIRED),
    ("approval", ErrorKind.POLICY_BLOCKED),
    ("审批", ErrorKind.POLICY_BLOCKED),
    ("not allowed", ErrorKind.POLICY_BLOCKED),
    ("not installed", ErrorKind.ENVIRONMENT_MISSING),
    ("未检测到", ErrorKind.ENVIRONMENT_MISSING),
    ("missing", ErrorKind.ENVIRONMENT_MISSING),
    ("缺少", ErrorKind.ENVIRONMENT_MISSING),
    ("unsupported", ErrorKind.CAPABILITY_GAP),
    ("not implemented", ErrorKind.CAPABILITY_GAP),
    ("不支持", ErrorKind.CAPABILITY_GAP),
    ("unavailable", ErrorKind.BACKEND_UNAVAILABLE),
)


def _coerce_kind(value: Any) -> ErrorKind | None:
    """@brief 把字符串/枚举归一化为 ErrorKind；未知返回 None（不盲目信任）。"""
    if isinstance(value, ErrorKind):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    for member in ErrorKind:
        if member.value == text:
            return member
    return None


def _hint_kind(text: str, hints: tuple[tuple[str, ErrorKind], ...]) -> ErrorKind | None:
    """@brief 按关键词表返回首个命中的 ErrorKind，未命中返回 None。"""
    lowered = text.lower()
    for keyword, kind in hints:
        if keyword in lowered:
            return kind
    return None


def _classify_exception(exception: BaseException) -> ErrorKind:
    """@brief 异常类型 → ErrorKind（名称优先，再 isinstance 兜底）。"""
    name = type(exception).__name__
    if name in _EXCEPTION_KIND:
        return _EXCEPTION_KIND[name]
    if isinstance(exception, TimeoutError):
        return ErrorKind.TRANSIENT
    if isinstance(exception, (ModuleNotFoundError, ImportError)):
        return ErrorKind.ENVIRONMENT_MISSING
    if isinstance(exception, ValueError):
        return ErrorKind.INVALID_ARGUMENT
    return ErrorKind.FATAL


def _verification_fail_present(verification_result: Mapping[str, Any]) -> bool:
    """@brief 检查是否存在 required/critical FAIL，防止被 aggregate BLOCKED 掩盖。"""
    for check in verification_result.get("checks") or []:
        if isinstance(check, Mapping) and check_status(check) == VerificationStatus.FAIL:
            return True
    return False


def _classify_blocked(result: Mapping[str, Any]) -> ErrorKind:
    """@brief 细分 BLOCKED 的具体原因，默认 USER_ACTION_REQUIRED。"""
    text = " ".join(
        filter(
            None,
            [str(result.get("reason") or ""), str(result.get("message") or "")],
        )
    ).strip()
    if text:
        kind = _hint_kind(text, _BLOCKED_HINTS)
        if kind is not None:
            return kind
    return ErrorKind.USER_ACTION_REQUIRED


def _classify_verification(verification_result: Mapping[str, Any]) -> ErrorKind | None:
    """@brief VerificationResult → ErrorKind；PASS/WARN 返回 None（不触发恢复）。"""
    status = normalize_status(verification_result.get("status"))
    if status in (VerificationStatus.PASS, VerificationStatus.WARN):
        return None
    if status == VerificationStatus.FAIL:
        return ErrorKind.VERIFICATION_FAILED
    # BLOCKED：required FAIL 不被 BLOCKED 掩盖；否则按 reason 细分。
    if _verification_fail_present(verification_result):
        return ErrorKind.VERIFICATION_FAILED
    return _classify_blocked(verification_result)


def _classify_capability(capability_result: Mapping[str, Any]) -> ErrorKind | None:
    """@brief Capability Facade / Router 结果 → ErrorKind。"""
    status = str(capability_result.get("status") or "").strip().lower()
    if status == "capability_gap":
        return ErrorKind.CAPABILITY_GAP
    code = str(capability_result.get("error_code") or "").strip().lower()
    if code and code in _ERROR_CODE_KIND:
        return _ERROR_CODE_KIND[code]
    if status == "unavailable":
        return ErrorKind.BACKEND_UNAVAILABLE
    if status == "blocked":
        return _classify_blocked(capability_result)
    return None


def _classify_execution(execution_result: Mapping[str, Any]) -> ErrorKind | None:
    """@brief ExecutionResult → ErrorKind；工具层成功返回 None（验证层负责）。"""
    if execution_result.get("success") is True:
        return None
    code = str(execution_result.get("error_code") or "").strip().lower()
    if code and code in _ERROR_CODE_KIND:
        return _ERROR_CODE_KIND[code]
    kind = _coerce_kind(execution_result.get("error_kind"))
    if kind is not None:
        return kind
    return ErrorKind.TOOL_UNAVAILABLE


def classify_error(
    *,
    error_kind: Any = None,
    error_code: str | None = None,
    exception: BaseException | None = None,
    execution_result: Mapping[str, Any] | None = None,
    verification_result: Mapping[str, Any] | None = None,
    capability_result: Mapping[str, Any] | None = None,
    policy_result: Mapping[str, Any] | None = None,
    message: str | None = None,
) -> ErrorKind | None:
    """@brief 把失败事实统一分类为 ErrorKind；无失败（如 Verification PASS）返回 None。

    优先级（确定性）：显式 error_kind → 结构化 error_code → 既有 Result 状态
    （policy > capability > verification > execution）→ 异常类型 → message 关键词 →
    未知归 FATAL。
    """
    if error_kind is not None:
        kind = _coerce_kind(error_kind)
        if kind is not None:
            return kind

    if error_code:
        code = str(error_code).strip().lower()
        kind = _ERROR_CODE_KIND.get(code)
        if kind is not None:
            return kind

    if policy_result is not None:
        return ErrorKind.POLICY_BLOCKED

    if capability_result is not None:
        kind = _classify_capability(capability_result)
        if kind is not None:
            return kind

    if verification_result is not None:
        # PASS/WARN 是确定性「无需恢复」，直接返回 None；FAIL/BLOCKED 返回具体 kind。
        return _classify_verification(verification_result)

    if execution_result is not None:
        kind = _classify_execution(execution_result)
        if kind is not None:
            return kind

    if exception is not None:
        code = str(getattr(exception, "code", "") or "").lower()
        if code in _ERROR_CODE_KIND:
            return _ERROR_CODE_KIND[code]
        return _classify_exception(exception)

    if message:
        kind = _hint_kind(str(message), _MESSAGE_HINTS)
        if kind is not None:
            return kind

    return ErrorKind.FATAL


def _resolve_fallback(
    *,
    operation_id: str | None,
    failed_backend: str | None,
    explicit_fallback: str | None,
    capability_facade: Any,
) -> str | None:
    """@brief 通过 Capability Facade 查询可回退 backend（只推荐，不执行）。"""
    if explicit_fallback:
        return str(explicit_fallback)
    if not operation_id or capability_facade is None:
        return None
    try:
        candidates = capability_facade.get_backend_candidates(operation_id)
    except Exception:
        return None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        backend = candidate.get("backend")
        if backend and str(backend) != (failed_backend or ""):
            return str(backend)
    return None


def _trace_decision(decision: RecoveryDecision, trace_dir: Any, run_id: str | None, step_id: str | None) -> None:
    """@brief 写 recovery 事件；观测失败绝不能影响决策结果。"""
    if trace_dir is None:
        return
    if decision.decision == "retry":
        event_type = "recovery.retry"
    elif decision.decision == "fallback_backend":
        event_type = "recovery.backend_fallback"
    else:
        event_type = "recovery.decision"
    try:
        emit(
            trace_dir,
            event_type,
            run_id=run_id or None,
            step_id=step_id,
            error_code=decision.error_kind,
            retry_count=decision.retry_count,
            message=decision.reason,
            data={"action": decision.decision, "fallback_backend": decision.fallback_backend},
        )
    except Exception:
        pass


def decide(
    *,
    error_kind: Any = None,
    error_code: str | None = None,
    exception: BaseException | None = None,
    message: str | None = None,
    execution_result: Mapping[str, Any] | None = None,
    verification_result: Mapping[str, Any] | None = None,
    capability_result: Mapping[str, Any] | None = None,
    policy_result: Mapping[str, Any] | None = None,
    capability_id: str | None = None,
    operation_id: str | None = None,
    failed_backend: str | None = None,
    fallback_backend: str | None = None,
    retry_count: int = 0,
    max_retries: int | None = None,
    capability_facade: Any = None,
    trace_dir: Any = None,
    run_id: str | None = None,
    step_id: str | None = None,
) -> RecoveryDecision | None:
    """@brief 决定失败后的下一步动作；PASS/WARN 或无需恢复时返回 None。

    :param capability_facade: 可注入的 Capability Facade（含 get_backend_candidates /
        get_capability）。缺省使用 core.capability 真源；测试注入 Fake。
    """
    kind = classify_error(
        error_kind=error_kind,
        error_code=error_code,
        exception=exception,
        execution_result=execution_result,
        verification_result=verification_result,
        capability_result=capability_result,
        policy_result=policy_result,
        message=message,
    )
    if kind is None:
        return None

    budget = max(0, int(max_retries) if max_retries is not None else DEFAULT_MAX_RETRIES)
    count = max(0, int(retry_count or 0))
    facade = capability_facade if capability_facade is not None else _capability_facade

    action: str
    fallback: str | None = None
    reason: str

    if kind == ErrorKind.TRANSIENT:
        if count < budget:
            action, reason = "retry", "瞬时错误，允许有限重试"
        else:
            action, reason = "fail", f"瞬时错误重试已达上限（max_retries={budget}）"
    elif kind == ErrorKind.INVALID_ARGUMENT:
        action, reason = "replan_required", "参数无效，需上层 Agent 修正参数后重试"
    elif kind == ErrorKind.BACKEND_UNAVAILABLE:
        fallback = _resolve_fallback(
            operation_id=operation_id,
            failed_backend=failed_backend,
            explicit_fallback=fallback_backend,
            capability_facade=facade,
        )
        if fallback:
            action, reason = "fallback_backend", f"主后端不可用，回退到 {fallback}"
        else:
            action, reason = "block", "无可用后端且无合法 fallback"
    elif kind == ErrorKind.TOOL_UNAVAILABLE:
        # Capability 仍存在 → 交还上层 Agent 组合/换入口；Capability 本身缺失 → CAPABILITY_GAP。
        if capability_id is not None and facade is not None:
            try:
                if facade.get_capability(capability_id) is None:
                    reason = "能力缺口（capability_gap），交还上层 Agent 查证（agent_resolution_required）"
                    decision = RecoveryDecision(
                        decision="replan_required",
                        reason=reason,
                        retry_count=count,
                        max_retries=budget,
                        error_kind=ErrorKind.CAPABILITY_GAP.value,
                    )
                    _trace_decision(decision, trace_dir, run_id, step_id)
                    return decision
            except Exception:
                pass
        action, reason = "replan_required", "Tool 不可用，交还上层 Agent 组合或换入口"
    elif kind == ErrorKind.ENVIRONMENT_MISSING:
        fallback = _resolve_fallback(
            operation_id=operation_id,
            failed_backend=failed_backend,
            explicit_fallback=fallback_backend,
            capability_facade=facade,
        )
        if fallback:
            action, reason = "fallback_backend", f"环境缺失，回退到 {fallback}"
        else:
            action, reason = "block", "环境缺失且无合法 fallback"
    elif kind == ErrorKind.VERIFICATION_FAILED:
        action, reason = "replan_required", "执行成功但验证失败，需修复后重做（不允许报告成功）"
    elif kind == ErrorKind.USER_ACTION_REQUIRED:
        action, reason = "user_action_required", "需要用户操作解除阻塞"
    elif kind == ErrorKind.POLICY_BLOCKED:
        action, reason = "block", "Policy Gate 阻止，禁止 Recovery 绕过"
    elif kind == ErrorKind.CAPABILITY_GAP:
        action, reason = "replan_required", "能力缺口，交还上层 Agent 查证（agent_resolution_required）"
    else:  # FATAL 或未预期
        action, reason = "fail", "致命错误，不允许自动重试"

    decision = RecoveryDecision(
        decision=action,
        reason=reason,
        retry_count=count,
        max_retries=budget,
        fallback_backend=fallback,
        error_kind=kind.value,
    )
    _trace_decision(decision, trace_dir, run_id, step_id)
    return decision


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "ErrorKind",
    "classify_error",
    "decide",
]
