# SolidWorks 实时可视化执行流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 CAD Studio 中加入结构化执行事件、SolidWorks 操作快照、置顶机械鱼 HUD 和可视化交付卡，完整还原“对话任务驱动 SolidWorks 逐步建模”的演示体验。

**Architecture:** 复用现有 Queue JSONL 事件流，新增 Python 视觉追踪器与窗口捕获器；Queue Worker 为 Codex 子进程注入当前任务的事件文件和快照目录；Tauri 新增 `live-hud` 透明窗口和有界快照读取命令；React 主窗口与 HUD 共享同一份事件状态。

**Tech Stack:** Python 3.12、pywin32、Pillow、pytest、Rust/Tauri 2、React 19、TypeScript、Vitest、Playwright、Motion、Phosphor Icons。

## Global Constraints

- 原生 SolidWorks 操作只使用现有 COM 封装，保持全局串行执行。
- 视觉事件必须来自真实执行，不得用随机进度或模拟动画补足。
- 任务状态为 `pilot`、`review_required` 或 `blocked` 时不得展示为正式完成。
- 单条视觉事件最大 64 KiB。
- 单张快照只允许 PNG/JPEG，最大 8 MiB。
- 单任务快照上限 80 张，并保留每个阶段首尾帧及最近 20 帧。
- `live-hud` 只读取当前应用数据目录下 `queue/visual/**` 的文件。
- 快照路径必须经过规范化和前缀校验，拒绝目录穿越。
- 不捕获其他桌面窗口、系统敏感界面或用户凭据。
- HUD 默认尺寸 420x300，不遮挡 SolidWorks 特征树和绘图区中心。
- 所有 UI 文本使用简体中文，组件名、事件名和代码标识保持英文。

## File Structure

### Python 执行层

- Create: `scripts/sw_visual_trace.py`
  - 事件结构、环境变量解析、步骤上下文、自动截图入口。
- Create: `scripts/sw_window_capture.py`
  - SolidWorks 主窗口发现、PIL 截图、快照命名和保留策略。
- Modify: `apps/desktop/cad_workbench/queue_worker.py`
  - 为 Codex 子进程注入视觉环境变量，写会话启动事件。
- Modify: `scripts/sw_session.py`
  - 新建、打开、保存、导出自动埋点。
- Modify: `scripts/sw_part.py`
  - 草图、拉伸、旋转、切除、圆角、倒角、孔自动埋点。
- Create: `tests/test_sw_visual_trace.py`
- Create: `tests/test_sw_window_capture.py`
- Create: `tests/test_sw_visual_integration.py`
- Create: `tests/test_live_visual_queue.py`

### Tauri 层

- Modify: `apps/workbench-ui/src-tauri/tauri.conf.json`
- Modify: `apps/workbench-ui/src-tauri/capabilities/default.json`
- Modify: `apps/workbench-ui/src-tauri/src/lib.rs`
  - 新增 `read_live_visual_frame`、`set_live_hud_visible` 命令。
- Modify: `apps/workbench-ui/src-tauri/src/lib.rs` tests
  - 快照文件名、路径和大小限制测试。

### React 层

- Create: `apps/workbench-ui/src/live/visualTypes.ts`
- Create: `apps/workbench-ui/src/live/visualState.ts`
- Create: `apps/workbench-ui/src/live/visualState.test.ts`
- Create: `apps/workbench-ui/src/live/LiveHud.tsx`
- Create: `apps/workbench-ui/src/live/Mascot.tsx`
- Create: `apps/workbench-ui/src/live/live-hud.css`
- Create: `apps/workbench-ui/src/live/LiveExecutionStrip.tsx`
- Create: `apps/workbench-ui/src/live/LiveDeliveryCard.tsx`
- Create: `apps/workbench-ui/src/live/liveFixtures.ts`
- Create: `apps/workbench-ui/src/assets/live-mascot/idle.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/working.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/checking.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/complete.webp`
- Modify: `apps/workbench-ui/src/main.tsx`
- Modify: `apps/workbench-ui/src/App.tsx`
- Modify: `apps/workbench-ui/src/types.ts`
- Modify: `apps/workbench-ui/src/styles.css`

### End-to-End

- Create: `ai_team/live-visual-e2e.cjs`
- Create: `tests/live_visual_solidworks_smoke.py`
- Modify: `docs/CAD_STUDIO_USER_MANUAL.md`
- Modify: `SKILL.md`

---

### Task 1: 视觉事件写入器

**Files:**
- Create: `scripts/sw_visual_trace.py`
- Create: `tests/test_sw_visual_trace.py`

**Interfaces:**
- Consumes: 环境变量 `CADSTUDIO_JOB_ID`、`CADSTUDIO_VISUAL_EVENT_FILE`、`CADSTUDIO_VISUAL_FRAME_DIR`
- Produces: `VisualTrace.from_environment() -> VisualTrace | None`
- Produces: `VisualTrace.step(step_id, phase, title, message="")`
- Produces: `visual_step(step_id, phase, title, message="", snapshot=True)`
- Produces: `traced_step(step_id, phase, title, message="")`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sw_visual_trace.py` with:

```python
import json
from pathlib import Path

import pytest

from scripts.sw_visual_trace import VisualTrace, traced_step


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_step_writes_started_and_completed(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-1.jsonl"
    frames = tmp_path / "frames"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-1")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    monkeypatch.setenv("CADSTUDIO_VISUAL_FRAME_DIR", str(frames))

    trace = VisualTrace.from_environment()
    assert trace is not None
    with trace.step("main-sketch", "sketch", "绘制主体草图", message="正在创建中心线"):
        pass

    events = read_events(event_file)
    assert [item["type"] for item in events] == [
        "visual.step.started",
        "visual.step.completed",
    ]
    assert events[0]["data"]["stepId"] == "sketch-main-sketch"
    assert events[0]["data"]["phase"] == "sketch"
    assert events[1]["progress"] == 20


def test_step_failure_writes_failed_event(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-1.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-1")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))

    trace = VisualTrace.from_environment()
    assert trace is not None
    with pytest.raises(RuntimeError, match="boom"):
        with trace.step("main-feature", "feature", "生成主体"):
            raise RuntimeError("boom")

    events = read_events(event_file)
    assert events[-1]["type"] == "visual.step.failed"
    assert events[-1]["data"]["error"] == "boom"


def test_decorator_emits_only_when_environment_is_present(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-2.jsonl"
    monkeypatch.delenv("CADSTUDIO_JOB_ID", raising=False)
    monkeypatch.delenv("CADSTUDIO_VISUAL_EVENT_FILE", raising=False)

    @traced_step("save", "delivery", "保存模型")
    def save_model():
        return "saved"

    assert save_model() == "saved"
    assert not event_file.exists()

    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-2")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    assert save_model() == "saved"
    assert [item["type"] for item in read_events(event_file)] == [
        "visual.step.started",
        "visual.step.completed",
    ]


def test_oversized_payload_is_rejected(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-3.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-3")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    trace = VisualTrace.from_environment()
    assert trace is not None

    with pytest.raises(ValueError, match="64 KiB"):
        trace.emit("visual.plan.ready", "x" * 70000)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m pytest tests\test_sw_visual_trace.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.sw_visual_trace'`.

- [ ] **Step 3: Implement the visual trace writer**

Create `scripts/sw_visual_trace.py`:

```python
"""结构化 SolidWorks 视觉执行事件写入器。"""
from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import threading
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


class VisualTrace:
    """把一次任务的视觉事件追加到现有 Queue JSONL。"""

    def __init__(self, event_file: Path, job_id: str, frame_dir: Path | None = None):
        self.event_file = Path(event_file)
        self.job_id = str(job_id)
        self.frame_dir = Path(frame_dir) if frame_dir else None
        self.sequence = 0

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
    ) -> Iterator[None]:
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
        self.emit(
            "visual.step.started",
            message or f"{title}开始",
            progress=max(0, PHASE_PROGRESS[phase] - 5),
            data=base,
        )
        try:
            yield
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
                    queue_root = self.event_file.parent.parent
                    try:
                        snapshot_path = str(captured.resolve().relative_to(queue_root.resolve()))
                    except ValueError:
                        snapshot_path = str(captured.resolve())
            except Exception as exc:
                snapshot_error = str(exc)[:1000]
        completed = {**base}
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```powershell
python -m pytest tests\test_sw_visual_trace.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/sw_visual_trace.py tests/test_sw_visual_trace.py
git commit -m "feat: add structured visual execution trace"
```

---

### Task 2: SolidWorks 窗口快照与保留策略

**Files:**
- Create: `scripts/sw_window_capture.py`
- Create: `tests/test_sw_window_capture.py`

**Interfaces:**
- Consumes: `capture_solidworks_window(frame_dir: Path, sequence: int, phase: str, step_id: str) -> Path | None`
- Produces: `snapshot_filename(sequence, phase, step_id) -> str`
- Produces: `prune_snapshots(frame_dir: Path, max_frames=80) -> list[Path]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sw_window_capture.py` with:

```python
from pathlib import Path

from scripts import sw_window_capture


def test_snapshot_filename_contains_sequence_phase_and_step():
    assert sw_window_capture.snapshot_filename(7, "feature", "main-shaft") == (
        "step-007-feature-main-shaft.png"
    )


def test_prune_keeps_first_and_last_per_phase(tmp_path):
    for index in range(1, 101):
        phase = "sketch" if index <= 50 else "feature"
        path = tmp_path / f"step-{index:03d}-{phase}-step-{index}.png"
        path.write_bytes(b"png")

    kept = sw_window_capture.prune_snapshots(tmp_path, max_frames=30)
    names = {path.name for path in kept}

    assert "step-001-sketch-step-1.png" in names
    assert "step-050-sketch-step-50.png" in names
    assert "step-051-feature-step-51.png" in names
    assert "step-100-feature-step-100.png" in names
    assert len(kept) <= 30


def test_capture_returns_none_when_no_solidworks_window(monkeypatch, tmp_path):
    monkeypatch.setattr(sw_window_capture, "_solidworks_window_rect", lambda: None)
    assert sw_window_capture.capture_solidworks_window(
        tmp_path, 1, "planning", "planning-open"
    ) is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m pytest tests\test_sw_window_capture.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.sw_window_capture'`.

- [ ] **Step 3: Implement capture and retention**

Create `scripts/sw_window_capture.py`:

```python
"""只捕获 SolidWorks 主窗口的可视化快照。"""
from __future__ import annotations

import os
import re
from pathlib import Path


_SNAPSHOT = re.compile(r"^step-(\d{3,6})-([a-z]+)-(.+)\.(png|jpe?g)$")


def snapshot_filename(sequence: int, phase: str, step_id: str) -> str:
    return f"step-{max(1, int(sequence)):03d}-{phase}-{step_id}.png"


def _solidworks_window_rect():
    if os.name != "nt":
        return None
    try:
        import win32gui
        from sw_process import solidworks_processes

        processes = solidworks_processes() or {}
        pids = {int(pid) for pid in processes}
        if not pids:
            return None
        found = None

        def visit(hwnd, _):
            nonlocal found
            if found or not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32gui.GetWindowThreadProcessId(hwnd)
            if pid not in pids:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left > 640 and bottom - top > 360:
                found = (left, top, right, bottom)

        win32gui.EnumWindows(visit, None)
        return found
    except Exception:
        return None


def capture_solidworks_window(
    frame_dir: Path,
    sequence: int,
    phase: str,
    step_id: str,
) -> Path | None:
    rect = _solidworks_window_rect()
    if rect is None:
        return None
    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=rect, all_screens=True)
    target_dir = Path(frame_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / snapshot_filename(sequence, phase, step_id)
    image.save(target, "PNG", optimize=True)
    if target.stat().st_size > 8 * 1024 * 1024:
        target.unlink(missing_ok=True)
        raise ValueError("SolidWorks 快照超过 8 MiB")
    prune_snapshots(target_dir)
    return target


def prune_snapshots(frame_dir: Path, max_frames: int = 80) -> list[Path]:
    files = sorted(Path(frame_dir).glob("step-*.png"))
    if len(files) <= max_frames:
        return files
    parsed = []
    for path in files:
        match = _SNAPSHOT.match(path.name)
        if match:
            parsed.append((int(match.group(1)), match.group(2), path))
    protected = set()
    for phase in {item[1] for item in parsed}:
        phase_items = [item for item in parsed if item[1] == phase]
        protected.add(phase_items[0][2])
        protected.add(phase_items[-1][2])
    recent = [path for _, _, path in sorted(parsed, reverse=True)[:20]]
    keep = protected | set(recent)
    for _, _, path in sorted(parsed, reverse=True):
        if len(keep) >= max_frames:
            break
        keep.add(path)
    for path in files:
        if path not in keep:
            path.unlink(missing_ok=True)
    return sorted(keep)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```powershell
python -m pytest tests\test_sw_window_capture.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/sw_window_capture.py tests/test_sw_window_capture.py
git commit -m "feat: capture SolidWorks visual snapshots"
```

---

### Task 3: Worker 注入与 SolidWorks 自动埋点

**Files:**
- Modify: `apps/desktop/cad_workbench/queue_worker.py`
- Modify: `scripts/sw_session.py`
- Modify: `scripts/sw_part.py`
- Create: `tests/test_live_visual_queue.py`
- Create: `tests/test_sw_visual_integration.py`

**Interfaces:**
- Consumes: `visual_step(step_id, phase, title, message="", snapshot=True)` from Task 1
- Produces: `visual_runtime_env(job: dict, queue_dir: Path) -> dict[str, str]`
- Produces: `visual_frame_dir_for(queue_dir: Path, job_id: Any) -> Path`
- Produces: `SolidWorksSession.new/open/save/export` emits `visual.step.*`
- Produces: `sw_part` core feature functions emit `visual.step.*`

- [ ] **Step 1: Write failing worker environment tests**

Create `tests/test_live_visual_queue.py`:

```python
from pathlib import Path

from apps.desktop.cad_workbench.queue_worker import (
    event_path_for,
    visual_frame_dir_for,
    visual_runtime_env,
)


def test_visual_runtime_env_uses_existing_event_stream(tmp_path):
    job = {
        "id": "job-visual-1",
        "uiConfig": {"visualMode": True},
    }

    env = visual_runtime_env(job, tmp_path)

    assert env["CADSTUDIO_JOB_ID"] == "job-visual-1"
    assert env["CADSTUDIO_VISUAL_MODE"] == "1"
    assert env["CADSTUDIO_VISUAL_EVENT_FILE"] == str(
        event_path_for(tmp_path, "job-visual-1")
    )
    assert env["CADSTUDIO_VISUAL_FRAME_DIR"] == str(
        visual_frame_dir_for(tmp_path, "job-visual-1")
    )


def test_visual_runtime_env_is_empty_when_disabled(tmp_path):
    assert visual_runtime_env(
        {"id": "job-normal", "uiConfig": {"visualMode": False}},
        tmp_path,
    ) == {}
```

- [ ] **Step 2: Write failing SolidWorks instrumentation tests**

Create `tests/test_sw_visual_integration.py`:

```python
import contextlib
from types import SimpleNamespace

from scripts import sw_session, sw_visual_trace


def test_new_part_uses_visual_step(monkeypatch):
    entered = []

    @contextlib.contextmanager
    def fake_step(step_id, phase, title, message="", snapshot=True):
        entered.append((step_id, phase, title))
        yield

    monkeypatch.setattr(sw_session, "visual_step", fake_step)
    monkeypatch.setattr(
        sw_session,
        "connect_solidworks",
        lambda **_: (
            SimpleNamespace(),
            None,
            {"started_by_cad_studio": False, "process_id": 7},
        ),
    )
    monkeypatch.setattr(
        sw_session,
        "new_document",
        lambda *_args, **_kwargs: SimpleNamespace(GetTitle=lambda: "Part1"),
    )

    session = sw_session.SolidWorksSession()
    session.new_part()

    assert entered == [("part-new-part", "planning", "创建零件文档")]
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests\test_live_visual_queue.py tests\test_sw_visual_integration.py -v
```

Expected: import failures for `visual_runtime_env`, `visual_frame_dir_for`, and `sw_session.visual_step`.

- [ ] **Step 4: Add Worker visual environment**

In `apps/desktop/cad_workbench/queue_worker.py`, add beside `event_path_for`:

```python
def visual_frame_dir_for(queue_dir: Path, job_id: Any) -> Path:
    """返回当前任务的视觉快照目录。"""
    safe_id = "".join(
        ch for ch in str(job_id or "") if ch.isascii() and (ch.isalnum() or ch in "-_")
    ) or "unknown"
    directory = Path(queue_dir) / "visual" / safe_id[:96]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def visual_runtime_env(job: dict[str, Any], queue_dir: Path) -> dict[str, str]:
    """为启用可视化模式的任务生成子进程环境。"""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    if ui_config.get("visualMode") is not True:
        return {}
    job_id = job.get("id")
    return {
        "CADSTUDIO_JOB_ID": str(job_id),
        "CADSTUDIO_VISUAL_MODE": "1",
        "CADSTUDIO_VISUAL_EVENT_FILE": str(event_path_for(queue_dir, job_id)),
        "CADSTUDIO_VISUAL_FRAME_DIR": str(visual_frame_dir_for(queue_dir, job_id)),
    }
```

In `_run_command_with_runtime`, after reading `knowledge`, add:

```python
    queue_root = job_path.parent
    child_env.update(visual_runtime_env(job, queue_root))
    if child_env.get("CADSTUDIO_VISUAL_MODE") == "1":
        append_event(
            queue_root,
            job,
            "visual.session.started",
            "可视化执行已开始",
            {
                "eventFile": child_env["CADSTUDIO_VISUAL_EVENT_FILE"],
                "frameDir": child_env["CADSTUDIO_VISUAL_FRAME_DIR"],
            },
        )
```

- [ ] **Step 5: Instrument SolidWorksSession**

At the top of `scripts/sw_session.py`, add:

```python
try:
    from .sw_visual_trace import visual_step
except ImportError:
    from sw_visual_trace import visual_step
```

Wrap methods with real COM calls:

```python
    def new(self, doc_type="part", template_path=None):
        with visual_step(
            f"part-new-{doc_type}",
            "planning",
            f"创建{doc_type}文档",
            "正在创建 SolidWorks 文档",
        ):
            self.model = new_document(
                self.sw,
                doc_type=doc_type,
                template_path=template_path,
                max_documents=self.max_documents,
            )
            self._remember(self.model)
            return self.model

    def open(self, file_path, read_only=False, silent=False, raise_on_error=True):
        with visual_step(
            "part-open",
            "planning",
            "打开输入文件",
            f"正在打开 {Path(file_path).name}",
        ):
            return self._open_impl(file_path, read_only, silent, raise_on_error)

    def save(self, model=None, file_path=None):
        with visual_step(
            "model-save",
            "delivery",
            "保存 SolidWorks 模型",
            "正在保存当前模型",
        ):
            return self._save_impl(model, file_path)

    def export(self, model=None, output_path=None, format_ext=None, **kwargs):
        with visual_step(
            "model-export",
            "delivery",
            "导出交付文件",
            f"正在导出 {format_ext or Path(str(output_path)).suffix}",
        ):
            return self._export_impl(model, output_path, format_ext, **kwargs)
```

Move the existing bodies of `open`, `save`, and `export` into `_open_impl`, `_save_impl`, and `_export_impl` without changing behavior.

- [ ] **Step 6: Instrument core feature wrappers**

At the top of `scripts/sw_part.py`, add:

```python
try:
    from .sw_visual_trace import traced_step, visual_step
except ImportError:
    from sw_visual_trace import traced_step, visual_step
```

Add decorators to:

```python
@traced_step("feature-extrude", "feature", "生成拉伸特征")
def extrude_boss(model, sketch_name, depth, direction=True, merge=True, start_offset=0.0):
    # Keep the existing function body exactly as-is.

@traced_step("feature-cut", "feature", "生成切除特征")
def extrude_cut(model, sketch_name, depth, direction=True, flip=False, both_directions=False):
    # Keep the existing function body exactly as-is.

@traced_step("feature-revolve", "feature", "生成旋转特征")
def revolve_boss(model, sketch_name, angle_rad, axis_sketch_name=None):
    # Keep the existing function body exactly as-is.

@traced_step("feature-fillet", "feature", "生成圆角特征")
def fillet(model, radius, edges=None):
    # Keep the existing function body exactly as-is.

@traced_step("feature-chamfer", "feature", "生成倒角特征")
def chamfer(model, distance, angle_deg=45):
    # Keep the existing function body exactly as-is.

@traced_step("feature-hole", "feature", "生成孔特征")
def hole_wizard(model, hole_type, standard, fastener_type, size, depth, x, y, z):
    # Keep the existing function body exactly as-is.
```

For the `sketch` context manager, emit manually:

```python
    with visual_step(
        "sketch-create",
        "sketch",
        f"绘制草图：{plane_name}",
        "正在进入草图环境",
    ):
        started = start_sketch(model, plane_name)
        if not started:
            raise RuntimeError(f"无法在 {plane_name} 创建草图")
        try:
            yield sketch_ref
        finally:
            exit_sketch(model)
```

- [ ] **Step 7: Run tests and verify they pass**

Run:

```powershell
python -m pytest tests\test_live_visual_queue.py tests\test_sw_visual_integration.py tests\test_sw_session_ownership.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add apps/desktop/cad_workbench/queue_worker.py scripts/sw_session.py scripts/sw_part.py tests/test_live_visual_queue.py tests/test_sw_visual_integration.py
git commit -m "feat: emit live visual events during SolidWorks execution"
```

---

### Task 4: Tauri HUD 窗口与安全快照读取

**Files:**
- Modify: `apps/workbench-ui/src-tauri/tauri.conf.json`
- Modify: `apps/workbench-ui/src-tauri/capabilities/default.json`
- Modify: `apps/workbench-ui/src-tauri/src/lib.rs`

**Interfaces:**
- Produces: Tauri window label `live-hud`
- Produces: command `read_live_visual_frame(id: String, fileName: String) -> Response`
- Produces: command `set_live_hud_visible(visible: bool) -> Result<(), String>`
- Produces: `validate_live_frame_name(file_name: &str) -> Result<(), String>`

- [ ] **Step 1: Write failing Rust tests**

In the `#[cfg(test)]` module of `apps/workbench-ui/src-tauri/src/lib.rs`, add:

```rust
    #[test]
    fn live_frame_name_rejects_paths_and_non_images() {
        assert!(super::validate_live_frame_name("step-001-sketch-main.png").is_ok());
        assert!(super::validate_live_frame_name("../secret.png").is_err());
        assert!(super::validate_live_frame_name("step-001-sketch-main.exe").is_err());
        assert!(super::validate_live_frame_name("preview.png").is_err());
    }
```

- [ ] **Step 2: Run the Rust test and verify it fails**

Run:

```powershell
cargo test --manifest-path apps\workbench-ui\src-tauri\Cargo.toml live_frame_name_rejects_paths_and_non_images
```

Expected: compile fails because `validate_live_frame_name` is missing.

- [ ] **Step 3: Add the second Tauri window**

In `apps/workbench-ui/src-tauri/tauri.conf.json`, append to `app.windows`:

```json
{
  "label": "live-hud",
  "title": "CAD Live",
  "url": "index.html?window=live",
  "width": 420,
  "height": 300,
  "minWidth": 320,
  "minHeight": 220,
  "visible": false,
  "transparent": true,
  "decorations": false,
  "alwaysOnTop": true,
  "skipTaskbar": true,
  "resizable": false,
  "focus": false,
  "shadow": false
}
```

Change capabilities window list to:

```json
"windows": ["main", "live-hud"]
```

Add permissions:

```json
"core:window:allow-set-always-on-top",
"core:window:allow-set-ignore-cursor-events",
"core:window:allow-show",
"core:window:allow-hide"
```

- [ ] **Step 4: Implement frame validation and commands**

In `apps/workbench-ui/src-tauri/src/lib.rs`, add near `read_preview_file`:

```rust
fn validate_live_frame_name(file_name: &str) -> Result<(), String> {
    if file_name.contains('/') || file_name.contains('\\') || file_name.contains("..") {
        return Err("快照文件名包含非法路径段".to_string());
    }
    if !file_name.starts_with("step-") {
        return Err("只允许读取任务步骤快照".to_string());
    }
    let extension = Path::new(file_name)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !["png", "jpg", "jpeg"].contains(&extension.as_str()) {
        return Err("快照只允许 PNG 或 JPEG".to_string());
    }
    Ok(())
}

#[tauri::command]
fn read_live_visual_frame(
    app: AppHandle,
    id: String,
    file_name: String,
) -> Result<tauri::ipc::Response, String> {
    validate_live_frame_name(&file_name)?;
    let root = queue_dir(&app)?
        .join("visual")
        .join(safe_id(&id)?);
    let canonical_root = fs::canonicalize(&root)
        .map_err(|error| format!("无法定位视觉快照目录: {error}"))?;
    let target = fs::canonicalize(root.join(&file_name))
        .map_err(|error| format!("无法读取视觉快照: {error}"))?;
    if !target.starts_with(&canonical_root) || !target.is_file() {
        return Err("视觉快照越界或不是普通文件".to_string());
    }
    let metadata = fs::metadata(&target).map_err(|error| error.to_string())?;
    if metadata.len() > 8 * 1024 * 1024 {
        return Err("视觉快照超过 8 MiB".to_string());
    }
    let bytes = fs::read(target).map_err(|error| error.to_string())?;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
fn set_live_hud_visible(app: AppHandle, visible: bool) -> Result<(), String> {
    let window = app
        .get_webview_window("live-hud")
        .ok_or_else(|| "live-hud 窗口未初始化".to_string())?;
    if visible {
        window.show().map_err(|error| error.to_string())?;
        window
            .set_always_on_top(true)
            .map_err(|error| error.to_string())?;
    } else {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}
```

Add both commands to `tauri::generate_handler!`.

- [ ] **Step 5: Run Rust tests and frontend build**

Run:

```powershell
cargo test --manifest-path apps\workbench-ui\src-tauri\Cargo.toml
npm run build --prefix apps\workbench-ui
```

Expected: all Rust tests pass and Vite build exits `0`.

- [ ] **Step 6: Commit**

```powershell
git add apps/workbench-ui/src-tauri/tauri.conf.json apps/workbench-ui/src-tauri/capabilities/default.json apps/workbench-ui/src-tauri/src/lib.rs
git commit -m "feat: add secure live HUD window"
```

---

### Task 5: React 视觉状态模型

**Files:**
- Create: `apps/workbench-ui/src/live/visualTypes.ts`
- Create: `apps/workbench-ui/src/live/visualState.ts`
- Create: `apps/workbench-ui/src/live/visualState.test.ts`

**Interfaces:**
- Consumes: `QueueEvent[]`、`AutomationJob`
- Produces: `VisualPhase`
- Produces: `VisualStep`
- Produces: `LiveVisualState`
- Produces: `deriveLiveVisual(job, events) -> LiveVisualState`

- [ ] **Step 1: Write failing state tests**

Create `apps/workbench-ui/src/live/visualState.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { AutomationJob, QueueEvent } from "../types";
import { deriveLiveVisual } from "./visualState";

function job(overrides: Partial<AutomationJob> = {}): AutomationJob {
  return {
    schemaVersion: "2.0",
    id: "job-visual",
    runId: "run-visual",
    kind: "agent_task",
    title: "阶梯轴可视化",
    detail: "SolidWorks",
    status: "running",
    progress: 30,
    stage: "executing",
    createdAt: "2026-11-06T00:00:00Z",
    updatedAt: "2026-11-06T00:00:01Z",
    requestedBy: "test",
    createdByAppVersion: "test",
    lastMessage: "正在执行",
    ...overrides,
  };
}

function visualEvent(
  type: string,
  data: Record<string, unknown>,
  progress = 30,
): QueueEvent {
  return {
    type,
    jobId: "job-visual",
    progress,
    message: String(data.message ?? data.title ?? ""),
    at: "2026-11-06T00:00:02Z",
    data,
  };
}

describe("deriveLiveVisual", () => {
  it("maps a running feature step to working", () => {
    const state = deriveLiveVisual(job(), [
      visualEvent("visual.step.started", {
        stepId: "feature-main-shaft",
        sequence: 3,
        phase: "feature",
        title: "生成主体阶梯轴",
        message: "正在旋转轮廓",
      }),
    ]);

    expect(state.status).toBe("working");
    expect(state.title).toBe("生成主体阶梯轴");
    expect(state.phase).toBe("feature");
    expect(state.sequence).toBe(3);
  });

  it("maps delivery completion to complete only for passed jobs", () => {
    const events = [
      visualEvent(
        "visual.delivery.ready",
        {
          stepId: "delivery-ready",
          phase: "delivery",
          title: "交付文件已生成",
          message: "模型与 STEP 已保存",
        },
        100,
      ),
    ];

    expect(deriveLiveVisual(job({ status: "passed", progress: 100 }), events).status).toBe(
      "complete",
    );
    expect(
      deriveLiveVisual(job({ status: "review_required", progress: 100 }), events).status,
    ).toBe("checking");
  });

  it("falls back to job state when visual events are absent", () => {
    expect(deriveLiveVisual(job({ status: "failed", lastMessage: "COM 失败" }), []).status).toBe(
      "warning",
    );
    expect(deriveLiveVisual(job({ status: "running", stage: "reviewing" }), []).status).toBe(
      "checking",
    );
  });

  it("keeps the latest snapshot path and stats", () => {
    const state = deriveLiveVisual(job(), [
      visualEvent("visual.step.completed", {
        stepId: "feature-main-shaft",
        sequence: 4,
        phase: "feature",
        title: "主体完成",
        message: "实体已重建",
        snapshotPath: "visual/job-visual/step-004-feature-main-shaft.png",
        stats: { volumeMm3: 28378.5, featureCount: 6 },
      }),
    ]);

    expect(state.snapshotPath).toContain("step-004-feature-main-shaft.png");
    expect(state.stats.volumeMm3).toBe(28378.5);
    expect(state.stats.featureCount).toBe(6);
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
npm test --prefix apps\workbench-ui -- src/live/visualState.test.ts
```

Expected: Vitest reports missing `./visualState`.

- [ ] **Step 3: Implement types and derivation**

Create `apps/workbench-ui/src/live/visualTypes.ts`:

```ts
export type VisualPhase =
  | "planning"
  | "sketch"
  | "feature"
  | "assembly"
  | "drawing"
  | "review"
  | "delivery";

export type VisualStatus = "thinking" | "working" | "checking" | "complete" | "warning";

export type VisualStep = {
  stepId: string;
  sequence: number;
  phase: VisualPhase;
  title: string;
  message: string;
  snapshotPath?: string;
  stats?: Record<string, number>;
};

export type LiveVisualState = {
  status: VisualStatus;
  phase: VisualPhase;
  title: string;
  message: string;
  progress: number;
  sequence: number;
  snapshotPath?: string;
  stats: Record<string, number>;
  steps: VisualStep[];
};
```

Create `apps/workbench-ui/src/live/visualState.ts`:

```ts
import type { AutomationJob, QueueEvent } from "../types";
import type { LiveVisualState, VisualPhase, VisualStatus, VisualStep } from "./visualTypes";

const phases = new Set<VisualPhase>([
  "planning",
  "sketch",
  "feature",
  "assembly",
  "drawing",
  "review",
  "delivery",
]);

function phaseOf(value: unknown): VisualPhase {
  return typeof value === "string" && phases.has(value as VisualPhase)
    ? (value as VisualPhase)
    : "planning";
}

function numericStats(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] =>
      typeof entry[1] === "number" && Number.isFinite(entry[1]),
    ),
  );
}

function eventStep(event: QueueEvent): VisualStep | null {
  const data = event.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const value = data as Record<string, unknown>;
  if (typeof value.stepId !== "string" || typeof value.title !== "string") return null;
  return {
    stepId: value.stepId,
    sequence: typeof value.sequence === "number" ? value.sequence : 0,
    phase: phaseOf(value.phase),
    title: value.title,
    message: event.message || (typeof value.message === "string" ? value.message : ""),
    snapshotPath: typeof value.snapshotPath === "string" ? value.snapshotPath : undefined,
    stats: numericStats(value.stats),
  };
}

function jobFallback(job: AutomationJob): LiveVisualState {
  const status: VisualStatus =
    job.status === "passed"
      ? "complete"
      : ["failed", "blocked", "cancelled", "approval_required"].includes(job.status)
        ? "warning"
        : job.stage === "reviewing"
          ? "checking"
          : job.status === "queued"
            ? "thinking"
            : "working";
  return {
    status,
    phase: job.stage === "reviewing" ? "review" : job.stage === "delivery" ? "delivery" : "planning",
    title: job.lastMessage || job.title,
    message: job.lastMessage || "",
    progress: job.progress,
    sequence: 0,
    stats: {},
    steps: [],
  };
}

export function deriveLiveVisual(job: AutomationJob, events: QueueEvent[]): LiveVisualState {
  const visualEvents = events.filter((event) => event.type?.startsWith("visual."));
  const steps = visualEvents.map(eventStep).filter((item): item is VisualStep => Boolean(item));
  const latest = steps.at(-1);
  const latestEvent = visualEvents.at(-1);
  if (!latest || !latestEvent) return jobFallback(job);

  let status: VisualStatus = "working";
  if (latestEvent.type === "visual.step.started") status = "thinking";
  if (latest.phase === "review") status = "checking";
  if (latestEvent.type === "visual.step.failed" || latestEvent.type === "visual.session.failed") {
    status = "warning";
  }
  if (latestEvent.type === "visual.delivery.ready") {
    status = job.status === "passed" ? "complete" : "checking";
  }
  if (["failed", "blocked", "cancelled", "approval_required"].includes(job.status)) {
    status = "warning";
  }

  return {
    status,
    phase: latest.phase,
    title: latest.title,
    message: latest.message,
    progress:
      typeof latestEvent.progress === "number" ? latestEvent.progress : job.progress,
    sequence: latest.sequence,
    snapshotPath: [...steps].reverse().find((step) => step.snapshotPath)?.snapshotPath,
    stats: Object.assign({}, ...steps.map((step) => step.stats ?? {})),
    steps,
  };
}
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
npm test --prefix apps\workbench-ui -- src/live/visualState.test.ts
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```powershell
git add apps/workbench-ui/src/live/visualTypes.ts apps/workbench-ui/src/live/visualState.ts apps/workbench-ui/src/live/visualState.test.ts
git commit -m "feat: derive live visual state from queue events"
```

---

### Task 6: 机械鱼 HUD

**Files:**
- Create: `apps/workbench-ui/src/live/Mascot.tsx`
- Create: `apps/workbench-ui/src/live/LiveHud.tsx`
- Create: `apps/workbench-ui/src/live/live-hud.css`
- Create: `apps/workbench-ui/src/live/liveFixtures.ts`
- Create: `apps/workbench-ui/src/assets/live-mascot/idle.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/working.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/checking.webp`
- Create: `apps/workbench-ui/src/assets/live-mascot/complete.webp`
- Modify: `apps/workbench-ui/src/main.tsx`

**Interfaces:**
- Consumes: `deriveLiveVisual()` from Task 5
- Consumes: Tauri commands `read_queue_jobs`, `read_queue_events`, `read_live_visual_frame`, `set_live_hud_visible`
- Produces: `<LiveHud />`
- Produces: `<Mascot status={VisualStatus} />`
- Produces: demo route `?window=live&demo=complete`

- [ ] **Step 1: Generate the original mascot assets**

Use the `imagegen` skill with this exact visual brief:

```text
Original compact mechanical koi-fish desktop assistant, deep navy and teal ceramic shell,
soft cyan inner light, small copper accents, friendly but focused expression, 3/4 view,
transparent background, no text, no logo, consistent character design.
Four separate 512x512 WebP assets: idle floating, working with spinning ring,
checking with magnifier and grid scan, complete with bright spark and raised fin.
```

Save the four transparent assets to:

```text
apps/workbench-ui/src/assets/live-mascot/idle.webp
apps/workbench-ui/src/assets/live-mascot/working.webp
apps/workbench-ui/src/assets/live-mascot/checking.webp
apps/workbench-ui/src/assets/live-mascot/complete.webp
```

- [ ] **Step 2: Add the mascot component**

Create `apps/workbench-ui/src/live/Mascot.tsx`:

```tsx
import { motion, useReducedMotion } from "motion/react";
import type { VisualStatus } from "./visualTypes";
import idle from "../assets/live-mascot/idle.webp";
import working from "../assets/live-mascot/working.webp";
import checking from "../assets/live-mascot/checking.webp";
import complete from "../assets/live-mascot/complete.webp";

const assets: Record<VisualStatus, string> = {
  thinking: idle,
  working,
  checking,
  complete,
  warning: idle,
};

export function Mascot({ status }: { status: VisualStatus }) {
  const reducedMotion = useReducedMotion();
  return (
    <motion.div
      className={`live-mascot status-${status}`}
      animate={
        reducedMotion
          ? undefined
          : status === "working"
            ? { y: [0, -4, 0], rotate: [-1, 1, -1] }
            : { y: [0, -3, 0] }
      }
      transition={{ duration: status === "working" ? 1.3 : 2.8, repeat: Infinity }}
    >
      <img src={assets[status]} alt="" draggable={false} />
      {status === "working" ? <i className="mascot-ring" /> : null}
    </motion.div>
  );
}
```

- [ ] **Step 3: Add the HUD data loop and layout**

Create `apps/workbench-ui/src/live/LiveHud.tsx` with the complete implementation:

```tsx
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { AnimatePresence, motion } from "motion/react";
import { ArrowsOutSimple, CaretDown, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import type { AutomationJob, QueueEvent } from "../types";
import { demoEvents, demoJob } from "./liveFixtures";
import { deriveLiveVisual } from "./visualState";
import { Mascot } from "./Mascot";
import "./live-hud.css";

const DEMO = new URLSearchParams(location.search).get("demo");

function activeJob(jobs: AutomationJob[]) {
  const rank = (job: AutomationJob) =>
    ["running", "review_required", "approval_required", "queued", "passed", "failed"].indexOf(job.status);
  return [...jobs]
    .filter((job) => ["running", "review_required", "approval_required", "queued", "passed", "failed"].includes(job.status))
    .sort((a, b) => rank(a) - rank(b) || b.updatedAt.localeCompare(a.updatedAt))[0];
}

export function LiveHud() {
  const [collapsed, setCollapsed] = useState(false);
  const [job, setJob] = useState<AutomationJob | undefined>(DEMO ? demoJob : undefined);
  const [events, setEvents] = useState<QueueEvent[]>(DEMO ? demoEvents : []);
  const [frameUrl, setFrameUrl] = useState<string>();

  async function load() {
    if (DEMO) return;
    const jobs = await invoke<AutomationJob[]>("read_queue_jobs");
    const selected = activeJob(jobs);
    setJob(selected);
    if (!selected) {
      setEvents([]);
      return;
    }
    const nextEvents = await invoke<QueueEvent[]>("read_queue_events", { id: selected.id });
    setEvents(nextEvents);
  }

  useEffect(() => {
    void load();
    if (DEMO) return;
    let timer: number | undefined;
    let unlisten: (() => void) | undefined;
    void listen("queue-changed", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void load(), 80);
    }).then((dispose) => {
      unlisten = dispose;
    });
    return () => {
      window.clearTimeout(timer);
      unlisten?.();
    };
  }, []);

  const visual = useMemo(
    () => (job ? deriveLiveVisual(job, events) : undefined),
    [job, events],
  );

  useEffect(() => {
    if (!job || !visual?.snapshotPath || DEMO) {
      setFrameUrl(undefined);
      return;
    }
    const fileName = visual.snapshotPath.split(/[\\/]/).at(-1);
    if (!fileName) return;
    let disposed = false;
    void invoke<ArrayBuffer>("read_live_visual_frame", { id: job.id, fileName }).then((bytes) => {
      if (disposed) return;
      const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return url;
      });
    });
    return () => {
      disposed = true;
    };
  }, [job?.id, visual?.snapshotPath]);

  if (!job || !visual) {
    return (
      <main className="live-hud empty">
        <Mascot status="thinking" />
        <section><strong>等待可视化任务</strong><span>提交任务后这里会同步执行步骤</span></section>
      </main>
    );
  }

  if (collapsed) {
    return (
      <button className="live-hud collapsed" type="button" onClick={() => setCollapsed(false)}>
        <Mascot status={visual.status} />
        <span>{visual.progress}%</span>
      </button>
    );
  }

  return (
    <main className={`live-hud status-${visual.status}`}>
      <header data-tauri-drag-region>
        <span>LIVE CAD</span>
        <strong>{job.title}</strong>
        <button type="button" onClick={() => setCollapsed(true)} title="收起">
          <CaretDown size={16} />
        </button>
      </header>
      <div className="live-hud-body">
        <Mascot status={visual.status} />
        <section className="live-hud-copy">
          <div className="live-bubble">
            <strong>{visual.title}</strong>
            <p>{visual.message || "正在等待下一步"}</p>
          </div>
          <div className="live-progress-bar"><i style={{ width: `${visual.progress}%` }} /></div>
          <div className="live-step-line">
            <span>{visual.phase.toUpperCase()}</span>
            <small>STEP {String(visual.sequence).padStart(2, "0")}</small>
            <small>{visual.progress}%</small>
          </div>
        </section>
        <AnimatePresence>
          {frameUrl ? (
            <motion.img
              className="live-snapshot"
              src={frameUrl}
              alt="SolidWorks 当前步骤快照"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
            />
          ) : null}
        </AnimatePresence>
      </div>
      <footer>
        {visual.status === "complete" ? <CheckCircle size={16} weight="fill" /> : null}
        {visual.status === "warning" ? <WarningCircle size={16} weight="fill" /> : null}
        <span>{visual.stats.volumeMm3 ? `${visual.stats.volumeMm3.toFixed(1)} mm³` : "CAD 执行中"}</span>
        <span>{visual.stats.featureCount ? `${visual.stats.featureCount} 个特征` : ""}</span>
        <ArrowsOutSimple size={14} />
      </footer>
    </main>
  );
}
```

- [ ] **Step 4: Add demo fixtures and query-based entry**

Create `apps/workbench-ui/src/live/liveFixtures.ts`:

```ts
import type { AutomationJob, QueueEvent } from "../types";

export const demoJob: AutomationJob = {
  schemaVersion: "2.0",
  id: "job-live-demo",
  runId: "run-live-demo",
  kind: "agent_task",
  title: "阶梯轴可视化建模",
  detail: "SolidWorks 2026",
  status: "passed",
  progress: 100,
  stage: "delivery",
  createdAt: "2026-11-06T00:00:00Z",
  updatedAt: "2026-11-06T00:00:20Z",
  requestedBy: "demo",
  createdByAppVersion: "demo",
};

export const demoEvents: QueueEvent[] = [
  {
    type: "visual.step.completed",
    jobId: demoJob.id,
    progress: 55,
    message: "主体阶梯轴已生成",
    at: "2026-11-06T00:00:12Z",
    data: {
      stepId: "feature-main-shaft",
      sequence: 3,
      phase: "feature",
      title: "生成主体阶梯轴",
      message: "旋转特征已重建成实体",
      stats: { volumeMm3: 28378.5, featureCount: 6 },
    },
  },
  {
    type: "visual.delivery.ready",
    jobId: demoJob.id,
    progress: 100,
    message: "交付文件已生成",
    at: "2026-11-06T00:00:20Z",
    data: {
      stepId: "delivery-ready",
      sequence: 7,
      phase: "delivery",
      title: "这一轮搞定啦",
      message: "SLDPRT 与 STEP 已保存",
      stats: { volumeMm3: 28378.5, featureCount: 6 },
    },
  },
];
```

Update `apps/workbench-ui/src/main.tsx`:

```tsx
import App from "./App";
import { LiveHud } from "./live/LiveHud";

const windowKind = new URLSearchParams(location.search).get("window");

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {windowKind === "live" ? <LiveHud /> : <App />}
  </React.StrictMode>,
);
```

- [ ] **Step 5: Add HUD styles**

Create `apps/workbench-ui/src/live/live-hud.css` with these complete core rules:

```css
:root {
  background: transparent;
}

html,
body,
#root {
  margin: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: transparent;
  font-family: "Segoe UI Variable", "Microsoft YaHei UI", sans-serif;
}

.live-hud {
  position: relative;
  width: calc(100% - 16px);
  height: calc(100% - 16px);
  margin: 8px;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid rgba(116, 221, 230, 0.38);
  border-radius: 18px;
  background:
    linear-gradient(145deg, rgba(8, 22, 30, 0.96), rgba(12, 34, 43, 0.91)),
    radial-gradient(circle at 85% 10%, rgba(72, 196, 210, 0.2), transparent 38%);
  color: #eefbfc;
  box-shadow: 0 18px 52px rgba(0, 0, 0, 0.38), inset 0 1px rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(16px);
}

.live-hud header {
  height: 42px;
  padding: 0 10px 0 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(126, 222, 228, 0.14);
}

.live-hud header span {
  color: #67d7e2;
  font-size: 10px;
  letter-spacing: 0.14em;
}

.live-hud header strong {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.live-hud header button {
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  color: #cceff2;
}

.live-hud-body {
  height: calc(100% - 76px);
  padding: 12px 14px;
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) 112px;
  gap: 12px;
  align-items: center;
}

.live-mascot {
  position: relative;
  width: 92px;
  height: 92px;
  display: grid;
  place-items: center;
}

.live-mascot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 8px 18px rgba(52, 213, 224, 0.22));
}

.mascot-ring {
  position: absolute;
  inset: 6px;
  border: 2px dashed rgba(101, 226, 233, 0.55);
  border-radius: 50%;
  animation: live-spin 5s linear infinite;
}

.live-bubble {
  min-height: 62px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(233, 249, 250, 0.94);
  color: #112f36;
}

.live-bubble strong {
  display: block;
  font-size: 12px;
}

.live-bubble p {
  margin: 5px 0 0;
  font-size: 11px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.live-progress-bar {
  height: 4px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.09);
}

.live-progress-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #4bd7df, #a8f4dc);
  transition: width 240ms ease;
}

.live-step-line {
  margin-top: 7px;
  display: flex;
  gap: 8px;
  color: #8fdce2;
  font-size: 9px;
  letter-spacing: 0.08em;
}

.live-step-line small {
  color: #7da5ab;
}

.live-snapshot {
  width: 112px;
  height: 82px;
  border-radius: 10px;
  object-fit: cover;
  border: 1px solid rgba(151, 232, 236, 0.22);
}

.live-hud footer {
  height: 34px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8db8bd;
  font-size: 9px;
  border-top: 1px solid rgba(126, 222, 228, 0.12);
}

.live-hud footer span:nth-child(2) {
  flex: 1;
}

.live-hud.collapsed {
  width: 112px;
  height: 112px;
  margin: 8px;
  padding: 0;
  cursor: pointer;
}

.live-hud.collapsed span {
  position: absolute;
  right: 10px;
  bottom: 8px;
  font-size: 10px;
  color: #7ee7ee;
}

.live-hud.empty {
  display: grid;
  grid-template-columns: 100px 1fr;
  align-items: center;
  padding: 20px;
  box-sizing: border-box;
}

.live-hud.empty section {
  display: grid;
  gap: 6px;
}

.live-hud.empty section span {
  color: #7da5ab;
  font-size: 11px;
}

.status-warning {
  border-color: rgba(239, 176, 82, 0.5);
}

@keyframes live-spin {
  to { transform: rotate(360deg); }
}
```

- [ ] **Step 6: Run the frontend build**

Run:

```powershell
npm run build --prefix apps\workbench-ui
```

Expected: TypeScript and Vite build exit `0`.

- [ ] **Step 7: Commit**

```powershell
git add apps/workbench-ui/src/live/Mascot.tsx apps/workbench-ui/src/live/LiveHud.tsx apps/workbench-ui/src/live/live-hud.css apps/workbench-ui/src/live/liveFixtures.ts apps/workbench-ui/src/main.tsx apps/workbench-ui/src/assets/live-mascot
git commit -m "feat: add mechanical fish live HUD"
```

---

### Task 7: 主窗口可视化执行开关与交付卡

**Files:**
- Create: `apps/workbench-ui/src/live/LiveExecutionStrip.tsx`
- Create: `apps/workbench-ui/src/live/LiveDeliveryCard.tsx`
- Modify: `apps/workbench-ui/src/types.ts`
- Modify: `apps/workbench-ui/src/App.tsx`
- Modify: `apps/workbench-ui/src/styles.css`

**Interfaces:**
- Consumes: `deriveLiveVisual()`
- Consumes: Tauri `set_live_hud_visible`
- Produces: persisted `AppSettings.visualMode`
- Produces: persisted `AppSettings.showLiveHud`
- Produces: `<LiveExecutionStrip job events />`
- Produces: `<LiveDeliveryCard job visual />`

- [ ] **Step 1: Extend settings types**

In `apps/workbench-ui/src/types.ts`, add to `AppSettings`:

```ts
visualMode: boolean;
showLiveHud: boolean;
```

- [ ] **Step 2: Add main-window state and persistence**

In `apps/workbench-ui/src/App.tsx`, add near wallpaper settings state:

```tsx
const [visualMode, setVisualMode] = useState(false);
const [showLiveHud, setShowLiveHud] = useState(true);
```

In `loadSettings`, return:

```tsx
      visualMode: parsed.visualMode === true,
      showLiveHud: parsed.showLiveHud !== false,
```

When applying loaded settings around line 2283, add:

```tsx
      setVisualMode(settings.visualMode);
      setShowLiveHud(settings.showLiveHud);
```

In the settings persistence object, add:

```tsx
      visualMode,
      showLiveHud,
```

Add both values to the persistence effect dependency list.

Add a startup visibility effect near the other settings effects:

```tsx
  useEffect(() => {
    if (!settingsLoaded || !isTauriRuntime()) return;
    void invoke("set_live_hud_visible", { visible: showLiveHud }).catch((error) => {
      setWindowHint(`桌宠窗口初始化失败：${String(error)}`);
    });
  }, [settingsLoaded, showLiveHud]);
```

- [ ] **Step 3: Add HUD visibility helper**

In `App.tsx`, add:

```tsx
  async function updateLiveHudVisibility(visible: boolean) {
    setShowLiveHud(visible);
    if (!isTauriRuntime()) return;
    try {
      await invoke("set_live_hud_visible", { visible });
    } catch (error) {
      setWindowHint(`桌宠窗口状态更新失败：${String(error)}`);
    }
  }
```

- [ ] **Step 4: Include visual mode in new agent jobs**

In the `uiConfig` object created by `submitAgentMessage`, add:

```tsx
        visualMode,
        liveHud: showLiveHud,
```

In the task `capabilities` array, add `"visual_live_execution"` only when `visualMode` is true:

```tsx
      capabilities: visualMode
        ? [...capabilities, "visual_live_execution"]
        : capabilities,
```

- [ ] **Step 5: Add the execution strip component**

Create `apps/workbench-ui/src/live/LiveExecutionStrip.tsx`:

```tsx
import type { AutomationJob, QueueEvent } from "../types";
import { deriveLiveVisual } from "./visualState";

export function LiveExecutionStrip({
  job,
  events,
}: {
  job: AutomationJob;
  events: QueueEvent[];
}) {
  const visual = deriveLiveVisual(job, events);
  return (
    <section className={`live-execution-strip status-${visual.status}`} aria-live="polite">
      <div className="live-execution-copy">
        <span>{visual.phase.toUpperCase()}</span>
        <strong>{visual.title}</strong>
        <small>{visual.message || `步骤 ${visual.sequence}`}</small>
      </div>
      <div className="live-execution-progress">
        <i style={{ width: `${visual.progress}%` }} />
      </div>
      <span className="live-execution-progress-label">{visual.progress}%</span>
    </section>
  );
}
```

- [ ] **Step 6: Add the delivery card component**

Create `apps/workbench-ui/src/live/LiveDeliveryCard.tsx`:

```tsx
import { CheckCircle, FolderOpen, WarningCircle } from "@phosphor-icons/react";
import type { AutomationJob } from "../types";
import { deriveLiveVisual } from "./visualState";
import type { QueueEvent } from "../types";

export function LiveDeliveryCard({
  job,
  events,
  onOpenDelivery,
}: {
  job: AutomationJob;
  events: QueueEvent[];
  onOpenDelivery: () => void;
}) {
  const visual = deriveLiveVisual(job, events);
  const isComplete = job.status === "passed";
  return (
    <section className={`live-delivery-card ${isComplete ? "complete" : "review"}`}>
      <header>
        {isComplete ? <CheckCircle size={18} weight="fill" /> : <WarningCircle size={18} weight="fill" />}
        <strong>{isComplete ? "本轮交付完成" : "本轮需要复核"}</strong>
        <span>{job.reviewGate?.status || job.status}</span>
      </header>
      <div className="live-delivery-stats">
        <div><span>体积</span><strong>{visual.stats.volumeMm3 ? `${visual.stats.volumeMm3.toFixed(1)} mm³` : "未提供"}</strong></div>
        <div><span>特征</span><strong>{visual.stats.featureCount ?? "未提供"}</strong></div>
        <div><span>输出</span><strong>{job.result?.outputPath?.split(/[\\/]/).at(-1) || "未提供"}</strong></div>
      </div>
      <footer>
        <button type="button" onClick={onOpenDelivery}>
          <FolderOpen size={15} />
          查看交付页
        </button>
      </footer>
    </section>
  );
}
```

- [ ] **Step 7: Render visual controls and components in App**

In the agent header, after `ConversationControls`, add:

```tsx
                <label className="visual-mode-toggle">
                  <input
                    type="checkbox"
                    checked={visualMode}
                    onChange={(event) => setVisualMode(event.target.checked)}
                  />
                  可视化执行
                </label>
                <button
                  className="visual-hud-toggle"
                  type="button"
                  onClick={() => void updateLiveHudVisibility(!showLiveHud)}
                >
                  {showLiveHud ? "隐藏桌宠" : "显示桌宠"}
                </button>
```

Inside the active job panel, before the engineering plan, add:

```tsx
                  <LiveExecutionStrip job={activeAgentJob} events={activeAgentEvents} />
```

When the active job is terminal, render the delivery card above the existing timeline:

```tsx
                  {["passed", "review_required", "failed", "blocked"].includes(activeAgentJob.status) ? (
                    <LiveDeliveryCard
                      job={activeAgentJob}
                      events={activeAgentEvents}
                      onOpenDelivery={() => setActiveTab("export")}
                    />
                  ) : null}
```

- [ ] **Step 8: Add styles**

Append to `apps/workbench-ui/src/styles.css`:

```css
.visual-mode-toggle,
.visual-hud-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(99, 176, 181, 0.24);
  border-radius: 7px;
  background: rgba(252, 255, 255, 0.62);
  color: #31575b;
  font-size: 11px;
  white-space: nowrap;
}

.live-execution-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px 38px;
  gap: 10px;
  align-items: center;
  padding: 9px 11px;
  border: 1px solid rgba(70, 166, 172, 0.2);
  border-radius: 8px;
  background: rgba(238, 249, 250, 0.72);
}

.live-execution-copy {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.live-execution-copy span {
  color: #27939d;
  font-size: 9px;
  letter-spacing: 0.08em;
}

.live-execution-copy strong,
.live-execution-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-execution-copy strong {
  font-size: 12px;
}

.live-execution-copy small,
.live-execution-progress-label {
  color: #62868a;
  font-size: 10px;
}

.live-execution-progress {
  height: 4px;
  overflow: hidden;
  border-radius: 4px;
  background: rgba(52, 117, 122, 0.11);
}

.live-execution-progress i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #42bec7, #89d9c3);
  transition: width 220ms ease;
}

.live-delivery-card {
  padding: 12px;
  border: 1px solid rgba(49, 151, 158, 0.24);
  border-radius: 9px;
  background: rgba(247, 253, 253, 0.78);
}

.live-delivery-card header,
.live-delivery-card footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-delivery-card header strong {
  flex: 1;
  font-size: 12px;
}

.live-delivery-card header span {
  color: #668b8f;
  font-size: 10px;
}

.live-delivery-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 10px 0;
}

.live-delivery-stats div {
  min-width: 0;
  padding: 8px;
  background: rgba(224, 242, 243, 0.55);
}

.live-delivery-stats span,
.live-delivery-stats strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-delivery-stats span {
  color: #6b8d91;
  font-size: 9px;
}

.live-delivery-stats strong {
  margin-top: 3px;
  font-size: 11px;
}

.live-delivery-card footer button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 7px;
  background: #1d777f;
  color: white;
  font-size: 10px;
}

@media (max-width: 960px) {
  .live-execution-strip {
    grid-template-columns: minmax(0, 1fr) 70px 34px;
  }

  .live-execution-copy {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .live-execution-copy small {
    display: none;
  }

  .live-delivery-stats {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 9: Run frontend tests and build**

Run:

```powershell
npm test --prefix apps\workbench-ui
npm run build --prefix apps\workbench-ui
```

Expected: all Vitest tests pass and the production build exits `0`.

- [ ] **Step 10: Commit**

```powershell
git add apps/workbench-ui/src/live/LiveExecutionStrip.tsx apps/workbench-ui/src/live/LiveDeliveryCard.tsx apps/workbench-ui/src/types.ts apps/workbench-ui/src/App.tsx apps/workbench-ui/src/styles.css
git commit -m "feat: connect live visual flow to CAD Studio chat"
```

---

### Task 8: End-to-End 演示与文档

**Files:**
- Create: `ai_team/live-visual-e2e.cjs`
- Create: `tests/live_visual_solidworks_smoke.py`
- Modify: `docs/CAD_STUDIO_USER_MANUAL.md`
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: HUD demo route `?window=live&demo=complete`
- Consumes: `.venv\Scripts\python.exe`
- Produces: visual regression screenshots
- Produces: real SolidWorks visual smoke report

- [ ] **Step 1: Add the HUD browser regression**

Create `ai_team/live-visual-e2e.cjs`:

```js
const { chromium } = require("playwright");
const path = require("node:path");
const fs = require("node:fs");

async function main() {
  const root = path.resolve(__dirname, "../apps/workbench-ui");
  const output = path.join(root, "live-visual-e2e");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 420, height: 300 } });
  await page.goto("http://127.0.0.1:5174/?window=live&demo=complete");
  await page.waitForSelector(".live-hud");
  await page.screenshot({ path: path.join(output, "live-hud-complete.png") });
  const text = await page.locator(".live-hud").innerText();
  if (!text.includes("完成") && !text.includes("搞定")) {
    throw new Error(`HUD completion text missing: ${text}`);
  }
  const overflow = await page.locator(".live-hud").evaluate((element) => (
    element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight
  ));
  if (overflow) throw new Error("HUD content overflows its window");
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
```

- [ ] **Step 2: Add the real SolidWorks smoke**

Create `tests/live_visual_solidworks_smoke.py`:

```python
"""用真实 SolidWorks 验证可视化事件与快照。"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_connect import mm
from sw_part import extrude_boss, sketch, sketch_circle
from sw_session import SolidWorksSession


def main() -> int:
    output = ROOT / "output" / "live-visual-smoke"
    frames = output / "frames"
    events = output / "events.jsonl"
    output.mkdir(parents=True, exist_ok=True)
    os.environ["CADSTUDIO_JOB_ID"] = "live-visual-smoke"
    os.environ["CADSTUDIO_VISUAL_EVENT_FILE"] = str(events)
    os.environ["CADSTUDIO_VISUAL_FRAME_DIR"] = str(frames)

    with SolidWorksSession(version=2026, visible=True) as session:
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_circle(model, 0, 0, mm(20))
        if extrude_boss(model, ref, mm(40)) is None:
            raise RuntimeError("拉伸失败")
        part = output / "live-visual-smoke.SLDPRT"
        if not session.save(model, str(part)):
            raise RuntimeError("保存失败")

    payload = [
        json.loads(line)
        for line in events.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(item["type"] == "visual.step.completed" for item in payload)
    assert any(item["data"].get("phase") == "feature" for item in payload)
    assert any(item["data"].get("snapshotPath") for item in payload)
    print(json.dumps({"events": len(payload), "part": str(part)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run automated tests**

Run:

```powershell
npm run dev --prefix apps\workbench-ui
```

In another terminal run:

```powershell
node ai_team\live-visual-e2e.cjs
python -m pytest tests\test_sw_visual_trace.py tests\test_sw_window_capture.py tests\test_live_visual_queue.py tests\test_sw_visual_integration.py -v
npm test --prefix apps\workbench-ui
cargo test --manifest-path apps\workbench-ui\src-tauri\Cargo.toml
```

Expected:

- HUD screenshot generated without overflow.
- Python visual tests all pass.
- Vitest all pass.
- Cargo tests all pass.

- [ ] **Step 4: Run the real SolidWorks smoke**

Run:

```powershell
.\.venv\Scripts\python.exe tests\live_visual_solidworks_smoke.py
```

Expected:

- SolidWorks opens visibly.
- At least one `visual.step.completed` event exists.
- At least one feature-phase event and one snapshot path exist.
- `output/live-visual-smoke/live-visual-smoke.SLDPRT` exists.

- [ ] **Step 5: Document usage**

In `docs/CAD_STUDIO_USER_MANUAL.md`, add a section:

```markdown
## 可视化执行

在 AI 执行对话右上角打开“可视化执行”，再提交 SolidWorks 任务。

桌面右上角会出现机械鱼助手：

- 思考状态：正在整理建模步骤。
- 工作状态：SolidWorks 正在执行当前草图或特征。
- 检查状态：正在复核模型、工程图和交付文件。
- 完成状态：显示体积、特征数和交付文件。
- 警告状态：显示失败、阻断或待人工复核原因。

点击“隐藏桌宠”只隐藏 HUD，不停止任务。重新打开后 HUD 会恢复当前活动任务。

可视化快照只来自 SolidWorks 主窗口，存放在应用数据目录的 `queue/visual/` 下。
```

In `SKILL.md`, add to the Codex 本机接入 section:

```markdown
启用 `visualMode` 的任务会获得 `CADSTUDIO_VISUAL_EVENT_FILE` 和
`CADSTUDIO_VISUAL_FRAME_DIR`。SolidWorks 高层封装自动写入
`visual.step.started/completed/failed` 事件，并在每次成功步骤后捕获主窗口快照。
```

- [ ] **Step 6: Run the full verification**

Run:

```powershell
python -m pytest tests\test_sw_visual_trace.py tests\test_sw_window_capture.py tests\test_live_visual_queue.py tests\test_sw_visual_integration.py -v
npm test --prefix apps\workbench-ui
npm run build --prefix apps\workbench-ui
cargo test --manifest-path apps\workbench-ui\src-tauri\Cargo.toml
node ai_team\live-visual-e2e.cjs
```

Expected: every command exits `0`.

- [ ] **Step 7: Commit**

```powershell
git add ai_team/live-visual-e2e.cjs tests/live_visual_solidworks_smoke.py docs/CAD_STUDIO_USER_MANUAL.md SKILL.md
git commit -m "test: verify SolidWorks live visual flow"
```

---

## Verification Matrix

| Spec requirement | Covered by |
| --- | --- |
| 真实执行事件 | Task 1, Task 3 |
| SolidWorks 前台逐步操作 | Task 3, Task 8 |
| 独立置顶 HUD | Task 4, Task 6 |
| 原创机械鱼五状态 | Task 6 |
| 主窗口实时执行条 | Task 7 |
| 完成交付卡 | Task 7 |
| 快照安全与保留 | Task 2, Task 4 |
| 多任务绑定 | Task 5, Task 6 |
| 异常降级 | Task 5, Task 6 |
| Tauri 权限边界 | Task 4 |
| 真实端到端验收 | Task 8 |

## Execution Notes

- 每完成一个任务立即运行该任务的测试并提交，不把多个任务压成一个提交。
- 遇到现有文件测试失败时，先判断是否由本轮修改引入；已有未提交改动不得回退。
- Task 6 生成资产时使用 `imagegen` 技能，角色必须是原创机械鱼。
- Task 8 的真实 SolidWorks 冒烟使用可见窗口，结束后确认没有遗留 `SLDWORKS.exe`。
