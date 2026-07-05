# -*- coding: utf-8 -*-
"""@file acad_review.py
@brief 复核 AutoCAD 图纸的实体、图层和包围盒。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from acad_session import AutoCADSession, point_tuple


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """@brief 安全读取 COM 属性。"""
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _entity_bbox(entity: Any) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """@brief 获取实体包围盒；不支持时返回 None。"""
    try:
        min_pt, max_pt = entity.GetBoundingBox()
        return point_tuple(min_pt), point_tuple(max_pt)
    except Exception:
        return None


def _merge_bbox(
    current: Optional[List[List[float]]],
    bbox: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
) -> List[List[float]]:
    """@brief 合并全局包围盒。"""
    min_pt, max_pt = bbox
    if current is None:
        return [list(min_pt), list(max_pt)]
    for i in range(3):
        current[0][i] = min(current[0][i], min_pt[i])
        current[1][i] = max(current[1][i], max_pt[i])
    return current


def review_active(session: AutoCADSession) -> Dict[str, Any]:
    """@brief 复核当前活动文档。"""
    doc = session.active_document()
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    bbox_global: Optional[List[List[float]]] = None
    bbox_failures = 0

    for entity in session.iter_model_entities():
        object_name = str(_safe_getattr(entity, "ObjectName", "Unknown"))
        layer_name = str(_safe_getattr(entity, "Layer", "Unknown"))
        type_counts[object_name] += 1
        layer_counts[layer_name] += 1
        bbox = _entity_bbox(entity)
        if bbox is None:
            bbox_failures += 1
        else:
            bbox_global = _merge_bbox(bbox_global, bbox)

    full_name = str(_safe_getattr(doc, "FullName", ""))
    file_exists = bool(full_name and Path(full_name).exists())
    file_size = Path(full_name).stat().st_size if file_exists else None

    return {
        "status": "ok",
        "document": str(_safe_getattr(doc, "Name", "")),
        "full_name": full_name,
        "file_exists": file_exists,
        "file_size": file_size,
        "modelspace_entity_count": sum(type_counts.values()),
        "type_counts": dict(type_counts),
        "layer_counts": dict(layer_counts),
        "bbox": bbox_global,
        "bbox_failures": bbox_failures,
    }


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="复核 AutoCAD 当前或指定图纸")
    parser.add_argument("target", nargs="?", help="可选：要打开并复核的 DWG/DXF")
    parser.add_argument("--launch", action="store_true", help="允许启动 AutoCAD")
    parser.add_argument("--json", help="保存复核报告 JSON")
    args = parser.parse_args()

    session = AutoCADSession(create_if_missing=args.launch, visible=True).connect()
    if args.target:
        session.open_document(args.target, read_only=True)
    report = review_active(session)
    session.zoom_extents()

    if args.json:
        out = Path(args.json).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(out)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

