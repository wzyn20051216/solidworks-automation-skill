"""AutoCAD 混合后端前置检查。

默认只读；只有显式 ``--install-sdk`` 时才调用 winget 安装 Microsoft .NET SDK。
Autodesk Managed API DLL 只从本机 AutoCAD 安装目录发现，不自动下载或复制。
"""
from __future__ import annotations

import argparse
import hashlib
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

REQUIRED_MANAGED_DLLS = ("accoremgd.dll", "acdbmgd.dll", "acmgd.dll")
RUNTIME_REQUIRED_CHECKS = (
    "plugin_loaded",
    "command_executed",
    "dwg_saved",
    "dwg_reopened",
    "pdf_generated",
    "png_generated",
    "entities_checked",
    "layers_checked",
    "dimensions_checked",
)
DEFAULT_EVIDENCE_PATH = ROOT / "output" / "autocad-dotnet" / "latest-report.json"
REQUIRED_ARTIFACT_SUFFIXES = (".dll", ".dwg", ".pdf", ".png")


def _find_managed_api(installation: dict[str, Any]) -> list[str]:
    """@brief 在 AutoCAD 安装目录中查找 Autodesk.AutoCAD.Managed DLL。"""
    executable = installation.get("executable")
    if not executable:
        return []
    root = Path(executable).resolve().parent
    names = (*REQUIRED_MANAGED_DLLS, "Autodesk.AutoCAD.Interop.dll")
    return [str(path) for name in names for path in root.rglob(name) if path.is_file()]


def _sdk_info() -> dict[str, Any]:
    fixed_dotnet = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "dotnet.exe"
    user_dotnet = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "dotnet" / "dotnet.exe"
    candidates = [shutil.which("dotnet"), shutil.which("dotnet.exe"), str(user_dotnet), str(fixed_dotnet)]
    dotnet = None
    sdk_versions: list[str] = []
    for candidate in dict.fromkeys(item for item in candidates if item):
        if not Path(candidate).is_file():
            continue
        result = subprocess.run([candidate, "--list-sdks"], capture_output=True, text=True, check=False)
        versions = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if dotnet is None or versions:
            dotnet = candidate
            sdk_versions = versions
        if versions:
            break
    msbuild = shutil.which("msbuild") or shutil.which("MSBuild.exe")
    return {"dotnet": dotnet, "sdk_versions": sdk_versions, "msbuild": msbuild}


def _runtime_evidence(path: Path) -> dict[str, Any]:
    """@brief 校验真机回归证据；前置存在不代表插件已可用。"""
    if not path.is_file():
        return {"status": "blocked", "path": str(path), "error_code": "AUTOCAD_DOTNET_RUNTIME_NOT_VERIFIED", "checks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "path": str(path), "error_code": "AUTOCAD_DOTNET_EVIDENCE_INVALID", "error": str(exc), "checks": {}}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    missing = [check for check in RUNTIME_REQUIRED_CHECKS if checks.get(check) is not True]
    ledger = payload.get("artifactLedger") if isinstance(payload.get("artifactLedger"), list) else []
    ledger_by_suffix: dict[str, dict[str, Any]] = {}
    artifact_errors: list[str] = []
    evidence_root = path.resolve().parent
    for item in ledger:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        artifact = Path(str(item["path"])).resolve()
        try:
            artifact.relative_to(evidence_root)
        except ValueError:
            artifact_errors.append(f"产物不在证据目录内: {artifact}")
            continue
        suffix = artifact.suffix.lower()
        ledger_by_suffix[suffix] = item
        if not artifact.is_file() or artifact.stat().st_size != item.get("size"):
            artifact_errors.append(f"产物缺失或大小变化: {artifact}")
            continue
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != item.get("sha256"):
            artifact_errors.append(f"产物 SHA-256 变化: {artifact}")
    missing_artifacts = [suffix for suffix in REQUIRED_ARTIFACT_SUFFIXES if suffix not in ledger_by_suffix]
    passed = (
        payload.get("backend") == "autocad_dotnet"
        and payload.get("status") == "pass"
        and not missing
        and not missing_artifacts
        and not artifact_errors
    )
    return {
        "status": "pass" if passed else "blocked",
        "path": str(path),
        "error_code": None if passed else "AUTOCAD_DOTNET_RUNTIME_NOT_VERIFIED",
        "checks": checks,
        "missing_checks": missing,
        "missing_artifacts": missing_artifacts,
        "artifact_errors": artifact_errors,
    }


def _install_sdk() -> dict[str, Any]:
    winget = shutil.which("winget") or shutil.which("winget.exe")
    if not winget:
        return {"status": "blocked", "error_code": "WINGET_MISSING", "message": "未发现 winget，无法自动安装 .NET SDK"}
    command = [winget, "install", "--id", "Microsoft.DotNet.SDK.8", "--exact", "--source", "winget", "--accept-source-agreements", "--accept-package-agreements"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return {"status": "pass" if result.returncode == 0 else "failed", "command": command, "returncode": result.returncode, "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]}


def run_preflight(*, install_sdk: bool = False, evidence_path: Path | None = None) -> dict[str, Any]:
    """@brief 返回四类 AutoCAD 后端的统一前置报告。"""
    installation = discover_installation("autocad")
    sdk = _sdk_info()
    install_result = _install_sdk() if install_sdk and not sdk["sdk_versions"] else None
    if install_result and install_result.get("status") == "pass":
        sdk = _sdk_info()
    managed_api = _find_managed_api(installation)
    managed_names = {Path(path).name.lower() for path in managed_api}
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
    missing_managed_api = [name for name in REQUIRED_MANAGED_DLLS if name not in managed_names]
    api_ready = not missing_managed_api
    evidence = _runtime_evidence(evidence_path or DEFAULT_EVIDENCE_PATH)
    runtime_ready = evidence["status"] == "pass"
    dotnet_status = "pilot" if dotnet_ready and api_ready and runtime_ready else "blocked"
    if not dotnet_ready or not api_ready:
        dotnet_error = "AUTOCAD_DOTNET_PREREQUISITE_MISSING"
        dotnet_stage = "preflight"
    else:
        dotnet_error = None if runtime_ready else evidence.get("error_code")
        dotnet_stage = "review" if runtime_ready else "load"
    return {
        "schemaVersion": "1.0",
        "platform": platform.platform(),
        "installation": installation,
        "sdk": sdk,
        "managed_api": {"paths": managed_api, "status": "pass" if api_ready else "blocked", "missing": missing_managed_api, "error_code": None if api_ready else "AUTOCAD_MANAGED_API_MISSING"},
        "runtime_evidence": evidence,
        "writable": writable,
        "backends": {
            "dxf_headless": {"backend": "dxf_headless", "status": "pilot", "stage": "preflight", "artifacts": [], "limitations": ["只读 DXF"], "retryable": False},
            "autocad_com": {"backend": "autocad_com", "status": "blocked", "stage": "preflight", "artifacts": [], "limitations": ["当前 AutoCAD 2024 ActiveX 动态代理不稳定"], "retryable": True, "error_code": "AUTOCAD_COM_UNSTABLE"},
            "autocad_script": {"backend": "autocad_script", "status": "pilot", "stage": "preflight", "artifacts": [], "limitations": ["命令异步，必须保存后复核"], "retryable": True},
            "autocad_dotnet": {
                "backend": "autocad_dotnet",
                "status": dotnet_status,
                "stage": dotnet_stage,
                "artifacts": [str(evidence_path or DEFAULT_EVIDENCE_PATH)] if runtime_ready else [],
                "limitations": [] if runtime_ready else ["需要 .NET SDK、本机 Autodesk Managed API DLL，并通过 NETLOAD、DWG 重开、PDF/PNG 和实体复核"],
                "retryable": True,
                "error_code": dotnet_error,
            },
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
