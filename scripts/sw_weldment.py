"""SolidWorks 原生焊件结构构件与切割清单封装。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

try:
    from .sw_connect import get_com_member, save_document
    from .sw_document_data import set_custom_properties
    from .sw_part import _ensure_sketch_selected
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member, save_document
    from sw_document_data import set_custom_properties
    from sw_part import _ensure_sketch_selected
    from sw_preflight import import_com_dependencies


pythoncom, _win32com, VARIANT = import_com_dependencies()

SW_CONNECTED_SEGMENTS_SIMPLE_CUT = 1
SW_END_CONDITION_MITER = 1
SW_SOLID_BODY = 0
CORE_CUT_LIST_PROPERTY_NAMES = {
    "length",
    "长度",
    "angle1",
    "角度1",
    "angle2",
    "角度2",
    "angle direction",
    "角度方向",
    "angle rotation",
    "角度旋转",
    "description",
    "说明",
    "material",
    "材料",
    "weight",
    "质量",
    "单重",
    "quantity",
    "数量",
    "total length",
    "总长度",
    "unit_of_measure",
    "计量单位",
    "profile_designation",
    "material_spec",
    "source_repository",
    "source_sku",
}


def _as_tuple(value) -> tuple:
    """@brief 把 COM 单对象、SAFEARRAY 或空值规范为元组。"""
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(item for item in value if item is not None)
    return (value,)


def _active_configuration_name(model) -> str:
    """@brief 回读活动配置名，供自定义配置型材调用使用。"""
    manager = get_com_member(model, "ConfigurationManager")
    configuration = get_com_member(manager, "ActiveConfiguration")
    return str(get_com_member(configuration, "Name") or "")


def create_weldment_profile(
    model,
    sketch_ref,
    output_path: str | Path,
    *,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """@brief 将选定轮廓草图保存为真实 ``.sldlfp`` 焊件型材。"""
    target = Path(output_path).expanduser().resolve()
    if target.suffix.casefold() != ".sldlfp":
        raise ValueError("焊件型材输出必须使用 .sldlfp 扩展名")
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_sketch_selected(model, sketch_ref)
    configuration_name = _active_configuration_name(model)
    if properties:
        set_custom_properties(
            model,
            properties,
            configuration_name=configuration_name,
            save=False,
        )
        _ensure_sketch_selected(model, sketch_ref)
    if not save_document(model, str(target)):
        raise RuntimeError("自定义焊件型材保存失败")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("SolidWorks 返回成功，但未生成 .sldlfp 文件")
    return {
        "path": str(target),
        "configuration_name": configuration_name,
        "size_bytes": target.stat().st_size,
        "properties": dict(properties or {}),
    }


def create_structural_member(
    model,
    profile_path: str | Path,
    segment_groups: Iterable[Iterable[Any]],
    *,
    configuration_name: str = "",
    apply_corner_treatment: bool = True,
    corner_treatment_type: int = SW_END_CONDITION_MITER,
    connected_segments_option: int = SW_CONNECTED_SEGMENTS_SIMPLE_CUT,
    allow_protrusion: bool = False,
):
    """@brief 用 ``InsertStructuralWeldment5`` 创建一组原生结构构件。"""
    profile = Path(profile_path).expanduser().resolve()
    if not profile.is_file() or profile.suffix.casefold() != ".sldlfp":
        raise FileNotFoundError(f"焊件型材不存在或格式错误: {profile}")
    manager = get_com_member(model, "FeatureManager")
    existing_types = {
        str(get_com_member(feature, "GetTypeName2") or "")
        for feature in _iter_feature_chain(get_com_member(model, "FirstFeature"), "GetNextFeature")
    }
    if "WeldmentFeature" not in existing_types:
        model.ClearSelection2(True)
        weldment_feature = get_com_member(manager, "InsertWeldmentFeature")
        if weldment_feature is None:
            raise RuntimeError("InsertWeldmentFeature 创建失败")
    groups = []
    for index, raw_segments in enumerate(segment_groups, start=1):
        segments = tuple(item for item in raw_segments if item is not None)
        if not segments:
            raise ValueError(f"结构构件第 {index} 组没有路径段")
        group = get_com_member(manager, "CreateStructuralMemberGroup")
        if group is None:
            raise RuntimeError("CreateStructuralMemberGroup 未返回对象")
        group.Segments = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, segments)
        group.ApplyCornerTreatment = bool(apply_corner_treatment)
        if apply_corner_treatment:
            group.CornerTreatmentType = int(corner_treatment_type)
            # 保留每条路径段为独立切料实体，切割清单才能按长度正确分组。
            group.MiterMergeCondition = False
        groups.append(group)

    # pywin32 会把 Python 元组封送为 VARIANT SAFEARRAY；不传模糊的预选择集。
    feature = get_com_member(
        manager,
        "InsertStructuralWeldment5",
        str(profile),
        int(connected_segments_option),
        bool(allow_protrusion),
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, tuple(groups)),
        str(configuration_name),
    )
    if feature is None:
        raise RuntimeError("InsertStructuralWeldment5 创建失败")
    model.ClearSelection2(True)
    if not bool(get_com_member(model, "EditRebuild3")):
        raise RuntimeError("结构构件创建后的模型重建失败")
    return feature


def _body_length_key(body) -> int:
    """@brief 用实体包围盒最长边生成微米级分组键。"""
    box = tuple(float(item) for item in (get_com_member(body, "GetBodyBox") or ()))
    if len(box) != 6:
        raise RuntimeError("结构构件实体未返回 6 值包围盒")
    spans = (abs(box[3] - box[0]), abs(box[4] - box[1]), abs(box[5] - box[2]))
    return int(round(max(spans) * 1_000_000.0))


def _body_cut_list_key(body) -> tuple[int, int, int]:
    """@brief 生成旋转不变的三轴微米包围盒键，避免同长异型材误合并。"""
    box = tuple(float(item) for item in (get_com_member(body, "GetBodyBox") or ()))
    if len(box) != 6:
        raise RuntimeError("结构构件实体未返回 6 值包围盒")
    spans = sorted((abs(box[3] - box[0]), abs(box[4] - box[1]), abs(box[5] - box[2])))
    return tuple(int(round(item * 1_000_000.0)) for item in spans)


def ensure_cut_list(model) -> list[Any]:
    """@brief 为尚无清单的焊件按实体长度创建原生 CutListFolder。

    ``InsertWeldmentCutList2`` 的每次调用接收一组应属于同一切料项的实体。
    这里按包围盒最长边分组，使矩形框架的等长横梁/立柱分别形成数量为 2 的
    清单项；不把不同长度实体误合并为一项。
    """
    existing_by_name = {}
    for feature in iter_features_recursive(model):
        if str(get_com_member(feature, "GetTypeName2") or "") == "CutListFolder":
            existing_by_name.setdefault(str(get_com_member(feature, "Name") or ""), feature)
    existing = list(existing_by_name.values())
    if existing:
        return existing
    bodies = _as_tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False))
    if not bodies:
        raise RuntimeError("没有可写入切割清单的结构构件实体")
    grouped: dict[tuple[int, int, int], list[Any]] = {}
    for body in bodies:
        grouped.setdefault(_body_cut_list_key(body), []).append(body)
    manager = get_com_member(model, "FeatureManager")
    created = []
    for length_key in sorted(grouped):
        body_array = VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
            tuple(grouped[length_key]),
        )
        method = getattr(manager, "InsertWeldmentCutList2", None)
        if callable(method):
            feature = method(body_array)
        else:
            ole_object = getattr(manager, "_oleobj_", None)
            if ole_object is None:
                raise RuntimeError("FeatureManager 不支持 InsertWeldmentCutList2")
            # SW2026 IDispatch 将 DISPID 174 的方法同时暴露成值为 None 的伪属性，
            # 直接按官方类型库 DISPATCH_METHOD 语义调用，避免把 None 当函数。
            feature = ole_object.Invoke(
                174,
                0,
                pythoncom.DISPATCH_METHOD,
                True,
                body_array,
            )
        if feature is None:
            raise RuntimeError(f"InsertWeldmentCutList2 创建失败: length_key={length_key}")
        created.append(feature)
    if not bool(get_com_member(model, "EditRebuild3")):
        raise RuntimeError("切割清单创建后的模型重建失败")
    return created


def _iter_feature_chain(first_feature, next_member: str):
    """@brief 遍历顶层或同级子特征链。"""
    feature = first_feature
    count = 0
    while feature is not None and count < 4096:
        yield feature
        feature = get_com_member(feature, next_member)
        count += 1


def iter_features_recursive(model):
    """@brief 深度遍历焊件文件夹中的 CutListFolder 等子特征。"""
    def walk(feature):
        yield feature
        try:
            first_child = get_com_member(feature, "GetFirstSubFeature")
        except Exception:
            first_child = None
        for child in _iter_feature_chain(first_child, "GetNextSubFeature"):
            yield from walk(child)

    for root in _iter_feature_chain(get_com_member(model, "FirstFeature"), "GetNextFeature"):
        yield from walk(root)


def _read_property(manager, name: str) -> dict[str, Any]:
    """@brief 使用 Get6 读取切割清单属性并保留原始/解析值。"""
    raw = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    resolved = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    was_resolved = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    linked = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    status = int(manager.Get6(name, False, raw, resolved, was_resolved, linked))
    return {
        "name": str(name),
        "status": status,
        "raw": str(raw.value or ""),
        "resolved": str(resolved.value or ""),
        "was_resolved": bool(was_resolved.value),
        "linked": bool(linked.value),
    }


def read_property_manager(manager, *, core_only: bool = True) -> dict[str, dict[str, Any]]:
    """@brief 枚举属性管理器中的制造属性，默认排除模板标题栏噪声。"""
    names = _as_tuple(get_com_member(manager, "GetNames"))
    if core_only:
        names = tuple(
            name for name in names if str(name).strip().casefold() in CORE_CUT_LIST_PROPERTY_NAMES
        )
    return {str(name): _read_property(manager, str(name)) for name in names}


def set_cut_list_properties(model, properties: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 将型材来源和材料规格写入每个原生切割清单项并回读。"""
    if not properties:
        raise ValueError("切割清单属性不能为空")
    ensure_cut_list(model)
    results = []
    seen_names = set()
    for feature in iter_features_recursive(model):
        if str(get_com_member(feature, "GetTypeName2") or "") != "CutListFolder":
            continue
        feature_name = str(get_com_member(feature, "Name") or "")
        if feature_name in seen_names:
            continue
        seen_names.add(feature_name)
        manager = get_com_member(feature, "CustomPropertyManager")
        item = {"name": feature_name, "properties": {}}
        for raw_name, raw_value in properties.items():
            name = str(raw_name).strip()
            if not name:
                raise ValueError("切割清单属性名不能为空")
            value = str(raw_value)
            add_status = int(manager.Add3(name, 30, value, 2))
            readback = _read_property(manager, name)
            verified = readback["raw"] == value or readback["resolved"] == value
            if not verified:
                raise RuntimeError(f"切割清单属性回读失败: {item['name']} / {name}")
            item["properties"][name] = {"add_status": add_status, **readback}
        results.append(item)
    return results


def update_cut_list(model) -> list[dict[str, Any]]:
    """@brief 更新所有原生 CutListFolder 并返回文件夹级几何证据。"""
    folders = []
    seen_names = set()
    for feature in iter_features_recursive(model):
        type_name = str(get_com_member(feature, "GetTypeName2") or "")
        if type_name != "CutListFolder":
            continue
        feature_name = str(get_com_member(feature, "Name") or "")
        if feature_name in seen_names:
            continue
        seen_names.add(feature_name)
        body_folder = get_com_member(feature, "GetSpecificFeature2")
        update_ok = bool(get_com_member(body_folder, "UpdateCutList")) if body_folder else False
        manager = get_com_member(feature, "CustomPropertyManager")
        folders.append({
            "name": feature_name,
            "type": type_name,
            "body_count": int(get_com_member(body_folder, "GetBodyCount") or 0) if body_folder else 0,
            "update_ok": update_ok,
            "properties": read_property_manager(manager) if manager else {},
        })
    return folders


def weldment_evidence(model, *, create_missing_cut_list: bool = False) -> dict[str, Any]:
    """@brief 回读结构构件、实体数量和 SW2024+ 配置切割清单项目。"""
    if create_missing_cut_list:
        ensure_cut_list(model)
    folders = update_cut_list(model)
    features = []
    seen_features = set()
    for feature in iter_features_recursive(model):
        row = {
            "name": str(get_com_member(feature, "Name") or ""),
            "type": str(get_com_member(feature, "GetTypeName2") or ""),
        }
        key = (row["name"], row["type"])
        if key not in seen_features:
            seen_features.add(key)
            features.append(row)
    configuration = get_com_member(get_com_member(model, "ConfigurationManager"), "ActiveConfiguration")
    cut_list_items = []
    try:
        items = _as_tuple(get_com_member(configuration, "GetCutListItems"))
    except Exception:
        items = ()
    for index, item in enumerate(items, start=1):
        manager = get_com_member(item, "CustomPropertyManager")
        cut_list_items.append({
            "index": index,
            "properties": read_property_manager(manager) if manager else {},
        })

    bodies = _as_tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False))
    feature_types = [item["type"] for item in features]
    return {
        "configuration": str(get_com_member(configuration, "Name") or ""),
        "features": features,
        "feature_types": feature_types,
        "solid_body_count": len(bodies),
        "cut_list_folders": folders,
        "cut_list_items": cut_list_items,
        "has_weldment_feature": "WeldmentFeature" in feature_types,
        "has_structural_member": any(item in {"StructuralMember", "WeldMemberFeat"} for item in feature_types),
    }


def export_cut_list_csv(evidence: dict[str, Any], output_path: str | Path) -> Path:
    """@brief 将完整切割清单属性导出为 UTF-8-SIG CSV。"""
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = evidence.get("cut_list_folders") or evidence.get("cut_list_items") or []
    property_names = sorted({name for row in rows for name in row.get("properties", {})})
    columns = ["index", "name", "body_count", *property_names]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            values = {
                "index": row.get("index", index),
                "name": row.get("name", ""),
                "body_count": row.get("body_count", ""),
            }
            for name, payload in row.get("properties", {}).items():
                values[name] = payload.get("resolved") or payload.get("raw") or ""
            writer.writerow(values)
    return target
