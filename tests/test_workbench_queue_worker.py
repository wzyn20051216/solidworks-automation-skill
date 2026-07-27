import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from apps.desktop.cad_workbench.agent_contracts import (
    DEFAULT_PROFILE,
    codex_output_path,
    load_profile,
    require_policy_approval,
    resolve_workspace,
    validate_codex_job,
)
from apps.desktop.cad_workbench.artifact_ledger import build_artifact_ledger
from apps.desktop.cad_workbench.queue_worker import (
    JobCancelled,
    MOCK_HANDLERS,
    _run_command_with_runtime,
    acquire_lock,
    approve_job,
    build_handlers,
    build_codex_prompt,
    cancel_marker_path,
    event_path_for,
    lock_path_for,
    process_queue,
    read_job,
    recover_stale_jobs,
    release_lock,
    request_cancel,
    resolve_codex_command,
    run_codex_job,
    write_job,
)
from apps.desktop.cad_workbench.worker_health import read_worker_health
from apps.desktop.cad_workbench.reviewer_gate import evaluate_ledger


def test_build_handlers_registers_real_agent_tasks() -> None:
    """@brief 桌面端启用 Agent 后必须真正注册 agent_task，不能只注册旧 Codex 类型。"""
    handlers = build_handlers(enable_codex=True, enable_agent=True)

    assert "codex_task" in handlers
    assert "agent_task" in handlers


def test_process_queue_dispatches_agent_executor_to_agent_task_handler(tmp_path: Path) -> None:
    """@brief Claude 等 Agent 任务不得被内部强制改写为旧 codex_task。"""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    job = _queued_job("agent-dispatch", "agent_task")
    job.update({"executor": "agent", "policy": {"sandbox": "workspace-write", "approval": "never"}})
    write_job(queue_dir / "agent-dispatch.json", job)
    called: list[str] = []

    def handler(active_job: dict) -> dict:
        called.append(str(active_job["id"]))
        return {"mode": "agent", "message": "Claude 执行完成", "outputs": []}

    processed = process_queue(queue_dir, handlers={"agent_task": handler})

    assert called == ["agent-dispatch"]
    assert processed[0]["status"] == "review_required"
    assert processed[0]["result"]["mode"] == "agent"


def _queued_job(job_id: str = "job-1", kind: str = "create_shell") -> dict:
    return {
        "id": job_id,
        "kind": kind,
        "title": "新建外壳",
        "detail": "生成参数化壳体、开孔和基础检查任务",
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-07-25T12:00:00+08:00",
        "updatedAt": "2026-07-25T12:00:00+08:00",
        "projectPath": "D:/demo/demo_shell.step",
    }


def test_write_job_retries_transient_windows_access_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """@brief 队列文件被 Windows 短暂占用时，worker 必须重试而不是直接失败。"""
    original_replace = Path.replace
    attempts = {"denied": 0}

    def flaky_replace(self: Path, target: Path) -> Path:
        if Path(target).name == "job-retry.json" and attempts["denied"] < 2:
            attempts["denied"] += 1
            raise PermissionError(5, "拒绝访问", str(self))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    job_path = tmp_path / "queue" / "job-retry.json"

    write_job(job_path, _queued_job("job-retry"))

    assert attempts["denied"] == 2
    assert read_job(job_path)["id"] == "job-retry"
    assert list(job_path.parent.glob("*.tmp")) == []


def test_queue_worker_processes_queued_job(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-1.json"
    write_job(job_path, _queued_job())

    processed = process_queue(queue_dir, handlers=MOCK_HANDLERS)

    assert len(processed) == 1
    saved = read_job(job_path)
    assert saved["status"] == "review_required"
    assert saved["progress"] == 100
    assert saved["result"]["mode"] == "mock"
    assert [event["status"] for event in saved["workerLog"]] == ["running", "review_required"]
    assert saved["attempt"] == 1
    assert saved["runnerId"].startswith("cad-workbench-python-worker-")
    assert saved["heartbeatAt"]
    assert saved["leaseUntil"]
    assert Path(saved["artifactLedgerPath"]).exists()
    assert Path(saved["reviewGatePath"]).exists()
    assert saved["reviewGate"]["status"] == "warning"
    assert lock_path_for(job_path).exists()
    health = read_worker_health(queue_dir)
    assert health is not None
    assert health["status"] == "attention"
    assert health["processedCount"] == 1
    event_path = event_path_for(queue_dir, "job-1")
    assert event_path.exists()
    assert "artifact.ledger_written" in event_path.read_text(encoding="utf-8")
    assert "review.gate_completed" in event_path.read_text(encoding="utf-8")
    assert "run.review_required" in event_path.read_text(encoding="utf-8")


def test_worker_health_ignores_health_metadata_file(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-health.json"
    write_job(job_path, _queued_job("job-health"))

    process_queue(queue_dir, handlers=MOCK_HANDLERS)
    process_queue(queue_dir, handlers=MOCK_HANDLERS)

    health = read_worker_health(queue_dir)
    assert health is not None
    assert "healthy" not in health["queue"]
    assert health["queue"]["review_required"] == 1


def test_queue_worker_marks_unknown_kind_failed(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-2.json"
    write_job(job_path, _queued_job("job-2", "unknown_kind"))

    processed = process_queue(queue_dir)

    assert len(processed) == 1
    saved = read_job(job_path)
    assert saved["status"] == "failed"
    assert saved["progress"] == 100
    assert "未知任务类型" in saved["error"]


def test_artifact_ledger_records_output_hash(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-ledger.json"
    project_dir = tmp_path / "project"
    output_path = project_dir / "outputs" / "delivery.txt"
    job = _queued_job("job-ledger")
    job["projectPath"] = str(project_dir)
    write_job(job_path, job)

    def handler(job: dict) -> dict:
        output_path.parent.mkdir(parents=True)
        output_path.write_bytes(b"artifact\n")
        return {"mode": "mock", "message": "生成交付物", "outputs": {"report": "outputs/delivery.txt"}}

    process_queue(queue_dir, handlers={"create_shell": handler})

    saved = read_job(job_path)
    ledger = json.loads(Path(saved["artifactLedgerPath"]).read_text(encoding="utf-8"))
    artifact = ledger["artifacts"][0]
    assert ledger["jobId"] == "job-ledger"
    assert artifact["kind"] == "report"
    assert artifact["exists"] is True
    assert artifact["sizeBytes"] == len("artifact\n".encode("utf-8"))
    assert artifact["sha256"] == hashlib.sha256(b"artifact\n").hexdigest()
    assert saved["artifacts"][0]["sha256"] == artifact["sha256"]
    assert saved["reviewGate"]["status"] == "pass"


def test_reviewer_gate_passes_known_cad_file_signatures(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-cad-signatures.json"
    project_dir = tmp_path / "project"
    outputs_dir = project_dir / "outputs"
    job = _queued_job("job-cad-signatures")
    job["projectPath"] = str(project_dir)
    write_job(job_path, job)

    def handler(job: dict) -> dict:
        outputs_dir.mkdir(parents=True)
        (outputs_dir / "model.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        (outputs_dir / "model.stl").write_text("solid demo\nendsolid demo\n", encoding="utf-8")
        (outputs_dir / "drawing.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        (outputs_dir / "drawing.pdf").write_bytes(b"%PDF-1.7\n%demo\n")
        (outputs_dir / "drawing.dwg").write_bytes(b"AC1032 demo")
        return {
            "mode": "mock",
            "message": "生成 CAD 交付物",
            "outputs": {
                "step": "outputs/model.step",
                "stl": "outputs/model.stl",
                "dxf": "outputs/drawing.dxf",
                "pdf": "outputs/drawing.pdf",
                "dwg": "outputs/drawing.dwg",
            },
        }

    process_queue(queue_dir, handlers={"create_shell": handler})

    saved = read_job(job_path)
    checks = saved["reviewGate"]["checks"]
    assert saved["reviewGate"]["status"] == "pass"
    assert any(check["id"] == "artifact-format-step" and check["status"] == "pass" for check in checks)
    assert any(check["id"] == "artifact-format-stl" and check["status"] == "pass" for check in checks)
    assert any(check["id"] == "artifact-format-dxf" and check["status"] == "pass" for check in checks)
    assert any(check["id"] == "artifact-format-pdf" and check["status"] == "pass" for check in checks)
    assert any(check["id"] == "artifact-format-dwg" and check["status"] == "pass" for check in checks)


def test_reviewer_gate_fails_invalid_known_format(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-invalid-format.json"
    project_dir = tmp_path / "project"
    output_path = project_dir / "outputs" / "drawing.pdf"
    job = _queued_job("job-invalid-format")
    job["projectPath"] = str(project_dir)
    write_job(job_path, job)

    def handler(job: dict) -> dict:
        output_path.parent.mkdir(parents=True)
        output_path.write_text("not a pdf", encoding="utf-8")
        return {"mode": "mock", "message": "生成伪 PDF", "outputs": {"pdf": "outputs/drawing.pdf"}}

    process_queue(queue_dir, handlers={"create_shell": handler})

    saved = read_job(job_path)
    checks = saved["reviewGate"]["checks"]
    assert saved["status"] == "failed"
    assert saved["reviewGate"]["status"] == "fail"
    assert any(check["id"] == "artifact-format-pdf" and check["status"] == "fail" for check in checks)


def test_reviewer_gate_fails_missing_artifact(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-missing-artifact.json"
    project_dir = tmp_path / "project"
    job = _queued_job("job-missing-artifact")
    job["projectPath"] = str(project_dir)
    write_job(job_path, job)

    def handler(job: dict) -> dict:
        return {"mode": "mock", "message": "声明了不存在的交付物", "outputs": {"step": "outputs/missing.step"}}

    process_queue(queue_dir, handlers={"create_shell": handler})

    saved = read_job(job_path)
    review = saved["reviewGate"]
    assert saved["status"] == "failed"
    assert review["status"] == "fail"
    assert any(check["status"] == "fail" for check in review["checks"])


def test_reviewer_gate_rejects_codex_receipt_as_cad_delivery(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-no-cad.json"
    receipt = tmp_path / "codex-result.json"
    receipt.write_text('{"summary":"只返回说明"}', encoding="utf-8")
    job = _queued_job("job-no-cad", "codex_task")
    job.update(
        {
            "executor": "codex",
            "expectedOutput": "SLDPRT / STEP / STL",
            "prompt": "生成模型",
            "cwd": str(Path(__file__).resolve().parents[1]),
        }
    )
    write_job(job_path, job)

    def handler(_job: dict) -> dict:
        return {
            "mode": "codex",
            "message": "Codex 已结束",
            "outputPath": str(receipt),
            "verification": [{"command": "echo", "status": "passed", "note": "仅检查回执"}],
        }

    process_queue(queue_dir, handlers={"codex_task": handler})

    saved = read_job(job_path)
    assert saved["status"] == "failed"
    failed_ids = {check["id"] for check in saved["reviewGate"]["checks"] if check["status"] == "fail"}
    assert {"expected-cad-deliverable-sldprt", "expected-cad-deliverable-step", "expected-cad-deliverable-stl"} <= failed_ids


def test_reviewer_gate_rejects_failed_executor_verification(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-verification-failed.json"
    model_path = tmp_path / "model.step"
    model_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    job = _queued_job("job-verification-failed", "codex_task")
    job.update(
        {
            "executor": "codex",
            "expectedOutput": "SLDPRT / STEP / STL",
            "prompt": "生成模型",
            "cwd": str(Path(__file__).resolve().parents[1]),
        }
    )
    write_job(job_path, job)

    def handler(_job: dict) -> dict:
        return {
            "mode": "codex",
            "message": "生成后检查失败",
            "outputs": [{"kind": "step", "path": str(model_path)}],
            "verification": [{"command": "几何检查", "status": "failed", "note": "孔未贯穿"}],
        }

    process_queue(queue_dir, handlers={"codex_task": handler})

    saved = read_job(job_path)
    assert saved["status"] == "failed"
    assert any(check["id"] == "executor-verification-0" and check["status"] == "fail" for check in saved["reviewGate"]["checks"])


def test_reviewer_gate_rejects_cad_spec_mismatch_from_validation_json(tmp_path: Path) -> None:
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(
            {
                "cad_spec": {
                    "measurement_source": "SolidWorks API test fixture",
                    "plate_mm": {"length": 120, "width": 80, "thickness": 8},
                    "holes": [{"diameter_mm": 6}, {"diameter_mm": 12}],
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 校准板，中心孔直径 10 mm，四角孔直径 4 mm。",
        "strictRules": [],
        "resultMessage": "已创建 120 x 80 x 8 mm 校准板。",
        "verification": [{"command": "cad-check", "status": "passed", "note": "执行器自报通过"}],
        "artifacts": [
            {
                "kind": "json",
                "path": str(validation),
                "exists": True,
                "isDirectory": False,
                "sizeBytes": validation.stat().st_size,
                "sha256": hashlib.sha256(validation.read_bytes()).hexdigest(),
                "producedThisRun": True,
            }
        ],
    }

    review = evaluate_ledger(ledger)

    assert review["status"] == "fail"
    assert any(check["id"] == "spec-envelope-dimensions" and check["status"] == "fail" for check in review["checks"])
    assert any(check["id"] == "spec-hole-diameters" and check["status"] == "fail" for check in review["checks"])


def test_reviewer_gate_accepts_matching_cad_spec_evidence(tmp_path: Path) -> None:
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(
            {
                "cad_spec": {
                    "measurement_source": "SolidWorks API test fixture",
                    "plate_mm": {"length": 60, "width": 40, "thickness": 12},
                    "holes": [{"diameter_mm": 4}, {"diameter_mm": 10}],
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 校准板，中心孔直径 10 mm，四角孔直径 4 mm。",
        "strictRules": [],
        "resultMessage": "已完成校准板。",
        "verification": [{"command": "cad-check", "status": "passed", "note": "尺寸已读取"}],
        "artifacts": [
            {
                "kind": "json",
                "path": str(validation),
                "exists": True,
                "isDirectory": False,
                "sizeBytes": validation.stat().st_size,
                "sha256": hashlib.sha256(validation.read_bytes()).hexdigest(),
                "producedThisRun": True,
            }
        ],
    }

    review = evaluate_ledger(ledger)

    assert review["status"] == "pass"
    assert any(check["id"] == "spec-envelope-dimensions" and check["status"] == "pass" for check in review["checks"])
    assert any(check["id"] == "spec-hole-diameters" and check["status"] == "pass" for check in review["checks"])


def test_reviewer_gate_accepts_envelope_with_different_axis_order(tmp_path: Path) -> None:
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(
            {
                "cad_spec": {
                    "measurement_source": "SolidWorks API test fixture",
                    "geometry": {"length_mm": 60, "width_mm": 12, "height_mm": 40},
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 零件。",
        "strictRules": [],
        "verification": [{"command": "cad-check", "status": "passed", "note": "已读取包围盒"}],
        "artifacts": [
            {
                "kind": "json",
                "path": str(validation),
                "exists": True,
                "isDirectory": False,
                "sizeBytes": validation.stat().st_size,
                "sha256": hashlib.sha256(validation.read_bytes()).hexdigest(),
                "producedThisRun": True,
            }
        ],
    }

    review = evaluate_ledger(ledger)

    assert any(check["id"] == "spec-envelope-dimensions" and check["status"] == "pass" for check in review["checks"])


def test_reviewer_gate_fails_when_machine_readable_spec_evidence_is_missing() -> None:
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 校准板，中心孔直径 10 mm。",
        "strictRules": [],
        "resultMessage": "已创建 60 x 40 x 12 mm 校准板，中心孔直径 10 mm。",
        "verification": [{"command": "cad-check", "status": "passed", "note": "执行器自报通过"}],
        "artifacts": [],
    }

    review = evaluate_ledger(ledger)

    assert review["status"] == "fail"
    assert any(check["id"] == "spec-envelope-dimensions" and check["status"] == "fail" for check in review["checks"])
    assert any(check["id"] == "spec-hole-diameters" and check["status"] == "fail" for check in review["checks"])


def test_reviewer_gate_rejects_untrusted_matching_numbers(tmp_path: Path) -> None:
    validation = tmp_path / "agent_claim.json"
    validation.write_text(
        json.dumps(
            {
                "cad_spec": {
                    "plate_mm": {"length": 60, "width": 40, "thickness": 12},
                    "holes": [{"diameter_mm": 10}],
                }
            }
        ),
        encoding="utf-8",
    )
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 校准板，中心孔直径 10 mm。",
        "strictRules": [],
        "verification": [{"command": "agent-claim", "status": "passed", "note": "仅由 Agent 声明"}],
        "artifacts": [
            {
                "kind": "json",
                "path": str(validation),
                "exists": True,
                "isDirectory": False,
                "sizeBytes": validation.stat().st_size,
                "sha256": hashlib.sha256(validation.read_bytes()).hexdigest(),
                "producedThisRun": True,
            }
        ],
    }

    review = evaluate_ledger(ledger)

    assert review["status"] == "fail"
    assert any(check["id"] == "spec-envelope-dimensions" and "缺少独立" in check["message"] for check in review["checks"])
    assert any(check["id"] == "spec-hole-diameters" and "缺少独立" in check["message"] for check in review["checks"])


@pytest.mark.parametrize(
    ("produced_this_run", "sha256"),
    [(False, "actual"), (True, "tampered")],
)
def test_reviewer_gate_rejects_stale_or_tampered_measurement_report(
    tmp_path: Path,
    produced_this_run: bool,
    sha256: str,
) -> None:
    """@brief 旧报告或账本哈希不一致时，机器测量证据不得进入规格门禁。"""
    validation = tmp_path / "cad_review.json"
    validation.write_text(
        json.dumps(
            {
                "cad_spec": {
                    "measurement_source": "SolidWorks API test fixture",
                    "envelope_mm": {"length": 60, "width": 40, "height": 12},
                    "holes": [{"diameter_mm": 10}],
                }
            }
        ),
        encoding="utf-8",
    )
    actual_sha256 = hashlib.sha256(validation.read_bytes()).hexdigest()
    ledger = {
        "executor": "codex",
        "objective": "创建 60 x 40 x 12 mm 零件，中心孔直径 10 mm。",
        "strictRules": [],
        "verification": [],
        "artifacts": [
            {
                "kind": "json",
                "path": str(validation),
                "exists": True,
                "isDirectory": False,
                "sizeBytes": validation.stat().st_size,
                "sha256": actual_sha256 if sha256 == "actual" else sha256,
                "producedThisRun": produced_this_run,
            }
        ],
    }

    review = evaluate_ledger(ledger)

    assert review["status"] == "fail"
    assert any(check["id"] == "spec-envelope-dimensions" and check["status"] == "fail" for check in review["checks"])
    assert any(check["id"] == "spec-hole-diameters" and check["status"] == "fail" for check in review["checks"])


def test_queue_worker_skips_terminal_jobs(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job = _queued_job("job-3", "delivery_package")
    job["status"] = "cancelled"
    write_job(queue_dir / "job-3.json", job)

    processed = process_queue(queue_dir)

    assert processed == []
    assert read_job(queue_dir / "job-3.json")["status"] == "cancelled"


def test_queue_worker_skips_locked_job(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-locked.json"
    write_job(job_path, _queued_job("job-locked"))
    lock_path = acquire_lock(job_path, "other-worker")

    try:
        processed = process_queue(queue_dir)
    finally:
        release_lock(lock_path)

    assert processed == []
    assert read_job(job_path)["status"] == "queued"


def test_queue_worker_quarantines_invalid_json(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    bad_path = queue_dir / "bad.json"
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text("{bad json", encoding="utf-8")

    processed = process_queue(queue_dir)

    assert processed == []
    assert not bad_path.exists()
    quarantined = list((queue_dir / "quarantine").glob("bad_*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].with_suffix(".error.txt").exists()


def test_queue_worker_recovers_stale_running_job(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-stale.json"
    job = _queued_job("job-stale")
    job.update(
        {
            "status": "running",
            "progress": 34,
            "leaseUntil": "2020-01-01T00:00:00+08:00",
            "runnerId": "dead-worker",
            "workerPid": 123,
        }
    )
    write_job(job_path, job)

    recovered = recover_stale_jobs(queue_dir)

    saved = read_job(job_path)
    assert recovered == 1
    assert saved["status"] == "queued"
    assert "runnerId" not in saved
    assert "workerPid" not in saved


def test_queue_worker_does_not_recover_stale_job_while_os_lock_is_held(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-stale-locked.json"
    job = _queued_job("job-stale-locked")
    job.update({"status": "running", "leaseUntil": "2020-01-01T00:00:00+08:00"})
    write_job(job_path, job)
    lock_path = acquire_lock(job_path, "live-worker")

    try:
        recovered = recover_stale_jobs(queue_dir)
    finally:
        release_lock(lock_path)

    assert recovered == 0
    assert read_job(job_path)["status"] == "running"


def test_queue_worker_turns_stale_cancel_request_into_cancelled(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-stale-cancel.json"
    job = _queued_job("job-stale-cancel")
    job.update({"status": "running", "leaseUntil": "2020-01-01T00:00:00+08:00", "cancelRequested": True})
    write_job(job_path, job)
    cancel_marker_path(job_path).write_text("cancel\n", encoding="ascii")

    recovered = recover_stale_jobs(queue_dir)

    saved = read_job(job_path)
    assert recovered == 1
    assert saved["status"] == "cancelled"
    assert saved["cancelRequested"] is True


def test_managed_command_refreshes_heartbeat_and_writes_events(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-managed.json"
    job = _queued_job("job-managed")
    job.update({"status": "running", "runnerId": "runner-1", "leaseUntil": "2020-01-01T00:00:00+08:00"})
    write_job(job_path, job)
    job["_runtime"] = {"jobPath": str(job_path), "runnerId": "runner-1", "leaseSeconds": 3}

    completed = _run_command_with_runtime(
        [sys.executable, "-c", "import time; time.sleep(1); print('done')"],
        tmp_path,
        5,
        job,
    )

    saved = read_job(job_path)
    assert completed.returncode == 0
    assert saved["heartbeatAt"]
    assert saved["leaseUntil"] != "2020-01-01T00:00:00+08:00"
    events = event_path_for(queue_dir, "job-managed").read_text(encoding="utf-8")
    assert "codex.started" in events
    assert "run.heartbeat" in events
    assert "codex.completed" in events


def test_managed_command_stops_when_cancel_requested(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-cancel.json"
    job = _queued_job("job-cancel")
    job.update({"status": "running", "runnerId": "runner-2", "leaseUntil": "2099-01-01T00:00:00+08:00"})
    write_job(job_path, job)
    job["_runtime"] = {"jobPath": str(job_path), "runnerId": "runner-2", "leaseSeconds": 3}

    def cancel_later() -> None:
        time.sleep(0.5)
        request_cancel(job_path)

    thread = threading.Thread(target=cancel_later)
    thread.start()
    try:
        try:
            _run_command_with_runtime([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, 10, job)
        except JobCancelled:
            pass
        else:
            raise AssertionError("应响应取消请求")
    finally:
        thread.join(timeout=2)

    events = event_path_for(queue_dir, "job-cancel").read_text(encoding="utf-8")
    assert cancel_marker_path(job_path).exists()
    assert "run.cancel_requested" in events
    assert "codex.cancelled" in events


def test_codex_prompt_contains_ui_configuration() -> None:
    job = _queued_job("job-4", "create_shell")
    job.update(
        {
            "executor": "codex",
            "objective": "按配置生成带真实 USB-C 开孔的外壳",
            "targetSoftware": "AI 自动选软件",
            "expectedOutput": "输出 SLDPRT、STEP、STL 和 GB/T 图纸",
            "strictRules": ["真实开孔必须切透实体", "提交并推送 GitHub"],
            "uiConfig": {
                "cadRuntime": {
                    "application": "auto",
                    "applicationLabel": "AI 自动选软件",
                    "route": "三维优先 SolidWorks，二维图纸优先 AutoCAD。",
                    "localCadAutomation": True,
                    "solidworksSkillPath": "C:/Users/test-user/.codex/skills/solidworks-automation/SKILL.md",
                    "autocadSkillPath": "C:/Users/test-user/.codex/skills/solidworks-automation/subskills/autocad-automation/SKILL.md",
                },
                "selection": {"mode": "auto_best"},
                "manufacturing": {"process": "auto"},
                "geometry": {"wallThickness": 1.6},
            },
        }
    )

    prompt = build_codex_prompt(job)

    assert "按配置生成带真实 USB-C 开孔的外壳" in prompt
    assert "真实开孔必须切透实体" in prompt
    assert "solidworks-automation skill" in prompt
    assert "autocad-automation skill" in prompt
    assert "目标 CAD 软件" in prompt
    assert "三维优先 SolidWorks，二维图纸优先 AutoCAD。" in prompt
    assert "本机 CAD 自动化: 允许" in prompt
    assert "auto_best" in prompt
    assert "自动选择最佳工程方案" in prompt
    assert '"wallThickness": 1.6' in prompt


def test_codex_executor_requires_enable_flag(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job = _queued_job("job-5", "create_shell")
    job["executor"] = "codex"
    write_job(queue_dir / "job-5.json", job)

    process_queue(queue_dir)

    saved = read_job(queue_dir / "job-5.json")
    assert saved["status"] == "failed"
    assert "--enable-codex" in saved["error"]


def test_resolve_codex_command_uses_node_for_cmd_launcher(tmp_path: Path, monkeypatch) -> None:
    codex_cmd = tmp_path / "codex.cmd"
    codex_cmd.write_text("@echo off\n", encoding="utf-8")
    codex_js = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    codex_js.parent.mkdir(parents=True)
    codex_js.write_text("", encoding="utf-8")
    node_exe = tmp_path / "node.exe"
    node_exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("CODEX_BIN", str(codex_cmd))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker._codex_windowsapps_candidates", lambda: [])
    monkeypatch.setattr(
        "apps.desktop.cad_workbench.queue_worker.shutil.which",
        lambda name: str(node_exe) if name in {"node", "node.exe"} else None,
    )

    command = resolve_codex_command()

    assert command == [str(node_exe), str(codex_js)]
    assert "cmd.exe" not in command


def test_resolve_codex_command_uses_path_exe(tmp_path: Path, monkeypatch) -> None:
    codex_exe = tmp_path / "codex.exe"
    codex_exe.write_text("demo", encoding="utf-8")
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.shutil.which", lambda name: str(codex_exe) if name == "codex.exe" else None)
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker._codex_windowsapps_candidates", lambda: [])

    command = resolve_codex_command()

    assert command == [str(codex_exe)]


def test_codex_executor_invokes_codex_exec_with_prompt(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "codex-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.codex_output_path", lambda job, cwd: output_path)
    job = _queued_job("job-6", "create_shell")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "执行一次可控 Codex 桥接测试",
            "objective": "目标尺寸与企业任务上下文不能被用户补充 prompt 覆盖",
            "codexOutputPath": str(tmp_path / "ignored.md"),
        }
    )
    calls = []

    def fake_runner(command, cwd, timeout_seconds):
        calls.append((command, cwd, timeout_seconds))
        output_path.write_text(
            json.dumps(
                {"summary": "完成", "changedFiles": [], "verification": [], "risks": [], "nextSteps": []},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["mode"] == "codex"
    assert result["sandbox"] == "workspace-write"
    assert calls[0][0][:2] == ["codex", "exec"]
    assert "执行一次可控 Codex 桥接测试" in calls[0][0][-1]
    assert "目标尺寸与企业任务上下文不能被用户补充 prompt 覆盖" in calls[0][0][-1]
    assert "【用户补充 prompt】" in calls[0][0][-1]
    assert "-s" in calls[0][0]
    assert "workspace-write" in calls[0][0]
    assert "-a" not in calls[0][0]
    assert "-c" in calls[0][0]
    assert 'approval_policy="never"' in calls[0][0]
    assert "--output-schema" in calls[0][0]
    assert str(DEFAULT_PROFILE.policy.output_schema_path) in calls[0][0]
    assert str(tmp_path / "ignored.md") not in calls[0][0]
    assert calls[0][2] == 3


def test_codex_executor_fails_when_structured_output_is_missing(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "missing.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.codex_output_path", lambda job, cwd: output_path)
    job = _queued_job("job-no-result", "codex_task")
    job.update({"executor": "codex", "cwd": str(Path(__file__).resolve().parents[1]), "prompt": "不写结果"})

    def fake_runner(command, cwd, timeout_seconds):
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    try:
        run_codex_job(job, runner=fake_runner, timeout_seconds=3)
    except RuntimeError as error:
        assert "未生成结构化结果文件" in str(error)
    else:
        raise AssertionError("Codex 未写结构化结果时必须失败")


def test_codex_executor_parses_structured_artifacts(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "codex-result.json"
    generated = tmp_path / "model.step"
    generated.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.codex_output_path", lambda job, cwd: output_path)
    job = _queued_job("job-structured", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "结构化结果测试",
            "uiConfig": {"outputDir": str(tmp_path)},
        }
    )

    def fake_runner(command, cwd, timeout_seconds):
        output_path.write_text(
            json.dumps(
                {
                    "summary": "已生成模型",
                    "changedFiles": [str(generated)],
                    "verification": [{"command": "check", "status": "passed", "note": "ok"}],
                    "risks": [],
                    "nextSteps": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["message"] == "已生成模型"
    assert any(item["path"] == str(generated) for item in result["artifacts"])
    assert result["verification"][0]["status"] == "passed"


def _evaluate_codex_artifact_run(
    tmp_path: Path,
    monkeypatch,
    expected_output: str,
    changed_files: list[Path],
    mutate_artifacts,
) -> dict:
    output_path = tmp_path / "codex-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.validate_codex_job", lambda job: tmp_path)
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.codex_output_path", lambda job, cwd: output_path)
    job = _queued_job("job-artifact-proof", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(tmp_path),
            "prompt": "本轮交付物证明测试",
            "expectedOutput": expected_output,
            "uiConfig": {"outputDir": str(tmp_path), "cadRuntime": {"localCadAutomation": True}},
        }
    )

    def fake_runner(command, cwd, timeout_seconds):
        mutate_artifacts()
        output_path.write_text(
            json.dumps(
                {
                    "summary": "已生成交付文件",
                    "changedFiles": [str(path) for path in changed_files],
                    "verification": [{"command": "cad-check", "status": "passed", "note": "ok"}],
                    "risks": [],
                    "nextSteps": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)
    ledger = build_artifact_ledger(tmp_path / "queue", job, result)
    return evaluate_ledger(ledger)


def test_codex_old_step_without_change_fails_current_run_proof(tmp_path: Path, monkeypatch) -> None:
    step_path = tmp_path / "old-model.step"
    step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")

    review = _evaluate_codex_artifact_run(tmp_path, monkeypatch, "STEP", [step_path], lambda: None)

    assert review["status"] == "fail"
    assert any(check["id"] == "expected-cad-deliverable-step" and check["status"] == "fail" for check in review["checks"])


def test_codex_touch_only_does_not_pass_current_run_proof(tmp_path: Path, monkeypatch) -> None:
    step_path = tmp_path / "touched-model.step"
    step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")

    review = _evaluate_codex_artifact_run(
        tmp_path,
        monkeypatch,
        "STEP",
        [step_path],
        lambda: os.utime(step_path, None),
    )

    assert review["status"] == "fail"


def test_codex_new_step_passes_current_run_proof(tmp_path: Path, monkeypatch) -> None:
    step_path = tmp_path / "new-model.step"

    review = _evaluate_codex_artifact_run(
        tmp_path,
        monkeypatch,
        "STEP",
        [step_path],
        lambda: step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8"),
    )

    assert review["status"] == "pass"


def test_codex_modified_step_passes_current_run_proof(tmp_path: Path, monkeypatch) -> None:
    step_path = tmp_path / "revised-model.step"
    step_path.write_text("old", encoding="utf-8")

    review = _evaluate_codex_artifact_run(
        tmp_path,
        monkeypatch,
        "STEP",
        [step_path],
        lambda: step_path.write_text("ISO-10303-21;\nUPDATED\nEND-ISO-10303-21;\n", encoding="utf-8"),
    )

    assert review["status"] == "pass"


def test_codex_assembly_package_proves_sldasm_step_and_stl(tmp_path: Path, monkeypatch) -> None:
    assembly_path = tmp_path / "assembly.sldasm"
    step_path = tmp_path / "assembly.step"
    stl_path = tmp_path / "assembly.stl"

    def create_package() -> None:
        assembly_path.write_bytes(b"SolidWorks assembly test payload")
        step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        stl_path.write_text("solid assembly\nendsolid assembly\n", encoding="utf-8")

    review = _evaluate_codex_artifact_run(
        tmp_path,
        monkeypatch,
        "SLDASM / STEP / STL",
        [assembly_path, step_path, stl_path],
        create_package,
    )

    expected_checks = [check for check in review["checks"] if check["id"].startswith("expected-cad-deliverable-")]
    assert len(expected_checks) == 3
    assert all(check["status"] == "pass" for check in expected_checks)
    assert review["status"] == "warning"


def test_codex_executor_rejects_artifact_outside_allowed_roots(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "codex-result.json"
    allowed = tmp_path / "allowed"
    rejected = tmp_path / "outside" / "old-model.step"
    rejected.parent.mkdir(parents=True)
    rejected.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.codex_output_path", lambda job, cwd: output_path)
    job = _queued_job("job-rejected-artifact", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "越界交付物测试",
            "uiConfig": {"outputDir": str(allowed)},
        }
    )

    def fake_runner(command, cwd, timeout_seconds):
        output_path.write_text(
            json.dumps(
                {
                    "summary": "声明旧文件",
                    "changedFiles": [str(rejected)],
                    "verification": [],
                    "risks": [],
                    "nextSteps": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)

    assert all(item["path"] != str(rejected) for item in result["artifacts"])
    assert any("已拒绝" in risk and str(rejected) in risk for risk in result["risks"])


def test_policy_gate_requires_approval_for_git_push(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-git-push.json"
    job = _queued_job("job-git-push", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "提交并推送",
            "capabilities": ["git_push"],
            "policy": {"sandbox": "workspace-write", "approval": "never", "requirePush": True},
        }
    )
    write_job(job_path, job)

    processed = process_queue(queue_dir)

    saved = read_job(job_path)
    assert len(processed) == 1
    assert saved["status"] == "approval_required"
    assert saved["progress"] == 0
    assert "Git push" in saved["lastMessage"]
    assert "policy.approval_required" in event_path_for(queue_dir, "job-git-push").read_text(encoding="utf-8")


def test_policy_gate_allows_approved_job(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-approved.json"
    job = _queued_job("job-approved", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "审批后执行",
            "capabilities": ["git_push"],
            "policy": {"sandbox": "workspace-write", "approval": "never", "requirePush": True},
        }
    )
    write_job(job_path, job)

    process_queue(queue_dir)
    approved = approve_job(job_path, approved_by="tester")

    assert approved["status"] == "queued"
    assert approved["approvedBy"] == "tester"
    assert approved["approvedPolicyReasons"]

    processed = process_queue(
        queue_dir,
        handlers={"codex_task": lambda active_job: {"mode": "codex", "message": f"已执行 {active_job['id']}"}},
    )

    saved = read_job(job_path)
    assert len(processed) == 1
    assert saved["status"] == "review_required"
    assert saved["result"]["mode"] == "codex"


def test_policy_gate_rechecks_approved_scope_after_job_changes(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-scope.json"
    job = _queued_job("job-scope", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "审批范围测试",
            "capabilities": ["git_push"],
            "policy": {"sandbox": "workspace-write", "approval": "never", "requirePush": True},
        }
    )
    write_job(job_path, job)
    process_queue(queue_dir)
    approved = approve_job(job_path, approved_by="tester")
    approved["policy"]["sandbox"] = "danger-full-access"
    write_job(job_path, approved)

    reasons = require_policy_approval(read_job(job_path))

    assert reasons
    assert any("danger-full-access" in reason for reason in reasons)


def test_policy_gate_requires_approval_for_danger_full_access(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-full-access.json"
    job = _queued_job("job-full-access", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "全权限测试",
            "policy": {"sandbox": "danger-full-access", "approval": "never", "requirePush": False},
        }
    )
    write_job(job_path, job)

    process_queue(queue_dir)

    saved = read_job(job_path)
    assert saved["status"] == "approval_required"
    assert any("danger-full-access" in reason for reason in saved["approvalReasons"])


def test_policy_gate_requires_approval_for_dangerous_capability(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-cad-macro.json"
    job = _queued_job("job-cad-macro", "codex_task")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "CAD 宏测试",
            "capabilities": ["cad_macro"],
            "policy": {"sandbox": "workspace-write", "approval": "never", "requirePush": False},
        }
    )
    write_job(job_path, job)

    process_queue(queue_dir)

    saved = read_job(job_path)
    assert saved["status"] == "approval_required"
    assert any("CAD 宏" in reason for reason in saved["approvalReasons"])


def test_codex_full_access_requires_policy_and_cli_flag(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    calls = []

    def fake_runner(command, cwd, timeout_seconds):
        calls.append(command)
        Path(command[command.index("-o") + 1]).write_text(
            json.dumps(
                {"summary": "完成", "changedFiles": [], "verification": [], "risks": [], "nextSteps": []},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    job = _queued_job("job-full-cli", "codex_task")
    job.update({"executor": "codex", "cwd": str(repo), "prompt": "沙箱测试", "policy": {"sandbox": "danger-full-access"}})

    result_without_cli = run_codex_job(job, runner=fake_runner, allow_full_access=False)
    result_with_cli = run_codex_job(job, runner=fake_runner, allow_full_access=True)

    assert result_without_cli["sandbox"] == "workspace-write"
    assert result_with_cli["sandbox"] == "danger-full-access"
    assert calls[0][calls[0].index("-s") + 1] == "workspace-write"
    assert calls[1][calls[1].index("-s") + 1] == "danger-full-access"


def test_enterprise_profile_uses_restricted_default_sandbox() -> None:
    assert DEFAULT_PROFILE.policy.sandbox == "workspace-write"


def test_loaded_profile_uses_restricted_default_sandbox(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({"name": "custom", "policy": {}}), encoding="utf-8")

    profile = load_profile(profile_path)

    assert profile.policy.sandbox == "workspace-write"


def test_codex_executor_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    job = _queued_job("job-7", "codex_task")
    job.update({"executor": "codex", "cwd": str(tmp_path), "prompt": "越界测试"})

    try:
        validate_codex_job(job)
    except ValueError as error:
        assert "cwd 不在允许工作区内" in str(error)
    else:
        raise AssertionError("应拒绝仓库外 cwd")


@pytest.mark.skipif(os.name != "nt", reason="Windows 扩展路径仅在 Windows 上验证")
def test_resolve_workspace_accepts_windows_extended_path_prefix() -> None:
    """@brief Windows 扩展路径与普通盘符路径必须被识别为同一工作区。"""
    repo = Path(__file__).resolve().parents[1]
    extended_repo = Path("\\\\?\\" + str(repo))

    resolved = resolve_workspace({"cwd": str(extended_repo)}, allowed_roots=[repo])

    assert resolved == repo


@pytest.mark.skipif(os.name != "nt", reason="Windows 扩展路径仅在 Windows 上验证")
def test_resolve_workspace_still_rejects_extended_path_outside_allowed_root() -> None:
    """@brief 去掉扩展路径前缀后仍必须执行工作区边界检查。"""
    repo = Path(__file__).resolve().parents[1]
    extended_parent = Path("\\\\?\\" + str(repo.parent))

    with pytest.raises(ValueError, match="cwd 不在允许工作区内"):
        resolve_workspace({"cwd": str(extended_parent)}, allowed_roots=[repo])


def test_codex_output_path_is_forced_inside_workspace() -> None:
    repo = Path(__file__).resolve().parents[1]
    job = _queued_job("job-8", "codex_task")
    job.update({"executor": "codex", "cwd": str(repo), "codexOutputPath": "C:/Windows/win.ini"})

    cwd = resolve_workspace(job)
    output = codex_output_path(job, cwd)

    assert output == repo / "ai_team" / "job-8_codex_result.json"
