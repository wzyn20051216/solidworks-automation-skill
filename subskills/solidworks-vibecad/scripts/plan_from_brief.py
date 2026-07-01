#!/usr/bin/env python
"""
从自然语言需求生成 SolidWorks 参数化设计计划。

本脚本是 VibeCAD 工作台的最小可运行闭环：它不直接控制 SolidWorks，
而是把需求收敛为可审查、可交给 SolidWorks API 封装执行的 JSON 计划。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


THREAD_RULES = {
    "M3": {"pitch": 0.5, "tap_drill": 2.5, "mouth_chamfer": 0.3},
    "M4": {"pitch": 0.7, "tap_drill": 3.3, "mouth_chamfer": 0.4},
    "M5": {"pitch": 0.8, "tap_drill": 4.2, "mouth_chamfer": 0.5},
    "M6": {"pitch": 1.0, "tap_drill": 5.0, "mouth_chamfer": 0.6},
    "M8": {"pitch": 1.25, "tap_drill": 6.8, "mouth_chamfer": 0.8},
    "M10": {"pitch": 1.5, "tap_drill": 8.5, "mouth_chamfer": 1.0},
    "M12": {"pitch": 1.75, "tap_drill": 10.2, "mouth_chamfer": 1.2},
}


def parse_triplet_mm(text: str) -> tuple[float, float, float] | None:
    """解析 90x60x8mm 这类尺寸。"""
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*mm",
        text,
    )
    if not match:
        return None
    return tuple(float(match.group(index)) for index in range(1, 4))


def parse_first_number_before(text: str, keywords: tuple[str, ...]) -> float | None:
    """解析关键词附近的第一个 mm 数值。"""
    pattern = r"(\d+(?:\.\d+)?)\s*mm\s*(?:" + "|".join(map(re.escape, keywords)) + r")"
    match = re.search(pattern, text)
    if match:
        return float(match.group(1))
    return None


def parse_radius_or_chamfer(text: str, prefix: str, default: float) -> float:
    """解析 R6、C1 等简写。"""
    match = re.search(rf"{re.escape(prefix)}\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    return float(match.group(1)) if match else default


def detect_thread(text: str) -> str | None:
    """识别 M3/M4/M5 等螺纹规格。"""
    match = re.search(r"\b(M(?:3|4|5|6|8|10|12))\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def build_plan(brief: str) -> dict:
    """构建设计计划。"""
    dims = parse_triplet_mm(brief) or (90.0, 60.0, 8.0)
    length, width, thickness = dims
    thread = detect_thread(brief) or "M5"
    thread_rule = THREAD_RULES[thread]
    center_hole_diameter = parse_first_number_before(brief, ("通孔", "中心孔", "轴孔")) or 22.0
    corner_fillet = parse_radius_or_chamfer(brief, "R", 6.0)
    edge_chamfer = parse_radius_or_chamfer(brief, "C", 1.0)

    assumptions = []
    if parse_triplet_mm(brief) is None:
        assumptions.append("未识别到底板尺寸，采用 90x60x8 mm 默认安装座。")
    if detect_thread(brief) is None:
        assumptions.append("未识别固定孔规格，采用 M5 固定孔。")
    assumptions.extend(
        [
            "四角固定孔默认按矩形孔距布置，边距取 10 mm。",
            "固定孔按通孔处理；若需要攻丝孔，应切换 threaded_hole 特征。",
            "减重口袋保留至少 3 mm 壁厚和 2 mm 底厚。",
        ]
    )

    hole_edge_margin = 10.0
    hole_positions = [
        [-length / 2 + hole_edge_margin, -width / 2 + hole_edge_margin],
        [length / 2 - hole_edge_margin, -width / 2 + hole_edge_margin],
        [-length / 2 + hole_edge_margin, width / 2 - hole_edge_margin],
        [length / 2 - hole_edge_margin, width / 2 - hole_edge_margin],
    ]

    features = [
        {
            "name": "BasePlate",
            "type": "base_plate",
            "params": {"length": length, "width": width, "thickness": thickness},
            "required": True,
        },
        {
            "name": "OuterCornerFillet",
            "type": "fillet",
            "params": {"radius": corner_fillet, "target": "outer_vertical_edges"},
            "required": True,
            "fallback": "若圆角求解失败，降级为 R4 或逐边添加。",
        },
        {
            "name": "TopEdgeChamfer",
            "type": "chamfer",
            "params": {"distance": edge_chamfer, "target": "top_outer_edges"},
            "required": True,
            "fallback": "若整圈倒角失败，按边对象分组选择后重试。",
        },
        {
            "name": "CornerMountingHoles",
            "type": "through_hole_pattern",
            "params": {
                "fastener": thread,
                "clearance_diameter": clearance_diameter(thread),
                "positions_xy": hole_positions,
            },
            "required": True,
        },
        {
            "name": "CenterShaftClearance",
            "type": "through_hole",
            "params": {"diameter": center_hole_diameter, "position_xy": [0.0, 0.0]},
            "required": True,
        },
        {
            "name": "SideLighteningPockets",
            "type": "pocket_pair",
            "params": {
                "count": 2,
                "min_wall": 3.0,
                "min_floor": 2.0,
                "placement": "left_and_right_of_center_hole",
            },
            "required": False,
            "fallback": "若口袋与中心孔或固定孔冲突，缩小口袋或跳过并记录。",
        },
        {
            "name": "HoleMouthChamfers",
            "type": "chamfer",
            "params": {
                "distance": max(0.4, thread_rule["mouth_chamfer"]),
                "target": "all_hole_mouth_edges",
            },
            "required": True,
        },
    ]

    return {
        "plan_version": 1,
        "source_brief": brief.strip(),
        "part_family": "cnc_mount",
        "parameters": {
            "unit": "mm",
            "material": "6061 aluminum",
            "base_plate": {"length": length, "width": width, "thickness": thickness},
            "fixed_hole_fastener": thread,
            "tap_drill_reference": {
                "thread": thread,
                "tap_drill": thread_rule["tap_drill"],
                "pitch": thread_rule["pitch"],
                "note": "当前固定孔按 clearance through hole 处理，攻丝孔时使用该底孔参考。",
            },
            "center_hole_diameter": center_hole_diameter,
            "corner_fillet": corner_fillet,
            "edge_chamfer": edge_chamfer,
        },
        "features": features,
        "operation_sequence": [
            "close_same_name_documents",
            "new_part",
            "base_plate",
            "outer_fillet_and_chamfer",
            "pockets",
            "through_holes",
            "mouth_chamfers",
            "custom_properties",
            "save_export_review",
        ],
        "assumptions": assumptions,
        "risk_register": [
            {
                "risk": "圆角和倒角在复杂孔槽之后求解失败或耗时过长。",
                "mitigation": "按 CNC 子技能顺序先处理外轮廓圆角/倒角，再切孔槽；失败时降低半径并逐边重试。",
            },
            {
                "risk": "孔口边选择不稳定。",
                "mitigation": "枚举 body.GetEdges()，按圆心、半径、顶面高度匹配边对象并用 edge.Select2()。",
            },
            {
                "risk": "输出文件已在 SolidWorks 打开导致 SaveAs 失败。",
                "mitigation": "执行前关闭同名旧文档，保存后检查文件存在和大小。",
            },
        ],
        "review_plan": {
            "expected_outputs": ["SLDPRT", "STEP", "parameters_json", "review_report_json", "isometric_preview"],
            "views": ["isometric", "front", "top", "right"],
            "checks": [
                "expected_outputs_exist",
                "previews_created",
                "previews_not_blank",
                "feature_summary_available",
                "features_include_fillet_chamfer_cut",
            ],
        },
        "solidworks_mapping": [
            {
                "operation": "new_part",
                "preferred_api": "sw_session.SolidWorksSession.new_part",
                "notes": "统一通过 session 管理文档生命周期。",
            },
            {
                "operation": "base_plate",
                "preferred_api": "sw_part.sketch_rectangle + sw_part.extrude_boss",
                "notes": "基础体保持简单草图，避免一开始画复杂圆角轮廓。",
            },
            {
                "operation": "outer_fillet_and_chamfer",
                "preferred_api": "FeatureFillet + InsertFeatureChamfer with edge.Select2",
                "notes": "按对象选边，不依赖 Edge1 或坐标点击。",
            },
            {
                "operation": "save_export_review",
                "preferred_api": "session.save + session.export + sw_review.run_review",
                "notes": "必须生成多视角预览和 review report。",
            },
        ],
    }


def clearance_diameter(thread: str) -> float:
    """返回常用螺钉通孔直径。"""
    table = {"M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 9.0}
    return table.get(thread, THREAD_RULES[thread]["tap_drill"] + 0.5)


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成 SolidWorks 参数化设计计划")
    parser.add_argument("--brief", help="自然语言需求")
    parser.add_argument("--brief-file", type=Path, help="需求文本文件")
    parser.add_argument("--out", type=Path, required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    if not args.brief and not args.brief_file:
        parser.error("必须提供 --brief 或 --brief-file")

    brief = args.brief if args.brief else args.brief_file.read_text(encoding="utf-8")
    plan = build_plan(brief)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
