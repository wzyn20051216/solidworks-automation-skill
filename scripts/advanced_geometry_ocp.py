"""@brief 严格受限的 OCP 参数化截面 Loft 黄金样件后端。

本模块只接受圆、椭圆或多边形的结构化封闭截面，并生成真实封闭 Loft 实体。
输出 STEP/BREP 后必须重新打开并再次通过有效性、实体数量、体积和包围盒门禁；
STL 只作为网格交付，不作为可编辑 B-Rep 或连续性证明。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_TOP_FIELDS = {"schemaVersion", "modelId", "units", "operation", "solid", "ruled", "toleranceMm", "sections", "outputs"}
_SECTION_FIELDS = {"id", "type", "z", "center", "radius", "majorRadius", "minorRadius", "rotationDeg", "points"}
_SECTION_TYPES = {"circle", "ellipse", "polygon"}
_OUTPUTS = {"step", "brep", "stl"}
_NATIVE_STDOUT_LOCK = threading.Lock()


@contextmanager
def _suppress_native_stdout():
    """@brief 临时抑制 OCCT 的 C++ 标准输出，避免污染 CLI/MCP JSON。

    OCCT 的 STEP reader/writer 会绕过 Python 日志系统直接写进程 stdout。文件描述符
    重定向是进程级操作，因此必须串行，并在异常路径中无条件恢复原描述符。
    """
    with _NATIVE_STDOUT_LOCK:
        try:
            if sys.stdout is not None:
                sys.stdout.flush()
            saved_stdout = os.dup(1)
        except (AttributeError, OSError):
            # pythonw/Tauri GUI 进程可能没有控制台；此时也没有 CLI stdout 可被污染。
            yield
            return
        null_stdout = None
        try:
            null_stdout = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null_stdout, 1)
            yield
        finally:
            try:
                if sys.stdout is not None:
                    sys.stdout.flush()
                os.dup2(saved_stdout, 1)
            finally:
                if null_stdout is not None:
                    os.close(null_stdout)
                os.close(saved_stdout)


def _now_iso() -> str:
    """@brief 返回 UTC 秒级时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identifier(value: Any, field: str) -> str:
    """@brief 验证稳定且不会进入文件名注入的标识符。"""
    token = str(value or "")
    if not _ID.fullmatch(token):
        raise ValueError(f"{field} 只能使用字母开头的 1-64 位字母、数字或下划线。")
    return token


def _finite(value: Any, field: str, *, positive: bool = False, maximum: float | None = None) -> float:
    """@brief 校验有限数值、正数约束和可选上限。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是有限数值。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限数值。") from exc
    if not math.isfinite(number) or (positive and number <= 0) or (maximum is not None and number > maximum):
        raise ValueError(f"{field} 超出允许范围。")
    return number


def _point2(value: Any, field: str) -> list[float]:
    """@brief 校验二维点。"""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} 必须是两个有限数值。")
    return [_finite(value[0], f"{field}[0]"), _finite(value[1], f"{field}[1]")]


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    """@brief 判断两条非相邻二维线段是否相交或接触。"""
    def orientation(p: list[float], q: list[float], r: list[float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def within(p: list[float], q: list[float], r: list[float]) -> bool:
        return min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12 and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12

    values = (orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b))
    if values[0] * values[1] < 0 and values[2] * values[3] < 0:
        return True
    return any(
        abs(value) <= 1e-12 and within(left, point, right)
        for value, left, point, right in (
            (values[0], a, c, b), (values[1], a, d, b), (values[2], c, a, d), (values[3], c, b, d)
        )
    )


def _validate_simple_polygon(points: list[list[float]], field: str) -> float:
    """@brief 校验多边形非退化、无自交，并返回带符号两倍面积。"""
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or (second + 1) % count == first:
                continue
            c, d = points[second], points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                raise ValueError(f"{field} 包含自交或非相邻边接触。")
    area2 = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))
    if abs(area2) <= 1e-9:
        raise ValueError(f"{field} 形成退化多边形。")
    return area2


def _load_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 从字典或最大 1 MiB JSON 文件读取请求。"""
    if isinstance(value, dict):
        return dict(value)
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError("OCP Loft 请求必须是存在的 JSON 文件。")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("OCP Loft 请求超过 1 MiB 安全上限。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OCP Loft 请求必须是 JSON object。")
    return payload


def validate_ocp_loft_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 严格校验参数化截面 Loft 请求。"""
    request = _load_request(value)
    unknown = set(request) - _TOP_FIELDS
    if unknown:
        raise ValueError(f"请求含未允许字段: {', '.join(sorted(unknown))}")
    if request.get("schemaVersion") != "1.0" or request.get("units") != "mm" or request.get("operation") != "loft":
        raise ValueError("schemaVersion/units/operation 必须分别为 1.0/mm/loft。")
    _identifier(request.get("modelId"), "modelId")
    if request.get("solid") is not True:
        raise ValueError("黄金后端当前只允许 solid=true 的封闭实体 Loft。")
    if request.get("ruled") is not True:
        raise ValueError("黄金后端当前只允许 ruled=true；平滑 Loft 尚未通过鼓包和连续性验证。")
    _finite(request.get("toleranceMm"), "toleranceMm", positive=True, maximum=0.1)
    outputs = request.get("outputs")
    if not isinstance(outputs, list) or not outputs or len(outputs) != len(set(outputs)) or any(item not in _OUTPUTS for item in outputs):
        raise ValueError("outputs 必须是无重复的 step/brep/stl 白名单数组。")
    if not {"step", "brep"}.intersection(outputs):
        raise ValueError("outputs 至少包含 step 或 brep，以便执行持久化 B-Rep 重开验收。")
    sections = request.get("sections")
    if not isinstance(sections, list) or not 2 <= len(sections) <= 32:
        raise ValueError("sections 数量必须为 2-32。")
    ids: set[str] = set()
    previous_z: float | None = None
    section_family: str | None = None
    polygon_vertex_count: int | None = None
    polygon_winding: int | None = None
    for index, section in enumerate(sections):
        if not isinstance(section, dict) or set(section) - _SECTION_FIELDS:
            raise ValueError(f"sections[{index}] 结构无效或含未允许字段。")
        section_id = _identifier(section.get("id"), f"sections[{index}].id")
        if section_id in ids:
            raise ValueError(f"截面 ID 重复: {section_id}")
        ids.add(section_id)
        kind = section.get("type")
        if kind not in _SECTION_TYPES:
            raise ValueError(f"sections[{index}].type 仅支持 circle/ellipse/polygon。")
        family = "polygon" if kind == "polygon" else "analytic"
        if section_family is None:
            section_family = family
        elif family != section_family:
            raise ValueError("圆/椭圆截面不能与多边形截面混用；请使用同一拓扑家族。")
        z_value = _finite(section.get("z"), f"sections[{index}].z")
        if previous_z is not None and z_value <= previous_z:
            raise ValueError("截面 z 必须严格递增，避免退化或反向 Loft。")
        previous_z = z_value
        _point2(section.get("center", [0, 0]), f"sections[{index}].center")
        expected = {"id", "type", "z"}
        optional_center = {"center"} if "center" in section else set()
        if kind == "circle":
            _finite(section.get("radius"), f"sections[{index}].radius", positive=True)
            expected |= {"radius"} | optional_center
        elif kind == "ellipse":
            major = _finite(section.get("majorRadius"), f"sections[{index}].majorRadius", positive=True)
            minor = _finite(section.get("minorRadius"), f"sections[{index}].minorRadius", positive=True)
            if major < minor:
                raise ValueError(f"sections[{index}].majorRadius 必须不小于 minorRadius。")
            if "rotationDeg" in section:
                _finite(section["rotationDeg"], f"sections[{index}].rotationDeg")
            expected |= {"majorRadius", "minorRadius"} | optional_center | ({"rotationDeg"} if "rotationDeg" in section else set())
        else:
            points = section.get("points")
            if not isinstance(points, list) or not 3 <= len(points) <= 128:
                raise ValueError(f"sections[{index}].points 数量必须为 3-128。")
            normalized = [_point2(point, f"sections[{index}].points") for point in points]
            if len({tuple(point) for point in normalized}) != len(normalized):
                raise ValueError(f"sections[{index}].points 不能包含重复点。")
            area2 = _validate_simple_polygon(normalized, f"sections[{index}].points")
            winding = 1 if area2 > 0 else -1
            if polygon_vertex_count is None:
                polygon_vertex_count = len(normalized)
                polygon_winding = winding
            elif len(normalized) != polygon_vertex_count or winding != polygon_winding:
                raise ValueError("多边形 Loft 的各截面必须具有相同顶点数和相同绕向。")
            expected |= {"points"} | optional_center
        unexpected_for_kind = set(section) - expected
        if unexpected_for_kind:
            raise ValueError(f"sections[{index}] 包含不适用于 {kind} 的字段: {', '.join(sorted(unexpected_for_kind))}")
    return request


def _make_wire(section: dict[str, Any]):
    """@brief 从一个白名单截面构造闭合 TopoDS_Wire。"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Elips, gp_Pnt

    center = section.get("center", [0, 0])
    x = float(center[0])
    y = float(center[1])
    z = float(section["z"])
    kind = section["type"]
    if kind == "circle":
        curve = gp_Circ(gp_Ax2(gp_Pnt(x, y, z), gp_Dir(0, 0, 1)), float(section["radius"]))
    elif kind == "ellipse":
        rotation = math.radians(float(section.get("rotationDeg", 0)))
        axis = gp_Ax2(gp_Pnt(x, y, z), gp_Dir(0, 0, 1), gp_Dir(math.cos(rotation), math.sin(rotation), 0))
        curve = gp_Elips(axis, float(section["majorRadius"]), float(section["minorRadius"]))
    else:
        curve = None
    if curve is not None:
        # 周期曲线拆成相同参数的四段，避免不同截面接缝错配导致平滑 Loft 鼓包。
        wire_builder = BRepBuilderAPI_MakeWire()
        for start in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            wire_builder.Add(BRepBuilderAPI_MakeEdge(curve, start, start + math.pi / 2).Edge())
        if not wire_builder.IsDone():
            raise RuntimeError(f"解析截面构造失败: {section['id']}")
        return wire_builder.Wire()
    polygon = BRepBuilderAPI_MakePolygon()
    for point in section["points"]:
        polygon.Add(gp_Pnt(x + float(point[0]), y + float(point[1]), z))
    polygon.Close()
    if not polygon.IsDone():
        raise RuntimeError(f"多边形截面构造失败: {section['id']}")
    return polygon.Wire()


def build_ocp_loft_shape(value: str | Path | dict[str, Any]):
    """@brief 构造真实 OCP 封闭 Loft 实体。"""
    request = validate_ocp_loft_request(value)
    if importlib.util.find_spec("OCP") is None:
        raise ModuleNotFoundError("缺少 OCP 运行时。")
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    builder = BRepOffsetAPI_ThruSections(True, bool(request["ruled"]), float(request["toleranceMm"]))
    builder.CheckCompatibility(True)
    for section in request["sections"]:
        builder.AddWire(_make_wire(section))
    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("OCP Loft 构造失败。")
    shape = builder.Shape()
    if shape.IsNull():
        raise RuntimeError("OCP Loft 返回空形状。")
    return request, shape


def _expected_section_bounds(request: dict[str, Any]) -> dict[str, list[float]]:
    """@brief 根据白名单截面参数计算理论包络，作为明显鼓包门禁。"""
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    for section in request["sections"]:
        center = section.get("center", [0, 0])
        x, y, z = float(center[0]), float(center[1]), float(section["z"])
        if section["type"] == "circle":
            x_radius = y_radius = float(section["radius"])
        elif section["type"] == "ellipse":
            major = float(section["majorRadius"])
            minor = float(section["minorRadius"])
            angle = math.radians(float(section.get("rotationDeg", 0)))
            x_radius = math.sqrt((major * math.cos(angle)) ** 2 + (minor * math.sin(angle)) ** 2)
            y_radius = math.sqrt((major * math.sin(angle)) ** 2 + (minor * math.cos(angle)) ** 2)
        else:
            x_values = [x + float(point[0]) for point in section["points"]]
            y_values = [y + float(point[1]) for point in section["points"]]
            x_radius = y_radius = 0.0
            minimum[0] = min(minimum[0], *x_values)
            maximum[0] = max(maximum[0], *x_values)
            minimum[1] = min(minimum[1], *y_values)
            maximum[1] = max(maximum[1], *y_values)
        if section["type"] != "polygon":
            minimum[0] = min(minimum[0], x - x_radius)
            maximum[0] = max(maximum[0], x + x_radius)
            minimum[1] = min(minimum[1], y - y_radius)
            maximum[1] = max(maximum[1], y + y_radius)
        minimum[2] = min(minimum[2], z)
        maximum[2] = max(maximum[2], z)
    return {"min": minimum, "max": maximum}


def _verify_section_envelope(request: dict[str, Any], evidence: dict[str, Any]) -> None:
    """@brief 阻断超过截面理论包络的异常 Loft。"""
    expected = _expected_section_bounds(request)
    actual = evidence["boundsMm"]
    tolerance = max(float(request["toleranceMm"]), 1e-6) * 2
    deltas = [expected["min"][i] - actual["min"][i] for i in range(3)] + [actual["max"][i] - expected["max"][i] for i in range(3)]
    maximum_excess = max(deltas)
    if maximum_excess > tolerance:
        raise RuntimeError(f"OCP Loft 超出截面理论包络 {maximum_excess:g} mm，疑似接缝错配或异常鼓包。")
    evidence["sectionEnvelopeCheck"] = {"expectedBoundsMm": expected, "maximumExcessMm": maximum_excess, "toleranceMm": tolerance, "pass": True}


def _shape_evidence(shape) -> dict[str, Any]:
    """@brief 收集有效性、拓扑、包围盒、体积和表面积。"""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer

    def count(kind) -> int:
        explorer = TopExp_Explorer(shape, kind)
        total = 0
        while explorer.More():
            total += 1
            explorer.Next()
        return total

    volume_props = GProp_GProps()
    surface_props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume_props)
    BRepGProp.SurfaceProperties_s(shape, surface_props)
    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    xmin, ymin, zmin, xmax, ymax, zmax = bounds.Get()
    evidence = {
        "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "volumeMm3": float(volume_props.Mass()),
        "surfaceAreaMm2": float(surface_props.Mass()),
        "boundsMm": {"min": [float(xmin), float(ymin), float(zmin)], "max": [float(xmax), float(ymax), float(zmax)]},
        "topology": {"solids": count(TopAbs_SOLID), "faces": count(TopAbs_FACE), "edges": count(TopAbs_EDGE), "vertices": count(TopAbs_VERTEX)},
    }
    if not evidence["valid"] or evidence["topology"]["solids"] < 1 or evidence["volumeMm3"] <= 0 or evidence["surfaceAreaMm2"] <= 0:
        raise RuntimeError("OCP Loft 未通过有效实体、拓扑、体积或面积门禁。")
    if any(not math.isfinite(value) for value in evidence["boundsMm"]["min"] + evidence["boundsMm"]["max"]):
        raise RuntimeError("OCP Loft 包围盒包含非有限数值。")
    return evidence


def _verify_reopened_evidence(original: dict[str, Any], reopened: dict[str, Any], fmt: str) -> None:
    """@brief 验证重开形状与原始形状的体积及包围盒一致。"""
    volume_reference = float(original["volumeMm3"])
    volume_delta = abs(float(reopened["volumeMm3"]) - volume_reference) / max(volume_reference, 1e-12)
    original_bounds = original["boundsMm"]["min"] + original["boundsMm"]["max"]
    reopened_bounds = reopened["boundsMm"]["min"] + reopened["boundsMm"]["max"]
    maximum_bound_delta = max(abs(float(left) - float(right)) for left, right in zip(original_bounds, reopened_bounds))
    if volume_delta > 1e-6 or maximum_bound_delta > 1e-5:
        raise RuntimeError(
            f"{fmt.upper()} 重开后几何偏差超限: volumeRelativeDelta={volume_delta:g}, "
            f"maximumBoundDeltaMm={maximum_bound_delta:g}。"
        )
    reopened["comparisonToOriginal"] = {
        "volumeRelativeDelta": volume_delta,
        "maximumBoundDeltaMm": maximum_bound_delta,
        "withinTolerance": True,
    }


def _sha256(path: Path) -> str:
    """@brief 计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versioned_stem(out_dir: Path, model_id: str, outputs: list[str]) -> str:
    """@brief 为整组产物选择不会发生任何覆盖的统一文件名。"""
    suffixes = {"step": ".step", "brep": ".brep", "stl": ".stl"}
    index = 1
    while True:
        stem = model_id if index == 1 else f"{model_id}_v{index}"
        if all(not (out_dir / f"{stem}{suffixes[item]}").exists() for item in outputs):
            return stem
        index += 1


def _write_shape(shape, target: Path, fmt: str) -> None:
    """@brief 使用已查证的 OCP API 写出一个白名单格式。"""
    if fmt == "step":
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        with _suppress_native_stdout():
            writer = STEPControl_Writer()
            transfer_status = writer.Transfer(shape, STEPControl_AsIs)
            write_status = writer.Write(str(target)) if transfer_status == IFSelect_RetDone else None
        if transfer_status != IFSelect_RetDone or write_status != IFSelect_RetDone:
            raise RuntimeError("STEP 写入失败。")
    elif fmt == "brep":
        from OCP.BRepTools import BRepTools

        if not BRepTools.Write_s(shape, str(target)):
            raise RuntimeError("BREP 写入失败。")
    elif fmt == "stl":
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        mesher = BRepMesh_IncrementalMesh(shape, 0.2, False, 0.35, True)
        mesher.Perform()
        if not mesher.IsDone() or not StlAPI_Writer().Write(shape, str(target)):
            raise RuntimeError("STL 网格化或写入失败。")
    else:  # pragma: no cover - 调用前已验证
        raise ValueError(f"不支持输出格式: {fmt}")
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError(f"{fmt.upper()} 产物为空。")


def _reopen_shape(path: Path, fmt: str):
    """@brief 重开 STEP 或 BREP，返回真实 TopoDS_Shape。"""
    if fmt == "step":
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader

        with _suppress_native_stdout():
            reader = STEPControl_Reader()
            read_status = reader.ReadFile(str(path))
            transferred_roots = reader.TransferRoots() if read_status == IFSelect_RetDone else 0
        if read_status != IFSelect_RetDone or transferred_roots <= 0:
            raise RuntimeError("STEP 重开或实体转换失败。")
        shape = reader.OneShape()
    elif fmt == "brep":
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape

        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
            raise RuntimeError("BREP 重开失败。")
    else:
        raise ValueError("只有 STEP/BREP 参与 B-Rep 重开验收。")
    if shape.IsNull():
        raise RuntimeError(f"{fmt.upper()} 重开后为空形状。")
    return shape


def execute_ocp_loft(value: str | Path | dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """@brief 执行真实 Loft、写出产物并用重开形状完成验收。"""
    try:
        request, shape = build_ocp_loft_shape(value)
    except (ValueError, json.JSONDecodeError) as exc:
        return _blocked("validate", "ocp_loft_invalid_request", str(exc))
    except ModuleNotFoundError as exc:
        return _blocked("preflight", "ocp_runtime_missing", str(exc), missingDependencies=["OCP"])
    except Exception as exc:
        return _failed("create", "ocp_loft_create_failed", str(exc))

    original: dict[str, Any] = {}
    try:
        original = _shape_evidence(shape)
        _verify_section_envelope(request, original)
    except Exception as exc:
        return _failed("review", "ocp_loft_section_envelope_failed", str(exc), geometryEvidence={"original": original})
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _versioned_stem(out_dir, request["modelId"], request["outputs"])
    artifacts: list[dict[str, Any]] = []
    reopened: dict[str, Any] = {}
    suffixes = {"step": ".step", "brep": ".brep", "stl": ".stl"}
    try:
        for fmt in request["outputs"]:
            target = out_dir / f"{stem}{suffixes[fmt]}"
            _write_shape(shape, target, fmt)
            artifact = {
                "kind": fmt, "format": fmt, "path": str(target), "exists": True,
                "sizeBytes": target.stat().st_size, "sha256": _sha256(target),
                "producedThisRun": True, "sourceBackend": "headless_ocp_loft",
            }
            artifacts.append(artifact)
            if fmt in {"step", "brep"}:
                reopened[fmt] = _shape_evidence(_reopen_shape(target, fmt))
                _verify_reopened_evidence(original, reopened[fmt], fmt)
                artifact["reopened"] = True
            else:
                artifact["reopened"] = False
                artifact["limitations"] = ["STL 是离散网格，非 B-Rep；本轮只验证文件非空和来源哈希。"]
    except Exception as exc:
        return _failed(
            "save_or_reopen",
            "ocp_loft_artifact_verification_failed",
            str(exc),
            artifacts=artifacts,
            geometryEvidence={"original": original, "reopened": reopened},
        )
    return {
        "schemaVersion": "1.0", "status": "review_required", "stage": "review", "backend": "headless_ocp_loft",
        "modelId": request["modelId"], "geometryProduced": True, "producedThisRun": True,
        "artifacts": artifacts, "geometryEvidence": {"original": original, "reopened": reopened},
        "manual_review_required": True, "retryable": False, "error_code": None, "generatedAt": _now_iso(),
        "limitations": ["已验证真实封闭直纹 Loft B-Rep，但未证明平滑 G1/G2 连续性、模具质量、Class-A 曲面或可制造性。"],
    }


def _blocked(stage: str, error_code: str, message: str, **extra: Any) -> dict[str, Any]:
    """@brief 构造稳定 blocked 结果。"""
    result = {"schemaVersion": "1.0", "status": "blocked", "stage": stage, "backend": "headless_ocp_loft", "geometryProduced": False, "producedThisRun": False, "artifacts": [], "geometryEvidence": {}, "manual_review_required": True, "retryable": False, "error_code": error_code, "message": message, "generatedAt": _now_iso()}
    result.update(extra)
    return result


def _failed(stage: str, error_code: str, message: str, **extra: Any) -> dict[str, Any]:
    """@brief 构造稳定 failed 结果。"""
    result = {"schemaVersion": "1.0", "status": "failed", "stage": stage, "backend": "headless_ocp_loft", "geometryProduced": False, "producedThisRun": False, "artifacts": [], "geometryEvidence": {}, "manual_review_required": True, "retryable": False, "error_code": error_code, "message": message, "generatedAt": _now_iso()}
    result.update(extra)
    return result
