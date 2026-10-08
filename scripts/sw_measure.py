"""
SolidWorks 测量与自检工具。

面向机械设计工程师最常用的三类自检证据：
1. 质量属性（质量、体积、表面积、质心、惯性矩）
2. 包围盒（含轴向尺寸，用于判断零件能否放进箱体/托盘）
3. 装配体干涉检查（把 InterferenceDetectionManager 封装成可审计结果）

设计约束：所有函数都返回结构化字典而非抛裸异常，便于 MCP 层把失败原因和
"下一步该怎么做"一起交给用户；但连接类错误仍然向上抛，由 MCP 层统一包装。
"""
from __future__ import annotations

import math

try:
    from .sw_connect import get_com_member
except ImportError:
    from sw_connect import get_com_member


# swMassPropertyStatus_e
_MASS_STATUS_LABELS = {
    0: "not_calculated",
    1: "calculated",
    2: "failed",
}

# 单位换算：SolidWorks 质量属性返回 SI（kg, m, m^2, m^3, kg*m^2）
_MM_PER_M = 1000.0
_KG_TO_G = 1000.0


def _safe_member(obj, name, *args, default=None):
    """@brief 安全读取 COM 成员，失败时返回默认值。"""
    try:
        member = getattr(obj, name)
        value = member(*args) if args or callable(member) else member
    except Exception:
        return default
    return default if value is None else value


def _round(value, digits=6):
    """@brief 数值安全取整，None 原样返回。"""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# swUserPreferenceDoubleValue_e.swMaterialPropertyDensity
SW_MATERIAL_DENSITY_PREF = 7

_DEFAULT_DENSITY_KG_M3 = 1000.0


def collect_mass_properties(model, density_kg_m3=None):
    """
    读取零件或装配体的质量属性。

    参数:
        model: IModelDoc2 对象。
        density_kg_m3: 可选的材料密度（kg/m³）。为 None 时使用文档当前密度；
            未分配材料的文档 SolidWorks 按 1000 kg/m³ 计算，此时结果不可直接
            用于工程判断。

    返回:
        dict，包含 mass_g / volume_mm3 / surface_area_mm2 / center_of_mass_mm 等。

    说明:
        质量属性通过 ``IModelDocExtension.CreateMassProperty`` 获取，这是官方
        推荐的 Automation 接口；不要用仅支持进程内非托管 C++ 的
        ``IGetMassProperties``。

        密度通过 ``swMaterialPropertyDensity``(7) 偏好项设置。``IMassProperty.Density``
        是**只读**属性，``SetOverrideMass`` 并非有效成员——这两条路径真机实测都不可用。

    注意:
        设置密度偏好项会**修改当前文档**的密度设定。若只做临时估算，请在调用后
        自行恢复原值（返回值中的 ``previous_density_kg_m3`` 可用于恢复）。
    """
    result = {
        "units": {"mass": "g", "length": "mm", "volume": "mm3", "area": "mm2", "inertia": "kg*mm2"},
        "mass_g": None,
        "volume_mm3": None,
        "surface_area_mm2": None,
        "center_of_mass_mm": None,
        "moment_of_inertia_kg_mm2": None,
        "density_kg_m3": density_kg_m3,
        "material": None,
        "material_assigned": None,
        "errors": [],
    }

    material = _safe_member(model, "MaterialIdName")
    result["material"] = material
    result["material_assigned"] = bool(material)
    if not material:
        # 这是工程提醒而非执行错误：质量数值本身算得出来，只是密度是默认值。
        result["warnings"] = [
            "文档未分配材料，SolidWorks 按默认密度（1000 kg/m³）计算；"
            "质量结果不可直接用于工程判断，请分配材料或显式传入 density_kg_m3。"
        ]

    try:
        extension = get_com_member(model, "Extension")
        mass_property = get_com_member(extension, "CreateMassProperty")
    except Exception as exc:
        result["errors"].append(f"创建质量属性对象失败: {exc}")
        return result

    if mass_property is None:
        result["errors"].append("CreateMassProperty 返回空对象")
        return result

    if density_kg_m3 is not None:
        try:
            previous = _safe_member(model, "GetUserPreferenceDoubleValue", SW_MATERIAL_DENSITY_PREF)
            result["previous_density_kg_m3"] = previous
            model.SetUserPreferenceDoubleValue(SW_MATERIAL_DENSITY_PREF, float(density_kg_m3))
            result["density_overridden"] = True
        except Exception as exc:
            result["density_overridden"] = False
            result["errors"].append(f"设置密度失败，将使用文档当前密度: {exc}")

    def read(name, *args):
        """@brief 读取一个质量属性成员并记录失败原因。"""
        try:
            member = getattr(mass_property, name)
            return member(*args) if args or callable(member) else member
        except Exception as exc:
            result["errors"].append(f"{name} 读取失败: {exc}")
            return None

    # IMassProperty.Status 在部分版本（实测 SW2024 SP5）不可用。它只是诊断字段，
    # 缺失时不应记入 errors，否则每次测量都会带一条无意义的告警。
    status = None
    try:
        member = getattr(mass_property, "Status")
        status = member() if callable(member) else member
    except Exception:
        pass
    result["status"] = _MASS_STATUS_LABELS.get(status, status)

    mass_kg = read("Mass")
    if mass_kg is not None:
        result["mass_g"] = _round(float(mass_kg) * _KG_TO_G, 6)

    volume_m3 = read("Volume")
    if volume_m3 is not None:
        result["volume_mm3"] = _round(float(volume_m3) * (_MM_PER_M**3), 6)

    area_m2 = read("SurfaceArea")
    if area_m2 is not None:
        result["surface_area_mm2"] = _round(float(area_m2) * (_MM_PER_M**2), 6)

    # 由质量/体积反算密度，作为"实际参与计算的密度"的独立校验：
    # 若它与传入的 density_kg_m3 明显不符，说明密度设置没有生效。
    implied_density = None
    if mass_kg not in (None, 0) and volume_m3 not in (None, 0):
        implied_density = _round(float(mass_kg) / float(volume_m3), 6)
    result["density_kg_m3"] = _round(float(density_kg_m3), 6) if density_kg_m3 is not None else implied_density
    result["implied_density_kg_m3"] = implied_density
    if density_kg_m3 is not None and implied_density is not None:
        if abs(implied_density - float(density_kg_m3)) > max(1.0, float(density_kg_m3) * 0.01):
            result["errors"].append(
                f"密度设置可能未生效：请求 {density_kg_m3} kg/m³，"
                f"但质量/体积反算出 {implied_density} kg/m³。"
            )

    # CenterOfMass 在 makepy 强类型代理下是方法，在动态代理下是属性；
    # get_com_member 已经封装了这个差异，不要直接属性访问。
    try:
        center = list(get_com_member(mass_property, "CenterOfMass") or [])
    except Exception as exc:
        result["errors"].append(f"CenterOfMass 读取失败: {exc}")
        center = []
    if len(center) >= 3:
        result["center_of_mass_mm"] = [_round(value * _MM_PER_M, 6) for value in center[:3]]

    try:
        inertia = list(get_com_member(mass_property, "GetMomentOfInertia", 0) or [])
    except Exception as exc:
        result["errors"].append(f"GetMomentOfInertia 读取失败: {exc}")
        inertia = []
    if len(inertia) >= 9:
        # 返回 3x3 对称张量；SI 单位 kg*m^2 转 kg*mm^2。
        result["moment_of_inertia_kg_mm2"] = [
            [_round(inertia[row * 3 + column] * (_MM_PER_M**2), 6) for column in range(3)]
            for row in range(3)
        ]

    return result


def collect_bounding_box(model):
    """
    读取零件的包围盒。

    参数:
        model: IModelDoc2 对象（零件）。

    返回:
        dict，包含 min_corner_mm / max_corner_mm / size_mm / diagonal_mm。

    说明:
        ``GetPartBox(True)`` 返回模型坐标系下的 [xmin,ymin,zmin,xmax,ymax,zmax]；
        装配体请使用 ``GetBox``，两者签名不同，此函数会自动选择。
    """
    result = {
        "units": "mm",
        "min_corner_mm": None,
        "max_corner_mm": None,
        "size_mm": None,
        "diagonal_mm": None,
        "errors": [],
    }

    box = None
    try:
        member = getattr(model, "GetPartBox")
        box = member(True)
    except Exception:
        try:
            box = model.GetBox(0)
        except Exception as exc:
            result["errors"].append(f"包围盒读取失败: {exc}")
            return result

    values = list(box or [])
    if len(values) < 6:
        result["errors"].append("包围盒未返回 6 个坐标值")
        return result

    scaled = [float(value) * _MM_PER_M for value in values[:6]]
    minimum, maximum = scaled[:3], scaled[3:6]
    size = [abs(maximum[index] - minimum[index]) for index in range(3)]
    result["min_corner_mm"] = [_round(value, 6) for value in minimum]
    result["max_corner_mm"] = [_round(value, 6) for value in maximum]
    result["size_mm"] = [_round(value, 6) for value in size]
    result["diagonal_mm"] = _round(math.sqrt(sum(value * value for value in size)), 6)
    return result


def inspect_interference(asm_model, treat_subassemblies_as_components=False,
                         treat_coincidence_as_interference=False, include_volume=True):
    """
    对装配体运行干涉检查。

    参数:
        asm_model: IAssemblyDoc 对象。
        treat_subassemblies_as_components: 是否把子装配体当作单一零件比较。
        treat_coincidence_as_interference: 是否把重合面视为干涉。真实工程中
            螺栓贴合面、贴合板件通常重合，此选项默认关闭可避免大量伪干涉。
        include_volume: 是否读取每个干涉体的体积（用于判断严重程度）。

    返回:
        dict，包含 interference_count、items、severity 与 manual_review_required。

    说明:
        干涉检查是"必须人工复核"的证据：结果为零不代表设计正确（可能是配合留隙
        过大或组件被压缩未参与计算），结果非零也不必然意味着错误（过盈配合、
        焊接件、注塑件干涉是设计意图）。因此始终设置 manual_review_required。
    """
    result = {
        "status": "blocked",
        "interference_count": None,
        "items": [],
        "severity": None,
        "manual_review_required": True,
        "options": {
            "treat_subassemblies_as_components": bool(treat_subassemblies_as_components),
            "treat_coincidence_as_interference": bool(treat_coincidence_as_interference),
        },
        "errors": [],
    }

    try:
        asm_model.ClearSelection2(True)
        interference = get_com_member(asm_model, "InterferenceDetectionManager")
    except Exception as exc:
        result["errors"].append(f"无法获取干涉检查对象: {exc}")
        return result

    if interference is None:
        result["errors"].append("InterferenceDetectionManager 返回空对象；请确认活动文档是装配体。")
        return result

    try:
        interference.TreatSubAssembliesAsComponents = bool(treat_subassemblies_as_components)
        interference.TreatCoincidenceAsInterference = bool(treat_coincidence_as_interference)
        interference.IgnoreHiddenBodies = False
        interference.ShowIgnoredInterferences = True
        interference.IncludeMultibodyPartInterferences = False
        result["options"].update(ignore_hidden_bodies=False,
                                 show_ignored_interferences=True,
                                 include_multibody_part_interferences=False)
        # GetInterferences 执行计算；Done 只在读取结果后释放管理器。
        raw_items = get_com_member(interference, "GetInterferences")
        detected = list(raw_items) if raw_items is not None else []
        count = int(get_com_member(interference, "GetInterferenceCount"))
        if count < 0 or count != len(detected):
            raise RuntimeError(f"干涉数量与数组不一致: {count} != {len(detected)}")
        items = []
        for index, item in enumerate(detected):
            entry = {"index": index, "name": None}
            if include_volume:
                volume_m3 = float(get_com_member(item, "Volume"))
                if not math.isfinite(volume_m3) or volume_m3 < 0:
                    raise RuntimeError(f"无效干涉体积: {volume_m3}")
                entry["volume_mm3"] = _round(volume_m3 * (_MM_PER_M**3), 6)
            components = get_com_member(item, "Components")
            entry["components"] = [
                {"name": get_com_member(component, "Name2"),
                 "path": get_com_member(component, "GetPathName")}
                for component in (components if components is not None else [])
            ]
            items.append(entry)
    except Exception as exc:
        result["errors"].append(f"配置、计算或读取干涉失败: {exc}")
        return result
    finally:
        try:
            interference.Done()
        except Exception as exc:
            result["errors"].append(f"结束干涉检查失败: {exc}")

    if result["errors"]:
        return result

    volumes = [item.get("volume_mm3") for item in items if item.get("volume_mm3") is not None]
    if count == 0:
        result["severity"] = "none"
    elif volumes and max(volumes) < 1.0:
        result["severity"] = "negligible"
    elif volumes and max(volumes) < 100.0:
        result["severity"] = "minor"
    else:
        result["severity"] = "major"

    result["status"] = "pass" if count == 0 else "warn"
    result["interference_count"] = count
    result["items"] = items
    result["max_volume_mm3"] = _round(max(volumes), 6) if volumes else None
    return result


def check_tolerance_fit(shaft_mm, hole_mm, nominal_mm=None, fit="clearance"):
    """
    计算基本尺寸的配合间隙并给出 IT 公差等级参考。

    参数:
        shaft_mm: 轴（外尺寸）实测或标称直径，mm。
        hole_mm: 孔（内尺寸）实测或标称直径，mm。
        nominal_mm: 标称尺寸，默认取孔尺寸。
        fit: "clearance"（间隙配合）| "transition"（过渡）| "interference"（过盈）。

    返回:
        dict，包含 clearance_mm 与判定结论。

    说明:
        这是**辅助判断**，不替代公差表：真实设计必须按 GB/T 1800 或 ISO 286
        查表确定上下偏差，并按功能要求选择配合代号（如 H7/g6）。
        SolidWorks 模型中的名义尺寸不含公差，因此本函数只能检查"名义间隙"，
        不能替代公差链计算。
    """
    nominal = float(nominal_mm if nominal_mm is not None else hole_mm)
    clearance = float(hole_mm) - float(shaft_mm)

    if fit == "clearance":
        expected = clearance > 0
        verdict = "间隙配合" if expected else "不是间隙配合：孔不大于轴"
    elif fit == "interference":
        expected = clearance < 0
        verdict = "过盈配合" if expected else "不是过盈配合：孔不小于轴"
    else:
        expected = True
        verdict = "过渡配合"

    return {
        "nominal_mm": _round(nominal, 6),
        "hole_mm": _round(float(hole_mm), 6),
        "shaft_mm": _round(float(shaft_mm), 6),
        "clearance_mm": _round(clearance, 6),
        "fit_requested": fit,
        "fit_satisfied": bool(expected),
        "verdict": verdict,
        "caveat": "名义尺寸不含公差，真实配合必须按 GB/T 1800 或 ISO 286 查表并做公差链计算。",
    }
