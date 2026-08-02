"""CAD Studio 本机 CAD 安装发现。

该模块只读检查快捷方式、常见安装目录和 COM 注册，不启动或关闭 CAD。
路径发现结果供 CLI、Skill 自检和桌面端复用；调用方负责脱敏后再上传诊断包。
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


PUBLIC_DESKTOP = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
SHORTCUTS = {
    "solidworks": PUBLIC_DESKTOP / "SOLIDWORKS 2024.lnk",
    "autocad": PUBLIC_DESKTOP / "AutoCAD 2024 - 简体中文 (Simplified Chinese).lnk",
}
SHORTCUT_PATTERNS = {
    "solidworks": ("SOLIDWORKS*.lnk",),
    "autocad": ("AutoCAD*.lnk",),
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


def _shortcut_paths(product: str) -> list[Path]:
    """@brief 枚举产品的全部公共桌面快捷方式，不把版本固定为 2024。"""
    paths = [SHORTCUTS[product]]
    if PUBLIC_DESKTOP.is_dir():
        for pattern in SHORTCUT_PATTERNS[product]:
            paths.extend(PUBLIC_DESKTOP.glob(pattern))
    return _unique_paths(paths)


def _version_metadata(*values: object) -> tuple[str | None, str | None]:
    """@brief 从显示名、路径或文件版本文本中提取年份与 Service Pack。"""
    text = " ".join(str(value or "") for value in values)
    version_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    service_pack_match = re.search(r"\bSP\s*0?(\d+)(?:[._](\d+))?\b", text, re.IGNORECASE)
    service_pack = None
    if service_pack_match:
        service_pack = f"SP{int(service_pack_match.group(1)):02d}"
        if service_pack_match.group(2) is not None:
            service_pack += f".{int(service_pack_match.group(2))}"
    return (version_match.group(1) if version_match else None, service_pack)


def _uninstall_registry_candidates(product: str) -> list[dict[str, Any]]:
    """@brief 从 Windows 卸载注册表读取主 CAD 产品的真实安装目录。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    executable_name = "SLDWORKS.exe" if product == "solidworks" else "acad.exe"
    product_pattern = (
        re.compile(r"^SOLIDWORKS\s+20\d{2}(?:\s+SP\s*[\d.]+)?$", re.IGNORECASE)
        if product == "solidworks"
        else re.compile(r"^AutoCAD\s+20\d{2}(?:\s+-.*)?$", re.IGNORECASE)
    )
    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    result: list[dict[str, Any]] = []
    for hive, root_name in roots:
        try:
            root = winreg.OpenKey(hive, root_name)
        except OSError:
            continue
        try:
            try:
                child_names = [winreg.EnumKey(root, index) for index in range(winreg.QueryInfoKey(root)[0])]
            except OSError:
                child_names = []
            for child_name in child_names:
                try:
                    child = winreg.OpenKey(root, child_name)
                except OSError:
                    continue
                try:
                    try:
                        display_name = str(winreg.QueryValueEx(child, "DisplayName")[0] or "")
                    except OSError:
                        continue
                    if not product_pattern.match(display_name.strip()):
                        continue
                    try:
                        install_location = str(winreg.QueryValueEx(child, "InstallLocation")[0] or "")
                    except OSError:
                        install_location = ""
                    if not install_location:
                        continue
                    version, service_pack = _version_metadata(display_name, install_location)
                    result.append({
                        "path": Path(install_location) / executable_name,
                        "source": "uninstall-registry",
                        "version": version,
                        "service_pack": service_pack,
                        "display_name": display_name,
                        "shortcut": None,
                    })
                finally:
                    winreg.CloseKey(child)
        finally:
            winreg.CloseKey(root)
    return result


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
            for pattern in (
                f"{drive}/Solidworks*/SOLIDWORKS*/{exe}",
                f"{drive}/SolidW*rks*/SOLIDWORKS*/{exe}",
                f"{drive}/SOLIDWORKS Corp/SOLIDWORKS*/{exe}",
            ):
                candidates.extend(Path(p) for p in glob.glob(pattern))
        else:
            candidates.extend([root / "AutoCAD 2024" / exe, root / "Autodesk" / "AutoCAD 2024" / exe])
            for pattern in (f"{drive}/AutoCAD*/{exe}", f"{drive}/Autodesk/AutoCAD*/{exe}"):
                candidates.extend(Path(p) for p in glob.glob(pattern))
    return candidates


def discover_installations(product: str, *, exists: Callable[[Path], bool] | None = None) -> list[dict[str, Any]]:
    """@brief 发现产品的全部安装，并按版本从新到旧排序。"""
    if product not in {"solidworks", "autocad"}:
        raise ValueError(f"不支持的 CAD 产品: {product}")
    exists = exists or Path.is_file
    exe_name = "SLDWORKS.exe" if product == "solidworks" else "acad.exe"
    candidates: list[dict[str, Any]] = []
    for shortcut in _shortcut_paths(product):
        target, workdir = _shortcut_info(shortcut)
        version, service_pack = _version_metadata(shortcut.name, target, workdir)
        candidates.extend({
            "path": path,
            "source": "shortcut",
            "version": version,
            "service_pack": service_pack,
            "display_name": shortcut.stem,
            "shortcut": str(shortcut),
        } for path in resolve_shortcut_target(target, workdir, exe_name))
    candidates.extend(_uninstall_registry_candidates(product))
    candidates.extend({
        "path": path,
        "source": "registry",
        "version": _version_metadata(path)[0],
        "service_pack": _version_metadata(path)[1],
        "display_name": None,
        "shortcut": None,
    } for path in _registry_paths(product))
    candidates.extend({
        "path": path,
        "source": "common-path",
        "version": _version_metadata(path)[0],
        "service_pack": _version_metadata(path)[1],
        "display_name": None,
        "shortcut": None,
    } for path in _common_candidates(product))

    source_priority = {"uninstall-registry": 4, "shortcut": 3, "registry": 2, "common-path": 1}
    candidates.sort(
        key=lambda item: (
            int(item["version"]) if str(item.get("version") or "").isdigit() else 0,
            source_priority.get(str(item.get("source")), 0),
        ),
        reverse=True,
    )
    installed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = Path(candidate["path"])
        if not exists(path):
            continue
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        version = candidate.get("version") or _version_metadata(path)[0]
        installed.append({
            "product": product,
            "installed": True,
            "executable": str(path),
            "source": candidate["source"],
            "version": version,
            "servicePack": candidate.get("service_pack"),
            "displayName": candidate.get("display_name"),
            "shortcut": candidate.get("shortcut"),
            "registered": _com_registered(product),
        })

    installed.sort(
        key=lambda item: (
            int(item["version"]) if str(item.get("version") or "").isdigit() else 0,
            source_priority.get(str(item.get("source")), 0),
        ),
        reverse=True,
    )
    return installed


def discover_installation(product: str, *, exists: Callable[[Path], bool] | None = None) -> dict:
    """@brief 返回最新安装，保持旧调用方的单结果接口兼容。"""
    installations = discover_installations(product, exists=exists)
    if installations:
        return installations[0]
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
