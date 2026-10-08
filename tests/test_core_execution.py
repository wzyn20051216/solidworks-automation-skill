"""@brief Execution Core 单元测试 + Worker 最小接入 regression（Fake handler/reviewer）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "desktop"))

from core.execution import ExecutionAssessment, execute_with_core  # noqa: E402
from core.state import RunStatus, StepStatus, VerificationStatus  # noqa: E402
from core.trace import read_events  # noqa: E402


def _handler(result):
    def _run(job):
        return result
    return _run


def test_handler_success_no_review_preserves_result():
    assessment = execute_with_core(
        handler=_handler({"message": "ok", "outputs": ["a.step"]}),
        handler_arg={},
        run_id="r1",
    )
    assert assessment.raw_result == {"message": "ok", "outputs": ["a.step"]}
    assert assessment.exception is None
    assert assessment.execution_result.success is True
    assert assessment.run_context.status == RunStatus.COMPLETED
    assert assessment.step.status == StepStatus.SUCCESS
    assert assessment.verification_result is None
    assert assessment.recovery_decision is None


def test_handler_exception_produces_fail_and_recovery():
    def boom(job):
        raise ValueError("bad argument")

    assessment = execute_with_core(handler=boom, handler_arg={}, run_id="r1")
    assert assessment.exception is not None
    assert assessment.execution_result.success is False
    assert assessment.run_context.status == RunStatus.FAILED
    assert assessment.step.status == StepStatus.FAILED
    assert assessment.recovery_decision is not None
    assert assessment.recovery_decision.decision == "replan_required"
    assert assessment.recovery_decision.error_kind == "invalid_argument"


def test_requires_review_false_does_not_call_reviewer():
    called = []

    def reviewer():
        called.append(1)
        return {"status": "pass"}

    execute_with_core(handler=_handler({"message": "ok"}), handler_arg={}, run_id="r1", reviewer=reviewer)
    assert called == []


def test_requires_review_with_existing_result_does_not_call_reviewer():
    called = []

    def reviewer():
        called.append(1)
        return {"status": "pass"}

    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=reviewer,
        reviewer_result={"status": "pass"},
    )
    assert called == []  # 已有 result 优先，不重复调 reviewer
    assert assessment.verification_result.status == VerificationStatus.PASS
    assert assessment.run_context.status == RunStatus.COMPLETED


def test_reviewer_pass_completed():
    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=lambda: {"status": "pass"},
    )
    assert assessment.verification_result.status == VerificationStatus.PASS
    assert assessment.run_context.status == RunStatus.COMPLETED
    assert assessment.step.status == StepStatus.SUCCESS


def test_reviewer_warn_requires_manual_review():
    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=lambda: {"status": "warning"},
    )
    assert assessment.verification_result.status == VerificationStatus.WARN
    assert assessment.run_context.status == RunStatus.BLOCKED
    assert assessment.recovery_decision.decision == "user_action_required"


def test_reviewer_fail_not_success():
    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=lambda: {"status": "fail"},
    )
    assert assessment.verification_result.status == VerificationStatus.FAIL
    assert assessment.run_context.status == RunStatus.FAILED
    assert assessment.step.status == StepStatus.FAILED
    assert assessment.recovery_decision.decision == "replan_required"


def test_reviewer_blocked_not_success():
    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=lambda: {"status": "blocked", "reason": "no env"},
    )
    assert assessment.verification_result.status == VerificationStatus.BLOCKED
    assert assessment.run_context.status == RunStatus.BLOCKED
    assert assessment.step.status == StepStatus.BLOCKED
    assert assessment.recovery_decision is not None


def test_reviewer_exception_becomes_blocked():
    def boom():
        raise RuntimeError("reviewer crashed")

    assessment = execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=boom,
    )
    assert assessment.verification_result.status == VerificationStatus.BLOCKED
    assert assessment.verification_result.error_code == "reviewer_error"
    assert assessment.recovery_decision is not None


def test_capability_gap_recovery_decision():
    class UnsupportedFeatureError(ValueError):
        pass

    def handler(job):
        raise UnsupportedFeatureError("not supported")

    assessment = execute_with_core(handler=handler, handler_arg={}, run_id="r1")
    assert assessment.recovery_decision.decision == "replan_required"
    assert assessment.recovery_decision.error_kind == "capability_gap"


def test_backend_unavailable_fallback_decision_not_executed():
    class FakeCapability:
        def get_backend_candidates(self, operation_id):
            return [
                {"backend": "solidworks-com-pywin32", "priority": 10},
                {"backend": "solidworks-com-comtypes", "priority": 20},
            ]

        def get_capability(self, capability_id):
            return {"id": capability_id, "level": "verified"}

    class SolidWorksConnectionError(RuntimeError):
        pass

    calls = []

    def handler(job):
        calls.append(1)
        raise SolidWorksConnectionError("connect failed")

    assessment = execute_with_core(
        handler=handler,
        handler_arg={},
        run_id="r1",
        operation_id="solidworks_standard_automation",
        capability_facade=FakeCapability(),
    )
    assert calls == [1]  # handler 只执行一次，未自动 fallback
    assert assessment.recovery_decision.decision == "fallback_backend"
    assert assessment.recovery_decision.fallback_backend == "solidworks-com-pywin32"


def test_retry_decision_recorded_handler_once():
    calls = []

    def handler(job):
        calls.append(1)
        raise TimeoutError("slow")

    assessment = execute_with_core(handler=handler, handler_arg={}, run_id="r1")
    assert calls == [1]
    assert assessment.recovery_decision.decision == "retry"
    assert assessment.recovery_decision.error_kind == "transient"


def test_trace_written(tmp_path):
    execute_with_core(handler=_handler({"message": "ok"}), handler_arg={}, run_id="r1", trace_dir=tmp_path)
    events = read_events(tmp_path, "r1")
    assert [event["type"] for event in events] == [
        "run.started",
        "step.started",
        "tool.called",
        "tool.succeeded",
    ]


def test_trace_failure_does_not_affect_result(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    assessment = execute_with_core(handler=_handler({"message": "ok"}), handler_arg={}, run_id="r1", trace_dir=blocker)
    assert assessment.raw_result == {"message": "ok"}
    assert assessment.run_context.status == RunStatus.COMPLETED


def test_requires_review_full_chain_trace(tmp_path):
    execute_with_core(
        handler=_handler({"message": "ok"}),
        handler_arg={},
        run_id="r1",
        requires_review=True,
        reviewer=lambda: {"status": "pass"},
        trace_dir=tmp_path,
    )
    events = read_events(tmp_path, "r1")
    types = [event["type"] for event in events]
    assert "run.started" in types
    assert "tool.succeeded" in types
    assert "verification.started" in types
    assert "verification.passed" in types
    assert types[-1] == "run.completed"


def test_assessment_json_serializable():
    assessment = execute_with_core(handler=_handler({"message": "ok"}), handler_arg={}, run_id="r1")
    payload = assessment.to_dict()
    assert payload["run_id"] == "r1"
    assert payload["execution"]["success"] is True
    # 不复制 raw_result / 完整异常
    assert "raw_result" not in payload
    assert payload["exception"] is None


# ---- Worker 最小接入 regression ----


def _make_job(**overrides):
    job = {
        "schemaVersion": "2.0",
        "id": "job-exec-1",
        "runId": "run-exec-1",
        "kind": "create_shell",
        "title": "test",
        "detail": "test",
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "projectId": "p",
        "conversationId": "c",
        "inputs": [],
        "stage": "intake",
        "capabilities": [],
        "policy": {"approval": "never"},
    }
    job.update(overrides)
    return job


def test_worker_wraps_handler_preserves_result(tmp_path):
    from cad_workbench.queue_worker import process_job, read_job

    path = tmp_path / "job-exec-1.json"
    path.write_text(json.dumps(_make_job()), encoding="utf-8")
    calls = []

    def handler(job):
        calls.append(job["id"])
        return {"message": "ok", "outputs": []}

    result = process_job(path, handlers={"create_shell": handler})
    assert calls == ["job-exec-1"]  # handler 只调用一次
    assert result["result"]["message"] == "ok"  # 原结果保持
    stored = read_job(path)
    assert stored["executionAssessment"]["execution"]["success"] is True
    assert "verificationAssessment" in stored  # 既有 Reviewer Gate 被统一标准化（sidecar）


def test_worker_handler_exception_still_fails(tmp_path):
    from cad_workbench.queue_worker import process_job

    path = tmp_path / "job-exec-1.json"
    path.write_text(json.dumps(_make_job()), encoding="utf-8")

    def handler(job):
        raise ValueError("boom")

    result = process_job(path, handlers={"create_shell": handler})
    assert result["status"] == "failed"  # 原失败语义不变
    assert "boom" in str(result.get("error") or result.get("lastMessage") or "")


def test_worker_queue_schema_unchanged(tmp_path):
    from cad_workbench.queue_worker import process_job, read_job

    path = tmp_path / "job-exec-1.json"
    path.write_text(json.dumps(_make_job()), encoding="utf-8")
    process_job(path, handlers={"create_shell": lambda job: {"message": "ok", "outputs": []}})
    stored = read_job(path)
    for key in (
        "id",
        "runId",
        "kind",
        "status",
        "result",
        "reviewGate",
        "reviewGatePath",
        "artifactLedgerPath",
        "artifacts",
        "stage",
    ):
        assert key in stored, key
    assert stored["status"] in {"passed", "review_required", "failed", "blocked", "cancelled"}
