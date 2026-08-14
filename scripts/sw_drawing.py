"""
SolidWorks 工程图操作工具
"""
import math
import re
from fractions import Fraction
from pathlib import Path

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import create_empty_dispatch_variant, get_com_member
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import create_empty_dispatch_variant, get_com_member

pythoncom, _win32com, VARIANT = import_com_dependencies()


PAPER_SIZES = {
    "A4": {"code": 5, "width_m": 0.297, "height_m": 0.210},
    "A3": {"code": 6, "width_m": 0.420, "height_m": 0.297},
    "A2": {"code": 7, "width_m": 0.594, "height_m": 0.420},
    "A1": {"code": 8, "width_m": 0.841, "height_m": 0.594},
    "A0": {"code": 9, "width_m": 1.189, "height_m": 0.841},
}

STANDARD_DRAWING_SCALES = (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01)

# SolidWorks.Interop.swconst.swAlignDimensionType_e（SW2026 Interop 反射确认）。
ALIGN_DIMENSION_TYPES = {
    "auto_arrange": 0,
    "space_evenly": 1,
    "colinear": 2,
    "stagger": 3,
    "top_align_text": 4,
    "bottom_align_text": 5,
    "left_align_text": 6,
    "right_align_text": 7,
}


def _safe_member(obj, name, *args, default=None):
    """@brief 读取工程图 COM 成员，失败时返回默认值。"""
    if obj is None:
        return default
    try:
        value = get_com_member(obj, name, *args)
        return default if value is None else value
    except Exception:
        return default


def _as_sequence(value):
    """@brief 统一 COM 数组、元组和单对象返回值。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _normalise_box(value):
    """@brief 将 COM Outline/GetBox 数组统一为二维边界框。"""
    if isinstance(value, dict) and {"left", "bottom", "right", "top"} <= set(value):
        try:
            x1, y1, x2, y2 = (float(value[key]) for key in ("left", "bottom", "right", "top"))
        except (TypeError, ValueError):
            return None
        return {"left": min(x1, x2), "bottom": min(y1, y2), "right": max(x1, x2), "top": max(y1, y2)}
    values = _as_sequence(value)
    try:
        if len(values) >= 6:
            x1, y1, x2, y2 = float(values[0]), float(values[1]), float(values[3]), float(values[4])
        elif len(values) >= 4:
            x1, y1, x2, y2 = map(float, values[:4])
        else:
            return None
    except (TypeError, ValueError):
        return None
    return {
        "left": min(x1, x2),
        "bottom": min(y1, y2),
        "right": max(x1, x2),
        "top": max(y1, y2),
    }


def _annotation_box(owner):
    """@brief 读取尺寸、注释或表格注解的二维包围盒。"""
    annotation = _safe_member(owner, "GetAnnotation") or owner
    return _normalise_box(_safe_member(annotation, "GetBox"))


def _view_display_dimensions(view):
    """@brief 兼容数组接口与链式接口，返回视图中的真实 DisplayDimension。"""
    dimensions = _as_sequence(_safe_member(view, "GetDisplayDimensions", default=[]))
    if dimensions:
        return dimensions
    current = _safe_member(view, "GetFirstDisplayDimension5") or _safe_member(view, "GetFirstDisplayDimension")
    while current is not None:
        dimensions.append(current)
        current = _safe_member(view, "GetNextDisplayDimension", current)
    return dimensions


def auto_arrange_drawing_dimensions(drawing_model, *, spacing_m=0.01, mode="auto_arrange") -> dict:
    """@brief 使用 SolidWorks 官方 AlignDimensions 对每个视图的尺寸自动排列。

    该接口只负责 SolidWorks 自身的尺寸布局，不提供尺寸文字包围盒，也不能证明最终
    图面无重叠。调用后仍必须导出 PDF/BMP 做视觉复核。
    """
    spacing, spacing_valid = _finite_positive(spacing_m, 0.01)
    if not spacing_valid or spacing > 0.1:
        raise ValueError("spacing_m 必须是 (0, 0.1] 米范围内的有限数值。")
    if mode not in ALIGN_DIMENSION_TYPES:
        raise ValueError(f"未知尺寸排列模式: {mode}")
    extension = _safe_member(drawing_model, "Extension")
    if extension is None or not hasattr(extension, "AlignDimensions"):
        return {
            "status": "blocked",
            "stage": "arrange",
            "method": "IModelDocExtension.AlignDimensions",
            "mode": mode,
            "spacing_m": spacing,
            "views": [],
            "selected_dimension_count": 0,
            "manual_review_required": True,
            "retryable": False,
            "error_code": "DRAWING_ALIGN_DIMENSIONS_API_UNAVAILABLE",
        }

    results = []
    total_selected = 0
    sheets = _as_sequence(_safe_member(drawing_model, "GetSheetNames", default=[]))
    for sheet_name in sheets or [""]:
        sheet = _safe_member(drawing_model, "GetSheet", sheet_name) or _safe_member(drawing_model, "GetCurrentSheet")
        for view in _as_sequence(_safe_member(sheet, "GetViews", default=[])):
            dimensions = _view_display_dimensions(view)
            _safe_member(drawing_model, "ClearSelection2", True)
            selected = 0
            for dimension in dimensions:
                annotation = _safe_member(dimension, "GetAnnotation")
                if annotation is None:
                    continue
                selected_ok = _safe_member(annotation, "Select2", selected > 0, 0, default=False)
                if not selected_ok:
                    selected_ok = _safe_member(annotation, "Select", selected > 0, default=False)
                if selected_ok:
                    selected += 1
            attempted = selected >= 2
            aligned = False
            error = None
            if attempted:
                try:
                    aligned = bool(get_com_member(extension, "AlignDimensions", ALIGN_DIMENSION_TYPES[mode], spacing))
                except Exception as exc:
                    error = str(exc)
            results.append({
                "sheet": str(sheet_name),
                "view": str(_safe_member(view, "Name", default="") or ""),
                "dimension_count": len(dimensions),
                "selected_count": selected,
                "attempted": attempted,
                "aligned": aligned,
                "error": error,
            })
            total_selected += selected
    _safe_member(drawing_model, "ClearSelection2", True)
    _safe_member(drawing_model, "ForceRebuild3", False)
    _safe_member(drawing_model, "GraphicsRedraw2")
    attempted_results = [item for item in results if item["attempted"]]
    failed_results = [item for item in attempted_results if not item["aligned"]]
    if not attempted_results:
        status = "review_required"
        error_code = "DRAWING_ALIGN_DIMENSIONS_NOT_ENOUGH_PER_VIEW"
    elif failed_results:
        status = "review_required"
        error_code = "DRAWING_ALIGN_DIMENSIONS_PARTIAL"
    else:
        status = "pass"
        error_code = None
    return {
        "status": status,
        "stage": "arrange",
        "method": "IModelDocExtension.AlignDimensions",
        "mode": mode,
        "enum_value": ALIGN_DIMENSION_TYPES[mode],
        "spacing_m": spacing,
        "views": results,
        "selected_dimension_count": total_selected,
        "aligned_view_count": sum(1 for item in results if item["aligned"]),
        "manual_review_required": True,
        "retryable": bool(failed_results),
        "error_code": error_code,
        "limitations": ["官方排列接口不返回文字包围盒；排列后仍需 PDF/BMP 目视复核。"],
    }


def _finite_positive(value, default):
    """@brief 将 COM 数值转成有限正数，否则使用保守默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default), False
    if not math.isfinite(number) or number <= 0:
        return float(default), False
    return number, True


def _dimension_text_evidence(display_dimension) -> dict:
    """@brief 收集尺寸文字片段；不伪造 SolidWorks 最终格式化文本。"""
    parts = []
    for index, label in ((0, "all"), (1, "prefix"), (2, "suffix"), (3, "callout_above"), (4, "callout_below")):
        value = str(_safe_member(display_dimension, "GetText", index, default="") or "")
        if value:
            parts.append({"index": index, "kind": label, "text": value})
    all_text = next((item["text"] for item in parts if item["kind"] == "all"), "")
    if all_text:
        lines = all_text.splitlines() or [all_text]
        source = "display_dimension_get_text_all"
        rendered_value_available = True
    else:
        explicit = [item["text"] for item in parts if item["kind"] != "all"]
        # GetText() 在 SW2026 常只返回用户前后缀，不返回格式化后的主尺寸值。
        # 用 8 个等宽字符作为主值占位，避免把空字符串估成零宽度。
        lines = ["".join(explicit) + "0000.000"]
        source = "explicit_parts_plus_conservative_value_placeholder" if explicit else "conservative_value_placeholder"
        rendered_value_available = False
    return {
        "parts": parts,
        "estimation_lines": lines,
        "source": source,
        "rendered_value_available": rendered_value_available,
    }


def estimate_dimension_text_box(display_dimension, *, padding_m=None) -> dict:
    """@brief 用 IAnnotation 锚点和 ITextFormat 保守估算尺寸文字边界。

    SW2026 没有尺寸文字的原生 bounding-box API。本函数输出任意旋转文字都能
    被覆盖的轴对齐外接方框，并明确标记 ``source=estimated``；不能作为原生几何证据。
    """
    annotation = _safe_member(display_dimension, "GetAnnotation")
    position = _as_sequence(_safe_member(annotation, "GetPosition", default=[]))
    try:
        x, y = float(position[0]), float(position[1])
        position_available = math.isfinite(x) and math.isfinite(y)
    except (IndexError, TypeError, ValueError):
        x = y = 0.0
        position_available = False

    text_format = _safe_member(annotation, "GetTextFormat", 0)
    format_source = "IAnnotation.GetTextFormat(0)"
    if text_format is None:
        text_format = _safe_member(display_dimension, "GetTextFormat")
        format_source = "IDisplayDimension.GetTextFormat()"
    char_height, char_height_available = _finite_positive(
        _safe_member(text_format, "CharHeight"),
        0.0035,
    )
    width_factor, width_factor_available = _finite_positive(
        _safe_member(text_format, "WidthFactor"),
        1.0,
    )
    spacing_factor, spacing_factor_available = _finite_positive(
        _safe_member(text_format, "CharSpacingFactor"),
        1.0,
    )
    text = _dimension_text_evidence(display_dimension)
    lines = text["estimation_lines"] or ["0000.000"]

    def line_units(line):
        """@brief 估算单行字宽；中文和全角字符按一个字高计。"""
        units = 0.0
        for character in line or " ":
            units += 1.0 if ord(character) > 0xFF else 0.62
        return max(units, 0.62)

    max_units = max(line_units(line) for line in lines)
    line_count = max(1, len(lines))
    estimated_width = max_units * char_height * width_factor * spacing_factor
    estimated_height = line_count * char_height * 1.25
    padding = max(0.001, char_height * 0.4) if padding_m is None else max(0.0, float(padding_m))
    # 尺寸文字角度未由 API 暴露；使用矩形对角线作为任意旋转下的方形包络。
    half_extent = math.hypot(estimated_width, estimated_height) / 2.0 + padding
    box = None
    if position_available:
        box = {
            "left": x - half_extent,
            "bottom": y - half_extent,
            "right": x + half_extent,
            "top": y + half_extent,
        }

    available_fields = sum((position_available, char_height_available, width_factor_available, spacing_factor_available))
    if position_available and available_fields == 4 and text["rendered_value_available"]:
        confidence = "medium"
    elif position_available:
        confidence = "low"
    else:
        confidence = "unavailable"
    return {
        "box": box,
        "source": "estimated",
        "confidence": confidence,
        "method": "annotation_position_text_format_arbitrary_rotation_envelope",
        "native_bounding_box_available": False,
        "position_m": [x, y] if position_available else None,
        "text_evidence": text,
        "text_format": {
            "source": format_source if text_format is not None else "conservative_defaults",
            "char_height_m": char_height,
            "width_factor": width_factor,
            "char_spacing_factor": spacing_factor,
            "char_height_available": char_height_available,
            "width_factor_available": width_factor_available,
            "char_spacing_factor_available": spacing_factor_available,
        },
        "estimated_unrotated_size_m": {"width": estimated_width, "height": estimated_height},
        "padding_m": padding,
        "orientation_assumption": "unknown_angle_conservative_square_envelope",
        "limitations": [
            "SolidWorks 2026 IAnnotation 不提供尺寸文字原生包围盒",
            "主尺寸格式化值可能不由 GetText 返回，缺失时使用保守占位宽度",
            "估算只能用于碰撞风险筛查，最终交付仍需 PDF/BMP 目视复核",
        ],
    }


def select_drawing_template(candidates, *, paper_size="A3", require_gbt=True) -> dict:
    """@brief 从本机候选中选择图幅匹配且具有 GB/T 标识的图框模板。

    仅把文件名和扩展名作为候选证据，不把命名匹配宣称为模板内容已合规。
    """
    paper_size = str(paper_size).upper()
    if paper_size not in PAPER_SIZES:
        raise ValueError(f"不支持的图幅: {paper_size}")
    inspected = []
    for raw_path in candidates or []:
        path = Path(raw_path).expanduser().resolve()
        name = path.stem.casefold()
        compact_name = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", name)
        is_format = path.suffix.casefold() == ".slddrt"
        paper_match = paper_size.casefold() in name
        gbt_match = (
            "gbt" in compact_name
            or "国标" in compact_name
            or bool(re.search(r"(?:^|[^a-z0-9])gb(?:t)?(?:[^a-z0-9]|$)", name, re.IGNORECASE))
        )
        path_text = str(path).casefold()
        localized_candidate = any(token in path_text for token in ("chinese-simplified", "chinese_simplified", "简体中文"))
        score = int(path.is_file()) * 8 + int(is_format) * 4 + int(paper_match) * 2 + int(gbt_match) + int(localized_candidate) * 2
        inspected.append({
            "path": str(path),
            "exists": path.is_file(),
            "is_sheet_format": is_format,
            "paper_match": paper_match,
            "gbt_candidate": gbt_match,
            "localized_candidate": localized_candidate,
            "score": score,
        })
    eligible = [item for item in inspected if item["exists"] and item["is_sheet_format"] and item["paper_match"]]
    if require_gbt:
        eligible = [item for item in eligible if item["gbt_candidate"]]
    selected = max(eligible, key=lambda item: (item["score"], item["path"].casefold()), default=None)
    return {
        "status": "pass" if selected else "blocked",
        "paper_size": paper_size,
        "selected": selected["path"] if selected else None,
        "candidates": inspected,
        "gbt_content_verified": False,
        "manual_review_required": True,
        "error_code": None if selected else "DRAWING_GBT_TEMPLATE_MISSING" if require_gbt else "DRAWING_TEMPLATE_MISSING",
    }


def plan_standard_view_layout(
    model_size_m,
    *,
    paper_size="A3",
    margin_m=0.012,
    gap_m=0.018,
    title_block_width_m=0.180,
    title_block_height_m=0.055,
) -> dict:
    """@brief 为第三角三视图计算不会侵入标题栏的自适应布局。"""
    paper_size = str(paper_size).upper()
    spec = PAPER_SIZES.get(paper_size)
    if spec is None:
        raise ValueError(f"不支持的图幅: {paper_size}")
    try:
        width, height, depth = (float(item) for item in model_size_m)
    except (TypeError, ValueError) as exc:
        raise ValueError("model_size_m 必须包含三个米制外形尺寸") from exc
    if min(width, height, depth) <= 0 or not all(math.isfinite(item) for item in (width, height, depth)):
        raise ValueError("模型外形尺寸必须为有限正数")

    sheet_width = spec["width_m"]
    sheet_height = spec["height_m"]
    working_left = margin_m
    working_bottom = margin_m + title_block_height_m + gap_m
    working_right = sheet_width - margin_m
    working_top = sheet_height - margin_m
    available_width = working_right - working_left
    available_height = working_top - working_bottom
    raw_scale = min(
        (available_width - gap_m) / (width + depth),
        (available_height - gap_m) / (height + depth),
    )
    if raw_scale <= 0:
        return {
            "status": "blocked",
            "paper_size": paper_size,
            "sheet": {"width_m": sheet_width, "height_m": sheet_height},
            "views": [],
            "manual_review_required": True,
            "retryable": True,
            "error_code": "DRAWING_LAYOUT_WORKING_AREA_INVALID",
        }
    scale = next((item for item in STANDARD_DRAWING_SCALES if item <= raw_scale + 1e-12), raw_scale)

    front_w, front_h = width * scale, height * scale
    top_w, top_h = width * scale, depth * scale
    right_w, right_h = depth * scale, height * scale
    layout_w = front_w + gap_m + right_w
    layout_h = front_h + gap_m + top_h
    origin_x = working_left + max(0.0, (available_width - layout_w) / 2.0)
    origin_y = working_bottom + max(0.0, (available_height - layout_h) / 2.0)

    def view_record(name, left, bottom, view_width, view_height):
        """@brief 创建单个视图的中心点与边界框记录。"""
        return {
            "name": name,
            "center": [left + view_width / 2.0, bottom + view_height / 2.0],
            "box": {"left": left, "bottom": bottom, "right": left + view_width, "top": bottom + view_height},
        }

    views = [
        view_record("*Front", origin_x, origin_y, front_w, front_h),
        view_record("*Top", origin_x, origin_y + front_h + gap_m, top_w, top_h),
        view_record("*Right", origin_x + front_w + gap_m, origin_y, right_w, right_h),
    ]
    title_box = {
        "left": sheet_width - margin_m - title_block_width_m,
        "bottom": margin_m,
        "right": sheet_width - margin_m,
        "top": margin_m + title_block_height_m,
    }
    return {
        "status": "pass",
        "paper_size": paper_size,
        "sheet": {"width_m": sheet_width, "height_m": sheet_height},
        "working_area": {"left": working_left, "bottom": working_bottom, "right": working_right, "top": working_top},
        "title_block_box": title_box,
        "scale": scale,
        "scale_ratio": list(_scale_ratio(scale)),
        "views": views,
        "manual_review_required": True,
    }


def _scale_ratio(scale):
    """@brief 将浮点比例转换为 SolidWorks 可接受的整数比。"""
    ratio = Fraction(float(scale)).limit_denominator(1000)
    return ratio.numerator, ratio.denominator


def _apply_view_layout(view, item, numerator, denominator) -> dict:
    """@brief 将已创建视图移动到规划中心并设置独立比例。"""
    center = [float(item["center"][0]), float(item["center"][1])]
    if hasattr(view, "UseParentScale"):
        view.UseParentScale = False
    if hasattr(view, "PositionLocked"):
        view.PositionLocked = False
    view.ScaleRatio = (int(numerator), int(denominator))
    position = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, center)
    method = getattr(view, "SetViewPosition", None)
    if method is not None:
        moved = bool(get_com_member(view, "SetViewPosition", position, False))
        if not moved:
            raise RuntimeError(f"SetViewPosition 返回失败: {center}")
    else:
        view.Position = tuple(center)
    actual_position = _view_position(view)
    position_verified = bool(
        actual_position
        and abs(actual_position[0] - center[0]) <= 1e-5
        and abs(actual_position[1] - center[1]) <= 1e-5
    )
    if not position_verified:
        raise RuntimeError(f"视图位置回读不一致: requested={center}, actual={actual_position}")
    return {
        "name": item["name"],
        "actual_name": str(_safe_member(view, "Name", default="")),
        "orientation": str(_safe_member(view, "GetOrientationName", default="")),
        "center": center,
        "actual_center": list(actual_position),
        "position_verified": True,
        "scale_ratio": [int(numerator), int(denominator)],
    }


def _normalise_orientation(value):
    """@brief 将 SolidWorks 标准视图方向统一为 front/top/right 键。"""
    compact = re.sub(r"[^a-z\u4e00-\u9fff]", "", str(value or "").casefold())
    aliases = {
        "front": "front",
        "top": "top",
        "right": "right",
        "frontview": "front",
        "topview": "top",
        "rightview": "right",
        "前视": "front",
        "主视": "front",
        "上视": "top",
        "俯视": "top",
        "右视": "right",
    }
    return aliases.get(compact)


def _view_position(view):
    """@brief 读取工程图视图中心位置。"""
    values = _as_sequence(_safe_member(view, "Position", default=[]))
    try:
        if len(values) < 2:
            return None
        return float(values[0]), float(values[1])
    except (IndexError, TypeError, ValueError):
        return None


def _collect_drawing_views(drawing_model):
    """@brief 同时尝试 Sheet.GetViews 与 GetFirstView 链读取真实模型视图。"""
    sheet = _safe_member(drawing_model, "GetCurrentSheet")
    views = _as_sequence(_safe_member(sheet, "GetViews", default=[]))
    if len(views) >= 3:
        return views
    traversed = []
    sheet_view = _safe_member(drawing_model, "GetFirstView")
    current = _safe_member(sheet_view, "GetNextView")
    guard = 0
    while current is not None and guard < 1000:
        traversed.append(current)
        current = _safe_member(current, "GetNextView")
        guard += 1
    return traversed if len(traversed) >= len(views) else views


def _map_native_standard_views(views):
    """@brief 依据方向名、基准视图关系和原始位置映射第三角三视图。"""
    by_orientation = {}
    diagnostics = []
    for view in views:
        orientation_name = str(_safe_member(view, "GetOrientationName", default=""))
        orientation = _normalise_orientation(orientation_name)
        base_view = _safe_member(view, "GetBaseView")
        position = _view_position(view)
        diagnostics.append({
            "name": str(_safe_member(view, "Name", default="")),
            "orientation": orientation_name,
            "position": list(position) if position else None,
            "has_base_view": base_view is not None,
            "referenced_model": str(_safe_member(view, "GetReferencedModelName", default="")),
        })
        if orientation and orientation not in by_orientation:
            by_orientation[orientation] = view
    if set(by_orientation) >= {"front", "top", "right"}:
        return by_orientation, diagnostics, "orientation_name"

    positioned = [(view, _view_position(view), _safe_member(view, "GetBaseView")) for view in views]
    positioned = [item for item in positioned if item[1] is not None]
    if len(positioned) >= 3:
        base_candidates = [item for item in positioned if item[2] is None]
        front = min(base_candidates or positioned, key=lambda item: item[1][0] + item[1][1])
        remaining = [item for item in positioned if item[0] is not front[0]]
        top = max(remaining, key=lambda item: item[1][1] - front[1][1])
        right_candidates = [item for item in remaining if item[0] is not top[0]]
        if right_candidates:
            right = max(right_candidates, key=lambda item: item[1][0] - front[1][0])
            return {"front": front[0], "top": top[0], "right": right[0]}, diagnostics, "base_and_position"
    return by_orientation, diagnostics, "unresolved"


def create_adaptive_standard_views(drawing_model, part_path, layout) -> dict:
    """@brief 按预先计算的布局创建前、俯、右三个真实工程图视图。"""
    created = []
    numerator, denominator = layout.get("scale_ratio") or _scale_ratio(layout["scale"])
    for item in layout.get("views", []):
        center = item["center"]
        view = drawing_model.CreateDrawViewFromModelView3(part_path, item["name"], center[0], center[1], 0)
        if view is None:
            if not created:
                native_created = bool(_safe_member(drawing_model, "Create3rdAngleViews2", str(part_path), default=False))
                if native_created:
                    _safe_member(drawing_model, "ForceRebuild3", False)
                    _safe_member(drawing_model, "GraphicsRedraw2")
                    native_views = _collect_drawing_views(drawing_model)
                    by_orientation, diagnostics, mapping_method = _map_native_standard_views(native_views)
                    expected = {"front": "*Front", "top": "*Top", "right": "*Right"}
                    if set(by_orientation) >= set(expected):
                        layout_by_name = {entry["name"]: entry for entry in layout.get("views", [])}
                        try:
                            for orientation in ("front", "top", "right"):
                                created.append(
                                    _apply_view_layout(
                                        by_orientation[orientation],
                                        layout_by_name[expected[orientation]],
                                        numerator,
                                        denominator,
                                    )
                                )
                        except Exception as exc:
                            return {
                                "status": "failed",
                                "stage": "layout",
                                "backend": "native_3rd_angle",
                                "views": created,
                                "native_view_diagnostics": diagnostics,
                                "retryable": True,
                                "error_code": "DRAWING_VIEW_POSITION_FAILED",
                                "error": str(exc),
                            }
                        return {
                            "status": "pass",
                            "stage": "create",
                            "backend": "native_3rd_angle",
                            "mapping_method": mapping_method,
                            "native_view_diagnostics": diagnostics,
                            "views": created,
                            "view_count": len(created),
                            "retryable": False,
                            "error_code": None,
                            "manual_review_required": True,
                        }
                    return {
                        "status": "failed",
                        "stage": "map",
                        "backend": "native_3rd_angle",
                        "views": [],
                        "orientations_found": sorted(by_orientation),
                        "mapping_method": mapping_method,
                        "native_view_diagnostics": diagnostics,
                        "retryable": True,
                        "error_code": "DRAWING_VIEW_ORIENTATION_MAP_FAILED",
                    }
            return {
                "status": "failed",
                "stage": "create",
                "views": created,
                "retryable": True,
                "error_code": "DRAWING_VIEW_CREATE_FAILED",
            }
        try:
            created.append(_apply_view_layout(view, item, numerator, denominator))
        except Exception as exc:
            return {
                "status": "failed",
                "stage": "layout",
                "backend": "individual_model_views",
                "views": created,
                "retryable": True,
                "error_code": "DRAWING_VIEW_POSITION_FAILED",
                "error": str(exc),
            }
    return {
        "status": "pass",
        "stage": "create",
        "backend": "individual_model_views",
        "views": created,
        "view_count": len(created),
        "retryable": False,
        "error_code": None,
        "manual_review_required": True,
    }


def create_standard_views(drawing_model, part_path):
    """
    创建标准三视图（第三角投影法）

    参数:
        drawing_model: IDrawingDoc
        part_path: 零件文件路径
    """
    return drawing_model.Create3rdAngleViews2(part_path)


def add_view(drawing_model, part_path, view_name, x, y, scale=None):
    """
    添加单个视图

    参数:
        view_name: 视图方向名称
            "*Front", "*Back", "*Top", "*Bottom",
            "*Left", "*Right", "*Isometric",
            "*Trimetric", "*Dimetric"
        x, y: 视图放置位置（米）
        scale: 视图比例（如 0.5 表示 1:2），None 使用图纸默认
    """
    view = drawing_model.CreateDrawViewFromModelView3(
        part_path, view_name, x, y, 0
    )
    if view and scale:
        view.ScaleRatio = (1.0, 1.0 / scale)
    return view


def add_section_view(drawing_model, x, y):
    """在当前选择的剖切线位置创建剖视图"""
    return drawing_model.CreateSectionViewAt5(x, y, 0, "", 0, None, 0)


def add_detail_view(drawing_model, x, y, scale=2.0):
    """创建局部放大视图"""
    return drawing_model.CreateDetailViewAt4(x, y, 0, 0, scale, 0, "")


def insert_dimensions(drawing_model, view=None):
    """
    自动标注尺寸（模型项目）

    参数:
        view: 目标视图对象，None 则标注所有视图
    """
    # SolidWorks 2024 新增 InsertModelAnnotations4，返回实际插入的 IAnnotation
    # 数组；旧版/动态代理仍可能只有 InsertModelAnnotations3。优先使用 4，
    # 再回退到 3，避免把“方法返回 True”误当成已经插入尺寸。
    # SW2024 swInsertAnnotation_e：32768=标记为工程图的模型尺寸。
    # 8 是通用尺寸类型、524288 是未标记尺寸；本机 SW2024 对二者组合静默
    # 返回 None，而 32768 会返回真实 IAnnotation 数组。
    args4 = (
        0,          # swImportModelItemsFromEntireModel
        32768,      # swInsertDimensionsMarkedForDrawing
        True, False, False, False,
        False, False,
    )
    args3 = args4[:6]
    # 官方 API 示例要求先激活一个工程图视图；未激活时 SW2024 会静默返回空结果。
    try:
        sheet = _safe_member(drawing_model, "GetCurrentSheet")
        views = _as_sequence(_safe_member(sheet, "GetViews", default=[]))
        if views:
            # 三视图第一个通常是前视图；通过对象 Name 读取失败时使用已知顺序，
            # 但仍要求 SelectByID2/ActivateView 真正返回成功。
            first_view = views[0]
            name = _safe_member(first_view, "Name", default="")
            if name:
                extension = getattr(drawing_model, "Extension", None)
                if extension is not None:
                    get_com_member(
                        extension, "SelectByID2",
                        name, "DRAWINGVIEW", 0, 0, 0, False, 0,
                        create_empty_dispatch_variant(), 0,
                    )
                get_com_member(drawing_model, "ActivateView", name)
    except Exception:
        # 激活失败仍继续尝试，让结构复核决定是否有真实尺寸证据。
        pass
    owners = (drawing_model, getattr(drawing_model, "Extension", None))
    for owner in owners:
        if owner is None:
            continue
        try:
            method4 = getattr(owner, "InsertModelAnnotations4", None)
            if method4 is not None:
                inserted = get_com_member(owner, "InsertModelAnnotations4", *args4)
                if inserted is not None:
                    return inserted
            method3 = getattr(owner, "InsertModelAnnotations3", None)
            if method3 is not None:
                return get_com_member(owner, "InsertModelAnnotations3", *args3)
        except (AttributeError, TypeError, pythoncom.com_error):
            continue
    # 新建三视图后 SW2024 有时尚未建立可导入的视图缓存；强制重建后仅重试
    # 一次。使用“标记为工程图”与消重语义，不会靠重复调用制造重复尺寸。
    try:
        get_com_member(drawing_model, "ForceRebuild3", False)
        get_com_member(drawing_model, "GraphicsRedraw2")
        for owner in owners:
            if owner is not None and getattr(owner, "InsertModelAnnotations4", None) is not None:
                inserted = get_com_member(owner, "InsertModelAnnotations4", *args4)
                if inserted is not None:
                    return inserted
    except (AttributeError, TypeError, pythoncom.com_error):
        pass
    # 调用方可以继续做结构复核，但必须把缺少真实尺寸证据显示为 warning。
    return False


def add_note(drawing_model, x, y, text):
    """
    添加注释

    参数:
        x, y: 注释位置（米）
        text: 注释文本
    """
    return drawing_model.InsertNote(text)


def insert_bom_table(drawing_model, template_path, x, y, bom_type=1, config_name=""):
    """
    插入 BOM 表

    参数:
        template_path: BOM 模板路径（.sldbomtbt）
        x, y: 表格放置位置（米）
        bom_type: 1=顶层, 2=仅零件, 3=缩进
        config_name: 配置名称
    """
    return drawing_model.InsertBomTable4(
        template_path, x, y, bom_type, config_name, "", False
    )


def set_sheet_format(drawing_model, format_path):
    """
    设置图纸格式（图框）

    参数:
        format_path: 图纸格式文件路径（.slddrt）
    """
    sheet = drawing_model.GetCurrentSheet()
    return sheet.SetTemplateName(format_path)


def add_sheet(drawing_model, paper_size=7, template_path=""):
    """
    添加新图纸

    参数:
        paper_size: 纸张大小
            0=A, 1=B, 2=C, 3=D, 4=E,
            5=A4, 6=A3, 7=A2, 8=A1, 9=A0
        template_path: 图纸格式模板路径
    """
    return drawing_model.NewSheet4(
        "", paper_size, 12, 1.0, 1.0, True, template_path, 0, 0, "", 0, 0, 0, 0, 0, 0
    )


def add_a3_sheet(drawing_model, template_candidates, *, require_gbt=True) -> dict:
    """@brief 选择本机 A3 图框并创建横向 A3 工程图页。"""
    selection = select_drawing_template(template_candidates, paper_size="A3", require_gbt=require_gbt)
    if selection["selected"] is None:
        return {
            **selection,
            "stage": "preflight",
            "retryable": True,
            "created": False,
        }
    created = bool(add_sheet(drawing_model, paper_size=PAPER_SIZES["A3"]["code"], template_path=selection["selected"]))
    return {
        **selection,
        "status": "pass" if created else "failed",
        "stage": "create",
        "retryable": not created,
        "created": created,
        "error_code": None if created else "DRAWING_A3_SHEET_CREATE_FAILED",
    }


def setup_current_sheet_as_a3(drawing_model, template_candidates, *, require_gbt=True) -> dict:
    """@brief 使用 IDrawingDoc.SetupSheet6 将当前页设置为横向 A3。"""
    selection = select_drawing_template(template_candidates, paper_size="A3", require_gbt=require_gbt)
    if selection["selected"] is None:
        return {
            **selection,
            "stage": "preflight",
            "retryable": True,
            "configured": False,
        }
    sheet = _safe_member(drawing_model, "GetCurrentSheet")
    sheet_name = str(_safe_member(sheet, "GetName", default="") or "")
    if not sheet_name:
        return {
            **selection,
            "status": "blocked",
            "stage": "preflight",
            "retryable": True,
            "configured": False,
            "error_code": "DRAWING_CURRENT_SHEET_MISSING",
        }
    try:
        configured = bool(get_com_member(
            drawing_model,
            "SetupSheet6",
            sheet_name,
            PAPER_SIZES["A3"]["code"],
            12,
            1.0,
            1.0,
            True,
            selection["selected"],
            0.0,
            0.0,
            "",
            False,
            0.0,
            0.0,
            0.0,
            0.0,
            0,
            0,
        ))
    except Exception as exc:
        return {
            **selection,
            "status": "failed",
            "stage": "create",
            "retryable": True,
            "configured": False,
            "error_code": "DRAWING_A3_SETUP_FAILED",
            "error": str(exc),
        }
    return {
        **selection,
        "status": "pass" if configured else "failed",
        "stage": "create",
        "retryable": not configured,
        "configured": configured,
        "sheet_name": sheet_name,
        "error_code": None if configured else "DRAWING_A3_SETUP_FAILED",
    }


def get_all_views(drawing_model):
    """获取当前图纸上的所有视图"""
    sheet = get_com_member(drawing_model, "GetCurrentSheet")
    views = get_com_member(sheet, "GetViews")
    result = []
    if views:
        for view in views:
            result.append({
                "name": view.Name,
                "type": view.Type,
                "scale": view.ScaleRatio,
            })
    return result


def _paper_size_from_template(template_path):
    """@brief 从模板文件名推断标准图幅；无法判断时返回 None。"""
    name = Path(str(template_path or "")).stem.upper()
    for paper_size in PAPER_SIZES:
        if re.search(rf"(?:^|[^A-Z0-9]){paper_size}(?:[^A-Z0-9]|$)", name):
            return paper_size
    return None


def inspect_drawing_structure(drawing_model, *, paper_size_hint=None, title_block_box=None) -> dict:
    """@brief 读取工程图结构并返回可审计报告，不修改文档。"""
    sheets = _as_sequence(_safe_member(drawing_model, "GetSheetNames", default=[]))
    if not sheets:
        current_sheet = _safe_member(drawing_model, "GetCurrentSheet")
        current_name = _safe_member(current_sheet, "GetName", default="")
        if current_name:
            sheets = [current_name]
    views = []
    dimensions = []
    notes = []
    tables = []
    for sheet_name in sheets or [""]:
        sheet = _safe_member(drawing_model, "GetSheet", sheet_name) or _safe_member(drawing_model, "GetCurrentSheet")
        for view in _as_sequence(_safe_member(sheet, "GetViews", default=[])):
            view_record = {
                "sheet": str(sheet_name),
                "name": _safe_member(view, "Name", default=""),
                "type": _safe_member(view, "Type", default=None),
                "scale": _safe_member(view, "ScaleRatio", default=None),
                "box": _normalise_box(_safe_member(view, "GetOutline")),
            }
            views.append(view_record)
            view_dimensions = _view_display_dimensions(view)
            for dimension in view_dimensions:
                native_box = _annotation_box(dimension)
                estimated_box_evidence = estimate_dimension_text_box(dimension) if native_box is None else None
                dimensions.append({
                    "sheet": str(sheet_name),
                    "view": _safe_member(view, "Name", default=""),
                    "name": (
                        _safe_member(dimension, "Name", default="")
                        or _safe_member(dimension, "GetNameForSelection", default="")
                        or _safe_member(_safe_member(dimension, "GetDimension"), "FullName", default="")
                    ),
                    "type": _safe_member(dimension, "Type", default=None),
                    "text": _safe_member(dimension, "GetText", 0, default=""),
                    "box": native_box or estimated_box_evidence.get("box"),
                    "box_source": "native" if native_box else estimated_box_evidence.get("source"),
                    "box_confidence": "high" if native_box else estimated_box_evidence.get("confidence"),
                    "box_evidence": {
                        "box": native_box,
                        "source": "native",
                        "confidence": "high",
                        "method": "annotation_get_box",
                    } if native_box else estimated_box_evidence,
                })
            for note in _as_sequence(_safe_member(view, "GetNotes", default=[])):
                notes.append({"sheet": str(sheet_name), "text": _safe_member(note, "Text", default=""), "box": _annotation_box(note)})
            for table in _as_sequence(_safe_member(view, "GetTableAnnotations", default=[])):
                tables.append({"sheet": str(sheet_name), "type": _safe_member(table, "Type", default=None), "box": _annotation_box(table)})
    current_sheet = _safe_member(drawing_model, "GetCurrentSheet")
    template = _safe_member(current_sheet, "GetTemplateName", default="")
    paper_size = str(paper_size_hint or _paper_size_from_template(template) or "").upper() or None
    spec = PAPER_SIZES.get(paper_size)
    inferred_title_box = title_block_box
    if inferred_title_box is None and spec is not None:
        inferred_title_box = {
            "left": spec["width_m"] - 0.012 - 0.180,
            "bottom": 0.012,
            "right": spec["width_m"] - 0.012,
            "top": 0.067,
        }
    compact_template_name = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", Path(str(template or "")).stem.casefold())
    template_name = Path(str(template or "")).stem.casefold()
    gbt_candidate = (
        "gbt" in compact_template_name
        or "国标" in compact_template_name
        or bool(re.search(r"(?:^|[^a-z0-9])gb(?:t)?(?:[^a-z0-9]|$)", template_name, re.IGNORECASE))
    )
    outline_count = sum(item.get("box") is not None for item in views)
    dimension_box_count = sum(item.get("box") is not None for item in dimensions)
    native_dimension_box_count = sum(item.get("box_source") == "native" for item in dimensions)
    estimated_dimension_box_count = sum(item.get("box_source") == "estimated" and item.get("box") is not None for item in dimensions)
    low_confidence_dimension_box_count = sum(item.get("box_confidence") in {"low", "unavailable"} for item in dimensions)
    result = {
        "status": "pass" if views else "blocked",
        "stage": "review",
        "sheets": [str(item) for item in sheets],
        "views": views,
        "dimensions": dimensions,
        "notes": notes,
        "tables": tables,
        "template_path": str(template or ""),
        "paper_size": paper_size,
        "sheet_size": {"width_m": spec["width_m"], "height_m": spec["height_m"]} if spec else None,
        "title_block": {
            "candidate": bool(template),
            "gbt_candidate": gbt_candidate,
            "content_verified": False,
            "box": _normalise_box(title_block_box) if title_block_box is not None else inferred_title_box,
        },
        "view_count": len(views),
        "dimension_count": len(dimensions),
        "table_count": len(tables),
        "view_outline_count": outline_count,
        "dimension_box_count": dimension_box_count,
        "native_dimension_box_count": native_dimension_box_count,
        "estimated_dimension_box_count": estimated_dimension_box_count,
        "low_confidence_dimension_box_count": low_confidence_dimension_box_count,
        "manual_review_required": True,
        "retryable": not bool(views),
        "error_code": None if views else "DRAWING_VIEWS_MISSING",
        "checks": [
            {"id": "drawing-views", "status": "pass" if views else "fail", "message": "工程图包含视图" if views else "未读取到工程图视图"},
            {"id": "drawing-template", "status": "pass" if template else "warning", "message": "已读取图框模板" if template else "图框模板需要人工确认"},
            {"id": "drawing-a3-sheet", "status": "pass" if paper_size == "A3" else "warning", "message": "当前图幅识别为 A3" if paper_size == "A3" else "当前图幅不是 A3 或无法识别"},
            {"id": "drawing-gbt-template", "status": "pass" if gbt_candidate else "warning", "message": "模板名称是 GB/T 候选，内容仍需目视复核" if gbt_candidate else "未发现 GB/T 图框候选证据"},
            {"id": "drawing-dimensions", "status": "pass" if dimensions else "warning", "message": "已读取真实尺寸实体" if dimensions else "未读取到尺寸实体"},
            {"id": "drawing-view-outlines", "status": "pass" if views and outline_count == len(views) else "warning", "message": "已读取全部视图边界" if views and outline_count == len(views) else "部分视图缺少边界，无法完整检查碰撞"},
            {
                "id": "drawing-dimension-boxes",
                "status": "pass" if dimensions and native_dimension_box_count == len(dimensions) else "warning",
                "message": (
                    "已读取全部尺寸文字原生边界"
                    if dimensions and native_dimension_box_count == len(dimensions)
                    else f"原生边界 {native_dimension_box_count}/{len(dimensions)}，保守估算 {estimated_dimension_box_count}/{len(dimensions)}；估算不等于原生证据"
                ),
            },
        ],
    }
    return result


def export_sheet_to_pdf(model, output_path, sheet_names=None, sw_app=None):
    """
    将工程图导出为 PDF

    参数:
        model: IModelDoc2（工程图文档）
        output_path: 输出 PDF 路径
        sheet_names: 图纸名称列表，None=所有图纸
        sw_app: 可选的 SldWorks.Application 对象；传入会话对象可避免 SW2024
            动态 IModelDoc2 未暴露 GetSldWorksObject 的兼容性问题。
    """
    sw = sw_app
    if sw is None:
        for prog_id in ("SldWorks.Application.32", "SldWorks.Application"):
            try:
                sw = _win32com.GetActiveObject(prog_id)
                break
            except Exception:
                continue
    if sw is None:
        return False
    try:
        pdf_data = get_com_member(sw, "GetExportFileData", 1)  # 1 = swExportPDFData
    except Exception:
        return False

    if sheet_names is None:
        drawing = model
        sheet_names = get_com_member(drawing, "GetSheetNames")

    try:
        pdf_data.SetSheets(0, sheet_names)  # 0 = swExportData_ExportSpecifiedSheets
    except Exception:
        return False

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    if success:
        print(f"PDF 导出成功: {output_path}")
    else:
        print(f"PDF 导出失败, 错误码: {errors.value}")
    return success


# =============================================================================
# 尺寸公差（dimension_tolerances）
# 来源：SW2024 电机项目 gen_drawing.py set_tol。仅覆盖线性尺寸公差；GD&T 几何公差框
# 仍为 reference_only。返回工程图模块统一证据字典（status∈pass|failed|review_required）。
# =============================================================================

# swTolType_e（SolidWorks.Interop.swconst）。技能约定：硬编码整数 + 注释枚举来源，
# 不加载 swconst.tlb。
SW_TOL_NONE = 0       # swTolNONE
SW_TOL_MIN = 1        # swTolMIN
SW_TOL_MAX = 2        # swTolMAX
SW_TOL_BASIC = 3      # swTolBASIC
SW_TOL_SYMMETRIC = 4  # swTolSYMMETRIC —— SW2024 已验证渲染
SW_TOL_BILATERAL = 5  # swTolBILATERAL（上下不同）
SW_TOL_LIMIT = 6      # swTolLIMIT

# GB/T 1804 一般公差·中等级 m：(上界 mm, 对称 ± mm)，线性查表。
_GB1804M_BANDS = (
    (6.0, 0.1),
    (30.0, 0.2),
    (120.0, 0.3),
    (400.0, 0.5),
    (float("inf"), 0.8),
)


def gb1804m_band(nominal_mm):
    """@brief GB/T 1804-m（一般公差·中等级）按名义尺寸线性分档，返回对称 ±（mm）。

    纯查表函数，不接触 COM，可单测。
    """
    n = abs(float(nominal_mm))
    for upper, band in _GB1804M_BANDS:
        if n <= upper:
            return band
    return 0.8  # 防御性兜底（>400）


def set_dimension_tolerance(display_dimension, nominal_mm, *, tol_type=SW_TOL_SYMMETRIC,
                            plus_mm=None, minus_mm=None):
    """@brief 为 DisplayDimension 设置尺寸公差。

    默认对称（tol_type=4）。plus_mm/minus_mm 任一为 None 时，按 GB/T 1804-m 以名义尺寸
    自动分档填充。公差值内部换算为米调用 IDimension.SetToleranceValues。

    三个必踩坑（详见 references/tolerances.md）：
      1. 必须用 SetToleranceType 方法启用 ± 显示（ITolerance.Type 属性赋值不渲染）；
      2. 带宽按已知名义尺寸查表，不读尺寸回读值（GetValue2/SystemValue 单位会错档）；
      3. SetToleranceValues 取米（±0.2mm → 0.0002）。

    返回证据字典：status=pass 仅代表 COM 调用成功，是否真正渲染须以导出 PDF/BMP 目视复核。
    """
    result = {
        "status": "failed",
        "stage": "tolerance",
        "tolerance_type": int(tol_type),
        "nominal_mm": float(nominal_mm),
        "plus_mm": None,
        "minus_mm": None,
        "band_source": None,
        "rendered_via": "IDimension.SetToleranceType + SetToleranceValues",
        "error_code": None,
        "retryable": False,
        "manual_review_required": True,
    }
    try:
        auto = (plus_mm is None) or (minus_mm is None)
        band = gb1804m_band(nominal_mm)
        if plus_mm is None:
            plus_mm = band
        if minus_mm is None:
            minus_mm = band
        plus_mm = float(plus_mm)
        minus_mm = float(minus_mm)
        result["plus_mm"] = plus_mm
        result["minus_mm"] = minus_mm
        result["band_source"] = "gb1804m_m" if auto else "explicit"

        dimension = get_com_member(display_dimension, "GetDimension")
        if dimension is None:
            result["error_code"] = "DRAWING_TOLERANCE_NO_DIMENSION"
            return result

        # 1) 启用显示（必须用方法，不是 ITolerance.Type= 属性赋值）
        get_com_member(dimension, "SetToleranceType", int(tol_type))
        # 2) 公差值，单位米：上差=+tol，下差=-tol（对称时两者同值）
        get_com_member(dimension, "SetToleranceValues", plus_mm / 1000.0, -minus_mm / 1000.0)

        result["status"] = "pass"
    except Exception as exc:
        result["error_code"] = "DRAWING_TOLERANCE_SET_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result


def apply_gb1804m(display_dimension, nominal_mm):
    """@brief 便捷封装：按 GB/T 1804-m 套对称 ± 公差。"""
    return set_dimension_tolerance(display_dimension, nominal_mm, tol_type=SW_TOL_SYMMETRIC)


# =============================================================================
# 视图比例与坐标扫描式标注（drawing_edge_scan_dimensioning）
# 来源：SW2024 电机项目 gen_drawing.py find_edge / find_solid_x / picktype / adddim。
# 设计：find_edge / find_solid_x 为纯函数（注入 picktype 可单测）；make_picktype 把真实
# 工程图接成 picktype；scan_view_dimensions 端到端编排（前视图 W/H + 俯视图 D）。
# =============================================================================

# 视图比例低于此阈值时，SolidWorks 不暴露可点选的边/面（点选恒返回 type=12 视图对象，
# probe_scale 实证：0.50 可选 / 0.45 不可选）。
PICKABILITY_THRESHOLD_SCALE = 0.5


def pickability_ok(view):
    """@brief 视图比例门禁自检：读 ScaleRatio，判断是否 ≥1:2。

    返回 {status∈pass|blocked, scale, threshold, reason}。status=blocked 表示坐标扫描会
    静默失败，调用方应先 force_view_scale。
    """
    ratio = _safe_member(view, "ScaleRatio", default=None)
    scale = None
    if isinstance(ratio, (tuple, list)) and len(ratio) == 2 and ratio[1]:
        try:
            scale = float(ratio[0]) / float(ratio[1])
        except (TypeError, ValueError, ZeroDivisionError):
            scale = None
    result = {
        "status": "blocked",
        "stage": "pickability",
        "scale": scale,
        "threshold": PICKABILITY_THRESHOLD_SCALE,
        "reason": None,
    }
    if scale is None:
        result["reason"] = "无法读取视图 ScaleRatio"
    elif scale < PICKABILITY_THRESHOLD_SCALE:
        result["reason"] = (
            "视图比例 %.3f 低于 %.2f（1:2），SolidWorks 不暴露可点选边/面；"
            "先调 force_view_scale" % (scale, PICKABILITY_THRESHOLD_SCALE)
        )
    else:
        result["status"] = "pass"
    return result


def force_view_scale(view, scale, *, drawing_model=None):
    """@brief 强制视图真实比例，绕开 UseSheetScale 默认 True。

    CreateDrawViewFromModelView3 的 Scale 参数在 UseSheetScale 默认 True 时被忽略，大件会
    静默落到图纸比例（常 <1:2，低于可选择性阈值）。本函数：UseSheetScale=False +
    UseParentScale=False + ScaleDecimal=scale，可选重建后回读 ScaleRatio 验证。

    返回 {status∈pass|failed|review_required, scale, scale_ratio, verified}。
    """
    s = float(scale)
    result = {
        "status": "failed",
        "stage": "scale",
        "scale": s,
        "scale_ratio": None,
        "verified": False,
        "error_code": None,
        "retryable": False,
        "manual_review_required": False,
    }
    try:
        if hasattr(view, "UseSheetScale"):
            view.UseSheetScale = False
        if hasattr(view, "UseParentScale"):
            view.UseParentScale = False
        try:
            view.ScaleDecimal = s
        except Exception:
            num, den = _scale_ratio(s)
            view.ScaleRatio = (int(num), int(den))
        if drawing_model is not None:
            try:
                get_com_member(drawing_model, "EditRebuild3")
            except Exception:
                pass
        ratio = _safe_member(view, "ScaleRatio", default=None)
        if isinstance(ratio, (tuple, list)) and len(ratio) == 2 and ratio[1]:
            result["scale_ratio"] = [int(ratio[0]), int(ratio[1])]
            actual = float(ratio[0]) / float(ratio[1])
            result["verified"] = abs(actual - s) <= max(1e-6, abs(s) * 1e-3)
            result["status"] = "pass"
        else:
            result["status"] = "review_required"
            result["manual_review_required"] = True
            result["error_code"] = "DRAWING_SCALE_READBACK_FAILED"
    except Exception as exc:
        result["error_code"] = "DRAWING_SCALE_FORCE_FAILED"
        result["retryable"] = True
        result["error"] = str(exc)
    return result


def find_edge(view_outline, axis, side, fixed, picktype, *,
              coarse_steps=24, binary_iters=16, micro_range=0.0009):
    """@brief 在视图轮廓 `axis` 方向 `side` 侧找到一条可点选边（seltype==1）的坐标。

    纯函数（picktype 由调用方注入，可单测）。
      view_outline: [xmin, ymin, xmax, ymax]（米）。
      axis: 0=沿 X 扫描（变 X，固定 Y），1=沿 Y 扫描（变 Y，固定 X）。
      side: "min"（取 lo 侧边）或 "max"（取 hi 侧边）。
      fixed: 另一轴的固定坐标（米）。
      picktype(c, axis, fixed)->int: 0=空/仅视图对象，1=边，2=面。每次调用会自行清选择。

    算法：粗扫(24步)定位 空→实体 过渡 → 二分(16次)精确定位边界 → 以边界为中心
    ±micro_range(0.9mm)/0.1mm 微扫落在 seltype==1 的可选边上。对薄边与旋转/缩放鲁棒。
    返回边所在坐标 c（米），或 None（该侧无可点选几何）；微扫未命中边时回退返回边界中心。
    """
    lo = float(view_outline[axis])
    hi = float(view_outline[axis + 2])
    if hi <= lo:
        return None
    c_empty = None
    c_geom = None
    for k in range(coarse_steps + 1):
        if side == "min":
            c = lo + (hi - lo) * k / coarse_steps
        else:
            c = hi - (hi - lo) * k / coarse_steps
        st = picktype(c, axis, fixed)
        if st == 0:
            c_empty = c
        else:
            c_geom = c
            if c_empty is not None:
                break
    if c_geom is None:
        return None
    if c_empty is None:
        c_empty = lo if side == "min" else hi
    a, b = c_empty, c_geom
    for _ in range(binary_iters):
        m = (a + b) / 2.0
        if picktype(m, axis, fixed) == 0:
            a = m
        else:
            b = m
    center = (a + b) / 2.0
    for k in range(-9, 10):
        c = center + micro_range * k / 9.0
        if picktype(c, axis, fixed) == 1:
            return c
    return center


def find_solid_x(view_outline, ymid, picktype):
    """@brief 在视图 X 跨度内找一个落在实体面（seltype==2）上的 X，远离竖边/内部空隙。

    作为竖向（H/D）边扫描的固定 X，使点选不咬到竖边（夹爪等含中央空隙的零件）。
    找不到时回退到 X 中点。
    """
    lo = float(view_outline[0])
    hi = float(view_outline[2])
    if hi <= lo:
        return (lo + hi) / 2.0
    for frac in (0.5, 0.25, 0.75, 0.35, 0.65, 0.15, 0.85):
        x = lo + (hi - lo) * frac
        if picktype(x, 0, ymid) == 2:
            return x
    return (lo + hi) / 2.0


def make_picktype(drawing_model):
    """@brief 把活动工程图文档接成 find_edge 的 picktype(c, axis, fixed)->seltype 闭包。

    内部用 SelectionManager.GetSelectedObjectCount2 + GetSelectedObjectType6（回退 5/4/3）
    读首个几何对象类型（跳过 type=12 的视图对象）。每次点选前 ClearSelection。
    SelectByID2 作用于**活动文档**——调用方须确保该工程图已激活。
    任何点选异常都降级返回 0（视为空），使扫描优雅地得到部分结果而非抛错。
    """
    extension = _safe_member(drawing_model, "Extension", default=None)
    sel_mgr = _safe_member(drawing_model, "SelectionManager", default=None)
    empty = create_empty_dispatch_variant()
    cached_type_method = []

    def _gettype(idx):
        if cached_type_method:
            try:
                return get_com_member(sel_mgr, cached_type_method[0], idx, -1)
            except Exception:
                cached_type_method.clear()
        for mname in ("GetSelectedObjectType6", "GetSelectedObjectType5",
                      "GetSelectedObjectType4", "GetSelectedObjectType3"):
            try:
                value = get_com_member(sel_mgr, mname, idx, -1)
                cached_type_method.append(mname)
                return value
            except Exception:
                continue
        return 0

    def seltype():
        count = _safe_member(sel_mgr, "GetSelectedObjectCount2", -1, default=0)
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0
        for idx in range(1, count + 1):
            if _gettype(idx) in (1, 2):
                return _gettype(idx)
        return 0

    def picktype(c, axis, fixed):
        xc = c if axis == 0 else fixed
        yc = fixed if axis == 0 else c
        try:
            get_com_member(drawing_model, "ClearSelection")
        except Exception:
            pass
        try:
            get_com_member(extension, "SelectByID2", "", "", xc, yc, 0.0, False, 0, empty, 0)
        except Exception:
            return 0
        return seltype()

    return picktype


def add_dimension_between(drawing_model, point_a, point_b, dim_x, dim_y, *, retries=4):
    """@brief 在活动工程图上点选两点并 AddDimension2 标注，失败重试 ≤retries 次。

    point_a/point_b: (x, y) 米；dim_x/dim_y: 尺寸文字放置坐标（米）。
    边线点选可能在刚创建视图几何未稳态时瞬时失败，故重试。返回 DisplayDimension 或 None。
    """
    extension = _safe_member(drawing_model, "Extension", default=None)
    ax, ay = float(point_a[0]), float(point_a[1])
    bx, by = float(point_b[0]), float(point_b[1])
    empty = create_empty_dispatch_variant()
    for _ in range(max(1, int(retries))):
        try:
            get_com_member(drawing_model, "ClearSelection")
        except Exception:
            pass
        get_com_member(extension, "SelectByID2", "", "", ax, ay, 0.0, False, 0, empty, 0)
        get_com_member(extension, "SelectByID2", "", "", bx, by, 0.0, True, 0, empty, 0)
        dd = get_com_member(drawing_model, "AddDimension2", dim_x, dim_y, 0.0)
        if dd:
            try:
                get_com_member(drawing_model, "ClearSelection")
            except Exception:
                pass
            return dd
    return None


def _scan_dim_entry(axis, display_dimension, nominal_mm, apply_tolerance):
    """@brief 单个扫描尺寸的结果条目（内部用）。"""
    entry = {
        "axis": axis,
        "display_dimension_set": bool(display_dimension),
        "nominal_mm": float(nominal_mm),
        "tolerance_report": None,
    }
    if display_dimension and apply_tolerance:
        entry["tolerance_report"] = apply_gb1804m(display_dimension, nominal_mm)
    elif display_dimension:
        entry["tolerance_report"] = {"status": "skipped", "reason": "apply_tolerance=False"}
    return entry


def scan_view_dimensions(drawing_model, front_view, top_view, *,
                         nominal_width_mm, nominal_height_mm, nominal_depth_mm,
                         gap=0.030, apply_tolerance=True):
    """@brief 坐标扫描式标注前视图 W/H + 俯视图 D，可选套 GB/T 1804-m 对称公差。

    端到端：取两视图轮廓 → find_edge 定位 W/H/D 的左/右、上/下边 → add_dimension_between
    标注 →（可选）apply_gb1804m。调用前须确保：
      ① 工程图已激活（SelectByID2 作用于活动文档）；
      ② 视图已存盘（新建视图仅暴露部分剪影边，存盘后全部边线可选）；
      ③ 视图比例≥1:2（用 force_view_scale）。

    返回 {status∈pass|review_required|failed, dimensions:[…], edges, outline_front,
    outline_top, manual_review_required}。三个尺寸全成功标 pass；任一缺失标
    review_required；全程 pass 仍要求目视复核尺寸位置/重叠/尺寸链。
    """
    report = {
        "status": "review_required",
        "stage": "edge_scan",
        "dimensions": [],
        "edges": {},
        "outline_front": None,
        "outline_top": None,
        "apply_tolerance": bool(apply_tolerance),
        "nominal": {
            "width_mm": float(nominal_width_mm),
            "height_mm": float(nominal_height_mm),
            "depth_mm": float(nominal_depth_mm),
        },
        "manual_review_required": True,
        "error_code": None,
    }
    try:
        fo = _as_sequence(_safe_member(front_view, "GetOutline", default=[]))
        to = _as_sequence(_safe_member(top_view, "GetOutline", default=[]))
        if len(fo) < 4 or len(to) < 4:
            report["error_code"] = "DRAWING_SCAN_NO_OUTLINE"
            return report
        fo = [float(v) for v in fo]
        to = [float(v) for v in to]
        report["outline_front"] = fo
        report["outline_top"] = to

        fmx = (fo[0] + fo[2]) / 2.0
        fmy = (fo[1] + fo[3]) / 2.0
        tmy = (to[1] + to[3]) / 2.0

        picktype = make_picktype(drawing_model)

        # W：前视图 X 跨度（固定 Y=中）
        lw = find_edge(fo, 0, "min", fmy, picktype)
        rw = find_edge(fo, 0, "max", fmy, picktype)
        # H：前视图 Y 跨度（固定 X=实体面，避开中央空隙与竖边）
        hx = find_solid_x(fo, fmy, picktype)
        bh = find_edge(fo, 1, "min", hx, picktype)
        th = find_edge(fo, 1, "max", hx, picktype)
        # D：俯视图 Y 跨度（俯视图深度轴=竖向）
        dxv = find_solid_x(to, tmy, picktype)
        bd = find_edge(to, 1, "min", dxv, picktype)
        td = find_edge(to, 1, "max", dxv, picktype)
        report["edges"] = {"W": [lw, rw], "H": [bh, th], "D": [bd, td]}

        try:
            get_com_member(drawing_model, "ClearSelection")
        except Exception:
            pass

        dd_w = add_dimension_between(drawing_model, (lw, fmy), (rw, fmy), fmx, fo[1] - gap * 0.6) \
            if (lw and rw) else None
        dd_h = add_dimension_between(drawing_model, (hx, bh), (hx, th), fo[0] - gap * 0.6, fmy) \
            if (bh and th) else None
        dd_d = add_dimension_between(drawing_model, (dxv, bd), (dxv, td), to[0] - gap * 0.6, tmy) \
            if (bd and td) else None

        report["dimensions"] = [
            _scan_dim_entry("W", dd_w, nominal_width_mm, apply_tolerance),
            _scan_dim_entry("H", dd_h, nominal_height_mm, apply_tolerance),
            _scan_dim_entry("D", dd_d, nominal_depth_mm, apply_tolerance),
        ]

        all_set = all(r["display_dimension_set"] for r in report["dimensions"])
        report["status"] = "pass" if all_set else "review_required"
        report["error_code"] = None if all_set else "DRAWING_SCAN_PARTIAL"
    except Exception as exc:
        report["status"] = "failed"
        report["error_code"] = "DRAWING_SCAN_FAILED"
        report["retryable"] = True
        report["error"] = str(exc)
    return report
