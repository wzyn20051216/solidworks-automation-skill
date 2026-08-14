"""
SolidWorks 质量属性读取工具
读取零件/装配体的质量、体积、表面积、重心。能力清单：mass_properties=pilot。
只读不改；不保存、不修改文档。质量依赖材料密度，未设材料时质量无意义。
"""
try:
    from .sw_connect import get_com_member
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member
    from sw_preflight import import_com_dependencies

pythoncom, _win32com, VARIANT = import_com_dependencies()


class MassPropertiesError(RuntimeError):
    """质量属性读取错误。"""


def _read_material(model):
    """@brief 尽力读取材料名（"" 表示未赋材料）。

    IModelDoc2.Material（属性）或 GetMaterialPropertyName2(config)（方法，返回
    (name, database) 元组）。任一取到非空即返回；都失败返回 ""。
    """
    if model is None:
        return ""
    for accessor, args in (("Material", ()), ("GetMaterialPropertyName2", ("",))):
        try:
            value = get_com_member(model, accessor, *args)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (tuple, list)) and value and isinstance(value[0], str) and value[0].strip():
            return value[0].strip()
    return ""


def mass_properties(model, *, accuracy=0, default_density=0.0):
    """@brief 读取质量/体积/表面积/重心。

    model: 已打开的零件或装配体文档（IModelDoc2，open_document 的结果）。经
    get_com_member(model, "Extension") 取 IModelDocExtension（属性，不要当方法）。
    accuracy: 0=普通精度。default_density: 几何无材料时的兜底密度（kg/m³），通常 0.0。

    返回证据字典：volume_mm3 / surface_mm2 / center_of_mass_mm 恒为几何值（有意义）；
    mass_kg 仅在材料已赋且 >0 时 mass_meaningful=True（status=pass），否则
    status=review_required。质量始终须人工复核材料密度（manual_review_required=True）。
    """
    result = {
        "status": "failed",
        "stage": "mass_properties",
        "mass_kg": None,
        "volume_mm3": None,
        "surface_mm2": None,
        "center_of_mass_mm": None,
        "mass_meaningful": False,
        "material": "",
        "accuracy": int(accuracy),
        "manual_review_required": True,
        "error_code": None,
        "retryable": False,
        "limitations": [
            "质量依赖材料密度；未设材料时 mass_kg 无意义",
            "密度赋值（InsertMaterial）尚未封装，关联 appearance 能力为 TODO",
        ],
    }
    try:
        if model is None:
            result["error_code"] = "MASS_NO_MODEL"
            return result
        extension = get_com_member(model, "Extension")
        if extension is None:
            result["error_code"] = "MASS_NO_EXTENSION"
            return result
        status_ref = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        props = get_com_member(
            extension, "GetMassProperties2", int(accuracy), status_ref, float(default_density)
        )
        if not props or len(props) < 6:
            result["error_code"] = "MASS_NO_PROPERTIES"
            return result
        props = [float(v) for v in props]
        # [0,1,2]=重心 m；[3]=体积 m³；[4]=表面积 m²；[5]=质量 kg
        result["center_of_mass_mm"] = [props[0] * 1000.0, props[1] * 1000.0, props[2] * 1000.0]
        result["volume_mm3"] = props[3] * 1e9
        result["surface_mm2"] = props[4] * 1e6
        result["mass_kg"] = props[5]
        material = _read_material(model)
        result["material"] = material
        meaningful = bool(material) and (props[5] is not None and props[5] > 0)
        result["mass_meaningful"] = meaningful
        result["status"] = "pass" if meaningful else "review_required"
        if not meaningful:
            result["error_code"] = "MASS_MATERIAL_UNASSIGNED" if not material else "MASS_NONPOSITIVE"
    except Exception as exc:
        result["error_code"] = "MASS_READ_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result
