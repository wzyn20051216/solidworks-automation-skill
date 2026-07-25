import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from apps.desktop.cad_workbench.agent_contracts import (
    DEFAULT_PROFILE,
    codex_output_path,
    load_profile,
    require_policy_approval,
    resolve_workspace,
    validate_codex_job,
)
from apps.desktop.cad_workbench.queue_worker import (
    JobCancelled,
    _run_command_with_runtime,
    acquire_lock,
    approve_job,
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
from apps.desktop.cad_workbench.worker_health import read_worker_health


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
    assert Path(saved["artifactLedgerPath"]).exists()
    assert Path(saved["reviewGatePath"]).exists()
    assert saved["reviewGate"]["status"] == "warning"
    assert not lock_path_for(job_path).exists()
    health = read_worker_health(queue_dir)
    assert health is not None
    assert health["status"] == "healthy"
    assert health["processedCount"] == 1
    event_path = event_path_for(queue_dir, "job-1")
    assert event_path.exists()
    assert "artifact.ledger_written" in event_path.read_text(encoding="utf-8")
    assert "review.gate_completed" in event_path.read_text(encoding="utf-8")
    assert "run.passed" in event_path.read_text(encoding="utf-8")


def test_worker_health_ignores_health_metadata_file(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    job_path = queue_dir / "job-health.json"
    write_job(job_path, _queued_job("job-health"))

    process_queue(queue_dir)
    process_queue(queue_dir)

    health = read_worker_health(queue_dir)
    assert health is not None
    assert "healthy" not in health["queue"]
    assert health["queue"]["passed"] == 1


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
    assert review["status"] == "fail"
    assert any(check["status"] == "fail" for check in review["checks"])


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
    assert saved["status"] == "passed"
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


def test_codex_output_path_is_forced_inside_workspace() -> None:
    repo = Path(__file__).resolve().parents[1]
    job = _queued_job("job-8", "codex_task")
    job.update({"executor": "codex", "cwd": str(repo), "codexOutputPath": "C:/Windows/win.ini"})

    cwd = resolve_workspace(job)
    output = codex_output_path(job, cwd)

    assert output == repo / "ai_team" / "job-8_codex_result.md"
