"""构建并回归 AutoCAD 2024 .NET 白名单插件。

默认只构建；显式 ``--real-cad`` 时才启动本次脚本拥有的 AutoCAD Core Console
实例。脚本不连接或关闭用户手动启动的 AutoCAD 桌面进程。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from cad_installation import discover_installation  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1] / "dotnet" / "CadStudio.AutoCAD2024" / "CadStudio.AutoCAD2024.csproj"
REQUIRED_CHECKS = (
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
SYSTEM_VARIABLES = ("SECURELOAD", "FILEDIA", "BACKGROUNDPLOT")


def _dotnet_executable() -> str | None:
    """@brief 返回当前 PATH 或系统标准目录中的 dotnet SDK 主机。"""
    fixed = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "dotnet" / "dotnet.exe"
    user = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "dotnet" / "dotnet.exe"
    candidates = [shutil.which("dotnet"), shutil.which("dotnet.exe"), str(user), str(fixed)]
    fallback = None
    for candidate in dict.fromkeys(item for item in candidates if item):
        if not Path(candidate).is_file():
            continue
        fallback = fallback or candidate
        completed = subprocess.run([candidate, "--list-sdks"], capture_output=True, text=True, check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            return candidate
    return fallback


def _find_template() -> Path | None:
    """@brief 查找当前用户的公制 AutoCAD 模板。"""
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk"
    if local.is_dir():
        matches = sorted(local.glob("AutoCAD 2024/**/Template/acadiso.dwt"))
        if matches:
            return matches[0]
    return None


def _script_text(plugin: Path, original_variables: dict[str, int]) -> str:
    """@brief 生成固定白名单脚本，不接受调用方注入任意 AutoLISP 或命令。"""
    plugin_path = plugin.resolve().as_posix()
    commands = ["_.SECURELOAD", "0", "_.FILEDIA", "0", "_.BACKGROUNDPLOT", "0", "_.NETLOAD", f'"{plugin_path}"', "CADSTUDIOPROBE", "CADSTUDIOCREATE"]
    for name in SYSTEM_VARIABLES:
        commands.extend((f"_.{name}", str(original_variables[name])))
    commands.extend(("_.QUIT", "_Y", ""))
    return "\n".join(commands)


def _system_variable_probe_text() -> str:
    """@brief 生成只读取回归所涉及系统变量当前值的固定脚本。"""
    commands: list[str] = []
    for name in SYSTEM_VARIABLES:
        commands.extend((f"_.{name}", ""))
    commands.extend(("_.QUIT", "_Y", ""))
    return "\n".join(commands)


def _parse_system_variable(output: str, name: str) -> int | None:
    """@brief 从中英文 Core Console 提示中提取整数系统变量默认值。"""
    match = re.search(rf"{re.escape(name)}[\s\S]{{0,200}}?<([0-9]+)>", output, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _decode_output(raw: bytes | None) -> str:
    """@brief 解码 dotnet UTF-8、系统 GB18030 或 AutoCAD UTF-16 输出。"""
    if not raw:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or raw.count(b"\x00") > len(raw) // 4:
        return raw.decode("utf-16", errors="replace") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030", errors="strict")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def _run(command: list[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": _decode_output(completed.stdout)[-6000:],
            "stderr_tail": _decode_output(completed.stderr)[-3000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout_tail": _decode_output(exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode("utf-8"))[-6000:],
            "stderr_tail": _decode_output(exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode("utf-8"))[-3000:],
            "timed_out": True,
        }


def _runtime_status(plugin_report: dict[str, Any], process_result: dict[str, Any]) -> tuple[str, list[str]]:
    checks = plugin_report.get("checks") if isinstance(plugin_report.get("checks"), dict) else {}
    missing = [name for name in REQUIRED_CHECKS if checks.get(name) is not True]
    if process_result.get("returncode") != 0:
        return "failed", missing
    return ("pass" if plugin_report.get("status") == "pass" and not missing else "blocked"), missing


def _artifact_nonempty(path: Path, minimum_size: int = 32) -> bool:
    """@brief 确认导出文件来自本轮且不是空壳。"""
    return path.is_file() and path.stat().st_size >= minimum_size


def _artifact_record(path: Path) -> dict[str, Any]:
    """@brief 记录本轮产物大小和 SHA-256，供后续能力门禁复验。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "size": path.stat().st_size, "sha256": digest.hexdigest()}


def _persist_result(result: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """@brief 持久化每次真机回归结果，失败也必须打断连续通过序列。"""
    output_root = ROOT / "output" / "autocad-dotnet"
    final_report = run_dir / "final-report.json"
    final_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = result.setdefault("artifacts", [])
    if str(final_report) not in artifacts:
        artifacts.append(str(final_report))
    latest = output_root / "latest-report.json"
    latest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path = output_root / "runtime-history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.is_file() else {"schemaVersion": "1.0", "runs": []}
    except (OSError, json.JSONDecodeError):
        history = {"schemaVersion": "1.0", "runs": []}
    runs = history.get("runs") if isinstance(history.get("runs"), list) else []
    runs.append({
        "runDir": str(run_dir),
        "status": result.get("status"),
        "stage": result.get("stage"),
        "error_code": result.get("error_code"),
        "generatedAt": result.get("generatedAt"),
        "report": str(final_report),
        "artifactDigests": [item["sha256"] for item in result.get("artifactLedger", []) if isinstance(item, dict) and item.get("sha256")],
    })
    history["runs"] = runs[-100:]
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_regression(*, real_cad: bool = False, timeout: int = 180) -> dict[str, Any]:
    """@brief 构建插件，并按需执行 AutoCAD Core Console 真机回归。"""
    installation = discover_installation("autocad")
    executable = Path(str(installation.get("executable") or ""))
    install_dir = executable.parent if executable.is_file() else None
    dotnet = _dotnet_executable()
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = ROOT / "output" / "autocad-dotnet" / timestamp
    build_dir = run_dir / "plugin"
    report_path = run_dir / "runtime-report.json"
    drawing_path = run_dir / "cad-studio-dotnet-probe.dwg"
    pdf_path = run_dir / "cad-studio-dotnet-probe.pdf"
    png_path = run_dir / "cad-studio-dotnet-probe.png"
    run_dir.mkdir(parents=True, exist_ok=False)

    result: dict[str, Any] = {
        "schemaVersion": "1.0",
        "backend": "autocad_dotnet",
        "generatedAt": now.isoformat(),
        "status": "blocked",
        "stage": "preflight",
        "installation": installation,
        "artifacts": [],
        "limitations": [],
        "retryable": True,
        "error_code": None,
    }
    if not dotnet:
        result.update(error_code="DOTNET_SDK_MISSING", limitations=["未发现 dotnet SDK"])
        return _persist_result(result, run_dir)
    if not install_dir:
        result.update(error_code="AUTOCAD_NOT_FOUND", limitations=["未发现 AutoCAD 2024 安装目录"])
        return _persist_result(result, run_dir)

    build = _run(
        [dotnet, "build", str(PROJECT), "--configuration", "Release", "--output", str(build_dir), f"-p:AutoCADInstallDir={install_dir}"],
        cwd=ROOT,
        timeout=timeout,
    )
    result["build"] = build
    plugin = build_dir / "CadStudio.AutoCAD2024.dll"
    if build.get("returncode") != 0 or not plugin.is_file():
        result.update(status="failed", stage="build", error_code="AUTOCAD_DOTNET_BUILD_FAILED")
        return _persist_result(result, run_dir)
    result["artifacts"].append(str(plugin))

    if not real_cad:
        result.update(stage="load", error_code="AUTOCAD_DOTNET_RUNTIME_NOT_VERIFIED", limitations=["插件已构建，尚未执行真机 NETLOAD 回归"])
        return _persist_result(result, run_dir)

    core_console = install_dir / "accoreconsole.exe"
    template = _find_template()
    if not core_console.is_file() or not template:
        result.update(stage="preflight", error_code="AUTOCAD_CORE_CONSOLE_PREREQUISITE_MISSING", limitations=["缺少 accoreconsole.exe 或 acadiso.dwt"])
        return _persist_result(result, run_dir)

    system_variable_probe = run_dir / "cad-studio-system-variable-probe.scr"
    system_variable_probe.write_text(_system_variable_probe_text(), encoding="ascii")
    system_variable_result = _run(
        [str(core_console), "/i", str(template), "/s", str(system_variable_probe)],
        cwd=run_dir,
        timeout=timeout,
        env=os.environ.copy(),
    )
    original_variables = {
        name: _parse_system_variable(system_variable_result.get("stdout_tail", ""), name)
        for name in SYSTEM_VARIABLES
    }
    result["systemVariableProbe"] = {**system_variable_result, "originalValues": original_variables}
    if system_variable_result.get("returncode") != 0 or any(value is None for value in original_variables.values()):
        result.update(stage="preflight", error_code="AUTOCAD_SYSTEM_VARIABLE_PROBE_FAILED", limitations=["无法安全读取并恢复 SECURELOAD/FILEDIA/BACKGROUNDPLOT 原值"])
        return _persist_result(result, run_dir)

    script = run_dir / "cad-studio-dotnet-regression.scr"
    script.write_text(_script_text(plugin, {name: int(value) for name, value in original_variables.items()}), encoding="ascii")
    environment = os.environ.copy()
    environment["CAD_STUDIO_DOTNET_REPORT_PATH"] = str(report_path)
    environment["CAD_STUDIO_DOTNET_OUTPUT_DWG"] = str(drawing_path)
    environment["CAD_STUDIO_DOTNET_OUTPUT_PDF"] = str(pdf_path)
    environment["CAD_STUDIO_DOTNET_OUTPUT_PNG"] = str(png_path)
    process = _run(
        [str(core_console), "/i", str(template), "/s", str(script)],
        cwd=run_dir,
        timeout=timeout,
        env=environment,
    )
    result["runtime"] = process
    if report_path.is_file():
        try:
            plugin_report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.update(status="failed", stage="review", error_code="AUTOCAD_DOTNET_EVIDENCE_INVALID", limitations=[str(exc)])
            return _persist_result(result, run_dir)
    else:
        plugin_report = {"status": "failed", "checks": {}, "error_code": "AUTOCAD_DOTNET_REPORT_MISSING"}
    checks = plugin_report.get("checks") if isinstance(plugin_report.get("checks"), dict) else {}
    checks["pdf_generated"] = _artifact_nonempty(pdf_path)
    checks["png_generated"] = _artifact_nonempty(png_path)
    plugin_report["checks"] = checks
    if all(checks.get(name) is True for name in REQUIRED_CHECKS):
        plugin_report["status"] = "pass"
        plugin_report["error_code"] = None
    report_path.write_text(json.dumps(plugin_report, ensure_ascii=False, indent=2), encoding="utf-8")
    status, missing = _runtime_status(plugin_report, process)
    result.update(
        status=status,
        stage="review",
        checks=plugin_report.get("checks", {}),
        missing_checks=missing,
        error_code=None if status == "pass" else plugin_report.get("error_code") or "AUTOCAD_DOTNET_RUNTIME_NOT_VERIFIED",
        limitations=[] if status == "pass" else ["真机回归尚未同时通过 DWG 重开、PDF/PNG、实体、图层和尺寸检查"],
    )
    result["artifacts"].extend(str(path) for path in (report_path, drawing_path, pdf_path, png_path) if path.is_file())
    ledger_paths = (plugin, drawing_path, pdf_path, png_path, report_path)
    result["artifactLedger"] = [_artifact_record(path) for path in ledger_paths if path.is_file()]
    return _persist_result(result, run_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoCAD 2024 .NET 白名单插件回归")
    parser.add_argument("--real-cad", action="store_true", help="启动本次脚本拥有的 AutoCAD Core Console 进行 NETLOAD 回归")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    report = run_regression(real_cad=args.real_cad, timeout=args.timeout)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
