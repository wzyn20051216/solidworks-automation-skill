"""@brief CAD Studio 本地自动化队列 worker 原型。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import uuid
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .agent_contracts import (
    DEFAULT_PROFILE,
    agent_output_path,
    codex_output_path,
    compile_codex_prompt,
    policy_reasons,
    require_policy_approval,
    validate_codex_job,
)
from .agent_providers import AgentProvider, build_provider_command, parse_provider_result, resolve_provider
from .artifact_ledger import sha256_file, write_artifact_ledger
from .core import CN_TZ, now_iso
from .engineering_orchestrator import (
    build_engineering_plan,
    engineering_plan_from_dict,
    replan_for_local_change,
    requires_engineering_orchestration,
)
from .knowledge_retrieval import build_job_knowledge_context
from .reviewer_gate import write_reviewer_gate
from .worker_health import QUEUE_METADATA_FILES, write_worker_health


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]

WORKER_NAME = "cad-workbench-python-worker"
KNOWN_JOB_KINDS = {"create_shell", "import_model", "delivery_package", "codex_task", "agent_task"}
TERMINAL_STATES = {"passed", "review_required", "failed", "cancelled"}
NON_EXECUTABLE_STATES = {"approval_required", *TERMINAL_STATES}
DEFAULT_CODEX_TIMEOUT_SECONDS = 1800
DEFAULT_LEASE_SECONDS = 900
CAD_ARTIFACT_EXTENSIONS = {".sldprt", ".sldasm", ".step", ".stp", ".stl", ".dwg", ".dxf", ".pdf", ".iges", ".igs"}
PROVIDER_VERIFICATION_FILE = "provider_verifications.json"
_ACTIVE_LOCKS: dict[Path, BinaryIO] = {}
_ACTIVE_LOCKS_GUARD = threading.Lock()
QUEUE_WRITE_RETRIES = 24


class JobCancelled(RuntimeError):
    """@brief 任务被用户取消。"""


def _codex_windowsapps_candidates() -> list[Path]:
    """@brief 返回 Windows Store 版 Codex 的候选 exe 路径。"""
    candidates: list[Path] = []
    windows_apps = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WindowsApps"
    try:
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/*/resources/codex.exe")))
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/app/resources/codex.exe")))
    except OSError:
        return []
    return candidates


def _node_codex_command(npm_root: Path) -> list[str] | None:
    """@brief 直接通过 Node 启动 npm Codex，避免 cmd.exe 二次解析用户 prompt。"""
    script = npm_root / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    if not script.is_file():
        return None
    bundled_node = npm_root / "node.exe"
    node = str(bundled_node) if bundled_node.is_file() else (shutil.which("node.exe") or shutil.which("node"))
    return [node, str(script)] if node else None


def resolve_codex_command() -> list[str]:
    """@brief 解析可由 Python worker 可靠启动的 Codex CLI 命令。"""
    env_path = os.environ.get("CODEX_BIN")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            if candidate.suffix.lower() in {".cmd", ".bat"}:
                command = _node_codex_command(candidate.parent)
                if command:
                    return command
            else:
                return [str(candidate)]

    appdata = os.environ.get("APPDATA")
    if appdata:
        command = _node_codex_command(Path(appdata) / "npm")
        if command:
            return command

    candidates: list[Path] = []
    for name in ("codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(_codex_windowsapps_candidates())

    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        return [str(candidate)]

    raise FileNotFoundError(
        "没有找到 Codex CLI。请在设置里同步 CC Switch 或确认已安装 Codex，并把 codex.exe/codex.cmd 加入 PATH。"
    )


def default_tauri_queue_dir(identifier: str = "com.wzyn.cadstudio") -> Path:
    """@brief 返回 Tauri 默认应用数据队列目录。"""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / identifier / "queue"
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / identifier / "queue"
    return Path.home() / ".local" / "share" / identifier / "queue"


def read_job(path: Path) -> dict[str, Any]:
    """@brief 读取单个队列任务 JSON。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"任务不是 JSON 对象: {path}")
    return payload


def write_job(path: Path, job: dict[str, Any]) -> None:
    """@brief 原子回写单个队列任务 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, job)


def _queue_write_delay(attempt: int) -> float:
    """@brief 返回 Windows 队列文件被短暂占用时的退避时间。"""
    return min(0.025 + attempt * 0.025, 0.25)


def atomic_replace_with_retry(temporary: Path, target: Path) -> None:
    """@brief 用重试机制替换队列文件，规避 Windows 瞬时文件锁。"""
    last_error: OSError | None = None
    for attempt in range(QUEUE_WRITE_RETRIES):
        try:
            temporary.replace(target)
            return
        except OSError as error:
            last_error = error
            time.sleep(_queue_write_delay(attempt))
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    raise OSError(
        f"队列文件写入失败，Windows 暂时拒绝访问 {target}。"
        "请关闭重复运行的 CAD Studio/Worker，或稍后重试。"
    ) from last_error


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """@brief 使用唯一临时文件写入 JSON，再原子替换目标文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    atomic_replace_with_retry(temporary, path)


def cancel_marker_path(path: Path) -> Path:
    """@brief 返回跨进程取消标记路径，避免任务 JSON 并发回写吞掉取消请求。"""
    path = Path(path)
    return path.with_suffix(path.suffix + ".cancel")


def is_cancel_requested(path: Path, job: dict[str, Any] | None = None) -> bool:
    """@brief 同时检查独立标记和任务字段。"""
    if cancel_marker_path(path).exists():
        return True
    current = job if job is not None else read_job(path)
    return current.get("status") == "cancelled" or current.get("cancelRequested") is True


def worker_id() -> str:
    """@brief 返回当前 worker 进程的短标识。"""
    return f"{WORKER_NAME}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def lock_path_for(path: Path) -> Path:
    """@brief 返回任务文件对应的领取锁路径。"""
    return Path(str(path) + ".lock")


def quarantine_dir(queue_dir: Path) -> Path:
    """@brief 返回坏任务隔离目录。"""
    directory = Path(queue_dir) / "quarantine"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def events_dir(queue_dir: Path) -> Path:
    """@brief 返回任务事件流目录。"""
    directory = Path(queue_dir) / "events"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def logs_dir(queue_dir: Path) -> Path:
    """@brief 返回运行日志目录。"""
    directory = Path(queue_dir) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def event_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief 返回任务 JSONL 事件文件路径。"""
    safe_id = "".join(ch for ch in str(job_id or "") if ch.isascii() and (ch.isalnum() or ch in "-_"))
    if not safe_id:
        safe_id = "unknown"
    return events_dir(queue_dir) / f"{safe_id[:96]}.jsonl"


def log_paths_for(queue_dir: Path, job_id: Any) -> tuple[Path, Path]:
    """@brief 返回任务 stdout/stderr 日志路径。"""
    safe_id = "".join(ch for ch in str(job_id or "") if ch.isascii() and (ch.isalnum() or ch in "-_")) or "unknown"
    directory = logs_dir(queue_dir)
    return directory / f"{safe_id[:96]}.stdout.log", directory / f"{safe_id[:96]}.stderr.log"


def append_event(queue_dir: Path, job: dict[str, Any], event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    """@brief 追加一条结构化队列事件。"""
    event = {
        "type": event_type,
        "jobId": job.get("id"),
        "runId": job.get("runId"),
        "status": job.get("status"),
        "progress": job.get("progress"),
        "message": message,
        "at": now_iso(),
        "worker": WORKER_NAME,
        "runnerId": job.get("runnerId"),
        "data": data or {},
    }
    path = event_path_for(queue_dir, job.get("id"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_iso(value: Any) -> datetime | None:
    """@brief 解析 ISO 时间，失败返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def lease_until(seconds: int = DEFAULT_LEASE_SECONDS) -> str:
    """@brief 返回 lease 过期时间。"""
    return (datetime.now(CN_TZ) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def is_expired(value: Any) -> bool:
    """@brief 判断 lease 是否过期。"""
    parsed = parse_iso(value)
    if parsed is None:
        return True
    return parsed <= datetime.now(CN_TZ)


def quarantine_bad_job(path: Path, error: Exception) -> Path:
    """@brief 隔离无法解析的任务文件，避免 watch 循环中断。"""
    path = Path(path)
    target = quarantine_dir(path.parent) / f"{path.stem}_{datetime.now(CN_TZ).strftime('%Y%m%d_%H%M%S')}.json"
    shutil.move(str(path), str(target))
    report = target.with_suffix(".error.txt")
    report.write_text(str(error), encoding="utf-8")
    return target


def acquire_lock(path: Path, runner_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Path | None:
    """@brief 获取由操作系统维护生命周期的文件锁。"""
    lock_path = lock_path_for(path)
    payload = json.dumps(
        {
            "runnerId": runner_id,
            "pid": os.getpid(),
            "lockedAt": now_iso(),
            "leaseUntil": lease_until(lease_seconds),
        },
        ensure_ascii=False,
        indent=2,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _ACTIVE_LOCKS_GUARD:
        if lock_path in _ACTIVE_LOCKS:
            return None
        handle = lock_path.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        handle.seek(0)
        handle.truncate()
        handle.write(payload.encode("utf-8"))
        handle.flush()
        _ACTIVE_LOCKS[lock_path] = handle
    return lock_path


def release_lock(lock_path: Path | None) -> None:
    """@brief 释放文件锁；锁文件保留，进程退出时操作系统也会自动释放锁。"""
    if lock_path is None:
        return
    path = Path(lock_path)
    with _ACTIVE_LOCKS_GUARD:
        handle = _ACTIVE_LOCKS.pop(path, None)
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def mark_job_claimed(job: dict[str, Any], runner_id: str, lease_seconds: int) -> None:
    """@brief 写入任务领取信息。"""
    job["runnerId"] = runner_id
    job["workerPid"] = os.getpid()
    job["heartbeatAt"] = now_iso()
    job["leaseUntil"] = lease_until(lease_seconds)
    job["attempt"] = int(job.get("attempt") or 0) + 1


def refresh_job_heartbeat(path: Path, runner_id: str, lease_seconds: int, message: str = "worker heartbeat") -> dict[str, Any]:
    """@brief 刷新运行中任务 heartbeat 与 lease。"""
    job = read_job(path)
    if is_cancel_requested(path, job):
        raise JobCancelled("任务已请求取消")
    job["runnerId"] = runner_id
    job["workerPid"] = os.getpid()
    job["heartbeatAt"] = now_iso()
    job["leaseUntil"] = lease_until(lease_seconds)
    job["lastMessage"] = message
    write_job(path, job)
    append_event(path.parent, job, "run.heartbeat", message)
    return job


def request_cancel(path: Path) -> dict[str, Any]:
    """@brief 将任务标记为请求取消。"""
    cancel_marker_path(path).write_text("cancel\n", encoding="ascii")
    job = read_job(path)
    job["cancelRequested"] = True
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "已请求取消，等待 worker 停止当前步骤。"
    write_job(path, job)
    append_event(path.parent, job, "run.cancel_requested", "已请求取消")
    return job


def approve_job(path: Path, approved_by: str = "local-user") -> dict[str, Any]:
    """@brief 人工批准待审批任务重新进入队列。"""
    job = read_job(path)
    if job.get("status") != "approval_required":
        return job
    reasons = policy_reasons(job)
    job["approvedBy"] = approved_by
    job["approvedAt"] = now_iso()
    job["approvedPolicyReasons"] = reasons
    job["status"] = "queued"
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "人工审批已通过，任务重新进入队列。"
    write_job(path, job)
    append_event(path.parent, job, "policy.approved", "人工审批已通过", {"approvedBy": approved_by})
    return job


def mark_approval_required(path: Path, job: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    """@brief 将任务置为待审批状态。"""
    job["status"] = "approval_required"
    job["progress"] = 0
    job["approvalReasons"] = reasons
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "任务需要人工审批: " + "；".join(reasons)
    append_worker_event(job, "approval_required", job["lastMessage"])
    write_job(path, job)
    append_event(path.parent, job, "policy.approval_required", job["lastMessage"], {"reasons": reasons})
    return job


def recover_stale_jobs(queue_dir: Path) -> int:
    """@brief 将 lease 过期的 running 任务恢复为 queued。"""
    recovered = 0
    recovery_runner_id = f"{worker_id()}-recovery"
    for path in sorted(Path(queue_dir).glob("*.json")):
        if path.name in QUEUE_METADATA_FILES:
            continue
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") != "running" or not is_expired(job.get("leaseUntil")):
            continue
        lock_path = acquire_lock(path, recovery_runner_id)
        if lock_path is None:
            continue
        try:
            job = read_job(path)
            if job.get("status") != "running" or not is_expired(job.get("leaseUntil")):
                continue
            cancel_requested = is_cancel_requested(path, job)
            if cancel_requested:
                set_job_state(job, "cancelled", int(job.get("progress") or 0), "worker lease 已过期，取消请求已生效。")
                job["cancelRequested"] = True
                event_type = "run.cancelled"
            else:
                set_job_state(job, "queued", 0, "worker lease 已过期，任务已恢复排队。")
                job.pop("cancelRequested", None)
                cancel_marker_path(path).unlink(missing_ok=True)
                event_type = "run.recovered_stale"
            job.pop("runnerId", None)
            job.pop("workerPid", None)
            job.pop("heartbeatAt", None)
            job.pop("leaseUntil", None)
            write_job(path, job)
            append_event(path.parent, job, event_type, job["lastMessage"])
            recovered += 1
        finally:
            release_lock(lock_path)
    return recovered


def append_worker_event(job: dict[str, Any], status: str, message: str) -> None:
    """@brief 在任务中追加 worker 状态流水，便于 UI 和测试追踪。"""
    events = job.setdefault("workerLog", [])
    if isinstance(events, list):
        events.append(
            {
                "status": status,
                "message": message,
                "at": now_iso(),
                "worker": WORKER_NAME,
            }
        )


def set_job_state(job: dict[str, Any], status: str, progress: int, message: str) -> None:
    """@brief 更新任务状态、进度和最后执行信息。"""
    job["status"] = status
    job["progress"] = max(0, min(100, int(progress)))
    job["updatedAt"] = now_iso()
    job["lastMessage"] = message
    append_worker_event(job, status, message)


def mock_create_shell(job: dict[str, Any]) -> dict[str, Any]:
    """@brief mock 生成外壳任务，后续替换为 SolidWorks COM handler。"""
    return {
        "mode": "mock",
        "message": "已完成外壳、真实开孔和 3D 打印基础检查的 mock 流程。",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def mock_import_model(job: dict[str, Any]) -> dict[str, Any]:
    """@brief mock 导入模型任务，后续替换为模型解析 handler。"""
    return {
        "mode": "mock",
        "message": "已记录模型路径并创建项目上下文 mock 结果。",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def mock_delivery_package(job: dict[str, Any]) -> dict[str, Any]:
    """@brief mock 交付包任务，后续替换为真实导出和打包 handler。"""
    return {
        "mode": "mock",
        "message": "已完成 STEP、STL、PDF、DWG 交付清单 mock 汇总。",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def build_codex_prompt(job: dict[str, Any]) -> str:
    """@brief 把图形化配置任务转换为 Codex 可执行提示词。"""
    return compile_codex_prompt(job, profile=DEFAULT_PROFILE)


def _artifact_roots(job: dict[str, Any], cwd: Path) -> list[Path]:
    """@brief 返回任务允许声明交付物的工作区、输出目录和输入文件目录。"""
    roots = [cwd.resolve()]
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    output_dir = ui_config.get("outputDir")
    if output_dir:
        candidate = Path(str(output_dir)).expanduser()
        roots.append((candidate if candidate.is_absolute() else cwd / candidate).resolve())
    project_path = job.get("projectPath")
    if project_path:
        candidate = Path(str(project_path)).expanduser()
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        roots.append((candidate.parent if candidate.suffix else candidate).resolve())
    return roots


def _path_in_roots(path: Path, roots: list[Path]) -> bool:
    """@brief 判断路径是否位于任一允许根目录内。"""
    return any(root == path or root in path.parents for root in roots)


def _snapshot_cad_artifacts(roots: list[Path], limit: int = 10000) -> dict[str, dict[str, Any]]:
    """@brief 记录执行前 CAD 文件元数据，用于证明交付物在本轮新增或发生变化。"""
    snapshot: dict[str, dict[str, Any]] = {}
    visited: set[Path] = set()
    for root in roots:
        if root in visited or not root.exists():
            continue
        visited.add(root)
        candidates = [root] if root.is_file() else root.rglob("*")
        try:
            for candidate in candidates:
                if len(snapshot) >= limit:
                    return snapshot
                if not candidate.is_file() or candidate.suffix.lower() not in CAD_ARTIFACT_EXTENSIONS:
                    continue
                stat = candidate.stat()
                snapshot[str(candidate.resolve())] = {
                    "sizeBytes": stat.st_size,
                    "mtimeNs": stat.st_mtime_ns,
                    "sha256": sha256_file(candidate),
                }
        except OSError:
            continue
    return snapshot


def _validate_codex_result(value: Any) -> dict[str, Any]:
    """@brief 严格校验 Codex 最终 JSON，避免只检查字段存在就进入交付门禁。"""
    if not isinstance(value, dict):
        raise RuntimeError("Codex 结构化结果必须是 JSON 对象")
    required_fields = {"summary", "changedFiles", "verification", "risks", "nextSteps"}
    missing_fields = sorted(required_fields.difference(value))
    if missing_fields:
        raise RuntimeError(f"Codex 结构化结果缺少字段: {', '.join(missing_fields)}")
    if not isinstance(value["summary"], str):
        raise RuntimeError("Codex 结构化结果 summary 必须是字符串")
    for field in ("changedFiles", "risks", "nextSteps"):
        if not isinstance(value[field], list) or not all(isinstance(item, str) for item in value[field]):
            raise RuntimeError(f"Codex 结构化结果 {field} 必须是字符串数组")
    if not isinstance(value["verification"], list):
        raise RuntimeError("Codex 结构化结果 verification 必须是数组")
    for index, item in enumerate(value["verification"]):
        if not isinstance(item, dict):
            raise RuntimeError(f"verification[{index}] 必须是对象")
        if set(item) != {"command", "status", "note"}:
            raise RuntimeError(f"verification[{index}] 字段不符合 Schema")
        if not isinstance(item["command"], str) or not isinstance(item["note"], str):
            raise RuntimeError(f"verification[{index}] command/note 必须是字符串")
        if item["status"] not in {"passed", "failed", "skipped"}:
            raise RuntimeError(f"verification[{index}] status 非法: {item['status']}")
    return value


def _provider_id_for_job(job: dict[str, Any]) -> str:
    """@brief 从统一任务协议读取 Provider，旧 Codex 任务自动兼容。"""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    agent_runtime = ui_config.get("agentRuntime") if isinstance(ui_config.get("agentRuntime"), dict) else {}
    return str(agent_runtime.get("provider") or "codex").strip().lower()


def record_provider_verification(queue_dir: Path, provider: AgentProvider) -> Path:
    """@brief 记录真实结构化任务成功证据，供桌面端健康状态读取。"""
    verification_path = Path(queue_dir) / PROVIDER_VERIFICATION_FILE
    try:
        current = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.is_file() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        current = {}
    providers = current.get("providers") if isinstance(current, dict) and isinstance(current.get("providers"), dict) else {}
    providers[provider.id] = {
        "verified": True,
        "verifiedAt": now_iso(),
        "protocol": provider.protocol,
        "resultSchema": "codex_final_response.schema.json",
    }
    atomic_write_json(verification_path, {"schemaVersion": "1.0", "providers": providers})
    return verification_path


def previous_engineering_plan(job: dict[str, Any]) -> dict[str, Any] | None:
    """@brief 从同一队列的上一轮对话任务恢复 DAG，并按本轮要求局部重规划。"""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    source_job_id = str(ui_config.get("sourceJobId") or "").strip()
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    current_job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else None
    if not source_job_id or current_job_path is None or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", source_job_id) is None:
        return None
    source_path = current_job_path.parent / f"{source_job_id}.json"
    try:
        source_job = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    result = source_job.get("result") if isinstance(source_job, dict) and isinstance(source_job.get("result"), dict) else {}
    payload = result.get("engineeringPlan") if isinstance(result.get("engineeringPlan"), dict) else None
    if payload is None:
        return None
    objective = str(job.get("objective") or job.get("detail") or "").strip()
    try:
        return replan_for_local_change(engineering_plan_from_dict(payload), objective).to_dict()
    except (KeyError, TypeError, ValueError):
        return None


def run_agent_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    allow_full_access: bool = False,
) -> dict[str, Any]:
    """@brief 通过统一 Provider Adapter 调用本机 Agent CLI。"""
    cwd = validate_codex_job(job)
    provider_id = _provider_id_for_job(job)
    if runner is None:
        provider = resolve_provider(provider_id)
    else:
        names = {"codex": "Codex", "claude": "Claude Code", "gemini": "Gemini CLI", "opencode": "OpenCode"}
        protocols = {
            "codex": "codex-exec-v1",
            "claude": "claude-print-v1",
            "gemini": "gemini-headless-v1",
            "opencode": "opencode-jsonl-v1",
        }
        if provider_id not in names:
            raise ValueError(f"不支持的 Agent Provider: {provider_id}")
        provider = AgentProvider(provider_id, names[provider_id], protocols[provider_id], provider_id in {"codex", "claude"}, True, (provider_id,))
    prompt_job = dict(job)
    prompt_job["_knowledgeContext"] = build_job_knowledge_context(job)
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    orchestration = ui_config.get("engineeringOrchestration") if isinstance(ui_config.get("engineeringOrchestration"), dict) else {}
    objective = str(job.get("objective") or job.get("detail") or "")
    orchestration_mode = str(orchestration.get("mode") or "auto_dag")
    if orchestration_mode != "off":
        continued_plan = previous_engineering_plan(job)
        if continued_plan is not None:
            prompt_job["_engineeringPlan"] = continued_plan
        elif requires_engineering_orchestration(objective):
            prompt_job["_engineeringPlan"] = build_engineering_plan(objective).to_dict()
    prompt = build_codex_prompt(prompt_job)
    legacy_codex = job.get("executor") == "codex" and provider.id == "codex"
    output_path = codex_output_path(job, cwd) if legacy_codex else agent_output_path(job, cwd)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    engineering_plan_path: Path | None = None
    if isinstance(prompt_job.get("_engineeringPlan"), dict):
        engineering_plan_path = output_path.with_suffix(".engineering-plan.json")
        engineering_plan_path.write_text(
            json.dumps(prompt_job["_engineeringPlan"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    allowed_roots = _artifact_roots(job, cwd)
    artifact_baseline = _snapshot_cad_artifacts(allowed_roots)
    policy = job.get("policy") if isinstance(job.get("policy"), dict) else {}
    requested_sandbox = policy.get("sandbox")
    sandbox = "danger-full-access" if allow_full_access and requested_sandbox == "danger-full-access" else "workspace-write"

    agent_runtime = ui_config.get("agentRuntime") if isinstance(ui_config.get("agentRuntime"), dict) else {}
    model = str(agent_runtime.get("model") or "").strip() or None
    command = build_provider_command(
        provider,
        prompt,
        cwd,
        output_path,
        DEFAULT_PROFILE.policy.output_schema_path,
        sandbox,
        model=model,
    )
    if runner is None and job.get("_runtime"):
        completed = _run_command_with_runtime(command, cwd, timeout_seconds, job)
    else:
        active_runner = runner or _run_command
        completed = active_runner(command, cwd, timeout_seconds)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError((stderr or stdout or f"{provider.name} failed with code {completed.returncode}").strip())

    structured = _validate_codex_result(parse_provider_result(provider, stdout, output_path))
    if runner is None:
        runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
        job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else None
        queue_dir = job_path.parent if job_path else default_tauri_queue_dir()
        record_provider_verification(queue_dir, provider)

    changed_files = structured.get("changedFiles") if isinstance(structured.get("changedFiles"), list) else []
    artifacts: list[dict[str, Any]] = []
    rejected_artifacts: list[str] = []
    for raw_path in changed_files:
        candidate = Path(str(raw_path)).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if not _path_in_roots(candidate, allowed_roots):
            rejected_artifacts.append(str(candidate))
            continue
        artifacts.append({"kind": candidate.suffix.lstrip(".") or "file", "path": str(candidate)})
    artifacts.append({"kind": "agent_output", "path": str(output_path)})
    if engineering_plan_path is not None:
        artifacts.append({"kind": "engineering_plan", "path": str(engineering_plan_path)})
    risks = structured.get("risks") if isinstance(structured.get("risks"), list) else []
    if rejected_artifacts:
        risks = [*risks, "已拒绝工作区、输出目录或输入文件目录之外的交付路径: " + "；".join(rejected_artifacts)]

    return {
        "mode": "codex" if legacy_codex else "agent",
        "provider": provider.to_dict(),
        "message": str(structured.get("summary") or f"{provider.name} 已完成执行，结果已回写到本地输出文件。"),
        "command": command[:2] + ["..."],
        "cwd": str(cwd),
        "sandbox": sandbox,
        "artifactBaseline": artifact_baseline,
        "outputPath": str(output_path),
        "outputs": artifacts,
        "artifacts": artifacts,
        "verification": structured.get("verification") if isinstance(structured.get("verification"), list) else [],
        "risks": risks,
        "nextSteps": structured.get("nextSteps") if isinstance(structured.get("nextSteps"), list) else [],
        "knowledgeContext": prompt_job["_knowledgeContext"],
        "engineeringPlan": prompt_job.get("_engineeringPlan"),
        "engineeringPlanPath": str(engineering_plan_path) if engineering_plan_path else None,
        "stdoutTail": stdout[-4000:],
        "stderrTail": stderr[-4000:],
    }


def run_codex_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    allow_full_access: bool = False,
) -> dict[str, Any]:
    """@brief 兼容旧调用名称，实际走统一 Agent Provider Runtime。"""
    return run_agent_job(job, runner=runner, timeout_seconds=timeout_seconds, allow_full_access=allow_full_access)


def _run_command(command: Sequence[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    """@brief 运行外部命令，便于测试中替换。"""
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run_command_with_runtime(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    job: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    """@brief 运行 Agent 进程并维护 heartbeat、lease 与取消语义。"""
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    job_path = Path(str(runtime.get("jobPath")))
    runner_id = str(runtime.get("runnerId") or job.get("runnerId") or worker_id())
    lease_seconds = int(runtime.get("leaseSeconds") or DEFAULT_LEASE_SECONDS)
    heartbeat_interval = max(1.0, min(10.0, lease_seconds / 3))
    started_at = time.monotonic()
    next_heartbeat = 0.0
    stdout_path, stderr_path = log_paths_for(job_path.parent, job.get("id"))
    event_prefix = "agent" if job.get("executor") == "agent" else "codex"
    process_label = "Codex" if event_prefix == "codex" else "Agent"

    append_event(job_path.parent, job, f"{event_prefix}.started", f"{process_label} 进程已启动", {"cwd": str(cwd), "stdout": str(stdout_path), "stderr": str(stderr_path)})
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )

        while process.poll() is None:
            now = time.monotonic()
            if now - started_at > timeout_seconds:
                terminate_process(process)
                append_event(job_path.parent, job, f"{event_prefix}.timeout", f"{process_label} 执行超时，已请求终止")
                raise TimeoutError(f"{process_label} 执行超时: {timeout_seconds}s")
            if now >= next_heartbeat:
                try:
                    refresh_job_heartbeat(job_path, runner_id, lease_seconds, f"{process_label} 正在执行，worker 已续租。")
                except JobCancelled:
                    terminate_process(process)
                    append_event(job_path.parent, job, f"{event_prefix}.cancelled", f"收到取消请求，已终止 {process_label} 进程")
                    raise
                next_heartbeat = now + heartbeat_interval
            time.sleep(0.25)

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
    completed = subprocess.CompletedProcess(list(command), process.returncode or 0, stdout=stdout, stderr=stderr)
    append_event(
        job_path.parent,
        job,
        f"{event_prefix}.completed",
        f"{process_label} 进程已退出",
        {"returnCode": completed.returncode},
    )
    return completed


def terminate_process(process: subprocess.Popen[str]) -> None:
    """@brief 尽力终止子进程并回收。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            text=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


MOCK_HANDLERS: Mapping[str, JobHandler] = {
    "create_shell": mock_create_shell,
    "import_model": mock_import_model,
    "delivery_package": mock_delivery_package,
}
DEFAULT_HANDLERS: Mapping[str, JobHandler] = {}


def process_job(
    path: Path,
    handlers: Mapping[str, JobHandler] | None = None,
    runner_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """@brief 执行一个 queued 任务，终态任务会被跳过。"""
    path = Path(path)
    job = read_job(path)
    if job.get("status") != "queued":
        return None

    active_handlers = handlers or DEFAULT_HANDLERS
    try:
        job_id = job.get("id")
        kind = job.get("kind")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("任务缺少 id")
        if kind not in KNOWN_JOB_KINDS:
            raise ValueError(f"未知任务类型: {kind}")
        if job.get("executor") in {"codex", "agent"}:
            approval_reasons = require_policy_approval(job)
            if approval_reasons:
                return mark_approval_required(path, job, approval_reasons)
            executor_kind = "codex_task" if job.get("executor") == "codex" else "agent_task"
            if executor_kind not in active_handlers:
                flag = "--enable-codex" if executor_kind == "codex_task" else "--enable-agent"
                raise ValueError(f"Agent 执行器未启用，请给 worker 添加 {flag}")
            kind = executor_kind

        if kind not in active_handlers:
            raise ValueError(f"任务类型未配置 handler: {kind}")

        mark_job_claimed(job, runner_id or worker_id(), lease_seconds)
        set_job_state(job, "running", 12, "worker 已接单，正在准备本地 CAD 执行环境。")
        write_job(path, job)
        append_event(path.parent, job, "run.claimed", "任务已被 worker 领取")
        append_event(path.parent, job, "step.started", "任务执行开始")

        job["_runtime"] = {"jobPath": str(path), "runnerId": job.get("runnerId"), "leaseSeconds": lease_seconds}
        result = active_handlers[kind](job)
        if is_cancel_requested(path):
            raise JobCancelled("任务已请求取消")
        job.pop("_runtime", None)
        job["result"] = result
        ledger = write_artifact_ledger(path.parent, job, result)
        job["artifactLedgerPath"] = ledger["ledgerPath"]
        job["artifacts"] = ledger["artifacts"]
        append_event(path.parent, job, "artifact.ledger_written", "交付物账本已写入", {"ledgerPath": ledger["ledgerPath"]})
        review = write_reviewer_gate(path.parent, ledger)
        if is_cancel_requested(path):
            raise JobCancelled("任务已请求取消")
        job["reviewGate"] = review
        job["reviewGatePath"] = review["reviewPath"]
        append_event(path.parent, job, "review.gate_completed", "Reviewer Gate 已完成", {"status": review["status"], "reviewPath": review["reviewPath"]})
        if review["status"] == "fail":
            message = "交付文件检查未通过，任务不可交付。请查看复核记录并修正。"
            job["error"] = message
            set_job_state(job, "failed", 100, message)
            append_event(path.parent, job, "run.failed", message)
        else:
            message = str(result.get("message", "任务完成"))
            if review["status"] == "warning":
                message = f"{message} 文件级检查存在警告，仍需 CAD 原生或人工复核。"
            status = "review_required" if review["status"] == "warning" else "passed"
            set_job_state(job, status, 100, message)
            append_event(path.parent, job, "run.review_required" if status == "review_required" else "run.passed", message)
    except JobCancelled as error:
        job.pop("_runtime", None)
        job["cancelRequested"] = True
        set_job_state(job, "cancelled", int(job.get("progress") or 0), str(error))
        append_event(path.parent, job, "run.cancelled", str(error))
    except Exception as error:  # noqa: BLE001 - worker 必须把单任务错误写回队列，不能让队列静默中断。
        job.pop("_runtime", None)
        job["error"] = str(error)
        set_job_state(job, "failed", 100, str(error))
        append_event(path.parent, job, "run.failed", str(error))

    write_job(path, job)
    return job


def build_handlers(
    enable_codex: bool = False,
    enable_agent: bool = False,
    codex_full_access: bool = False,
    enable_mock: bool = False,
) -> Mapping[str, JobHandler]:
    """@brief 根据 CLI 参数构建任务分发器。"""
    handlers: dict[str, JobHandler] = dict(DEFAULT_HANDLERS)
    if enable_mock:
        handlers.update(MOCK_HANDLERS)
    if enable_codex:
        handlers["codex_task"] = lambda job: run_agent_job(job, allow_full_access=codex_full_access)
    if enable_agent:
        handlers["agent_task"] = lambda job: run_agent_job(job, allow_full_access=codex_full_access)
    return handlers


def process_queue(
    queue_dir: Path,
    limit: int | None = None,
    handlers: Mapping[str, JobHandler] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[dict[str, Any]]:
    """@brief 扫描队列目录并执行 queued 任务。"""
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    recovered = recover_stale_jobs(queue_dir)
    processed: list[dict[str, Any]] = []
    runner_id = worker_id()
    last_error: str | None = None

    for path in sorted(queue_dir.glob("*.json")):
        if path.name in QUEUE_METADATA_FILES:
            continue
        if limit is not None and len(processed) >= limit:
            break
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") in NON_EXECUTABLE_STATES or job.get("status") != "queued":
            continue
        lock_path = acquire_lock(path, runner_id, lease_seconds)
        if lock_path is None:
            continue
        try:
            result = process_job(path, handlers=handlers, runner_id=runner_id, lease_seconds=lease_seconds)
            if result is not None:
                processed.append(result)
                if result.get("status") == "failed":
                    last_error = str(result.get("error") or result.get("lastMessage") or "任务失败")
        finally:
            release_lock(lock_path)
    write_worker_health(queue_dir, runner_id, processed_count=len(processed), recovered_count=recovered, last_error=last_error)
    return processed


def watch_queue(
    queue_dir: Path,
    interval_seconds: float = 1.0,
    handlers: Mapping[str, JobHandler] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    """@brief 持续监听队列目录，适合后续做成后台进程。"""
    runner_id = worker_id()
    while True:
        processed = process_queue(queue_dir, handlers=handlers, lease_seconds=lease_seconds)
        write_worker_health(queue_dir, runner_id, processed_count=len(processed))
        time.sleep(interval_seconds)


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio 本地自动化队列 worker")
    parser.add_argument("--queue-dir", type=Path, default=default_tauri_queue_dir(), help="队列 JSON 目录")
    parser.add_argument("--watch", action="store_true", help="持续监听队列")
    parser.add_argument("--limit", type=int, default=None, help="单次最多处理任务数")
    parser.add_argument("--interval", type=float, default=1.0, help="监听轮询间隔秒数")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS, help="任务领取 lease 秒数")
    parser.add_argument("--enable-codex", action="store_true", help="允许 worker 调用 codex exec 执行任务")
    parser.add_argument("--enable-agent", action="store_true", help="允许 worker 调用已选择的本机 Agent Provider")
    parser.add_argument("--codex-full-access", action="store_true", help="允许 Codex 使用 danger-full-access 沙箱")
    parser.add_argument("--enable-mock", action="store_true", help="仅开发测试：启用不生成真实 CAD 文件的 mock handler")
    args = parser.parse_args()
    handlers = build_handlers(
        enable_codex=args.enable_codex,
        enable_agent=args.enable_agent,
        codex_full_access=args.codex_full_access,
        enable_mock=args.enable_mock,
    )

    if args.watch:
        watch_queue(args.queue_dir, interval_seconds=args.interval, handlers=handlers, lease_seconds=args.lease_seconds)
        return 0

    processed = process_queue(args.queue_dir, limit=args.limit, handlers=handlers, lease_seconds=args.lease_seconds)
    print(f"processed {len(processed)} job(s) from {args.queue_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
