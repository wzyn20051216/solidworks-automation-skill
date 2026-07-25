from pathlib import Path

from apps.desktop.cad_workbench.queue_worker import process_queue, read_job, write_job


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


def test_queue_worker_processes_queued_job(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-1.json"
    write_job(job_path, _queued_job())

    processed = process_queue(queue_dir)

    assert len(processed) == 1
    saved = read_job(job_path)
    assert saved["status"] == "passed"
    assert saved["progress"] == 100
    assert saved["result"]["mode"] == "mock"
    assert [event["status"] for event in saved["workerLog"]] == ["running", "passed"]


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


def test_queue_worker_skips_terminal_jobs(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job = _queued_job("job-3", "delivery_package")
    job["status"] = "cancelled"
    write_job(queue_dir / "job-3.json", job)

    processed = process_queue(queue_dir)

    assert processed == []
    assert read_job(queue_dir / "job-3.json")["status"] == "cancelled"
