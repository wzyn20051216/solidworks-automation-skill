"""
SolidWorks 装配体操作工具。

本模块优先封装装配体中最容易踩坑的 COM 流程：组件解析、装配体上下文实体映射、
真实 Mate 创建、运动型装配验证。SolidWorks API 使用米作为长度单位。
"""
import math
import os

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import open_document, safe_get_com_member
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import open_document, safe_get_com_member

pythoncom, _win32com, VARIANT = import_com_dependencies()


SW_MATE_COINCIDENT = 0
SW_MATE_CONCENTRIC = 1
SW_MATE_PARALLEL = 3
SW_MATE_DISTANCE = 5
SW_MATE_GEAR = 10
SW_ADD_MATE_ERROR_UNKNOWN = 0
SW_ADD_MATE_ERROR_NO_ERROR = 1
SW_COMPONENT_SUPPRESSED = 0
SW_COMPONENT_LIGHTWEIGHT = 1
SW_COMPONENT_FULLY_RESOLVED = 2
SW_COMPONENT_RESOLVED = 3
SW_SOLID_BODY = 0


def _empty_callout():
    """创建兼容 SelectByID2 的空 Callout 参数。"""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def _select_by_id(extension, entity_name, entity_type, append=False, mark=0):
    """
    统一封装 SelectByID2，避免 None 在部分 SolidWorks 版本中触发类型不匹配。

    参数:
        extension: ModelDocExtension 对象
        entity_name: 实体名称
        entity_type: 实体类型字符串
        append: 是否追加选择
        mark: 选择标记

    返回:
        bool
    """
    return extension.SelectByID2(
        entity_name, entity_type, 0, 0, 0, append, mark, _empty_callout(), 0
    )


def _as_alias_list(aliases):
    """将字符串或序列统一成非空名称列表。"""
    if isinstance(aliases, str):
        return [aliases]
    names = [str(item) for item in aliases if str(item)]
    if not names:
        raise ValueError("aliases 不能为空")
    return names


def _active_solidworks_app():
    """获取当前运行中的 SolidWorks 应用对象。"""
    try:
        return _win32com.GetActiveObject("SldWorks.Application")
    except Exception:
        return None


def _activate_model_document(sw, model):
    """激活给定文档，兼容 ActivateDoc3 的 by-ref error 参数。"""
    if sw is None or model is None:
        return False
    title = safe_get_com_member(model, "GetTitle")
    if not title:
        return False
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        return sw.ActivateDoc3(title, False, 0, errors) is not None
    except Exception:
        try:
            sw.ActivateDoc2(title, False, errors)
            return True
        except Exception:
            return False


def _add_component5(asm_model, component_path, config_name, x, y, z):
    """调用 AddComponent5 的 SW2024 兼容签名。"""
    add_component5 = getattr(asm_model, "AddComponent5", None)
    if not add_component5:
        return None
    return add_component5(
        component_path,
        0,              # swAddComponentConfigOptions_e: 使用指定/默认配置
        "",
        False,
        config_name or "",
        float(x),
        float(y),
        float(z),
    )


def _add_component4(asm_model, component_path, config_name, x, y, z):
    """调用 AddComponent4。"""
    return asm_model.AddComponent4(
        component_path,
        config_name or "",
        float(x),
        float(y),
        float(z),
    )


def add_component(asm_model, part_path, x=0, y=0, z=0, config_name="", sw=None):
    """
    向装配体添加零部件

    参数:
        asm_model: IAssemblyDoc (装配体文档)
        part_path: 零件/子装配体文件路径
        x, y, z: 放置位置（米）
        config_name: 配置名称，空字符串使用默认配置
        sw: 可选 SolidWorks 应用对象；用于 AddComponent 失败后自动打开零件并切回装配体。

    返回:
        IComponent2 对象
    """
    component_path = os.path.abspath(os.path.expandvars(os.path.expanduser(str(part_path))))
    if not os.path.exists(component_path):
        raise FileNotFoundError(f"组件文件不存在: {component_path}")

    component = None
    errors = []

    try:
        # SW2024 中文版 + pywin32 下 AddComponent4 可能返回 None；
        # AddComponent5 的 8 参数签名更稳定。
        component = _add_component5(asm_model, component_path, config_name, x, y, z)
    except Exception as exc:
        errors.append(f"AddComponent5: {exc}")

    if component is None:
        try:
            component = _add_component4(asm_model, component_path, config_name, x, y, z)
        except Exception as exc:
            errors.append(f"AddComponent4: {exc}")

    if component is None:
        sw = sw or _active_solidworks_app()
        if sw is not None:
            try:
                opened = open_document(sw, component_path, read_only=False, silent=True)
                if opened is None:
                    errors.append("OpenDoc6: 返回 None")
                elif _activate_model_document(sw, asm_model):
                    component = _add_component5(
                        asm_model,
                        component_path,
                        config_name,
                        x,
                        y,
                        z,
                    )
                    if component is None:
                        errors.append("open_then_AddComponent5: 返回 None")
                else:
                    errors.append("ActivateDoc: 无法重新激活装配体")
            except Exception as exc:
                errors.append(f"open_then_AddComponent5: {exc}")
        else:
            errors.append("GetActiveObject(SldWorks.Application): 返回 None")

    if component:
        print(f"已添加组件: {component_path}")
    else:
        detail = "；".join(errors) if errors else "AddComponent5/AddComponent4 均返回 None"
        print(f"添加组件失败: {component_path} ({detail})")
    return component


def resolve_component(component, state=SW_COMPONENT_FULLY_RESOLVED):
    """
    @brief 将组件解析为 Resolved/FullyResolved 状态。
    @param component IComponent2 对象。
    @param state swComponentSuppressionState_e，默认 2=swComponentFullyResolved。
    @return SetSuppression2 的返回值；若主状态失败会尝试 3=swComponentResolved。
    """
    if component is None:
        raise ValueError("component 不能为空")
    try:
        return component.SetSuppression2(state)
    except Exception:
        if state != SW_COMPONENT_RESOLVED:
            return component.SetSuppression2(SW_COMPONENT_RESOLVED)
        raise


def get_component_model(component, resolve=True, raise_on_error=True):
    """
    @brief 获取组件引用的零件/子装配文档。
    @param component IComponent2 对象。
    @param resolve 是否先解析组件；轻化或压缩组件常导致 GetModelDoc2 返回 None。
    @param raise_on_error 失败时是否抛异常。
    @return IModelDoc2；失败且 raise_on_error=False 时返回 None。
    """
    if component is None:
        if raise_on_error:
            raise ValueError("component 不能为空")
        return None
    if resolve:
        resolve_component(component)
    model = safe_get_com_member(component, "GetModelDoc2")
    if model is None and raise_on_error:
        name = safe_get_com_member(component, "Name2")
        raise RuntimeError(f"组件未解析或未加载，无法读取零件文档: {name}")
    return model


def get_component_feature(component, aliases, resolve=True):
    """
    @brief 按一组候选名称查找组件内部特征。
    @param component IComponent2 对象。
    @param aliases 特征候选名，例如 ["前视基准面", "Front Plane"]。
    @param resolve 是否先解析组件。
    @return IFeature 对象。
    """
    model = get_component_model(component, resolve=resolve)
    names = _as_alias_list(aliases)
    for name in names:
        feature = safe_get_com_member(model, "FeatureByName", name)
        if feature:
            return feature
    comp_name = safe_get_com_member(component, "Name2")
    raise RuntimeError(f"组件 {comp_name} 缺少特征: {names}")


def get_assembly_entity(component, feature_or_face):
    """
    @brief 将零件文档内对象映射到当前组件实例的装配体上下文。
    @param component IComponent2 对象。
    @param feature_or_face 零件内的 IFeature、IFace2、ISketchSegment 等对象。
    @return 装配体上下文对象，可用于 Select2 后创建 Mate。
    """
    entity = component.GetCorresponding(feature_or_face)
    if entity is None:
        comp_name = safe_get_com_member(component, "Name2")
        raise RuntimeError(f"无法映射装配体上下文实体: {comp_name}")
    return entity


def get_component_feature_entity(component, aliases, resolve=True):
    """
    @brief 查找组件内部特征并映射为装配体上下文实体。
    @param component IComponent2 对象。
    @param aliases 特征候选名。
    @param resolve 是否先解析组件。
    @return 装配体上下文实体。
    """
    feature = get_component_feature(component, aliases, resolve=resolve)
    return get_assembly_entity(component, feature)


def find_largest_cylinder_face(component, min_radius=0.0, max_radius=None, resolve=True):
    """
    @brief 查找组件中指定半径范围内面积最大的圆柱面。
    @param component IComponent2 对象。
    @param min_radius 最小半径，单位米。
    @param max_radius 最大半径，单位米；None 表示不限制。
    @param resolve 是否先解析组件。
    @return 装配体上下文中的 IFace2 圆柱面。
    """
    part = get_component_model(component, resolve=resolve)
    max_radius = float("inf") if max_radius is None else float(max_radius)
    best_face = None
    best_area = -1.0
    bodies = safe_get_com_member(part, "GetBodies2", SW_SOLID_BODY, False) or []
    for body in bodies:
        faces = safe_get_com_member(body, "GetFaces") or []
        for face in faces:
            surface = safe_get_com_member(face, "GetSurface")
            if not surface:
                continue
            try:
                if not safe_get_com_member(surface, "IsCylinder"):
                    continue
                params = safe_get_com_member(surface, "CylinderParams")
                radius = float(params[6])
                if radius < min_radius or radius > max_radius:
                    continue
                area = float(safe_get_com_member(face, "GetArea"))
                if area > best_area:
                    best_area = area
                    best_face = face
            except Exception:
                continue

    if best_face is None:
        comp_name = safe_get_com_member(component, "Name2")
        raise RuntimeError(
            f"未找到圆柱面: {comp_name}, radius=[{min_radius}, {max_radius}]"
        )
    return get_assembly_entity(component, best_face)


def select_entities_for_mate(model, entity1, entity2, mark=1):
    """
    @brief 选择两个装配体上下文实体并校验选择集数量。
    @param model IModelDoc2/IAssemblyDoc 对象。
    @param entity1 第一个 Mate 实体。
    @param entity2 第二个 Mate 实体。
    @param mark SolidWorks 选择标记，普通 Mate 通常为 1。
    @return True。
    """
    model.ClearSelection2(True)
    if not entity1.Select2(False, mark):
        raise RuntimeError("选择第一个 Mate 实体失败")
    if not entity2.Select2(True, mark):
        raise RuntimeError("选择第二个 Mate 实体失败")
    selected_count = model.SelectionManager.GetSelectedObjectCount2(-1)
    if selected_count != 2:
        model.ClearSelection2(True)
        raise RuntimeError(f"Mate 选择数量错误: selected={selected_count}, expected=2")
    return True


def add_mate5_checked(
    asm_model,
    mate_type,
    align=0,
    flip=False,
    distance=0.0,
    distance_upper=None,
    distance_lower=None,
    gear_num=0.0,
    gear_den=0.0,
    angle=0.0,
    angle_upper=None,
    angle_lower=None,
    for_positioning_only=False,
    lock_rotation=False,
    width_mate_option=0,
    name=None,
    clear_selection=True,
):
    """
    @brief 用 SolidWorks 2015+ 的 15 参数 AddMate5 创建 Mate，并检查错误码。
    @param asm_model IAssemblyDoc/IModelDoc2 装配体对象。
    @param mate_type swMateType_e 枚举值。
    @param gear_num 齿轮比分子，仅 Gear Mate 使用。
    @param gear_den 齿轮比分母，仅 Gear Mate 使用。
    @param lock_rotation 同心 Mate 是否锁定旋转；运动模型默认应为 False。
    @param name 可选 Mate 名称。
    @return Mate2 对象。
    """
    distance_upper = distance if distance_upper is None else distance_upper
    distance_lower = distance if distance_lower is None else distance_lower
    angle_upper = angle if angle_upper is None else angle_upper
    angle_lower = angle if angle_lower is None else angle_lower
    error_status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    mate = asm_model.AddMate5(
        int(mate_type),
        int(align),
        bool(flip),
        float(distance),
        float(distance_upper),
        float(distance_lower),
        float(gear_num),
        float(gear_den),
        float(angle),
        float(angle_upper),
        float(angle_lower),
        bool(for_positioning_only),
        bool(lock_rotation),
        int(width_mate_option),
        error_status,
    )
    # swAddMateError_e 中 1=swAddMateError_NoError；0=Unknown 在部分版本也会伴随非空 Mate。
    if mate is None or int(error_status.value) not in (
        SW_ADD_MATE_ERROR_UNKNOWN,
        SW_ADD_MATE_ERROR_NO_ERROR,
    ):
        raise RuntimeError(
            f"AddMate5 失败: type={mate_type}, error_status={error_status.value}"
        )
    if name:
        try:
            mate.Name = name
        except Exception:
            pass
    if clear_selection:
        asm_model.ClearSelection2(True)
    return mate


def add_concentric_mate_by_cylinders(
    asm_model,
    component_a,
    component_b,
    radius_a=None,
    radius_b=None,
    name=None,
    lock_rotation=False,
):
    """
    @brief 通过两个圆柱面创建同心 Mate，默认保留旋转自由度。
    @param asm_model IAssemblyDoc/IModelDoc2 装配体对象。
    @param component_a 第一个组件。
    @param component_b 第二个组件。
    @param radius_a 第一个组件圆柱半径范围 (min, max)，单位米；None 表示任意。
    @param radius_b 第二个组件圆柱半径范围 (min, max)，单位米；None 表示任意。
    @param name 可选 Mate 名称。
    @param lock_rotation 是否锁定同心旋转；运动装配应保持 False。
    @return Mate2 对象。
    """
    radius_a = radius_a or (0.0, None)
    radius_b = radius_b or (0.0, None)
    face_a = find_largest_cylinder_face(component_a, radius_a[0], radius_a[1])
    face_b = find_largest_cylinder_face(component_b, radius_b[0], radius_b[1])
    select_entities_for_mate(asm_model, face_a, face_b, mark=1)
    return add_mate5_checked(
        asm_model,
        SW_MATE_CONCENTRIC,
        lock_rotation=lock_rotation,
        name=name,
    )


def add_gear_mate_by_cylinders(
    asm_model,
    component_a,
    component_b,
    teeth_a,
    teeth_b,
    radius_a=None,
    radius_b=None,
    name=None,
):
    """
    @brief 通过两个齿轮轴/孔圆柱面创建真实 Gear Mate。
    @param asm_model IAssemblyDoc/IModelDoc2 装配体对象。
    @param component_a 第一个齿轮组件。
    @param component_b 第二个齿轮组件。
    @param teeth_a 第一个齿轮齿数或等效节圆比。
    @param teeth_b 第二个齿轮齿数或等效节圆比。
    @param radius_a 第一个齿轮轴/孔圆柱半径范围，单位米。
    @param radius_b 第二个齿轮轴/孔圆柱半径范围，单位米。
    @param name 可选 Mate 名称。
    @return Mate2 对象。
    """
    if float(teeth_a) == 0 or float(teeth_b) == 0:
        raise ValueError("Gear Mate 的齿数/传动比不能为 0")
    radius_a = radius_a or (0.0, None)
    radius_b = radius_b or (0.0, None)
    face_a = find_largest_cylinder_face(component_a, radius_a[0], radius_a[1])
    face_b = find_largest_cylinder_face(component_b, radius_b[0], radius_b[1])
    select_entities_for_mate(asm_model, face_a, face_b, mark=1)
    return add_mate5_checked(
        asm_model,
        SW_MATE_GEAR,
        gear_num=float(teeth_a),
        gear_den=float(teeth_b),
        name=name,
    )


def add_revolute_joint_by_cylinders(
    asm_model,
    component_a,
    component_b,
    radius_a=None,
    radius_b=None,
    name=None,
):
    """
    @brief 创建可转动铰接轴的核心同心 Mate。

    官方 Hinge Mate 等效于同心配合加轴向定位配合；自动化时先用本函数保留
    一条旋转自由度，再用平面重合/距离 Mate 约束轴向窜动。
    """
    return add_concentric_mate_by_cylinders(
        asm_model,
        component_a,
        component_b,
        radius_a=radius_a,
        radius_b=radius_b,
        name=name,
        lock_rotation=False,
    )


def build_transform_data_x(tx, ty, tz, angle_rad=0.0):
    """
    @brief 生成绕局部 X 轴旋转并平移的 SolidWorks MathTransform 数组。
    @param tx X 平移，单位米。
    @param ty Y 平移，单位米。
    @param tz Z 平移，单位米。
    @param angle_rad 绕 X 轴旋转角，单位弧度。
    @return 16 元组，可赋给 MathTransform.ArrayData。
    """
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return (
        1.0, 0.0, 0.0,
        0.0, c, -s,
        0.0, s, c,
        tx, ty, tz,
        1.0,
        0.0, 0.0, 0.0,
    )


def apply_component_transform_x(component, tx, ty, tz, angle_rad=0.0):
    """
    @brief 基于组件现有 Transform2 修改位姿并触发装配求解。
    @param component IComponent2 对象。
    @param tx X 平移，单位米。
    @param ty Y 平移，单位米。
    @param tz Z 平移，单位米。
    @param angle_rad 绕 X 轴旋转角，单位弧度。
    @return True 表示 SetTransformAndSolve2 或 Transform2 赋值成功。
    """
    transform = component.Transform2
    if transform is None:
        raise RuntimeError("组件没有可用 Transform2")
    transform.ArrayData = build_transform_data_x(tx, ty, tz, angle_rad)
    try:
        if component.SetTransformAndSolve2(transform):
            return True
    except Exception:
        pass
    try:
        component.Transform2 = transform
        return True
    except Exception:
        return False


def iter_feature_tree(model, include_subfeatures=True):
    """
    @brief 遍历模型特征树，兼容 FirstFeature/GetNextFeature 伪可调用属性。
    @param model IModelDoc2 对象。
    @param include_subfeatures 是否包含子特征。
    @return 生成器，产出 (feature, depth)。
    """
    def walk_subfeatures(parent, depth):
        sub = safe_get_com_member(parent, "GetFirstSubFeature")
        while sub:
            yield sub, depth
            if include_subfeatures:
                yield from walk_subfeatures(sub, depth + 1)
            sub = safe_get_com_member(sub, "GetNextSubFeature")

    feature = safe_get_com_member(model, "FirstFeature")
    while feature:
        yield feature, 0
        if include_subfeatures:
            yield from walk_subfeatures(feature, 1)
        feature = safe_get_com_member(feature, "GetNextFeature")


def collect_mate_feature_summary(model):
    """
    @brief 收集 MateGroup 及其子 Mate 特征摘要。
    @param model IModelDoc2 装配体对象。
    @return 包含 name、type、depth 的列表，用于验证真实机械配合是否写入特征树。
    """
    result = []
    for feature, depth in iter_feature_tree(model, include_subfeatures=True):
        name = safe_get_com_member(feature, "Name")
        type_name = safe_get_com_member(feature, "GetTypeName2")
        if (
            type_name == "MateGroup"
            or str(type_name).startswith("Mate")
            or "mate" in str(name).lower()
            or "配合" in str(name)
        ):
            result.append({
                "name": name,
                "type": type_name,
                "depth": depth,
            })
    return result


def add_mate_coincident(asm_model, entity1_name, entity1_type, entity2_name, entity2_type):
    """
    添加重合配合

    参数:
        entity1_name/entity2_name: 实体名称（面、边、点等）
        entity1_type/entity2_type: 实体类型字符串（"FACE", "PLANE", "EDGE", "VERTEX" 等）
    """
    asm_model.ClearSelection2(True)
    _select_by_id(asm_model.Extension, entity1_name, entity1_type, mark=1)
    _select_by_id(asm_model.Extension, entity2_name, entity2_type, append=True, mark=1)
    return add_mate5_checked(asm_model, SW_MATE_COINCIDENT)


def add_mate_concentric(asm_model, face1_name, face2_name):
    """添加同心配合"""
    asm_model.ClearSelection2(True)
    _select_by_id(asm_model.Extension, face1_name, "FACE", mark=1)
    _select_by_id(asm_model.Extension, face2_name, "FACE", append=True, mark=1)
    return add_mate5_checked(asm_model, SW_MATE_CONCENTRIC, lock_rotation=False)


def add_mate_distance(asm_model, entity1_name, entity1_type, entity2_name, entity2_type, distance):
    """
    添加距离配合

    参数:
        distance: 配合距离（米）
    """
    asm_model.ClearSelection2(True)
    _select_by_id(asm_model.Extension, entity1_name, entity1_type, mark=1)
    _select_by_id(asm_model.Extension, entity2_name, entity2_type, append=True, mark=1)
    return add_mate5_checked(asm_model, SW_MATE_DISTANCE, distance=distance)


def add_mate_parallel(asm_model, face1_name, face2_name):
    """添加平行配合"""
    asm_model.ClearSelection2(True)
    _select_by_id(asm_model.Extension, face1_name, "FACE", mark=1)
    _select_by_id(asm_model.Extension, face2_name, "FACE", append=True, mark=1)
    return add_mate5_checked(asm_model, SW_MATE_PARALLEL)


def get_components(asm_model, top_level_only=True):
    """
    获取装配体中的所有组件

    参数:
        top_level_only: True=仅顶层组件, False=包含子装配体中的组件

    返回:
        组件信息列表
    """
    components = safe_get_com_member(asm_model, "GetComponents", top_level_only)
    result = []
    if components:
        for comp in components:
            result.append({
                "name": safe_get_com_member(comp, "Name2"),
                "path": safe_get_com_member(comp, "GetPathName"),
                "suppressed": safe_get_com_member(comp, "IsSuppressed"),
                "visible": safe_get_com_member(comp, "Visible"),
            })
    return result


def find_component_by_name(asm_model, keyword, top_level_only=True, case_sensitive=False):
    """
    @brief 按组件名关键字查找 IComponent2 对象。
    @param asm_model 装配体 IModelDoc2/IAssemblyDoc。
    @param keyword 组件名关键字，例如 "impeller" 或 "叶轮"。
    @param top_level_only True=仅顶层组件。
    @param case_sensitive 是否区分大小写。
    @return 第一个匹配的 IComponent2 对象。
    """
    if not keyword:
        raise ValueError("keyword 不能为空")
    components = safe_get_com_member(asm_model, "GetComponents", top_level_only) or []
    needle = str(keyword) if case_sensitive else str(keyword).lower()
    for component in components:
        name = str(safe_get_com_member(component, "Name2"))
        haystack = name if case_sensitive else name.lower()
        if needle in haystack:
            return component
    raise RuntimeError(f"未找到组件: {keyword}")


def suppress_component(asm_model, component_name):
    """压缩（隐藏）组件"""
    _select_by_id(asm_model.Extension, component_name, "COMPONENT")
    asm_model.EditSuppress()


def unsuppress_component(asm_model, component_name):
    """解压缩（显示）组件"""
    _select_by_id(asm_model.Extension, component_name, "COMPONENT")
    asm_model.EditUnsuppress()


def replace_component(asm_model, old_component_name, new_part_path):
    """
    替换装配体中的组件

    参数:
        old_component_name: 旧组件名称
        new_part_path: 新零件文件路径
    """
    _select_by_id(asm_model.Extension, old_component_name, "COMPONENT")
    return asm_model.ReplaceComponents2(new_part_path, "", False, 0, True)


def get_interference_detection(asm_model):
    """运行干涉检查"""
    interference = asm_model.InterferenceDetection
    interference.TreatSubAssembliesAsComponents = False
    interference.TreatCoincidenceAsInterference = False
    interference.Done()

    count = interference.GetInterferenceCount()
    print(f"检测到 {count} 处干涉")
    return count
