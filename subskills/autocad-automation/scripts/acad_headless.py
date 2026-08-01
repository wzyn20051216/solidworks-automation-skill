"""@file acad_headless.py
@brief 使用 ezdxf 只读检查 DXF，并可选生成无头 PNG 预览。

该后端不读取或写入 DWG，不执行 AutoLISP，也不会修改源 DXF。最终 DWG/PDF
交付仍必须经过 AutoCAD COM 和原生打开复核。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DIMENSION_TYPES = {
    "DIMENSION",
    "ARC_DIMENSION",
    "LARGE_RADIAL_DIMENSION",
}
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
TITLE_KEYWORDS = ("图号", "名称", "材料", "比例", "单位", "设计", "审核", "CAD STUDIO")
LAYER_GROUPS = {
    "outline": {"OUTLINE", "OBJECT", "VISIBLE", "粗实线", "轮廓"},
    "center": {"CENTER", "CENTRE", "CENTERLINE", "中心线"},
    "hidden": {"HIDDEN", "HIDE", "虚线"},
    "dimension": {"DIM", "DIMS", "DIMENSION", "尺寸"},
    "text": {"TEXT", "NOTE", "ANNOTATION", "文字"},
    "frame": {"FRAME", "BORDER", "TITLEBLOCK", "TITLE_BLOCK", "图框", "标题栏"},
}


def _layer_details(document) -> list[dict[str, Any]]:
    """@brief 收集图层显示、打印、颜色和线型证据。"""
    details = []
    for layer in document.layers:
        details.append({
            "name": str(layer.dxf.name),
            "color": int(layer.color),
            "linetype": str(layer.dxf.linetype),
            "off": bool(layer.is_off()),
            "frozen": bool(layer.is_frozen()),
            "locked": bool(layer.is_locked()),
            "plot": bool(layer.dxf.get("plot", 1)),
        })
    return details


def _entity_text(entity) -> str:
    """@brief 读取 TEXT/MTEXT/属性文字，失败时返回空字符串。"""
    try:
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text())
        return str(entity.dxf.get("text", ""))
    except Exception:
        return ""


def _dimension_evidence(entity) -> dict[str, Any]:
    """@brief 提取真实 DXF 尺寸实体的可审计字段。"""
    measurement = None
    try:
        measurement = float(entity.get_measurement())
    except Exception:
        pass
    return {
        "type": entity.dxftype(),
        "layer": str(entity.dxf.layer),
        "measurement": measurement,
        "dimstyle": str(entity.dxf.get("dimstyle", "")),
        "textOverride": str(entity.dxf.get("text", "")),
    }


def _hole_evidence(entity) -> dict[str, Any]:
    """@brief 提取圆孔中心、直径和图层证据。"""
    center = entity.dxf.center
    radius = float(entity.dxf.radius)
    return {
        "layer": str(entity.dxf.layer),
        "center": [float(center.x), float(center.y)],
        "radius": radius,
        "diameter": radius * 2.0,
    }


def _frame_candidates(modelspace) -> list[dict[str, Any]]:
    """@brief 查找尺寸接近常见图幅比例的闭合轻量多段线。"""
    candidates = []
    paper_ratios = (420 / 297, 297 / 210)
    for entity in modelspace.query("LWPOLYLINE"):
        if not bool(entity.closed):
            continue
        points = [(float(x), float(y)) for x, y in entity.get_points("xy")]
        if len(points) < 4:
            continue
        xs = [item[0] for item in points]
        ys = [item[1] for item in points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if min(width, height) < 120:
            continue
        ratio = max(width, height) / max(1e-9, min(width, height))
        if min(abs(ratio - expected) for expected in paper_ratios) > 0.15:
            continue
        candidates.append({
            "layer": str(entity.dxf.layer),
            "width": width,
            "height": height,
            "bbox": [[min(xs), min(ys)], [max(xs), max(ys)]],
        })
    return candidates


def _layer_group_checks(layer_names: list[str]) -> dict[str, bool]:
    """@brief 按中英文常用别名检查机械图纸关键图层。"""
    normalized = {name.strip().upper() for name in layer_names}
    return {
        group: any(alias.upper() in normalized for alias in aliases)
        for group, aliases in LAYER_GROUPS.items()
    }


def _engineering_evaluation(
    *,
    layer_checks: dict[str, bool],
    dimension_count: int,
    frame_count: int,
    title_keywords: list[str],
    hole_count: int,
) -> dict[str, Any]:
    """@brief 根据结构化证据给出机械图纸复核状态和问题码。"""
    issues = []
    if not layer_checks["outline"]:
        issues.append({"code": "drawing-layer-outline", "message": "缺少轮廓/粗实线图层"})
    if not layer_checks["dimension"] or dimension_count == 0:
        issues.append({"code": "drawing-true-dimensions", "message": "缺少 DIM 图层或真实 DIMENSION 实体"})
    if not layer_checks["frame"] or frame_count == 0:
        issues.append({"code": "drawing-frame", "message": "缺少图框图层或常见图幅闭合边框"})
    if len(title_keywords) < 3:
        issues.append({"code": "drawing-title-block", "message": "标题栏字段证据不足"})
    if hole_count and not layer_checks["center"]:
        issues.append({"code": "drawing-hole-centers", "message": "检测到圆孔但缺少中心线图层"})
    return {
        "status": "pass" if not issues else "warn",
        "issues": issues,
        "manualReviewRequired": True,
    }


def inspect_dxf(source: str | Path) -> dict[str, Any]:
    """@brief 只读检查 DXF 的图层、尺寸、图框、孔位和包围盒。"""
    try:
        import ezdxf
        from ezdxf import bbox
    except ImportError as exc:
        raise RuntimeError("缺少可选依赖 ezdxf，请执行: python -m pip install ezdxf") from exc

    path = Path(source).expanduser().resolve()
    if path.suffix.lower() != ".dxf":
        raise ValueError("无头后端只接受 DXF；DWG 必须使用 AutoCAD COM 只读打开")
    if not path.is_file():
        raise FileNotFoundError(path)
    document = ezdxf.readfile(path)
    modelspace = document.modelspace()
    type_counts = Counter(entity.dxftype() for entity in modelspace)
    layer_counts = Counter(str(entity.dxf.layer) for entity in modelspace)
    dimensions = [
        _dimension_evidence(entity)
        for entity in modelspace
        if entity.dxftype() in DIMENSION_TYPES
    ]
    holes = [
        _hole_evidence(entity)
        for entity in modelspace
        if entity.dxftype() == "CIRCLE"
    ]
    text_values = [
        _entity_text(entity).strip()
        for entity in modelspace
        if entity.dxftype() in TEXT_TYPES and _entity_text(entity).strip()
    ]
    keyword_matches = sorted({
        keyword
        for keyword in TITLE_KEYWORDS
        if any(keyword.casefold() in text.casefold() for text in text_values)
    })
    layer_details = _layer_details(document)
    layer_checks = _layer_group_checks([item["name"] for item in layer_details])
    frames = _frame_candidates(modelspace)
    extents = bbox.extents(modelspace, fast=True)
    bbox_value = None
    if extents.has_data:
        bbox_value = [list(extents.extmin), list(extents.extmax)]
    return {
        "schemaVersion": "2.0",
        "status": "ok",
        "backend": "ezdxf-readonly",
        "source": path.name,
        "fileSize": path.stat().st_size,
        "dxfVersion": document.dxfversion,
        "units": int(document.header.get("$INSUNITS", 0)),
        "entityCount": sum(type_counts.values()),
        "typeCounts": dict(type_counts),
        "layerCounts": dict(layer_counts),
        "layers": [item["name"] for item in layer_details],
        "layerDetails": layer_details,
        "bbox": bbox_value,
        "dimensionEvidence": dimensions,
        "trueDimensionEntityCount": len(dimensions),
        "holeEvidence": holes,
        "frameCandidates": frames,
        "titleTextKeywords": keyword_matches,
        "engineeringChecks": {
            "layerGroups": layer_checks,
            "hasTrueDimensions": bool(dimensions),
            "hasFrameCandidate": bool(frames),
            "hasTitleBlockEvidence": len(keyword_matches) >= 3,
            "hasHoleCenters": not holes or layer_checks["center"],
        },
        "evaluation": _engineering_evaluation(
            layer_checks=layer_checks,
            dimension_count=len(dimensions),
            frame_count=len(frames),
            title_keywords=keyword_matches,
            hole_count=len(holes),
        ),
        "limitations": ["只读 DXF 检查", "不替代 AutoCAD 原生 DWG/PDF 复核"],
    }


def render_dxf(source: str | Path, output: str | Path) -> dict[str, Any]:
    """@brief 使用 ezdxf/matplotlib 渲染只读 PNG 预览。"""
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("生成 PNG 预览需要 ezdxf 和 matplotlib") from exc

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path.suffix.lower() != ".dxf" or output_path.suffix.lower() != ".png":
        raise ValueError("预览输入必须是 DXF，输出必须是 PNG")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.readfile(source_path)
    figure = plt.figure(figsize=(12, 8), dpi=140)
    axes = figure.add_axes([0.02, 0.02, 0.96, 0.96])
    axes.set_aspect("equal")
    axes.axis("off")
    context = RenderContext(document)
    Frontend(context, MatplotlibBackend(axes)).draw_layout(document.modelspace(), finalize=True)
    figure.savefig(output_path, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(figure)
    pixel_check: dict[str, Any] = {}
    try:
        from PIL import Image

        with Image.open(output_path) as image:
            rgb = image.convert("RGB")
            sampled = rgb.resize((96, 64))
            unique_colors = len(set(sampled.getdata()))
            pixel_check = {
                "width": image.width,
                "height": image.height,
                "uniqueSampleColors": unique_colors,
                "likelyBlank": unique_colors < 8,
            }
    except Exception as exc:
        pixel_check = {"error": str(exc), "likelyBlank": None}
    return {
        "status": "ok" if not pixel_check.get("likelyBlank") else "warn",
        "backend": "ezdxf-matplotlib",
        "path": output_path.name,
        "size": output_path.stat().st_size,
        "pixelCheck": pixel_check,
    }


def main(argv: list[str] | None = None) -> int:
    """@brief CLI 入口。"""
    parser = argparse.ArgumentParser(description="使用 ezdxf 只读检查/预览 DXF")
    parser.add_argument("source", type=Path)
    parser.add_argument("--preview", type=Path, help="可选 PNG 预览输出")
    parser.add_argument("--json", type=Path, help="可选 JSON 报告输出")
    args = parser.parse_args(argv)
    report = inspect_dxf(args.source)
    if args.preview:
        report["preview"] = render_dxf(args.source, args.preview)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
