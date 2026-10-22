"""
@file create_compression_spring.py
@brief 生成圆柱压缩弹簧 SolidWorks 零件。

流程：纯几何模块按线径/中径/自由长度/圈数计算等螺距螺旋中心线与力学派生量 ->
3D 草图螺旋路径（始终作为真实曲线证据） -> 尝试圆形轮廓扫描成实体线材 ->
写弹簧参数 -> 保存/导出/审查。扫描失败时降级为“螺旋中心线证据”，不阻断可审查交付。

能力等级：pilot。螺旋线坐标、弹簧指数 C、实体长度、刚度 k=G d^4/(8 D^3 Na) 已离线单测；
真实扫描实体、端圈并紧/磨平和压并高度仍需真机与工程复核。
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
    clear,
    hide_reference_planes,
    validate_basename,
    write_properties,
)
from sw_connect import get_com_member, mm  # noqa: E402
from sw_export import export_to_step  # noqa: E402
from sw_part import current_sketch_name  # noqa: E402
from sw_review import run_review, save_preview  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402
from standard_parts_geometry import compression_spring_helix  # noqa: E402


def build_helix_path(model, geometry) -> tuple[str, int]:
    """@brief 用 3D 草图短线段画出螺旋中心线，作为扫描路径与证据曲线。"""
    sketch_mgr = model.SketchManager
    sketch_mgr.Insert3DSketch(True)
    sketch_name = current_sketch_name(model, "Sketch_Spring_Helix")
    previous = None
    created = 0
    for x, y, z in geometry.helix_xyz_mm:
        point = (mm(x), mm(y), mm(z))
        if previous is not None:
            segment = sketch_mgr.CreateLine(previous[0], previous[1], previous[2], point[0], point[1], point[2])
            if segment:
                created += 1
        previous = point
    sketch_mgr.Insert3DSketch(True)
    feature = model.FeatureByName(sketch_name)
    if feature:
        feature.Name = "Sketch_Spring_Helix_Path"
        sketch_name = "Sketch_Spring_Helix_Path"
    print(f"OK 螺旋中心线: {created} 段")
    return sketch_name, created


def try_circular_profile_sweep(model, path_sketch_name: str, wire_diameter_mm: float) -> bool:
    """@brief 尝试用圆形轮廓沿螺旋路径扫描成实体线材。

    使用 InsertProtrusionSwept4 的圆形轮廓选项（免去在螺旋起点法向建轮廓草图）。
    该 COM 路径版本敏感，任何失败都返回 False 并交回中心线证据路线，不抛出。
    """
    clear(model)
    feature_manager = model.FeatureManager
    if not model.Extension.SelectByID2(
        path_sketch_name, "SKETCH", 0, 0, 0, False, 4, None, 0
    ):
        print("WARN 选择螺旋路径草图失败，跳过扫描")
        return False
    try:
        feature = feature_manager.InsertProtrusionSwept4(
            0,      # TwistControlType: swTwistControlFollowPath
            False,  # KeepTangency
            False,  # ForceNonRational
            0,      # AdvancedSmoothing / Frenet 选项
            False,  # AlignWithEndFaces
            0.0,    # TwistAngle
            0,      # StartTangencyType
            0,      # EndTangencyType
            False,  # KeepNormalConstant
            0,      # StartTangentLength
            0,      # EndTangentLength
            False,  # MergeSmoothFaces
            False,  # UseFeatureScope
            True,   # UseAutoSelect
            True,   # CircularProfile
            mm(wire_diameter_mm),  # CircularProfileDiameter
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARN 圆形轮廓扫描失败: {exc}")
        clear(model)
        return False
    clear(model)
    if feature is None:
        print("WARN InsertProtrusionSwept4 返回 None")
        return False
    try:
        feature.Name = "Boss_Spring_Wire"
    except Exception:  # noqa: BLE001
        pass
    print(f"OK 弹簧线材扫描: {getattr(feature, 'Name', '<未命名>')}")
    return True


def has_solid_body(model) -> bool:
    """@brief 重建后回读是否存在实体，不把 COM 返回等同于落盘成功。"""
    model.ForceRebuild3(False)
    bodies = get_com_member(model, "GetBodies2", 0, False) or []
    return len(list(bodies)) > 0


def build_compression_spring(args) -> dict:
    """@brief 依据参数生成压缩弹簧并交付。"""
    geometry = compression_spring_helix(
        args.wire_diameter,
        args.mean_diameter,
        args.free_length,
        args.total_coils,
        end_type=args.end_type,
        right_handed=args.handedness == "right",
        shear_modulus_mpa=args.shear_modulus,
        samples_per_coil=args.samples_per_coil,
    )

    basename = validate_basename(
        args.basename
        or f"CompressionSpring_d{args.wire_diameter:g}_D{args.mean_diameter:g}"
    )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / f"{basename}.SLDPRT"
    step_path = output_dir / f"{basename}.step"
    param_path = output_dir / f"{basename}_parameters.json"

    session = SolidWorksSession(visible=True)
    model = session.new_part()

    path_sketch_name, segment_count = build_helix_path(model, geometry)
    swept = try_circular_profile_sweep(model, path_sketch_name, geometry.wire_diameter_mm)
    representation = "swept-solid" if (swept and has_solid_body(model)) else "helix-centerline"

    model.ForceRebuild3(False)
    write_properties(
        model,
        [
            ("零件类型", "圆柱压缩弹簧"),
            ("线径", f"{geometry.wire_diameter_mm:g} mm"),
            ("中径", f"{geometry.mean_diameter_mm:g} mm"),
            ("外径", f"{geometry.outer_diameter_mm:g} mm"),
            ("自由长度", f"{geometry.free_length_mm:g} mm"),
            ("总圈数", f"{geometry.total_coils:g}"),
            ("有效圈数", f"{geometry.active_coils:g}"),
            ("节距", f"{geometry.pitch_mm:.4f} mm"),
            ("实体长度", f"{geometry.solid_length_mm:g} mm"),
            ("弹簧指数C", f"{geometry.spring_index:.3f}"),
            ("端型", geometry.end_type),
            ("旋向", "RH" if geometry.right_handed else "LH"),
            ("刚度", f"{geometry.spring_rate_n_per_mm:.4f} N/mm" if geometry.spring_rate_n_per_mm else "未提供剪切模量"),
            ("几何表达", representation),
        ],
    )
    hide_reference_planes(model)
    model.ViewZoomtofit2()

    helix_preview_path = None
    if representation == "helix-centerline":
        helix_preview_path = output_dir / f"{basename}_helix_evidence.bmp"
        save_preview(model, helix_preview_path, "isometric")

    param_path.write_text(
        json.dumps(
            {
                "units": "mm",
                "type": "compression_spring",
                "wire_diameter_mm": geometry.wire_diameter_mm,
                "mean_diameter_mm": geometry.mean_diameter_mm,
                "outer_diameter_mm": geometry.outer_diameter_mm,
                "free_length_mm": geometry.free_length_mm,
                "total_coils": geometry.total_coils,
                "active_coils": geometry.active_coils,
                "pitch_mm": geometry.pitch_mm,
                "solid_length_mm": geometry.solid_length_mm,
                "spring_index": geometry.spring_index,
                "end_type": geometry.end_type,
                "right_handed": geometry.right_handed,
                "spring_rate_n_per_mm": geometry.spring_rate_n_per_mm,
                "representation": representation,
                "helix_segment_count": segment_count,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not session.save(model, str(part_path)):
        raise RuntimeError(f"保存失败: {part_path}")
    if representation == "swept-solid" and not export_to_step(model, str(step_path)):
        raise RuntimeError(f"STEP 导出失败: {step_path}")
    if representation != "swept-solid":
        step_path = None
        print("WARN 未生成实体，跳过 STEP 导出；仅交付螺旋中心线证据")

    expected_outputs = [str(part_path), str(param_path)]
    if step_path is not None:
        expected_outputs.append(str(step_path))
    if helix_preview_path is not None:
        expected_outputs.append(str(helix_preview_path))
    report, report_path = run_review(
        model,
        output_dir,
        basename=basename,
        expected_outputs=expected_outputs,
    )
    print(f"审查报告: {report_path}")
    print(f"审查状态: {report['evaluation']['status']} / {report['evaluation']['score']}")
    print(f"几何表达: {representation}")
    return {
        "part_path": str(part_path),
        "step_path": str(step_path) if step_path else None,
        "param_path": str(param_path),
        "review_path": str(report_path),
        "review": report["evaluation"],
        "representation": representation,
    }


def parse_args():
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="生成圆柱压缩弹簧 SolidWorks 零件。")
    parser.add_argument("--wire-diameter", type=float, default=3.0, help="线径 d（mm），默认 3。")
    parser.add_argument("--mean-diameter", type=float, default=24.0, help="中径 D（mm），默认 24。")
    parser.add_argument("--free-length", type=float, default=60.0, help="自由长度 L（mm），默认 60。")
    parser.add_argument("--total-coils", type=float, default=8.0, help="总圈数 Nt，默认 8。")
    parser.add_argument(
        "--end-type",
        choices=("closed_ground", "closed", "open"),
        default="closed_ground",
        help="端型，默认 closed_ground（并紧磨平）。",
    )
    parser.add_argument("--handedness", choices=("right", "left"), default="right", help="旋向，默认右旋。")
    parser.add_argument("--shear-modulus", type=float, help="剪切模量 G（MPa），提供则计算刚度；弹簧钢约 79300。")
    parser.add_argument("--samples-per-coil", type=int, default=36, help="每圈螺旋采样点数，默认 36。")
    parser.add_argument("--basename", help="输出文件名前缀；默认按线径中径生成。")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "solidworks_standard_parts_output",
        help="输出目录。",
    )
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    result = build_compression_spring(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
