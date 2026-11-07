"""结构化 SolidWorks 视觉执行事件写入器。"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


MAX_EVENT_BYTES = 64 * 1024
PHASE_PROGRESS = {
    "planning": 5,
    "sketch": 20,
    "feature": 55,
    "assembly": 70,
    "drawing": 85,
    "review": 95,
    "delivery": 100,
}
_TOKEN = re.compile(r"[^a-z0-9_-]+")
_LOCK = threading.Lock()


@dataclass
class VisualStepHandle:
    """Caller-visible step metadata collected before the completion event."""

    stats: dict[str, float] = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_token(value: Any, fallback: str = "step") -> str:
    token = _TOKEN.sub("-", str(value or "").strip().lower()).strip("-_")
    return (token or fallback)[:96]


def _write_json_line(path: Path, event: dict[str, Any]) -> None:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_EVENT_BYTES:
        raise ValueError("视觉事件超过 64 KiB 限制")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, payload + b"\n")
        finally:
            os.close(descriptor)


def _initial_sequence(path: Path) -> int:
    """@brief 从现有事件流恢复步骤序号，避免不同高层调用互相覆盖。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        try:
            event = json.loads(line)
            sequence = event.get("data", {}).get("sequence")
            if isinstance(sequence, int):
                return max(0, sequence)
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return 0


class VisualTrace:
    """把一次任务的视觉事件追加到现有 Queue JSONL。"""

    def __init__(self, event_file: Path, job_id: str, frame_dir: Path | None = None):
        self.event_file = Path(event_file)
        self.job_id = str(job_id)
        self.frame_dir = Path(frame_dir) if frame_dir else None
        self.sequence = _initial_sequence(self.event_file)

    @classmethod
    def from_environment(cls) -> "VisualTrace | None":
        event_file = os.environ.get("CADSTUDIO_VISUAL_EVENT_FILE", "").strip()
        job_id = os.environ.get("CADSTUDIO_JOB_ID", "").strip()
        if not event_file or not job_id:
            return None
        frame_dir = os.environ.get("CADSTUDIO_VISUAL_FRAME_DIR", "").strip()
        return cls(Path(event_file), job_id, Path(frame_dir) if frame_dir else None)

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "type": event_type,
            "jobId": self.job_id,
            "at": _now_iso(),
            "message": str(message),
            "data": data or {},
        }
        if progress is not None:
            event["progress"] = max(0, min(100, int(progress)))
        _write_json_line(self.event_file, event)

    @contextlib.contextmanager
    def step(
        self,
        step_id: str,
        phase: str,
        title: str,
        message: str = "",
        *,
        snapshot: bool = True,
    ) -> Iterator[VisualStepHandle]:
        if phase not in PHASE_PROGRESS:
            raise ValueError(f"未知视觉阶段: {phase}")
        self.sequence += 1
        normalized_step = _safe_token(step_id)
        if not normalized_step.startswith(f"{phase}-"):
            normalized_step = f"{phase}-{normalized_step}"
        base = {
            "stepId": normalized_step,
            "sequence": self.sequence,
            "phase": phase,
            "title": str(title),
        }
        handle = VisualStepHandle()
        self.emit(
            "visual.step.started",
            message or f"{title}开始",
            progress=max(0, PHASE_PROGRESS[phase] - 5),
            data=base,
        )
        try:
            yield handle
        except Exception as exc:
            self.emit(
                "visual.step.failed",
                message or f"{title}失败",
                progress=max(0, PHASE_PROGRESS[phase] - 5),
                data={**base, "error": str(exc)[:2000]},
            )
            raise
        snapshot_path = None
        snapshot_error = None
        if snapshot and self.frame_dir is not None:
            try:
                try:
                    from .sw_window_capture import capture_solidworks_window
                except ImportError:
                    from sw_window_capture import capture_solidworks_window

                captured = capture_solidworks_window(
                    self.frame_dir,
                    self.sequence,
                    phase,
                    normalized_step,
                )
                if captured is not None:
                    event_dir = self.event_file.parent
                    queue_root = (
                        event_dir.parent
                        if event_dir.name.casefold() == "events"
                        else event_dir
                    )
                    try:
                        snapshot_path = str(captured.resolve().relative_to(queue_root.resolve()))
                    except ValueError:
                        snapshot_path = str(captured.resolve())
            except Exception as exc:
                snapshot_error = str(exc)[:1000]
        completed = {**base}
        if handle.stats:
            completed["stats"] = dict(handle.stats)
        if snapshot_path:
            completed["snapshotPath"] = snapshot_path
        if snapshot_error:
            completed["snapshotError"] = snapshot_error
        self.emit(
            "visual.step.completed",
            message or f"{title}完成",
            progress=PHASE_PROGRESS[phase],
            data=completed,
        )


def visual_step(
    step_id: str,
    phase: str,
    title: str,
    message: str = "",
    *,
    snapshot: bool = True,
):
    """在存在视觉环境时创建一个步骤上下文。"""
    trace = VisualTrace.from_environment()
    if trace is None:
        return contextlib.nullcontext()
    return trace.step(step_id, phase, title, message, snapshot=snapshot)


def traced_step(
    step_id: str,
    phase: str,
    title: str,
    message: str = "",
    *,
    snapshot: bool = True,
):
    """为普通函数自动添加视觉步骤。"""

    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with visual_step(step_id, phase, title, message, snapshot=snapshot):
                return function(*args, **kwargs)

        return wrapper

    return decorator
