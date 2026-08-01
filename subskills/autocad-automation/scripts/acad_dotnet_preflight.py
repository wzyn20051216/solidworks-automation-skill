"""AutoCAD 混合后端前置检查。

默认只读；只有显式 ``--install-sdk`` 时才调用 winget 安装 Microsoft .NET SDK。
Autodesk Managed API DLL 只从本机 AutoCAD 安装目录发现，不自动下载或复制。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
from cad_installation import discover_installation  # noqa: E402


def _find_managed_api(installation: dict[str, Any]) -> list[str]:
    """@brief 在 AutoCAD 安装目录中查找 Autodesk.AutoCAD.Managed DLL。"""
    executable = installation.get("executable")
    if not executable:
        return []
    root = Path(executable).resolve().parent
    names = ("acdbmgd.dll", "acmgd.dll", "Autodesk.AutoCAD.Interop.dll")
    return [str(path) for name in names for path in root.rglob(name) if path.is_file()]


def _sdk_info() -> dict[str, Any]:
    dotnet = shutil.which("dotnet") or shutil.which("dotnet.exe")
    sdk_versions: list[str] = []
    if dotnet:
        result = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True, check=False)
        sdk_versions = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    msbuild = shutil.which("msbuild") or shutil.which("MSBuild.exe")
    return {"dotnet": dotnet, "sdk_versions": sdk_versions, "msbuild": msbuild}


def _install_sdk() -> dict[str, Any]:
    winget = shutil.which("winget") or shutil.which("winget.exe")
    if not winget:
        return {"status": "blocked", "error_code": "WINGET_MISSING", "message": "未发现 winget，无法自动安装 .NET SDK"}
    command = [winget, "install", "--id", "Microsoft.DotNet.SDK.8", "--exact", "--source", "winget", "--accept-source-agreements", "--accept-package-agreements"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return {"status": "pass" if result.returncode == 0 else "failed", "command": command, "returncode": result.returncode, "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]}


def run_preflight(*, install_sdk: bool = False) -> dict[str, Any]:
    """@brief 返回四类 AutoCAD 后端的统一前置报告。"""
    installation = discover_installation("autocad")
    sdk = _sdk_info()
    install_result = _install_sdk() if install_sdk and not sdk["sdk_versions"] else None
    if install_result and install_result.get("status") == "pass":
        sdk = _sdk_info()
    managed_api = _find_managed_api(installation)
    writable = []
    for label, raw in (("temp", os.environ.get("TEMP", str(Path.cwd()))), ("output", str(Path.cwd() / "output"))):
        path = Path(raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".cad-studio-preflight"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable.append({"id": label, "status": "pass", "path": str(path)})
        except OSError as exc:
            writable.append({"id": label, "status": "blocked", "path": str(path), "error": str(exc)})
    dotnet_ready = bool(sdk["sdk_versions"])
    api_ready = bool(managed_api)
    return {
        "schemaVersion": "1.0",
        "platform": platform.platform(),
        "installation": installation,
        "sdk": sdk,
        "managed_api": {"paths": managed_api, "status": "pass" if api_ready else "blocked", "error_code": None if api_ready else "AUTOCAD_MANAGED_API_MISSING"},
        "writable": writable,
        "backends": {
            "dxf_headless": {"backend": "dxf_headless", "status": "pilot", "stage": "preflight", "artifacts": [], "limitations": ["只读 DXF"], "retryable": False},
            "autocad_com": {"backend": "autocad_com", "status": "blocked", "stage": "preflight", "artifacts": [], "limitations": ["当前 AutoCAD 2024 ActiveX 动态代理不稳定"], "retryable": True, "error_code": "AUTOCAD_COM_UNSTABLE"},
            "autocad_script": {"backend": "autocad_script", "status": "pilot", "stage": "preflight", "artifacts": [], "limitations": ["命令异步，必须保存后复核"], "retryable": True},
            "autocad_dotnet": {"backend": "autocad_dotnet", "status": "pilot" if dotnet_ready and api_ready else "blocked", "stage": "preflight", "artifacts": [], "limitations": [] if dotnet_ready and api_ready else ["需要 .NET SDK 和本机 Autodesk Managed API DLL"], "retryable": True, "error_code": None if dotnet_ready and api_ready else "AUTOCAD_DOTNET_PREREQUISITE_MISSING"},
        },
        "install_sdk": install_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoCAD 混合后端前置检查")
    parser.add_argument("--install-sdk", action="store_true", help="允许通过 winget 安装 Microsoft .NET SDK")
    args = parser.parse_args()
    report = run_preflight(install_sdk=args.install_sdk)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
