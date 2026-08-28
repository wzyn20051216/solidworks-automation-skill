"""工程图制造交付审视器。"""
from __future__ import annotations

import copy
import math
import re
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


def _normalise_token(value: Any) -> str:
    """@brief 规范化用于精确比对的短文本，但不做子串匹配。"""
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _dimension_identity(dimension: Mapping[str, Any]) -> str:
    """@brief 提取尺寸的稳定标识；D1 与 D10 必须保持不同。"""
    explicit = dimension.get("id") or dimension.get("dimension_id")
    if explicit:
        return str(explicit).strip()
    return str(dimension.get("name") or "").split("@", 1)[0].strip()


def _dimension_view(dimension: Mapping[str, Any]) -> str:
    """@brief 优先使用结构化视图名，兼容 SolidWorks 的 ID@View 名称。"""
    explicit = str(dimension.get("semantic_view") or dimension.get("view") or "").strip()
    if explicit:
        return explicit.lstrip("*")
    name = str(dimension.get("name") or "")
    return name.split("@", 1)[1].strip().lstrip("*") if "@" in name else ""


def _dimension_text(dimension: Mapping[str, Any]) -> str:
    """@brief 最终 PDF 回读文字优先于 COM 的空字符串。"""
    return str(dimension.get("rendered_text") or dimension.get("text") or "").strip()


def _extract_numbers(value: Any) -> list[float]:
    """@brief 从标注文字中提取有限数值，用于毫米值精确核验。"""
    result = []
    for token in re.findall(r"[-+]?\d+(?:\.\d+)?", str(value or "")):
        try:
            number = float(token)
        except ValueError:
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def _dimension_mismatches(requirement: Mapping[str, Any], dimension: Mapping[str, Any]) -> list[str]:
    """@brief 返回单项尺寸证据与规格之间的全部语义差异。"""
    mismatches = []
    expected_view = _normalise_token(str(requirement.get("view") or "").lstrip("*"))
    actual_view = _normalise_token(_dimension_view(dimension))
    if expected_view and actual_view != expected_view:
        mismatches.append("view")

    expected_kind = _normalise_token(requirement.get("kind"))
    actual_kind = _normalise_token(dimension.get("kind") or dimension.get("semantic_kind"))
    if expected_kind and actual_kind != expected_kind:
        mismatches.append("kind")

    actual_text = _dimension_text(dimension)
    if "text" in requirement and _normalise_token(actual_text) != _normalise_token(requirement.get("text")):
        mismatches.append("text")
    if "valueMm" in requirement:
        expected_value = float(requirement["valueMm"])
        actual_values = []
        if dimension.get("value_mm") is not None:
            try:
                actual_values.append(float(dimension["value_mm"]))
            except (TypeError, ValueError):
                pass
        rendered_values = _extract_numbers(actual_text)
        if rendered_values:
            actual_values.append(rendered_values[0])
        if not any(abs(value - expected_value) <= 0.01 for value in actual_values):
            mismatches.append("valueMm")
    for field in ("tolerance", "datum"):
        if field not in requirement:
            continue
        actual_value = dimension.get(field)
        if actual_value is None:
            actual_value = actual_text
        if _normalise_token(requirement[field]) not in _normalise_token(actual_value):
            mismatches.append(field)
    return mismatches


def _required_dimension_report(spec: Mapping[str, Any], structure: Mapping[str, Any] | None) -> dict[str, Any]:
    """@brief 按 ID、视图、种类和值逐项核验必需尺寸，禁止模糊子串放行。"""
    requirements = list(spec.get("requiredDimensions") or [])
    dimensions = list((structure or {}).get("dimensions") or [])
    checks = []
    used: set[int] = set()
    for item in requirements:
        identifier = str(item.get("id") or "").strip()
        candidates = [
            (index, dimension)
            for index, dimension in enumerate(dimensions)
            if index not in used and _normalise_token(_dimension_identity(dimension)) == _normalise_token(identifier)
        ]
        best = None
        for index, dimension in candidates:
            mismatches = _dimension_mismatches(item, dimension)
            candidate = (len(mismatches), index, dimension, mismatches)
            if best is None or candidate[0] < best[0]:
                best = candidate
        passed = bool(best and not best[3])
        if passed:
            used.add(best[1])
        checks.append({
            "id": identifier,
            "passed": passed,
            "matched_dimension": _dimension_identity(best[2]) if best else None,
            "mismatches": list(best[3]) if best else ["id"],
            "expected": dict(item),
        })
    missing = [item["id"] for item in checks if not item["passed"]]
    return {
        "required_count": len(requirements),
        "matched_count": len(requirements) - len(missing),
        "missing": missing,
        "checks": checks,
        "status": "pass" if not missing else "fail",
        "match_policy": "exact structured id/view/kind/value/text/tolerance/datum",
    }


def _hole_specification(specification: Any) -> dict[str, Any]:
    """@brief 把孔规格解析为螺纹或孔径约束，并保留通孔语义。"""
    text = str(specification or "").strip()
    compact = _normalise_token(text).replace("×", "x")
    thread = re.search(r"m(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?", compact)
    diameter = re.search(r"(?:[ø⌀]|dia(?:meter)?|直径|孔径)(\d+(?:\.\d+)?)", compact)
    return {
        "raw": text,
        "thread": f"m{thread.group(1)}" + (f"x{thread.group(2)}" if thread and thread.group(2) else "") if thread else None,
        "diameter_mm": float(diameter.group(1)) if diameter else None,
        "through_required": any(token in compact for token in ("通孔", "贯通", "thru", "through")),
    }


def _distance_mm(expected: list[Any], actual: list[Any]) -> float:
    """@brief 比较规格声明的二维或三维孔位坐标。"""
    if len(expected) not in {2, 3} or len(actual) < len(expected):
        return float("inf")
    try:
        return math.sqrt(sum((float(expected[index]) - float(actual[index])) ** 2 for index in range(len(expected))))
    except (TypeError, ValueError):
        return float("inf")


def _group_semantic_text(group: Mapping[str, Any]) -> str:
    """@brief 只读取专用语义字段，避免整个 JSON 的无关数字造成命中。"""
    fields = ("specification", "thread", "thread_specification", "callout", "hole_type")
    return " ".join(str(group.get(field) or "") for field in fields)


def _hole_group_matches(parsed: Mapping[str, Any], group: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """@brief 核验单个孔组的规格证据，不允许 M8 被直径 8 或其他 M 规格替代。"""
    mismatches = []
    semantic = _normalise_token(_group_semantic_text(group)).replace("×", "x")
    if parsed.get("thread"):
        tokens = re.findall(r"m\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?", semantic)
        if parsed["thread"] not in tokens:
            mismatches.append("thread")
    elif parsed.get("diameter_mm") is not None:
        diameters = []
        for value in group.get("diameters_mm") or []:
            try:
                diameters.append(float(value))
            except (TypeError, ValueError):
                continue
        if not any(abs(value - float(parsed["diameter_mm"])) <= 0.05 for value in diameters):
            mismatches.append("diameter")
    elif _normalise_token(parsed.get("raw")) != semantic:
        mismatches.append("specification")
    if parsed.get("through_required"):
        through = group.get("through")
        state = _normalise_token(group.get("through_state") or group.get("end_condition"))
        if through is not True and state not in {"through", "thru", "throughall", "通孔", "贯通"}:
            mismatches.append("through_state")
    return not mismatches, mismatches


def _hole_report(spec: Mapping[str, Any], model_evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """@brief 用规格、数量和逐孔位置一一匹配 B-Rep/特征证据。"""
    requirements = list(spec.get("holeRequirements") or [])
    if not requirements:
        return {"required_count": 0, "missing": [], "checks": [], "status": "pass"}
    evidence = model_evidence or {}
    groups = list(evidence.get("hole_groups") or evidence.get("holeGroups") or [])
    checks = []
    used: set[int] = set()
    for item in requirements:
        parsed = _hole_specification(item.get("specification"))
        location_checks = []
        for location in item.get("locationsMm") or []:
            best = None
            for index, group in enumerate(groups):
                if index in used:
                    continue
                specification_matches, mismatches = _hole_group_matches(parsed, group)
                position_error = _distance_mm(list(location), list(group.get("position_mm") or []))
                candidate = (0 if specification_matches else 1, position_error, index, group, mismatches)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
            passed = bool(best and best[0] == 0 and best[1] <= 0.1)
            if passed:
                used.add(best[2])
            location_checks.append({
                "expected_position_mm": list(location),
                "passed": passed,
                "position_error_mm": round(best[1], 6) if best and math.isfinite(best[1]) else None,
                "mismatches": list(best[4]) if best else ["missing_group"],
                "matched_group_index": best[2] if passed else None,
            })
        count_matches = int(item.get("count", 0)) == len(location_checks) and all(check["passed"] for check in location_checks)
        checks.append({
            "id": str(item.get("id") or item.get("specification") or ""),
            "passed": count_matches,
            "specification": item.get("specification"),
            "expected_count": int(item.get("count", 0)),
            "matched_count": sum(1 for check in location_checks if check["passed"]),
            "locations": location_checks,
        })
    missing = [item["id"] for item in checks if not item["passed"]]
    return {
        "required_count": len(requirements),
        "missing": missing,
        "checks": checks,
        "status": "pass" if not missing else "fail",
        "evidence_source": "model_measurements" if groups else "missing",
        "position_tolerance_mm": 0.1,
        "diameter_tolerance_mm": 0.05,
    }


def _bom_report(spec: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 只接受真实 BOM 类型、非空数据行及请求的配置。"""
    bom_spec = dict(spec.get("bom") or {})
    required = bool(bom_spec.get("required")) or spec.get("documentType") == "assembly"
    if not required:
        return {"required": False, "status": "pass", "tables": []}
    tables = [
        table for table in structure.get("tables") or []
        if table.get("kind") == "bom" or table.get("type") == 2
    ]
    if not tables:
        return {"required": True, "status": "fail", "tables": [], "reason": "missing"}
    usable = []
    for table in tables:
        row_count = table.get("row_count")
        if not isinstance(row_count, int) or row_count <= 1:
            continue
        cells = list(table.get("cells") or [])
        if len(cells) < 2 or not any(str(cell).strip() for row in cells[1:] for cell in row):
            continue
        requested_configuration = str(bom_spec.get("configuration") or "").strip()
        if requested_configuration and str(table.get("configuration") or "").strip() != requested_configuration:
            continue
        expected_rows = list(bom_spec.get("expectedRows") or bom_spec.get("rows") or [])
        flattened_rows = ["|".join(_normalise_token(cell) for cell in row) for row in cells[1:]]
        if expected_rows and not all(
            any(_normalise_token(expected) in row for row in flattened_rows)
            for expected in expected_rows
        ):
            continue
        usable.append(table)
    return {
        "required": True,
        "status": "pass" if usable else "review_required",
        "tables": tables,
        "usable_table_count": len(usable),
        "reason": None if usable else "content_or_configuration_unverified",
    }


def _title_block_report(spec: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 标题栏候选只证明模板存在，字段内容必须回读后才能通过。"""
    title_spec = dict(spec.get("titleBlock") or {})
    if not title_spec.get("required"):
        return {"required": False, "status": "pass", "mismatches": []}
    title_block = dict(structure.get("title_block") or {})
    if not title_block.get("candidate"):
        return {"required": True, "status": "fail", "mismatches": ["candidate"]}
    expected_fields = {key: value for key, value in title_spec.items() if key != "required"}
    actual_fields = dict(title_block.get("fields") or {})
    mismatches = []
    for key, expected in expected_fields.items():
        if key == "format":
            if _normalise_token(expected) == "gb_t" and not title_block.get("gbt_candidate"):
                mismatches.append(key)
            continue
        if _normalise_token(actual_fields.get(key)) != _normalise_token(expected):
            mismatches.append(key)
    verified = bool(title_block.get("content_verified"))
    return {
        "required": True,
        "status": "pass" if verified and not mismatches else "fail" if mismatches else "review_required",
        "mismatches": mismatches,
        "content_verified": verified,
        "fields": actual_fields,
    }


def _canonical_view_name(value: Any) -> str:
    """@brief 统一 SolidWorks 标准视图英文名和常见中文名。"""
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").casefold())
    aliases = {
        "front": "front", "frontview": "front", "主视": "front", "前视": "front",
        "top": "top", "topview": "top", "俯视": "top", "上视": "top",
        "right": "right", "rightview": "right", "右视": "right",
        "left": "left", "leftview": "left", "左视": "left",
        "bottom": "bottom", "bottomview": "bottom", "仰视": "bottom",
        "isometric": "isometric", "isometricview": "isometric", "轴测": "isometric", "等轴测": "isometric",
    }
    return aliases.get(compact, compact)


def _view_requirement_label(requirement: Mapping[str, Any], fallback: str) -> str:
    """@brief 从剖视或局部视图规格中提取稳定标签。"""
    return str(requirement.get("id") or requirement.get("name") or requirement.get("label") or fallback).strip()


def _view_report(spec: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 核验标准、轴测、剖视和局部视图均有对应结构证据。"""
    requested = dict(spec.get("views") or {})
    actual = list(structure.get("views") or [])
    checks = []
    used: set[int] = set()

    for name in ("front", "top", "right", "left", "bottom", "isometric"):
        if name not in requested:
            continue
        match = next((
            index for index, view in enumerate(actual)
            if index not in used and name in {
                _canonical_view_name(view.get("semantic_view")),
                _canonical_view_name(view.get("orientation")),
                _canonical_view_name(view.get("name")),
            }
        ), None)
        if match is not None:
            used.add(match)
        checks.append({"id": name, "kind": "standard" if name != "isometric" else "isometric", "passed": match is not None, "matched_view_index": match})

    for collection_name, expected_type, kind in (("sections", 2, "section"), ("details", 3, "detail")):
        for requirement_index, requirement in enumerate(requested.get(collection_name) or []):
            label = _view_requirement_label(requirement, f"{kind}-{requirement_index + 1}")
            expected = _normalise_token(label)
            candidates = []
            for index, view in enumerate(actual):
                if index in used:
                    continue
                view_type = view.get("type")
                semantic_kind = _normalise_token(view.get("kind") or view.get("semantic_kind"))
                if view_type != expected_type and semantic_kind != kind:
                    continue
                actual_label = _normalise_token(view.get("spec_id") or view.get("label") or view.get("name"))
                if not expected or expected == actual_label or expected in actual_label:
                    candidates.append(index)
            match = candidates[0] if candidates else None
            if match is not None:
                used.add(match)
            checks.append({"id": label, "kind": kind, "passed": match is not None, "matched_view_index": match})

    missing = [item["id"] for item in checks if not item["passed"]]
    return {
        "required_count": len(checks),
        "matched_count": len(checks) - len(missing),
        "missing": missing,
        "checks": checks,
        "status": "pass" if not missing else "fail",
    }


def _annotation_evidence_text(record: Mapping[str, Any]) -> str:
    """@brief 汇总专业标注的专用字段，不扫描无关结构数据。"""
    parts = [
        record.get("label"),
        record.get("name"),
        record.get("datum_identifier"),
        *(record.get("text_parts") or []),
        *(record.get("variables") or []),
    ]
    for frame in record.get("frames") or []:
        parts.extend(frame.get("symbols") or [])
        parts.extend(frame.get("values") or [])
    return " ".join(str(item or "") for item in parts)


def _professional_annotation_report(spec: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 按视图、类型、数量和文字核验专业工程图标注。"""
    requested = dict(spec.get("professionalAnnotations") or {})
    if not requested:
        return {"required_count": 0, "missing": [], "checks": [], "status": "pass"}
    evidence = dict(structure.get("professional_annotations") or {})
    checks = []
    collection_map = {
        "centerMarks": "center_marks",
        "centerLines": "center_lines",
        "holeCallouts": "hole_callouts",
        "datums": "datum_tags",
        "geometricTolerances": "geometric_tolerances",
        "surfaceFinishSymbols": "surface_finish_symbols",
        "weldSymbols": "weld_symbols",
    }
    for request_key, evidence_key in collection_map.items():
        records = list(evidence.get(evidence_key) or [])
        for requirement in requested.get(request_key) or []:
            expected_view = _canonical_view_name(requirement.get("view"))
            candidates = [
                record for record in records
                if expected_view == _canonical_view_name(record.get("semantic_view") or record.get("view"))
            ]
            expected_count = int(requirement.get("count", 1))
            expected_text = str(requirement.get("text") or "")
            if request_key in {"centerMarks", "centerLines"}:
                matched = candidates[:expected_count]
            elif request_key == "datums":
                matched = [
                    record for record in candidates
                    if _normalise_token(record.get("label")) == _normalise_token(expected_text)
                ][:expected_count]
            else:
                matched = [
                    record for record in candidates
                    if _normalise_token(expected_text) in _normalise_token(_annotation_evidence_text(record))
                ][:expected_count]
            passed = len(matched) == expected_count
            checks.append({
                "id": str(requirement.get("id") or ""),
                "kind": request_key,
                "view": requirement.get("view"),
                "expected_count": expected_count,
                "matched_count": len(matched),
                "passed": passed,
                "expected_text": expected_text or None,
            })
    missing = [item["id"] for item in checks if not item["passed"]]
    return {
        "required_count": len(checks),
        "matched_count": len(checks) - len(missing),
        "missing": missing,
        "checks": checks,
        "status": "pass" if not missing else "fail",
        "evidence": evidence,
    }


def _note_report(
    spec: Mapping[str, Any],
    structure: Mapping[str, Any] | None,
    pdf_path: str | Path | None,
) -> dict[str, Any]:
    """@brief 验证规格注释已在 COM 结构及最终 PDF 中真实出现。"""
    required = [str(item) for item in spec.get("notes") or [] if str(item).strip()]
    base = {
        "required_count": len(required),
        "missing_structure": [],
        "missing_position": [],
        "missing_pdf": [],
        "pdf_matches": [],
        "pdf": None,
        "status": "pass",
        "error_code": None,
    }
    if not required:
        return base
    notes = list((structure or {}).get("notes") or [])
    for text in required:
        matching = [item for item in notes if str(item.get("text") or "") == text]
        if not matching:
            base["missing_structure"].append(text)
        elif not any(item.get("position_m") and len(item["position_m"]) >= 2 for item in matching):
            base["missing_position"].append(text)
    if pdf_path is None:
        base.update({"status": "blocked", "missing_pdf": required, "error_code": "DRAWING_FINAL_PDF_REQUIRED_FOR_NOTES"})
        return base
    pdf = inspect_pdf_text_layout(pdf_path)
    base["pdf"] = pdf
    if pdf.get("status") == "blocked":
        base.update({"status": "blocked", "missing_pdf": required, "error_code": pdf.get("error_code") or "DRAWING_NOTE_PDF_EVIDENCE_MISSING"})
        return base
    sheet_order = {str(name): index + 1 for index, name in enumerate((structure or {}).get("sheets") or [])}
    used_spans: set[tuple[int, int]] = set()
    for text in required:
        note_records = [item for item in notes if str(item.get("text") or "") == text]
        sheet = str(note_records[0].get("sheet") or "") if note_records else ""
        expected_page = sheet_order.get(sheet, 1)
        candidates = []
        for page in pdf.get("pages") or []:
            if int(page.get("page", 0)) != expected_page:
                continue
            for span_index, span in enumerate(page.get("textSpans") or []):
                if (expected_page, span_index) in used_spans:
                    continue
                if str(span.get("text") or "").strip() == text:
                    candidates.append((expected_page, span_index, span))
        if candidates:
            page_number, span_index, span = candidates[0]
            used_spans.add((page_number, span_index))
            base["pdf_matches"].append({
                "text": text,
                "page": page_number,
                "bbox_pt": list(span["bboxPt"]),
                "span_text": span.get("text", ""),
                "evidence_source": "pdf_vector_text_bbox",
            })
        else:
            base["missing_pdf"].append(text)
    if base["missing_structure"] or base["missing_position"] or base["missing_pdf"]:
        base.update({"status": "blocked", "error_code": "DRAWING_NOTE_EVIDENCE_INCOMPLETE"})
    return base


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
            dimensions[index]["rendered_text"] = str(match.get("text") or "")
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


def _with_rendered_note_boxes(structure: Mapping[str, Any], note_report: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 用最终 PDF 的注释文字框补齐 SolidWorks 未返回的注释范围。"""
    result = copy.deepcopy(dict(structure))
    notes = list(result.get("notes") or [])
    sheet_size = result.get("sheet_size") or {}
    try:
        width_m = float(sheet_size["width_m"])
        height_m = float(sheet_size["height_m"])
    except (KeyError, TypeError, ValueError):
        return result
    pdf_payload = note_report.get("pdf") or {}
    pages = {int(page.get("page")): page for page in (pdf_payload.get("pages") or [])}
    matches = list(note_report.get("pdf_matches") or [])
    for note in notes:
        if note.get("box"):
            continue
        text = str(note.get("text") or "")
        match = next((item for item in matches if item.get("text") == text), None)
        if not match or int(match.get("page", 0)) not in pages:
            continue
        page = pages[int(match["page"])]
        page_width = float(page["widthPt"])
        page_height = float(page["heightPt"])
        left, top, right, bottom = (float(value) for value in match["bbox_pt"])
        note["box"] = {
            "left": left / page_width * width_m,
            "bottom": (page_height - bottom) / page_height * height_m,
            "right": right / page_width * width_m,
            "top": (page_height - top) / page_height * height_m,
        }
        note["box_source"] = "pdf_vector_text"
        note["box_confidence"] = "high"
    result["notes"] = notes
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
    note_report = _note_report(spec, structure, pdf_path)
    reviewed_structure = structure
    if pdf_dimension_rendering and pdf_dimension_rendering.get("status") == "pass":
        reviewed_structure = _with_rendered_dimension_boxes(reviewed_structure, pdf_dimension_rendering)
    reviewed_structure = _with_rendered_note_boxes(reviewed_structure, note_report)
    layout = review_drawing_layout(reviewed_structure, preview_evidence=preview_evidence) if reviewed_structure else {
        "status": "blocked", "error_code": "DRAWING_STRUCTURE_EVIDENCE_MISSING", "findings": [], "checks": []
    }
    checks.extend(layout.get("checks") or [])
    findings.extend(layout.get("findings") or [])
    view_report = _view_report(spec, reviewed_structure)
    dimension_report = _required_dimension_report(spec, reviewed_structure)
    hole_report = _hole_report(spec, model_evidence)
    professional_annotation_report = _professional_annotation_report(spec, reviewed_structure)
    checks.append(_check("drawing-required-views", view_report["status"], f"必需视图 {view_report['required_count']} 项，缺失 {len(view_report['missing'])} 项", missing=view_report["missing"]))
    checks.append(_check("drawing-required-dimensions", dimension_report["status"], f"必需尺寸 {dimension_report['required_count']} 项，缺失 {len(dimension_report['missing'])} 项", missing=dimension_report["missing"]))
    checks.append(_check("drawing-hole-requirements", hole_report["status"], f"孔槽要求 {hole_report['required_count']} 项，缺失 {len(hole_report['missing'])} 项", missing=hole_report["missing"]))
    checks.append(_check(
        "drawing-professional-annotations",
        professional_annotation_report["status"],
        f"专业标注 {professional_annotation_report['required_count']} 项，缺失 {len(professional_annotation_report['missing'])} 项",
        missing=professional_annotation_report["missing"],
    ))
    model_dimensions_requested = bool(spec.get("insertModelDimensions", True))
    model_dimension_status = "pass"
    if model_dimensions_requested and not structure.get("dimensions") and not spec.get("requiredDimensions"):
        model_dimension_status = "fail"
        findings.append({
            "code": "DRAWING_MODEL_DIMENSIONS_MISSING",
            "severity": "fail",
            "message": "规格要求插入模型尺寸，但结构证据中没有读取到任何尺寸实体；请补充尺寸或显式设置 insertModelDimensions=false。",
        })
    checks.append(_check(
        "drawing-model-dimensions",
        model_dimension_status,
        "已读取模型尺寸实体" if model_dimension_status == "pass" else "规格要求模型尺寸，但工程图没有尺寸实体",
    ))
    checks.append(_check(
        "drawing-notes",
        note_report["status"],
        f"必需注释 {note_report['required_count']} 项，COM 缺失 {len(note_report['missing_structure'])} 项，PDF 缺失 {len(note_report['missing_pdf'])} 项",
        missing_structure=note_report["missing_structure"],
        missing_position=note_report["missing_position"],
        missing_pdf=note_report["missing_pdf"],
    ))
    if dimension_report["missing"]:
        findings.append({"code": "DRAWING_REQUIRED_DIMENSIONS_MISSING", "severity": "fail", "missing": dimension_report["missing"]})
    if view_report["missing"]:
        findings.append({"code": "DRAWING_REQUIRED_VIEWS_MISSING", "severity": "fail", "missing": view_report["missing"]})
    if hole_report["missing"]:
        findings.append({"code": "DRAWING_HOLE_REQUIREMENTS_MISSING", "severity": "fail", "missing": hole_report["missing"]})
    if professional_annotation_report["missing"]:
        findings.append({"code": "DRAWING_PROFESSIONAL_ANNOTATIONS_MISSING", "severity": "fail", "missing": professional_annotation_report["missing"]})
    if note_report["status"] != "pass":
        findings.append({
            "code": note_report["error_code"] or "DRAWING_NOTE_EVIDENCE_INCOMPLETE",
            "severity": "fail",
            "missing_structure": note_report["missing_structure"],
            "missing_position": note_report["missing_position"],
            "missing_pdf": note_report["missing_pdf"],
        })

    bom_report = _bom_report(spec, structure)
    checks.append(_check(
        "drawing-bom",
        bom_report["status"],
        f"BOM要求={bom_report['required']}，BOM表={len(bom_report.get('tables') or [])}，可验证={bom_report.get('usable_table_count', 0)}",
        reason=bom_report.get("reason"),
    ))
    if bom_report["status"] != "pass":
        findings.append({
            "code": "DRAWING_BOM_TABLE_MISSING" if bom_report["status"] == "fail" else "DRAWING_BOM_CONTENT_UNVERIFIED",
            "severity": "fail" if bom_report["status"] == "fail" else "warning",
            "message": "装配工程图未读取到 BOM 表结构" if bom_report["status"] == "fail" else "BOM 类型存在，但数据行或配置尚未完成结构化回读",
        })

    title_block_report = _title_block_report(spec, structure)
    checks.append(_check(
        "drawing-title-block",
        title_block_report["status"],
        "标题栏字段已结构化核验" if title_block_report["status"] == "pass" else "标题栏结构或字段证据不完整",
        mismatches=title_block_report.get("mismatches") or [],
        content_verified=title_block_report.get("content_verified"),
    ))
    if title_block_report["status"] != "pass":
        findings.append({
            "code": "DRAWING_TITLE_BLOCK_MISSING" if title_block_report["status"] == "fail" and "candidate" in title_block_report.get("mismatches", []) else "DRAWING_TITLE_BLOCK_CONTENT_UNVERIFIED",
            "severity": "fail" if title_block_report["status"] == "fail" else "warning",
            "message": "标题栏结构证据缺失" if "candidate" in title_block_report.get("mismatches", []) else "标题栏候选存在，但字段内容未完成结构化核验",
            "mismatches": title_block_report.get("mismatches") or [],
        })

    pdf_report = None
    if pdf_path:
        pdf_report = inspect_pdf_text_layout(pdf_path)
        checks.append(_check("drawing-pdf-text-layout", "warning" if pdf_report.get("overlaps") or pdf_report.get("status") == "blocked" else "pass", pdf_report.get("message", "PDF文字边界已检查")))
        if pdf_report.get("overlaps"):
            findings.append({"code": "DRAWING_PDF_TEXT_OVERLAP_RISK", "severity": "fail", "overlaps": pdf_report["overlaps"]})
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
    semantic_review_required = any(
        report.get("status") == "review_required"
        for report in (bom_report, title_block_report)
    )
    status = (
        "blocked"
        if layout.get("status") == "blocked" or rendering_status == "blocked" or note_report["status"] == "blocked" or (pdf_report and pdf_report.get("overlaps"))
        else "review_required"
        if fail_findings or semantic_review_required or layout.get("status") != "pass" or rendering_status != "pass" or validation["status"] == "pilot"
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
        "view_evidence": view_report,
        "dimension_evidence": dimension_report,
        "hole_evidence": hole_report,
        "professional_annotation_evidence": professional_annotation_report,
        "bom_evidence": bom_report,
        "title_block_evidence": title_block_report,
        "note_evidence": note_report,
        "pdf_evidence": pdf_report,
        "pdf_dimension_rendering": pdf_dimension_rendering,
        "manual_review_required": status != "pass",
        "error_code": "DRAWING_REVIEW_FINDINGS" if fail_findings else "DRAWING_SEMANTIC_EVIDENCE_INCOMPLETE" if semantic_review_required else pdf_dimension_rendering.get("error_code") if rendering_status != "pass" else layout.get("error_code"),
        "capability_level": "pilot",
    }
