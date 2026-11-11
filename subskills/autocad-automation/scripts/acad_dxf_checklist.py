"""依据项目模板量测选定 DXF 布局。布局与制造语义仍须人工复核。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


PAPER_MM = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}
TEMPLATE_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "dxf-checklist-template.schema.json"


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("DXF 检查模板只能使用有限数值")
    return number


def load_template(path: Path) -> dict[str, Any]:
    from jsonschema import Draft202012Validator

    template = json.loads(path.read_text(encoding="utf-8-sig"), parse_float=_finite_float, parse_constant=_finite_float)
    schema = json.loads(TEMPLATE_SCHEMA.read_text(encoding="utf-8"))
    errors = Draft202012Validator(schema).iter_errors(template)
    error = next(errors, None)
    if error is not None:
        field = ".".join(map(str, error.absolute_path)) or "template"
        raise ValueError(f"DXF 检查模板 {field} 无效: {error.message}")
    return template


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _visible_entities(document, entities, parent_layer: str = "0", depth: int = 0):
    """保留尺寸实体和块属性，同时解析普通嵌套块及其 0 图层继承。"""
    for entity in entities:
        layer = entity.dxf.get("layer", "0")
        layer = (parent_layer if layer == "0" else layer).casefold()
        if entity.dxf.get("invisible", 0):
            continue
        if document.layers.has_entry(layer):
            record = document.layers.get(layer)
            if record.is_off() or record.is_frozen() or not record.dxf.get("plot", 1):
                continue
        if entity.dxftype() == "INSERT":
            block = document.blocks.get(entity.dxf.name)
            if depth >= 12 or block is None or block.block.is_xref:
                continue
            for insert in (entity.multi_insert() if entity.mcount > 1 else (entity,)):
                attributes = (attr for attr in insert.attribs if not attr.is_invisible)
                yield from _visible_entities(document, attributes, layer, depth + 1)
                yield from _visible_entities(document, insert.virtual_entities(), layer, depth + 1)
        else:
            yield layer, entity


def _rectangle(entity):
    if entity.dxftype() != "LWPOLYLINE" or not entity.closed or len(entity) != 4:
        return None
    points = list(entity.get_points("xyb"))
    if any(bulge for _, _, bulge in points) or entity.dxf.extrusion != (0, 0, 1):
        return None
    xy = [(round(x, 8), round(y, 8)) for x, y, _ in points]
    xs, ys = sorted({x for x, _ in xy}), sorted({y for _, y in xy})
    if len(xs) != 2 or len(ys) != 2 or len(set(xy)) != 4:
        return None
    if any((a[0] == b[0]) == (a[1] == b[1]) for a, b in zip(xy, xy[1:] + xy[:1])):
        return None
    return (xs[0], ys[0], xs[1], ys[1])


def _size(bounds):
    return [bounds[2] - bounds[0], bounds[3] - bounds[1]]


def _fits(actual, expected, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def _inside(inner, outer, tolerance):
    return (inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance
            and inner[2] <= outer[2] + tolerance and inner[3] <= outer[3] + tolerance)


def _text(entity):
    if entity.dxftype() in {"TEXT", "MTEXT", "ATTRIB"}:
        return entity.plain_text().strip()
    return ""


def _text_in_bounds(entity, bounds, tolerance):
    point = entity.dxf.insert if entity.dxftype() == "MTEXT" else entity.get_placement()[1]
    return _inside((point.x, point.y, point.x, point.y), bounds, tolerance)


def dimension_measurement(entity) -> float | None:
    try:
        if entity.dxftype() == "DIMENSION" and entity.dimtype == 1:
            # 对齐尺寸由 WCS 定义点给出，不能投影到默认水平旋转角。
            measurement = entity.dxf.defpoint2.distance(entity.dxf.defpoint3)
        else:
            measurement = float(entity.get_measurement())
        return measurement if math.isfinite(measurement) else None
    except (AttributeError, TypeError, ValueError, NotImplementedError):
        return None


def check_drawing(document, template: dict[str, Any], *, digest: str) -> dict[str, Any]:
    """返回机器量测结果及独立的人工审图事项。"""
    checks: list[dict[str, Any]] = []

    def record(name, passed, **evidence):
        checks.append({"id": name, "status": "pass" if passed else "fail", **evidence})

    layout_name = template.get("layout", "Model")
    try:
        layout = document.layouts.get(layout_name)
    except KeyError as exc:
        raise ValueError(f"DXF 中不存在模板指定的布局: {layout_name}") from exc
    units = document.header.get("$INSUNITS", 0) if layout.is_modelspace else layout.dxf_layout.dxf.plot_paper_units
    millimetres = (units == 4 or (units == 0 and template.get("unitlessModelIsMm", False))) if layout.is_modelspace else units == 1
    record("units", millimetres, code=units, unitlessModelIsMm=template.get("unitlessModelIsMm", False))

    sheet = template["sheet"]
    width, height = PAPER_MM[sheet["size"]]
    if sheet["orientation"] == "portrait":
        width, height = height, width
    left, bottom, right, top = sheet.get("insetsMm", [0, 0, 0, 0])
    expected = [width - left - right, height - bottom - top]
    if min(expected) <= 0:
        raise ValueError("DXF 检查模板的图框内缩量超出图幅")
    tolerance = sheet.get("toleranceMm", 1)
    entities = list(_visible_entities(document, layout))
    frame_layers = {layer.casefold() for layer in template["frameLayers"]}
    title_layers = {layer.casefold() for layer in template["titleLayers"]}
    frames = [box for layer, entity in entities if layer in frame_layers and (box := _rectangle(entity))]
    matching_frames = [box for box in frames if _fits(_size(box), expected, tolerance)]
    frame = matching_frames[0] if len(matching_frames) == 1 else None
    record("sheet_frame", millimetres and frame is not None,
           expectedMm=expected, candidatesMm=[_size(box) for box in frames], matchingCount=len(matching_frames))

    title_boxes = [box for layer, entity in entities if layer in title_layers and (box := _rectangle(entity))
                   and frame and _inside(box, frame, tolerance)]
    if "titleSizeMm" in template:
        title_boxes = [box for box in title_boxes if _fits(_size(box), template["titleSizeMm"], tolerance)]
    if frame is not None and "titleAnchorMm" in template:
        title_boxes = [box for box in title_boxes
                       if _fits((box[0] - frame[0], box[1] - frame[1]), template["titleAnchorMm"], tolerance)]
    title = title_boxes[0] if len(title_boxes) == 1 else None
    record("title_frame", millimetres and title is not None,
           expectedMm=template.get("titleSizeMm"), expectedAnchorMm=template.get("titleAnchorMm"),
           candidatesMm=[_size(box) for box in title_boxes])
    title_text = [(entity, text) for layer, entity in entities if layer in title_layers
                  and (text := _text(entity)) and title and _text_in_bounds(entity, title, tolerance)]
    missing_fields = [field for field in template["titleFields"]
                      if not any(field.casefold() in text.casefold() for _, text in title_text)]
    record("title_fields", not missing_fields, missing=missing_fields)
    if "minTitleTextHeightMm" in template:
        heights = [entity.dxf.get("char_height" if entity.dxftype() == "MTEXT" else "height", 0)
                   for entity, _ in title_text]
        minimum = template["minTitleTextHeightMm"]
        record("title_text_height", millimetres and bool(heights) and min(heights) >= minimum,
               minimumMm=minimum, measuredMm=min(heights, default=None))

    dim_layers = {layer.casefold() for layer in template.get("dimensionLayers", [])}
    dimensions = [entity for layer, entity in entities if entity.dxftype() in {"DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION"}
                  and (not dim_layers or layer in dim_layers)]
    measurable = [value for entity in dimensions if (value := dimension_measurement(entity)) is not None and value > 0]
    overrides = [entity.dxf.handle for entity in dimensions if entity.dxf.get("text", "") not in ("", "<>")]
    minimum_count = template["minDimensions"]
    record("dimensions", len(measurable) >= minimum_count and len(measurable) == len(dimensions)
           and (template.get("allowDimensionOverrides", False) or not overrides),
           minimum=minimum_count, count=len(dimensions), measurements=measurable, overrides=overrides)
    if "expectedDimensionValues" in template:
        remaining = sorted(measurable)
        missing = []
        dimension_tolerance = template.get("dimensionTolerance", 0.01)
        for expected_value in sorted(template["expectedDimensionValues"]):
            match = next((index for index, value in enumerate(remaining)
                          if abs(value - expected_value) <= dimension_tolerance), None)
            if match is None:
                missing.append(expected_value)
            else:
                remaining.pop(match)
        record("expected_dimension_values", not missing, missing=missing, tolerance=dimension_tolerance)

    for layer, expected_weight in template.get("lineweightsMm", {}).items():
        measured = document.layers.get(layer).dxf.lineweight if document.layers.has_entry(layer) else None
        record("layer_lineweight", measured is not None and abs(measured / 100 - expected_weight) < 0.000001,
               layer=layer, expectedMm=expected_weight, measuredMm=measured / 100 if measured is not None and measured >= 0 else None)
    if "scaleLabel" in template:
        scale = template["scaleLabel"]
        pattern = re.compile(r"(?<![0-9:])" + re.escape(scale) + r"(?![0-9:])", re.IGNORECASE)
        record("scaleLabel", any(pattern.search(text) for _, text in title_text), expected=scale)
    if "projectionLabel" in template:
        projection = template["projectionLabel"]
        record("projectionLabel", any(projection.casefold() in text.casefold() for _, text in title_text),
               expected=projection)
    if "requiredNotes" in template:
        drawing_text = [_text(entity).casefold() for _, entity in entities]
        missing = [note for note in template["requiredNotes"] if not any(note.casefold() in text for text in drawing_text)]
        record("required_notes", not missing, missing=missing)

    passed = all(check["status"] == "pass" for check in checks)
    return {
        "schemaVersion": "1.0",
        "status": "review_required" if passed else "failed",
        "machineStatus": "pass" if passed else "fail",
        "sourceSha256": digest,
        "template": template,
        "layout": layout.name,
        "checks": checks,
        "manualReviewRequired": True,
        "manualChecks": [
            {"id": "dimension_clearance", "status": "review_required", "detail": "核对尺寸、引线及文字避让与打印可读性"},
            {"id": "drawing_semantics", "status": "review_required", "detail": "核对尺寸链、比例和投影表达、BOM 与技术要求"},
            {"id": "delivery", "status": "review_required", "detail": "核对原生图纸和归档版本"},
        ],
    }
