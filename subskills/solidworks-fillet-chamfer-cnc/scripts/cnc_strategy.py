"""CNC 多圆角/倒角子技能的离线参数、DFM 约束与执行计划。

@brief 在连接 SolidWorks COM 之前验证参数，并生成可审计的特征计划。
@details 本模块只使用 Python 标准库，可用于 CI、VibeCAD 和桌面端预检。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class MountParameters:
    """@brief CNC 安装座参数，所有长度单位均为毫米。"""

    length: float = 120.0
    width: float = 80.0
    thickness: float = 18.0
    boss_length: float = 58.0
    boss_width: float = 34.0
    boss_height: float = 10.0
    base_corner_radius: float = 8.0
    boss_corner_radius: float = 5.0
    top_chamfer: float = 1.0
    bottom_chamfer: float = 0.8
    boss_top_chamfer: float = 0.8
    hole_chamfer: float = 0.5
    chamfer_angle_deg: float = 45.0
    mount_hole_diameter: float = 7.0
    counterbore_diameter: float = 13.0
    counterbore_depth: float = 4.0
    mount_hole_x: float = 46.0
    mount_hole_y: float = 28.0
    dowel_hole_diameter: float = 5.0
    dowel_hole_x: float = 0.0
    dowel_hole_y: float = 24.0
    slot_length: float = 62.0
    slot_width: float = 16.0
    pocket_length: float = 24.0
    pocket_width: float = 30.0
    pocket_center_x: float = 45.0
    pocket_depth: float = 4.0
    pocket_shape: str = "rounded_slot"
    minimum_edge_wall: float = 2.0
    minimum_feature_web: float = 2.0
    minimum_bottom_wall: float = 3.0


NUMERIC_FIELDS = tuple(
    item.name for item in fields(MountParameters) if item.name != "pocket_shape"
)
NONNEGATIVE_FIELDS = {
    "base_corner_radius",
    "boss_corner_radius",
    "top_chamfer",
    "bottom_chamfer",
    "boss_top_chamfer",
    "hole_chamfer",
    "dowel_hole_x",
    "dowel_hole_y",
}
POCKET_SHAPES = {"rounded_slot", "rectangle"}
INVALID_BASENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def finite_number(name: str, value: Any) -> float:
    """@brief 把输入转换为有限浮点数。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数值")
    return number


def validate_basename(value: str) -> str:
    """@brief 验证输出基名，禁止路径逃逸和 Windows 非法字符。"""
    basename = str(value).strip()
    if not basename or basename in {".", ".."}:
        raise ValueError("basename 不能为空或为点路径")
    if Path(basename).name != basename or INVALID_BASENAME.search(basename):
        raise ValueError("basename 只能是文件基名，不能包含路径或 Windows 非法字符")
    return basename


def _coerce_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验参数键并按字段类型转换覆盖值。"""
    allowed = {item.name for item in fields(MountParameters)}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError(f"未知参数: {', '.join(unknown)}")
    result: dict[str, Any] = {}
    for name, value in overrides.items():
        if name == "pocket_shape":
            result[name] = str(value).strip().lower()
        else:
            result[name] = finite_number(name, value)
    return result


def parse_set_values(items: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """@brief 解析重复的 ``--set name=value`` 参数。"""
    overrides: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set 必须使用 name=value 格式: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name or not value.strip():
            raise ValueError(f"--set 的名称和值不能为空: {item}")
        overrides[name] = value.strip()
    return _coerce_overrides(overrides)


def load_parameter_file(path: Path) -> dict[str, Any]:
    """@brief 读取 JSON 参数文件；支持直接对象或 ``parameters`` 包装对象。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取参数文件 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("参数文件根节点必须是 JSON 对象")
    values = payload.get("parameters", payload)
    if not isinstance(values, dict):
        raise ValueError("parameters 必须是 JSON 对象")
    return _coerce_overrides(values)


def parameter_positions(params: MountParameters) -> dict[str, list[tuple[float, float]]]:
    """@brief 返回孔位的唯一真源，供建模与离线碰撞检查共同使用。"""
    mount = [
        (x, y)
        for x in (-params.mount_hole_x, params.mount_hole_x)
        for y in (-params.mount_hole_y, params.mount_hole_y)
    ]
    dowel = [
        (-params.dowel_hole_x, -params.dowel_hole_y),
        (params.dowel_hole_x, params.dowel_hole_y),
    ]
    return {"mount": mount, "dowel": dowel}


def _circle_gap(
    first: tuple[float, float],
    first_radius: float,
    second: tuple[float, float],
    second_radius: float,
) -> float:
    """@brief 计算两个圆形加工特征之间的净间距。"""
    return math.dist(first, second) - first_radius - second_radius


def _point_to_centered_slot_gap(
    point: tuple[float, float],
    point_radius: float,
    size_x: float,
    size_y: float,
) -> float:
    """@brief 计算圆形特征到原点水平或垂直长圆槽的净间距。"""
    if size_x >= size_y:
        slot_radius = size_y / 2.0
        half_centerline = max(0.0, size_x / 2.0 - slot_radius)
        closest = (min(max(point[0], -half_centerline), half_centerline), 0.0)
    else:
        slot_radius = size_x / 2.0
        half_centerline = max(0.0, size_y / 2.0 - slot_radius)
        closest = (0.0, min(max(point[1], -half_centerline), half_centerline))
    return math.dist(point, closest) - point_radius - slot_radius


def analyze_parameters(params: MountParameters) -> dict[str, Any]:
    """@brief 执行无 COM 的工程参数和二维包络检查。"""
    errors: list[str] = []
    warnings: list[str] = []

    for name in NUMERIC_FIELDS:
        value = finite_number(name, getattr(params, name))
        if name in NONNEGATIVE_FIELDS:
            if value < 0.0:
                errors.append(f"{name} 不能小于 0")
        elif value <= 0.0:
            errors.append(f"{name} 必须大于 0")

    if params.pocket_shape not in POCKET_SHAPES:
        errors.append(f"pocket_shape 必须是 {sorted(POCKET_SHAPES)} 之一")
    if not 5.0 <= params.chamfer_angle_deg <= 85.0:
        errors.append("chamfer_angle_deg 必须在 5 到 85 度之间")
    if params.boss_length + 2.0 * params.minimum_feature_web > params.length:
        errors.append("boss_length 未在基体长度方向保留最小台阶宽度")
    if params.boss_width + 2.0 * params.minimum_feature_web > params.width:
        errors.append("boss_width 未在基体宽度方向保留最小台阶宽度")
    if params.base_corner_radius * 2.0 >= min(params.length, params.width):
        errors.append("base_corner_radius 过大，外轮廓圆角会自交或退化")
    if params.boss_corner_radius * 2.0 >= min(params.boss_length, params.boss_width):
        errors.append("boss_corner_radius 过大，凸台圆角会自交或退化")

    if params.top_chamfer > params.thickness / 2.0:
        errors.append("top_chamfer 不能大于基体厚度的一半")
    if params.bottom_chamfer > params.thickness / 2.0:
        errors.append("bottom_chamfer 不能大于基体厚度的一半")
    if params.top_chamfer + params.bottom_chamfer >= params.thickness:
        errors.append("顶面与底面倒角在厚度方向没有保留实体")
    if params.boss_top_chamfer > params.boss_height / 2.0:
        errors.append("boss_top_chamfer 不能大于凸台高度的一半")
    if params.base_corner_radius and params.top_chamfer > params.base_corner_radius:
        warnings.append("top_chamfer 大于 base_corner_radius，外轮廓交汇处求解风险较高")
    if params.boss_corner_radius and params.boss_top_chamfer > params.boss_corner_radius:
        warnings.append("boss_top_chamfer 大于 boss_corner_radius，凸台交汇处求解风险较高")

    if params.counterbore_diameter <= params.mount_hole_diameter:
        errors.append("counterbore_diameter 必须大于 mount_hole_diameter")
    if params.counterbore_depth >= params.thickness - params.minimum_bottom_wall:
        errors.append("counterbore_depth 未保留 minimum_bottom_wall")
    if params.pocket_depth >= params.thickness - params.minimum_bottom_wall:
        errors.append("pocket_depth 未保留 minimum_bottom_wall")
    if params.hole_chamfer > params.counterbore_depth / 2.0:
        errors.append("hole_chamfer 相对沉孔深度过大")

    positions = parameter_positions(params)
    mount_radius = params.counterbore_diameter / 2.0 + params.hole_chamfer
    dowel_radius = params.dowel_hole_diameter / 2.0 + params.hole_chamfer
    for label, points, radius in (
        ("安装沉孔", positions["mount"], mount_radius),
        ("定位孔", positions["dowel"], dowel_radius),
    ):
        for x, y in points:
            if abs(x) + radius + params.minimum_edge_wall > params.length / 2.0:
                errors.append(f"{label} X={x:g} 超出基体或未保留外边壁厚")
            if abs(y) + radius + params.minimum_edge_wall > params.width / 2.0:
                errors.append(f"{label} Y={y:g} 超出基体或未保留外边壁厚")

    all_holes = [
        *(('mount', point, mount_radius) for point in positions["mount"]),
        *(('dowel', point, dowel_radius) for point in positions["dowel"]),
    ]
    if len(set(positions["dowel"])) != len(positions["dowel"]):
        errors.append("两个定位孔位置重合；dowel_hole_x 与 dowel_hole_y 不能同时为 0")
    for index, (first_kind, first, first_radius) in enumerate(all_holes):
        for second_kind, second, second_radius in all_holes[index + 1 :]:
            gap = _circle_gap(first, first_radius, second, second_radius)
            if gap < params.minimum_feature_web:
                errors.append(
                    f"{first_kind} 孔 {first} 与 {second_kind} 孔 {second} 的净间距 "
                    f"{gap:.3f} mm 小于 minimum_feature_web"
                )

    slot_major = max(params.slot_length, params.slot_width)
    if not math.isclose(params.slot_length, slot_major):
        warnings.append("slot_length 小于 slot_width；建模时会自动按较长尺寸作为槽轴方向")
    if params.slot_length + 2.0 * params.minimum_edge_wall > params.length:
        errors.append("中心长圆槽在长度方向未保留外边壁厚")
    if params.slot_width + 2.0 * params.minimum_edge_wall > params.width:
        errors.append("中心长圆槽在宽度方向未保留外边壁厚")
    if params.slot_length > params.boss_length or params.slot_width > params.boss_width:
        warnings.append("中心槽超出凸台包络，将同时切入基体；确认这是贯穿通道而非封闭凸台槽")

    if abs(params.pocket_center_x) + params.pocket_length / 2.0 + params.minimum_edge_wall > params.length / 2.0:
        errors.append("减重口袋在 X 方向超出基体或未保留外边壁厚")
    if params.pocket_width / 2.0 + params.minimum_edge_wall > params.width / 2.0:
        errors.append("减重口袋在 Y 方向超出基体或未保留外边壁厚")
    center_slot_half_x = params.slot_length / 2.0
    pocket_inner_x = abs(params.pocket_center_x) - params.pocket_length / 2.0
    slot_pocket_web = pocket_inner_x - center_slot_half_x
    if slot_pocket_web < params.minimum_feature_web:
        errors.append(
            f"中心槽与减重口袋的 X 向净间距 {slot_pocket_web:.3f} mm "
            "小于 minimum_feature_web"
        )
    if params.pocket_shape == "rectangle":
        warnings.append("矩形口袋含尖锐内角；CNC 交付应给出刀具圆角或改用 rounded_slot")

    for kind, point, radius in all_holes:
        gap = _point_to_centered_slot_gap(point, radius, params.slot_length, params.slot_width)
        if gap < params.minimum_feature_web:
            errors.append(f"{kind} 孔 {point} 与中心槽净间距 {gap:.3f} mm 不足")
        pocket_dx = abs(abs(point[0]) - abs(params.pocket_center_x)) - params.pocket_length / 2.0
        pocket_dy = abs(point[1]) - params.pocket_width / 2.0
        approximate_gap = math.hypot(max(0.0, pocket_dx), max(0.0, pocket_dy)) - radius
        if pocket_dx <= 0.0 and pocket_dy <= 0.0:
            approximate_gap = -radius
        if approximate_gap < params.minimum_feature_web:
            errors.append(f"{kind} 孔 {point} 与减重口袋包络净间距不足")

    return {
        "status": "blocked" if errors else "pass_with_warnings" if warnings else "pass",
        "errors": errors,
        "warnings": warnings,
        "calculated": {
            "mount_hole_positions_mm": positions["mount"],
            "dowel_hole_positions_mm": positions["dowel"],
            "slot_to_pocket_web_mm": round(slot_pocket_web, 6),
            "base_bottom_wall_mm": round(params.thickness - params.pocket_depth, 6),
            "counterbore_bottom_wall_mm": round(params.thickness - params.counterbore_depth, 6),
        },
    }


def require_valid_parameters(params: MountParameters) -> dict[str, Any]:
    """@brief 参数存在硬错误时立即阻断 COM 建模。"""
    report = analyze_parameters(params)
    if report["errors"]:
        raise ValueError("；".join(report["errors"]))
    return report


def build_parameters(*overrides: Mapping[str, Any]) -> tuple[MountParameters, dict[str, Any]]:
    """@brief 按传入顺序叠加参数，并返回校验后的不可变对象。"""
    params = MountParameters()
    for values in overrides:
        params = replace(params, **_coerce_overrides(values))
    report = require_valid_parameters(params)
    return params, report


def fallback_values(value_mm: float, policy: str) -> list[float]:
    """@brief 生成有界且可追溯的尺寸降级阶梯。"""
    if value_mm <= 0.0:
        return []
    if policy == "strict":
        return [value_mm]
    if policy != "progressive":
        raise ValueError("failure_policy 必须为 strict 或 progressive")
    values = [value_mm, value_mm * 0.75, value_mm * 0.5]
    return list(dict.fromkeys(round(item, 6) for item in values if item >= 0.1))


def build_operation_plan(params: MountParameters, failure_policy: str = "progressive") -> list[dict[str, Any]]:
    """@brief 生成语义目标、期望边数和尺寸降级均明确的执行计划。"""
    operations = [
        ("outer_treatments", "Fillet_Base_Corners", "fillet", "base_vertical_edges", 4, params.base_corner_radius),
        ("outer_treatments", "Fillet_Boss_Corners", "fillet", "boss_vertical_edges", 4, params.boss_corner_radius),
        (
            "outer_treatments",
            "Chamfer_Top_Outer",
            "chamfer",
            "base_top_outer_loop",
            8 if params.base_corner_radius > 0.0 else 4,
            params.top_chamfer,
        ),
        (
            "outer_treatments",
            "Chamfer_Bottom_Outer",
            "chamfer",
            "base_bottom_outer_loop",
            8 if params.base_corner_radius > 0.0 else 4,
            params.bottom_chamfer,
        ),
        (
            "outer_treatments",
            "Chamfer_Boss_Top",
            "chamfer",
            "boss_top_outer_loop",
            8 if params.boss_corner_radius > 0.0 else 4,
            params.boss_top_chamfer,
        ),
        ("finishing", "Chamfer_Hole_Mouths", "chamfer", "hole_mouth_loops", 6, params.hole_chamfer),
    ]
    plan = []
    for stage, name, kind, target, expected_count, value in operations:
        if value <= 0.0:
            continue
        plan.append(
            {
                "stage": stage,
                "name": name,
                "kind": kind,
                "target": target,
                "expected_edge_count": expected_count,
                "requested_value_mm": value,
                "attempt_values_mm": fallback_values(value, failure_policy),
                "angle_deg": params.chamfer_angle_deg if kind == "chamfer" else None,
                "required": True,
            }
        )
    return plan


def plan_payload(
    params: MountParameters,
    validation: Mapping[str, Any],
    failure_policy: str,
) -> dict[str, Any]:
    """@brief 返回可直接序列化的 v2 计划载荷。"""
    return {
        "schema_version": 2,
        "units": "mm",
        "parameters": asdict(params),
        "validation": dict(validation),
        "failure_policy": failure_policy,
        "operations": build_operation_plan(params, failure_policy),
    }
