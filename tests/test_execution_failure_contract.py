"""@brief 对失败事实与最终完成状态做独立断言，不依赖真实 CAD。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "mcp-server"))
sys.path.insert(0, str(ROOT / "apps" / "desktop"))
from core.execution import execute_with_core, normalize_tool_payload


@pytest.mark.parametrize("payload", [
    {"status": "ok", "feature_created": False},
    {"status": "ok", "saved": False},
    {"status": "ok", "rebuild_ok": False},
    {"success": False}, {"status": "error"}, None, False,
])
def test_failed_tool_cannot_complete_even_if_reviewer_passes(payload):
    """@brief 独立失败事实不能被随后 PASS 掩盖。"""
    result = execute_with_core(handler=lambda _: payload, run_id="failed",
        requires_review=True, reviewer_result={"status": "pass"})
    assert result.execution_result.success is False
    assert result.run_context.status.value == "failed"


@pytest.mark.parametrize("review", [
    {"status": "warning"}, {"status": "review_required"},
    {"status": "pass", "manual_review_required": True},
    {"status": "pass", "checks": [{"status": "fail", "required": True}]},
])
def test_review_not_approved_cannot_complete(review):
    """@brief 待复核和关键失败都不等于最终任务成功。"""
    result = execute_with_core(handler=lambda _: {"status": "ok"}, run_id="review",
        requires_review=True, reviewer_result=review)
    assert result.run_context.status.value != "completed"


def test_dry_run_and_optional_unsaved_result_keep_compatibility():
    """@brief 预览不创建特征、未要求保存，均不得误报执行失败。"""
    payload = {"status": "ok", "dry_run": True, "feature_created": False, "saved": None}
    assert normalize_tool_payload(payload) == payload


def test_mcp_json_and_markdown_expose_failure():
    """@brief 不同格式都从同一个事实判定产生失败状态。"""
    import server
    raw = {"status": "ok", "feature_created": False}
    assert json.loads(server._result(raw, server.ResponseFormat.JSON))["status"] == "error"
    assert server._result(raw, server.ResponseFormat.MARKDOWN).startswith("# error")


def test_worker_records_review_failure_as_core_failure(tmp_path):
    """@brief 交付物缺失的任务，Queue 和 Core 都不得留有完成态。"""
    from cad_workbench.queue_worker import process_job
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"id": "review-fail", "kind": "create_shell",
        "status": "queued", "expectedOutput": "STEP", "capabilities": []}), encoding="utf-8")
    result = process_job(path, handlers={"create_shell": lambda _: {"message": "ok", "outputs": []}})
    assert result["status"] == "failed"
    assert result["executionAssessment"]["status"] == "failed"


def test_worker_rejects_structured_handler_failure(tmp_path):
    """@brief 不抛异常的失败 Handler 也必须阻断交付。"""
    from cad_workbench.queue_worker import process_job
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"id": "tool-fail", "kind": "create_shell", "status": "queued"}), encoding="utf-8")
    result = process_job(path, handlers={"create_shell": lambda _: {"success": False, "message": "cut failed"}})
    assert result["status"] == "failed"
    assert result["executionAssessment"]["execution"]["success"] is False
