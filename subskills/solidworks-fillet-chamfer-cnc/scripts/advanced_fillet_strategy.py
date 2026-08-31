"""SolidWorks 高级圆角的离线契约与本机能力探测。

@brief 为可变半径、面圆角、全圆角和 setback 提供严格参数校验。
@details 本模块不连接 SolidWorks；类型库探测也只读取本机 COM 元数据。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


ADVANCED_KINDS = ("variable", "face", "full_round", "setback")

REQUIRED_INTERFACES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "variable": {
        "IFeatureManager": ("FeatureFillet3",),
        "IVariableFilletFeatureData2": (
            "GetControlPointsCount",
            "GetControlPointRadiusAtIndex",
            "SetControlPointRadiusAtIndex",
        ),
    },
    "face": {
        "IFeatureManager": ("CreateDefinition", "CreateFeature"),
        "ISimpleFilletFeatureData2": ("Initialize", "SetFaces"),
    },
    "full_round": {
        "IFeatureManager": ("CreateDefinition", "CreateFeature"),
        "ISimpleFilletFeatureData2": ("Initialize", "SetFaces"),
    },
    "setback": {
        "IFeatureManager": ("FeatureFillet3",),
        "ISimpleFilletFeatureData2": ("GetSetbackVerticesCount",),
    },
}


@dataclass(frozen=True)
class VariableFilletSpec:
    """@brief 单边可变半径圆角参数，长度单位为毫米。"""

    start_radius: float = 2.0
    end_radius: float = 5.0
    control_points: tuple[tuple[float, float], ...] = ()
    transition: str = "smooth"
    overflow: str = "default"


@dataclass(frozen=True)
class FaceFilletSpec:
    """@brief 两组相邻面的面圆角参数。"""

    radius: float = 4.0
    propagate_tangent: bool = False
    overflow: str = "default"


@dataclass(frozen=True)
class FullRoundFilletSpec:
    """@brief 侧面组 1、中心面组、侧面组 2 的全圆角参数。"""

    propagate_tangent: bool = False


@dataclass(frozen=True)
class SetbackFilletSpec:
    """@brief 三边交汇角的恒定半径与逐边 setback 距离。"""

    radius: float = 3.0
    distances: tuple[float, float, float] = (4.0, 4.0, 4.0)
    overflow: str = "default"


def _finite_positive(name: str, value: Any) -> float:
    """@brief 返回有限正数，否则抛出可读错误。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} 必须是有限正数")
    return number


def validate_variable_spec(spec: VariableFilletSpec, *, edge_length_mm: float) -> dict[str, Any]:
    """@brief 校验端点半径、控制点位置和过渡方式。"""
    edge_length = _finite_positive("edge_length_mm", edge_length_mm)
    radii = [
        _finite_positive("start_radius", spec.start_radius),
        _finite_positive("end_radius", spec.end_radius),
    ]
    controls: list[dict[str, float]] = []
    last_location = 0.0
    for index, item in enumerate(spec.control_points):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError(f"control_points[{index}] 必须是 (位置比例, 半径)")
        location = float(item[0])
        radius = _finite_positive(f"control_points[{index}].radius", item[1])
        if not math.isfinite(location) or not 0.0 < location < 1.0:
            raise ValueError("控制点位置比例必须严格位于 0 和 1 之间")
        if location <= last_location:
            raise ValueError("控制点位置必须严格递增")
        last_location = location
        radii.append(radius)
        controls.append({"location": location, "radius_mm": radius})
    if spec.transition not in {"smooth", "straight"}:
        raise ValueError("transition 必须是 smooth 或 straight")
    if spec.overflow not in {"default", "keep_edge", "keep_surface"}:
        raise ValueError("overflow 值无效")
    if max(radii) * 2.0 >= edge_length:
        raise ValueError("最大圆角直径必须小于目标边长度")
    return {
        "status": "pass",
        "kind": "variable",
        "endpoint_radii_mm": radii[:2],
        "control_points": controls,
        "edge_length_mm": edge_length,
    }


def validate_face_spec(spec: FaceFilletSpec, *, clearance_mm: float) -> dict[str, Any]:
    """@brief 校验面圆角半径不超过相邻面的可用包络。"""
    radius = _finite_positive("radius", spec.radius)
    clearance = _finite_positive("clearance_mm", clearance_mm)
    if radius >= clearance:
        raise ValueError("面圆角半径必须小于两面可用净空")
    if spec.overflow not in {"default", "keep_edge", "keep_surface"}:
        raise ValueError("overflow 值无效")
    return {"status": "pass", "kind": "face", "radius_mm": radius}


def validate_full_round_spec(
    _spec: FullRoundFilletSpec,
    *,
    face_set_counts: tuple[int, int, int],
) -> dict[str, Any]:
    """@brief 校验全圆角三组面均非空且互不混组。"""
    if len(face_set_counts) != 3 or any(int(count) <= 0 for count in face_set_counts):
        raise ValueError("全圆角必须提供非空的侧面组1、中心面组、侧面组2")
    return {
        "status": "pass",
        "kind": "full_round",
        "face_set_counts": list(face_set_counts),
    }


def validate_setback_spec(
    spec: SetbackFilletSpec,
    *,
    incident_edge_lengths_mm: Iterable[float],
) -> dict[str, Any]:
    """@brief 校验三条交汇边与逐边 setback 数组的一一对应关系。"""
    radius = _finite_positive("radius", spec.radius)
    lengths = [_finite_positive("incident_edge_length", item) for item in incident_edge_lengths_mm]
    distances = [_finite_positive("setback_distance", item) for item in spec.distances]
    if len(lengths) != 3 or len(distances) != 3:
        raise ValueError("当前稳定 setback 路径要求恰好三条交汇边和三个距离")
    for index, (distance, length) in enumerate(zip(distances, lengths)):
        if distance >= length:
            raise ValueError(f"setback 距离[{index}] 必须小于对应边长")
    if radius >= min(lengths) / 2.0:
        raise ValueError("setback 圆角半径必须小于最短交汇边的一半")
    return {
        "status": "pass",
        "kind": "setback",
        "radius_mm": radius,
        "distances_mm": distances,
        "incident_edge_lengths_mm": lengths,
    }


def inspect_typelib_members(type_library_path: Path) -> dict[str, set[str]]:
    """@brief 读取 SolidWorks 类型库并返回接口成员集合。"""
    try:
        import pythoncom
    except ImportError as exc:  # pragma: no cover - 非 Windows CI 路径
        raise RuntimeError("缺少 pywin32，无法读取 SolidWorks 类型库") from exc
    path = Path(type_library_path)
    if not path.is_file():
        raise FileNotFoundError(f"SolidWorks 类型库不存在: {path}")
    library = pythoncom.LoadTypeLib(str(path))
    interfaces: dict[str, set[str]] = {}
    wanted = {name for requirements in REQUIRED_INTERFACES.values() for name in requirements}
    for index in range(library.GetTypeInfoCount()):
        info = library.GetTypeInfo(index)
        name = library.GetDocumentation(index)[0]
        if name not in wanted:
            continue
        attributes = info.GetTypeAttr()
        interfaces[name] = {
            info.GetNames(info.GetFuncDesc(member_index).memid)[0]
            for member_index in range(attributes.cFuncs)
        }
    return interfaces


def build_capability_report(
    interfaces: Mapping[str, Iterable[str]],
    *,
    source: str,
) -> dict[str, Any]:
    """@brief 对照精确接口契约生成逐能力可审计报告。"""
    normalized = {name: set(members) for name, members in interfaces.items()}
    capabilities: dict[str, Any] = {}
    for kind, requirements in REQUIRED_INTERFACES.items():
        missing: list[str] = []
        present: list[str] = []
        for interface, members in requirements.items():
            found = normalized.get(interface, set())
            for member in members:
                qualified = f"{interface}.{member}"
                (present if member in found else missing).append(qualified)
        capabilities[kind] = {
            "status": "interface_ready" if not missing else "blocked",
            "present": present,
            "missing": missing,
        }
    return {
        "schema_version": 1,
        "source": source,
        "capabilities": capabilities,
        "note": "interface_ready 只代表接口存在，必须通过真机建模证据后才能标记 verified。",
    }


def spec_payload(spec: Any, validation: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 把不可变参数对象转换为 JSON 友好的执行计划。"""
    return {
        "schema_version": 1,
        "spec": asdict(spec),
        "validation": dict(validation),
    }
