"""
@file create_spur_gear.py
@brief 生成渐开线直齿圆柱齿轮 SolidWorks 零件。

流程：纯几何模块计算闭合齿廓 -> Front Plane 画闭合轮廓 -> 拉伸齿宽 -> 切中心孔
-> 写齿轮参数属性 -> 保存 SLDPRT / 导出 STEP / 自审查。

能力等级：pilot。齿廓几何（模数、齿数、压力角、分度/基/齿顶/齿根圆、变位）已离线单测，
但真实 SolidWorks 特征落盘、变位根切边界和啮合精度仍需真机与工程复核。
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
    assert_feature,
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
from standard_parts_geometry import spur_gear_profile  # noqa: E402


def build_spur_gear(args) -> dict:
    """@brief 依据参数生成直齿轮并交付。"""
    geometry = spur_gear_profile(
        args.module,
        args.teeth,
        pressure_angle_deg=args.pressure_angle,
        addendum_coeff=args.addendum_coeff,
        dedendum_coeff=args.dedendum_coeff,
        profile_shift_coeff=args.profile_shift,
        bore_diameter_mm=args.bore,
        samples_per_flank=args.samples,
    )
    if geometry.is_pointed:
        print("WARN 齿顶已尖化（顶隙为 0），请减小齿顶高系数或增大齿数后复核")

    basename = validate_basename(
        args.basename or f"SpurGear_m{args.module:g}_z{geometry.teeth}"
    )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / f"{basename}.SLDPRT"
    step_path = output_dir / f"{basename}.step"
    param_path = output_dir / f"{basename}_parameters.json"

    session = SolidWorksSession(visible=True)
    model = session.new_part()

    sketch_name = sketch_closed_profile(model, geometry.profile_xy_mm, "Front Plane")
    extrude_profile(model, sketch_name, args.face_width, f"齿轮基体 m{args.module:g} z{geometry.teeth}").Name = (
        "Boss_Gear_Body"
    )
    bore_feature = bore_center_hole(model, geometry.bore_diameter_mm, "Front Plane", "齿轮中心孔")
    if bore_feature is not None:
        bore_feature.Name = "Cut_Gear_Bore"

    set_document_appearance(model, "steel")
    model.ForceRebuild3(False)
    write_properties(
        model,
        [
            ("零件类型", "渐开线直齿圆柱齿轮"),
            ("模数", f"{geometry.module_mm:g} mm"),
            ("齿数", str(geometry.teeth)),
            ("压力角", f"{geometry.pressure_angle_deg:g} deg"),
            ("变位系数", f"{args.profile_shift:g}"),
            ("分度圆直径", f"{geometry.pitch_diameter_mm:.4f} mm"),
            ("基圆直径", f"{geometry.base_diameter_mm:.4f} mm"),
            ("齿顶圆直径", f"{geometry.addendum_diameter_mm:.4f} mm"),
            ("齿根圆直径", f"{geometry.root_diameter_mm:.4f} mm"),
            ("齿宽", f"{args.face_width:g} mm"),
            ("中心孔直径", f"{geometry.bore_diameter_mm:g} mm"),
        ],
    )
    hide_reference_planes(model)
    model.ViewZoomtofit2()

    param_path.write_text(
        json.dumps(
            {
                "units": "mm",
                "type": "spur_gear",
                "module_mm": geometry.module_mm,
                "teeth": geometry.teeth,
                "pressure_angle_deg": geometry.pressure_angle_deg,
                "profile_shift_coeff": args.profile_shift,
                "pitch_diameter_mm": geometry.pitch_diameter_mm,
                "base_diameter_mm": geometry.base_diameter_mm,
                "addendum_diameter_mm": geometry.addendum_diameter_mm,
                "root_diameter_mm": geometry.root_diameter_mm,
                "face_width_mm": args.face_width,
                "bore_diameter_mm": geometry.bore_diameter_mm,
                "is_pointed": geometry.is_pointed,
                "profile_point_count": len(geometry.profile_xy_mm),
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
    parser = argparse.ArgumentParser(description="生成渐开线直齿圆柱齿轮 SolidWorks 零件。")
    parser.add_argument("--module", type=float, default=2.0, help="模数 m（mm），默认 2。")
    parser.add_argument("--teeth", type=int, default=20, help="齿数 z，默认 20。")
    parser.add_argument("--pressure-angle", type=float, default=20.0, help="压力角（度），默认 20。")
    parser.add_argument("--face-width", type=float, default=15.0, help="齿宽（mm），默认 15。")
    parser.add_argument("--bore", type=float, default=10.0, help="中心孔直径（mm），默认 10；传 0 不打孔。")
    parser.add_argument("--addendum-coeff", type=float, default=1.0, help="齿顶高系数 ha*，默认 1.0。")
    parser.add_argument("--dedendum-coeff", type=float, default=1.25, help="齿根高系数 hf*，默认 1.25。")
    parser.add_argument("--profile-shift", type=float, default=0.0, help="变位系数 x，默认 0。")
    parser.add_argument("--samples", type=int, default=12, help="每条齿廓渐开线采样点数，默认 12。")
    parser.add_argument("--basename", help="输出文件名前缀；默认按模数齿数生成。")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "solidworks_standard_parts_output",
        help="输出目录。",
    )
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    result = build_spur_gear(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
