"""@brief 受限 OCP 平滑 Loft、Sweep、Knit、Thicken 与连续性证据后端。

所有操作只接受结构化白名单输入。输入 B-Rep 必须绑定本轮产物标记与 SHA-256，
输出必须版本化并在 STEP/BREP 重开后再次验证；G1/G2 结论来自共享边采样，不能
用“B-Rep 有效”代替连续性证明。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .advanced_geometry_ocp import (
        _make_wire,
        _reopen_shape,
        _sha256,
        _shape_evidence,
        _verify_reopened_evidence,
        _verify_section_envelope,
        _versioned_stem,
        _write_shape,
        validate_ocp_loft_request,
    )
except ImportError:
    from advanced_geometry_ocp import (
        _make_wire,
        _reopen_shape,
        _sha256,
        _shape_evidence,
        _verify_reopened_evidence,
        _verify_section_envelope,
        _versioned_stem,
        _write_shape,
        validate_ocp_loft_request,
    )


_COMMON_FIELDS = {"schemaVersion", "modelId", "units", "operation", "toleranceMm", "outputs"}
_OUTPUTS = {"step", "brep", "stl"}


def _now_iso() -> str:
    """@brief 返回 UTC 秒级时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 读取不超过 4 MiB 的 JSON object。"""
    if isinstance(value, dict):
        return dict(value)
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError("高级曲面请求必须是存在的 JSON 文件。")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("高级曲面请求超过 4 MiB 安全上限。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("高级曲面请求必须是 JSON object。")
    return payload


def _finite(value: Any, field: str, *, positive: bool = False, maximum: float | None = None) -> float:
    """@brief 校验有限数值及可选范围。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是有限数值。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限数值。") from exc
    if not math.isfinite(number) or (positive and number <= 0) or (maximum is not None and number > maximum):
        raise ValueError(f"{field} 超出允许范围。")
    return number


def _point3(value: Any, field: str) -> list[float]:
    """@brief 校验三维点。"""
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} 必须是三个有限数值。")
    return [_finite(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _validate_common(request: dict[str, Any], operation_fields: set[str]) -> None:
    """@brief 校验公共协议字段、输出格式和未知字段。"""
    unknown = set(request) - _COMMON_FIELDS - operation_fields
    if unknown:
        raise ValueError(f"请求含未允许字段: {', '.join(sorted(unknown))}")
    if request.get("schemaVersion") != "1.0" or request.get("units") != "mm":
        raise ValueError("schemaVersion/units 必须分别为 1.0/mm。")
    model_id = str(request.get("modelId") or "")
    if not model_id or len(model_id) > 64 or not model_id[0].isalpha() or not all(char.isalnum() or char == "_" for char in model_id):
        raise ValueError("modelId 只能使用字母开头的 1-64 位字母、数字或下划线。")
    _finite(request.get("toleranceMm"), "toleranceMm", positive=True, maximum=0.1)
    outputs = request.get("outputs")
    if not isinstance(outputs, list) or not outputs or len(outputs) != len(set(outputs)) or any(item not in _OUTPUTS for item in outputs):
        raise ValueError("outputs 必须是无重复的 step/brep/stl 白名单数组。")
    if not {"step", "brep"}.intersection(outputs):
        raise ValueError("outputs 至少包含 step 或 brep，以执行 B-Rep 重开验收。")


def _trusted_artifact(value: Any, field: str) -> dict[str, Any]:
    """@brief 验证本轮可信 STEP/BREP 输入及哈希。"""
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "producedThisRun"}:
        raise ValueError(f"{field} 必须包含 path、sha256 和 producedThisRun。")
    if value.get("producedThisRun") is not True:
        raise ValueError(f"{field}.producedThisRun 必须为 true。")
    path = Path(str(value.get("path") or "")).expanduser().resolve()
    if path.suffix.lower() not in {".step", ".stp", ".brep"} or not path.is_file():
        raise ValueError(f"{field}.path 必须是存在的 STEP/BREP 文件。")
    if path.stat().st_size <= 0 or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError(f"{field}.path 文件大小无效。")
    digest = str(value.get("sha256") or "").lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest) or digest != _sha256(path):
        raise ValueError(f"{field}.sha256 与实际文件不一致。")
    return {"path": str(path), "sha256": digest, "producedThisRun": True}


def validate_surface_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 按操作类型校验高级曲面请求。"""
    request = _load_request(value)
    operation = request.get("operation")
    if operation == "smooth_loft":
        _validate_common(request, {"solid", "sections", "continuityTarget", "maxDegree"})
        if request.get("solid") is not True or request.get("continuityTarget") not in {"C1", "C2"}:
            raise ValueError("smooth_loft 只允许 solid=true 且 continuityTarget 为 C1/C2。")
        maximum_degree = request.get("maxDegree")
        if isinstance(maximum_degree, bool) or not isinstance(maximum_degree, int) or not 3 <= maximum_degree <= 12:
            raise ValueError("maxDegree 必须是 3-12 的整数。")
        legacy = {
            "schemaVersion": "1.0", "modelId": request["modelId"], "units": "mm", "operation": "loft",
            "solid": True, "ruled": True, "toleranceMm": request["toleranceMm"],
            "sections": request.get("sections"), "outputs": request["outputs"],
        }
        validate_ocp_loft_request(legacy)
    elif operation == "sweep":
        _validate_common(request, {"profile", "path"})
        profile = request.get("profile")
        if not isinstance(profile, dict) or set(profile) != {"type", "radiusMm"} or profile.get("type") != "circle":
            raise ValueError("sweep.profile 当前只允许 circle + radiusMm。")
        _finite(profile.get("radiusMm"), "profile.radiusMm", positive=True)
        path = request.get("path")
        if not isinstance(path, dict) or path.get("type") not in {"line", "arc_xy"}:
            raise ValueError("sweep.path 当前只允许 line 或 arc_xy。")
        if path["type"] == "line":
            if set(path) != {"type", "start", "end"}:
                raise ValueError("line path 必须且只能包含 type/start/end。")
            start, end = _point3(path["start"], "path.start"), _point3(path["end"], "path.end")
            if math.dist(start, end) <= 1e-6:
                raise ValueError("line path 长度必须大于 1e-6 mm。")
        else:
            if set(path) != {"type", "center", "radiusMm", "startAngleDeg", "sweepAngleDeg"}:
                raise ValueError("arc_xy path 必须且只能包含 type/center/radiusMm/startAngleDeg/sweepAngleDeg。")
            _point3(path["center"], "path.center")
            _finite(path["radiusMm"], "path.radiusMm", positive=True)
            _finite(path["startAngleDeg"], "path.startAngleDeg")
            sweep = _finite(path["sweepAngleDeg"], "path.sweepAngleDeg", positive=True)
            if sweep > 180:
                raise ValueError("arc_xy 首版只允许 (0, 180] 度单圆弧。")
    elif operation == "knit":
        _validate_common(request, {"inputs", "makeSolid"})
        inputs = request.get("inputs")
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 32:
            raise ValueError("knit.inputs 必须包含 1-32 个可信输入。")
        request["inputs"] = [_trusted_artifact(item, f"inputs[{index}]") for index, item in enumerate(inputs)]
        if request.get("makeSolid") is not True:
            raise ValueError("knit 首版只允许 makeSolid=true 的闭壳验收。")
    elif operation == "thicken":
        _validate_common(request, {"input", "thicknessMm"})
        request["input"] = _trusted_artifact(request.get("input"), "input")
        thickness = _finite(request.get("thicknessMm"), "thicknessMm")
        if abs(thickness) < 1e-6 or abs(thickness) > 100:
            raise ValueError("thicknessMm 绝对值必须位于 [1e-6, 100] mm。")
    else:
        raise ValueError("operation 仅支持 smooth_loft、sweep、knit、thicken。")
    return request


def collect_surface_continuity_evidence(shape, *, skip_planar_faces: bool = False) -> dict[str, Any]:
    """@brief 对双邻接边五点采样，返回真实 C0/G1/G2 数值证据。"""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_G2, GeomAbs_Plane
    from OCP.LocalAnalysis import LocalAnalysis_SurfaceContinuity
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopoDS import TopoDS

    mapping = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, mapping)
    edge_records = []
    fractions = (0.05, 0.25, 0.5, 0.75, 0.95)
    skipped_planar = 0
    for index in range(1, mapping.Extent() + 1):
        faces = list(mapping.FindFromIndex(index))
        if len(faces) != 2:
            continue
        edge = TopoDS.Edge(mapping.FindKey(index))
        face1, face2 = TopoDS.Face(faces[0]), TopoDS.Face(faces[1])
        if skip_planar_faces and (
            BRepAdaptor_Surface(face1).GetType() == GeomAbs_Plane
            or BRepAdaptor_Surface(face2).GetType() == GeomAbs_Plane
        ):
            skipped_planar += 1
            continue
        range1 = BRep_Tool.Range_s(edge, face1)
        range2 = BRep_Tool.Range_s(edge, face2)
        curve1 = BRep_Tool.CurveOnSurface_s(edge, face1, range1[0], range1[1])
        curve2 = BRep_Tool.CurveOnSurface_s(edge, face2, range2[0], range2[1])
        samples = []
        if curve1 is not None and curve2 is not None:
            surface1, surface2 = BRep_Tool.Surface_s(face1), BRep_Tool.Surface_s(face2)
            for fraction in fractions:
                parameter1 = range1[0] + (range1[1] - range1[0]) * fraction
                parameter2 = range2[0] + (range2[1] - range2[0]) * fraction
                point1, point2 = curve1.Value(parameter1), curve2.Value(parameter2)
                analysis = LocalAnalysis_SurfaceContinuity(
                    surface1, point1.X(), point1.Y(), surface2, point2.X(), point2.Y(), GeomAbs_G2
                )
                done = bool(analysis.IsDone())
                samples.append({
                    "fraction": fraction, "isDone": done,
                    "isC0": bool(analysis.IsC0()) if done else False,
                    "isG1": bool(analysis.IsG1()) if done else False,
                    "isG2": bool(analysis.IsG2()) if done else False,
                    "c0ValueMm": float(analysis.C0Value()) if done else None,
                    "g1AngleRad": float(analysis.G1Angle()) if done else None,
                    "g1AngleDeg": math.degrees(float(analysis.G1Angle())) if done else None,
                    "g2CurvatureGap": float(analysis.G2CurvatureGap()) if done else None,
                })
        edge_records.append({
            "edgeIndex": index, "sameParameter": bool(BRep_Tool.SameParameter_s(edge)), "samples": samples,
            "g1Pass": bool(samples) and all(item["isDone"] and item["isG1"] for item in samples),
            "g2Pass": bool(samples) and all(item["isDone"] and item["isG1"] and item["isG2"] for item in samples),
        })
    all_samples = [sample for edge in edge_records for sample in edge["samples"] if sample["isDone"]]
    return {
        "method": "LocalAnalysis_SurfaceContinuity",
        "scope": "non_planar_shared_edges" if skip_planar_faces else "all_shared_edges",
        "sampleFractions": list(fractions),
        "sharedEdgeCount": len(edge_records),
        "skippedPlanarSharedEdgeCount": skipped_planar,
        "sampleCount": len(all_samples),
        "g1PassedEdgeCount": sum(1 for item in edge_records if item["g1Pass"]),
        "g2PassedEdgeCount": sum(1 for item in edge_records if item["g2Pass"]),
        "allSampledEdgesG1": bool(edge_records) and all(item["g1Pass"] for item in edge_records),
        "allSampledEdgesG2": bool(edge_records) and all(item["g2Pass"] for item in edge_records),
        "maximumG1AngleDeg": max((item["g1AngleDeg"] for item in all_samples), default=None),
        "maximumG2CurvatureGap": max((item["g2CurvatureGap"] for item in all_samples), default=None),
        "edges": edge_records,
        "limitations": ["只对拓扑共享边的离散采样点判定；不等于 Class-A 曲面认证。"],
    }


def _smooth_loft(request: dict[str, Any]):
    """@brief 构造带平滑设置的封闭 Loft 实体。"""
    from OCP.Approx import Approx_Centripetal
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.GeomAbs import GeomAbs_C1, GeomAbs_C2

    builder = BRepOffsetAPI_ThruSections(True, False, float(request["toleranceMm"]))
    builder.CheckCompatibility(True)
    builder.SetSmoothing(True)
    builder.SetContinuity(GeomAbs_C2 if request["continuityTarget"] == "C2" else GeomAbs_C1)
    builder.SetMaxDegree(int(request["maxDegree"]))
    builder.SetParType(Approx_Centripetal)
    for section in request["sections"]:
        builder.AddWire(_make_wire(section))
    builder.Build()
    if not builder.IsDone() or builder.Shape().IsNull():
        raise RuntimeError("OCP 平滑 Loft 构造失败。")
    return builder.Shape()


def _circle_wire(center: list[float], normal: list[float], radius: float):
    """@brief 在给定法向平面构造四段闭合圆形 Wire。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    circle = gp_Circ(gp_Ax2(gp_Pnt(*center), gp_Dir(*normal)), radius)
    wire = BRepBuilderAPI_MakeWire()
    for start in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
        wire.Add(BRepBuilderAPI_MakeEdge(circle, start, start + math.pi / 2).Edge())
    if not wire.IsDone():
        raise RuntimeError("Sweep 圆形截面构造失败。")
    return wire.Wire()


def _sweep(request: dict[str, Any]):
    """@brief 沿单直线或 XY 单圆弧扫描闭合圆形截面。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    path = request["path"]
    if path["type"] == "line":
        start, end = [float(item) for item in path["start"]], [float(item) for item in path["end"]]
        vector = [end[index] - start[index] for index in range(3)]
        length = math.sqrt(sum(item * item for item in vector))
        normal = [item / length for item in vector]
        spine_edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end)).Edge()
    else:
        center = [float(item) for item in path["center"]]
        radius = float(path["radiusMm"])
        start_angle = math.radians(float(path["startAngleDeg"]))
        end_angle = start_angle + math.radians(float(path["sweepAngleDeg"]))
        arc = gp_Circ(gp_Ax2(gp_Pnt(*center), gp_Dir(0, 0, 1)), radius)
        spine_edge = BRepBuilderAPI_MakeEdge(arc, start_angle, end_angle).Edge()
        start = [center[0] + radius * math.cos(start_angle), center[1] + radius * math.sin(start_angle), center[2]]
        normal = [-math.sin(start_angle), math.cos(start_angle), 0.0]
        length = radius * (end_angle - start_angle)
    spine_builder = BRepBuilderAPI_MakeWire(spine_edge)
    if not spine_builder.IsDone():
        raise RuntimeError("Sweep 路径 Wire 构造失败。")
    profile_radius = float(request["profile"]["radiusMm"])
    profile = _circle_wire(start, normal, profile_radius)
    builder = BRepOffsetAPI_MakePipeShell(spine_builder.Wire())
    builder.SetMode(False)
    tolerance = float(request["toleranceMm"])
    builder.SetTolerance(tolerance, tolerance, 0.01)
    builder.Add(profile, False, True)
    builder.Build()
    if not builder.IsDone() or not builder.MakeSolid() or builder.Shape().IsNull():
        raise RuntimeError("OCP Sweep 未生成封闭实体。")
    return builder.Shape(), {"pathLengthMm": length, "expectedVolumeMm3": math.pi * profile_radius**2 * length}


def _topology_counts(shape) -> dict[str, int]:
    """@brief 返回形状的 face/shell/solid 数量。"""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def count(kind) -> int:
        explorer, total = TopExp_Explorer(shape, kind), 0
        while explorer.More():
            total += 1
            explorer.Next()
        return total

    return {"faces": count(TopAbs_FACE), "shells": count(TopAbs_SHELL), "solids": count(TopAbs_SOLID)}


def _knit(request: dict[str, Any]):
    """@brief 缝合可信 STEP/BREP，并仅在闭壳时转为实体。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    sewing = BRepBuilderAPI_Sewing(float(request["toleranceMm"]), True, True, True, False)
    for artifact in request["inputs"]:
        path = Path(artifact["path"])
        sewing.Add(_reopen_shape(path, "brep" if path.suffix.lower() == ".brep" else "step"))
    sewing.Perform()
    sewed = sewing.SewedShape()
    sewing_evidence = {
        "freeEdgeCount": int(sewing.NbFreeEdges()),
        "multipleEdgeCount": int(sewing.NbMultipleEdges()),
        "contiguousEdgeCount": int(sewing.NbContigousEdges()),
        "valid": not sewed.IsNull() and bool(BRepCheck_Analyzer(sewed).IsValid()),
    }
    if not sewing_evidence["valid"] or sewing_evidence["freeEdgeCount"] or sewing_evidence["multipleEdgeCount"]:
        raise RuntimeError(f"Knit 未形成无自由边、无多重边的有效闭壳: {sewing_evidence}")
    shells = []
    explorer = TopExp_Explorer(sewed, TopAbs_SHELL)
    while explorer.More():
        shells.append(TopoDS.Shell(explorer.Current()))
        explorer.Next()
    if len(shells) != 1:
        raise RuntimeError(f"Knit 转实体要求恰好一个闭壳，实际 {len(shells)}。")
    maker = BRepBuilderAPI_MakeSolid(shells[0])
    shape = maker.Solid()
    if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise RuntimeError("Knit 闭壳转实体失败。")
    return shape, sewing_evidence


def _thicken(request: dict[str, Any]):
    """@brief 对可信开放面/壳执行简单偏置加厚。"""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid

    artifact = request["input"]
    path = Path(artifact["path"])
    source = _reopen_shape(path, "brep" if path.suffix.lower() == ".brep" else "step")
    topology = _topology_counts(source)
    if topology["solids"]:
        raise ValueError("thicken 首版只接受开放 face/shell；实体抽壳请走后续 hollow 操作。")
    if topology["faces"] < 1:
        raise ValueError("thicken 输入至少需要一个有效面。")
    builder = BRepOffsetAPI_MakeThickSolid()
    builder.MakeThickSolidBySimple(source, float(request["thicknessMm"]))
    if not builder.IsDone() or builder.Shape().IsNull():
        raise RuntimeError("OCP Thicken 构造失败，可能存在偏置自交或厚度过大。")
    shape = builder.Shape()
    # MakeThickSolidBySimple 的正偏置可能返回反向 Solid；统一为正体积后再交付。
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    volume = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume)
    orientation_reversed = volume.Mass() < 0
    if orientation_reversed:
        shape = shape.Reversed()
    return shape, {
        "sourceTopology": topology,
        "thicknessMm": float(request["thicknessMm"]),
        "orientationReversedForPositiveVolume": orientation_reversed,
    }


def _persist_result(request: dict[str, Any], shape, output_dir: str | Path, *, backend: str, extra: dict[str, Any]) -> dict[str, Any]:
    """@brief 写出版本化产物，重开 B-Rep，并附几何与连续性证据。"""
    original = _shape_evidence(shape)
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _versioned_stem(out_dir, request["modelId"], request["outputs"])
    suffixes = {"step": ".step", "brep": ".brep", "stl": ".stl"}
    artifacts, reopened = [], {}
    for fmt in request["outputs"]:
        target = out_dir / f"{stem}{suffixes[fmt]}"
        _write_shape(shape, target, fmt)
        artifact = {
            "kind": fmt, "format": fmt, "path": str(target), "exists": True,
            "sizeBytes": target.stat().st_size, "sha256": _sha256(target),
            "producedThisRun": True, "sourceBackend": backend, "reopened": fmt in {"step", "brep"},
        }
        artifacts.append(artifact)
        if fmt in {"step", "brep"}:
            reopened[fmt] = _shape_evidence(_reopen_shape(target, fmt))
            _verify_reopened_evidence(original, reopened[fmt], fmt)
    continuity = collect_surface_continuity_evidence(
        shape, skip_planar_faces=request["operation"] in {"smooth_loft", "sweep"}
    )
    if request["operation"] == "smooth_loft":
        continuity["target"] = request["continuityTarget"]
        continuity["targetPassed"] = (
            continuity["allSampledEdgesG2"]
            if request["continuityTarget"] == "C2"
            else continuity["allSampledEdgesG1"]
        )
    return {
        "schemaVersion": "1.0", "status": "review_required", "stage": "review", "backend": backend,
        "operation": request["operation"], "modelId": request["modelId"], "geometryProduced": True,
        "producedThisRun": True, "artifacts": artifacts,
        "geometryEvidence": {"original": original, "reopened": reopened, **extra},
        "continuityEvidence": continuity,
        "manual_review_required": True, "retryable": False, "error_code": None,
        "limitations": [
            "B-Rep 有效和共享边采样不能替代 Class-A、模具质量或可制造性认证。",
            "只有 continuityEvidence 中全部采样边通过时，才能声明该采样范围内的 G1/G2。",
        ],
    }


def execute_advanced_surface(value: str | Path | dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """@brief 执行一个白名单高级曲面操作并返回稳定证据。"""
    try:
        request = validate_surface_request(value)
    except (ValueError, json.JSONDecodeError) as exc:
        return _surface_result("blocked", "validate", "ocp_surface_invalid_request", str(exc))
    try:
        if request["operation"] == "smooth_loft":
            shape = _smooth_loft(request)
            envelope = _shape_evidence(shape)
            legacy = {
                "toleranceMm": request["toleranceMm"], "sections": request["sections"],
            }
            _verify_section_envelope(legacy, envelope)
            extra = {"sectionEnvelope": envelope.get("sectionEnvelopeCheck", {})}
        elif request["operation"] == "sweep":
            shape, extra = _sweep(request)
            actual_volume = _shape_evidence(shape)["volumeMm3"]
            relative_error = abs(actual_volume - extra["expectedVolumeMm3"]) / max(extra["expectedVolumeMm3"], 1e-12)
            extra["volumeRelativeError"] = relative_error
            if relative_error > 1e-4:
                raise RuntimeError(f"Sweep 体积与截面积乘路径长度不一致: {relative_error:g}")
        elif request["operation"] == "knit":
            shape, extra = _knit(request)
        else:
            shape, extra = _thicken(request)
        return _persist_result(request, shape, output_dir, backend=f"headless_ocp_{request['operation']}", extra=extra)
    except ValueError as exc:
        return _surface_result("blocked", "create", "ocp_surface_operation_blocked", str(exc))
    except Exception as exc:
        return _surface_result("failed", "create_or_review", "ocp_surface_operation_failed", str(exc))


def _surface_result(status: str, stage: str, error_code: str, message: str) -> dict[str, Any]:
    """@brief 返回高级曲面专用 blocked/failed 稳定结构。"""
    return {
        "schemaVersion": "1.0", "status": status, "stage": stage,
        "backend": "headless_ocp_advanced_surface", "geometryProduced": False,
        "producedThisRun": False, "artifacts": [], "geometryEvidence": {},
        "manual_review_required": True, "retryable": False,
        "error_code": error_code, "message": message,
        "generatedAt": _now_iso(),
    }
