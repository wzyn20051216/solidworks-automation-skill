"""@brief 工程图阶段的 GB 强制门禁。

检查器本身只读 DXF；本模块负责从 Agent 产物中定位 DXF、执行检查器、
校验检查报告，并把可追溯证据写回任务结果。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable


EXPECTED_ITEMS = (
    "sheet_format",
    "frame_layers",
    "title_block",
    "scale",
    "dimension_values",
    "dimension_readability",
    "line_weight",
    "font",
    "projection",
    "bom",
    "technical_requirements",
    "archive",
)

GateRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


def pipeline_stage(job: dict[str, Any]) -> str:
    """@brief 读取项目流水线阶段，兼容旧任务字段。"""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    pipeline = ui_config.get("pipeline") if isinstance(ui_config.get("pipeline"), dict) else {}
    return str(pipeline.get("stage") or job.get("pipelineStage") or "").strip().lower()


def _path_value(value: Any) -> str | None:
    """@brief 从字符串或产物对象中提取路径。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("path", "outputPath", "file"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _artifact_paths(result: dict[str, Any]) -> Iterable[Path]:
    """@brief 遍历 Agent 返回的 artifacts/outputs，不把普通说明文字当路径。"""
    for key in ("artifacts", "outputs"):
        value = result.get(key)
        if isinstance(value, (str, dict)):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            continue
        for item in values:
            raw = _path_value(item)
            if raw:
                yield Path(raw).expanduser()


def _is_within(path: Path, roots: list[Path]) -> bool:
    """@brief 判断路径是否位于允许的产物根目录内。"""
    try:
        candidate = os.path.normcase(os.path.normpath(str(path.resolve())))
    except (OSError, RuntimeError, ValueError):
        return False
    for root in roots:
        try:
            root_value = os.path.normcase(os.path.normpath(str(root.resolve())))
            if os.path.commonpath([candidate, root_value]) == root_value:
                return True
        except (OSError, RuntimeError, ValueError):
            # Windows 跨盘符 commonpath 会抛 ValueError；继续检查下一个允许根。
            continue
    return False


def _allowed_roots(job: dict[str, Any], cwd: Path) -> list[Path]:
    """@brief 返回可用于定位 DXF 的工作区与输出根目录。"""
    roots: list[Path] = [Path(cwd)]
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    for raw in (job.get("cwd"), job.get("projectPath"), ui_config.get("outputDir")):
        if isinstance(raw, str) and raw.strip():
            roots.append(Path(raw).expanduser())
    for raw in ui_config.get("artifactRoots", []) if isinstance(ui_config.get("artifactRoots"), list) else []:
        if isinstance(raw, str) and raw.strip():
            roots.append(Path(raw).expanduser())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _select_dxf(result: dict[str, Any], roots: list[Path]) -> Path | None:
    """@brief 从本轮产物中选择最新的有效 DXF。"""
    candidates: list[Path] = []
    for raw in _artifact_paths(result):
        if raw.suffix.lower() != ".dxf":
            continue
        try:
            candidate = raw.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if candidate.is_file() and _is_within(candidate, roots):
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def _report_path(dxf: Path, job: dict[str, Any]) -> Path:
    """@brief 把权威检查报告放在本轮 verification 目录，缺失时回退到 DXF 同目录。"""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    raw_output = ui_config.get("outputDir")
    if isinstance(raw_output, str) and raw_output.strip():
        output = Path(raw_output).expanduser().resolve()
        verification = output / "verification"
        if verification.is_dir() or output.is_dir():
            return verification / "gb_checklist.json"
    if dxf.parent.name.lower() in {"drawing", "drawings", "图纸"}:
        verification = dxf.parent.parent / "verification"
        if verification.is_dir():
            return verification / "gb_checklist.json"
    return dxf.parent / "gb_checklist.json"


def _validate_report(report: Any) -> tuple[bool, list[str], str]:
    """@brief 严格验证检查器报告，不接受部分通过或无报告成功。"""
    if not isinstance(report, dict):
        return False, [], "检查器未返回 JSON 对象"
    items = report.get("items")
    if not isinstance(items, list):
        return False, [], "检查器报告缺少 items 数组"
    indexed = {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }
    missing = [item_id for item_id in EXPECTED_ITEMS if item_id not in indexed]
    failed = [
        item_id
        for item_id in EXPECTED_ITEMS
        if item_id in indexed and str(indexed[item_id].get("status")) != "pass"
    ]
    unexpected = sorted(set(indexed) - set(EXPECTED_ITEMS))
    if missing:
        return False, [*missing, *failed], f"检查报告缺少项目: {missing}"
    if failed:
        return False, failed, f"检查项目未通过: {failed}"
    if str(report.get("status")) != "pass":
        return False, failed, f"检查器总体状态不是 pass: {report.get('status')}"
    if unexpected:
        return False, [], f"检查报告出现未知项目，拒绝放行: {unexpected}"
    return True, [], "12 项 GB 检查全部通过"


def run_gb_drawing_gate(
    job: dict[str, Any],
    result: dict[str, Any],
    cwd: Path,
    runner: GateRunner | None = None,
) -> dict[str, Any] | None:
    """@brief 在 drawing 阶段强制执行 GB 检查并返回门禁证据。"""
    if pipeline_stage(job) != "drawing":
        return None
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    gates = ui_config.get("gates") if isinstance(ui_config.get("gates"), dict) else {}
    if gates.get("strictGbDrawing") is False:
        return None

    roots = _allowed_roots(job, Path(cwd))
    dxf = _select_dxf(result, roots)
    if dxf is None:
        evidence = {
            "schemaVersion": "1.0",
            "status": "fail",
            "stage": "gb_drawing",
            "errorCode": "GB_DXF_MISSING",
            "message": "工程图阶段没有找到本轮 DXF，禁止交付。",
            "failedItems": list(EXPECTED_ITEMS),
        }
        result["gbDrawingGate"] = evidence
        return evidence

    report_path = _report_path(dxf, job)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        report_path.unlink(missing_ok=True)
    except OSError:
        pass
    script = Path(__file__).resolve().parents[3] / "scripts" / "gb_drawing_check.py"
    if not script.is_file():
        evidence = {
            "schemaVersion": "1.0",
            "status": "fail",
            "stage": "gb_drawing",
            "errorCode": "GB_CHECKER_MISSING",
            "message": f"GB 检查器不存在: {script}",
            "dxfPath": str(dxf),
            "reportPath": str(report_path),
            "failedItems": list(EXPECTED_ITEMS),
        }
        result["gbDrawingGate"] = evidence
        return evidence

    command = [sys.executable, str(script), str(dxf), "--json", str(report_path)]
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    active_runner = runner or (
        lambda args, run_cwd, timeout: subprocess.run(
            args,
            cwd=str(run_cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=child_env,
        )
    )
    try:
        completed = active_runner(command, Path(cwd), 120)
        return_code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as error:  # noqa: BLE001 - 门禁必须把检查器异常写回任务。
        return_code = -1
        stdout = ""
        stderr = str(error)

    report: Any = None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        report = None
    passed, failed_items, detail = _validate_report(report)
    if return_code != 0:
        passed = False
        detail = f"检查器退出码 {return_code}；{detail}"
    evidence = {
        "schemaVersion": "1.0",
        "status": "pass" if passed else "fail",
        "stage": "gb_drawing",
        "command": command,
        "returnCode": return_code,
        "dxfPath": str(dxf),
        "reportPath": str(report_path),
        "failedItems": failed_items,
        "message": detail,
        "stdoutTail": stdout[-2000:],
        "stderrTail": stderr[-2000:],
    }
    result["gbDrawingGate"] = evidence
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        result["artifacts"] = artifacts
    if all(_path_value(item) != str(report_path) for item in artifacts):
        artifacts.append({"kind": "gb_checklist", "path": str(report_path)})
    return evidence
