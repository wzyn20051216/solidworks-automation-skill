"""SolidWorks 2026 高级圆角能力探测与真机回归。

@brief 验证多控制点可变半径、保持线、曲率连续曲面组合、全圆角、setback 和宽度-宽度倒角。
@details 每种能力使用独立零件，保存、STEP 导出、重开和预览均成功才记为 verified。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advanced_fillet_strategy import (  # noqa: E402
    ADVANCED_KINDS,
    FaceFilletSpec,
    FullRoundFilletSpec,
    HoldLineFilletSpec,
    SetbackFilletSpec,
    SurfaceCombinationSpec,
    VariableFilletSpec,
    WidthWidthChamferSpec,
    build_capability_report,
    inspect_typelib_members,
    validate_face_spec,
    validate_full_round_spec,
    validate_hold_line_spec,
    validate_setback_spec,
    validate_surface_combination_spec,
    validate_variable_spec,
    validate_width_width_chamfer_spec,
)
from hold_line_bridge import (  # noqa: E402
    HoldLineBridgeError,
    create_hold_line_via_csharp,
    create_hold_line_via_native_addin,
    unsafe_hold_line_probe_enabled,
)
from sw_appearance import set_document_appearance  # noqa: E402
from sw_connect import create_empty_dispatch_variant, get_com_member, mm  # noqa: E402
from sw_export import export_to_step  # noqa: E402
from sw_review import run_review  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402
from sw_preflight import import_com_dependencies  # noqa: E402


pythoncom, _win32com_client, VARIANT = import_com_dependencies()


SW_SOLID_BODY = 0
SW_FM_FILLET = 1
SW_SIMPLE_FACE = 2
SW_SIMPLE_FULL_ROUND = 3
SW_FACE_SET_1 = 1
SW_FACE_SET_2 = 2
SW_FULL_SET_1 = 3
SW_FULL_CENTER_SET = 4
SW_FULL_SET_2 = 5
SW_PROFILE_CIRCULAR = 0
SW_OVERFLOW_DEFAULT = 0
SW_FEATURE_VARIABLE = 1
SW_FILLET_PROPAGATE = 1
SW_FILLET_UNIFORM_RADIUS = 2
SW_FILLET_VARIABLE_TYPE = 4
SW_FILLET_CORNER_TYPE = 32
SW_FILLET_USE_TANGENT_HOLD_LINE = 16
SW_CHAMFER_DISTANCE_DISTANCE = 2
SW_CHAMFER_TANGENT_PROPAGATION = 4
GEOMETRY_TOLERANCE_M = 1e-5
SW_DISPLAY_ORIGINS = 6
SW_DISPLAY_REFERENCE_TRIAD = 205


class HoldLineInteropBlockedError(RuntimeError):
    """@brief 表示保持线几何已准备，但跨语言后端未形成可读回特征。"""

    def __init__(self, attempts: list[dict[str, Any]]):
        super().__init__(
            "SW2026 SP1.1 保持线调用未通过：Python、C#、SWBasic 与进程内 C++ 均在 "
            "HoldLines/ISetHoldLines 边界失败；"
            f"已记录 {len(attempts)} 次受控尝试"
        )
        self.attempts = attempts


def _dispatch_array(items: tuple[Any, ...]):
    """@brief 构造需要由 COM 明确识别为 IDispatch 数组的参数。"""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(items))


def _double_array(values: tuple[float, ...] | list[float]):
    """@brief 构造 SolidWorks setback 等接口要求的 SAFEARRAY<double>。"""
    return VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [float(value) for value in values],
    )


def _variant_array(items: tuple[Any, ...]):
    """@brief 构造属性 setter 常用的 SAFEARRAY<VARIANT>。"""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, list(items))


def _typed_feature_data(data, interface_name: str):
    """@brief 通过已生成的 SW2026 makepy 接口包装无类型 FeatureData。"""
    module = _win32com_client.gencache.EnsureModule(
        "{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0, 34, 0
    )
    interface = getattr(module, interface_name)
    return interface(data._oleobj_)


def _find_typelib(explicit: Path | None) -> Path:
    """@brief 定位本机 SolidWorks 主类型库。"""
    if explicit:
        return explicit.resolve()
    candidates = [
        Path(r"E:\SolidWroks2026\SOLIDWORKS\sldworks.tlb"),
        Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 sldworks.tlb，请使用 --typelib 显式指定")


def _select_plane(model) -> None:
    """@brief 兼容中英文名称选择前视基准面。"""
    model.ClearSelection2(True)
    for name in ("Front Plane", "前视基准面"):
        if model.Extension.SelectByID2(
            name, "PLANE", 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0
        ):
            return
    raise RuntimeError("无法选择前视基准面")


def _hide_review_helpers(model) -> None:
    """@brief 隐藏原点和参考三轴，避免蓝色构造符号污染审查图。"""
    for preference in (SW_DISPLAY_ORIGINS, SW_DISPLAY_REFERENCE_TRIAD):
        try:
            model.SetUserPreferenceToggle(preference, False)
        except Exception:
            continue
    model.ClearSelection2(True)


def _create_box(model, length_mm: float, width_mm: float, height_mm: float, name: str):
    """@brief 创建供高级圆角验证使用的矩形棱柱。"""
    _select_plane(model)
    model.SketchManager.InsertSketch(True)
    active = model.SketchManager.ActiveSketch
    sketch_name = active.Name if active else "Sketch1"
    model.SketchManager.CreateCenterRectangle(
        0, 0, 0, mm(length_mm / 2.0), mm(width_mm / 2.0), 0
    )
    model.SketchManager.InsertSketch(True)
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(
        sketch_name, "SKETCH", 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0
    ):
        raise RuntimeError(f"无法选择基础草图: {sketch_name}")
    feature = model.FeatureManager.FeatureExtrusion3(
        True, False, False, 0, 0, mm(height_mm), 0,
        False, False, False, False, 0, 0,
        False, False, False, False,
        True, False, True, 0, 0, False,
    )
    if feature is None:
        raise RuntimeError("验证棱柱创建失败")
    feature.Name = name
    model.ForceRebuild3(False)
    return feature


def _create_cylinder(model, radius_mm: float, height_mm: float, name: str):
    """@brief 创建平面与圆柱面组合的曲率连续回归基体。"""
    _select_plane(model)
    model.SketchManager.InsertSketch(True)
    active = model.SketchManager.ActiveSketch
    sketch_name = active.Name if active else "Sketch1"
    model.SketchManager.CreateCircleByRadius(0, 0, 0, mm(radius_mm))
    model.SketchManager.InsertSketch(True)
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(
        sketch_name, "SKETCH", 0, 0, 0, False, 0, create_empty_dispatch_variant(), 0
    ):
        raise RuntimeError(f"无法选择圆柱草图: {sketch_name}")
    feature = model.FeatureManager.FeatureExtrusion3(
        True, False, False, 0, 0, mm(height_mm), 0,
        False, False, False, False, 0, 0,
        False, False, False, False,
        True, False, True, 0, 0, False,
    )
    if feature is None:
        raise RuntimeError("曲面组合验证圆柱创建失败")
    feature.Name = name
    model.ForceRebuild3(False)
    return feature


def _add_projected_hold_line(model):
    """@brief 在顶面投影距外边 4 mm 的分割线，形成真实保持线。"""
    _select_plane(model)
    model.SketchManager.InsertSketch(True)
    active = model.SketchManager.ActiveSketch
    sketch_name = active.Name if active else "Sketch1"
    model.SketchManager.CreateLine(mm(-30.0), mm(21.0), 0, mm(30.0), mm(21.0), 0)
    model.SketchManager.InsertSketch(True)
    top = _find_face(model, lambda box: _near(box[2], mm(16.0)) and _near(box[5], mm(16.0)))
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(
        sketch_name, "SKETCH", 0, 0, 0, False, 4, create_empty_dispatch_variant(), 0
    ):
        raise RuntimeError(f"无法选择保持线投影草图: {sketch_name}")
    if not top.Select2(True, 1):
        raise RuntimeError("无法选择保持线分割目标面")
    model.InsertSplitLineProject(True, True)
    if not model.ForceRebuild3(False):
        raise RuntimeError("投影保持线重建失败")
    if model.FeatureByName("Split Line1") is None and model.FeatureByName("分割线1") is None:
        raise RuntimeError("投影保持线未在特征树中持久化")


def _body(model):
    """@brief 返回唯一实体，拒绝多实体歧义。"""
    bodies = tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False) or ())
    if len(bodies) != 1:
        raise RuntimeError(f"验证零件应仅有一个实体，实际 {len(bodies)}")
    return bodies[0]


def _point(vertex) -> tuple[float, float, float]:
    """@brief 返回顶点坐标。"""
    return tuple(float(value) for value in get_com_member(vertex, "GetPoint"))


def _edge_points(edge) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """@brief 返回直边端点，闭合边返回 None。"""
    start = get_com_member(edge, "GetStartVertex")
    end = get_com_member(edge, "GetEndVertex")
    if not start or not end:
        return None
    return _point(start), _point(end)


def _edge_length_mm(edge) -> float:
    """@brief 计算验证直边长度。"""
    points = _edge_points(edge)
    if not points:
        raise RuntimeError("目标边没有可读端点")
    start, end = points
    return sum((end[index] - start[index]) ** 2 for index in range(3)) ** 0.5 * 1000.0


def _near(left: float, right: float) -> bool:
    """@brief 判断两个米制几何坐标是否相等。"""
    return abs(left - right) <= GEOMETRY_TOLERANCE_M


def _find_edge(model, predicate: Callable[[tuple[float, ...], tuple[float, ...]], bool]):
    """@brief 按端点几何语义查找唯一边。"""
    matches = []
    for edge in tuple(get_com_member(_body(model), "GetEdges") or ()):
        points = _edge_points(edge)
        if points and predicate(points[0], points[1]):
            matches.append(edge)
    if len(matches) != 1:
        raise RuntimeError(f"目标边匹配不唯一: {len(matches)}")
    return matches[0]


def _face_box(face) -> tuple[float, ...]:
    """@brief 返回面的轴对齐包围盒。"""
    return tuple(float(value) for value in get_com_member(face, "GetBox"))


def _find_face(model, predicate: Callable[[tuple[float, ...]], bool]):
    """@brief 按包围盒几何语义查找唯一面。"""
    matches = [
        face
        for face in tuple(get_com_member(_body(model), "GetFaces") or ())
        if predicate(_face_box(face))
    ]
    if len(matches) != 1:
        raise RuntimeError(f"目标面匹配不唯一: {len(matches)}")
    return matches[0]


def _surface_type(face) -> str:
    """@brief 回读面的解析曲面类型，拒绝仅凭包围盒猜测。"""
    surface = get_com_member(face, "GetSurface")
    if surface is None:
        return "unknown"
    for member, label in (
        ("IsPlane", "plane"),
        ("IsCylinder", "cylinder"),
        ("IsCone", "cone"),
        ("IsSphere", "sphere"),
        ("IsTorus", "torus"),
    ):
        try:
            if bool(get_com_member(surface, member)):
                return label
        except Exception:
            continue
    return "freeform"


def _find_vertex(model, target: tuple[float, float, float]):
    """@brief 按精确角点坐标查找唯一顶点。"""
    vertices = []
    seen = set()
    for edge in tuple(get_com_member(_body(model), "GetEdges") or ()):
        for name in ("GetStartVertex", "GetEndVertex"):
            vertex = get_com_member(edge, name)
            if not vertex:
                continue
            point = _point(vertex)
            key = tuple(round(value, 9) for value in point)
            if key not in seen and all(_near(point[index], target[index]) for index in range(3)):
                seen.add(key)
                vertices.append(vertex)
    if len(vertices) != 1:
        raise RuntimeError(f"目标顶点匹配不唯一: {len(vertices)}")
    return vertices[0]


def _incident_edges(model, vertex) -> tuple[Any, ...]:
    """@brief 返回与目标顶点相接的全部边。"""
    target = _point(vertex)
    result = []
    for edge in tuple(get_com_member(_body(model), "GetEdges") or ()):
        points = _edge_points(edge)
        if points and any(
            all(_near(point[index], target[index]) for index in range(3)) for point in points
        ):
            result.append(edge)
    return tuple(result)


def _assert_feature(model, feature, name: str):
    """@brief 命名、重建并确认高级圆角持久化。"""
    if feature is None:
        raise RuntimeError(f"{name} 创建失败，API 返回 None")
    feature.Name = name
    if not model.ForceRebuild3(False):
        raise RuntimeError(f"{name} 重建失败")
    persisted = model.FeatureByName(name)
    if persisted is None:
        raise RuntimeError(f"{name} 重建后未在特征树中持久化")
    return persisted


def _create_variable(model):
    """@brief 创建带三个中间控制点的真实可变半径圆角。"""
    spec = VariableFilletSpec(
        start_radius=2.0,
        end_radius=5.0,
        control_points=((0.25, 3.0), (0.50, 6.0), (0.75, 4.0)),
    )
    edge = _find_edge(
        model,
        lambda a, b: _near(abs(a[0] - b[0]), mm(60.0))
        and _near(a[1], mm(15.0)) and _near(b[1], mm(15.0))
        and _near(a[2], mm(16.0)) and _near(b[2], mm(16.0)),
    )
    validation = validate_variable_spec(spec, edge_length_mm=_edge_length_mm(edge))
    model.ClearSelection2(True)
    if not edge.Select2(False, 1):
        raise RuntimeError("可变半径目标边选择失败")
    points = _edge_points(edge)
    if points is None:
        raise RuntimeError("可变半径目标边端点不可读")
    start, end = points
    for location, _radius in spec.control_points:
        xyz = tuple(start[index] + location * (end[index] - start[index]) for index in range(3))
        if not model.Extension.SelectByID2(
            "", "POINTREF", *xyz, True, 256, create_empty_dispatch_variant(), 0
        ):
            raise RuntimeError(f"可变半径控制点选择失败: location={location}")
    options = SW_FILLET_PROPAGATE + SW_FILLET_UNIFORM_RADIUS + SW_FILLET_VARIABLE_TYPE
    feature = model.FeatureManager.FeatureFillet3(
        options, 0.0, 0.0, 0.0, SW_FEATURE_VARIABLE,
        SW_OVERFLOW_DEFAULT, SW_PROFILE_CIRCULAR,
        _double_array((mm(spec.start_radius), mm(spec.end_radius))),
        0, 0, 0,
        _double_array([mm(radius) for _location, radius in spec.control_points]),
        0, 0,
    )
    return _assert_feature(model, feature, "Advanced_Variable_MultiPoint"), validation


def _create_face(model):
    """@brief 用现代 FeatureData API 创建相邻两面的面圆角。"""
    spec = FaceFilletSpec(radius=4.0)
    validation = validate_face_spec(spec, clearance_mm=16.0)
    top = _find_face(model, lambda box: _near(box[2], mm(16.0)) and _near(box[5], mm(16.0)))
    side = _find_face(model, lambda box: _near(box[1], mm(15.0)) and _near(box[4], mm(15.0)))
    model.ClearSelection2(True)
    if not top.Select2(False, 2) or not side.Select2(True, 4):
        raise RuntimeError("面圆角的面组选择失败")
    data = model.FeatureManager.CreateDefinition(SW_FM_FILLET)
    if data is None or not data.Initialize(SW_SIMPLE_FACE):
        raise RuntimeError("面圆角 FeatureData 初始化失败")
    data.ConicTypeForCrossSectionProfile = SW_PROFILE_CIRCULAR
    data.DefaultRadius = mm(spec.radius)
    data.PropagateToTangentFaces = spec.propagate_tangent
    data.SetFaces(SW_FACE_SET_1, _dispatch_array((top,)))
    data.SetFaces(SW_FACE_SET_2, _dispatch_array((side,)))
    if int(data.GetFaceCount(SW_FACE_SET_1)) != 1:
        raise RuntimeError("面圆角 Face Set 1 回读数量异常")
    if int(data.GetFaceCount(SW_FACE_SET_2)) != 1:
        raise RuntimeError("面圆角 Face Set 2 回读数量异常")
    feature = model.FeatureManager.CreateFeature(data)
    return _assert_feature(model, feature, "Advanced_Face_Fillet_R4"), validation


def _create_hold_line(model, sw=None):
    """@brief 优先用原生 C++ 创建保持线圆角，并保留跨语言负向证据。"""
    spec = HoldLineFilletSpec(radius=4.0, hold_line_count=1)
    _add_projected_hold_line(model)
    inner_top = _find_face(
        model,
        lambda box: _near(box[1], mm(-25.0)) and _near(box[4], mm(21.0))
        and _near(box[2], mm(16.0)) and _near(box[5], mm(16.0)),
    )
    outer_top = _find_face(
        model,
        lambda box: _near(box[1], mm(21.0)) and _near(box[4], mm(25.0))
        and _near(box[2], mm(16.0)) and _near(box[5], mm(16.0)),
    )
    side = _find_face(model, lambda box: _near(box[1], mm(25.0)) and _near(box[4], mm(25.0)))
    hold_line = _find_edge(
        model,
        lambda a, b: _near(abs(a[0] - b[0]), mm(60.0))
        and _near(a[1], mm(21.0)) and _near(b[1], mm(21.0))
        and _near(a[2], mm(16.0)) and _near(b[2], mm(16.0)),
    )
    validation = validate_hold_line_spec(
        spec,
        clearance_mm=16.0,
        available_hold_lines=1,
    )
    attempts = []
    try:
        model.ClearSelection2(True)
        if (
            not outer_top.Select2(False, 2)
            or not side.Select2(True, 4)
            or not hold_line.Select2(True, 8)
        ):
            raise HoldLineBridgeError("SWBasic 桥接所需的面组或保持线选择失败")
        native = create_hold_line_via_native_addin(
            sw,
            str(get_com_member(model, "GetTitle")),
        )
        feature_name = str(native.get("featureName") or "Advanced_Hold_Line_Fillet")
        feature = model.FeatureByName(feature_name)
        if feature is None:
            raise HoldLineBridgeError(
                "原生 Add-in 报告成功，但 Python 会话未找到保持线特征",
                native,
            )
        validation["backend"] = "native-cpp-swb"
        validation["native_bridge"] = native
        return _assert_feature(model, feature, feature_name), validation
    except HoldLineBridgeError as exc:
        attempts.append({
            "api": "C++ ISimpleFilletFeatureData2.ISetHoldLines",
            "backend": "native-cpp-swb",
            "error": str(exc),
            "evidence": exc.evidence,
            "created": False,
        })
    try:
        bridge = create_hold_line_via_csharp(
            str(get_com_member(model, "GetTitle")),
            solidworks_revision=str(get_com_member(sw, "RevisionNumber")),
        )
        feature_name = str(bridge.get("featureName") or "Advanced_Hold_Line_Fillet")
        feature = model.FeatureByName(feature_name)
        if feature is None:
            raise HoldLineBridgeError(
                "C# 桥接器报告成功，但 Python 会话未找到保持线特征",
                bridge,
            )
        validation["backend"] = "csharp-pia"
        validation["bridge"] = bridge
        return _assert_feature(model, feature, feature_name), validation
    except HoldLineBridgeError as exc:
        attempts.append({
            "api": "C# ISimpleFilletFeatureData2.HoldLines",
            "backend": "csharp-pia",
            "error": str(exc),
            "evidence": exc.evidence,
            "created": False,
        })
    if not unsafe_hold_line_probe_enabled():
        validation["attempts"] = attempts
        raise HoldLineInteropBlockedError(attempts)
    feature = None
    hold_line_values = (
        ("tuple", (hold_line,)),
        ("list", [hold_line]),
        ("dispatch_safearray", _dispatch_array((hold_line,))),
        ("variant_safearray", _variant_array((hold_line,))),
    )
    for top_label, top in (("inner", inner_top), ("outer", outer_top)):
        for value_label, hold_line_value in hold_line_values:
            try:
                model.ClearSelection2(True)
                if (
                    not top.Select2(False, 2)
                    or not side.Select2(True, 4)
                    or not hold_line.Select2(True, 8)
                ):
                    raise RuntimeError("保持线圆角的面组或保持线选择失败")
                data = model.FeatureManager.CreateDefinition(SW_FM_FILLET)
                if data is None:
                    raise RuntimeError("保持线圆角 CreateDefinition 返回 None")
                data = _typed_feature_data(data, "ISimpleFilletFeatureData2")
                if not data.Initialize(SW_SIMPLE_FACE):
                    raise RuntimeError("保持线圆角 FeatureData 初始化失败")
                data.ConicTypeForCrossSectionProfile = SW_PROFILE_CIRCULAR
                data.SetFaces(SW_FACE_SET_1, _dispatch_array((top,)))
                data.SetFaces(SW_FACE_SET_2, _dispatch_array((side,)))
                data.HoldLines = hold_line_value
                hold_line_count = int(data.GetHoldLineCount())
                if hold_line_count == 1:
                    feature = model.FeatureManager.CreateFeature(data)
                attempts.append({
                    "api": "ISimpleFilletFeatureData2.HoldLines",
                    "top_face": top_label,
                    "encoding": value_label,
                    "hold_line_count": hold_line_count,
                    "created": feature is not None,
                })
            except Exception as exc:
                attempts.append({
                    "api": "ISimpleFilletFeatureData2.HoldLines",
                    "top_face": top_label,
                    "encoding": value_label,
                    "error": f"{type(exc).__name__}: {exc}",
                    "created": False,
                })
            if feature is not None:
                break
        if feature is not None:
            break
    for top_label, top in (() if feature is not None else (("inner", inner_top), ("outer", outer_top))):
        for face_order, faces in (("top-side", (top, side)), ("side-top", (side, top))):
            for tangent_hold_line in (False, True):
                for direction in (0, 2048, 4096, 2048 + 4096):
                    model.ClearSelection2(True)
                    if (
                        not faces[0].Select2(False, 2)
                        or not faces[1].Select2(True, 4)
                        or not hold_line.Select2(True, 8)
                    ):
                        raise RuntimeError("保持线圆角的面组或保持线选择失败")
                    options = direction
                    if tangent_hold_line:
                        options += SW_FILLET_USE_TANGENT_HOLD_LINE
                    if spec.propagate_tangent:
                        options += SW_FILLET_PROPAGATE
                    feature = model.FeatureManager.FeatureFillet3(
                        options,
                        0.0,
                        0.0,
                        0.0,
                        SW_SIMPLE_FACE,
                        SW_OVERFLOW_DEFAULT,
                        SW_PROFILE_CIRCULAR,
                        None, None, None, None, None, None, None,
                    )
                    attempts.append({
                        "api": "IFeatureManager.FeatureFillet3",
                        "top_face": top_label,
                        "face_order": face_order,
                        "tangent_hold_line": tangent_hold_line,
                        "options": options,
                        "created": feature is not None,
                    })
                    if feature is not None:
                        break
                if feature is not None:
                    break
            if feature is not None:
                break
        if feature is not None:
            break
    if feature is not None:
        validation["selected_attempt"] = attempts[-1]
    validation["attempts"] = attempts
    if feature is None:
        raise HoldLineInteropBlockedError(attempts)
    return _assert_feature(model, feature, "Advanced_Hold_Line_Fillet"), validation


def _create_surface_combo(model):
    """@brief 创建平面到圆柱面的 G2 曲率连续面圆角。"""
    spec = SurfaceCombinationSpec(radius=3.0, curvature_continuous=True)
    top = _find_face(model, lambda box: _near(box[2], mm(20.0)) and _near(box[5], mm(20.0)))
    cylinder = _find_face(
        model,
        lambda box: _near(box[0], mm(-15.0)) and _near(box[3], mm(15.0))
        and _near(box[1], mm(-15.0)) and _near(box[4], mm(15.0))
        and _near(box[2], 0.0) and _near(box[5], mm(20.0)),
    )
    surface_types = (_surface_type(top), _surface_type(cylinder))
    validation = validate_surface_combination_spec(
        spec,
        clearance_mm=15.0,
        surface_types=surface_types,
    )
    model.ClearSelection2(True)
    if not top.Select2(False, 2) or not cylinder.Select2(True, 4):
        raise RuntimeError("复杂曲面组合的平面/圆柱面选择失败")
    data = model.FeatureManager.CreateDefinition(SW_FM_FILLET)
    if data is None or not data.Initialize(SW_SIMPLE_FACE):
        raise RuntimeError("复杂曲面组合 FeatureData 初始化失败")
    data.DefaultRadius = mm(spec.radius)
    data.CurvatureContinuous = spec.curvature_continuous
    data.PropagateToTangentFaces = spec.propagate_tangent
    data.SetFaces(SW_FACE_SET_1, _dispatch_array((top,)))
    data.SetFaces(SW_FACE_SET_2, _dispatch_array((cylinder,)))
    feature = model.FeatureManager.CreateFeature(data)
    return _assert_feature(model, feature, "Advanced_G2_Plane_Cylinder"), validation


def _create_full_round(model):
    """@brief 将窄棱柱的两侧面和顶面转换为全圆角。"""
    spec = FullRoundFilletSpec()
    validation = validate_full_round_spec(spec, face_set_counts=(1, 1, 1))
    side1 = _find_face(model, lambda box: _near(box[1], mm(-6.0)) and _near(box[4], mm(-6.0)))
    center = _find_face(model, lambda box: _near(box[2], mm(12.0)) and _near(box[5], mm(12.0)))
    side2 = _find_face(model, lambda box: _near(box[1], mm(6.0)) and _near(box[4], mm(6.0)))
    model.ClearSelection2(True)
    if not side1.Select2(False, 2) or not center.Select2(True, 512) or not side2.Select2(True, 4):
        raise RuntimeError("全圆角三组面选择失败")
    data = model.FeatureManager.CreateDefinition(SW_FM_FILLET)
    if data is None or not data.Initialize(SW_SIMPLE_FULL_ROUND):
        raise RuntimeError("全圆角 FeatureData 初始化失败")
    data.PropagateToTangentFaces = spec.propagate_tangent
    for which, faces, label in (
        (SW_FULL_SET_1, (side1,), "Side Set 1"),
        (SW_FULL_CENTER_SET, (center,), "Center Set"),
        (SW_FULL_SET_2, (side2,), "Side Set 2"),
    ):
        data.SetFaces(which, _dispatch_array(faces))
        if int(data.GetFaceCount(which)) != len(faces):
            raise RuntimeError(f"全圆角 {label} 回读数量异常")
    feature = model.FeatureManager.CreateFeature(data)
    return _assert_feature(model, feature, "Advanced_Full_Round"), validation


def _create_setback(model):
    """@brief 用 FeatureFillet3 创建三边角可变圆角及逐边 setback。"""
    spec = SetbackFilletSpec(radius=3.0, distances=(1.0, 1.0, 1.0))
    vertex = _find_vertex(model, (mm(30.0), mm(20.0), mm(18.0)))
    edges = _incident_edges(model, vertex)
    lengths = tuple(_edge_length_mm(edge) for edge in edges)
    validation = validate_setback_spec(spec, incident_edge_lengths_mm=lengths)
    if len(edges) != 3:
        raise RuntimeError(f"setback 角点应有三条边，实际 {len(edges)}")
    model.ClearSelection2(True)
    for index, edge in enumerate(edges):
        if not edge.Select2(index > 0, 1):
            raise RuntimeError(f"setback 第 {index + 1} 条边选择失败")
    if not vertex.Select2(True, 0):
        raise RuntimeError("setback 顶点选择失败")
    options = SW_FILLET_PROPAGATE + SW_FILLET_UNIFORM_RADIUS + SW_FILLET_CORNER_TYPE
    feature = model.FeatureManager.FeatureFillet3(
        options,
        mm(spec.radius),
        0.0,
        0.0,
        0,
        SW_OVERFLOW_DEFAULT,
        SW_PROFILE_CIRCULAR,
        0,
        0,
        0,
        _double_array([mm(value) for value in spec.distances]),
        0,
        0,
        0,
    )
    return _assert_feature(model, feature, "Advanced_Setback_R3"), validation


def _create_width_width_chamfer(model):
    """@brief 创建两侧距离不同的真实距离-距离倒角。"""
    spec = WidthWidthChamferSpec(width1=2.0, width2=4.0)
    edge = _find_edge(
        model,
        lambda a, b: _near(abs(a[0] - b[0]), mm(60.0))
        and _near(a[1], mm(15.0)) and _near(b[1], mm(15.0))
        and _near(a[2], mm(16.0)) and _near(b[2], mm(16.0)),
    )
    validation = validate_width_width_chamfer_spec(
        spec,
        adjacent_clearances_mm=(15.0, 16.0),
    )
    model.ClearSelection2(True)
    if not edge.Select2(False, 0):
        raise RuntimeError("宽度-宽度倒角目标边选择失败")
    options = SW_CHAMFER_TANGENT_PROPAGATION if spec.propagate_tangent else 0
    feature = model.FeatureManager.InsertFeatureChamfer(
        options,
        SW_CHAMFER_DISTANCE_DISTANCE,
        mm(spec.width1),
        0.0,
        mm(spec.width2),
        0.0,
        0.0,
        0.0,
    )
    return _assert_feature(model, feature, "Advanced_Width_Width_C2_C4"), validation


BUILDERS: Mapping[str, tuple[tuple[float, float, float], Callable[[Any], tuple[Any, dict[str, Any]]]]] = {
    "variable": ((60.0, 30.0, 16.0), _create_variable),
    "face": ((60.0, 30.0, 16.0), _create_face),
    "hold_line": ((60.0, 50.0, 16.0), _create_hold_line),
    "surface_combo": ((30.0, 30.0, 20.0), _create_surface_combo),
    "full_round": ((60.0, 12.0, 12.0), _create_full_round),
    "setback": ((60.0, 40.0, 18.0), _create_setback),
    "width_width_chamfer": ((60.0, 30.0, 16.0), _create_width_width_chamfer),
}


def _feature_data_evidence(feature, kind: str, model=None) -> dict[str, Any]:
    """@brief 回读高级圆角 FeatureData 的关键事实。"""
    data = get_com_member(feature, "GetDefinition")
    evidence: dict[str, Any] = {
        "name": feature.Name,
        "type_name": str(get_com_member(feature, "GetTypeName2")),
        "definition_available": data is not None,
    }
    if data is None:
        return evidence
    try:
        evidence["selection_access"] = bool(data.AccessSelections(model, None)) if model is not None else False
    except Exception:
        evidence["selection_access"] = False
    for name in (
        "Type", "DefaultRadius", "FilletEdgeCount", "GetControlPointsCount",
        "GetSetbackVerticesCount", "GetHoldLineCount", "CurvatureContinuous",
    ):
        try:
            value = get_com_member(data, name)
            if isinstance(value, float):
                value = round(value * 1000.0, 6) if "Radius" in name else value
            evidence[name] = value
        except Exception:
            continue
    if kind == "variable" and int(evidence.get("GetControlPointsCount") or 0) > 0:
        controls = []
        for index in range(int(evidence["GetControlPointsCount"])):
            location = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, 0.0)
            edge = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)
            try:
                radius = data.GetControlPointRadiusAtIndex(index, location, edge)
                controls.append({
                    "index": index,
                    "location_percent": round(float(location.value), 6),
                    "radius_mm": round(float(radius) * 1000.0, 6),
                    "edge_available": edge.value is not None,
                })
            except Exception as exc:
                controls.append({"index": index, "error": str(exc)})
        evidence["control_points"] = controls
    if kind == "width_width_chamfer":
        try:
            evidence["edge_distances_mm"] = [
                round(float(data.GetEdgeChamferDistance(side)) * 1000.0, 6)
                for side in (0, 1)
            ]
        except Exception as exc:
            evidence["edge_distances_error"] = str(exc)
    try:
        data.ReleaseSelectionAccess()
    except Exception:
        pass
    evidence["kind"] = kind
    return evidence


def _evidence_passes(kind: str, evidence: Mapping[str, Any]) -> bool:
    """@brief 以 FeatureData 回读值判定高级特征是否真的按请求创建。"""
    if not evidence.get("definition_available"):
        return False
    if kind == "variable":
        controls = evidence.get("control_points") or []
        return (
            str(evidence.get("type_name")) == "VarFillet"
            and int(evidence.get("GetControlPointsCount") or 0) == 3
            and len(controls) == 3
            and all("error" not in item for item in controls)
            and [item["location_percent"] for item in controls] == [25.0, 50.0, 75.0]
            and [item["radius_mm"] for item in controls] == [3.0, 6.0, 4.0]
        )
    if kind == "face":
        return int(evidence.get("Type") or -1) == SW_SIMPLE_FACE
    if kind == "hold_line":
        return (
            int(evidence.get("Type") or -1) == SW_SIMPLE_FACE
            and int(evidence.get("GetHoldLineCount") or 0) == 1
        )
    if kind == "surface_combo":
        return (
            int(evidence.get("Type") or -1) == SW_SIMPLE_FACE
            and evidence.get("CurvatureContinuous") is True
        )
    if kind == "full_round":
        return int(evidence.get("Type") or -1) == SW_SIMPLE_FULL_ROUND
    if kind == "setback":
        return int(evidence.get("GetSetbackVerticesCount") or 0) == 1
    if kind == "width_width_chamfer":
        distances = sorted(float(value) for value in evidence.get("edge_distances_mm") or [])
        return int(evidence.get("Type") or -1) == SW_CHAMFER_DISTANCE_DISTANCE and distances == [2.0, 4.0]
    return False


def _verify_one(session: SolidWorksSession, kind: str, output_dir: Path) -> dict[str, Any]:
    """@brief 构建并完成一种高级圆角的交付闭环。"""
    size, builder = BUILDERS[kind]
    basename = f"Advanced_Fillet_{kind}"
    part_path = output_dir / f"{basename}.SLDPRT"
    step_path = output_dir / f"{basename}.step"
    model = None
    reopened = None
    try:
        model = session.new_part()
        if kind == "surface_combo":
            _create_cylinder(model, radius_mm=size[0] / 2.0, height_mm=size[2], name=f"Base_{kind}")
        else:
            _create_box(model, *size, name=f"Base_{kind}")
        feature, validation = builder(model, session.sw) if kind == "hold_line" else builder(model)
        set_document_appearance(model, "silver")
        _hide_review_helpers(model)
        model.ViewZoomtofit2()
        if not session.save(model, str(part_path)):
            raise RuntimeError(f"保存失败: {part_path}")
        if not export_to_step(model, str(step_path)):
            raise RuntimeError(f"STEP 导出失败: {step_path}")
        review, review_path = run_review(
            model,
            output_dir,
            basename=basename,
            expected_outputs=[str(part_path), str(step_path)],
        )
        before_close = _feature_data_evidence(feature, kind, model)
        feature_name = str(feature.Name)
        session.close(title=get_com_member(model, "GetTitle"))
        model = None
        reopened = session.open(str(part_path), read_only=True, silent=True)
        reopened_feature = reopened.FeatureByName(feature_name)
        reopen_ok = reopened_feature is not None and bool(reopened.ForceRebuild3(False))
        reopened_type = (
            str(get_com_member(reopened_feature, "GetTypeName2"))
            if reopened_feature
            else None
        )
        reopened_evidence = (
            _feature_data_evidence(reopened_feature, kind, reopened)
            if reopened_feature is not None
            else {"definition_available": False, "kind": kind}
        )
        session.close(model=reopened)
        reopened = None
        status = (
            "verified"
            if reopen_ok
            and _evidence_passes(kind, before_close)
            and _evidence_passes(kind, reopened_evidence)
            and part_path.is_file()
            and step_path.is_file()
            and review["evaluation"]["status"] in {"pass", "warn"}
            else "failed"
        )
        return {
            "status": status,
            "kind": kind,
            "validation": validation,
            "feature": before_close,
            "reopen": {
                "success": reopen_ok,
                "type_name": reopened_type,
                "feature": reopened_evidence,
            },
            "review": review["evaluation"],
            "review_path": str(review_path),
            "outputs": {
                "part": str(part_path),
                "step": str(step_path),
            },
        }
    finally:
        for document in (reopened, model):
            if document is None:
                continue
            try:
                session.close(title=get_com_member(document, "GetTitle"))
            except Exception:
                continue


def parse_args() -> argparse.Namespace:
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="探测并真机验证 SolidWorks 高级圆角能力。")
    parser.add_argument("--typelib", type=Path, help="sldworks.tlb 路径。")
    parser.add_argument(
        "--version", type=int,
        help="可选 SolidWorks 年份，例如 2026；省略时自动连接默认版本。",
    )
    parser.add_argument(
        "--modes", nargs="+", choices=ADVANCED_KINDS, default=list(ADVANCED_KINDS),
        help="需要验证的高级圆角类型。",
    )
    parser.add_argument("--verify-solidworks", action="store_true", help="执行真实 SolidWorks 建模回归。")
    parser.add_argument(
        "--unsafe-native-hold-line",
        action="store_true",
        help="仅在隔离实例中复测已知可能导致 SolidWorks 服务器故障的保持线后端。",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path.cwd() / "solidworks_advanced_fillet_output",
        help="报告和真机产物目录。",
    )
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    args = parse_args()
    if args.unsafe_native_hold_line:
        os.environ["CAD_STUDIO_UNSAFE_NATIVE_HOLD_LINE"] = "1"
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    typelib = _find_typelib(args.typelib)
    interfaces = inspect_typelib_members(typelib)
    report = build_capability_report(interfaces, source=str(typelib))
    selected = set(args.modes)
    report["capabilities"] = {
        kind: value for kind, value in report["capabilities"].items() if kind in selected
    }
    if args.verify_solidworks:
        session = SolidWorksSession(version=args.version, visible=True)
        report["runtime_environment"] = {
            "requested_version": args.version,
            "solidworks_revision": str(get_com_member(session.sw, "RevisionNumber")),
        }
        try:
            for kind in args.modes:
                capability = report["capabilities"][kind]
                if capability["status"] != "interface_ready":
                    capability["runtime"] = {
                        "status": "blocked",
                        "reason": "类型库缺少必需接口",
                    }
                    continue
                try:
                    capability["runtime"] = _verify_one(session, kind, args.output_dir)
                    capability["status"] = capability["runtime"]["status"]
                except Exception as exc:
                    status = "blocked" if isinstance(exc, HoldLineInteropBlockedError) else "failed"
                    capability["status"] = status
                    capability["runtime"] = {
                        "status": status,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    if isinstance(exc, HoldLineInteropBlockedError):
                        capability["runtime"]["attempts"] = exc.attempts
        finally:
            session.quit_owned_instance()
    report_path = args.output_dir / "advanced_fillet_capabilities.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    statuses = [item["status"] for item in report["capabilities"].values()]
    if args.verify_solidworks:
        return 0 if statuses and all(status == "verified" for status in statuses) else 2
    return 0 if statuses and all(status == "interface_ready" for status in statuses) else 2


if __name__ == "__main__":
    raise SystemExit(main())
