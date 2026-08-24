"""工程图制造交付审视器。"""
from __future__ import annotations

import json
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
    layout = review_drawing_layout(structure, preview_evidence=preview_evidence) if structure else {
        "status": "blocked", "error_code": "DRAWING_STRUCTURE_EVIDENCE_MISSING", "findings": [], "checks": []
    }
    checks.extend(layout.get("checks") or [])
    findings.extend(layout.get("findings") or [])
    dimension_report = _required_dimension_report(spec, structure)
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

    fail_findings = [item for item in findings if item.get("severity") == "fail" or item.get("status") == "fail"]
    status = "blocked" if layout.get("status") == "blocked" else "review_required" if fail_findings or layout.get("status") != "pass" or validation["status"] == "pilot" else "pass"
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
        "manual_review_required": True,
        "error_code": "DRAWING_REVIEW_FINDINGS" if fail_findings else layout.get("error_code"),
        "capability_level": "pilot",
    }
