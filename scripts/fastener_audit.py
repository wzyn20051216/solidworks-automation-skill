"""
@file fastener_audit.py
@brief 3D 配合层务实审计：沉头/锪孔有效性、螺栓头容纳、沉头朝向、跨零件避让。

面向“沉头是不是朝外/朝配合面装反了”“配合件有没有沉头避让特征”这类真实装配会翻车的问题，
把可验证的判据做成纯函数、离线单测；跨零件避让依赖装配元数据，作为 pilot。

判据（单位 mm）：
- 沉头有效性：沉孔直径 > 主孔径、沉孔深度 > 0，与主孔同轴。
- 头部容纳：沉孔直径 ≥ 头径 + 余量；柱形沉孔深度 ≥ 头高（内置 GB/T 常见头型尺寸表）。
- 朝向：沉头开口不应朝向配合(贴合)面（否则螺钉头顶在结合面上装不平）；同组孔朝向应一致。
- 跨零件避让（pilot）：柱头/沉头凸出侧的配合件应有避让特征或足够间隙。

来源约定见 references/design-rule-check.md。头部尺寸为常用规格近似，最终以实际紧固件手册为准。
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

# GB/T 常用头型头部尺寸（近似）：dk=头径 mm，k=头高 mm。
# socket_cap = 内六角圆柱头（GB/T 70.1）；countersunk_flat = 内六角沉头（GB/T 70.3，90°）。
HEAD_TABLE: dict[str, dict[float, dict[str, float]]] = {
    "socket_cap": {
        3.0: {"dk": 5.5, "k": 3.0},
        4.0: {"dk": 7.0, "k": 4.0},
        5.0: {"dk": 8.5, "k": 5.0},
        6.0: {"dk": 10.0, "k": 6.0},
        8.0: {"dk": 13.0, "k": 8.0},
        10.0: {"dk": 16.0, "k": 10.0},
        12.0: {"dk": 18.0, "k": 12.0},
    },
    "countersunk_flat": {
        3.0: {"dk": 6.0, "k": 1.7, "angle": 90.0},
        4.0: {"dk": 8.0, "k": 2.3, "angle": 90.0},
        5.0: {"dk": 10.0, "k": 2.8, "angle": 90.0},
        6.0: {"dk": 12.0, "k": 3.3, "angle": 90.0},
        8.0: {"dk": 16.0, "k": 4.4, "angle": 90.0},
        10.0: {"dk": 20.0, "k": 5.5, "angle": 90.0},
        12.0: {"dk": 24.0, "k": 6.5, "angle": 90.0},
    },
}

DEFAULT_HEAD_CLEARANCE_MM = 0.5
COUNTERSINK_DEFAULT_ANGLE = 90.0


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def nominal_from_thread(thread: str | None) -> float | None:
    """@brief 从螺纹标注（如 M6、M6x1）解析公称直径 mm。"""
    if not thread:
        return None
    match = re.match(r"\s*M\s*(\d+(?:\.\d+)?)", str(thread), re.IGNORECASE)
    return float(match.group(1)) if match else None


def head_dimensions(head_type: str, nominal_mm: float) -> dict[str, float] | None:
    """@brief 查头部尺寸；表外规格返回 None。"""
    table = HEAD_TABLE.get(head_type)
    if not table:
        return None
    key = round(float(nominal_mm), 1)
    return dict(table[key]) if key in table else None


def _check(check_id: str, category: str, status: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"id": check_id, "category": category, "status": status, "severity": severity, "message": message}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def parse_fastener_hole(feature: Mapping[str, Any]) -> dict[str, Any] | None:
    """@brief 从中性文档 hole 特征解析沉头/紧固信息；无沉头返回 None。"""
    params = feature.get("parameters") if isinstance(feature.get("parameters"), Mapping) else {}
    cbore = params.get("counterbore") if isinstance(params.get("counterbore"), Mapping) else None
    csink = params.get("countersink") if isinstance(params.get("countersink"), Mapping) else None
    if not cbore and not csink:
        return None
    sink_type = "counterbore" if cbore else "countersink"
    sink = cbore or csink
    head_type = str(params.get("headType") or ("socket_cap" if cbore else "countersunk_flat"))
    nominal = _num(params.get("fastenerNominalMm")) or nominal_from_thread(params.get("thread"))
    return {
        "id": str(feature.get("id") or ""),
        "main_diameter_mm": _num(params.get("diameter")),
        "sink_type": sink_type,
        "sink_diameter_mm": _num(sink.get("diameter")),
        "sink_depth_mm": _num(sink.get("depth")),
        "sink_angle_deg": _num(sink.get("angle")) or (COUNTERSINK_DEFAULT_ANGLE if csink else None),
        "sink_side": str(sink.get("side") or "") or None,
        "mating_side": str(params.get("matingSide") or "") or None,
        "head_type": head_type,
        "nominal_mm": nominal,
        "group": str(params.get("fastenerGroup") or head_type),
    }


def audit_fastener_hole(hole: Mapping[str, Any], *, head_clearance_mm: float = DEFAULT_HEAD_CLEARANCE_MM) -> list[dict[str, Any]]:
    """@brief 单件沉头审计：有效性 + 头部容纳 + 朝配合面。"""
    checks: list[dict[str, Any]] = []
    hid = hole.get("id") or "hole"
    main = hole.get("main_diameter_mm")
    sink_d = hole.get("sink_diameter_mm")
    sink_depth = hole.get("sink_depth_mm")
    sink_type = hole.get("sink_type")

    # DRC-CSK-001 沉头几何有效性
    if sink_d is None:
        checks.append(_check("DRC-CSK-001", "fastener", "info", "info", f"孔 {hid} 未提供沉孔直径，跳过有效性检查", target=hid))
    elif main is not None and sink_d <= main:
        checks.append(_check("DRC-CSK-001", "fastener", "fail", "major", f"孔 {hid} 沉孔直径 {sink_d:g} 不大于主孔 {main:g}，沉头无效", target=hid))
    elif sink_type == "counterbore" and (sink_depth is None or sink_depth <= 0):
        checks.append(_check("DRC-CSK-001", "fastener", "fail", "major", f"孔 {hid} 柱形沉孔深度非正，沉头无效", target=hid))
    else:
        checks.append(_check("DRC-CSK-001", "fastener", "pass", "info", f"孔 {hid} 沉头几何有效", target=hid))

    # DRC-CSK-002/003 头部容纳
    nominal = hole.get("nominal_mm")
    head = head_dimensions(str(hole.get("head_type")), nominal) if nominal else None
    if head is None:
        checks.append(_check("DRC-CSK-002", "fastener", "info", "info", f"孔 {hid} 头型/规格未知，跳过头部容纳检查", target=hid))
    else:
        if sink_d is not None:
            required_d = head["dk"] + head_clearance_mm
            if sink_d < required_d:
                checks.append(_check("DRC-CSK-002", "fastener", "fail", "major", f"孔 {hid} 沉孔直径 {sink_d:g} 小于头径容纳 {required_d:g}（头 {head['dk']:g}+{head_clearance_mm:g}）", target=hid, required_mm=required_d))
            else:
                checks.append(_check("DRC-CSK-002", "fastener", "pass", "info", f"孔 {hid} 沉孔直径容纳螺栓头", target=hid))
        if sink_type == "counterbore" and sink_depth is not None and "k" in head:
            if sink_depth < head["k"]:
                checks.append(_check("DRC-CSK-003", "fastener", "warning", "warning", f"孔 {hid} 沉孔深度 {sink_depth:g} 小于头高 {head['k']:g}，螺栓头不齐平", target=hid, required_mm=head["k"]))
            else:
                checks.append(_check("DRC-CSK-003", "fastener", "pass", "info", f"孔 {hid} 沉孔深度容纳头高", target=hid))

    # DRC-CSK-004 朝向配合面
    sink_side = hole.get("sink_side")
    mating_side = hole.get("mating_side")
    if not sink_side or not mating_side:
        checks.append(_check("DRC-CSK-004", "fastener", "info", "info", f"孔 {hid} 缺沉头朝向或配合面信息，跳过朝向检查", target=hid))
    elif sink_side == mating_side:
        checks.append(_check("DRC-CSK-004", "fastener", "fail", "critical", f"孔 {hid} 沉头开口朝向配合面 {mating_side}，螺钉头会顶在结合面上装不平", target=hid))
    else:
        checks.append(_check("DRC-CSK-004", "fastener", "pass", "info", f"孔 {hid} 沉头朝向 {sink_side} 背离配合面，正确", target=hid))

    return checks


def audit_orientation_consistency(holes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """@brief DRC-CSK-005 同组沉头朝向一致性：同一紧固组的沉头应朝同一侧。"""
    groups: dict[str, set[str]] = {}
    for hole in holes:
        side = hole.get("sink_side")
        if side:
            groups.setdefault(str(hole.get("group") or "default"), set()).add(str(side))
    checks: list[dict[str, Any]] = []
    for group, sides in groups.items():
        if len(sides) > 1:
            checks.append(_check("DRC-CSK-005", "fastener", "warning", "warning", f"紧固组 {group} 沉头朝向不一致: {', '.join(sorted(sides))}", target=group))
    if not checks and groups:
        checks.append(_check("DRC-CSK-005", "fastener", "pass", "info", "同组沉头朝向一致"))
    return checks


def audit_relief(stacks: Sequence[Mapping[str, Any]], *, min_gap_mm: float = 0.5) -> list[dict[str, Any]]:
    """@brief pilot·DRC-FIT-001 跨零件避让：柱头/沉头凸出侧的配合件应有避让或足够间隙。

    @param stacks 装配元数据 metadata.fastenerStacks，每项：
        {id, holeId, protrudes(bool), matingHasRelief(bool), gapMm}
    """
    if not stacks:
        return [_check("DRC-FIT-001", "fastener", "info", "info", "无装配紧固链元数据，跳过跨零件避让检查")]
    checks: list[dict[str, Any]] = []
    for stack in stacks:
        sid = str(stack.get("id") or stack.get("holeId") or "stack")
        protrudes = bool(stack.get("protrudes"))
        has_relief = bool(stack.get("matingHasRelief"))
        gap = _num(stack.get("gapMm"))
        if not protrudes:
            continue
        if has_relief:
            checks.append(_check("DRC-FIT-001", "fastener", "pass", "info", f"紧固链 {sid} 配合件已有避让特征", target=sid))
        elif gap is not None and gap >= min_gap_mm:
            checks.append(_check("DRC-FIT-001", "fastener", "pass", "info", f"紧固链 {sid} 配合面留有间隙 {gap:g}mm", target=sid))
        else:
            checks.append(_check("DRC-FIT-001", "fastener", "fail", "major", f"紧固链 {sid} 头部凸出但配合件无避让且无足够间隙，装配会顶死/干涉", target=sid))
    if not checks:
        checks.append(_check("DRC-FIT-001", "fastener", "info", "info", "无凸出紧固头，跳过跨零件避让检查"))
    return checks


def audit_fastener_holes(
    holes: Sequence[Mapping[str, Any]],
    *,
    stacks: Sequence[Mapping[str, Any]] | None = None,
    head_clearance_mm: float = DEFAULT_HEAD_CLEARANCE_MM,
) -> list[dict[str, Any]]:
    """@brief 汇总：逐孔沉头审计 + 朝向一致性 + 跨零件避让。"""
    checks: list[dict[str, Any]] = []
    if not holes:
        checks.append(_check("DRC-CSK-000", "fastener", "info", "info", "无沉头/锪孔特征，跳过紧固装配审计"))
    else:
        for hole in holes:
            checks.extend(audit_fastener_hole(hole, head_clearance_mm=head_clearance_mm))
        checks.extend(audit_orientation_consistency(holes))
    checks.extend(audit_relief(stacks or []))
    return checks


# ---------------------------------------------------------------------------
# pilot：真机圆柱面配对为沉头特征
# ---------------------------------------------------------------------------


def counterbores_from_cylinders(
    cylinders: Sequence[Mapping[str, Any]],
    *,
    normal_axis: int = 2,
    coaxial_tol_mm: float = 0.5,
) -> list[dict[str, Any]]:
    """@brief pilot：把同轴的两级圆柱（大直径=沉孔，小直径=主孔）配成沉头特征。

    输入取自 sw_review.collect_geometry_measurements 的内部圆柱孔壁
    （每项 {diameter_mm, origin_mm:[x,y,z], axis}）。沉头开口侧由大圆柱轴向位置估计，
    这里只给出主孔径/沉孔径/位置，朝向仍需结合面法向与实际模型复核（pilot）。
    """
    in_plane = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[normal_axis]
    u, v = in_plane
    groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for cyl in cylinders:
        origin = cyl.get("origin_mm")
        diameter = _num(cyl.get("diameter_mm"))
        axis = cyl.get("axis")
        if not isinstance(origin, (list, tuple)) or len(origin) < 3 or diameter is None:
            continue
        if isinstance(axis, (list, tuple)) and len(axis) >= 3 and abs(abs(float(axis[normal_axis])) - 1.0) > 0.02:
            continue
        key = (round(float(origin[u]), 1), round(float(origin[v]), 1))
        placed = False
        for existing in groups:
            if abs(existing[0] - key[0]) <= coaxial_tol_mm and abs(existing[1] - key[1]) <= coaxial_tol_mm:
                groups[existing].append({"diameter": diameter, "origin": origin})
                placed = True
                break
        if not placed:
            groups[key] = [{"diameter": diameter, "origin": origin}]

    features: list[dict[str, Any]] = []
    for (x, y), members in groups.items():
        diameters = sorted(m["diameter"] for m in members)
        if len(diameters) >= 2 and diameters[-1] > diameters[0]:
            features.append(
                {
                    "id": f"CB@{x:g},{y:g}",
                    "x_mm": x,
                    "y_mm": y,
                    "main_diameter_mm": round(diameters[0], 4),
                    "sink_diameter_mm": round(diameters[-1], 4),
                    "sink_type": "counterbore",
                }
            )
    return features
