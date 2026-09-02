"""SolidWorks 原生钣金特征创建与证据回读。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .sw_connect import get_com_member
    from .sw_part import _ensure_sketch_selected
except ImportError:
    from sw_connect import get_com_member
    from sw_part import _ensure_sketch_selected


SW_FM_BASE_FLANGE = 34
SW_END_COND_BLIND = 0
SW_BEND_ALLOWANCE_K_FACTOR = 2
SW_SHEET_METAL_RELIEF_RECTANGULAR = 1
SW_SOLID_BODY = 0


@dataclass(frozen=True)
class BaseFlangeSpec:
    """@brief 基体法兰的可制造参数，全部长度单位为米。"""

    thickness: float
    bend_radius: float
    depth: float
    k_factor: float = 0.42
    relief_ratio: float = 0.5
    reverse_direction: bool = False
    reverse_thickness: bool = False

    def validate(self) -> None:
        """@brief 在进入 COM 前拒绝明显无效的制造参数。"""
        if self.thickness <= 0:
            raise ValueError("钣金厚度必须大于 0")
        if self.bend_radius < 0:
            raise ValueError("折弯半径不能小于 0")
        if self.depth <= 0:
            raise ValueError("基体法兰深度必须大于 0")
        if not 0 < self.k_factor < 1:
            raise ValueError("K 因子必须位于 0 与 1 之间")
        if self.relief_ratio <= 0:
            raise ValueError("卸料槽比例必须大于 0")


def _feature_type(feature: Any) -> str:
    """@brief 安全读取特征类型名。"""
    try:
        return str(get_com_member(feature, "GetTypeName2") or "")
    except Exception:
        return ""


def iter_features(model):
    """@brief 顺序遍历特征树，兼容 pywin32 的属性/方法两种投影。"""
    feature = get_com_member(model, "FirstFeature")
    # pywin32 可能为不同 COM 对象复用短生命周期包装器的 Python id，不能
    # 用 id 去重；以硬上限防御异常的特征链循环。
    count = 0
    while feature is not None and count < 4096:
        yield feature
        feature = get_com_member(feature, "GetNextFeature")
        count += 1


def create_base_flange(model, sketch_ref, spec: BaseFlangeSpec):
    """@brief 使用现代 FeatureData API 从开放或闭合草图创建原生基体法兰。

    开放折线路径会生成轮廓法兰；闭合轮廓会生成平板基体。返回真实
    ``IFeature``，失败时抛出异常，不把空返回值包装为成功。
    """
    spec.validate()
    _ensure_sketch_selected(model, sketch_ref)
    manager = get_com_member(model, "FeatureManager")

    bend_allowance = get_com_member(manager, "CreateCustomBendAllowance")
    if bend_allowance is None:
        raise RuntimeError("CreateCustomBendAllowance 未返回对象")
    bend_allowance.Type = SW_BEND_ALLOWANCE_K_FACTOR
    bend_allowance.KFactor = float(spec.k_factor)

    data = get_com_member(manager, "CreateDefinition", SW_FM_BASE_FLANGE)
    if data is None:
        raise RuntimeError("CreateDefinition(swFmBaseFlange) 未返回特征数据")

    data.Initialize(
        False,
        True,
        bend_allowance,
        True,
        SW_SHEET_METAL_RELIEF_RECTANGULAR,
        True,
        float(spec.relief_ratio),
        0.0,
        0.0,
    )
    data.D1EndConditionType = SW_END_COND_BLIND
    data.D1EndConditionDistance = float(spec.depth)
    data.D2EndConditionType = SW_END_COND_BLIND
    data.D2EndConditionDistance = 0.0
    data.OverrideDefaultSheetMetalParameters = True
    data.Thickness = float(spec.thickness)
    data.BendRadius = float(spec.bend_radius)
    data.ReverseDirection = bool(spec.reverse_direction)
    data.ReverseThickness = bool(spec.reverse_thickness)

    feature = get_com_member(manager, "CreateFeature", data)
    if feature is None:
        raise RuntimeError("CreateFeature(IBaseFlangeFeatureData) 创建失败")
    # GetErrorCode2 还带一个 by-ref ``isWarning`` 参数；此处只需拒绝硬错误，
    # 使用无歧义的 GetErrorCode 可兼容 pywin32 静态与动态代理。
    error_code = int(get_com_member(feature, "GetErrorCode") or 0)
    if error_code:
        raise RuntimeError(f"基体法兰返回特征错误码: {error_code}")
    return feature


def sheet_metal_evidence(model) -> dict[str, Any]:
    """@brief 回读原生特征、实体与关键钣金参数，形成可审计证据。"""
    feature_rows = []
    base_parameters = []
    for feature in iter_features(model):
        type_name = _feature_type(feature)
        name = str(get_com_member(feature, "Name") or "")
        feature_rows.append({"name": name, "type": type_name})
        if type_name in {"BaseFlange", "SMBaseFlange", "Base-Flange"}:
            definition = get_com_member(feature, "GetDefinition")
            if definition is not None:
                base_parameters.append({
                    "name": name,
                    "thickness_m": float(get_com_member(definition, "Thickness") or 0.0),
                    "bend_radius_m": float(get_com_member(definition, "BendRadius") or 0.0),
                    "depth_m": float(get_com_member(definition, "D1EndConditionDistance") or 0.0),
                    "k_factor": float(get_com_member(definition, "KFactor") or 0.0),
                })

    bodies = tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False) or ())
    body_rows = []
    for body in bodies:
        is_sheet_metal = False
        try:
            is_sheet_metal = bool(get_com_member(body, "IsSheetMetal"))
        except Exception:
            pass
        body_rows.append({
            "name": str(get_com_member(body, "Name") or ""),
            "is_sheet_metal": is_sheet_metal,
        })

    type_names = [row["type"] for row in feature_rows]
    return {
        "features": feature_rows,
        "feature_types": type_names,
        "base_flange_parameters": base_parameters,
        "bodies": body_rows,
        "has_sheet_metal_feature": any("SheetMetal" in item for item in type_names),
        "has_base_flange": bool(base_parameters),
        "all_solid_bodies_are_sheet_metal": bool(body_rows) and all(
            row["is_sheet_metal"] for row in body_rows
        ),
    }
