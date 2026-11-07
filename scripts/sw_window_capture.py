"""只捕获 SolidWorks 主窗口的可视化快照。"""

from __future__ import annotations

import os
import re
from pathlib import Path


_SNAPSHOT = re.compile(r"^step-(\d{3,6})-([a-z]+)-(.+)\.(png|jpe?g)$")
_SAFE_SEGMENT = re.compile(r"[^a-z0-9_-]+")
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


def _safe_segment(value: str, fallback: str) -> str:
    token = _SAFE_SEGMENT.sub("-", str(value or "").strip().lower()).strip("-_")
    return (token or fallback)[:96]


def snapshot_filename(sequence: int, phase: str, step_id: str) -> str:
    safe_phase = _safe_segment(phase, "step")
    safe_step = _safe_segment(step_id, "snapshot")
    return f"step-{max(1, int(sequence)):03d}-{safe_phase}-{safe_step}.png"


def _solidworks_process_ids() -> set[int]:
    try:
        try:
            from .sw_process import solidworks_processes
        except ImportError:
            from sw_process import solidworks_processes

        return {int(pid) for pid in (solidworks_processes() or {})}
    except Exception:
        return set()


def _solidworks_window_handle() -> int | None:
    if os.name != "nt":
        return None
    try:
        import win32con
        import win32gui
        import win32process
    except Exception:
        return None

    process_ids = _solidworks_process_ids()
    if not process_ids:
        return None
    candidates: list[tuple[int, int, int]] = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetAncestor(hwnd, win32con.GA_ROOT) != hwnd:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid not in process_ids:
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        extended_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if extended_style & win32con.WS_EX_TOOLWINDOW:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width < 640 or height < 360:
            return
        title_priority = 1 if "solidworks" in title.casefold() else 0
        candidates.append((title_priority, width * height, hwnd))

    try:
        win32gui.EnumWindows(visit, None)
    except Exception:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return int(candidates[0][2])


def _solidworks_window_rect():
    handle = _solidworks_window_handle()
    if not handle:
        return None
    try:
        import win32gui

        return tuple(int(value) for value in win32gui.GetWindowRect(handle))
    except Exception:
        return None


def _capture_window_bitmap(handle: int):
    """优先使用 PrintWindow，避免把覆盖在 SolidWorks 上方的 HUD 截进快照。"""
    try:
        import ctypes
        from ctypes import wintypes
        import win32gui
        import win32ui
        from PIL import Image

        left, top, right, bottom = win32gui.GetWindowRect(handle)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None
        window_dc = win32gui.GetWindowDC(handle)
        source_dc = win32ui.CreateDCFromHandle(window_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            print_window = ctypes.windll.user32.PrintWindow
            print_window.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
            print_window.restype = wintypes.BOOL
            rendered = print_window(handle, memory_dc.GetSafeHdc(), 2)
            if not rendered:
                print_window(handle, memory_dc.GetSafeHdc(), 0)
            bits = bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB",
                (width, height),
                bits,
                "raw",
                "BGRX",
                0,
                1,
            ).copy()
            if image.convert("L").getextrema()[1] < 8:
                return None
            return image
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            source_dc.DeleteDC()
            win32gui.ReleaseDC(handle, window_dc)
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
    handle = _solidworks_window_handle()
    image = _capture_window_bitmap(handle) if handle else None
    if image is None:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=rect, all_screens=True)
    if image is None:
        return None

    target_dir = Path(frame_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / snapshot_filename(sequence, phase, step_id)
    image.save(target, "PNG", optimize=True)
    if target.stat().st_size > MAX_SNAPSHOT_BYTES:
        target.unlink(missing_ok=True)
        raise ValueError("SolidWorks 快照超过 8 MiB")
    prune_snapshots(target_dir)
    return target


def prune_snapshots(frame_dir: Path, max_frames: int = 80) -> list[Path]:
    frame_dir = Path(frame_dir)
    files = sorted(
        path
        for pattern in ("step-*.png", "step-*.jpg", "step-*.jpeg")
        for path in frame_dir.glob(pattern)
    )
    if len(files) <= max_frames:
        return files
    parsed = []
    for path in files:
        match = _SNAPSHOT.match(path.name)
        if match:
            parsed.append((int(match.group(1)), match.group(2), path))
    protected: set[Path] = set()
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
