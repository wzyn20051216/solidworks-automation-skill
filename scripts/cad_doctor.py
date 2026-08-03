"""CAD Studio 环境诊断 CLI。

该脚本只读取环境信息，不启动或关闭 CAD。输出适合桌面端和 CI 消费的 JSON，
并用稳定的检查 ID/状态帮助用户定位安装、依赖和权限问题。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from cad_installation import discover_all, discover_installations


_AGENT_DOWNLOADS = {
    "codex": "https://developers.openai.com/codex/cli/",
    "claude": "https://docs.anthropic.com/en/docs/claude-code/overview",
    "gemini": "https://github.com/google-gemini/gemini-cli",
    "opencode": "https://opencode.ai/",
}


def _check(
    name: str,
    ok: bool,
    message: str,
    *,
    severity: str = "error",
    code: str | None = None,
    action: str | None = None,
    install_command: str | None = None,
    download_url: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    """@brief 构造稳定检查项，并在失败时附带可执行修复信息。"""
    result: dict[str, Any] = {
        "id": name,
        "status": "passed" if ok else severity,
        "code": code or name.upper(),
        "message": message,
    }
    if not ok:
        if action:
            result["action"] = action
        if install_command:
            result["installCommand"] = install_command
        if download_url:
            result["downloadUrl"] = download_url
        result["required"] = required
    return result


def _collect_remediations(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """@brief 将失败检查转换为去重后的桌面端/CLI 修复动作。"""
    remediations: list[dict[str, Any]] = []
    seen: set[str] = set()
    agent_available = any(
        item["id"].startswith("agent.") and item["status"] == "passed"
        for item in checks
    )
    for item in checks:
        if item["status"] == "passed" or not item.get("action"):
            continue
        # Agent CLI 是可替代关系；只要发现一个，就不提示安装其余 Provider。
        if agent_available and item["id"].startswith("agent."):
            continue
        remediation_id = str(item["id"])
        if remediation_id in seen:
            continue
        seen.add(remediation_id)
        remediation = {
            "id": remediation_id,
            "title": item["action"],
            "reason": item["message"],
            "required": bool(item.get("required", False)),
        }
        for source, target in (("installCommand", "installCommand"), ("downloadUrl", "downloadUrl")):
            if item.get(source):
                remediation[target] = item[source]
        remediations.append(remediation)
    return remediations


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
    installation = discover_all()["solidworks"]
    available = discover_installations("solidworks")
    return {
        "registered": installation["registered"],
        "executables": [installation["executable"]] if installation["executable"] else [],
        "executable": installation["executable"],
        "source": installation["source"],
        "version": installation["version"],
        "servicePack": installation.get("servicePack"),
        "displayName": installation.get("displayName"),
        "shortcut": installation["shortcut"],
        "available": available,
    }


def run_doctor(*, probe_cad: bool = False) -> dict[str, Any]:
    """执行诊断并返回脱敏 JSON 数据。"""
    checks: list[dict[str, Any]] = []
    python_ready = sys.version_info >= (3, 10)
    checks.append(_check(
        "python",
        python_ready,
        f"Python {platform.python_version()}" if python_ready else f"Python {platform.python_version()} 低于推荐的 3.10",
        code="PYTHON_VERSION_UNSUPPORTED" if not python_ready else "PYTHON_READY",
        action="安装 Python 3.10 或更高版本",
        install_command="winget install -e --id Python.Python.3.12",
        download_url="https://www.python.org/downloads/windows/",
        required=True,
    ))
    dependencies = (
        (("win32com.client",), "pywin32", "warning", "安装 SolidWorks COM 自动化依赖", 'python -m pip install "pywin32>=305"', "https://pypi.org/project/pywin32/"),
        (("comtypes",), "comtypes", "warning", "安装 Windows COM 兼容依赖", 'python -m pip install "comtypes>=1.2.0"', "https://pypi.org/project/comtypes/"),
        (("ezdxf",), "ezdxf", "warning", "安装 DXF 无头读写依赖", 'python -m pip install "ezdxf>=1.3,<2"', "https://pypi.org/project/ezdxf/"),
        (("OCP",), "OCP", "warning", "安装 OCCT 开放格式几何后端", "python -m pip install -r requirements-occt.txt", "https://pypi.org/project/cadquery-ocp/"),
        (("fitz", "pymupdf"), "PyMuPDF", "warning", "安装 PDF 预览与文字复核依赖", "python -m pip install -r requirements-pdf.txt", "https://pymupdf.readthedocs.io/en/latest/installation.html"),
    )
    for module_names, label, severity, action, install_command, download_url in dependencies:
        available = False
        for module_name in module_names:
            try:
                available = available or importlib.util.find_spec(module_name) is not None
            except (ImportError, ModuleNotFoundError):
                continue
        checks.append(_check(
            f"python.{label.lower()}",
            available,
            f"{label} {'已安装' if available else '未安装；仅影响对应能力，其余后端仍可使用'}",
            severity=severity,
            code="DEPENDENCY_MISSING" if not available else "DEPENDENCY_READY",
            action=action,
            install_command=install_command,
            download_url=download_url,
        ))

    try:
        from fea_analysis import discover_solver

        calculix = discover_solver("calculix")
        calculix_ready = calculix.get("status") == "pass"
    except Exception:
        calculix_ready = False
    checks.append(_check(
        "solver.calculix",
        calculix_ready,
        "CalculiX 已发现" if calculix_ready else "未发现 CalculiX；仅阻断开放 FEA 求解，不影响建模、图纸和预览",
        severity="warning",
        code="CALCULIX_READY" if calculix_ready else "CALCULIX_NOT_FOUND",
        action="下载 CalculiX，并设置 CADSTUDIO_CALCULIX_EXE 指向 ccx.exe",
        download_url="https://www.calculix.de/",
    ))

    for cli in ("codex", "claude", "gemini", "opencode"):
        found = shutil.which(cli) or shutil.which(f"{cli}.exe")
        checks.append(_check(
            f"agent.{cli}",
            bool(found),
            f"{cli}: {'已发现' if found else '未发现；安装任意一个受支持的 Agent CLI 即可'}",
            severity="warning",
            code="AGENT_NOT_FOUND" if not found else "AGENT_READY",
            action=f"安装 {cli} CLI",
            download_url=_AGENT_DOWNLOADS[cli],
        ))

    sw = _solidworks_installation()
    sw_ready = bool(sw["registered"] or sw["executables"])
    checks.append(_check(
        "cad.solidworks",
        sw_ready,
        "SolidWorks COM 或安装目录已发现" if sw_ready else "未发现 SolidWorks；仅阻断 SLDPRT/SLDASM/SLDDRW 原生格式，STEP/IGES/BREP/STL/GLB 等开放格式仍可使用",
        severity="warning",
        code="SOLIDWORKS_READY" if sw_ready else "SOLIDWORKS_NOT_FOUND",
        action="需要 SolidWorks 原生格式时，从官方渠道安装并完成授权",
        download_url="https://www.solidworks.com/",
    ))
    autocad = discover_all()["autocad"]
    autocad_ready = bool(autocad["installed"])
    checks.append(_check(
        "cad.autocad",
        autocad_ready,
        "AutoCAD 安装已发现" if autocad_ready else "未发现 AutoCAD；仅阻断原生 DWG 后端，DXF/SVG/PDF/PNG 无头交付仍可使用",
        severity="warning",
        code="AUTOCAD_READY" if autocad_ready else "AUTOCAD_NOT_FOUND",
        action="需要原生 DWG 时，从 Autodesk 官方渠道安装并完成授权",
        download_url="https://www.autodesk.com/products/autocad/overview",
    ))

    documents = Path.home() / "Documents"
    documents_writable = _is_writable(documents)
    checks.append(_check(
        "filesystem.documents",
        documents_writable,
        f"文档目录可写: {documents.name}",
        code="DOCUMENTS_READY" if documents_writable else "DOCUMENTS_NOT_WRITABLE",
        action="为文档目录授予当前用户写入权限，或在 CAD Studio 中选择其他输出目录",
        required=True,
    ))
    temp_writable = _is_writable(Path(os.environ.get("TEMP", str(Path.home()))))
    checks.append(_check(
        "filesystem.temp",
        temp_writable,
        "临时目录可写",
        code="TEMP_READY" if temp_writable else "TEMP_NOT_WRITABLE",
        action="修复当前用户临时目录权限后重新诊断",
        required=True,
    ))

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
    remediations = _collect_remediations(checks)
    return {
        "schemaVersion": "1.0",
        "tool": "cad-studio doctor",
        "platform": platform.platform(aliased=True),
        "python": {"version": platform.python_version(), "executable": Path(sys.executable).name},
        "installations": {
            "solidworks": {key: value for key, value in sw.items() if key != "executables"},
            "autocad": autocad,
        },
        "checks": checks,
        "remediations": remediations,
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
