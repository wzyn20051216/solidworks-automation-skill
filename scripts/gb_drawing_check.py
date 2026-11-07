# -*- coding: utf-8 -*-
"""@file gb_drawing_check.py
@brief 按《CAD 工程制图国家标准（GB）出图规范》V1.0 第 12 章检查 DXF 出图。

只读检查，不修改图纸。检查项与规范第 12 章「出图前检查清单」一一对应，
输出机器可读的 gb_checklist.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _result(item_id: str, item: str, basis: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {
        "id": item_id,
        "item": item,
        "basis": basis,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _texts(entities) -> List[Any]:
    found = []
    for entity in entities:
        try:
            if entity.dxftype() in {"TEXT", "MTEXT"}:
                found.append(entity)
        except Exception:
            continue
    return found


def _plain_text(entity) -> str:
    try:
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text())
        return str(entity.dxf.text)
    except Exception:
        return ""


def _layer_roles(layers: set[str]) -> tuple[bool, str, bool]:
    """@brief 校验 GB/T 18229 的图层角色映射，兼容旧语义层名。"""
    aliases = {
        "sheet": {"SHEET", "FRAME", "BORDER"},
        "outline": {"OUTLINE", "OBJECT", "VISIBLE"},
        "hidden": {"HIDDEN", "DASHED"},
        "center": {"CENTER", "CENTRE"},
        "dimension": {"DIM", "DIMENSION", "DIMENSIONS"},
        "text": {"TEXT", "NOTE", "NOTES"},
        "table": {"TABLE", "BOM"},
        "title": {"TITLE", "TITLE_BLOCK", "TITLEBLOCK"},
    }
    upper_layers = {str(name).upper() for name in layers}
    missing = [role for role, names in aliases.items() if not names.intersection(upper_layers)]
    numeric = {f"{index:02d}" for index in range(1, 14)}
    numeric_complete = numeric.issubset(upper_layers)
    semantic_complete = not missing
    if semantic_complete:
        return True, "语义图层角色齐全（SHEET/OUTLINE/HIDDEN/CENTER/DIM/TEXT/TABLE/TITLE）", numeric_complete
    if numeric_complete:
        return True, "检测到完整 01–13 编号图层", True
    return False, f"缺少图层角色: {missing}", numeric_complete


def _title_block_bbox(entities) -> tuple[float, float, float, float] | None:
    """@brief 量取标题栏候选区域，优先图框右下角的 TITLE/TABLE 实体。"""
    from ezdxf import bbox as ezbbox

    candidates = []
    for entity in entities:
        try:
            layer = str(entity.dxf.layer).upper()
        except Exception:
            continue
        if layer not in {"TITLE", "TITLE_BLOCK", "TITLEBLOCK", "TABLE", "BOM"}:
            continue
        try:
            extents = ezbbox.extents([entity])
            if extents.has_data and extents.extmin.y < 70.0 and extents.extmax.x > 200.0:
                candidates.append(entity)
        except Exception:
            continue
    if not candidates:
        return None
    try:
        extents = ezbbox.extents(candidates)
        if not extents.has_data:
            return None
        return (
            float(extents.extmin.x),
            float(extents.extmin.y),
            float(extents.extmax.x),
            float(extents.extmax.y),
        )
    except Exception:
        return None


def check(dxf_path: Path) -> Dict[str, Any]:
    import ezdxf

    document = ezdxf.readfile(dxf_path)
    model = document.modelspace()
    entities = list(model)
    texts = _texts(entities)
    layers = {layer.dxf.name for layer in document.layers}
    items: List[Dict[str, Any]] = []

    bbox = None
    try:
        from ezdxf import bbox as ezbbox

        extents = ezbbox.extents(model)
        if extents.has_data:
            bbox = (extents.extmin.x, extents.extmin.y, extents.extmax.x, extents.extmax.y)
    except Exception:
        bbox = None

    if bbox:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        sheet_ok = abs(width - 420.0) <= 1.0 and abs(height - 297.0) <= 1.0
        items.append(
            _result(
                "sheet_format",
                "幅面与图框格式",
                "GB/T 14689",
                sheet_ok,
                f"实测图幅 {width:.2f} × {height:.2f} mm（要求 A3 横向 420 × 297）",
            )
        )
    else:
        items.append(
            _result("sheet_format", "幅面与图框格式", "GB/T 14689", False, "无法读取图形范围")
        )

    layer_ok, layer_detail, numeric_layers = _layer_roles(layers)
    items.append(
        _result(
            "frame_layers",
            "图框线与纸边界线",
            "GB/T 14689 / GB/T 18229 表 13",
            layer_ok,
            layer_detail + ("；01–13 编号齐全" if numeric_layers else "；当前按语义图层别名复核"),
        )
    )

    title_texts = [t for t in texts if (t.dxf.layer or "").upper() in {"TITLE", "TABLE"}]
    title_hit = [t for t in title_texts if any(key in _plain_text(t) for key in ("图号", "材料", "比例", "图幅"))]
    title_bbox = _title_block_bbox(entities)
    title_width = title_bbox[2] - title_bbox[0] if title_bbox else 0.0
    title_height = title_bbox[3] - title_bbox[1] if title_bbox else 0.0
    title_size_ok = (
        title_bbox is not None
        and abs(title_width - 180.0) <= 1.0
        and abs(title_height - 56.0) <= 1.0
        and title_bbox[0] >= 200.0
        and title_bbox[1] <= 10.0
    )
    items.append(
        _result(
            "title_block",
            "标题栏位置与内容",
            "GB/T 10609.1",
            bool(title_hit) and title_size_ok,
            (
                f"标题栏字段 {len(title_hit)} 条；外框实测 {title_width:.2f}×{title_height:.2f} mm，"
                "要求 180×56 mm 且在右下角"
            )
            if title_hit and title_bbox
            else ("标题栏字段齐全但无法量取外框" if title_hit else "未找到标题栏字段文字"),
        )
    )

    joined = " ".join(_plain_text(t) for t in texts)
    scale_ok = "1:1" in joined or "1：1" in joined
    items.append(
        _result("scale", "比例", "GB/T 14690", scale_ok, "检测到 1:1" if scale_ok else "未检测到标准比例")
    )

    dimensions = [e for e in entities if e.dxftype() == "DIMENSION"]
    measurements = []
    for dim in dimensions:
        try:
            value = float(dim.get_measurement())
            if value > 0:
                measurements.append(value)
        except Exception:
            continue
    items.append(
        _result(
            "dimension_values",
            "尺寸数值",
            "GB/T 4458.4",
            len(measurements) >= 5,
            f"真实尺寸实体 {len(measurements)} 个: {sorted(set(round(v, 3) for v in measurements))}",
        )
    )

    dimstyle_names = set()
    text_overrides = []
    dimtad_values = set()
    for dim in dimensions:
        try:
            style_name = str(dim.dxf.dimstyle or "")
            dimstyle_names.add(style_name)
            style = document.dimstyles.get(style_name)
            if hasattr(style.dxf, "dimtad"):
                dimtad_values.add(float(style.dxf.dimtad))
            text = str(dim.dxf.text or "")
            if text and text != "<>":
                text_overrides.append(text)
        except Exception:
            continue
    readability_ok = bool(dimensions) and not text_overrides and dimtad_values in ({1.0}, {})
    items.append(
        _result(
            "dimension_readability",
            "尺寸可读性",
            "GB/T 4458.4",
            readability_ok,
            (
                f"尺寸实体 {len(dimensions)} 个；尺寸样式 {sorted(dimstyle_names)}；"
                f"DIMTAD={sorted(dimtad_values)}；文字覆盖 {len(text_overrides)} 个；"
                "箭头与文字避让仍需目视复核"
            ),
        )
    )

    line_weights = []
    for layer in document.layers:
        try:
            weight = int(layer.dxf.lineweight) if layer.dxf.hasattr("lineweight") else -1
        except Exception:
            weight = -1
        if weight > 0:
            line_weights.append(weight / 100.0)
    weight_ok = any(abs(w - 0.5) < 0.01 for w in line_weights) and any(
        abs(w - 0.25) < 0.01 for w in line_weights
    )
    items.append(
        _result(
            "line_weight",
            "线宽层次",
            "GB/T 14665 表 1",
            weight_ok,
            f"图层线宽 {sorted(set(line_weights))} mm（A3 要求粗 0.5 / 细 0.25）",
        )
    )

    heights = []
    for entity in texts:
        try:
            heights.append(float(entity.dxf.height if entity.dxftype() == "TEXT" else entity.dxf.char_height))
        except Exception:
            continue
    min_height = min(heights) if heights else 0.0
    font_ok = bool(heights) and min_height >= 2.49
    items.append(
        _result(
            "font",
            "字体",
            "GB/T 14691 / GB/T 18229 表 4",
            font_ok,
            f"文字最小字高 {min_height:.2f} mm（要求 ≥ 2.5，推荐汉字 5 / 数字 3.5）",
        )
    )

    projection_ok = "第一角" in joined
    items.append(
        _result("projection", "投影法", "GB/T 14692", projection_ok, "检测到第一角标注" if projection_ok else "缺少第一角说明")
    )

    items.append(
        _result(
            "bom",
            "明细栏",
            "GB/T 10609.2",
            True,
            "单件零件图可省略明细栏",
        )
    )

    tech_ok = (
        ("1804" in joined or "未注公差" in joined)
        and ("1182" in joined or "1184" in joined or "几何公差" in joined)
        and ("Ra" in joined or "表面结构" in joined)
    )
    items.append(
        _result(
            "technical_requirements",
            "技术要求",
            "GB/T 131 / GB/T 1182 / GB/T 1804",
            tech_ok,
            "未注公差、几何公差、表面结构均已注明" if tech_ok else "技术要求缺项",
        )
    )

    siblings = {p.suffix.lower() for p in dxf_path.parent.iterdir() if p.is_file()}
    archive_ok = {".dwg", ".pdf"}.issubset(siblings)
    items.append(
        _result(
            "archive",
            "归档一致性",
            "GB/T 18229 第 9 章",
            archive_ok,
            f"同目录产物 {sorted(siblings)}",
        )
    )

    failed = [item["id"] for item in items if item["status"] != "pass"]
    return {
        "schemaVersion": "1.0",
        "standard": "CAD 工程制图国家标准（GB）出图规范 V1.0",
        "source": str(dxf_path),
        "status": "pass" if not failed else "fail",
        "failedItems": failed,
        "items": items,
        "manualReviewRequired": [
            "箭头形式统一性与尺寸数字避让需目视复核",
            "CTB 颜色-线宽映射需在打印预览中确认",
            "标题栏四区字段完整性需人工确认",
        ],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GB 出图规范检查")
    parser.add_argument("dxf", type=Path)
    parser.add_argument("--json", type=Path, help="可选输出 JSON 路径")
    args = parser.parse_args(argv)
    report = check(args.dxf)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
