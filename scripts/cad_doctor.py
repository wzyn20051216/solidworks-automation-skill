"""CAD Studio 环境诊断 CLI。

该脚本只读取环境信息，不启动或关闭 CAD。输出适合桌面端和 CI 消费的 JSON，
并用稳定的检查 ID/状态帮助用户定位安装、依赖和权限问题。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _check(name: str, ok: bool, message: str, *, severity: str = "error", code: str | None = None) -> dict[str, Any]:
    return {"id": name, "status": "passed" if ok else severity, "code": code or name.upper(), "message": message}


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".cad-studio-doctor-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _solidworks_installation() -> dict[str, Any]:
    result: dict[str, Any] = {"registered": False, "executables": []}
    if os.name != "nt":
        return result
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID"):
            result["registered"] = True
    except OSError:
        pass
    patterns = [
        r"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\SLDWORKS.exe",
        r"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS*\\SLDWORKS.exe",
        r"C:\\Program Files\\Dassault Systemes\\SOLIDWORKS*\\SLDWORKS.exe",
    ]
    for pattern in patterns:
        result["executables"].extend(path for path in glob.glob(pattern) if Path(path).is_file())
    return result


def run_doctor(*, probe_cad: bool = False) -> dict[str, Any]:
    """执行诊断并返回脱敏 JSON 数据。"""
    checks: list[dict[str, Any]] = []
    checks.append(_check("python", sys.version_info >= (3, 10), f"Python {platform.python_version()}"))
    for module_name, label in (("win32com.client", "pywin32"), ("comtypes", "comtypes"), ("ezdxf", "ezdxf")):
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError):
            available = False
        severity = "warning" if module_name == "ezdxf" else "error"
        checks.append(_check(f"python.{label}", available, f"{label} {'已安装' if available else '未安装'}", severity=severity, code="DEPENDENCY_MISSING" if not available else None))
    for cli in ("codex", "claude", "gemini", "opencode"):
        found = shutil.which(cli) or shutil.which(f"{cli}.exe")
        checks.append(_check(f"agent.{cli}", bool(found), f"{cli}: {'已发现' if found else '未发现'}", severity="warning", code="AGENT_NOT_FOUND" if not found else None))

    sw = _solidworks_installation()
    sw_ready = bool(sw["registered"] or sw["executables"])
    checks.append(_check("cad.solidworks", sw_ready, "SolidWorks COM 或安装目录已发现" if sw_ready else "未发现 SolidWorks COM 注册或安装目录", code="SOLIDWORKS_READY" if sw_ready else "SOLIDWORKS_NOT_FOUND"))
    autocad_ready = bool(shutil.which("acad.exe"))
    checks.append(_check("cad.autocad", autocad_ready, "AutoCAD 可执行文件已在 PATH" if autocad_ready else "未在 PATH 发现 acad.exe", severity="warning", code="AUTOCAD_READY" if autocad_ready else "AUTOCAD_NOT_FOUND"))

    documents = Path.home() / "Documents"
    checks.append(_check("filesystem.documents", _is_writable(documents), f"文档目录可写: {documents.name}", code="DOCUMENTS_NOT_WRITABLE"))
    checks.append(_check("filesystem.temp", _is_writable(Path(os.environ.get("TEMP", str(Path.home())))), "临时目录可写", code="TEMP_NOT_WRITABLE"))

    if probe_cad and sw["registered"]:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from sw_connect import connect_solidworks

            app, _ = connect_solidworks(wait_seconds=8, visible=False)
            checks.append(_check("cad.solidworks.com", app is not None, "SolidWorks COM 连接成功", code="SOLIDWORKS_COM_FAILED"))
        except Exception as exc:  # pragma: no cover - 真实 Windows 环境执行
            checks.append(_check("cad.solidworks.com", False, str(exc), code="SOLIDWORKS_COM_FAILED"))

    errors = sum(item["status"] == "error" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    return {
        "schemaVersion": "1.0",
        "tool": "cad-studio doctor",
        "platform": platform.platform(aliased=True),
        "python": {"version": platform.python_version(), "executable": Path(sys.executable).name},
        "checks": checks,
        "summary": {"status": "error" if errors else ("warning" if warnings else "passed"), "errors": errors, "warnings": warnings},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="诊断 CAD Studio 本地运行环境")
    parser.add_argument("--probe-cad", action="store_true", help="在 COM 已注册时尝试连接 SolidWorks")
    parser.add_argument("--output", type=Path, help="写入 JSON 文件")
    args = parser.parse_args(argv)
    result = run_doctor(probe_cad=args.probe_cad)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if result["summary"]["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
