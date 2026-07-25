from pathlib import Path
import subprocess
import sys
import threading
import time

from apps.desktop.cad_workbench.agent_contracts import DEFAULT_PROFILE, codex_output_path, resolve_workspace, validate_codex_job
from apps.desktop.cad_workbench.queue_worker import (
    JobCancelled,
    _run_command_with_runtime,
    acquire_lock,
    build_codex_prompt,
    event_path_for,
    lock_path_for,
    process_queue,
    read_job,
    recover_stale_jobs,
    release_lock,
    request_cancel,
    run_codex_job,
    write_job,
)


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
    assert saved["attempt"] == 1
    assert saved["runnerId"].startswith("cad-workbench-python-worker-")
    assert saved["heartbeatAt"]
    assert saved["leaseUntil"]
    assert not lock_path_for(job_path).exists()
    event_path = event_path_for(queue_dir, "job-1")
    assert event_path.exists()
    assert "run.passed" in event_path.read_text(encoding="utf-8")


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
    assert "run.cancel_requested" in events
    assert "codex.cancelled" in events


def test_codex_prompt_contains_ui_configuration() -> None:
    job = _queued_job("job-4", "create_shell")
    job.update(
        {
            "executor": "codex",
            "objective": "按配置生成带真实 USB-C 开孔的外壳",
            "expectedOutput": "输出 SLDPRT、STEP、STL 和 GB/T 图纸",
            "strictRules": ["真实开孔必须切透实体", "提交并推送 GitHub"],
            "uiConfig": {"manufacturing": {"process": "FDM"}, "shell": {"wallThickness": 1.6}},
        }
    )

    prompt = build_codex_prompt(job)

    assert "按配置生成带真实 USB-C 开孔的外壳" in prompt
    assert "真实开孔必须切透实体" in prompt
    assert "solidworks-automation skill" in prompt
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


def test_codex_executor_invokes_codex_exec_with_prompt(tmp_path: Path) -> None:
    job = _queued_job("job-6", "create_shell")
    job.update(
        {
            "executor": "codex",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "prompt": "执行一次可控 Codex 桥接测试",
            "codexOutputPath": str(tmp_path / "ignored.md"),
        }
    )
    calls = []

    def fake_runner(command, cwd, timeout_seconds):
        calls.append((command, cwd, timeout_seconds))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["mode"] == "codex"
    assert result["sandbox"] == "workspace-write"
    assert calls[0][0][:2] == ["codex", "exec"]
    assert "执行一次可控 Codex 桥接测试" in calls[0][0]
    assert "-s" in calls[0][0]
    assert "workspace-write" in calls[0][0]
    assert "--output-schema" in calls[0][0]
    assert str(DEFAULT_PROFILE.policy.output_schema_path) in calls[0][0]
    assert str(tmp_path / "ignored.md") not in calls[0][0]
    assert calls[0][2] == 3


def test_enterprise_profile_uses_restricted_default_sandbox() -> None:
    assert DEFAULT_PROFILE.policy.sandbox == "workspace-write"


def test_codex_executor_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    job = _queued_job("job-7", "codex_task")
    job.update({"executor": "codex", "cwd": str(tmp_path), "prompt": "越界测试"})

    try:
        validate_codex_job(job)
    except ValueError as error:
        assert "cwd 不在允许工作区内" in str(error)
    else:
        raise AssertionError("应拒绝仓库外 cwd")


def test_codex_output_path_is_forced_inside_workspace() -> None:
    repo = Path(__file__).resolve().parents[1]
    job = _queued_job("job-8", "codex_task")
    job.update({"executor": "codex", "cwd": str(repo), "codexOutputPath": "C:/Windows/win.ini"})

    cwd = resolve_workspace(job)
    output = codex_output_path(job, cwd)

    assert output == repo / "ai_team" / "job-8_codex_result.md"
