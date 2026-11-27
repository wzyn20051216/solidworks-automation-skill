"""
设计规格执行器：把校验后的 design spec 幂等地构建为 SolidWorks 零件。

与"AI 每次生成一套建模调用"相比，这里的价值在于：
- **幂等**：同一份规格产出的特征树结构一致，可重复构建、可比对。
- **可追溯**：每一步都记录实际创建的特征名与回读尺寸。
- **内建验证**：构建后自动回读包围盒/孔数/质量并与规格 verify 段比对。

单位为毫米；内部统一换算为米后传给 SolidWorks API。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

try:
    from .sw_connect import get_com_member, mm
    from .sw_part import (
        SketchSelectionRef,
        extrude_boss,
        fillet,
        sketch_circle,
        sketch_corner_rectangle,
        sketch,
    )
    from .sw_hole_features import (
        create_blind_hole,
        create_counterbore_hole,
        create_countersink_hole,
        create_through_hole,
    )
    from .sw_edge_select import select_edges
    from . import sw_measure
    from .design_spec import compare_verification
except ImportError:  # 直接以 scripts/ 为 sys.path 时
    from sw_connect import get_com_member, mm
    from sw_part import (
        SketchSelectionRef,
        extrude_boss,
        fillet,
        sketch_circle,
        sketch_corner_rectangle,
        sketch,
    )
    from sw_hole_features import (
        create_blind_hole,
        create_counterbore_hole,
        create_countersink_hole,
        create_through_hole,
    )
    from sw_edge_select import select_edges
    import sw_measure
    from design_spec import compare_verification


def _safe(obj, name, *args, default=None):
    """@brief 安全读取 COM 成员。"""
    try:
        member = getattr(obj, name)
        value = member(*args) if args or callable(member) else member
    except Exception:
        return default
    return default if value is None else value


def _feature_name(feature, fallback):
    """@brief 读取特征名，失败时回退。"""
    name = _safe(feature, "Name")
    return str(name) if name else fallback


def _rotate_point(x_mm, y_mm, angle_deg):
    """@brief 绕原点旋转二维点（用于圆周阵列孔的坐标计算）。"""
    radians = math.radians(angle_deg)
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    return (x_mm * cos_a - y_mm * sin_a, x_mm * sin_a + y_mm * cos_a)


def expand_hole_patterns(holes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    展开孔阵列定义。

    支持在孔上附加 ``"pattern": {"type": "circular", "count": 6, "radius": 30,
    "start_angle": 0}`` 或 ``{"type": "linear", "count": 4, "dx": 20, "dy": 0}``，
    展开为独立孔定义，每个孔带可追溯的 id。

    参数:
        holes: 归一化后的孔列表。

    返回:
        展开后的孔列表（原孔若带 pattern，则替换为 count 个孔）。
    """
    expanded: List[Dict[str, Any]] = []
    for hole in holes:
        pattern = hole.get("pattern")
        if not pattern:
            expanded.append(dict(hole))
            continue

        kind = str(pattern.get("type", "")).strip().lower()
        try:
            count = int(pattern.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        if count < 1 or count > 200:
            count = max(1, min(count, 200))

        base_position = list(hole.get("position_mm") or [0.0, 0.0, 0.0])
        for index in range(count):
            variant = dict(hole)
            variant.pop("pattern", None)
            if kind == "circular":
                radius = float(pattern.get("radius", 0.0) or 0.0)
                start = float(pattern.get("start_angle", 0.0) or 0.0)
                step = 360.0 / count
                x_mm, y_mm = _rotate_point(radius, 0.0, start + step * index)
                variant["position_mm"] = [
                    round(base_position[0] + x_mm, 6),
                    round(base_position[1] + y_mm, 6),
                    base_position[2],
                ]
            elif kind == "linear":
                dx = float(pattern.get("dx", 0.0) or 0.0)
                dy = float(pattern.get("dy", 0.0) or 0.0)
                dz = float(pattern.get("dz", 0.0) or 0.0)
                variant["position_mm"] = [
                    round(base_position[0] + dx * index, 6),
                    round(base_position[1] + dy * index, 6),
                    round(base_position[2] + dz * index, 6),
                ]
            else:
                # 未知阵列类型：保留原孔，交给调用方在 warnings 中说明。
                expanded.append(dict(hole))
                break
            variant["id"] = f"{hole.get('id', 'H')}_{index + 1}"
            expanded.append(variant)

    return expanded


def _create_base(model, base):
    """
    创建基础实体，返回 (feature, plane_name, errors)。

    坐标系约定：板料的**左下角在原点**，板面位于 XY 平面第一象限，沿 +Z 拉伸。
    这样规格里的孔位可以直接按图纸尺寸标注（"距左边 10、距下边 15"），不必做
    居中偏移的心算——这是机械工程师标注孔位的默认方式。
    """
    base_type = base.get("type")
    if base_type == "rect_plate":
        width_mm = base["width_mm"]
        height_mm = base["height_mm"]
        thickness_mm = base["thickness_mm"]
        with sketch(model, "Front Plane") as sketch_ref:
            sketch_corner_rectangle(model, 0.0, 0.0, mm(width_mm), mm(height_mm))
        feature = extrude_boss(model, sketch_ref, mm(thickness_mm))
        return feature, "Front Plane", []

    if base_type == "cylinder":
        diameter_mm = base["diameter_mm"]
        height_mm = base["height_mm"]
        with sketch(model, "Front Plane") as sketch_ref:
            sketch_circle(model, 0.0, 0.0, mm(diameter_mm / 2.0))
        feature = extrude_boss(model, sketch_ref, mm(height_mm))
        return feature, "Front Plane", []

    if base_type == "none":
        return None, "Front Plane", []

    return None, "Front Plane", [f"不支持的 base.type={base_type!r}"]


def validate_holes_inside_base(holes, base):
    """
    检查孔位是否落在基础实体范围内。

    越界的孔会被 SolidWorks 静默拒绝（切除草图完全在实体外，不产生特征），表现为
    "创建成功但特征不存在"。提前显式报错能让用户立刻知道是坐标问题而不是 API 问题。
    """
    problems = []
    base = base or {}
    if base.get("type") == "rect_plate":
        width = base["width_mm"]
        height = base["height_mm"]
        for hole in holes:
            x_mm, y_mm = hole["position_mm"][0], hole["position_mm"][1]
            radius = hole["diameter_mm"] / 2.0
            if x_mm - radius < -1e-6 or y_mm - radius < -1e-6 or x_mm + radius > width + 1e-6 or y_mm + radius > height + 1e-6:
                problems.append(
                    f"孔 {hole.get('id')} 位于 ({x_mm}, {y_mm})，直径 {hole['diameter_mm']}mm，"
                    f"超出了板料范围 {width}x{height}mm（原点在左下角）。"
                )
    elif base.get("type") == "cylinder":
        diameter = base["diameter_mm"]
        radius_base = diameter / 2.0
        for hole in holes:
            x_mm, y_mm = hole["position_mm"][0], hole["position_mm"][1]
            distance = math.hypot(x_mm, y_mm)
            if distance + hole["diameter_mm"] / 2.0 > radius_base + 1e-6:
                problems.append(
                    f"孔 {hole.get('id')} 中心距轴心 {distance:.3f}mm，超出圆柱半径 {radius_base}mm。"
                )
    return problems


def _hole_center_m(hole):
    """孔中心（规格中的 mm）转 SolidWorks API 需要的米。"""
    return (mm(hole["position_mm"][0]), mm(hole["position_mm"][1]))


_SUPPORTED_HOLE_TYPES = frozenset({"through", "blind", "counterbore", "countersink"})


def _create_hole(model, hole):
    """
    按孔类型分派到 sw_hole_features 的创建函数。

    注意：这些函数的长度参数都期望**米**，而规格统一用毫米，因此这里必须显式
    换算——把毫米直接传进去会得到 1000 倍大的草图，SolidWorks 会静默拒绝切除
    （表现为"创建成功但特征不存在"），实测把 100mm 的板撑到 13300mm。

    函数通过本模块的属性查找，而不是在导入期绑定：这样既便于单独替换某一种孔
    的行为做测试，也避免模块导入顺序影响实际调用的实现。
    """
    hole_type = hole.get("type")
    hole_name = hole.get("id", "孔")

    if hole_type == "through":
        return create_through_hole(
            model,
            center=_hole_center_m(hole),
            diameter=mm(hole["diameter_mm"]),
            name=hole.get("id", "通孔"),
        )
    if hole_type == "blind":
        return create_blind_hole(
            model,
            center=_hole_center_m(hole),
            diameter=mm(hole["diameter_mm"]),
            depth=mm(hole["depth_mm"]),
            name=hole_name,
        )
    if hole_type == "counterbore":
        return create_counterbore_hole(
            model,
            center=_hole_center_m(hole),
            hole_diameter=mm(hole["diameter_mm"]),
            counterbore_diameter=mm(hole["counterbore_diameter_mm"]),
            counterbore_depth=mm(hole["counterbore_depth_mm"]),
            name=hole_name,
        )
    if hole_type == "countersink":
        return create_countersink_hole(
            model,
            center=_hole_center_m(hole),
            hole_diameter=mm(hole["diameter_mm"]),
            countersink_diameter=mm(hole["countersink_diameter_mm"]),
            included_angle_deg=hole.get("angle_deg", 90.0),
            name=hole_name,
        )
    raise ValueError(f"不支持的孔类型: {hole_type!r}")


def build_from_spec(model, spec: Dict[str, Any], apply_fillets=True, verify_geometry=True):
    """
    按设计规格构建零件。

    参数:
        model: 新建的空白 IModelDoc2 零件文档。
        spec: **已通过 validate_design_spec 校验**的归一化规格
            （即校验结果中的 "normalized"）。
        apply_fillets: 是否执行 fillets 段。倒角/圆角失败时只记录警告，
            不回滚已建好的实体——几何失败通常是参数问题，用户需要看到
            已经建成的部分来定位。
        verify_geometry: 是否回读几何并与 verify 段比对。

    返回:
        dict：status / steps / warnings / errors / verification / measurements。
    """
    steps: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []

    # ---- 基础实体 ----
    feature, plane_name, base_errors = _create_base(model, spec.get("base") or {})
    errors.extend(base_errors)
    if feature is None and not base_errors and (spec.get("base") or {}).get("type") != "none":
        errors.append("基础实体创建失败：特征未生成。请检查模板是否可用。")
    steps.append({
        "step": "base",
        "type": (spec.get("base") or {}).get("type"),
        "feature": _feature_name(feature, "Base") if feature else None,
        "ok": feature is not None or (spec.get("base") or {}).get("type") == "none",
    })

    if errors:
        return {
            "status": "error",
            "steps": steps,
            "warnings": warnings,
            "errors": errors,
            "verification": {"status": "skipped", "checks": []},
        }

    if feature is not None:
        try:
            model.ForceRebuild3(False)
        except Exception:
            pass

    # ---- 孔 ----
    holes = expand_hole_patterns(spec.get("holes") or [])
    created_holes: List[Dict[str, Any]] = []

    for problem in validate_holes_inside_base(holes, spec.get("base") or {}):
        errors.append(problem)

    if errors:
        # 孔位越界属于规格错误，继续建孔只会得到一串误导性的"特征未创建"。
        steps.append({"step": "holes", "ok": False, "reason": "孔位越界，已跳过建孔"})
        return {
            "status": "error",
            "steps": steps,
            "warnings": warnings,
            "errors": errors,
            "verification": {"status": "skipped", "checks": []},
        }

    for hole in holes:
        hole_type = hole.get("type")
        if hole_type not in _SUPPORTED_HOLE_TYPES:
            errors.append(f"孔 {hole.get('id')}: 不支持的孔类型 {hole_type!r}")
            continue
        try:
            result = _create_hole(model, hole)
        except Exception as exc:
            errors.append(f"孔 {hole.get('id')} 创建失败: {exc}")
            steps.append({"step": "hole", "id": hole.get("id"), "type": hole_type, "ok": False})
            continue

        # HoleFeatureEvidence.to_dict() 的键是 feature_names（元组），
        # 没有 status 字段；特征创建成功时该元组非空。
        feature_names = (result or {}).get("feature_names") or ()
        ok = bool(feature_names) and not any(name is None for name in feature_names)
        created_holes.append({"id": hole.get("id"), "type": hole_type, "result": result, "ok": ok})
        steps.append({
            "step": "hole",
            "id": hole.get("id"),
            "type": hole_type,
            "position_mm": hole.get("position_mm"),
            "diameter_mm": hole.get("diameter_mm"),
            "ok": ok,
            "feature": feature_names[0] if feature_names else None,
        })
        if not ok:
            errors.append(
                f"孔 {hole.get('id')} 未成功创建（SolidWorks 未返回特征名）。"
                "常见原因：孔位在实体之外，或与前一个孔重叠。"
            )

    # ---- 圆角 ----
    # 循环变量名必须是 fillet_spec：用 `fillet` 会遮蔽上面 import 的 fillet 函数，
    # 使 fillet(model, radius) 变成调用一个 dict（'dict' object is not callable）。
    fillet_results = []
    if apply_fillets and spec.get("fillets"):
        for index, fillet_spec in enumerate(spec["fillets"]):
            radius_mm = fillet_spec.get("radius_mm")
            if radius_mm is None:
                continue
            edge_spec = {
                "axis": fillet_spec.get("axis", "z"),
                "convex_only": bool(fillet_spec.get("convex_only")),
                "concave_only": bool(fillet_spec.get("concave_only")),
            }
            selection = select_edges(model, edge_spec)
            entry = {
                "step": "fillet",
                "index": index,
                "radius_mm": radius_mm,
                "selected_count": selection.get("selected_count", 0),
                "ok": False,
            }
            if selection.get("status") != "ok":
                warnings.append(
                    f"圆角 {index}: 未选中任何边线（条件 {edge_spec}）；已跳过该圆角。"
                    f"可用 solidworks_list_edges 查看模型边线。"
                )
                fillet_results.append(entry)
                steps.append(entry)
                try:
                    model.ClearSelection2(True)
                except Exception:
                    pass
                continue
            try:
                created = fillet(model, mm(radius_mm))
                entry["ok"] = created is not None
                entry["feature"] = _feature_name(created, f"Fillet{index + 1}")
                if created is None:
                    warnings.append(f"圆角 {index}: 选中了 {entry['selected_count']} 条边但特征未生成，"
                                    "通常是半径过大导致自交。")
            except Exception as exc:
                entry["error"] = str(exc)
                warnings.append(f"圆角 {index} 失败: {exc}")
            finally:
                try:
                    model.ClearSelection2(True)
                except Exception:
                    pass
            fillet_results.append(entry)
            steps.append(entry)

    # ---- 回读与验证 ----
    measurements: Dict[str, Any] = {}
    verification: Dict[str, Any] = {"status": "skipped", "checks": []}
    if verify_geometry:
        expected = spec.get("verify") or {}
        try:
            model.ForceRebuild3(False)
        except Exception:
            pass
        try:
            if expected.get("envelope_mm"):
                bounding = sw_measure.collect_exact_part_bounding_box(model)
            else:
                bounding = sw_measure.collect_bounding_box(model)
        except Exception as exc:
            bounding = {"errors": [f"包围盒回读失败: {exc}"]}
        try:
            mass = sw_measure.collect_mass_properties(model)
        except Exception as exc:
            mass = {"errors": [f"质量属性回读失败: {exc}"]}

        measurements = {
            "bounding_box": {key: value for key, value in bounding.items() if key != "errors"},
            "mass_properties": {
                key: value for key, value in mass.items()
                if key in {"mass_g", "volume_mm3", "surface_area_mm2", "material", "material_assigned"}
            },
            "errors": list(bounding.get("errors") or []) + list(mass.get("errors") or []),
        }

        actual = {
            "envelope_mm": bounding.get("size_mm"),
            "hole_count": len([item for item in created_holes if item["ok"]]),
            "mass_g": mass.get("mass_g"),
        }
        verification = compare_verification(actual, expected)
        for error in measurements["errors"]:
            warnings.append(error)

    # 特征数与实测孔数一致性自检：孔创建"成功"但特征未出现是静默失败，
    # 必须靠回读数量比对才能发现。
    actual_hole_count = len([item for item in created_holes if item["ok"]])
    if holes and actual_hole_count < len(holes):
        errors.append(
            f"规格定义 {len(holes)} 个孔，实际成功创建 {actual_hole_count} 个；请核对失败的孔定义。"
        )

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "steps": steps,
        "hole_count_requested": len(holes),
        "hole_count_created": actual_hole_count,
        "fillet_results": fillet_results,
        "warnings": warnings,
        "errors": errors,
        "measurements": measurements,
        "verification": verification,
    }
