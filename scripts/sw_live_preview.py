"""将当前任务的 SolidWorks 建模窗口预览写入 CAD Studio 队列。"""

from contextvars import ContextVar
from pathlib import Path
import os
from queue import Queue
import tempfile
from threading import Lock, Thread

try:
    from .sw_connect import get_com_member
except ImportError:
    from sw_connect import get_com_member


_target = ContextVar("solidworks_preview_target", default=None)
_render_slot = Lock()
_ENV_KEY = "CAD_STUDIO_SW_PREVIEW_PATH"


def _clear_frame(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _same_document(left, right):
    import pythoncom

    return left._oleobj_.QueryInterface(pythoncom.IID_IUnknown) == right._oleobj_.QueryInterface(pythoncom.IID_IUnknown)


def preview_document(sw, model, process_id, existing=()):
    path = os.environ.get(_ENV_KEY)
    if os.name == "nt" and path:
        path = Path(path)
        try:
            if any(_same_document(doc, model) for doc in existing):
                raise RuntimeError("该文档在本轮打开前已存在")
        except Exception:
            _target.set(None)
            _clear_frame(path)
            return
        _target.set((path, sw, model, process_id))
        preview_checkpoint(model)


def close_preview_document(model):
    target = _target.get()
    if target is not None and target[2] is model:
        _target.set(None)
        _clear_frame(target[0])


def preview_checkpoint(model):
    target = _target.get()
    if target is None or target[2] is not model:
        return
    path, sw, _, process_id = target
    try:
        image = _capture_model_window(sw, model, process_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=path.parent) as staging:
            pending = Path(staging) / "frame.png"
            image.save(pending, format="PNG")
            os.replace(pending, path)
    except Exception:
        # 预览属于可选反馈，COM、窗口或文件异常都不得改变建模结果。
        _clear_frame(path)


def _capture_model_window(sw, model, process_id):
    import win32gui
    import win32process

    def window():
        active = get_com_member(sw, "ActiveDoc")
        if active is None or not _same_document(active, model):
            raise RuntimeError("当前活动文档不属于本轮建模")
        frame = int(get_com_member(get_com_member(sw, "Frame"), "GetHWndx64"))
        view = int(get_com_member(get_com_member(model, "ActiveView"), "GetViewHWndx64"))
        if (
            not process_id
            or not win32gui.IsWindowVisible(view)
            or not win32gui.IsWindowVisible(frame)
            or win32gui.IsIconic(frame)
            or not win32gui.IsChild(frame, view)
            or win32process.GetWindowThreadProcessId(frame)[1] != process_id
        ):
            raise RuntimeError("SolidWorks 建模窗口不可用")
        thread, pid = win32process.GetWindowThreadProcessId(view)
        if pid != process_id:
            raise RuntimeError("建模窗口的进程不匹配")
        def verify_child(child, _):
            if win32gui.IsWindowVisible(child) and win32process.GetWindowThreadProcessId(child)[1] != process_id:
                raise RuntimeError("建模窗口含有其他进程的子窗口")
            return True

        win32gui.EnumChildWindows(view, verify_child, None)
        return frame, view, thread

    identity = window()
    if not _render_slot.acquire(blocking=False):
        raise RuntimeError("上一次 SolidWorks 窗口捕获尚未退出")
    result = Queue(maxsize=1)

    def render():
        try:
            _, view, thread = identity
            if tuple(win32process.GetWindowThreadProcessId(view)) != (thread, process_id):
                raise RuntimeError("建模窗口已变更")
            value = _render_window(view)
        except Exception as error:
            value = error
        finally:
            _render_slot.release()
        result.put(value)

    try:
        Thread(target=render, daemon=True).start()
    except Exception:
        _render_slot.release()
        raise
    # PrintWindow 是同步的。驱动或窗口挂起时只丢失预览，建模进程继续。
    image = result.get(timeout=1.5)
    if isinstance(image, Exception):
        raise image
    if window() != identity:
        raise RuntimeError("SolidWorks 建模窗口已变更")
    return image


def _render_window(view):
    import ctypes
    from ctypes import wintypes
    import win32gui
    import win32ui
    from PIL import Image

    left, top, right, bottom = win32gui.GetWindowRect(view)
    width, height = right - left, bottom - top
    if min(width, height) < 1 or width * height > 16_777_216:
        raise RuntimeError("建模窗口尺寸超出预览限制")

    print_window = ctypes.windll.user32.PrintWindow
    print_window.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    print_window.restype = wintypes.BOOL
    paint_bitmap = ctypes.windll.gdi32.PatBlt
    paint_bitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
    paint_bitmap.restype = wintypes.BOOL
    window_dc = win32gui.GetWindowDC(view)
    try:
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, width, height)
            previous = memory.SelectObject(bitmap)
            try:
                dc = memory.GetSafeHdc()
                if not paint_bitmap(dc, 0, 0, width, height, 0x00000042):  # BLACKNESS
                    raise RuntimeError("SolidWorks 预览位图初始化失败")
                # PW_RENDERFULLCONTENT 请求 Windows 渲染该 HWND 自身的合成内容。
                # 不读取桌面像素，也不尝试其他 HWND。
                if not print_window(view, dc, 0x00000002):
                    raise RuntimeError("SolidWorks 建模窗口捕获失败")
                image = Image.frombytes("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
            finally:
                memory.SelectObject(previous)
        finally:
            memory.DeleteDC()
            if bitmap.GetHandle():
                win32gui.DeleteObject(bitmap.GetHandle())
    finally:
        win32gui.ReleaseDC(view, window_dc)
    if all(low == high for low, high in image.getextrema()):
        raise RuntimeError("SolidWorks 返回空白预览")
    image.thumbnail((960, 720), Image.Resampling.LANCZOS)
    return image
