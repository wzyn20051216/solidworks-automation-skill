"""@brief CAD Studio 本地自动化队列 worker 原型。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .core import now_iso


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]

WORKER_NAME = "cad-workbench-python-worker"
KNOWN_JOB_KINDS = {"create_shell", "import_model", "delivery_package", "codex_task"}
TERMINAL_STATES = {"passed", "failed", "cancelled"}
DEFAULT_CODEX_TIMEOUT_SECONDS = 1800


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


def build_codex_prompt(job: dict[str, Any]) -> str:
    """@brief 把图形化配置任务转换为 Codex 可执行提示词。"""
    objective = str(job.get("objective") or job.get("detail") or "执行 CAD 自动化任务")
    target = str(job.get("target") or "solidworks-automation skill")
    output = str(job.get("expectedOutput") or "完成实现、验证并总结结果")
    project_path = job.get("projectPath") or "未指定"
    strict_rules = job.get("strictRules") if isinstance(job.get("strictRules"), list) else []

    rule_lines = "\n".join(f"- {rule}" for rule in strict_rules)
    if not rule_lines:
        rule_lines = "\n".join(
            [
                "- 必须遵守 3D 打印真实开孔要求，不能只画外观线。",
                "- 必须遵守 GB/T 风格图纸规范，尺寸链、孔位和技术要求要完整。",
                "- 修改后必须运行可用验证，并提交中文 commit。",
            ]
        )

    return "\n".join(
        [
            "你是 Codex，请在本地仓库中执行 CAD 自动化任务。",
            "",
            "【任务目标】",
            objective,
            "",
            "【目标对象】",
            target,
            "",
            "【项目/模型路径】",
            str(project_path),
            "",
            "【期望输出】",
            output,
            "",
            "【强制规则】",
            rule_lines,
            "",
            "【执行要求】",
            "- 优先使用 solidworks-automation skill 及其子技能。",
            "- 如果需要生成或修改图纸，必须按中国机械制图常用规范复核。",
            "- 如果任务涉及上传 GitHub，完成验证后推送。",
            "- 结束时用中文说明改了什么、验证了什么、输出在哪里。",
        ]
    )


def run_codex_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """@brief 调用 codex exec 执行由 UI 生成的任务。"""
    cwd = Path(str(job.get("cwd") or Path.cwd())).expanduser()
    prompt = str(job.get("prompt") or build_codex_prompt(job))
    output_path = Path(str(job.get("codexOutputPath") or cwd / "ai_team" / f"{job['id']}_codex_result.md"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "codex",
        "exec",
        "-C",
        str(cwd),
        "-a",
        "never",
        "-s",
        "danger-full-access",
        "-o",
        str(output_path),
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
        if job.get("executor") == "codex":
            if "codex_task" not in active_handlers:
                raise ValueError("Codex 执行器未启用，请给 worker 添加 --enable-codex")
            kind = "codex_task"

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


def build_handlers(enable_codex: bool = False) -> Mapping[str, JobHandler]:
    """@brief 根据 CLI 参数构建任务分发器。"""
    handlers: dict[str, JobHandler] = dict(DEFAULT_HANDLERS)
    if enable_codex:
        handlers["codex_task"] = run_codex_job
    return handlers


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


def watch_queue(queue_dir: Path, interval_seconds: float = 1.0, handlers: Mapping[str, JobHandler] | None = None) -> None:
    """@brief 持续监听队列目录，适合后续做成后台进程。"""
    while True:
        process_queue(queue_dir, handlers=handlers)
        time.sleep(interval_seconds)


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio 本地自动化队列 worker")
    parser.add_argument("--queue-dir", type=Path, default=default_tauri_queue_dir(), help="队列 JSON 目录")
    parser.add_argument("--watch", action="store_true", help="持续监听队列")
    parser.add_argument("--limit", type=int, default=None, help="单次最多处理任务数")
    parser.add_argument("--interval", type=float, default=1.0, help="监听轮询间隔秒数")
    parser.add_argument("--enable-codex", action="store_true", help="允许 worker 调用 codex exec 执行任务")
    args = parser.parse_args()
    handlers = build_handlers(enable_codex=args.enable_codex)

    if args.watch:
        watch_queue(args.queue_dir, interval_seconds=args.interval, handlers=handlers)
        return 0

    processed = process_queue(args.queue_dir, limit=args.limit, handlers=handlers)
    print(f"processed {len(processed)} job(s) from {args.queue_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
