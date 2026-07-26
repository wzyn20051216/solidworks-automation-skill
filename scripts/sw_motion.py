"""
SolidWorks Motion Study 自动化工具。

本模块封装 Motion Study 中最容易踩坑的流程：加载专用类型库、创建运动算例、
创建匀速旋转马达并触发计算。SolidWorks API 使用米作为长度单位；转速参数使用 RPM。
"""
import glob
import os

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import safe_get_com_member
    from .sw_assembly import find_largest_cylinder_face
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import safe_get_com_member
    from sw_assembly import find_largest_cylinder_face

pythoncom, win32com_client, VARIANT = import_com_dependencies()


SW_FM_AEM_ROTATIONAL_MOTOR = 78
SW_MOTION_STUDY_BASIC_MOTION = 1


def _motion_typelib_candidates():
    """枚举常见 SolidWorks Motion Study 类型库路径。"""
    patterns = [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\swmotionstudy.tlb",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\swmotionstudy.tlb",
        r"C:\Program Files\Dassault Systemes\SOLIDWORKS*\swmotionstudy.tlb",
        r"E:\Solidworks\SOLIDWORKS\swmotionstudy.tlb",
    ]
    seen = set()
    for pattern in patterns:
        for path in glob.glob(os.path.expandvars(pattern)):
            norm = os.path.normcase(os.path.abspath(path))
            if norm in seen:
                continue
            seen.add(norm)
            yield path


def ensure_motion_type_library(raise_on_error=False):
    """
    @brief 生成 SolidWorks Motion Study 类型库的 pywin32 包装。
    @param raise_on_error 找不到或加载失败时是否抛异常。
    @return 成功加载的类型库路径；失败且 raise_on_error=False 时返回 None。

    Motion Study 的 `IMotionStudyManager` 位于 `swmotionstudy.tlb`，不在主
    `sldworks` 类型库里。未加载该类型库时，pywin32 动态对象常出现
    `CreateMotionStudy`、`GetMotionStudyCount` 等成员像属性不像方法的情况。
    """
    errors = []
    for path in _motion_typelib_candidates():
        try:
            tlb = pythoncom.LoadTypeLib(path)
            guid, lcid, _syskind, major, minor, _flags = tlb.GetLibAttr()
            win32com_client.gencache.EnsureModule(guid, lcid, major, minor)
            return path
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if raise_on_error:
        detail = "\n".join(errors) if errors else "未找到 swmotionstudy.tlb"
        raise RuntimeError("无法加载 SolidWorks Motion Study 类型库:\n" + detail)
    return None


def motion_member(obj, attr_name, *args):
    """
    @brief 兼容 Motion Study COM 成员“属性/方法”双态。
    @param obj COM 对象。
    @param attr_name 成员名。
    @param args 当成员可调用时传入的参数。
    @return 成员值或方法返回值。

    实测 SolidWorks 2024 + pywin32 下，`CreateMotionStudy`、`Activate`、
    `Calculate`、`Play` 可能表现为属性，`SetDuration`、`CreateDefinition`、
    `CreateFeature` 通常表现为方法。本函数统一隐藏差异。
    """
    member = getattr(obj, attr_name)
    if args:
        if callable(member):
            return member(*args)
        if len(args) == 0:
            return member
        raise TypeError(f"Motion Study 成员不可调用: {attr_name}")
    try:
        return member() if callable(member) else member
    except Exception as exc:
        message = str(exc)
        if "-2147352573" in message or "找不到成员" in message or "Member not found" in message:
            return member
        raise


def get_motion_study_manager(asm_model, load_type_library=True):
    """
    @brief 获取装配体的 MotionStudyManager。
    @param asm_model 装配体 IModelDoc2/IAssemblyDoc。
    @param load_type_library 是否先加载 `swmotionstudy.tlb`。
    @return MotionStudyManager COM 对象。
    """
    if load_type_library:
        ensure_motion_type_library(raise_on_error=False)
    manager = safe_get_com_member(asm_model.Extension, "GetMotionStudyManager")
    if manager is None:
        raise RuntimeError("无法获取 MotionStudyManager，请确认当前文档是装配体且 SolidWorks Motion 可用")
    return manager


def create_motion_study(asm_model, name=None, duration=4.0, study_type=None):
    """
    @brief 创建并激活一个 Motion Study。
    @param asm_model 装配体 IModelDoc2/IAssemblyDoc。
    @param name 可选算例名称。
    @param duration 动画时长，单位秒。
    @param study_type 可选 Motion Study 类型；None 时保持 SolidWorks 默认。
    @return Motion Study COM 对象。
    """
    manager = get_motion_study_manager(asm_model)
    study = motion_member(manager, "CreateMotionStudy")
    if study is None:
        raise RuntimeError("新建 Motion Study 失败")
    if name:
        try:
            study.Name = name
        except Exception:
            pass
    if study_type is not None:
        try:
            study.StudyType = int(study_type)
        except Exception:
            pass
    if not bool(motion_member(study, "Activate")):
        raise RuntimeError("激活 Motion Study 失败")
    if duration is not None:
        try:
            motion_member(study, "SetDuration", float(duration))
        except Exception:
            pass
    return study


def _set_first_supported(obj, names, value):
    """按候选属性名设置第一个可用属性。"""
    last_error = None
    for name in names:
        try:
            setattr(obj, name, value)
            return name
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("候选属性名不能为空")


def _set_load_references(motor_data, references):
    """
    @brief 为马达设置载荷引用，兼容 tuple/list/VARIANT 多种 COM 接收方式。
    @param motor_data ISimulationMotorFeatureData。
    @param references 装配体上下文实体列表。
    @return True 表示设置成功。
    """
    variants = [
        tuple(references),
        list(references),
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, list(references)),
        VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(references)),
    ]
    for refs in variants:
        try:
            motor_data.LoadReferences = refs
            return True
        except Exception:
            continue
    return False


def add_constant_speed_rotary_motor(
    motion_study,
    direction_reference,
    load_reference,
    rpm=60.0,
    relative_component=None,
    name=None,
    reverse=False,
):
    """
    @brief 给 Motion Study 添加匀速旋转马达。
    @param motion_study Motion Study COM 对象。
    @param direction_reference 旋转方向引用，通常为装配体上下文中的轴或圆柱面。
    @param load_reference 被驱动组件引用，通常为叶轮/转子圆柱面。
    @param rpm 转速，单位 RPM。
    @param relative_component 可选相对静止组件。
    @param name 可选马达特征名。
    @param reverse 是否反向旋转。
    @return 创建出的马达 Feature。
    """
    motor_data = motion_member(motion_study, "CreateDefinition", SW_FM_AEM_ROTATIONAL_MOTOR)
    if motor_data is None:
        raise RuntimeError("创建旋转马达 FeatureData 失败")

    motor_data.DirectionReference = direction_reference
    motion_member(motor_data, "ConstantSpeedMotor", float(rpm))
    motor_data.ReverseDirection = bool(reverse)
    if relative_component is not None:
        motor_data.RelativeComponent = relative_component

    try:
        motor_data.Location = load_reference
    except Exception:
        pass

    if not _set_load_references(motor_data, [load_reference]):
        raise RuntimeError("设置旋转马达 LoadReferences 失败")
    motor_feature = motion_member(motion_study, "CreateFeature", motor_data)
    if motor_feature is None:
        raise RuntimeError("创建旋转马达特征失败")
    if name:
        try:
            motor_feature.Name = name
        except Exception:
            pass
    return motor_feature


def add_constant_speed_rotary_motor_by_cylinders(
    motion_study,
    shaft_component,
    rotor_component,
    shaft_radius=None,
    rotor_radius=None,
    rpm=60.0,
    name=None,
    reverse=False,
):
    """
    @brief 通过两个圆柱面查找旋转轴和被驱动转子，并添加匀速旋转马达。
    @param motion_study Motion Study COM 对象。
    @param shaft_component 静止轴/支架组件。
    @param rotor_component 被驱动旋转组件。
    @param shaft_radius 轴圆柱半径范围 `(min, max)`，单位米；None 表示不限。
    @param rotor_radius 转子圆柱半径范围 `(min, max)`，单位米；None 表示不限。
    @param rpm 转速，单位 RPM。
    @param name 可选马达特征名。
    @param reverse 是否反向旋转。
    @return 创建出的马达 Feature。
    """
    shaft_radius = shaft_radius or (0.0, None)
    rotor_radius = rotor_radius or (0.0, None)
    direction_reference = find_largest_cylinder_face(
        shaft_component,
        min_radius=shaft_radius[0],
        max_radius=shaft_radius[1],
    )
    load_reference = find_largest_cylinder_face(
        rotor_component,
        min_radius=rotor_radius[0],
        max_radius=rotor_radius[1],
    )
    return add_constant_speed_rotary_motor(
        motion_study,
        direction_reference,
        load_reference,
        rpm=rpm,
        relative_component=shaft_component,
        name=name,
        reverse=reverse,
    )


def calculate_and_play(motion_study, play=True):
    """
    @brief 计算 Motion Study，并可选播放动画。
    @param motion_study Motion Study COM 对象。
    @param play True 时计算成功后调用 Play。
    @return Calculate 的布尔结果。
    """
    calculated = bool(motion_member(motion_study, "Calculate"))
    if play and calculated:
        try:
            motion_member(motion_study, "Play")
        except Exception:
            pass
    return calculated


def _collect_motion_features(motion_study):
    """@brief 读取 Motion 特征名称和类型，用于识别旋转马达等真实特征。"""
    try:
        raw_features = motion_member(motion_study, "GetMotionFeatures") or []
    except Exception:
        raw_features = []
    if not isinstance(raw_features, (list, tuple)):
        raw_features = [raw_features]
    features = []
    for feature in raw_features:
        try:
            type_name = None
            for member_name in ("GetTypeName2", "GetTypeName"):
                try:
                    type_name = motion_member(feature, member_name)
                    if type_name:
                        break
                except Exception:
                    continue
            features.append({
                "name": str(motion_member(feature, "Name") or ""),
                "type_id": int(motion_member(feature, "GetType") or 0),
                "type_name": str(type_name or ""),
            })
        except Exception as exc:
            features.append({"name": "", "type_id": 0, "type_name": "", "error": str(exc)})
    return features


def collect_motion_study_summary(asm_model):
    """
    @brief 收集装配体全部 Motion Study 的机器可读摘要。
    @param asm_model 装配体 IModelDoc2/IAssemblyDoc。
    @return 包含算例名称、类型、时长、马达/外力数量和结果状态的字典。

    本函数只读取官方类型库已公开的成员，不修改算例，也不把“存在算例”误报成
    “运动结果正确”。`results_out_of_date` 为 True 时必须重新 Calculate。
    """
    manager = get_motion_study_manager(asm_model)
    count = int(motion_member(manager, "GetMotionStudyCount") or 0)
    names = motion_member(manager, "GetMotionStudyNames") or []
    if isinstance(names, str):
        names = [names]
    names = [str(name) for name in list(names)[:count]]
    studies = []
    for name in names:
        study = motion_member(manager, "GetMotionStudy", name)
        if study is None:
            studies.append({"name": name, "available": False})
            continue
        study_type = int(motion_member(study, "StudyType") or 0)
        results = None
        results_error = None
        try:
            results = motion_member(study, "GetResults", study_type)
        except Exception as exc:
            results_error = str(exc)
        motion_features = _collect_motion_features(study)
        reported_motor_count = int(motion_member(study, "GetNumOfExternalMotors") or 0)
        motor_feature_count = sum("motor" in item.get("type_name", "").lower() for item in motion_features)
        item = {
            "name": str(motion_member(study, "Name") or name),
            "available": True,
            "study_type": study_type,
            "duration_seconds": float(motion_member(study, "GetDuration") or 0.0),
            "motor_count": max(reported_motor_count, motor_feature_count),
            "reported_motor_count": reported_motor_count,
            "motor_feature_count": motor_feature_count,
            "external_force_count": int(motion_member(study, "GetNumOfExternalForces") or 0),
            "feature_count": int(motion_member(study, "GetMotionFeaturesCount") or 0),
            "active": bool(motion_member(study, "IsActive")),
            "playing": bool(motion_member(study, "IsPlaying")),
            "results_available": results is not None,
            "motion_features": motion_features,
        }
        if results is not None:
            item["results_out_of_date"] = bool(motion_member(results, "IsOutOfDate"))
        if results_error:
            item["results_error"] = results_error
        studies.append(item)
    return {
        "motion_type_library": ensure_motion_type_library(raise_on_error=False),
        "study_count": count,
        "studies": studies,
    }


def validate_motion_study_summary(
    summary,
    study_name=None,
    expected_study_type=None,
    minimum_duration_seconds=0.001,
    minimum_motor_count=1,
    require_results=True,
):
    """
    @brief 验证 Motion Study 是否具备可交付的机器证据。
    @param summary collect_motion_study_summary() 的结果。
    @param study_name 可选目标算例名；None 时验证全部可用算例。
    @param expected_study_type 可选期望 StudyType 枚举值。
    @param minimum_duration_seconds 最小时长。
    @param minimum_motor_count 最少马达数量。
    @param require_results 是否强制要求已计算且结果不过期。
    @return 包含 status、checks、issues 和 matched_studies 的字典。
    """
    checks = []
    issues = []

    def check(check_id, passed, failure_message, study=None, success_message=None):
        """@brief 追加单条验收检查。"""
        message = success_message if passed and success_message else failure_message
        item = {"id": check_id, "passed": bool(passed), "message": message}
        if study:
            item["study"] = study
        checks.append(item)
        if not passed:
            issues.append(failure_message)

    studies = [item for item in summary.get("studies", []) if item.get("available")]
    if study_name is not None:
        studies = [item for item in studies if item.get("name") == study_name]
    check(
        "study-present",
        bool(studies),
        f"未找到可用 Motion Study: {study_name or '任意算例'}",
        success_message=f"已找到 Motion Study: {study_name or '任意算例'}",
    )
    check(
        "type-library",
        bool(summary.get("motion_type_library")),
        "未确认 swmotionstudy.tlb，Motion 结果读取可能不完整",
        success_message="已确认 swmotionstudy.tlb",
    )

    for study in studies:
        name = str(study.get("name") or "未命名算例")
        duration = float(study.get("duration_seconds") or 0.0)
        motor_count = int(study.get("motor_count") or 0)
        check(
            "duration",
            duration >= float(minimum_duration_seconds),
            f"{name} 时长 {duration:g}s 小于要求 {minimum_duration_seconds:g}s",
            name,
            f"{name} 时长 {duration:g}s 满足要求",
        )
        check(
            "motor-count",
            motor_count >= int(minimum_motor_count),
            f"{name} 马达数量 {motor_count} 小于要求 {minimum_motor_count}",
            name,
            f"{name} 检测到 {motor_count} 个马达特征",
        )
        if expected_study_type is not None:
            actual_type = int(study.get("study_type") or 0)
            check(
                "study-type",
                actual_type == int(expected_study_type),
                f"{name} StudyType={actual_type}，期望 {expected_study_type}",
                name,
                f"{name} StudyType={actual_type} 符合要求",
            )
        if require_results:
            available = bool(study.get("results_available"))
            check("results-present", available, f"{name} 没有可读取的计算结果", name, f"{name} 计算结果可读取")
            check(
                "results-fresh",
                available and study.get("results_out_of_date") is False,
                f"{name} 结果不存在或已经过期，必须重新 Calculate",
                name,
                f"{name} 结果存在且未过期",
            )
        if study.get("results_error"):
            check("results-readable", False, f"{name} 结果读取失败: {study['results_error']}", name)

    return {
        "status": "pass" if checks and all(item["passed"] for item in checks) else "fail",
        "checks": checks,
        "issues": issues,
        "matched_studies": [item.get("name") for item in studies],
        "requirements": {
            "study_name": study_name,
            "expected_study_type": expected_study_type,
            "minimum_duration_seconds": float(minimum_duration_seconds),
            "minimum_motor_count": int(minimum_motor_count),
            "require_results": bool(require_results),
        },
    }


def validate_motion_studies(asm_model, **requirements):
    """@brief 读取装配体 Motion 摘要并执行交付门禁。"""
    summary = collect_motion_study_summary(asm_model)
    validation = validate_motion_study_summary(summary, **requirements)
    return {"summary": summary, "validation": validation}
