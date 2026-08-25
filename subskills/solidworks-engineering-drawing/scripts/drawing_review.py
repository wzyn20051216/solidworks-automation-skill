"""工程图制造交付审视器。"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from scripts.sw_review import inspect_pdf_text_layout, review_drawing_layout

try:
    from .drawing_spec import load_drawing_spec, validate_drawing_spec
except ImportError:
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from drawing_spec import load_drawing_spec, validate_drawing_spec


def _check(code: str, status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"id": code, "status": status, "message": message, **extra}


def _required_dimension_report(spec: Mapping[str, Any], structure: Mapping[str, Any] | None) -> dict[str, Any]:
    requirements = list(spec.get("requiredDimensions") or [])
    dimensions = list((structure or {}).get("dimensions") or [])
    text = " ".join(str(item.get("text") or "") for item in dimensions)
    missing = []
    for item in requirements:
        identifier = str(item.get("id") or "")
        expected = str(item.get("text") or item.get("valueMm") or identifier)
        if not any(identifier in str(dim.get("name") or "") or expected in str(dim.get("text") or "") for dim in dimensions) and expected not in text:
            missing.append(identifier or expected)
    return {"required_count": len(requirements), "missing": missing, "status": "pass" if not missing else "fail"}


def _hole_report(spec: Mapping[str, Any], model_evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    requirements = list(spec.get("holeRequirements") or [])
    if not requirements:
        return {"required_count": 0, "missing": [], "status": "pass"}
    evidence = model_evidence or {}
    groups = list(evidence.get("hole_groups") or evidence.get("holeGroups") or [])
    missing = []
    for item in requirements:
        specification = str(item.get("specification"))
        count = int(item.get("count", 0))
        matching = [group for group in groups if specification.lower() in json.dumps(group, ensure_ascii=False).lower()]
        if not matching and len(groups) < count:
            missing.append(item.get("id", specification))
    return {"required_count": len(requirements), "missing": missing, "status": "pass" if not missing else "fail", "evidence_source": "model_measurements" if groups else "missing"}


def _boxes_overlap(first: Mapping[str, float], second: Mapping[str, float]) -> bool:
    """@brief 判断 PDF 点坐标文字框是否有可见面积重叠。"""
    return (
        min(float(first["right"]), float(second["right"])) > max(float(first["left"]), float(second["left"]))
        and min(float(first["bottom"]), float(second["bottom"])) > max(float(first["top"]), float(second["top"]))
    )


def inspect_pdf_dimension_rendering(
    pdf_path: str | Path,
    structure: Mapping[str, Any],
    *,
    match_tolerance_m: float = 0.012,
) -> dict[str, Any]:
    """@brief 将 COM 尺寸位置与最终 PDF 的真实矢量文字框一一关联。"""
    pdf = inspect_pdf_text_layout(pdf_path)
    dimensions = list(structure.get("dimensions") or [])
    sheet_size = structure.get("sheet_size") or {}
    width_m = sheet_size.get("width_m")
    height_m = sheet_size.get("height_m")
    base = {
        "status": "blocked",
        "stage": "pdf_dimension_rendering",
        "source": "solidworks_pdf_vector_text",
        "matched": [],
        "unmatched_dimension_indexes": [],
        "collisions": [],
        "error_code": None,
        "manual_review_required": True,
    }
    try:
        width_m = float(width_m)
        height_m = float(height_m)
        tolerance_m = float(match_tolerance_m)
    except (TypeError, ValueError):
        base.update({"error_code": "DRAWING_SHEET_SIZE_EVIDENCE_MISSING"})
        return base
    if width_m <= 0 or height_m <= 0 or tolerance_m <= 0 or not math.isfinite(tolerance_m):
        base.update({"error_code": "DRAWING_SHEET_SIZE_EVIDENCE_MISSING"})
        return base
    if pdf.get("status") == "blocked":
        base.update({"error_code": pdf.get("error_code") or "DRAWING_PDF_DIMENSION_EVIDENCE_MISSING", "pdf": pdf})
        return base
    pages = list(pdf.get("pages") or [])
    if not dimensions:
        base.update({"status": "pass", "error_code": None, "manual_review_required": False, "pdf": pdf})
        return base
    if not pages:
        base.update({"error_code": "DRAWING_PDF_VECTOR_TEXT_MISSING", "pdf": pdf})
        return base

    sheet_order = {str(name): index for index, name in enumerate(structure.get("sheets") or [])}
    used = set()
    for index, dimension in enumerate(dimensions):
        evidence = dimension.get("box_evidence") or {}
        position = evidence.get("position_m") or []
        if len(position) < 2:
            base["unmatched_dimension_indexes"].append(index)
            continue
        page_index = sheet_order.get(str(dimension.get("sheet") or ""), 0)
        if page_index >= len(pages):
            base["unmatched_dimension_indexes"].append(index)
            continue
        page = pages[page_index]
        page_width = float(page["widthPt"])
        page_height = float(page["heightPt"])
        try:
            expected_x = float(position[0]) / width_m * page_width
            expected_y = page_height - float(position[1]) / height_m * page_height
        except (TypeError, ValueError):
            base["unmatched_dimension_indexes"].append(index)
            continue
        tolerance_pt = tolerance_m / min(width_m / page_width, height_m / page_height)
        candidates = []
        for candidate_index, span in enumerate(page.get("textSpans") or []):
            if (page_index, candidate_index) in used or not span.get("dimensionCandidate"):
                continue
            left, top, right, bottom = (float(value) for value in span["bboxPt"])
            center_x = (left + right) / 2.0
            center_y = (top + bottom) / 2.0
            distance = math.hypot(center_x - expected_x, center_y - expected_y)
            if distance <= tolerance_pt:
                candidates.append((distance, candidate_index, span))
        if not candidates:
            base["unmatched_dimension_indexes"].append(index)
            continue
        _, candidate_index, span = min(candidates, key=lambda item: item[0])
        used.add((page_index, candidate_index))
        left, top, right, bottom = (float(value) for value in span["bboxPt"])
        base["matched"].append({
            "dimension_index": index,
            "dimension_name": str(dimension.get("name") or ""),
            "page": page_index + 1,
            "text": span["text"],
            "bbox_pt": [left, top, right, bottom],
            "box_m": {
                "left": left / page_width * width_m,
                "bottom": (page_height - bottom) / page_height * height_m,
                "right": right / page_width * width_m,
                "top": (page_height - top) / page_height * height_m,
            },
            "distance_to_com_position_pt": round(min(candidates, key=lambda item: item[0])[0], 6),
        })
    for current_index, current in enumerate(base["matched"]):
        for other in base["matched"][current_index + 1:]:
            if current["page"] == other["page"] and _boxes_overlap(
                {"left": current["bbox_pt"][0], "top": current["bbox_pt"][1], "right": current["bbox_pt"][2], "bottom": current["bbox_pt"][3]},
                {"left": other["bbox_pt"][0], "top": other["bbox_pt"][1], "right": other["bbox_pt"][2], "bottom": other["bbox_pt"][3]},
            ):
                base["collisions"].append({"first": current["dimension_name"], "second": other["dimension_name"], "code": "DRAWING_RENDERED_DIMENSION_TEXT_OVERLAP"})
    if base["unmatched_dimension_indexes"]:
        base.update({"status": "review_required", "error_code": "DRAWING_PDF_DIMENSION_MATCH_INCOMPLETE", "pdf": pdf})
    elif base["collisions"]:
        base.update({"status": "review_required", "error_code": "DRAWING_RENDERED_DIMENSION_TEXT_OVERLAP", "pdf": pdf})
    else:
        base.update({"status": "pass", "error_code": None, "manual_review_required": False, "pdf": pdf})
    return base


def _with_rendered_dimension_boxes(structure: Mapping[str, Any], rendering: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 用已关联的最终 PDF 文字框替代 COM 估算尺寸框。"""
    result = copy.deepcopy(dict(structure))
    dimensions = list(result.get("dimensions") or [])
    for match in rendering.get("matched") or []:
        index = int(match["dimension_index"])
        if 0 <= index < len(dimensions):
            dimensions[index]["box"] = dict(match["box_m"])
            dimensions[index]["box_source"] = "pdf_vector_text"
            dimensions[index]["box_confidence"] = "high"
            dimensions[index]["box_evidence"] = {
                "source": "solidworks_pdf_vector_text",
                "page": match["page"],
                "text": match["text"],
                "bbox_pt": match["bbox_pt"],
                "distance_to_com_position_pt": match["distance_to_com_position_pt"],
            }
    result["dimensions"] = dimensions
    return result


def review_drawing_artifacts(
    spec_source: str | Path | Mapping[str, Any],
    *,
    structure: Mapping[str, Any] | None = None,
    pdf_path: str | Path | None = None,
    preview_evidence: list[Mapping[str, Any]] | None = None,
    model_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """@brief 结合规格、COM结构、PDF文字和预览证据审视工程图。"""
    validation = validate_drawing_spec(spec_source)
    if validation["status"] == "blocked":
        return {"status": "blocked", "stage": "spec", "checks": validation["issues"], "findings": validation["issues"], "manual_review_required": True, "error_code": "DRAWING_SPEC_BLOCKED"}
    spec = validation["spec"]
    checks = []
    findings = list(validation.get("issues") or [])
    structure = structure or {}
    pdf_dimension_rendering = (
        inspect_pdf_dimension_rendering(pdf_path, structure)
        if pdf_path and structure
        else {
            "status": "blocked",
            "stage": "pdf_dimension_rendering",
            "source": "solidworks_pdf_vector_text",
            "matched": [],
            "unmatched_dimension_indexes": list(range(len(structure.get("dimensions") or []))),
            "collisions": [],
            "error_code": "DRAWING_FINAL_PDF_REQUIRED",
            "manual_review_required": True,
        }
    )
    reviewed_structure = (
        _with_rendered_dimension_boxes(structure, pdf_dimension_rendering)
        if pdf_dimension_rendering and pdf_dimension_rendering.get("status") == "pass"
        else structure
    )
    layout = review_drawing_layout(reviewed_structure, preview_evidence=preview_evidence) if reviewed_structure else {
        "status": "blocked", "error_code": "DRAWING_STRUCTURE_EVIDENCE_MISSING", "findings": [], "checks": []
    }
    checks.extend(layout.get("checks") or [])
    findings.extend(layout.get("findings") or [])
    dimension_report = _required_dimension_report(spec, reviewed_structure)
    hole_report = _hole_report(spec, model_evidence)
    checks.append(_check("drawing-required-dimensions", dimension_report["status"], f"必需尺寸 {dimension_report['required_count']} 项，缺失 {len(dimension_report['missing'])} 项", missing=dimension_report["missing"]))
    checks.append(_check("drawing-hole-requirements", hole_report["status"], f"孔槽要求 {hole_report['required_count']} 项，缺失 {len(hole_report['missing'])} 项", missing=hole_report["missing"]))
    if dimension_report["missing"]:
        findings.append({"code": "DRAWING_REQUIRED_DIMENSIONS_MISSING", "severity": "fail", "missing": dimension_report["missing"]})
    if hole_report["missing"]:
        findings.append({"code": "DRAWING_HOLE_REQUIREMENTS_MISSING", "severity": "fail", "missing": hole_report["missing"]})

    bom_required = bool((spec.get("bom") or {}).get("required")) or spec.get("documentType") == "assembly"
    table_count = int(structure.get("table_count", len(structure.get("tables") or [])))
    bom_status = "pass" if not bom_required or table_count > 0 else "fail"
    checks.append(_check("drawing-bom", bom_status, f"BOM要求={bom_required}，读取表格={table_count}"))
    if bom_status == "fail":
        findings.append({"code": "DRAWING_BOM_TABLE_MISSING", "severity": "fail", "message": "装配工程图未读取到 BOM 表结构"})

    title_block_required = bool((spec.get("titleBlock") or {}).get("required"))
    title_block = structure.get("title_block") or {}
    title_block_status = "pass" if not title_block_required or title_block.get("candidate") else "fail"
    checks.append(_check("drawing-title-block", title_block_status, "标题栏候选已读取" if title_block_status == "pass" else "规格要求标题栏，但结构证据中没有读取到图框标题栏"))
    if title_block_status == "fail":
        findings.append({"code": "DRAWING_TITLE_BLOCK_MISSING", "severity": "fail", "message": "标题栏结构证据缺失"})

    pdf_report = None
    if pdf_path:
        pdf_report = inspect_pdf_text_layout(pdf_path)
        checks.append(_check("drawing-pdf-text-layout", "warning" if pdf_report.get("overlaps") or pdf_report.get("status") == "blocked" else "pass", pdf_report.get("message", "PDF文字边界已检查")))
        if pdf_report.get("overlaps"):
            findings.append({"code": "DRAWING_PDF_TEXT_OVERLAP_RISK", "severity": "warning", "overlaps": pdf_report["overlaps"]})
    rendering_status = "pass" if pdf_dimension_rendering.get("status") == "pass" else "warning"
    checks.append(_check(
        "drawing-pdf-rendered-dimension-boxes",
        rendering_status,
        f"最终 PDF 尺寸文字框匹配 {len(pdf_dimension_rendering.get('matched') or [])}/{len(structure.get('dimensions') or [])}",
        unmatched_dimension_indexes=pdf_dimension_rendering.get("unmatched_dimension_indexes") or [],
    ))
    if pdf_dimension_rendering.get("collisions"):
        findings.extend({"code": item["code"], "severity": "fail", **item} for item in pdf_dimension_rendering["collisions"])

    fail_findings = [item for item in findings if item.get("severity") == "fail" or item.get("status") == "fail"]
    rendering_status = pdf_dimension_rendering.get("status")
    status = (
        "blocked"
        if layout.get("status") == "blocked" or rendering_status == "blocked"
        else "review_required"
        if fail_findings or layout.get("status") != "pass" or rendering_status != "pass" or validation["status"] == "pilot"
        else "pass"
    )
    return {
        "status": status,
        "stage": "review",
        "standard": spec.get("standard"),
        "projection": spec.get("projection"),
        "document_type": spec.get("documentType"),
        "checks": checks,
        "findings": findings,
        "layout": layout,
        "dimension_evidence": dimension_report,
        "hole_evidence": hole_report,
        "pdf_evidence": pdf_report,
        "pdf_dimension_rendering": pdf_dimension_rendering,
        "manual_review_required": status != "pass",
        "error_code": "DRAWING_REVIEW_FINDINGS" if fail_findings else pdf_dimension_rendering.get("error_code") if rendering_status != "pass" else layout.get("error_code"),
        "capability_level": "pilot",
    }
