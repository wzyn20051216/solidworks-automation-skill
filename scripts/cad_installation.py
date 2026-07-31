"""CAD Studio 本机 CAD 安装发现。

该模块只读检查快捷方式、常见安装目录和 COM 注册，不启动或关闭 CAD。
路径发现结果供 CLI、Skill 自检和桌面端复用；调用方负责脱敏后再上传诊断包。
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Callable, Iterable, Mapping


PUBLIC_DESKTOP = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
SHORTCUTS = {
    "solidworks": PUBLIC_DESKTOP / "SOLIDWORKS 2024.lnk",
    "autocad": PUBLIC_DESKTOP / "AutoCAD 2024 - 简体中文 (Simplified Chinese).lnk",
}


def resolve_shortcut_target(target: str | None, working_directory: str | None, executable_name: str) -> list[Path]:
    """把 Windows 快捷方式的目标和工作目录转换成可验证的 exe 候选。

    安装器快捷方式有时目标不是最终程序（例如 i386_SldWorks.exe），此时优先
    从工作目录补出真正的 SLDWORKS.exe，避免把安装器误当作 CAD 主程序。
    """
    candidates: list[Path] = []
    target_path = Path(target) if target else None
    if target_path and target_path.name.lower() == executable_name.lower():
        candidates.append(target_path)
    work_path = Path(working_directory) if working_directory else None
    if work_path:
        candidates.append(work_path / executable_name)
    if target_path and target_path.parent:
        candidates.append(target_path.parent / executable_name)
    return _unique_paths(candidates)


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.normpath(str(path)))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _shortcut_info(path: Path) -> tuple[str | None, str | None]:
    """读取 .lnk；没有 pywin32 或非 Windows 时安静失败。"""
    if not path.is_file() or os.name != "nt":
        return None, None
    try:
        import win32com.client  # type: ignore

        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
        return str(shortcut.TargetPath or ""), str(shortcut.WorkingDirectory or "")
    except Exception:
        return None, None


def _registry_paths(product: str) -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    roots = {
        "solidworks": [r"SOFTWARE\SolidWorks", r"SOFTWARE\WOW6432Node\SolidWorks"],
        "autocad": [r"SOFTWARE\Autodesk\AutoCAD", r"SOFTWARE\WOW6432Node\Autodesk\AutoCAD"],
    }[product]
    values = {"solidworks": {"InstallDir", "Location", "Path"}, "autocad": {"AcadLocation", "InstallDir", "Location", "Path"}}[product]
    result: list[Path] = []

    def walk(key, depth: int) -> None:
        for name in values:
            try:
                value, _ = winreg.QueryValueEx(key, name)
            except OSError:
                continue
            path = Path(str(value))
            result.append(path if path.suffix.lower() == ".exe" else path / ("SLDWORKS.exe" if product == "solidworks" else "acad.exe"))
        if depth <= 0:
            return
        try:
            names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        except OSError:
            names = []
        for name in names:
            try:
                child = winreg.OpenKey(key, name)
            except OSError:
                continue
            try:
                walk(child, depth - 1)
            finally:
                winreg.CloseKey(child)

    for root in roots:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
        except OSError:
            continue
        try:
            walk(key, 3)
        finally:
            winreg.CloseKey(key)
    return result


def _common_candidates(product: str) -> list[Path]:
    exe = "SLDWORKS.exe" if product == "solidworks" else "acad.exe"
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SOLIDWORKS Corp" / "SOLIDWORKS" / exe,
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk" / "AutoCAD 2024" / exe,
    ]
    for drive in ("D:", "E:"):
        root = Path(drive)
        if product == "solidworks":
            candidates.extend([
                root / "Solidworks" / "SOLIDWORKS" / exe,
                root / "SOLIDWORKS Corp" / "SOLIDWORKS" / exe,
            ])
            for pattern in (f"{drive}/Solidworks*/SOLIDWORKS*/{exe}", f"{drive}/SOLIDWORKS Corp/SOLIDWORKS*/{exe}"):
                candidates.extend(Path(p) for p in glob.glob(pattern))
        else:
            candidates.extend([root / "AutoCAD 2024" / exe, root / "Autodesk" / "AutoCAD 2024" / exe])
            for pattern in (f"{drive}/AutoCAD*/{exe}", f"{drive}/Autodesk/AutoCAD*/{exe}"):
                candidates.extend(Path(p) for p in glob.glob(pattern))
    return candidates


def discover_installation(product: str, *, exists: Callable[[Path], bool] | None = None) -> dict:
    """发现一个产品，返回 exe、来源、版本和 COM 注册状态。"""
    if product not in {"solidworks", "autocad"}:
        raise ValueError(f"不支持的 CAD 产品: {product}")
    exists = exists or Path.is_file
    exe_name = "SLDWORKS.exe" if product == "solidworks" else "acad.exe"
    candidates: list[tuple[Path, str]] = []
    shortcut = SHORTCUTS[product]
    target, workdir = _shortcut_info(shortcut)
    candidates.extend((path, "shortcut") for path in resolve_shortcut_target(target, workdir, exe_name))
    candidates.extend((path, "registry") for path in _registry_paths(product))
    candidates.extend((path, "common-path") for path in _common_candidates(product))
    for path, source in candidates:
        if exists(path):
            text = str(path)
            match = re.search(r"(?:20\d{2}|v?\d{2,3})", f"{text} {shortcut.name}", re.IGNORECASE)
            return {
                "product": product,
                "installed": True,
                "executable": text,
                "source": source,
                "version": match.group(0) if match else None,
                "shortcut": str(shortcut) if shortcut.is_file() else None,
                "registered": _com_registered(product),
            }
    return {"product": product, "installed": False, "executable": None, "source": None, "version": None, "shortcut": None, "registered": _com_registered(product)}


def _com_registered(product: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        progid = "SldWorks.Application" if product == "solidworks" else "AutoCAD.Application"
        winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, f"{progid}\\CLSID")
        return True
    except Exception:
        return False


def discover_all() -> Mapping[str, dict]:
    return {product: discover_installation(product) for product in ("solidworks", "autocad")}
