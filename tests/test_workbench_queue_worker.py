from pathlib import Path
import subprocess

from apps.desktop.cad_workbench.queue_worker import build_codex_prompt, process_queue, read_job, run_codex_job, write_job


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


def test_codex_prompt_contains_ui_configuration() -> None:
    job = _queued_job("job-4", "create_shell")
    job.update(
        {
            "executor": "codex",
            "objective": "按配置生成带真实 USB-C 开孔的外壳",
            "expectedOutput": "输出 SLDPRT、STEP、STL 和 GB/T 图纸",
            "strictRules": ["真实开孔必须切透实体", "提交并推送 GitHub"],
        }
    )

    prompt = build_codex_prompt(job)

    assert "按配置生成带真实 USB-C 开孔的外壳" in prompt
    assert "真实开孔必须切透实体" in prompt
    assert "solidworks-automation skill" in prompt


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
            "cwd": str(tmp_path),
            "prompt": "执行一次可控 Codex 桥接测试",
            "codexOutputPath": str(tmp_path / "codex_result.md"),
        }
    )
    calls = []

    def fake_runner(command, cwd, timeout_seconds):
        calls.append((command, cwd, timeout_seconds))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = run_codex_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["mode"] == "codex"
    assert calls[0][0][:2] == ["codex", "exec"]
    assert "执行一次可控 Codex 桥接测试" in calls[0][0]
    assert calls[0][1] == tmp_path
    assert calls[0][2] == 3
