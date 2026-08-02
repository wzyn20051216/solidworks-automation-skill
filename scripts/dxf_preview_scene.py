"""@file dxf_preview_scene.py
@brief 将 DXF 只读转换为浏览器可安全消费的 PreviewScene JSON。

该转换器不执行 AutoLISP、不解析 DWG，也不修改源文件。超出白名单的实体会记录为限制，
而不是交给浏览器执行或静默宣称完整显示。
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


MAX_DXF_BYTES = 50 * 1024 * 1024
MAX_ENTITIES = 200_000
SUPPORTED_TYPES = {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "DIMENSION"}
LAYER_COLORS = {
    "OUTLINE": "#25312f",
    "HOLES": "#176c65",
    "CENTER": "#8a9a95",
    "DIMENSION": "#b36b22",
    "FRAME": "#25312f",
    "TITLE": "#4f7770",
    "TEXT": "#42514e",
}


def _point(value: Any) -> list[float]:
    """@brief 将 ezdxf Vec3 或二元序列转换为有限二维坐标。"""
    x = float(value.x if hasattr(value, "x") else value[0])
    y = float(value.y if hasattr(value, "y") else value[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("DXF 包含非有限坐标")
    return [x, y]


def _circle_points(center: Any, radius: float, start: float = 0.0, end: float = 360.0) -> list[list[float]]:
    """@brief 将圆或圆弧离散为稳定的浏览器折线。"""
    cx, cy = _point(center)
    sweep = (end - start) % 360.0 or 360.0
    segments = max(12, min(96, int(math.ceil(sweep / 6.0))))
    return [
        [cx + math.cos(math.radians(start + sweep * index / segments)) * radius, cy + math.sin(math.radians(start + sweep * index / segments)) * radius]
        for index in range(segments + 1)
    ]


def _dimension_points(entity: Any) -> list[list[float]]:
    """@brief 提取真实 DIMENSION 定义点，避免依赖渲染块内部实现。"""
    points = []
    for name in ("defpoint2", "defpoint3", "defpoint", "text_midpoint"):
        if entity.dxf.hasattr(name):
            try:
                points.append(_point(entity.dxf.get(name)))
            except (TypeError, ValueError):
                continue
    return points


def _entity_payload(entity: Any) -> dict[str, Any] | None:
    """@brief 把白名单 DXF 实体转换为 PreviewScene 实体。"""
    kind = entity.dxftype()
    layer = str(entity.dxf.get("layer", "0"))
    handle = str(entity.dxf.get("handle", "")) or f"{kind.lower()}-{id(entity)}"
    base: dict[str, Any] = {
        "id": handle,
        "kind": kind.lower(),
        "layer": layer,
        "color": LAYER_COLORS.get(layer.upper(), "#42514e"),
        "evidenceRefs": [f"dxf:{handle}", f"layer:{layer}"],
    }
    if kind == "LINE":
        base["points"] = [_point(entity.dxf.start), _point(entity.dxf.end)]
    elif kind == "CIRCLE":
        base["kind"] = "circle"
        base["points"] = _circle_points(entity.dxf.center, float(entity.dxf.radius))
    elif kind == "ARC":
        base["kind"] = "arc"
        base["points"] = _circle_points(entity.dxf.center, float(entity.dxf.radius), float(entity.dxf.start_angle), float(entity.dxf.end_angle))
    elif kind == "LWPOLYLINE":
        points = [[float(x), float(y)] for x, y in entity.get_points("xy")]
        if entity.closed and points:
            points.append(points[0])
        base["kind"] = "polyline"
        base["points"] = points
    elif kind == "POLYLINE":
        points = [_point(vertex.dxf.location) for vertex in entity.vertices]
        if entity.is_closed and points:
            points.append(points[0])
        base["kind"] = "polyline"
        base["points"] = points
    elif kind in {"TEXT", "MTEXT"}:
        base["kind"] = "text"
        base["text"] = str(entity.plain_text() if kind == "MTEXT" else entity.dxf.get("text", ""))[:4096]
        base["points"] = [_point(entity.dxf.insert)]
    elif kind == "DIMENSION":
        base["kind"] = "dimension"
        try:
            measurement = float(entity.get_measurement())
            base["text"] = f"{measurement:g}" if math.isfinite(measurement) else "DIM"
        except (TypeError, ValueError, AttributeError):
            base["text"] = str(entity.dxf.get("text", "DIM"))[:256]
        base["points"] = _dimension_points(entity)
    else:
        return None
    if not base.get("points"):
        return None
    return base


def _bounds(entities: Iterable[dict[str, Any]]) -> dict[str, float]:
    """@brief 计算场景二维包围盒。"""
    points = [point for entity in entities for point in entity.get("points", [])]
    if not points:
        return {"minX": 0.0, "minY": 0.0, "maxX": 1.0, "maxY": 1.0}
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys)}


def dxf_to_preview_scene(source: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    """@brief 只读解析 DXF，返回并可选写出 PreviewScene 1.0。"""
    import ezdxf

    source_path = Path(source).expanduser().resolve()
    if source_path.suffix.lower() != ".dxf":
        raise ValueError("PreviewScene 转换只接受 DXF")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.stat().st_size > MAX_DXF_BYTES:
        raise ValueError(f"DXF 超过 {MAX_DXF_BYTES // 1024 // 1024} MB 安全上限")
    document = ezdxf.readfile(source_path)
    modelspace = document.modelspace()
    entities = []
    unsupported = Counter()
    for index, entity in enumerate(modelspace):
        if index >= MAX_ENTITIES:
            raise ValueError(f"DXF 实体数超过 {MAX_ENTITIES} 安全上限")
        if entity.dxftype() not in SUPPORTED_TYPES:
            unsupported[entity.dxftype()] += 1
            continue
        payload = _entity_payload(entity)
        if payload:
            entities.append(payload)
    layer_counts = Counter(str(entity.get("layer") or "0") for entity in entities)
    layers = [
        {"name": name, "color": LAYER_COLORS.get(name.upper(), "#42514e"), "count": count, "visible": True}
        for name, count in sorted(layer_counts.items())
    ]
    warnings = [f"未显示 {kind}: {count}" for kind, count in sorted(unsupported.items())]
    scene = {
        "schemaVersion": "1.0",
        "kind": "dxf-scene",
        "sourceArtifact": source_path.name,
        "units": "mm" if int(document.header.get("$INSUNITS", 0)) == 4 else "unitless",
        "bounds": _bounds(entities),
        "entities": entities,
        "layers": layers,
        "warnings": warnings,
        "limitations": ["只读 PreviewScene，不修改 DXF", *warnings],
    }
    if output is not None:
        target = Path(output).expanduser().resolve()
        if target.suffix.lower() != ".json" or not target.name.lower().endswith(".scene.json"):
            raise ValueError("PreviewScene 输出必须使用 .scene.json 后缀")
        if target.exists():
            raise FileExistsError(f"拒绝覆盖已有 PreviewScene: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    return scene


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="将 DXF 转换为安全 PreviewScene JSON")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    scene = dxf_to_preview_scene(args.source, args.output)
    print(json.dumps({"status": "pass", "output": str(args.output), "entities": len(scene["entities"]), "layers": len(scene["layers"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
