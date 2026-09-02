"""SolidWorks 参数与自定义属性操作。

本模块只封装已由 SolidWorks 2024 Interop 和官方 API Help 核对的接口：
``IDimension.SetSystemValue3`` 与 ``ICustomPropertyManager.Add3/Get6``。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

try:
    from .sw_connect import get_com_member, save_document
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member, save_document
    from sw_preflight import import_com_dependencies


pythoncom, _win32com, VARIANT = import_com_dependencies()

PROPERTY_TYPES = {
    "number": 3,
    "double": 5,
    "yes_no": 11,
    "text": 30,
    "date": 64,
}
SET_VALUE_MODES = {
    "current": 1,
    "all": 2,
    "specific": 3,
}
SET_VALUE_STATUS = {
    0: "successful",
    1: "failure",
    2: "invalid_value",
    3: "driven_dimension",
    4: "model_not_loaded",
    5: "frozen_feature_owner",
}


def _configuration_names(model) -> list[str]:
    """返回文档配置名，兼容 COM 返回 tuple/list/None。"""
    names = get_com_member(model, "GetConfigurationNames")
    return [str(name) for name in (names or [])]


def _resolve_configuration_name(names: Sequence[str], requested: str) -> str | None:
    """@brief 按 SolidWorks 配置名不区分大小写语义返回实际名称。"""
    matches = [str(name) for name in names if str(name).casefold() == requested.casefold()]
    if len(matches) > 1:
        raise RuntimeError(f"配置名大小写匹配不唯一: {requested}")
    return matches[0] if matches else None


def _active_configuration_name(model) -> str:
    """@brief 返回当前活动配置名；接口不可用时返回空字符串。"""
    try:
        manager = get_com_member(model, "ConfigurationManager")
        active = get_com_member(manager, "ActiveConfiguration")
        return str(get_com_member(active, "Name") or "")
    except Exception:
        return ""


def inspect_configurations(model) -> dict[str, Any]:
    """@brief 读取配置族清单并返回当前配置，配置修改仍需人工复核。"""
    names = _configuration_names(model)
    current = _active_configuration_name(model)
    return {
        "status": "pilot" if names else "blocked",
        "configurations": names,
        "active_configuration": current,
        "review_required": True,
        "limitations": ["未执行设计表创建/编辑和大型配置族批量变更", "配置间尺寸、属性、抑制状态和几何差异仍需人工复核"],
    }


def activate_configuration(
    model,
    configuration_name: str,
    *,
    rebuild: bool = True,
    save: bool = False,
) -> dict[str, Any]:
    """@brief 激活现有配置并通过活动配置名回读验证。"""
    requested_name = str(configuration_name).strip()
    if not requested_name:
        raise ValueError("configuration_name 不能为空")
    names = _configuration_names(model)
    name = _resolve_configuration_name(names, requested_name)
    if name is None:
        raise LookupError(f"找不到配置: {requested_name}")

    before = _active_configuration_name(model)
    api_called = before != name
    api_return = bool(get_com_member(model, "ShowConfiguration2", name)) if api_called else None
    after = _active_configuration_name(model)
    readback_verified = after == name
    api_success = readback_verified
    rebuild_success = bool(get_com_member(model, "EditRebuild3")) if rebuild and readback_verified else readback_verified
    save_success = bool(save_document(model)) if save and readback_verified and rebuild_success else not save
    success = readback_verified and rebuild_success and save_success
    return {
        "success": success,
        "configuration": name,
        "requested_configuration": requested_name,
        "before": before,
        "after": after,
        "api_called": api_called,
        "api_return": api_return,
        "api_success": api_success,
        "readback_verified": readback_verified,
        "rebuild_success": rebuild_success,
        "save_requested": save,
        "save_success": save_success,
        "review_required": True,
    }


def create_configuration(
    model,
    configuration_name: str,
    *,
    comment: str = "",
    alternate_name: str = "",
    options: int = 0,
    if_exists: str = "reuse",
    activate: bool = True,
    rebuild: bool = True,
    save: bool = False,
) -> dict[str, Any]:
    """@brief 使用 AddConfiguration3 创建配置，并校验清单及活动配置回读。

    ``options`` 对应官方 ``swConfigurationOptions2_e`` 位掩码。默认值 0 保持
    SolidWorks 默认行为；非零值必须由调用者基于目标版本枚举显式提供。
    """
    requested_name = str(configuration_name).strip()
    if not requested_name:
        raise ValueError("configuration_name 不能为空")
    if if_exists not in {"reuse", "error"}:
        raise ValueError("if_exists 只支持 reuse 或 error")
    if int(options) < 0:
        raise ValueError("options 不能为负数")

    before_names = _configuration_names(model)
    existing_name = _resolve_configuration_name(before_names, requested_name)
    existed = existing_name is not None
    name = existing_name or requested_name
    if existed and if_exists == "error":
        raise FileExistsError(f"配置已存在: {name}")

    created = None if existed else get_com_member(
        model,
        "AddConfiguration3",
        name,
        str(comment),
        str(alternate_name),
        int(options),
    )
    if not existed and created is None:
        raise RuntimeError(f"AddConfiguration3 未返回配置对象: {name}")

    after_names = _configuration_names(model)
    listed_name = _resolve_configuration_name(after_names, name)
    listed = listed_name is not None
    name = listed_name or name
    activation = (
        activate_configuration(model, name, rebuild=rebuild, save=False)
        if activate and listed
        else None
    )
    if activation:
        rebuild_success = bool(activation["rebuild_success"])
    elif rebuild and listed:
        rebuild_success = bool(get_com_member(model, "EditRebuild3"))
    else:
        rebuild_success = listed
    active_verified = activation["readback_verified"] if activation else True
    save_success = bool(save_document(model)) if save and listed and rebuild_success and active_verified else not save
    success = listed and rebuild_success and active_verified and save_success
    return {
        "success": success,
        "configuration": name,
        "requested_configuration": requested_name,
        "created": not existed,
        "reused": existed,
        "listed_after_create": listed,
        "configurations_before": before_names,
        "configurations_after": after_names,
        "options": int(options),
        "activation": activation,
        "save_requested": save,
        "save_success": save_success,
        "review_required": True,
    }


def _dimension_value_mm(dimension, configuration_name: str | None = None) -> float:
    """读取尺寸系统值并转为毫米。"""
    if configuration_name:
        return float(dimension.GetSystemValue2(configuration_name)) * 1000.0
    return float(get_com_member(dimension, "SystemValue")) * 1000.0


def update_dimension_mm(
    model,
    dimension_name: str,
    value_mm: float,
    *,
    configuration_mode: str = "current",
    configuration_names: Sequence[str] | None = None,
    rebuild: bool = True,
    save: bool = False,
) -> dict[str, Any]:
    """修改命名尺寸并返回可审计证据。

    ``configuration_mode`` 支持 ``current``、``all``、``specific``；specific
    必须提供配置名。SolidWorks API 内部单位为米。
    """
    if not dimension_name.strip():
        raise ValueError("dimension_name 不能为空")
    if value_mm <= 0:
        raise ValueError("value_mm 必须大于 0")
    if configuration_mode not in SET_VALUE_MODES:
        raise ValueError(f"不支持的配置范围: {configuration_mode}")

    dimension = model.Parameter(dimension_name)
    if dimension is None:
        raise LookupError(f"找不到尺寸: {dimension_name}")

    requested_names = [str(name).strip() for name in (configuration_names or []) if str(name).strip()]
    if configuration_mode == "specific" and not requested_names:
        raise ValueError("specific 模式必须提供 configuration_names")
    if configuration_mode == "all":
        evidence_names = _configuration_names(model)
    elif configuration_mode == "specific":
        evidence_names = requested_names
    else:
        evidence_names = []

    before = (
        {name: _dimension_value_mm(dimension, name) for name in evidence_names}
        if evidence_names
        else {"current": _dimension_value_mm(dimension)}
    )
    names_variant = (
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, requested_names)
        if configuration_mode == "specific"
        else None
    )
    status_code = int(
        dimension.SetSystemValue3(
            float(value_mm) / 1000.0,
            SET_VALUE_MODES[configuration_mode],
            names_variant,
        )
    )
    rebuild_success = (
        bool(get_com_member(model, "EditRebuild3"))
        if rebuild and status_code == 0
        else status_code == 0
    )
    after = (
        {name: _dimension_value_mm(dimension, name) for name in evidence_names}
        if evidence_names
        else {"current": _dimension_value_mm(dimension)}
    )
    save_success = bool(save_document(model)) if save and status_code == 0 and rebuild_success else not save
    success = status_code == 0 and rebuild_success and save_success
    return {
        "success": success,
        "dimension": dimension_name,
        "configuration_mode": configuration_mode,
        "configuration_names": requested_names,
        "requested_mm": float(value_mm),
        "before_mm": before,
        "after_mm": after,
        "set_status": status_code,
        "set_status_label": SET_VALUE_STATUS.get(status_code, f"unknown_{status_code}"),
        "rebuild_success": rebuild_success,
        "save_requested": save,
        "save_success": save_success,
    }


def _property_manager(model, configuration_name: str = ""):
    manager = model.Extension.CustomPropertyManager(configuration_name)
    if manager is None:
        scope = configuration_name or "文件级"
        raise RuntimeError(f"无法取得 {scope} 自定义属性管理器")
    return manager


def read_custom_property(model, name: str, *, configuration_name: str = "") -> dict[str, Any]:
    """读取一个文件级或配置级自定义属性。"""
    manager = _property_manager(model, configuration_name)
    raw_value = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    resolved_value = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    was_resolved = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    is_linked = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    status = int(manager.Get6(name, False, raw_value, resolved_value, was_resolved, is_linked))
    return {
        "name": name,
        "configuration": configuration_name,
        "status": status,
        "exists": status != 1,
        "raw": str(raw_value.value or ""),
        "resolved": str(resolved_value.value or ""),
        "was_resolved": bool(was_resolved.value),
        "is_linked": bool(is_linked.value),
    }


def set_custom_properties(
    model,
    properties: Mapping[str, Any],
    *,
    configuration_name: str = "",
    property_type: str = "text",
    save: bool = False,
) -> dict[str, Any]:
    """写入文件级或配置级属性，并逐项回读验证。"""
    if not properties:
        raise ValueError("properties 不能为空")
    if property_type not in PROPERTY_TYPES:
        raise ValueError(f"不支持的属性类型: {property_type}")
    manager = _property_manager(model, configuration_name)
    results = []
    for raw_name, raw_value in properties.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("属性名不能为空")
        value = str(raw_value)
        add_status = int(manager.Add3(name, PROPERTY_TYPES[property_type], value, 2))
        readback = read_custom_property(model, name, configuration_name=configuration_name)
        verified = add_status == 0 and readback["exists"] and readback["raw"] == value
        results.append({
            "name": name,
            "requested": value,
            "add_status": add_status,
            "verified": verified,
            "readback": readback,
        })
    save_success = bool(save_document(model)) if save and all(item["verified"] for item in results) else not save
    return {
        "success": all(item["verified"] for item in results) and save_success,
        "configuration": configuration_name,
        "property_type": property_type,
        "properties": results,
        "save_requested": save,
        "save_success": save_success,
    }
