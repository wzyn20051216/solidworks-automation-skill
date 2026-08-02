"""CAD Studio CLI 与桌面端任务语义的一致性测试。"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.cad_studio import prepare_job_for_retry


def test_cli_retry_preserves_history_and_clears_current_evidence():
    job = {
        "schemaVersion": "2.0",
        "id": "job-cli-retry",
        "runId": "run-old",
        "status": "failed",
        "progress": 100,
        "result": {"message": "旧结果"},
        "artifacts": [{"path": "old.step", "producedThisRun": True}],
        "drawingEvidence": {"status": "failed", "stage": "review"},
        "reviewFindings": [{"id": "dimension-overlap"}],
        "reviewGate": {"status": "fail"},
        "error": "旧错误",
        "prompt": "不应复制到历史快照",
    }

    result = prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")

    assert result["status"] == "queued"
    assert result["runId"].startswith("retry-")
    assert result["retryPolicy"]["retryFromStage"] == "drawing-bom"
    assert result["retryPolicy"]["overwrite"] is False
    assert result["artifacts"] == []
    assert result["runHistory"][0]["artifacts"][0]["path"] == "old.step"
    assert "prompt" not in result["runHistory"][0]
    for field in ("result", "drawingEvidence", "reviewFindings", "reviewGate", "error"):
        assert field not in result


def test_cli_retry_keeps_only_latest_twenty_runs():
    job = {
        "runId": "run-current",
        "status": "blocked",
        "runHistory": [{"runId": f"old-{index}"} for index in range(20)],
    }

    result = prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")

    assert len(result["runHistory"]) == 20
    assert result["runHistory"][0]["runId"] == "old-1"
    assert result["runHistory"][-1]["runId"] == "run-current"


def test_cli_retry_rejects_active_job():
    job = {"runId": "run-active", "status": "running"}

    try:
        prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")
    except ValueError as exc:
        assert "不可重试" in str(exc)
    else:
        raise AssertionError("运行中任务不应允许重试")


def test_check_dfm_cli_generates_report(tmp_path: Path):
    """@brief check-dfm 命令必须输出真实 JSON 报告。"""
    source = tmp_path / "plate.cadstudio.json"
    source.write_text(
        json.dumps(
            {
                "documentId": "plate",
                "features": [{"id": "base", "type": "box", "parameters": {"length": 100, "width": 50, "height": 8}}],
                "metadata": {"manufacturing": {"process": "machining", "material": "Al6061", "wallThickness": 3}},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "dfm.json"
    completed = subprocess.run(
        [sys.executable, "scripts/cad_studio.py", "check-dfm", "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "review_required"
    assert Path(payload["reportPath"]).exists()
    assert payload["artifacts"][0]["producedThisRun"] is True
