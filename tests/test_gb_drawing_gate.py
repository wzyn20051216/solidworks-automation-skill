"""@brief 工程图 GB Worker 门禁回归测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from apps.desktop.cad_workbench.gb_drawing_gate import (
    EXPECTED_ITEMS,
    _is_within,
    run_gb_drawing_gate,
)
from apps.desktop.cad_workbench.queue_worker import _job_timeout_seconds, process_queue, read_job, write_job
from apps.desktop.cad_workbench.reviewer_gate import evaluate_ledger


def _drawing_job(tmp_path: Path) -> dict:
    return {
        "id": "gb-gate-test",
        "uiConfig": {
            "outputDir": str(tmp_path / "output"),
            "pipeline": {"stage": "drawing"},
            "gates": {"strictGbDrawing": True},
        },
    }


def _report(status: str = "pass") -> dict:
    return {
        "schemaVersion": "1.0",
        "status": status,
        "items": [
            {"id": item_id, "status": "pass" if item_id != "font" or status == "pass" else "fail"}
            for item_id in EXPECTED_ITEMS
        ],
    }


def test_drawing_gate_requires_current_dxf(tmp_path: Path) -> None:
    job = _drawing_job(tmp_path)
    result = {"artifacts": []}

    evidence = run_gb_drawing_gate(job, result, tmp_path)

    assert evidence is not None
    assert evidence["status"] == "fail"
    assert evidence["errorCode"] == "GB_DXF_MISSING"
    assert result["gbDrawingGate"]["status"] == "fail"


def test_drawing_gate_passes_and_records_checklist(tmp_path: Path) -> None:
    output = tmp_path / "output"
    drawing = output / "drawing"
    drawing.mkdir(parents=True)
    dxf = drawing / "part.dxf"
    dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    result = {"artifacts": [{"kind": "dxf", "path": str(dxf)}]}
    job = _drawing_job(tmp_path)

    def runner(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        report_path = Path(command[command.index("--json") + 1])
        report_path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    evidence = run_gb_drawing_gate(job, result, tmp_path, runner=runner)

    assert evidence is not None
    assert evidence["status"] == "pass"
    assert evidence["failedItems"] == []
    assert Path(evidence["reportPath"]).is_file()
    assert any(item.get("kind") == "gb_checklist" for item in result["artifacts"])


def test_drawing_gate_fails_closed_on_checker_failure(tmp_path: Path) -> None:
    output = tmp_path / "output"
    drawing = output / "drawing"
    drawing.mkdir(parents=True)
    dxf = drawing / "part.dxf"
    dxf.write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    result = {"artifacts": [{"kind": "dxf", "path": str(dxf)}]}
    job = _drawing_job(tmp_path)

    def runner(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        report_path = Path(command[command.index("--json") + 1])
        report_path.write_text(json.dumps(_report("fail"), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="font failed")

    evidence = run_gb_drawing_gate(job, result, tmp_path, runner=runner)

    assert evidence is not None
    assert evidence["status"] == "fail"
    assert "font" in evidence["failedItems"]
    assert "退出码 1" in evidence["message"]


def test_pipeline_timeout_extends_only_drawing_stage(tmp_path: Path) -> None:
    drawing = _drawing_job(tmp_path)
    design = _drawing_job(tmp_path)
    design["uiConfig"]["pipeline"]["stage"] = "design"

    assert _job_timeout_seconds(drawing) == 3600
    assert _job_timeout_seconds(design) == 1800


def test_path_guard_continues_after_cross_drive_root(tmp_path: Path) -> None:
    candidate = tmp_path / "drawing" / "part.dxf"
    candidate.parent.mkdir()
    candidate.write_text("0\nEOF\n", encoding="utf-8")

    assert _is_within(candidate, [Path("Q:/not-the-same-drive"), tmp_path])


def test_process_job_marks_failed_review_when_gb_gate_fails(tmp_path: Path, monkeypatch) -> None:
    queue = tmp_path / "queue"
    project = tmp_path / "project"
    job = {
        "id": "gb-integration",
        "kind": "create_shell",
        "title": "GB 门禁",
        "detail": "工程图阶段门禁",
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-11-07T00:00:00+08:00",
        "updatedAt": "2026-11-07T00:00:00+08:00",
        "projectPath": str(project),
        "expectedOutput": "DWG / DXF / PDF",
        "uiConfig": {
            "outputDir": str(project),
            "pipeline": {"stage": "drawing"},
            "gates": {"strictGbDrawing": True},
        },
    }
    write_job(queue / "gb-integration.json", job)

    def handler(_job: dict) -> dict:
        drawing = project / "drawing"
        drawing.mkdir(parents=True)
        (drawing / "part.dwg").write_bytes(b"AC1032 demo")
        (drawing / "part.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        (drawing / "part.pdf").write_bytes(b"%PDF-1.7\n%demo\n")
        return {
            "mode": "mock",
            "message": "图纸已生成",
            "artifacts": [
                {"kind": "dwg", "path": str(drawing / "part.dwg")},
                {"kind": "dxf", "path": str(drawing / "part.dxf")},
                {"kind": "pdf", "path": str(drawing / "part.pdf")},
            ],
        }

    monkeypatch.setattr(
        "apps.desktop.cad_workbench.queue_worker.run_gb_drawing_gate",
        lambda _job, _result, _cwd: {
            "status": "fail",
            "stage": "gb_drawing",
            "message": "标题栏尺寸不合格",
            "failedItems": ["title_block"],
        },
    )

    process_queue(queue, handlers={"create_shell": handler})

    saved = read_job(queue / "gb-integration.json")
    assert saved["status"] == "failed"
    assert saved["reviewGate"]["status"] == "fail"
    assert any(
        item.get("id") == "gb-drawing-gate" and item.get("status") == "fail"
        for item in saved["reviewGate"]["checks"]
    )


def test_verify_stage_rejects_agent_receipt_without_verification_json(tmp_path: Path) -> None:
    receipt = tmp_path / "agent-result.json"
    receipt.write_text("{}", encoding="utf-8")
    review = evaluate_ledger(
        {
            "jobId": "verify-stage",
            "executor": "agent",
            "pipelineStage": "verify",
            "expectedOutput": "verification.json",
            "artifacts": [
                {
                    "kind": "agent_output",
                    "path": str(receipt),
                    "exists": True,
                    "isDirectory": False,
                    "sizeBytes": receipt.stat().st_size,
                    "sha256": "x",
                    "producedThisRun": True,
                }
            ],
            "verification": [],
            "risks": [],
        }
    )

    assert any(item["id"] == "pipeline-stage-verification" and item["status"] == "fail" for item in review["checks"])
