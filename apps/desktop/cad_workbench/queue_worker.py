"""@brief CAD Studio 本地自动化队列 worker 原型。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .agent_contracts import DEFAULT_PROFILE, codex_output_path, compile_codex_prompt, validate_codex_job
from .core import CN_TZ, now_iso


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]

WORKER_NAME = "cad-workbench-python-worker"
KNOWN_JOB_KINDS = {"create_shell", "import_model", "delivery_package", "codex_task"}
TERMINAL_STATES = {"passed", "failed", "cancelled"}
DEFAULT_CODEX_TIMEOUT_SECONDS = 1800
DEFAULT_LEASE_SECONDS = 900


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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
    """@brief 使用 O_EXCL 原子创建领取锁。"""
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
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(str(lock_path), flags)
    except FileExistsError:
        try:
            lock = read_job(lock_path)
            if is_expired(lock.get("leaseUntil")):
                lock_path.unlink(missing_ok=True)
                return acquire_lock(path, runner_id, lease_seconds)
        except Exception:
            lock_path.unlink(missing_ok=True)
            return acquire_lock(path, runner_id, lease_seconds)
        return None

    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return lock_path


def release_lock(lock_path: Path | None) -> None:
    """@brief 释放领取锁。"""
    if lock_path is not None:
        Path(lock_path).unlink(missing_ok=True)


def mark_job_claimed(job: dict[str, Any], runner_id: str, lease_seconds: int) -> None:
    """@brief 写入任务领取信息。"""
    job["runnerId"] = runner_id
    job["workerPid"] = os.getpid()
    job["heartbeatAt"] = now_iso()
    job["leaseUntil"] = lease_until(lease_seconds)
    job["attempt"] = int(job.get("attempt") or 0) + 1


def recover_stale_jobs(queue_dir: Path) -> int:
    """@brief 将 lease 过期的 running 任务恢复为 queued。"""
    recovered = 0
    for path in sorted(Path(queue_dir).glob("*.json")):
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") != "running" or not is_expired(job.get("leaseUntil")):
            continue
        set_job_state(job, "queued", int(job.get("progress") or 0), "worker lease 已过期，任务已恢复排队。")
        job.pop("runnerId", None)
        job.pop("workerPid", None)
        write_job(path, job)
        release_lock(lock_path_for(path))
        recovered += 1
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


def run_codex_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    full_access: bool = False,
) -> dict[str, Any]:
    """@brief 调用 codex exec 执行由 UI 生成的任务。"""
    cwd = validate_codex_job(job)
    prompt = str(job.get("prompt") or build_codex_prompt(job))
    output_path = codex_output_path(job, cwd)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sandbox = "danger-full-access" if full_access else "workspace-write"

    command = [
        "codex",
        "exec",
        "-C",
        str(cwd),
        "-a",
        "never",
        "-s",
        sandbox,
        "-o",
        str(output_path),
        "--output-schema",
        str(DEFAULT_PROFILE.policy.output_schema_path),
        prompt,
    ]
    active_runner = runner or _run_command
    completed = active_runner(command, cwd, timeout_seconds)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError((stderr or stdout or f"codex exec failed with code {completed.returncode}").strip())

    return {
        "mode": "codex",
        "message": "Codex 已完成执行，结果已回写到本地输出文件。",
        "command": command[:2] + ["..."],
        "cwd": str(cwd),
        "sandbox": sandbox,
        "outputPath": str(output_path),
        "stdoutTail": stdout[-4000:],
        "stderrTail": stderr[-4000:],
    }


def _run_command(command: Sequence[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    """@brief 运行外部命令，便于测试中替换。"""
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


DEFAULT_HANDLERS: Mapping[str, JobHandler] = {
    "create_shell": mock_create_shell,
    "import_model": mock_import_model,
    "delivery_package": mock_delivery_package,
}


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
        if job.get("executor") == "codex":
            if "codex_task" not in active_handlers:
                raise ValueError("Codex 执行器未启用，请给 worker 添加 --enable-codex")
            kind = "codex_task"

        if kind not in active_handlers:
            raise ValueError(f"任务类型未配置 handler: {kind}")

        mark_job_claimed(job, runner_id or worker_id(), lease_seconds)
        set_job_state(job, "running", 12, "worker 已接单，正在准备本地 CAD 执行环境。")
        write_job(path, job)

        result = active_handlers[kind](job)
        job["result"] = result
        set_job_state(job, "passed", 100, str(result.get("message", "任务完成")))
    except Exception as error:  # noqa: BLE001 - worker 必须把单任务错误写回队列，不能让队列静默中断。
        job["error"] = str(error)
        set_job_state(job, "failed", 100, str(error))

    write_job(path, job)
    return job


def build_handlers(enable_codex: bool = False, codex_full_access: bool = False) -> Mapping[str, JobHandler]:
    """@brief 根据 CLI 参数构建任务分发器。"""
    handlers: dict[str, JobHandler] = dict(DEFAULT_HANDLERS)
    if enable_codex:
        handlers["codex_task"] = lambda job: run_codex_job(job, full_access=codex_full_access)
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
    recover_stale_jobs(queue_dir)
    processed: list[dict[str, Any]] = []
    runner_id = worker_id()

    for path in sorted(queue_dir.glob("*.json")):
        if limit is not None and len(processed) >= limit:
            break
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") in TERMINAL_STATES or job.get("status") != "queued":
            continue
        lock_path = acquire_lock(path, runner_id, lease_seconds)
        if lock_path is None:
            continue
        try:
            result = process_job(path, handlers=handlers, runner_id=runner_id, lease_seconds=lease_seconds)
            if result is not None:
                processed.append(result)
        finally:
            release_lock(lock_path)
    return processed


def watch_queue(
    queue_dir: Path,
    interval_seconds: float = 1.0,
    handlers: Mapping[str, JobHandler] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    """@brief 持续监听队列目录，适合后续做成后台进程。"""
    while True:
        process_queue(queue_dir, handlers=handlers, lease_seconds=lease_seconds)
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
    parser.add_argument("--codex-full-access", action="store_true", help="允许 Codex 使用 danger-full-access 沙箱")
    args = parser.parse_args()
    handlers = build_handlers(enable_codex=args.enable_codex, codex_full_access=args.codex_full_access)

    if args.watch:
        watch_queue(args.queue_dir, interval_seconds=args.interval, handlers=handlers, lease_seconds=args.lease_seconds)
        return 0

    processed = process_queue(args.queue_dir, limit=args.limit, handlers=handlers, lease_seconds=args.lease_seconds)
    print(f"processed {len(processed)} job(s) from {args.queue_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
