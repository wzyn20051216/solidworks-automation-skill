"""SolidWorks 2026 高级圆角能力探测与真机回归。

@brief 验证可变半径、面圆角、全圆角和三边角 setback。
@details 每种能力使用独立零件，保存、STEP 导出、重开和预览均成功才记为 verified。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advanced_fillet_strategy import (  # noqa: E402
    ADVANCED_KINDS,
    FaceFilletSpec,
    FullRoundFilletSpec,
    SetbackFilletSpec,
    VariableFilletSpec,
    build_capability_report,
    inspect_typelib_members,
    validate_face_spec,
    validate_full_round_spec,
    validate_setback_spec,
    validate_variable_spec,
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
GEOMETRY_TOLERANCE_M = 1e-5
SW_DISPLAY_ORIGINS = 6
SW_DISPLAY_REFERENCE_TRIAD = 205


def _dispatch_array(items: tuple[Any, ...]):
    """@brief 构造需要由 COM 明确识别为 IDispatch 数组的参数。"""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(items))


def _double_array(values: tuple[float, ...] | list[float]):
    """@brief 构造 SolidWorks setback 等接口要求的 SAFEARRAY<double>。"""
    return VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [float(value) for value in values],
    )


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
    """@brief 创建单边端点 R2→R5 的真实可变半径圆角。"""
    spec = VariableFilletSpec(start_radius=2.0, end_radius=5.0)
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
    options = SW_FILLET_PROPAGATE + SW_FILLET_UNIFORM_RADIUS + SW_FILLET_VARIABLE_TYPE
    feature = model.FeatureManager.FeatureFillet3(
        options, 0.0, 0.0, 0.0, SW_FEATURE_VARIABLE,
        SW_OVERFLOW_DEFAULT, SW_PROFILE_CIRCULAR,
        (mm(spec.start_radius), mm(spec.end_radius)),
        0, 0, 0, 0, 0, 0,
    )
    return _assert_feature(model, feature, "Advanced_Variable_R2_R5"), validation


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


BUILDERS: Mapping[str, tuple[tuple[float, float, float], Callable[[Any], tuple[Any, dict[str, Any]]]]] = {
    "variable": ((60.0, 30.0, 16.0), _create_variable),
    "face": ((60.0, 30.0, 16.0), _create_face),
    "full_round": ((60.0, 12.0, 12.0), _create_full_round),
    "setback": ((60.0, 40.0, 18.0), _create_setback),
}


def _feature_data_evidence(feature, kind: str) -> dict[str, Any]:
    """@brief 回读高级圆角 FeatureData 的关键事实。"""
    data = get_com_member(feature, "GetDefinition")
    evidence: dict[str, Any] = {
        "name": feature.Name,
        "type_name": str(get_com_member(feature, "GetTypeName2")),
        "definition_available": data is not None,
    }
    if data is None:
        return evidence
    for name in (
        "Type", "DefaultRadius", "FilletEdgeCount", "GetControlPointsCount",
        "GetSetbackVerticesCount",
    ):
        try:
            value = get_com_member(data, name)
            if isinstance(value, float):
                value = round(value * 1000.0, 6) if "Radius" in name else value
            evidence[name] = value
        except Exception:
            continue
    evidence["kind"] = kind
    return evidence


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
        _create_box(model, *size, name=f"Base_{kind}")
        feature, validation = builder(model)
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
        before_close = _feature_data_evidence(feature, kind)
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
        session.close(model=reopened)
        reopened = None
        status = (
            "verified"
            if reopen_ok
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
            "reopen": {"success": reopen_ok, "type_name": reopened_type},
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
        "--output-dir", type=Path,
        default=Path.cwd() / "solidworks_advanced_fillet_output",
        help="报告和真机产物目录。",
    )
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    args = parse_args()
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
                    capability["status"] = "failed"
                    capability["runtime"] = {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
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
