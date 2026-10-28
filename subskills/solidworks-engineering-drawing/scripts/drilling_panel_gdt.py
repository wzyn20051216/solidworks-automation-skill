"""
@file drilling_panel_gdt.py
@brief 非标自动化钻孔台面板：孔位阵列识别 + 基准自动推测 + GB/T 位置度 GD&T 自动生成。

面向“一块布满孔的台面板从 3D 自动出图到 SLDDRW”这一极端案例，把最难自动化、也最有价值的
**分析推理**做成纯函数、可离线单测：

1. 孔位规整（detect_hole_patterns）：把散点孔按孔径分组，聚类成栅格/线性阵列，识别节距、
   行列数、原点，并给出规整度证据。
2. 基准自动推测（infer_datums）：按 3-2-1 原则，从包围盒与孔分布推出基准角与
   A（主平面）| B | C（两正交基准边），可选识别定位销孔作为基准孔目标。
3. GD&T 自动给出（generate_gdt）：为每组孔阵列生成 GB/T 1182 / ISO GPS 位置度框
   ⌀t Ⓜ | A | B | C，并给基准 A 加平面度。
4. 出图规划（build_hole_table / build_ordinate_dimensions / build_drawing_spec）：生成孔表、
   从基准原点的坐标标注，并组装成符合本子技能 drawing_spec schema 的规格，交给现有渲染器。

能力等级：分析/规划纯函数离线单测；把 GD&T/孔表/坐标标注真正落到 SLDDRW 的 COM 渲染由本子技能
的专项脚本执行，仍为 pilot，须真机与工程复核。单位统一 mm，坐标系为面板正面 XY。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Hole:
    """@brief 面板上的一个孔（mm）。"""

    id: str
    x: float
    y: float
    diameter: float
    kind: str = "clearance"  # clearance / tapped / dowel / counterbore

    @property
    def diameter_key(self) -> float:
        return round(self.diameter, 1)


@dataclass
class HolePattern:
    """@brief 一组同规格孔的阵列识别结果。"""

    id: str
    kind: str  # grid / linear / individual / cluster
    diameter_mm: float
    hole_kind: str
    count: int
    members: list[str]
    rows: int = 1
    cols: int = 1
    pitch_x_mm: float | None = None
    pitch_y_mm: float | None = None
    origin_mm: tuple[float, float] | None = None
    regular: bool = False
    complete: bool = True
    locations_mm: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class DatumScheme:
    """@brief 3-2-1 基准体系推测结果。"""

    origin_mm: tuple[float, float]
    datums: list[dict[str, Any]]
    primary_axis: str  # "x" 长边方向
    rationale: str
    dowel_candidates: list[str] = field(default_factory=list)


@dataclass
class GdtFrame:
    """@brief 一条几何公差框（feature control frame）。"""

    id: str
    symbol: str  # position / flatness / perpendicularity
    tolerance_mm: float
    material_condition: str | None  # M / L / None
    datums: list[str]
    applies_to: str
    text: str


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _cluster_1d(values: Sequence[float], tol: float) -> list[tuple[float, list[int]]]:
    """@brief 一维贪心聚类，返回 [(中心值, [原始下标...])]，按中心升序。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    clusters: list[tuple[float, list[int]]] = []
    for idx in order:
        value = values[idx]
        if clusters and abs(value - clusters[-1][0]) <= tol:
            center, members = clusters[-1]
            members.append(idx)
            clusters[-1] = (sum(values[i] for i in members) / len(members), members)
        else:
            clusters.append((value, [idx]))
    return clusters


def _uniform(diffs: Sequence[float], tol: float) -> bool:
    """@brief 判断相邻间距是否均匀。"""
    if not diffs:
        return False
    mean = sum(diffs) / len(diffs)
    return all(abs(d - mean) <= tol for d in diffs)


# ---------------------------------------------------------------------------
# 1. 孔位阵列识别
# ---------------------------------------------------------------------------


def detect_hole_patterns(
    holes: Sequence[Hole],
    *,
    cluster_tol_mm: float = 0.5,
    pitch_tol_mm: float = 0.2,
) -> list[HolePattern]:
    """@brief 把孔按孔径分组并识别栅格/线性/离散阵列。

    @param holes 面板孔列表。
    @param cluster_tol_mm 坐标聚类容差。
    @param pitch_tol_mm 判定节距均匀的容差。
    @return 阵列列表，按孔径降序、同径按数量降序稳定排序。
    """
    groups: dict[tuple[float, str], list[Hole]] = {}
    for hole in holes:
        groups.setdefault((hole.diameter_key, hole.kind), []).append(hole)

    patterns: list[HolePattern] = []
    seq = 0
    for diameter, kind in sorted(groups, key=lambda key: (-key[0], key[1])):
        members = groups[(diameter, kind)]
        seq += 1
        pattern = _classify_group(f"P{seq}", diameter, members, cluster_tol_mm, pitch_tol_mm)
        patterns.append(pattern)
    patterns.sort(key=lambda p: (-p.diameter_mm, -p.count))
    return patterns


def _classify_group(pid: str, diameter: float, members: list[Hole], cluster_tol: float, pitch_tol: float) -> HolePattern:
    xs = [h.x for h in members]
    ys = [h.y for h in members]
    ids = [h.id for h in members]
    locations = [(h.x, h.y) for h in members]
    hole_kind = members[0].kind
    count = len(members)
    if count == 1:
        return HolePattern(pid, "individual", diameter, hole_kind, 1, ids, origin_mm=(xs[0], ys[0]), regular=True, locations_mm=locations)

    x_clusters = _cluster_1d(xs, cluster_tol)
    y_clusters = _cluster_1d(ys, cluster_tol)
    cols, rows = len(x_clusters), len(y_clusters)
    x_centers = [c for c, _ in x_clusters]
    y_centers = [c for c, _ in y_clusters]

    # 栅格：行列各 >=2，且占用率高。
    if rows >= 2 and cols >= 2 and count >= max(4, int(0.6 * rows * cols)):
        pitch_x = _mean_pitch(x_centers)
        pitch_y = _mean_pitch(y_centers)
        regular = _uniform(_diffs(x_centers), pitch_tol) and _uniform(_diffs(y_centers), pitch_tol)
        return HolePattern(
            pid, "grid", diameter, hole_kind, count, ids, rows=rows, cols=cols,
            pitch_x_mm=pitch_x, pitch_y_mm=pitch_y, origin_mm=(min(x_centers), min(y_centers)),
            regular=regular, complete=count == rows * cols, locations_mm=locations,
        )
    # 线性阵列：单行或单列且 >=3。
    if rows == 1 and cols >= 3:
        return HolePattern(
            pid, "linear", diameter, hole_kind, count, ids, rows=1, cols=cols,
            pitch_x_mm=_mean_pitch(x_centers), origin_mm=(min(x_centers), y_centers[0]),
            regular=_uniform(_diffs(x_centers), pitch_tol), locations_mm=locations,
        )
    if cols == 1 and rows >= 3:
        return HolePattern(
            pid, "linear", diameter, hole_kind, count, ids, rows=rows, cols=1,
            pitch_y_mm=_mean_pitch(y_centers), origin_mm=(x_centers[0], min(y_centers)),
            regular=_uniform(_diffs(y_centers), pitch_tol), locations_mm=locations,
        )
    # 其余：离散簇。
    return HolePattern(
        pid, "cluster", diameter, hole_kind, count, ids, rows=rows, cols=cols,
        origin_mm=(min(xs), min(ys)), regular=False, locations_mm=locations,
    )


def _diffs(sorted_centers: Sequence[float]) -> list[float]:
    ordered = sorted(sorted_centers)
    return [ordered[i + 1] - ordered[i] for i in range(len(ordered) - 1)]


def _mean_pitch(centers: Sequence[float]) -> float | None:
    diffs = _diffs(centers)
    return sum(diffs) / len(diffs) if diffs else None


# ---------------------------------------------------------------------------
# 2. 基准自动推测（3-2-1）
# ---------------------------------------------------------------------------


def bounding_box(holes: Sequence[Hole], plate: Mapping[str, Any] | None = None) -> tuple[float, float, float, float]:
    """@brief 返回 (xmin, ymin, xmax, ymax)。优先用显式板尺寸，否则用孔范围外扩。"""
    if plate and _finite(plate.get("widthMm")) and _finite(plate.get("heightMm")):
        x0 = _finite(plate.get("originXMm")) or 0.0
        y0 = _finite(plate.get("originYMm")) or 0.0
        return x0, y0, x0 + float(plate["widthMm"]), y0 + float(plate["heightMm"])
    if not holes:
        raise ValueError("无孔且未提供板尺寸，无法确定包围盒")
    xs = [h.x for h in holes]
    ys = [h.y for h in holes]
    margin = 10.0
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def infer_datums(holes: Sequence[Hole], plate: Mapping[str, Any] | None = None) -> DatumScheme:
    """@brief 按 3-2-1 推测基准体系。

    约定：A=主平面（面板正面/大平面）；基准角取包围盒的 (xmin, ymin)；沿长边为 B（第二基准），
    沿短边为 C（第三基准）。若识别到恰好 2 个同规格小孔（疑似定位销/dowel），列为基准孔候选。
    """
    x0, y0, x1, y1 = bounding_box(holes, plate)
    width, height = x1 - x0, y1 - y0
    primary_axis = "x" if width >= height else "y"

    datums = [
        {"id": "A", "type": "plane", "feature": "primary_face", "role": "primary", "text": "A"},
        {
            "id": "B",
            "type": "edge",
            "feature": "long_edge" if primary_axis == "x" else "short_edge",
            "role": "secondary",
            "along": "x" if primary_axis == "x" else "y",
            "at_mm": y0 if primary_axis == "x" else x0,
            "text": "B",
        },
        {
            "id": "C",
            "type": "edge",
            "feature": "short_edge" if primary_axis == "x" else "long_edge",
            "role": "tertiary",
            "along": "y" if primary_axis == "x" else "x",
            "at_mm": x0 if primary_axis == "x" else y0,
            "text": "C",
        },
    ]

    dowel_candidates: list[str] = []
    explicit_dowels = [h for h in holes if h.kind == "dowel"]
    if len(explicit_dowels) == 2:
        dowel_candidates = [explicit_dowels[0].id, explicit_dowels[1].id]
    else:
        by_key: dict[tuple[float, str], list[Hole]] = {}
        for hole in holes:
            by_key.setdefault((hole.diameter_key, hole.kind), []).append(hole)
        for (diameter, _kind), members in by_key.items():
            if len(members) == 2 and diameter <= 8.0:
                dowel_candidates = [members[0].id, members[1].id]
                break

    rationale = (
        f"基准角取包围盒左下角 ({x0:g}, {y0:g})；长边 {max(width, height):g}mm 方向定 B，"
        f"短边 {min(width, height):g}mm 方向定 C；A 为面板主平面。3-2-1 约束。"
    )
    if dowel_candidates:
        rationale += f" 识别到疑似定位销对 {dowel_candidates}，可改用基准孔目标 B/C。"
    return DatumScheme((x0, y0), datums, primary_axis, rationale, dowel_candidates)


# ---------------------------------------------------------------------------
# 3. GD&T 自动生成（GB/T 1182 / ISO GPS）
# ---------------------------------------------------------------------------


def default_gdt_profile() -> dict[str, Any]:
    """@brief 默认公差 profile（mm）。"""
    return {
        "positionToleranceMm": 0.2,
        "dowelPositionToleranceMm": 0.05,
        "flatnessMm": 0.05,
        "materialCondition": "M",  # 间隙孔默认最大实体
        "datumRefs": ["A", "B", "C"],
    }


def _fcf_text(symbol_char: str, tolerance_mm: float, material: str | None, datums: Sequence[str], *, diametral: bool = True) -> str:
    """@brief 组装特征控制框文字，例如 '⌖ ⌀0.2 Ⓜ | A | B | C'。

    @param diametral True 时公差域为圆柱（位置度用 ⌀）；平面度等区域公差为 False，不加 ⌀。
    """
    material_map = {"M": "Ⓜ", "L": "Ⓛ", None: ""}
    mat = material_map.get(material, "")
    zone = "⌀" if diametral else ""
    body = f"{symbol_char} {zone}{tolerance_mm:g}"
    if mat:
        body += f" {mat}"
    if datums:
        body += " | " + " | ".join(datums)
    return body


def generate_gdt(patterns: Sequence[HolePattern], datums: DatumScheme, profile: Mapping[str, Any] | None = None) -> list[GdtFrame]:
    """@brief 为孔阵列生成位置度框，并给基准 A 加平面度。"""
    cfg = dict(default_gdt_profile())
    if profile:
        cfg.update(profile)
    refs = list(cfg["datumRefs"])
    frames: list[GdtFrame] = []

    # 基准 A 平面度。
    frames.append(
        GdtFrame("GDT-A-FLAT", "flatness", float(cfg["flatnessMm"]), None, [], "datum_A_face", _fcf_text("⏥", float(cfg["flatnessMm"]), None, [], diametral=False))
    )

    dowels = set(datums.dowel_candidates)
    for pattern in patterns:
        if pattern.kind not in {"grid", "linear", "individual", "cluster"}:
            continue
        is_dowel = pattern.hole_kind == "dowel" or set(pattern.members) <= dowels and pattern.count == 2 and len(dowels) == 2
        tol = float(cfg["dowelPositionToleranceMm"] if is_dowel else cfg["positionToleranceMm"])
        material = None if is_dowel else cfg["materialCondition"]  # 定位销孔通常 RFS
        frames.append(
            GdtFrame(
                f"GDT-{pattern.id}-POS",
                "position",
                tol,
                material,
                refs,
                pattern.id,
                _fcf_text("⌖", tol, material, refs),
            )
        )
    return frames


# ---------------------------------------------------------------------------
# 4. 孔表与坐标标注
# ---------------------------------------------------------------------------


def build_hole_table(patterns: Sequence[HolePattern], datums: DatumScheme) -> list[dict[str, Any]]:
    """@brief 生成孔表行：标签、规格、数量、阵列描述、基准原点相对信息。"""
    x0, y0 = datums.origin_mm
    rows: list[dict[str, Any]] = []
    tag_index = 0
    for pattern in patterns:
        tag_index += 1
        tag = chr(ord("A") + (tag_index - 1) % 26)
        spec = f"⌀{pattern.diameter_mm:g}"
        if pattern.hole_kind == "tapped":
            spec = f"M{pattern.diameter_mm:g}"
        description = f"{pattern.count}×{spec}"
        if pattern.kind == "grid":
            description += f"，{pattern.rows}×{pattern.cols} 栅格，节距 {pattern.pitch_x_mm:g}×{pattern.pitch_y_mm:g}"
        elif pattern.kind == "linear":
            pitch = pattern.pitch_x_mm or pattern.pitch_y_mm
            description += f"，{pattern.count} 孔线性，节距 {pitch:g}" if pitch else ""
        origin = pattern.origin_mm or (x0, y0)
        rows.append(
            {
                "tag": tag,
                "specification": spec,
                "quantity": pattern.count,
                "pattern": pattern.kind,
                "description": description,
                "origin_from_datum_mm": [round(origin[0] - x0, 4), round(origin[1] - y0, 4)],
                "regular": pattern.regular,
            }
        )
    return rows


def build_ordinate_dimensions(holes: Sequence[Hole], datums: DatumScheme, *, tol_mm: float = 0.05) -> dict[str, Any]:
    """@brief 从基准原点生成坐标（纵坐标）标注：唯一 X、Y 基线值。"""
    x0, y0 = datums.origin_mm
    xs = sorted({round(h.x - x0, 3) for h in holes})
    ys = sorted({round(h.y - y0, 3) for h in holes})
    return {
        "origin_mm": [x0, y0],
        "x_ordinates_mm": xs,
        "y_ordinates_mm": ys,
        "cluster_tol_mm": tol_mm,
    }


# ---------------------------------------------------------------------------
# 5. 汇总与 drawing_spec 生成
# ---------------------------------------------------------------------------


def analyze_drilling_panel(
    holes: Sequence[Hole],
    *,
    plate: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    cluster_tol_mm: float = 0.5,
) -> dict[str, Any]:
    """@brief 一站式分析：阵列识别 + 基准推测 + GD&T + 孔表 + 坐标标注。"""
    if not holes:
        raise ValueError("孔列表为空")
    patterns = detect_hole_patterns(holes, cluster_tol_mm=cluster_tol_mm)
    datums = infer_datums(holes, plate)
    gdt = generate_gdt(patterns, datums, profile)
    hole_table = build_hole_table(patterns, datums)
    ordinates = build_ordinate_dimensions(holes, datums)
    x0, y0, x1, y1 = bounding_box(holes, plate)
    return {
        "schema": "cadstudio.drilling-panel-analysis",
        "version": "1.0",
        "units": "mm",
        "holeCount": len(holes),
        "boundingBoxMm": [x0, y0, x1, y1],
        "patterns": [_pattern_dict(p) for p in patterns],
        "datums": {
            "originMm": list(datums.origin_mm),
            "primaryAxis": datums.primary_axis,
            "rationale": datums.rationale,
            "datums": datums.datums,
            "dowelCandidates": datums.dowel_candidates,
        },
        "gdt": [_gdt_dict(g) for g in gdt],
        "holeTable": hole_table,
        "ordinateDimensions": ordinates,
        "reviewRequired": True,
    }


def _pattern_dict(p: HolePattern) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "diameterMm": p.diameter_mm,
        "holeKind": p.hole_kind,
        "count": p.count,
        "rows": p.rows,
        "cols": p.cols,
        "pitchXMm": p.pitch_x_mm,
        "pitchYMm": p.pitch_y_mm,
        "originMm": list(p.origin_mm) if p.origin_mm else None,
        "regular": p.regular,
        "complete": p.complete,
        "members": p.members,
        "locationsMm": [[round(x, 4), round(y, 4)] for x, y in p.locations_mm],
    }


def _gdt_dict(g: GdtFrame) -> dict[str, Any]:
    return {
        "id": g.id,
        "symbol": g.symbol,
        "toleranceMm": g.tolerance_mm,
        "materialCondition": g.material_condition,
        "datums": g.datums,
        "appliesTo": g.applies_to,
        "text": g.text,
    }


_PAPER_SIZES = [("A4", 297.0, 210.0), ("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0)]


def _pick_paper_size(width_mm: float, height_mm: float, *, margin: float = 1.4) -> str:
    """@brief 按模型外形选最小可容纳的 ISO 图幅。"""
    long_side = max(width_mm, height_mm) * margin
    short_side = min(width_mm, height_mm) * margin
    for name, w, h in _PAPER_SIZES:
        if long_side <= w and short_side <= h:
            return name
    return "A0"


def build_drawing_spec(
    analysis: Mapping[str, Any],
    *,
    source_model: str,
    thickness_mm: float = 20.0,
    view_name: str = "front",
    standard: str = "GB_T",
) -> dict[str, Any]:
    """@brief 把分析结果组装成符合本子技能 schema 的 drawing_spec。

    面板正面作为主视图（schema 要求存在 front），附 A-A 剖视；GD&T/基准/孔标注放入
    professionalAnnotations，孔阵列进 holeRequirements，坐标基线进 requiredDimensions。
    真正把这些实体落到 SLDDRW 仍由本子技能的专项 COM 脚本执行（pilot）。
    """
    patterns = analysis.get("patterns", [])
    datum_defs = analysis.get("datums", {}).get("datums", [])
    hole_reqs = []
    hole_callouts = []
    center_marks_count = 0
    for pattern, table_row in zip(patterns, analysis.get("holeTable", [])):
        locations = pattern.get("locationsMm") or _pattern_locations(pattern)
        hole_reqs.append(
            {
                "id": pattern["id"],
                "specification": table_row["specification"],
                "count": pattern["count"],
                "locationsMm": locations,
                "view": view_name,
                "datum": "A",
                "pattern": pattern["kind"],
            }
        )
        hole_callouts.append({"id": f"HC-{pattern['id']}", "view": view_name, "text": table_row["description"]})
        center_marks_count += pattern["count"]

    datums = [{"id": f"DAT-{d['id']}", "view": view_name, "text": d["text"]} for d in datum_defs]
    gtols = [{"id": g["id"], "view": view_name, "text": g["text"]} for g in analysis.get("gdt", [])]

    required_dimensions = []
    ordinates = analysis.get("ordinateDimensions", {})
    for axis, key in (("X", "x_ordinates_mm"), ("Y", "y_ordinates_mm")):
        for i, value in enumerate(ordinates.get(key, [])):
            required_dimensions.append(
                {"id": f"ORD-{axis}{i}", "kind": "linear", "view": view_name, "valueMm": float(value), "datum": "A"}
            )
    for g in analysis.get("gdt", []):
        required_dimensions.append({"id": f"DIM-{g['id']}", "kind": "gdt", "view": view_name, "text": g["text"], "datum": "A"})

    bbox = analysis.get("boundingBoxMm", [0.0, 0.0, 100.0, 100.0])
    width_mm = float(bbox[2] - bbox[0])
    height_mm = float(bbox[3] - bbox[1])

    spec: dict[str, Any] = {
        "schemaVersion": "1.0",
        "sourceModel": source_model,
        "documentType": "part",
        "standard": standard,
        "projection": "first_angle",
        "paperSize": _pick_paper_size(width_mm, height_mm),
        "modelSizeMm": [round(width_mm, 3), round(height_mm, 3), round(float(thickness_mm), 3)],
        "views": {view_name: {}, "sections": [{"id": "A-A", "parent": view_name}]},
        "insertModelDimensions": False,
        "holeRequirements": hole_reqs,
        "requiredDimensions": required_dimensions,
        "professionalAnnotations": {
            "centerMarks": [{"id": "CM-HOLES", "view": view_name, "count": max(1, center_marks_count), "targets": ["holes"]}],
            "holeCallouts": hole_callouts,
            "datums": datums,
            "geometricTolerances": gtols,
        },
        "notes": _technical_notes(analysis),
        "outputs": {"slddrw": True, "pdf": True, "report": True},
    }
    if view_name != "front":
        spec["views"]["front"] = {}
    return spec


def _pattern_locations(pattern: Mapping[str, Any]) -> list[list[float]]:
    """@brief 由原点/节距还原栅格/线性阵列的孔位（近似，供 spec 占位；渲染以真实模型为准）。"""
    origin = pattern.get("originMm")
    if not origin:
        return [[0.0, 0.0]]
    if pattern["kind"] == "grid" and pattern.get("pitchXMm") and pattern.get("pitchYMm"):
        return [
            [origin[0] + c * pattern["pitchXMm"], origin[1] + r * pattern["pitchYMm"]]
            for r in range(pattern["rows"])
            for c in range(pattern["cols"])
        ][: pattern["count"]]
    if pattern["kind"] == "linear":
        pitch = pattern.get("pitchXMm") or pattern.get("pitchYMm") or 0.0
        horizontal = bool(pattern.get("pitchXMm"))
        return [
            [origin[0] + (i * pitch if horizontal else 0.0), origin[1] + (0.0 if horizontal else i * pitch)]
            for i in range(pattern["count"])
        ]
    return [list(origin)]


def _technical_notes(analysis: Mapping[str, Any]) -> list[str]:
    datum = analysis.get("datums", {})
    notes = [
        "未注公差按 GB/T 1804-m。",
        f"位置度基准体系 {'|'.join(d['id'] for d in datum.get('datums', []))}，基准原点为面板基准角。",
        "所有孔位以基准 A、B、C 为参照，按孔表与坐标标注加工。",
    ]
    if datum.get("dowelCandidates"):
        notes.append("定位销孔按基准孔目标控制，位置度从严。")
    return notes


# ---------------------------------------------------------------------------
# 输入适配：中性文档 -> 孔列表
# ---------------------------------------------------------------------------


def holes_from_neutral_document(document: Mapping[str, Any]) -> list[Hole]:
    """@brief 从 NeutralCadDocument 抽取孔（features[type=hole]）。"""
    units = str(document.get("units") or "mm").strip().lower()
    factor = UNIT_TO_MM.get(units)
    if factor is None:
        raise ValueError(f"不支持单位 {units}")
    holes: list[Hole] = []
    for feature in document.get("features", []):
        if not isinstance(feature, Mapping) or str(feature.get("type") or "").lower() != "hole":
            continue
        params = feature.get("parameters") if isinstance(feature.get("parameters"), Mapping) else {}
        x = _finite(params.get("x"))
        y = _finite(params.get("y"))
        diameter = _finite(params.get("diameter"))
        if diameter is None and _finite(params.get("radius")) is not None:
            diameter = _finite(params.get("radius")) * 2.0
        if x is None or y is None or diameter is None:
            continue
        holes.append(
            Hole(
                id=str(feature.get("id") or f"H{len(holes) + 1}"),
                x=x * factor,
                y=y * factor,
                diameter=diameter * factor,
                kind=str(params.get("holeKind") or params.get("kind") or "clearance"),
            )
        )
    return holes


# ---------------------------------------------------------------------------
# 打通真机 3D -> 分析：从活动 SolidWorks 模型抽取孔位快照（pilot）
# ---------------------------------------------------------------------------

_AXIS_IN_PLANE = {0: (1, 2), 1: (0, 2), 2: (0, 1)}
_AXIS_NAME = {0: "x", 1: "y", 2: "z"}


def _thinnest_axis(envelope: Mapping[str, Any]) -> int:
    """@brief 由包围盒最薄方向判定面板法向轴（0=x,1=y,2=z）。"""
    sizes = [
        _finite(envelope.get("length")) or 0.0,
        _finite(envelope.get("width")) or 0.0,
        _finite(envelope.get("height")) or 0.0,
    ]
    return min(range(3), key=lambda i: sizes[i])


def holes_from_geometry_measurements(
    measurements: Mapping[str, Any],
    *,
    part_box_mm: Sequence[float] | None = None,
    normal_axis: int | None = None,
    dedupe_tol_mm: float = 0.5,
    default_kind: str = "clearance",
    axis_parallel_tol: float = 0.02,
) -> dict[str, Any]:
    """@brief 把 sw_review.collect_geometry_measurements 的内部孔壁转成面板孔 + 板尺寸。

    这是“真机 3D -> 分析”的纯函数适配层，可离线单测。输入是已验证的 B-Rep 证据
    （envelope_mm + 内部圆柱孔壁 holes[{diameter_mm, position_mm, axis}]）：

    - 面板法向取包围盒最薄方向；只保留轴向与法向平行的圆柱（滤掉侧壁/斜孔）。
    - 法向坐标投影掉，得到孔在面板平面的 (x, y)。
    - 同一 (x, y) 的多段孔壁（沉孔/阶梯孔叠层）合并为一孔，取最小直径为功能孔径。
    - 孔型无法从纯几何判定，默认 clearance；定位销识别交给下游 infer_datums。

    @return {"holes": [Hole], "plate": {...}, "warnings": [...]}。
    """
    envelope = measurements.get("envelope_mm") if isinstance(measurements.get("envelope_mm"), Mapping) else {}
    axis = normal_axis if normal_axis is not None else (_thinnest_axis(envelope) if envelope else 2)
    u_index, v_index = _AXIS_IN_PLANE[axis]
    warnings: list[str] = []

    raw: list[tuple[float, float, float]] = []
    for record in measurements.get("holes", []):
        if not isinstance(record, Mapping):
            continue
        position = record.get("position_mm")
        diameter = _finite(record.get("diameter_mm"))
        hole_axis = record.get("axis")
        if not isinstance(position, (list, tuple)) or len(position) < 3 or diameter is None:
            continue
        if isinstance(hole_axis, (list, tuple)) and len(hole_axis) >= 3:
            if abs(abs(float(hole_axis[axis])) - 1.0) > axis_parallel_tol:
                continue  # 轴向不与面板法向平行，非通面板孔
        raw.append((float(position[u_index]), float(position[v_index]), diameter))

    # 合并同位置的多段孔壁，取最小直径。
    merged: list[list[float]] = []
    for x, y, diameter in raw:
        for slot in merged:
            if abs(slot[0] - x) <= dedupe_tol_mm and abs(slot[1] - y) <= dedupe_tol_mm:
                slot[2] = min(slot[2], diameter)
                break
        else:
            merged.append([x, y, diameter])

    holes = [Hole(id=f"H{i + 1}", x=round(x, 4), y=round(y, 4), diameter=round(d, 4), kind=default_kind) for i, (x, y, d) in enumerate(merged)]

    plate = _plate_from_box(part_box_mm, envelope, axis, holes, warnings)
    if not holes:
        warnings.append("未从模型抽取到与面板法向平行的内部孔；请确认模型为带孔面板且法向正确")
    return {"holes": holes, "plate": plate, "normalAxis": _AXIS_NAME[axis], "warnings": warnings}


def _plate_from_box(part_box_mm, envelope, axis, holes, warnings) -> dict[str, Any]:
    """@brief 由 GetPartBox 精确尺寸或孔范围推面板宽/高/厚与基准原点。"""
    u_index, v_index = _AXIS_IN_PLANE[axis]
    thickness = None
    if isinstance(envelope, Mapping):
        thickness = [envelope.get("length"), envelope.get("width"), envelope.get("height")][axis]
        thickness = _finite(thickness)
    if part_box_mm and len(part_box_mm) >= 6:
        lo = [float(part_box_mm[i]) for i in range(3)]
        hi = [float(part_box_mm[i + 3]) for i in range(3)]
        return {
            "widthMm": round(hi[u_index] - lo[u_index], 4),
            "heightMm": round(hi[v_index] - lo[v_index], 4),
            "thicknessMm": round(hi[axis] - lo[axis], 4),
            "originXMm": round(lo[u_index], 4),
            "originYMm": round(lo[v_index], 4),
        }
    if holes:
        xs = [h.x for h in holes]
        ys = [h.y for h in holes]
        margin = 10.0
        warnings.append("未提供 GetPartBox 角点，按孔范围外扩 10mm 估算板尺寸")
        return {
            "widthMm": round(max(xs) - min(xs) + 2 * margin, 4),
            "heightMm": round(max(ys) - min(ys) + 2 * margin, 4),
            "thicknessMm": round(thickness, 4) if thickness else 20.0,
            "originXMm": round(min(xs) - margin, 4),
            "originYMm": round(min(ys) - margin, 4),
        }
    return {"widthMm": 100.0, "heightMm": 100.0, "thicknessMm": round(thickness, 4) if thickness else 20.0, "originXMm": 0.0, "originYMm": 0.0}


def snapshot_holes_from_model(model, **adapter_kwargs) -> dict[str, Any]:
    """@brief pilot：从活动 SolidWorks 零件模型抽取孔位快照（holes + plate）。

    复用根技能已验证的 `sw_review.collect_geometry_measurements`（GetPartBox + 内部圆柱孔壁，
    FaceInSurfaceSense 已滤除外圆柱/凸台/圆角），再走纯函数适配层。COM 读取失败不抛出。
    """
    import sys as _sys
    from pathlib import Path as _Path

    parent_scripts = str(_Path(__file__).resolve().parents[3] / "scripts")
    if parent_scripts not in _sys.path:
        _sys.path.insert(0, parent_scripts)
    from sw_review import collect_geometry_measurements  # noqa: E402
    from sw_connect import get_com_member  # noqa: E402

    measurements = collect_geometry_measurements(model)
    part_box = None
    try:
        box = list(get_com_member(model, "GetPartBox", True) or [])
        if len(box) >= 6:
            part_box = [float(v) * 1000.0 for v in box[:6]]
    except Exception:  # noqa: BLE001
        part_box = None
    result = holes_from_geometry_measurements(measurements, part_box_mm=part_box, **adapter_kwargs)
    result["measurementErrors"] = measurements.get("errors", [])
    return result


def analyze_model(model, *, profile: Mapping[str, Any] | None = None, **adapter_kwargs) -> dict[str, Any]:
    """@brief pilot：一键打通真机 3D -> 孔位规整/基准/GD&T -> drawing_spec。"""
    snapshot = snapshot_holes_from_model(model, **adapter_kwargs)
    holes = snapshot["holes"]
    if not holes:
        return {"status": "blocked", "reason": "未抽取到面板孔", "snapshot": snapshot}
    plate = snapshot["plate"]
    analysis = analyze_drilling_panel(holes, plate=plate, profile=profile)
    spec = build_drawing_spec(analysis, source_model="panel.SLDPRT", thickness_mm=plate.get("thicknessMm", 20.0))
    return {"status": "ok", "snapshot": snapshot, "analysis": analysis, "drawingSpec": spec}


def main(argv: Sequence[str] | None = None) -> int:
    """@brief 命令行入口：读中性文档，输出分析 + drawing_spec。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="非标钻孔面板：孔位规整 + 基准推测 + GD&T + drawing_spec 生成。")
    parser.add_argument("input", nargs="?", help="NeutralCadDocument (.cadstudio.json) 路径。")
    parser.add_argument("--from-model", help="打通真机：打开该 SLDPRT 路径，直接从 3D 抽取孔位快照（pilot）。")
    parser.add_argument("--source-model", default="panel.SLDPRT", help="drawing_spec.sourceModel。")
    parser.add_argument("--analysis-out", help="分析 JSON 输出路径。")
    parser.add_argument("--spec-out", help="drawing_spec JSON 输出路径。")
    args = parser.parse_args(argv)

    if args.from_model:
        import sys as _sys
        from pathlib import Path as _Path

        _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / "scripts"))
        from sw_session import SolidWorksSession  # noqa: E402

        session = SolidWorksSession(visible=True)
        model = session.open(args.from_model)
        if model is None:
            raise SystemExit(f"无法打开模型: {args.from_model}")
        result = analyze_model(model)
        analysis = result.get("analysis")
        spec = result.get("drawingSpec")
        if analysis is None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
    else:
        if not args.input:
            parser.error("需要提供 NeutralCadDocument 路径，或使用 --from-model 从真机抽取")
        document = json.loads(Path(args.input).read_text(encoding="utf-8"))
        holes = holes_from_neutral_document(document)
        plate = document.get("metadata", {}).get("plate") if isinstance(document.get("metadata"), Mapping) else None
        analysis = analyze_drilling_panel(holes, plate=plate)
        thickness = 20.0
        if isinstance(plate, Mapping) and _finite(plate.get("thicknessMm")) is not None:
            thickness = float(plate["thicknessMm"])
        spec = build_drawing_spec(analysis, source_model=args.source_model, thickness_mm=thickness)

    if args.analysis_out:
        Path(args.analysis_out).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.spec_out:
        Path(args.spec_out).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"analysis": analysis, "drawingSpec": spec}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
