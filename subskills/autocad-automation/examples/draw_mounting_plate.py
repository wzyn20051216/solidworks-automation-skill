# -*- coding: utf-8 -*-
"""@file draw_mounting_plate.py
@brief AutoCAD 自动绘制安装板示例。
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from acad_session import AutoCADSession  # noqa: E402


def main() -> int:
    """@brief 示例入口。"""
    output = Path(r"C:\temp\autocad_mounting_plate.dwg")
    session = AutoCADSession(create_if_missing=True, visible=True).connect()
    session.new_document()

    session.create_layer("OUTLINE", color=7)
    session.create_layer("HOLE", color=1)
    session.create_layer("TEXT", color=3)

    width = 120.0
    height = 80.0
    hole_r = 4.5
    margin = 15.0

    session.add_rectangle((0, 0), width, height, layer="OUTLINE")
    for x in (margin, width - margin):
        for y in (margin, height - margin):
            session.add_circle((x, y, 0), hole_r, layer="HOLE")
    session.add_text("MOUNTING PLATE 120x80, 4xR4.5", (5, height + 8, 0), 4, layer="TEXT")

    session.regen()
    session.zoom_extents()
    session.save_as(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

