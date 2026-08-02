"""DFM worker 任务回归。"""
from __future__ import annotations

from pathlib import Path

from apps.desktop.cad_workbench.queue_worker import process_job, read_job, run_dfm_review_job, write_job


def test_worker_runs_dfm_review_from_ui_configuration(tmp_path: Path) -> None:
    """@brief 没有模型文件时，UI 配置草案也必须形成可追溯待复核报告。"""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    output_dir = tmp_path / "output"
    job_path = queue_dir / "dfm-job.json"
    job = {
        "schemaVersion": "2.0",
        "id": "dfm-job",
        "runId": "run-dfm",
        "kind": "dfm_review",
        "title": "DFM 复核",
        "detail": "配置草案",
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "projectId": "p",
        "conversationId": "c",
        "inputs": [],
        "stage": "intake",
        "capabilitySnapshot": {},
        "assumptions": [],
        "requiredArtifacts": ["dfm_report"],
        "verificationEvidence": [],
        "cwd": str(tmp_path),
        "uiConfig": {
            "outputDir": str(output_dir),
            "process": "CNC",
            "geometry": {"length": 120, "width": 70, "height": 8, "wallThickness": 3},
            "manufacturing": {"process": "CNC", "material": "Al6061", "unit": "mm"},
        },
    }
    write_job(job_path, job)

    result = process_job(job_path, handlers={"dfm_review": run_dfm_review_job})
    saved = read_job(job_path)

    assert result is not None
    assert saved["status"] == "review_required"
    assert saved["dfmEvidence"]["status"] == "review_required"
    assert saved["dfmEvidence"]["manualReviewRequired"] is True
    report_path = Path(saved["dfmEvidence"]["reportPath"])
    assert report_path.exists()
    assert saved["artifacts"]
    assert Path(saved["artifactLedgerPath"]).exists()
