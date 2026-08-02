"""无 CAD 软件时的开放格式写入器。

当前实现覆盖 `.cadstudio.json` 中基础盒体/圆柱到 STL、OBJ、DXF 的真实写入。
STEP/IGES/BREP 需要后续 OCCT/OCP 后端，不在本脚本中伪造支持。
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "apps" / "desktop"
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from cad_workbench.cad_core_contracts import preview_manifest_for_artifact, sha256_file, write_json_contract  # noqa: E402
try:  # noqa: E402
    from dxf_preview_scene import dxf_to_preview_scene
except ModuleNotFoundError:  # noqa: E402
    from scripts.dxf_preview_scene import dxf_to_preview_scene


Point3 = tuple[float, float, float]
Triangle = tuple[Point3, Point3, Point3]
Line2 = tuple[float, float, float, float, str]
Circle2 = tuple[float, float, float, str]
OCCT_FORMATS = {"step", "stp", "iges", "igs", "brep", "stl", "obj", "glb"}
ADVANCED_OCCT_FORMATS = {"step", "stp", "iges", "igs", "brep", "glb"}


def _feature_params(feature: dict[str, Any]) -> dict[str, Any]:
    return feature.get("parameters") if isinstance(feature.get("parameters"), dict) else {}


def _versioned_target(out_dir: Path, name: str, extension: str) -> Path:
    """@brief 生成不覆盖旧产物的版本化目标路径。"""
    target = out_dir / f"{name}.{extension}"
    if not target.exists():
        return target
    version = 2
    while True:
        candidate = out_dir / f"{name}_v{version}.{extension}"
        if not candidate.exists():
            return candidate
        version += 1


def _run_occt_service(document_path: Path, out_dir: Path, formats: list[str]) -> dict[str, Any]:
    """@brief 在独立进程中运行 OCCT，避免原生崩溃影响队列 Worker。"""
    service = ROOT / "scripts" / "headless_occt_service.py"
    with tempfile.TemporaryDirectory(prefix="cadstudio-occt-result-") as temp_dir:
        result_path = Path(temp_dir) / "result.json"
        command = [
            sys.executable,
            str(service),
            "--input",
            str(document_path),
            "--out-dir",
            str(out_dir),
            "--formats",
            *formats,
            "--result-json",
            str(result_path),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired:
            return {
                "backend": "headless_occt",
                "status": "failed",
                "artifacts": [],
                "limitations": ["OCCT 隔离服务超过 180 秒未完成。"],
                "error_code": "occt_timeout",
            }
        if result_path.is_file():
            return json.loads(result_path.read_text(encoding="utf-8"))
        return {
            "backend": "headless_occt",
            "status": "failed",
            "artifacts": [],
            "limitations": [f"OCCT 隔离服务未返回结果文件，退出码 {completed.returncode}。"],
            "error_code": "occt_result_missing",
        }


def _box_mesh(length: float, width: float, height: float) -> list[Triangle]:
    """@brief 生成以原点居中的盒体三角面片。"""
    x = length / 2
    y = width / 2
    z = height / 2
    v = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    ]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return [(v[a], v[b], v[c]) for a, b, c, _ in quads] + [(v[a], v[c], v[d]) for a, _, c, d in quads]


def _cylinder_mesh(radius: float, height: float, segments: int = 48) -> list[Triangle]:
    """@brief 生成 Z 轴圆柱体三角面片。"""
    z0 = -height / 2
    z1 = height / 2
    top = (0.0, 0.0, z1)
    bottom = (0.0, 0.0, z0)
    ring0 = [(math.cos(i / segments * math.tau) * radius, math.sin(i / segments * math.tau) * radius, z0) for i in range(segments)]
    ring1 = [(x, y, z1) for x, y, _ in ring0]
    triangles: list[Triangle] = []
    for index in range(segments):
        next_index = (index + 1) % segments
        triangles.append((ring0[index], ring0[next_index], ring1[next_index]))
        triangles.append((ring0[index], ring1[next_index], ring1[index]))
        triangles.append((bottom, ring0[index], ring0[next_index]))
        triangles.append((top, ring1[next_index], ring1[index]))
    return triangles


def _normal(triangle: Triangle) -> Point3:
    ax, ay, az = triangle[0]
    bx, by, bz = triangle[1]
    cx, cy, cz = triangle[2]
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def _validate_document(document: Any) -> dict[str, Any]:
    """@brief 校验无头写入所需的最小 NeutralCadDocument 结构。"""
    if not isinstance(document, dict):
        raise ValueError("NeutralCadDocument 必须是 JSON object。")
    if not str(document.get("documentId") or "").strip():
        raise ValueError("NeutralCadDocument 缺少 documentId。")
    if not isinstance(document.get("features", []), list):
        raise ValueError("NeutralCadDocument.features 必须是数组。")
    for feature in document.get("features", []):
        if not isinstance(feature, dict) or not str(feature.get("id") or "").strip() or not str(feature.get("type") or "").strip():
            raise ValueError("每个 feature 必须包含非空 id 和 type。")
        params = _feature_params(feature)
        for key in ("length", "width", "height", "radius", "diameter"):
            if key in params and float(params[key]) <= 0:
                raise ValueError(f"feature {feature['id']} 的 {key} 必须大于 0。")
    return document


def _triangles(document: dict[str, Any]) -> tuple[list[Triangle], list[str], bool]:
    triangles: list[Triangle] = []
    limitations: list[str] = []
    mesh_blocked = False
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        params = _feature_params(feature)
        kind = str(feature.get("type") or "").lower()
        operation = str(feature.get("operation") or "add").lower()
        if operation not in {"add", "new", "union"}:
            limitations.append(f"网格后端暂不支持布尔操作: {feature.get('id')} ({operation})")
            mesh_blocked = True
        elif kind == "box":
            triangles.extend(_box_mesh(float(params.get("length", 10)), float(params.get("width", 10)), float(params.get("height", 10))))
        elif kind == "cylinder":
            triangles.extend(_cylinder_mesh(float(params.get("radius", 5)), float(params.get("height", 10)), int(params.get("segments", 48))))
        else:
            limitations.append(f"暂未无头写入特征: {feature.get('id') or kind}")
            mesh_blocked = True
    return triangles, limitations, mesh_blocked


def write_ascii_stl(path: Path, name: str, triangles: list[Triangle]) -> None:
    """@brief 写出 ASCII STL。"""
    lines = [f"solid {name}"]
    for triangle in triangles:
        nx, ny, nz = _normal(triangle)
        lines.append(f"  facet normal {nx:.9g} {ny:.9g} {nz:.9g}")
        lines.append("    outer loop")
        for x, y, z in triangle:
            lines.append(f"      vertex {x:.9g} {y:.9g} {z:.9g}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_obj(path: Path, triangles: list[Triangle]) -> None:
    """@brief 写出 Wavefront OBJ，使用每三角形独立顶点以保持实现简单可靠。"""
    lines = ["# CAD Studio headless OBJ"]
    for triangle in triangles:
        for x, y, z in triangle:
            lines.append(f"v {x:.9g} {y:.9g} {z:.9g}")
    for index in range(0, len(triangles) * 3, 3):
        lines.append(f"f {index + 1} {index + 2} {index + 3}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _feature_radius(params: dict[str, Any]) -> float:
    return float(params.get("radius", float(params.get("diameter", 10)) / 2))


def _document_2d_geometry(document: dict[str, Any]) -> tuple[list[Line2], list[Circle2], tuple[float, float, float, float]]:
    """@brief 从中性 CAD 特征提取基础二维轮廓，用于 DXF/SVG/PDF/PNG 回退预览。"""
    lines: list[Line2] = []
    circles: list[Circle2] = []
    bounds = [0.0, 0.0, 1.0, 1.0]

    def include_point(x: float, y: float) -> None:
        bounds[0] = min(bounds[0], x)
        bounds[1] = min(bounds[1], y)
        bounds[2] = max(bounds[2], x)
        bounds[3] = max(bounds[3], y)

    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        kind = str(feature.get("type") or "").lower()
        params = _feature_params(feature)
        if kind == "box":
            length = float(params.get("length", 10))
            width = float(params.get("width", 10))
            x0, y0 = -length / 2, -width / 2
            x1, y1 = length / 2, width / 2
            lines.extend(
                [
                    (x0, y0, x1, y0, "OUTLINE"),
                    (x1, y0, x1, y1, "OUTLINE"),
                    (x1, y1, x0, y1, "OUTLINE"),
                    (x0, y1, x0, y0, "OUTLINE"),
                ]
            )
            include_point(x0, y0)
            include_point(x1, y1)
        elif kind in {"cylinder", "hole"}:
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            radius = _feature_radius(params)
            circles.append((x, y, radius, "HOLES"))
            include_point(x - radius, y - radius)
            include_point(x + radius, y + radius)
    margin = max((bounds[2] - bounds[0]) * 0.08, (bounds[3] - bounds[1]) * 0.08, 10.0)
    return lines, circles, (bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin)


def _unsupported_2d_features(document: dict[str, Any]) -> list[str]:
    """@brief 返回当前二维后端无法完整表达的特征 ID。"""
    unsupported: list[str] = []
    for feature in document.get("features", []):
        kind = str(feature.get("type") or "").lower()
        operation = str(feature.get("operation") or "add").lower()
        supported = kind in {"hole", "line", "polyline", "circle", "text", "dimension"} or (
            kind in {"box", "cylinder"} and operation in {"add", "new", "union"}
        )
        if not supported:
            unsupported.append(str(feature.get("id") or kind or "unknown"))
    return unsupported


def write_dxf(path: Path, document: dict[str, Any]) -> None:
    """@brief 写出包含机械制图图层、真实尺寸和可选 GB/T 图框的 DXF。"""
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    layer_specs = [
        ("OUTLINE", 7, "CONTINUOUS"),
        ("HOLES", 3, "CONTINUOUS"),
        ("CENTER", 4, "CENTER"),
        ("DIMENSION", 2, "CONTINUOUS"),
        ("FRAME", 7, "CONTINUOUS"),
        ("TITLE", 5, "CONTINUOUS"),
        ("TEXT", 5, "CONTINUOUS"),
    ]
    for layer, color, linetype in layer_specs:
        if layer not in doc.layers:
            doc.layers.add(layer, color=color, linetype=linetype)
    msp = doc.modelspace()
    lines, circles, _ = _document_2d_geometry(document)
    for x0, y0, x1, y1, layer in lines:
        msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": layer})
    for x, y, radius, layer in circles:
        msp.add_circle((x, y), radius, dxfattribs={"layer": layer})
        extension = max(radius * 1.45, radius + 2.0)
        msp.add_line((x - extension, y), (x + extension, y), dxfattribs={"layer": "CENTER"})
        msp.add_line((x, y - extension), (x, y + extension), dxfattribs={"layer": "CENTER"})
        msp.add_diameter_dim(center=(x, y), radius=radius, angle=45, dxfattribs={"layer": "DIMENSION"}).render()

    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        kind = str(feature.get("type") or "").lower()
        params = _feature_params(feature)
        layer = str(params.get("layer") or ("TEXT" if kind == "text" else "OUTLINE"))
        if layer not in doc.layers:
            doc.layers.add(layer, color=7)
        if kind == "line":
            msp.add_line((float(params.get("x1", 0)), float(params.get("y1", 0))), (float(params.get("x2", 0)), float(params.get("y2", 0))), dxfattribs={"layer": layer})
        elif kind == "polyline":
            points = params.get("points") if isinstance(params.get("points"), list) else []
            clean_points = [(float(point[0]), float(point[1])) for point in points if isinstance(point, (list, tuple)) and len(point) >= 2]
            if len(clean_points) >= 2:
                msp.add_lwpolyline(clean_points, close=bool(params.get("closed")), dxfattribs={"layer": layer})
        elif kind == "circle":
            msp.add_circle((float(params.get("x", 0)), float(params.get("y", 0))), _feature_radius(params), dxfattribs={"layer": layer})
        elif kind == "text":
            value = str(params.get("text") or feature.get("name") or feature.get("id") or "")
            msp.add_text(value, height=float(params.get("height", 3)), dxfattribs={"layer": layer}).set_placement((float(params.get("x", 0)), float(params.get("y", 0))))
        elif kind == "dimension":
            p1 = (float(params.get("x1", 0)), float(params.get("y1", 0)))
            p2 = (float(params.get("x2", 0)), float(params.get("y2", 0)))
            base = (float(params.get("baseX", (p1[0] + p2[0]) / 2)), float(params.get("baseY", min(p1[1], p2[1]) - 10)))
            msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=float(params.get("angle", 0)), dxfattribs={"layer": "DIMENSION"}).render()

    boxes = [feature for feature in document.get("features", []) if isinstance(feature, dict) and str(feature.get("type") or "").lower() == "box"]
    if boxes:
        params = _feature_params(boxes[0])
        length = float(params.get("length", 10))
        width = float(params.get("width", 10))
        x0, y0 = -length / 2, -width / 2
        x1, y1 = length / 2, width / 2
        msp.add_linear_dim(base=(0, y0 - 12), p1=(x0, y0), p2=(x1, y0), angle=0, dxfattribs={"layer": "DIMENSION"}).render()
        msp.add_linear_dim(base=(x1 + 12, 0), p1=(x1, y0), p2=(x1, y1), angle=90, dxfattribs={"layer": "DIMENSION"}).render()

    drawing = document.get("metadata", {}).get("drawing", {}) if isinstance(document.get("metadata"), dict) else {}
    if isinstance(drawing, dict) and bool(drawing.get("includeFrame")):
        _add_gbt_frame(msp, document, drawing)
    else:
        msp.add_text(str(document.get("title") or document.get("documentId") or "CAD Studio"), height=3, dxfattribs={"layer": "TEXT"}).set_placement((0, -18))
    doc.saveas(path)


def _add_gbt_frame(modelspace: Any, document: dict[str, Any], drawing: dict[str, Any]) -> None:
    """@brief 添加居中图幅、装订边和可检索的 GB/T 风格标题栏字段。"""
    sheet_sizes = {"A4": (210.0, 297.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}
    sheet = str(drawing.get("sheet") or "A3").upper()
    width, height = sheet_sizes.get(sheet, sheet_sizes["A3"])
    if str(drawing.get("orientation") or "landscape").lower() == "portrait" and width > height:
        width, height = height, width
    x0, y0 = -width / 2, -height / 2
    x1, y1 = width / 2, height / 2
    modelspace.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "FRAME"})
    modelspace.add_lwpolyline([(x0 + 20, y0 + 5), (x1 - 5, y0 + 5), (x1 - 5, y1 - 5), (x0 + 20, y1 - 5)], close=True, dxfattribs={"layer": "FRAME"})

    title_width = min(180.0, width - 30.0)
    title_height = 40.0
    tx0, ty0 = x1 - 5 - title_width, y0 + 5
    tx1, ty1 = x1 - 5, ty0 + title_height
    modelspace.add_lwpolyline([(tx0, ty0), (tx1, ty0), (tx1, ty1), (tx0, ty1)], close=True, dxfattribs={"layer": "TITLE"})
    for offset in (10.0, 22.0, 31.0):
        modelspace.add_line((tx0, ty0 + offset), (tx1, ty0 + offset), dxfattribs={"layer": "TITLE"})
    modelspace.add_line((tx0 + title_width * 0.62, ty0), (tx0 + title_width * 0.62, ty1), dxfattribs={"layer": "TITLE"})
    fields = [
        ("名称", str(document.get("title") or document.get("documentId") or "未命名"), tx0 + 3, ty0 + 34),
        ("图号", str(drawing.get("drawingNumber") or document.get("documentId") or "-"), tx0 + 3, ty0 + 25),
        ("材料", str(drawing.get("material") or "待确认"), tx0 + 3, ty0 + 14),
        ("比例", str(drawing.get("scale") or "1:1"), tx0 + title_width * 0.64, ty0 + 34),
        ("单位", str(document.get("units") or "mm"), tx0 + title_width * 0.64, ty0 + 25),
        ("设计", str(drawing.get("designer") or "CAD Studio"), tx0 + title_width * 0.64, ty0 + 14),
        ("审核", str(drawing.get("reviewer") or "待复核"), tx0 + title_width * 0.64, ty0 + 4),
    ]
    for label, value, x, y in fields:
        modelspace.add_text(f"{label}: {value}", height=2.6, dxfattribs={"layer": "TITLE"}).set_placement((x, y))


def write_svg(path: Path, document: dict[str, Any]) -> None:
    """@brief 写出浏览器可直接查看的 SVG 预览图。"""
    lines, circles, bounds = _document_2d_geometry(document)
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    title = html.escape(str(document.get("title") or document.get("documentId") or "CAD Studio"))
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.6g} {-max_y:.6g} {width:.6g} {height:.6g}">',
        f"<title>{title}</title>",
        '<rect x="-100000" y="-100000" width="200000" height="200000" fill="#f7f8fa"/>',
        '<g transform="scale(1,-1)" fill="none" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for x0, y0, x1, y1, layer in lines:
        color = "#1f2937" if layer == "OUTLINE" else "#0f766e"
        svg.append(f'<line x1="{x0:.6g}" y1="{y0:.6g}" x2="{x1:.6g}" y2="{y1:.6g}" stroke="{color}" stroke-width="0.7"/>')
    for x, y, radius, _layer in circles:
        svg.append(f'<circle cx="{x:.6g}" cy="{y:.6g}" r="{radius:.6g}" stroke="#0f766e" stroke-width="0.7"/>')
    svg.extend(["</g>", f'<text x="{min_x:.6g}" y="{-min_y:.6g}" fill="#475569" font-size="4">{title}</text>', "</svg>"])
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, document: dict[str, Any]) -> None:
    """@brief 写出不依赖第三方库的基础 PDF 回退预览。"""
    lines, circles, bounds = _document_2d_geometry(document)
    min_x, min_y, max_x, max_y = bounds
    scale = 72.0 / 25.4
    page_w = max((max_x - min_x) * scale, 200.0)
    page_h = max((max_y - min_y) * scale, 160.0)

    def tx(x: float) -> float:
        return (x - min_x) * scale

    def ty(y: float) -> float:
        return (y - min_y) * scale

    commands = ["0.97 0.98 0.99 rg 0 0 %.3f %.3f re f" % (page_w, page_h), "0.12 0.16 0.22 RG 0.75 w"]
    for x0, y0, x1, y1, _layer in lines:
        commands.append(f"{tx(x0):.3f} {ty(y0):.3f} m {tx(x1):.3f} {ty(y1):.3f} l S")
    commands.append("0.06 0.46 0.43 RG")
    for x, y, radius, _layer in circles:
        points = []
        for index in range(40):
            angle = index / 40 * math.tau
            points.append((tx(x + math.cos(angle) * radius), ty(y + math.sin(angle) * radius)))
        if points:
            commands.append(f"{points[0][0]:.3f} {points[0][1]:.3f} m")
            commands.extend(f"{px:.3f} {py:.3f} l" for px, py in points[1:])
            commands.append("h S")
    title = _pdf_escape(str(document.get("title") or document.get("documentId") or "CAD Studio"))
    commands.append(f"0.28 0.33 0.41 rg BT /F1 10 Tf 12 12 Td ({title}) Tj ET")
    content = ("\n".join(commands) + "\n").encode("ascii", errors="ignore")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.3f} {page_h:.3f}] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode("ascii"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    path.write_bytes(bytes(body))


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def write_png(path: Path, document: dict[str, Any], width: int = 900, height: int = 620) -> None:
    """@brief 写出无依赖 PNG 回退预览，确保无 WebGL 时仍有真实任务图像。"""
    lines, circles, bounds = _document_2d_geometry(document)
    min_x, min_y, max_x, max_y = bounds
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    margin = 36
    scale = min((width - margin * 2) / span_x, (height - margin * 2) / span_y)
    pixels = bytearray([248, 250, 252] * width * height)

    def point(x: float, y: float) -> tuple[int, int]:
        px = int((x - min_x) * scale + margin)
        py = int(height - ((y - min_y) * scale + margin))
        return max(0, min(width - 1, px)), max(0, min(height - 1, py))

    def set_px(px: int, py: int, color: tuple[int, int, int]) -> None:
        if 0 <= px < width and 0 <= py < height:
            offset = (py * width + px) * 3
            pixels[offset : offset + 3] = bytes(color)

    def draw_line(a: tuple[int, int], b: tuple[int, int], color: tuple[int, int, int]) -> None:
        x0, y0 = a
        x1, y1 = b
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    set_px(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    for x0, y0, x1, y1, _layer in lines:
        draw_line(point(x0, y0), point(x1, y1), (31, 41, 55))
    for x, y, radius, _layer in circles:
        previous = None
        for index in range(97):
            angle = index / 96 * math.tau
            current = point(x + math.cos(angle) * radius, y + math.sin(angle) * radius)
            if previous is not None:
                draw_line(previous, current, (15, 118, 110))
            previous = current

    raw = b"".join(b"\x00" + pixels[row * width * 3 : (row + 1) * width * 3] for row in range(height))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += _png_chunk(b"IDAT", zlib.compress(raw, level=6))
    payload += _png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def write_rendered_dxf_format(path: Path, document: dict[str, Any]) -> None:
    """@brief 从同一 DXF 工程图渲染 SVG、PDF 或 PNG，保持图层、尺寸和标题栏一致。"""
    import matplotlib

    matplotlib.use("Agg")
    import ezdxf
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    with tempfile.TemporaryDirectory(prefix="cadstudio-drawing-render-") as temp_dir:
        source = Path(temp_dir) / "drawing.dxf"
        write_dxf(source, document)
        dxf_document = ezdxf.readfile(source)
        figure = plt.figure(figsize=(11.69, 8.27), dpi=140)
        axes = figure.add_axes([0.015, 0.015, 0.97, 0.97])
        axes.set_aspect("equal")
        axes.axis("off")
        context = RenderContext(dxf_document)
        Frontend(context, MatplotlibBackend(axes)).draw_layout(dxf_document.modelspace(), finalize=True)
        figure.savefig(path, format=path.suffix.lower().lstrip("."), facecolor="white", bbox_inches="tight", pad_inches=0.04)
        plt.close(figure)


def export_headless(document_path: Path, out_dir: Path, formats: list[str]) -> dict[str, Any]:
    """@brief 将 NeutralCadDocument 写成开放格式产物。"""
    try:
        document = _validate_document(json.loads(document_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "backend": "headless_open_format",
            "status": "failed",
            "stage": "preflight",
            "artifacts": [],
            "previewManifest": "",
            "limitations": [str(exc)],
            "missingFormats": [fmt.lower().lstrip(".") for fmt in formats],
            "retryable": False,
            "error_code": "invalid_neutral_document",
        }
    name = str(document.get("documentId") or document_path.stem).replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    triangles, limitations, mesh_blocked = _triangles(document)
    unsupported_2d = _unsupported_2d_features(document)
    artifacts: list[dict[str, Any]] = []
    missing_formats: list[str] = []
    geometry_evidence: dict[str, Any] = {}
    normalized_formats = [fmt.lower().lstrip(".") for fmt in formats]
    occt_requested = [fmt for fmt in normalized_formats if fmt in OCCT_FORMATS]
    occt_handled: set[str] = set()
    if occt_requested and importlib.util.find_spec("OCP") is not None:
        occt_result = _run_occt_service(document_path, out_dir, occt_requested)
        occt_handled.update(occt_requested)
        artifacts.extend(occt_result.get("artifacts") or [])
        limitations.extend(occt_result.get("limitations") or [])
        geometry_evidence = occt_result.get("geometryEvidence") or {}
        if occt_result.get("status") != "pass":
            missing_formats.extend({"step" if fmt == "stp" else "iges" if fmt == "igs" else fmt for fmt in occt_requested})
    elif any(fmt in ADVANCED_OCCT_FORMATS for fmt in normalized_formats):
        blocked = [fmt for fmt in normalized_formats if fmt in ADVANCED_OCCT_FORMATS]
        occt_handled.update(blocked)
        missing_formats.extend(blocked)
        limitations.append("未发现 OCP 运行时，STEP/IGES/BREP/GLB 保持 blocked。")
    if (not triangles or mesh_blocked) and any(fmt in {"stl", "obj"} and fmt not in occt_handled for fmt in normalized_formats):
        limitations.append("当前文档不能完整网格化，未写出 STL/OBJ，避免把部分几何当成完整交付。")
    if unsupported_2d and any(fmt in {"dxf", "svg", "pdf", "png"} for fmt in normalized_formats):
        limitations.append("当前二维后端无法完整表达特征: " + ", ".join(unsupported_2d))
    for normalized in normalized_formats:
        if normalized in occt_handled:
            continue
        target = _versioned_target(out_dir, name, normalized)
        if normalized in {"cadstudio", "cadstudio.json", "json"}:
            target = _versioned_target(out_dir, name, "cadstudio.json")
            shutil.copyfile(document_path, target)
        elif normalized == "stl":
            if not triangles or mesh_blocked:
                missing_formats.append(normalized)
                continue
            write_ascii_stl(target, name, triangles)
        elif normalized == "obj":
            if not triangles or mesh_blocked:
                missing_formats.append(normalized)
                continue
            write_obj(target, triangles)
        elif normalized == "dxf":
            if unsupported_2d:
                missing_formats.append(normalized)
                continue
            write_dxf(target, document)
        elif normalized == "svg":
            if unsupported_2d:
                missing_formats.append(normalized)
                continue
            try:
                write_rendered_dxf_format(target, document)
            except ImportError:
                write_svg(target, document)
                limitations.append("缺少 matplotlib，SVG 使用简化轮廓回退，不包含完整尺寸文字。")
        elif normalized == "pdf":
            if unsupported_2d:
                missing_formats.append(normalized)
                continue
            try:
                write_rendered_dxf_format(target, document)
            except ImportError:
                write_pdf(target, document)
                limitations.append("缺少 matplotlib，PDF 使用简化轮廓回退，不包含完整尺寸文字。")
        elif normalized == "png":
            if unsupported_2d:
                missing_formats.append(normalized)
                continue
            try:
                write_rendered_dxf_format(target, document)
            except ImportError:
                write_png(target, document)
                limitations.append("缺少 matplotlib，PNG 使用简化轮廓回退，不包含完整尺寸文字。")
        else:
            limitations.append(f"无头后端暂不支持写入格式: {normalized}")
            missing_formats.append(normalized)
            continue
        artifacts.append({"kind": "cadstudio" if normalized in {"cadstudio", "cadstudio.json", "json"} else normalized, "path": str(target), "exists": True, "producedThisRun": True, "sha256": sha256_file(target), "sourceBackend": "headless_open_format"})
    preview_scene_path = ""
    dxf_artifact = next((item["path"] for item in artifacts if item["kind"] == "dxf"), "")
    if dxf_artifact:
        scene_target = _versioned_target(out_dir, name, "scene.json")
        try:
            dxf_to_preview_scene(dxf_artifact, scene_target)
            preview_scene_path = str(scene_target)
            artifacts.append({"kind": "preview_scene", "path": preview_scene_path, "exists": True, "producedThisRun": True, "sha256": sha256_file(scene_target), "sourceBackend": "ezdxf-preview-scene"})
        except (OSError, ValueError, ImportError) as exc:
            limitations.append(f"DXF PreviewScene 生成失败: {exc}")

    preview_source = ""
    for preview_kind in ("glb", "preview_scene", "dxf", "stl", "obj"):
        preview_source = next((item["path"] for item in artifacts if item["kind"] == preview_kind), "")
        if preview_source:
            break
    fallback_image = next((item["path"] for item in artifacts if item["kind"] == "png"), "")
    preview_manifest_path = ""
    if preview_source:
        manifest = preview_manifest_for_artifact(document_path, preview_source, fallback_image=fallback_image, units=document.get("units", "mm"), evidence_refs=[f"feature:{feature.get('id')}" for feature in document.get("features", []) if isinstance(feature, dict) and feature.get("id")])
        if preview_scene_path and preview_source == preview_scene_path:
            try:
                scene = json.loads(Path(preview_scene_path).read_text(encoding="utf-8"))
                manifest = replace(
                    manifest,
                    entities=scene.get("entities", []),
                    layers=scene.get("layers", []),
                    bounds=scene.get("bounds", {}),
                    limitations=[*manifest.limitations, *scene.get("limitations", [])],
                )
            except (OSError, json.JSONDecodeError):
                limitations.append("PreviewScene 清单读取失败，保留源文件预览。")
        preview_manifest_path = str(write_json_contract(_versioned_target(out_dir, name, "preview.json"), manifest))
        artifacts.append({"kind": "preview_manifest", "path": preview_manifest_path, "exists": True, "producedThisRun": True, "sha256": sha256_file(preview_manifest_path)})
    status = "pass" if artifacts and not missing_formats else "pilot" if artifacts else "blocked"
    return {
        "backend": "headless_open_format",
        "status": status,
        "stage": "save",
        "artifacts": artifacts,
        "previewManifest": preview_manifest_path,
        "geometryEvidence": geometry_evidence,
        "limitations": limitations,
        "missingFormats": sorted(set(missing_formats)),
        "retryable": False,
    }


def main(argv: list[str] | None = None) -> int:
    """@brief CLI 入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio 无头开放格式写入器")
    parser.add_argument("--input", type=Path, required=True, help="NeutralCadDocument .cadstudio.json")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--formats", nargs="+", default=["cadstudio", "step", "iges", "brep", "stl", "obj", "glb", "dxf", "svg", "pdf", "png"])
    args = parser.parse_args(argv)
    print(json.dumps(export_headless(args.input, args.out_dir, args.formats), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
