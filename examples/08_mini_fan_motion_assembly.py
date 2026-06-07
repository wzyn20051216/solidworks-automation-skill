"""
示例 8: 桌面迷你散热风扇基准装配与 Motion Study。

本示例用于验证完整自动化链路：生成 4 个零件、创建装配体、添加真实 Mate、
固定静止组件、保留叶轮旋转自由度、添加 60RPM 旋转马达并导出自审查报告。

注意：该示例优先追求稳定可运行，不把圆角/倒角作为成功标准。SolidWorks
边线自动选择在不同版本、语言和建模顺序下差异较大，圆角美化建议在后续
专门的实体选择策略中优化。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from sw_appearance import set_document_appearance
from sw_assembly import (
    SW_MATE_COINCIDENT,
    SW_MATE_DISTANCE,
    add_component,
    add_concentric_mate_by_cylinders,
    add_mate5_checked,
    collect_mate_feature_summary,
    find_component_by_name,
    get_component_feature_entity,
    resolve_component,
    select_entities_for_mate,
)
from sw_connect import (
    connect_solidworks,
    create_empty_dispatch_variant,
    get_com_member,
    mm,
    new_document,
    save_document,
)
from sw_motion import (
    add_constant_speed_rotary_motor_by_cylinders,
    calculate_and_play,
    create_motion_study,
)
from sw_part import (
    extrude_boss,
    extrude_cut,
    sketch,
    sketch_circle,
    sketch_corner_rectangle,
    sketch_rectangle,
)
from sw_review import run_review


OUTPUT_DIR = Path(r"C:\temp\solidworks_mini_fan_demo")


def save_and_close(sw, model, output_path: Path) -> Path:
    """
    @brief 保存文档并关闭，避免同名文档残留影响 AddComponent4。
    @param sw SolidWorks 应用对象。
    @param model 当前 IModelDoc2。
    @param output_path 输出文件路径。
    @return 保存后的绝对路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not save_document(model, str(output_path)):
        raise RuntimeError(f"保存失败: {output_path}")
    title = get_com_member(model, "GetTitle")
    sw.CloseDoc(title)
    return output_path


def create_base(sw) -> Path:
    """
    @brief 创建底座零件。
    @return .SLDPRT 文件路径。
    """
    model = new_document(sw, "part")
    with sketch(model, "Front Plane") as sketch_name:
        sketch_rectangle(model, 0, 0, mm(95), mm(62))
    extrude_boss(model, sketch_name, mm(8))
    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(8))
    extrude_boss(model, sketch_name, mm(12), merge=True)
    set_document_appearance(model, "#2F343A")
    model.ForceRebuild3(False)
    return save_and_close(sw, model, OUTPUT_DIR / "mini_fan_base.SLDPRT")


def create_stand(sw) -> Path:
    """
    @brief 创建中心立柱/轴零件。
    @return .SLDPRT 文件路径。
    """
    model = new_document(sw, "part")
    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(5))
    extrude_boss(model, sketch_name, mm(72))
    set_document_appearance(model, "#BFC4C8")
    model.ForceRebuild3(False)
    return save_and_close(sw, model, OUTPUT_DIR / "mini_fan_center_stand.SLDPRT")


def create_impeller(sw) -> Path:
    """
    @brief 创建带十字叶片的叶轮零件。
    @return .SLDPRT 文件路径。
    """
    model = new_document(sw, "part")

    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(12))
    extrude_boss(model, sketch_name, mm(7))

    # 这里使用矩形叶片保证稳定；弧形叶片和圆角美化留给后续选择策略优化。
    blade_rects = [
        (mm(12), mm(-5), mm(39), mm(5)),
        (mm(-39), mm(-5), mm(-12), mm(5)),
        (mm(-5), mm(12), mm(5), mm(39)),
        (mm(-5), mm(-39), mm(5), mm(-12)),
    ]
    with sketch(model, "Front Plane") as sketch_name:
        for x1, y1, x2, y2 in blade_rects:
            sketch_corner_rectangle(model, x1, y1, x2, y2)
    extrude_boss(model, sketch_name, mm(4), merge=True)

    set_document_appearance(model, "#2AA8FF")
    model.ForceRebuild3(False)
    return save_and_close(sw, model, OUTPUT_DIR / "mini_fan_impeller.SLDPRT")


def create_front_guard(sw) -> Path:
    """
    @brief 创建圆形防护前盖零件。
    @return .SLDPRT 文件路径。
    """
    model = new_document(sw, "part")

    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(47))
    extrude_boss(model, sketch_name, mm(3))

    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(39))
    extrude_cut(model, sketch_name, 0)

    # 十字防护筋，比复杂网罩更稳定，便于验证装配和运动链路。
    guard_bars = [
        (mm(-47), mm(-2), mm(47), mm(2)),
        (mm(-2), mm(-47), mm(2), mm(47)),
    ]
    with sketch(model, "Front Plane") as sketch_name:
        for x1, y1, x2, y2 in guard_bars:
            sketch_corner_rectangle(model, x1, y1, x2, y2)
    extrude_boss(model, sketch_name, mm(3), merge=True)

    set_document_appearance(model, "#D99A22")
    model.ForceRebuild3(False)
    return save_and_close(sw, model, OUTPUT_DIR / "mini_fan_front_guard.SLDPRT")


def set_component_fixed(asm, component, fixed: bool) -> bool:
    """
    @brief 固定或浮动装配体组件。
    @param asm 装配体 IModelDoc2/IAssemblyDoc。
    @param component 目标 IComponent2。
    @param fixed True=固定，False=浮动。
    @return 操作是否成功。
    """
    asm.ClearSelection2(True)
    selected = False
    try:
        selected = bool(component.Select4(False, create_empty_dispatch_variant(), False))
    except Exception:
        selected = False
    if not selected:
        selected = bool(
            asm.Extension.SelectByID2(
                get_com_member(component, "Name2"),
                "COMPONENT",
                0,
                0,
                0,
                False,
                0,
                create_empty_dispatch_variant(),
                0,
            )
        )
    if not selected:
        raise RuntimeError(f"无法选择组件: {get_com_member(component, 'Name2')}")
    member_name = "FixComponent" if fixed else "UnfixComponent"
    result = get_com_member(asm, member_name)
    asm.ClearSelection2(True)
    return bool(result) if result is not None else True


def add_plane_coincident_mate(asm, component_a, component_b, plane="Front Plane", name=None):
    """
    @brief 使用两个组件内部基准面创建重合 Mate。
    @param asm 装配体文档。
    @param component_a 第一个组件。
    @param component_b 第二个组件。
    @param plane 基准面名称。
    @param name 可选 Mate 名称。
    @return Mate2 对象。
    """
    entity_a = get_component_feature_entity(component_a, plane)
    entity_b = get_component_feature_entity(component_b, plane)
    select_entities_for_mate(asm, entity_a, entity_b, mark=1)
    return add_mate5_checked(asm, SW_MATE_COINCIDENT, name=name)


def add_plane_distance_mate(asm, component_a, component_b, distance_mm, plane="Front Plane", name=None):
    """
    @brief 使用两个组件内部基准面创建距离 Mate。
    @param asm 装配体文档。
    @param component_a 第一个组件。
    @param component_b 第二个组件。
    @param distance_mm 距离，单位 mm。
    @param plane 基准面名称。
    @param name 可选 Mate 名称。
    @return Mate2 对象。
    """
    entity_a = get_component_feature_entity(component_a, plane)
    entity_b = get_component_feature_entity(component_b, plane)
    select_entities_for_mate(asm, entity_a, entity_b, mark=1)
    return add_mate5_checked(
        asm,
        SW_MATE_DISTANCE,
        distance=mm(distance_mm),
        name=name,
    )


def create_assembly(sw, part_paths: dict[str, Path]) -> Path:
    """
    @brief 创建风扇装配体并添加 Mate 与 Motion Study。
    @param sw SolidWorks 应用对象。
    @param part_paths 零件路径字典。
    @return .SLDASM 文件路径。
    """
    asm = new_document(sw, "assembly")

    base = add_component(asm, str(part_paths["base"]), 0, 0, 0)
    stand = add_component(asm, str(part_paths["stand"]), 0, 0, 0)
    impeller = add_component(asm, str(part_paths["impeller"]), 0, 0, mm(42))
    front_guard = add_component(asm, str(part_paths["front_guard"]), 0, 0, mm(50))

    for component in (base, stand, impeller, front_guard):
        if component is None:
            raise RuntimeError("添加组件失败，请检查零件路径和活动装配体。")
        resolve_component(component)

    add_plane_coincident_mate(asm, base, stand, "Front Plane", name="base_stand_front_coincident")
    add_concentric_mate_by_cylinders(
        asm,
        base,
        stand,
        radius_a=(mm(7.5), mm(8.5)),
        radius_b=(mm(4.5), mm(5.5)),
        name="base_stand_concentric",
        lock_rotation=True,
    )
    add_concentric_mate_by_cylinders(
        asm,
        stand,
        impeller,
        radius_a=(mm(4.5), mm(5.5)),
        radius_b=(mm(11.0), mm(13.0)),
        name="stand_impeller_concentric_free",
        lock_rotation=False,
    )
    add_plane_distance_mate(
        asm,
        stand,
        impeller,
        distance_mm=42,
        plane="Front Plane",
        name="stand_impeller_axial_distance",
    )
    add_concentric_mate_by_cylinders(
        asm,
        stand,
        front_guard,
        radius_a=(mm(4.5), mm(5.5)),
        radius_b=(mm(38.0), mm(48.0)),
        name="stand_guard_concentric",
        lock_rotation=True,
    )
    add_plane_distance_mate(
        asm,
        stand,
        front_guard,
        distance_mm=50,
        plane="Front Plane",
        name="stand_guard_axial_distance",
    )

    set_component_fixed(asm, base, True)
    set_component_fixed(asm, stand, True)
    set_component_fixed(asm, front_guard, True)
    set_component_fixed(asm, impeller, False)

    study = create_motion_study(asm, name="mini_fan_impeller_60RPM_loop", duration=4.0)
    add_constant_speed_rotary_motor_by_cylinders(
        study,
        shaft_component=stand,
        rotor_component=impeller,
        shaft_radius=(mm(4.5), mm(5.5)),
        rotor_radius=(mm(11.0), mm(13.0)),
        rpm=60.0,
        name="impeller_rotary_motor_60RPM",
    )
    calculated = calculate_and_play(study, play=False)
    print(f"Motion Study 计算结果: {calculated}")
    print("Mate 摘要:")
    for item in collect_mate_feature_summary(asm):
        print(f"  - {item['name']} ({item['type']})")

    asm.ForceRebuild3(False)
    assembly_path = OUTPUT_DIR / "mini_fan_motion_assembly.SLDASM"
    if not save_document(asm, str(assembly_path)):
        raise RuntimeError(f"保存装配体失败: {assembly_path}")

    review_dir = OUTPUT_DIR / "review"
    report, report_path = run_review(
        asm,
        str(review_dir),
        basename="mini_fan_motion_assembly",
        expected_outputs=[str(assembly_path)],
    )
    print(f"审查报告: {report_path}")
    print(f"审查状态: {report.get('evaluation')}")
    return assembly_path


def main() -> None:
    """
    @brief 运行完整微型风扇基准示例。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sw, _ = connect_solidworks()
    part_paths = {
        "base": create_base(sw),
        "stand": create_stand(sw),
        "impeller": create_impeller(sw),
        "front_guard": create_front_guard(sw),
    }
    assembly_path = create_assembly(sw, part_paths)
    print(f"完成: {assembly_path}")


if __name__ == "__main__":
    main()
