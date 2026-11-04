"""
SolidWorks 语义选边工具。

背景：SolidWorks 传统的选边方式 ``SelectByID2("Edge1", "EDGE", x, y, z, ...)``
依赖实体的"坐标魔法值"，这些坐标在模型稍作修改后就会失效，是自动化脚本最脆弱
的一环。本模块改为遍历 B-Rep 拓扑，按**几何条件**（方向、长度、位置、是否属于
某个圆柱面）挑选边线，然后通过对象自身 ``Select4`` 建立选择集——不依赖名称和
坐标字符串，模型重建后依然可用。

支持的边线筛选条件：
    axis        边线方向（"x" | "y" | "z" | "vertical" | "all"）
    min_length_mm / max_length_mm
    along_z     是否为平行于 Z 轴的竖直边
    circular    是否为圆边（配合 hole/min_diameter 用来选孔的入口边）
    diameter_mm 圆边直径（与 tolerance_mm 配合）
    position_mm 边中点必须靠近的坐标（配合 position_tolerance_mm）
    convex_only 只保留凸边（外轮廓），用于外圆角
    concave_only 只保留凹边（内角），用于内圆角
"""
from __future__ import annotations

import math
import struct

try:
    from .sw_connect import create_empty_dispatch_variant, get_com_member
except ImportError:
    from sw_connect import create_empty_dispatch_variant, get_com_member


_MM_PER_M = 1000.0

# swSelectType_e 中的边线类型
SW_SEL_EDGE = "EDGE"

_AXIS_VECTORS = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}


def _to_mm(values):
    """@brief 把长度序列从米换算为毫米。"""
    return [float(value) * _MM_PER_M for value in values]


def _normalize(vector):
    """@brief 归一化向量，零向量返回 None。"""
    if not all(math.isfinite(component) for component in vector):
        return None
    length = math.hypot(*vector)
    if length < 1e-12:
        return None
    return tuple(component / length for component in vector)


def _is_parallel(first, second, angle_tolerance_deg=1.0):
    """@brief 判断两个单位向量是否（反）平行。"""
    if first is None or second is None or not all(math.isfinite(value) for value in (*first, *second)):
        return False
    dot = abs(sum(a * b for a, b in zip(first, second)))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot)) <= angle_tolerance_deg


def _edge_curve(edge):
    """@brief 获取 ICurve；仅在成员绑定失败时按真实类型信息调用，不猜 DISPID。"""
    try:
        curve = get_com_member(edge, "GetCurve")
        if curve is None:
            raise ValueError("IEdge.GetCurve 返回空曲线")
        getattr(curve, "IsLine")  # 排除 pywin32 返回的未调用方法包装。
        return curve
    except Exception as error:
        if not (isinstance(error, AttributeError) or getattr(error, "hresult", None) in {-2147352573, -2147352570}):
            raise
        original_error = error
    try:
        import pythoncom
        from win32com.client import dynamic
        ole = edge._oleobj_
        try:
            dispid = ole.GetIDsOfNames(0, "GetCurve")
        except Exception:
            # 名称绑定也不可用时，从当前对象的类型信息查真正的成员 ID。
            info = ole.GetTypeInfo()
            matches = []
            for index in range(info.GetTypeAttr().cFuncs):
                member_id = info.GetFuncDesc(index).memid
                if info.GetNames(member_id)[0] == "GetCurve":
                    matches.append(member_id)
            if not matches:
                raise ValueError("类型信息中没有 GetCurve")
            dispid = matches[0]
        curve = dynamic.Dispatch(ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True))
        getattr(curve, "IsLine")
        return curve
    except Exception as error:
        raise RuntimeError(f"GetCurve 绑定及兼容调用均失败: {original_error}; {error}") from error


def _curve_span(curve_params):
    """@brief 严格读取官方 11-double 布局；反向边按 SenseFlag 恢复曲线参数。"""
    if curve_params is None or len(curve_params) != 11:
        raise ValueError("GetCurveParams2 必须返回 11 个 double，不能猜测未知布局")
    values = [float(value) for value in curve_params[:8]]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("曲线参数包含非有限值")
    start, end = values[6:8]
    sense = struct.unpack("<ii", struct.pack("<d", float(curve_params[10])))[1]
    if sense not in (0, 1):
        raise ValueError("曲线方向标记无效")
    if not sense:
        start, end = -end, -start
    if start >= end:
        raise ValueError("曲线参数区间为空或顺序无效")
    return start, end


def _positive_mm(value):
    """@brief 拒绝无效/非有限几何量，避免 NaN 在筛选比较中穿透。"""
    result = float(value) * _MM_PER_M
    if not math.isfinite(result) or result <= 0:
        raise ValueError("几何长度必须为有限正数")
    return round(result, 6)


def describe_edge(edge, index=0):
    """
    读取一条边的几何描述。

    参数:
        edge: IEdge 对象。
        index: 该边在遍历顺序中的序号，仅用于标识。

    返回:
        dict，包含 length_mm / mid_point_mm / direction / is_line / is_circle /
        diameter_mm / convexity 等字段；读取失败时 errors 非空。
    """
    descriptor = {
        "index": index,
        "length_mm": None,
        "mid_point_mm": None,
        "direction": None,
        "is_line": None,
        "is_circle": None,
        "diameter_mm": None,
        "convexity": None,
        "errors": [],
        "edge": edge,
    }

    curve_params = None
    curve = None
    span = None
    try:
        curve = _edge_curve(edge)
    except Exception as exc:
        descriptor["errors"].append(f"读取曲线失败: {exc}")
    if curve is not None:
        try:
            curve_params = list(get_com_member(edge, "GetCurveParams2") or [])
            span = _curve_span(curve_params)
        except Exception as exc:
            descriptor["errors"].append(f"读取曲线参数失败: {exc}")
    try:
        if curve is not None:
            is_line, is_circle = get_com_member(curve, "IsLine"), get_com_member(curve, "IsCircle")
            if is_line is None or is_circle is None:
                raise ValueError("曲线类型返回空值")
            descriptor["is_line"], descriptor["is_circle"] = bool(is_line), bool(is_circle)
    except Exception as exc:
        descriptor["errors"].append(f"读取曲线类型失败: {exc}")

    # 边长：IEdge 没有 GetLength，长度在 ICurve::GetLength3(起参, 止参) 上。
    try:
        if curve is not None and span is not None:
            descriptor["length_mm"] = _positive_mm(get_com_member(curve, "GetLength3", *span))
    except Exception as exc:
        descriptor["errors"].append(f"读取边长失败: {exc}")

    # 中点优先用边的起止顶点（IEdge::GetStartVertex/GetEndVertex），
    # 这是不受曲线参数排列差异影响的方式。
    start_mm = end_mm = None
    endpoint_error = None
    try:
        start_mm = _to_mm(list(get_com_member(get_com_member(edge, "GetStartVertex"), "GetPoint") or []))
        end_mm = _to_mm(list(get_com_member(get_com_member(edge, "GetEndVertex"), "GetPoint") or []))
        if len(start_mm) != 3 or len(end_mm) != 3 or not all(math.isfinite(v) for v in start_mm + end_mm):
            raise ValueError("端点必须包含三个有限坐标")
    except Exception as exc:
        endpoint_error = exc
        start_mm = end_mm = None

    if span is not None and (not start_mm or not end_mm):
        start_mm, end_mm = _to_mm(curve_params[:3]), _to_mm(curve_params[3:6])
    if endpoint_error is not None and (not start_mm or not end_mm):
        descriptor["errors"].append(f"读取端点失败: {endpoint_error}")
    if start_mm and end_mm and len(start_mm) >= 3 and len(end_mm) >= 3 and all(math.isfinite(v) for v in start_mm + end_mm):
        descriptor["mid_point_mm"] = [
            round((start_mm[axis] + end_mm[axis]) / 2.0, 6) for axis in range(3)
        ]
        if descriptor["is_line"] is True:
            descriptor["direction"] = _normalize(
                [end_mm[axis] - start_mm[axis] for axis in range(3)]
            )

    # 直径：ICurve::CircleParams 的第 7 个元素是半径。
    # 短圆弧的直径可以远大于弧长，不能用两者的比例限制直径。
    if descriptor["is_circle"] and curve is not None:
        try:
            circle = list(get_com_member(curve, "CircleParams") or [])
            if len(circle) != 7 or not all(math.isfinite(float(value)) for value in circle):
                raise ValueError("CircleParams 必须返回七个有限数值")
            descriptor["diameter_mm"] = _positive_mm(float(circle[6]) * 2.0)
        except Exception as exc:
            descriptor["errors"].append(f"读取直径失败: {exc}")
    elif descriptor["is_line"] is True and descriptor["direction"] is None and curve is not None:
        try:
            line = [float(value) for value in get_com_member(curve, "LineParams")]
            if len(line) != 6 or not all(math.isfinite(value) for value in line):
                raise ValueError("LineParams 必须返回六个有限数值")
            descriptor["direction"] = _normalize(line[3:6])
            if descriptor["direction"] is None:
                raise ValueError("直线方向为零向量")
        except Exception as exc:
            descriptor["errors"].append(f"读取直线方向失败: {exc}")

    return descriptor


def describe_convexity(edge):
    """
    判断边是凸边还是凹边。

    通过边两侧面的法向与边切向的关系判断——这是凸凹的几何定义，不依赖
    SolidWorks 的显示选项。读取失败时返回 None，调用方应放行而不是误判。
    """
    try:
        faces = list(get_com_member(edge, "GetTwoAdjacentFaces2") or [])
    except Exception:
        return None
    if len(faces) < 2:
        return None

    normals = []
    for face in faces[:2]:
        try:
            params = list(get_com_member(face, "GetSurface").GetPlaneParams())
            normals.append(_normalize([float(params[axis]) for axis in range(3, 6)]))
        except Exception:
            try:
                surface = get_com_member(face, "GetSurface")
                normal = _normalize([float(value) for value in get_com_member(surface, "PlaneParams")[3:6]])
                normals.append(normal)
            except Exception:
                return None

    if any(normal is None for normal in normals):
        return None

    # 取边两端点所在面的中点法向更严谨；此处用面参数法向的夹角近似，
    # 对常见的平面-平面直边是准确的，对混合曲面返回 None 由调用方决定。
    dot = sum(a * b for a, b in zip(normals[0], normals[1]))
    return "concave" if dot > 0 else "convex"


def iter_model_edges(model, body_index=None):
    """
    遍历模型所有实体边线。

    参数:
        model: IModelDoc2 对象。
        body_index: 只遍历指定实体；None 表示全部实体。

    返回:
        (descriptors, errors)：边上描述列表与读取过程中的错误列表。
    """
    descriptors = []
    errors = []
    try:
        bodies = list(get_com_member(model, "GetBodies2", 0, False) or [])
    except Exception as exc:
        return descriptors, [f"读取实体列表失败: {exc}"]

    for index, body in enumerate(bodies):
        if body_index is not None and index != body_index:
            continue
        try:
            edges = list(get_com_member(body, "GetEdges") or [])
        except Exception as exc:
            errors.append(f"实体 {index} 读取边线失败: {exc}")
            continue
        for edge_index, edge in enumerate(edges):
            descriptor = describe_edge(edge, index=len(descriptors))
            descriptor["body_index"] = index
            descriptor["edge_index"] = edge_index
            descriptors.append(descriptor)
            errors.extend(f"实体 {index} 边 {edge_index}: {error}" for error in descriptor["errors"])

    return descriptors, errors


def filter_edges(descriptors, axis="all", min_length_mm=None, max_length_mm=None,
                 circular=None, diameter_mm=None, diameter_tolerance_mm=0.05,
                 position_mm=None, position_tolerance_mm=0.1,
                 convex_only=False, concave_only=False, angle_tolerance_deg=1.0):
    """
    按几何条件筛选边线。

    参数:
        axis: "x" | "y" | "z" | "vertical"（等价 z）| "all"。仅对直边生效。
        min_length_mm / max_length_mm: 长度范围筛选。
        circular: True 只保留圆边，False 只保留非圆边，None 不筛选。
        diameter_mm: 圆边直径筛选（需 circular=True）。
        position_mm: 边中点必须靠近的坐标 [x, y, z]（mm）。
        convex_only / concave_only: 按凸凹筛选；凸凹判定失败时不做排除，
            避免因读取失败而漏选用户明确要求的边。

    返回:
        (selected, rejected_reasons)：选中的描述列表与每条边被排除的原因。
    """
    selected = []
    rejected = []

    for name, value in (("min_length_mm", min_length_mm), ("max_length_mm", max_length_mm),
                        ("diameter_mm", diameter_mm), ("diameter_tolerance_mm", diameter_tolerance_mm),
                        ("position_tolerance_mm", position_tolerance_mm), ("angle_tolerance_deg", angle_tolerance_deg)):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} 必须是有限非负数")
    if min_length_mm is not None and max_length_mm is not None and min_length_mm > max_length_mm:
        raise ValueError("最小长度不能大于最大长度")
    if axis not in {"all", "vertical", *_AXIS_VECTORS}:
        raise ValueError("未知选边方向")
    if position_mm is not None and (len(position_mm) != 3 or not all(math.isfinite(value) for value in position_mm)):
        raise ValueError("选边位置必须包含三个有限坐标")

    normalized_axis = "z" if axis == "vertical" else axis
    target_vector = _AXIS_VECTORS.get(normalized_axis)

    for descriptor in descriptors:
        reasons = []

        if descriptor.get("is_line") is None and descriptor.get("is_circle") is None:
            reasons.append("曲线类型未知")

        if min_length_mm is not None:
            length = descriptor.get("length_mm")
            if length is None or not math.isfinite(length) or length < min_length_mm:
                reasons.append(f"长度 {length} < {min_length_mm}")

        if max_length_mm is not None:
            length = descriptor.get("length_mm")
            if length is None or not math.isfinite(length) or length > max_length_mm:
                reasons.append(f"长度 {length} > {max_length_mm}")

        if circular is not None and (descriptor.get("is_circle") is None or bool(descriptor.get("is_circle")) != bool(circular)):
            reasons.append(f"圆边判定不符（要求 circular={circular}）")

        if diameter_mm is not None:
            actual = descriptor.get("diameter_mm")
            if actual is None or not math.isfinite(actual) or actual <= 0:
                reasons.append("直径未知")
            elif abs(actual - diameter_mm) > diameter_tolerance_mm:
                reasons.append(f"直径 {actual} 偏离 {diameter_mm}±{diameter_tolerance_mm}")

        if position_mm is not None:
            midpoint = descriptor.get("mid_point_mm")
            if midpoint is None or len(midpoint) != 3 or not all(math.isfinite(value) for value in midpoint):
                reasons.append("中点未知")
            else:
                distance = max(abs(midpoint[axis] - position_mm[axis]) for axis in range(3))
                if distance > position_tolerance_mm:
                    reasons.append(f"中点偏离 {distance:.3f}mm > {position_tolerance_mm}mm")

        if target_vector is not None:
            if descriptor.get("is_circle"):
                reasons.append("圆边无轴向概念")
            elif not _is_parallel(descriptor.get("direction"), target_vector, angle_tolerance_deg):
                reasons.append(f"方向不平行于 {normalized_axis} 轴")

        if convex_only or concave_only:
            convexity = descriptor.get("convexity")
            if convexity is None:
                convexity = describe_convexity(descriptor.get("edge"))
                descriptor["convexity"] = convexity
            if convexity is not None:
                if convex_only and convexity != "convex":
                    reasons.append(f"非凸边（{convexity}）")
                if concave_only and convexity != "concave":
                    reasons.append(f"非凹边（{convexity}）")

        if reasons:
            rejected.append({"index": descriptor.get("index"), "reasons": reasons})
        else:
            selected.append(descriptor)

    return selected, rejected


def select_edges(model, edge_spec, clear_first=True, mark=0):
    """
    按语义条件选择边线，供后续特征（圆角/倒角）使用。

    参数:
        model: IModelDoc2 对象。
        edge_spec: 筛选条件字典，键与 ``filter_edges`` 参数一致。
        clear_first: 选择前是否清空当前选择集。
        mark: 选择标记。SolidWorks 的特征 API 通过标记区分"要倒角的边"等语义；
            默认 0 适用于 FeatureFillet / InsertFeatureChamfer。

    返回:
        dict：status / selected_count / selected / rejected / errors。

    说明:
        必须至少选中一条边，否则返回 status="error" 而不是静默继续——空选择会让
        SolidWorks 对"当前轮廓"执行操作，产生难以排查的错误特征。
    """
    if clear_first:
        try:
            model.ClearSelection2(True)
        except Exception:
            pass

    descriptors, errors = iter_model_edges(model)
    if not descriptors:
        return {
            "status": "error",
            "selected_count": 0,
            "selected": [],
            "rejected": [],
            "errors": errors + ["模型中未找到任何边线；请确认活动文档是零件且已创建实体。"],
        }

    selected, rejected = filter_edges(descriptors, **(edge_spec or {}))
    if not selected:
        return {
            "status": "error",
            "selected_count": 0,
            "selected": [],
            "rejected_count": len(rejected),
            "rejected_sample": rejected[:50],
            "errors": errors + [
                f"没有边线满足条件 {edge_spec}。已检查 {len(descriptors)} 条边，"
                "请放宽筛选条件或先用 solidworks_list_edges 查看可用边线。"
            ],
        }

    selection_failures = []
    applied = []
    for descriptor in selected:
        edge = descriptor.get("edge")
        if edge is None:
            continue
        if _select_edge(edge, append=True, mark=mark):
            applied.append(descriptor)
        else:
            selection_failures.append(f"边 {descriptor['index']}: Select 返回 False")

    if not applied:
        return {
            "status": "error",
            "selected_count": 0,
            "selected": [],
            "rejected": rejected[:50],
            "errors": errors + selection_failures + ["所有候选边线均选择失败。"],
        }

    return {
        "status": "ok",
        "selected_count": len(applied),
        "selected": [
            {
                "index": item["index"],
                "length_mm": item.get("length_mm"),
                "mid_point_mm": item.get("mid_point_mm"),
                "is_circle": item.get("is_circle"),
                "diameter_mm": item.get("diameter_mm"),
                "convexity": item.get("convexity"),
            }
            for item in applied
        ],
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:20],
        "errors": errors + selection_failures,
    }


def _select_edge(edge, append=True, mark=0):
    """
    选择一条边线。

    Select4 的第二个参数是 Callout，必须是 Dispatch VARIANT；传 Python 的 None 会
    得到 "类型不匹配"（0x80020005）。这与 sw_part._select_com_object 的处理保持一致：
    先用 Select2(append, mark)，失败再退到 Select4(append, callout)。
    """
    for method_name in ("Select2", "Select4"):
        method = getattr(edge, method_name, None)
        if not callable(method):
            continue
        try:
            if method_name == "Select2":
                if bool(method(append, mark)):
                    return True
            elif bool(method(append, create_empty_dispatch_variant())):
                return True
        except Exception:
            continue
    return False
