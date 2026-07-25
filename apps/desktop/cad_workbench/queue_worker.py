"""@brief CAD Studio 本地自动化队列 worker 原型。"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .core import now_iso


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]

WORKER_NAME = "cad-workbench-python-worker"
KNOWN_JOB_KINDS = {"create_shell", "import_model", "delivery_package"}
TERMINAL_STATES = {"passed", "failed", "cancelled"}


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


DEFAULT_HANDLERS: Mapping[str, JobHandler] = {
    "create_shell": mock_create_shell,
    "import_model": mock_import_model,
    "delivery_package": mock_delivery_package,
}


def process_job(path: Path, handlers: Mapping[str, JobHandler] | None = None) -> dict[str, Any] | None:
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
        if kind not in active_handlers:
            raise ValueError(f"任务类型未配置 handler: {kind}")

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


def process_queue(queue_dir: Path, limit: int | None = None, handlers: Mapping[str, JobHandler] | None = None) -> list[dict[str, Any]]:
    """@brief 扫描队列目录并执行 queued 任务。"""
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    processed: list[dict[str, Any]] = []

    for path in sorted(queue_dir.glob("*.json")):
        if limit is not None and len(processed) >= limit:
            break
        job = read_job(path)
        if job.get("status") in TERMINAL_STATES or job.get("status") != "queued":
            continue
        result = process_job(path, handlers=handlers)
        if result is not None:
            processed.append(result)
    return processed


def watch_queue(queue_dir: Path, interval_seconds: float = 1.0) -> None:
    """@brief 持续监听队列目录，适合后续做成后台进程。"""
    while True:
        process_queue(queue_dir)
        time.sleep(interval_seconds)


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio 本地自动化队列 worker")
    parser.add_argument("--queue-dir", type=Path, default=default_tauri_queue_dir(), help="队列 JSON 目录")
    parser.add_argument("--watch", action="store_true", help="持续监听队列")
    parser.add_argument("--limit", type=int, default=None, help="单次最多处理任务数")
    parser.add_argument("--interval", type=float, default=1.0, help="监听轮询间隔秒数")
    args = parser.parse_args()

    if args.watch:
        watch_queue(args.queue_dir, interval_seconds=args.interval)
        return 0

    processed = process_queue(args.queue_dir, limit=args.limit)
    print(f"processed {len(processed)} job(s) from {args.queue_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
