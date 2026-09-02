"""@brief SolidWorks C# Add-in 宿主的只读部署与运行状态探测。"""
from __future__ import annotations

import json
import argparse
import os
import platform
import sys
from pathlib import Path
from typing import Any


ADDIN_GUID = "{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSEMBLY = (
    ROOT
    / "dotnet"
    / "CadStudio.SolidWorks.AddinHost"
    / "bin"
    / "Release"
    / "net48"
    / "CadStudio.SolidWorks.AddinHost.dll"
)


def _registry_key_exists(root: Any, path: str) -> bool:
    """@brief 使用 64 位注册表视图判断精确键是否存在。"""
    try:
        import winreg

        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except (FileNotFoundError, OSError):
        return False


def _read_diagnostics() -> tuple[Path, dict[str, Any] | None, str | None]:
    """@brief 回读 Add-in 生成的诊断 JSON，不把陈旧文件误判为当前连接。"""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    path = Path(local_app_data) / "CAD Studio" / "SolidWorksAddin" / "host-status.json"
    if not path.is_file():
        return path, None, None
    try:
        return path, json.loads(path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, OSError) as exc:
        return path, None, str(exc)


def _process_is_running(process_id: int) -> bool:
    """@brief 用 Windows 查询权限句柄判断诊断所述宿主进程是否仍存在。"""
    if process_id <= 0:
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except (AttributeError, OSError, ValueError):
        return False


def probe_addin_host(assembly_path: str | Path | None = None) -> dict[str, Any]:
    """@brief 返回构建产物、注册层级、进程内连接和阻塞原因。"""
    assembly = Path(assembly_path).expanduser().resolve() if assembly_path else DEFAULT_ASSEMBLY.resolve()
    if platform.system() != "Windows":
        return {
            "status": "unavailable",
            "error_code": "WINDOWS_REQUIRED",
            "assembly": str(assembly),
        }

    import winreg

    clsid_path = rf"Software\Classes\CLSID\{ADDIN_GUID}\InprocServer32"
    addin_path = rf"SOFTWARE\SOLIDWORKS\Addins\{ADDIN_GUID}"
    startup_path = rf"Software\SOLIDWORKS\AddInsStartup\{ADDIN_GUID}"
    current_user_com = _registry_key_exists(winreg.HKEY_CURRENT_USER, clsid_path)
    machine_com = _registry_key_exists(winreg.HKEY_LOCAL_MACHINE, clsid_path)
    machine_discovery = _registry_key_exists(winreg.HKEY_LOCAL_MACHINE, addin_path)
    startup_enabled = _registry_key_exists(winreg.HKEY_CURRENT_USER, startup_path)
    diagnostic_path, diagnostics, diagnostic_error = _read_diagnostics()
    connected = bool(diagnostics and diagnostics.get("status") == "connected")
    host_process_id = int((diagnostics or {}).get("hostProcessId") or 0)
    host_process_name = str((diagnostics or {}).get("hostProcessName") or "")
    in_process_host = bool(
        connected
        and host_process_name.casefold() == "sldworks"
        and _process_is_running(host_process_id)
    )
    ui_ready = bool(
        in_process_host
        and diagnostics.get("callbackRegistered") is True
        and diagnostics.get("commandGroupReady") is True
        and diagnostics.get("taskPaneReady") is True
        and diagnostics.get("propertyManagerPageReady") is True
    )

    blockers: list[dict[str, str]] = []
    if not assembly.is_file():
        blockers.append({"code": "ASSEMBLY_MISSING", "message": "先构建 net48 x64 Add-in 程序集。"})
    if not machine_discovery:
        blockers.append({
            "code": "HKLM_ADDIN_REGISTRATION_MISSING",
            "message": "SolidWorks 进程内发现需要提升权限执行 Machine 注册；当前用户 COM 注册只用于激活冒烟测试。",
        })
    if machine_discovery and not connected:
        blockers.append({"code": "ADDIN_NOT_CONNECTED", "message": "注册存在，但诊断未显示 ConnectToSW 已连接。"})
    if connected and not in_process_host:
        blockers.append({"code": "DIAGNOSTIC_NOT_IN_PROCESS", "message": "诊断并非由仍在运行的 SLDWORKS.exe 进程写出，不能作为 Add-in 真机证据。"})
    if connected and not ui_ready:
        blockers.append({"code": "ADDIN_UI_NOT_READY", "message": "Add-in 已进入连接流程，但回调或 UI 子系统未全部就绪。"})
    if diagnostic_error:
        blockers.append({"code": "DIAGNOSTIC_JSON_INVALID", "message": diagnostic_error})

    return {
        "status": "ready" if ui_ready and not blockers else "blocked",
        "capability_level": "pilot",
        "addin_guid": ADDIN_GUID,
        "assembly": str(assembly),
        "assembly_exists": assembly.is_file(),
        "assembly_bytes": assembly.stat().st_size if assembly.is_file() else 0,
        "current_user_com_registered": current_user_com,
        "machine_com_registered": machine_com,
        "machine_solidworks_discovery_registered": machine_discovery,
        "startup_enabled": startup_enabled,
        "diagnostic_path": str(diagnostic_path),
        "diagnostics": diagnostics,
        "in_process_host": in_process_host,
        "ui_ready": ui_ready,
        "blockers": blockers,
        "review_required": True,
    }


def main() -> int:
    """@brief 命令行输出只读状态，可选保存为回归证据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = probe_addin_host(args.assembly)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if payload["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
