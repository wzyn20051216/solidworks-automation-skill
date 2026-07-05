# -*- coding: utf-8 -*-
"""@file acad_draw.py
@brief 通过 JSON brief 驱动 AutoCAD 绘图。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from acad_session import AutoCADSession


def load_brief(path: str | Path) -> Dict[str, Any]:
    """@brief 读取绘图 brief。"""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("绘图 brief 顶层必须是 JSON 对象。")
    return data


def draw_entity(session: AutoCADSession, entity: Dict[str, Any]) -> None:
    """@brief 按单个实体描述绘图。"""
    etype = str(entity.get("type", "")).lower()
    layer = entity.get("layer")
    color = entity.get("color")

    if etype == "line":
        session.add_line(entity["start"], entity["end"], layer=layer, color=color)
    elif etype == "circle":
        session.add_circle(entity["center"], entity["radius"], layer=layer, color=color)
    elif etype == "polyline":
        session.add_lwpolyline(
            entity["points"],
            closed=bool(entity.get("closed", False)),
            layer=layer,
            color=color,
        )
    elif etype == "rectangle":
        session.add_rectangle(
            entity["origin"],
            width=entity["width"],
            height=entity["height"],
            layer=layer,
            color=color,
        )
    elif etype == "text":
        session.add_text(
            entity["text"],
            entity["point"],
            height=entity.get("height", 2.5),
            layer=layer,
            color=color,
        )
    elif etype == "mtext":
        session.add_mtext(
            entity["text"],
            entity["point"],
            width=entity.get("width", 80),
            layer=layer,
            color=color,
        )
    else:
        raise ValueError(f"暂不支持实体类型: {etype!r}")


def _is_live_enabled(brief: Dict[str, Any], fast_mode: bool) -> bool:
    """@brief 判断是否启用可视化逐步绘图。"""
    if fast_mode:
        return False
    return bool(brief.get("live_preview", True))


def run(
    brief: Dict[str, Any],
    output: str | Path | None,
    new_document: bool,
    source: str | Path | None,
    fast_mode: bool,
    step_delay_s: float,
) -> Dict[str, Any]:
    """@brief 执行绘图 brief。"""
    session = AutoCADSession(create_if_missing=True, visible=True).connect()
    live_enabled = _is_live_enabled(brief, fast_mode)
    live_zoom_every = max(1, int(brief.get("live_zoom_every", 6)))
    if source:
        session.open_document(source)
    elif new_document or session.doc is None:
        session.new_document(brief.get("template"))
    if live_enabled:
        session.live_update(step_delay_s=step_delay_s, zoom=True)

    for layer in brief.get("layers", []):
        session.create_layer(
            str(layer["name"]),
            color=layer.get("color"),
            linetype=layer.get("linetype"),
        )
        if live_enabled:
            session.live_update(step_delay_s=step_delay_s, zoom=False)

    entities = brief.get("entities", [])
    for index, entity in enumerate(entities, start=1):
        draw_entity(session, entity)
        if live_enabled:
            session.live_update(
                step_delay_s=step_delay_s,
                zoom=(index == 1 or index % live_zoom_every == 0 or index == len(entities)),
            )

    session.regen()
    session.zoom_extents()

    saved_path = None
    target = output or brief.get("output")
    if target:
        saved_path = str(session.save_as(target))

    return {
        "status": "ok",
        "units": brief.get("units", "mm"),
        "entity_count": len(entities),
        "saved_path": saved_path,
        "live_preview": live_enabled,
        "step_delay_s": step_delay_s if live_enabled else 0.0,
    }


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="按 JSON brief 在 AutoCAD 中绘图")
    parser.add_argument("--input", required=True, help="绘图 JSON brief")
    parser.add_argument("--output", help="输出 DWG/DXF 路径")
    parser.add_argument("--source", help="要修改的既有 DWG/DXF")
    parser.add_argument("--new", action="store_true", help="新建文档")
    parser.add_argument("--fast", action="store_true", help="关闭逐步绘图，改为快速批量生成")
    parser.add_argument("--step-delay", type=float, default=0.12, help="逐步绘图时每一步停顿秒数")
    args = parser.parse_args()

    brief = load_brief(args.input)
    result = run(brief, args.output, args.new, args.source, args.fast, max(0.0, args.step_delay))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
