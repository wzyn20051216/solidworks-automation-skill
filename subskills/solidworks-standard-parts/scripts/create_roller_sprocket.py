"""
@file create_roller_sprocket.py
@brief 生成滚子链链轮 SolidWorks 零件（ANSI/ISO 简化齿形）。

流程：纯几何模块按链节距/滚子直径/齿数计算节圆、齿顶圆、齿根圆与简化齿形 ->
Front Plane 画闭合轮廓 -> 拉伸厚度 -> 切中心孔 -> 写链轮参数 -> 保存/导出/审查。

能力等级：pilot（可视化/打印级）。节圆直径 PD=P/sin(pi/N)、齿顶圆 OD、齿根圆已单测；
精确啮合齿形（滚子座样条、齿侧修形）仍需按 ANSI B29.1 / ISO 606 人工复核。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

THIS_FILE = Path(__file__).resolve()
sys.path.insert(0, str(THIS_FILE.parent))
PARENT_SCRIPT_DIR = THIS_FILE.parents[3] / "scripts"
sys.path.insert(0, str(PARENT_SCRIPT_DIR))

from _common import (  # noqa: E402
    bore_center_hole,
    extrude_profile,
    hide_reference_planes,
    sketch_closed_profile,
    validate_basename,
    write_properties,
)
from sw_appearance import set_document_appearance  # noqa: E402
from sw_export import export_to_step  # noqa: E402
from sw_review import run_review  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402
from standard_parts_geometry import roller_sprocket_profile  # noqa: E402


def build_roller_sprocket(args) -> dict:
    """@brief 依据参数生成滚子链链轮并交付。"""
    geometry = roller_sprocket_profile(
        args.chain_pitch,
        args.roller_diameter,
        args.teeth,
        bore_diameter_mm=args.bore,
        seat_samples=args.seat_samples,
    )

    basename = validate_basename(
        args.basename or f"Sprocket_P{args.chain_pitch:g}_z{geometry.teeth}"
    )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / f"{basename}.SLDPRT"
    step_path = output_dir / f"{basename}.step"
    param_path = output_dir / f"{basename}_parameters.json"

    session = SolidWorksSession(visible=True)
    model = session.new_part()

    sketch_name = sketch_closed_profile(model, geometry.profile_xy_mm, "Front Plane")
    extrude_profile(model, sketch_name, args.thickness, f"链轮基体 P{args.chain_pitch:g} z{geometry.teeth}").Name = (
        "Boss_Sprocket_Body"
    )
    bore_feature = bore_center_hole(model, geometry.bore_diameter_mm, "Front Plane", "链轮中心孔")
    if bore_feature is not None:
        bore_feature.Name = "Cut_Sprocket_Bore"

    set_document_appearance(model, "steel")
    model.ForceRebuild3(False)
    write_properties(
        model,
        [
            ("零件类型", "滚子链链轮（简化齿形）"),
            ("链节距", f"{geometry.chain_pitch_mm:g} mm"),
            ("滚子直径", f"{geometry.roller_diameter_mm:g} mm"),
            ("齿数", str(geometry.teeth)),
            ("节圆直径", f"{geometry.pitch_diameter_mm:.4f} mm"),
            ("齿顶圆直径", f"{geometry.outside_diameter_mm:.4f} mm"),
            ("齿根圆直径", f"{geometry.root_diameter_mm:.4f} mm"),
            ("滚子座半径", f"{geometry.seating_radius_mm:.4f} mm"),
            ("厚度", f"{args.thickness:g} mm"),
            ("中心孔直径", f"{geometry.bore_diameter_mm:g} mm"),
            ("齿形说明", "ANSI/ISO 简化齿形，精确啮合需人工按标准复核"),
        ],
    )
    hide_reference_planes(model)
    model.ViewZoomtofit2()

    param_path.write_text(
        json.dumps(
            {
                "units": "mm",
                "type": "roller_sprocket",
                "chain_pitch_mm": geometry.chain_pitch_mm,
                "roller_diameter_mm": geometry.roller_diameter_mm,
                "teeth": geometry.teeth,
                "pitch_diameter_mm": geometry.pitch_diameter_mm,
                "outside_diameter_mm": geometry.outside_diameter_mm,
                "root_diameter_mm": geometry.root_diameter_mm,
                "seating_radius_mm": geometry.seating_radius_mm,
                "thickness_mm": args.thickness,
                "bore_diameter_mm": geometry.bore_diameter_mm,
                "profile_point_count": len(geometry.profile_xy_mm),
                "profile_note": "simplified-ansi",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not session.save(model, str(part_path)):
        raise RuntimeError(f"保存失败: {part_path}")
    if not export_to_step(model, str(step_path)):
        raise RuntimeError(f"STEP 导出失败: {step_path}")

    report, report_path = run_review(
        model,
        output_dir,
        basename=basename,
        expected_outputs=[str(part_path), str(step_path), str(param_path)],
    )
    print(f"审查报告: {report_path}")
    print(f"审查状态: {report['evaluation']['status']} / {report['evaluation']['score']}")
    return {
        "part_path": str(part_path),
        "step_path": str(step_path),
        "param_path": str(param_path),
        "review_path": str(report_path),
        "review": report["evaluation"],
    }


def parse_args():
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="生成滚子链链轮 SolidWorks 零件。")
    parser.add_argument("--chain-pitch", type=float, default=12.7, help="链节距 P（mm），默认 12.7（ANSI #40）。")
    parser.add_argument("--roller-diameter", type=float, default=7.92, help="滚子直径 Dr（mm），默认 7.92。")
    parser.add_argument("--teeth", type=int, default=17, help="齿数 N，默认 17。")
    parser.add_argument("--thickness", type=float, default=6.0, help="链轮厚度（mm），默认 6。")
    parser.add_argument("--bore", type=float, default=20.0, help="中心孔直径（mm），默认 20；传 0 不打孔。")
    parser.add_argument("--seat-samples", type=int, default=8, help="每个滚子座圆弧采样点数，默认 8。")
    parser.add_argument("--basename", help="输出文件名前缀；默认按节距齿数生成。")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "solidworks_standard_parts_output",
        help="输出目录。",
    )
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    result = build_roller_sprocket(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
