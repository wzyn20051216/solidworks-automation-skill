"""工程图 DrawingSpec v1 解析与制造交付前置检查。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
PAPER_SIZES = {"A4", "A3", "A2", "A1", "A0"}
PROJECTIONS = {"first_angle", "third_angle"}
DOCUMENT_TYPES = {"part", "assembly", "sheet_metal"}


def load_drawing_spec(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """@brief 读取 DrawingSpec JSON 或复制内存规格。"""
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source).expanduser().resolve()
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError(f"DrawingSpec 必须是现有 JSON 文件: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"DrawingSpec JSON 无效: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("DrawingSpec 根节点必须是对象")
    return payload


def _issue(code: str, message: str, severity: str = "error", path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity, "path": path}


def validate_drawing_spec(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验工程图规格并返回可追溯的阻断/通过报告。"""
    try:
        spec = load_drawing_spec(source)
    except ValueError as exc:
        return {"status": "blocked", "schema_version": SCHEMA_VERSION, "issues": [_issue("DRAWING_SPEC_INVALID", str(exc))]}

    issues: list[dict[str, str]] = []
    required = ("schemaVersion", "sourceModel", "documentType", "standard", "projection", "paperSize", "views", "outputs")
    for field in required:
        if field not in spec:
            issues.append(_issue("DRAWING_SPEC_REQUIRED_FIELD_MISSING", f"缺少必填字段: {field}", path=field))
    if spec.get("schemaVersion") != SCHEMA_VERSION:
        issues.append(_issue("DRAWING_SPEC_VERSION_UNSUPPORTED", f"只支持 schemaVersion={SCHEMA_VERSION}", path="schemaVersion"))
    if spec.get("documentType") not in DOCUMENT_TYPES:
        issues.append(_issue("DRAWING_SPEC_DOCUMENT_TYPE_INVALID", "documentType 必须是 part、assembly 或 sheet_metal", path="documentType"))
    if spec.get("paperSize") not in PAPER_SIZES:
        issues.append(_issue("DRAWING_SPEC_PAPER_SIZE_INVALID", "paperSize 必须是 A4/A3/A2/A1/A0", path="paperSize"))
    standard = spec.get("standard")
    projection = spec.get("projection")
    if standard not in {"GB_T", "ISO"}:
        issues.append(_issue("DRAWING_SPEC_STANDARD_INVALID", "standard 必须是 GB_T 或 ISO", path="standard"))
    if projection not in PROJECTIONS:
        issues.append(_issue("DRAWING_SPEC_PROJECTION_INVALID", "projection 必须是 first_angle 或 third_angle", path="projection"))
    if standard == "GB_T" and projection == "third_angle":
        issues.append(_issue("DRAWING_GBT_PROJECTION_CONFLICT", "GB/T 工程图默认采用第一角投影，不能使用第三角布局"))

    views = spec.get("views")
    if not isinstance(views, dict) or not isinstance(views.get("front"), dict):
        issues.append(_issue("DRAWING_SPEC_FRONT_VIEW_MISSING", "views.front 是必需的主视图规格", path="views.front"))

    outputs = spec.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("slddrw") is not True or outputs.get("pdf") is not True or outputs.get("report") is not True:
        issues.append(_issue("DRAWING_SPEC_DELIVERY_OUTPUTS_INCOMPLETE", "outputs 必须至少要求 slddrw、pdf 和 report", path="outputs"))

    bom = spec.get("bom") or {}
    if spec.get("documentType") == "assembly" and bom.get("required", True):
        template_path = bom.get("templatePath")
        if not template_path or not Path(str(template_path)).expanduser().is_file():
            issues.append(_issue("DRAWING_BOM_TEMPLATE_MISSING", "装配工程图要求 BOM 时必须提供存在的 .sldbomtbt 模板", path="bom.templatePath"))

    for index, item in enumerate(spec.get("requiredDimensions", []) or []):
        if not isinstance(item, dict) or not item.get("id") or not item.get("kind") or not item.get("view"):
            issues.append(_issue("DRAWING_DIMENSION_SPEC_INCOMPLETE", "必需尺寸必须包含 id、kind 和 view", path=f"requiredDimensions[{index}]"))
    for index, item in enumerate(spec.get("holeRequirements", []) or []):
        valid = isinstance(item, dict) and item.get("id") and item.get("specification") and isinstance(item.get("count"), int) and item.get("count", 0) > 0
        locations = item.get("locationsMm") if isinstance(item, dict) else None
        if not valid or not isinstance(locations, list) or len(locations) != item.get("count", -1):
            issues.append(_issue("DRAWING_HOLE_REQUIREMENT_INCOMPLETE", "孔槽要求必须包含规格、数量，并为每个孔提供定位坐标", path=f"holeRequirements[{index}]"))

    if spec.get("documentType") == "sheet_metal":
        sheet_metal = spec.get("sheetMetal") or {}
        evidence = sheet_metal.get("flatPatternEvidencePath")
        if not evidence or not Path(str(evidence)).expanduser().is_file():
            issues.append(_issue("DRAWING_SHEET_METAL_FLAT_PATTERN_EVIDENCE_MISSING", "钣金工程图缺少可靠展开图证据，当前只能阻断或进入 pilot", "warning", "sheetMetal.flatPatternEvidencePath"))

    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    status = "blocked" if errors else "pilot" if warnings else "pass"
    return {
        "status": status,
        "schema_version": SCHEMA_VERSION,
        "spec": spec,
        "issues": issues,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "manual_review_required": True,
        "capability": "solidworks-engineering-drawing",
    }
