"""@brief 只读枚举 SolidWorks PID 与可识别版本；无需新增依赖或守护进程。"""
import ctypes
from ctypes import wintypes
import os


def solidworks_processes():
    """@brief 返回 PID→年份；枚举失败返回 None，避免猜测进程所有权。"""
    if os.name != "nt":
        return None

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
            ("name", wintypes.WCHAR * 260)]

    api = ctypes.windll.kernel32
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    result = {}
    entry = Entry()
    entry.dwSize = ctypes.sizeof(Entry)
    try:
        valid = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            if entry.name.casefold() == "sldworks.exe":
                year = None
                handle = api.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if api.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            import win32api
                            version = win32api.GetFileVersionInfo(buffer.value, "\\")
                            major = version["FileVersionMS"] >> 16
                            year = major if 2000 <= major <= 2035 else major + 1992 if 18 <= major <= 43 else None
                    except Exception:
                        pass
                    finally:
                        api.CloseHandle(handle)
                result[int(entry.pid)] = year
            valid = api.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return result
