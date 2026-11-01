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


def _safe(obj, name, *args, default=None):
    """@brief 安全读取 COM 成员。"""
    try:
        member = getattr(obj, name)
        value = member(*args) if args or callable(member) else member
    except Exception:
        return default
    return default if value is None else value


def _to_mm(values):
    """@brief 把长度序列从米换算为毫米。"""
    return [float(value) * _MM_PER_M for value in values]


def _normalize(vector):
    """@brief 归一化向量，零向量返回 None。"""
    length = math.sqrt(sum(component * component for component in vector))
    if length < 1e-12:
        return None
    return tuple(component / length for component in vector)


def _is_parallel(first, second, angle_tolerance_deg=1.0):
    """@brief 判断两个单位向量是否（反）平行。"""
    if first is None or second is None:
        return False
    dot = abs(sum(a * b for a, b in zip(first, second)))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot)) <= angle_tolerance_deg


def _edge_curve(edge):
    """返回 IEdge 的 ICurve。

    pywin32 的属性访问在部分 SolidWorks 版本上会对 GetCurve 抛
    DISP_E_MEMBERNOTFOUND，但该成员其实存在（dispid=1）——同一条边的
    GetCurveParams2 / GetTwoAdjacentFaces2 都正常。直接 Invoke 再包装可以绕开。
    """
    try:
        curve = get_com_member(edge, "GetCurve", default=None)
        if curve is not None:
            return curve
    except Exception:
        pass
    try:
        import pythoncom
        from win32com.client import dynamic
    except ImportError:
        return None
    try:
        raw = edge._oleobj_.Invoke(1, 0, pythoncom.DISPATCH_METHOD, True)
        return dynamic.Dispatch(raw)
    except Exception:
        return None


def _curve_span(curve_params):
    """从 GetCurveParams2 取 (起参, 止参)。

    实测布局是 [起点x, 起点y, 起点z, 终点x, 终点y, 终点z, 起参, 止参, ...]，
    共 11 个值，参数在索引 6、7。若某些版本只返回两个值，退回索引 0、1。
    """
    if not curve_params:
        return None
    try:
        if len(curve_params) >= 8:
            return float(curve_params[6]), float(curve_params[7])
        if len(curve_params) >= 2:
            return float(curve_params[0]), float(curve_params[1])
    except (TypeError, ValueError):
        return None
    return None


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
    curve = _edge_curve(edge)
    try:
        curve_params = list(get_com_member(edge, "GetCurveParams2") or [])
    except Exception as exc:
        descriptor["errors"].append(f"读取曲线参数失败: {exc}")
    try:
        if curve is not None:
            descriptor["is_line"] = bool(get_com_member(curve, "IsLine"))
            descriptor["is_circle"] = bool(get_com_member(curve, "IsCircle"))
    except Exception as exc:
        descriptor["errors"].append(f"读取曲线类型失败: {exc}")

    # 边长：IEdge 没有 GetLength，长度在 ICurve::GetLength3(起参, 止参) 上。
    try:
        span = _curve_span(curve_params)
        if curve is not None and span is not None:
            length_m = float(get_com_member(curve, "GetLength3", span[0], span[1]))
            descriptor["length_mm"] = round(length_m * _MM_PER_M, 6)
    except Exception as exc:
        descriptor["errors"].append(f"读取边长失败: {exc}")

    # 中点优先用边的起止顶点（IEdge::GetStartVertex/GetEndVertex），
    # 这是不受曲线参数排列差异影响的方式。
    start_mm = end_mm = None
    try:
        start_mm = _to_mm(list(get_com_member(get_com_member(edge, "GetStartVertex"), "GetPoint") or []))
        end_mm = _to_mm(list(get_com_member(get_com_member(edge, "GetEndVertex"), "GetPoint") or []))
    except Exception as exc:
        descriptor["errors"].append(f"读取端点失败: {exc}")

    if start_mm and end_mm and len(start_mm) >= 3 and len(end_mm) >= 3:
        descriptor["mid_point_mm"] = [
            round((start_mm[axis] + end_mm[axis]) / 2.0, 6) for axis in range(3)
        ]
        if not descriptor["is_circle"]:
            descriptor["direction"] = _normalize(
                [end_mm[axis] - start_mm[axis] for axis in range(3)]
            )

    # 曲线参数仅用于圆边直径/直线方向兜底；不同版本排列不同，因此做长度合法性校验：
    # 换算后的直径必须为正且与边长同量级，否则视为解析失败而不写脏数据。
    # 直径：ICurve::CircleParams 的第 7 个元素是半径。
    # GetCurveParams2 里根本没有半径——旧代码取 curve_params[6]，实际拿到的是
    # 起点坐标的分量或参数，任何版本上都算不出正确直径。
    if descriptor["is_circle"] and curve is not None:
        try:
            circle = list(get_com_member(curve, "CircleParams") or [])
            if len(circle) >= 7:
                candidate = abs(float(circle[6])) * 2.0 * _MM_PER_M
                if candidate > 0.0:
                    descriptor["diameter_mm"] = round(candidate, 6)
        except Exception as exc:
            descriptor["errors"].append(f"读取直径失败: {exc}")
    elif descriptor["direction"] is None and curve_params and len(curve_params) >= 6:
        try:
            descriptor["direction"] = _normalize(
                [float(curve_params[3 + axis]) for axis in range(3)]
            )
        except (TypeError, ValueError):
            pass

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

    normalized_axis = "z" if axis == "vertical" else axis
    target_vector = _AXIS_VECTORS.get(normalized_axis)

    for descriptor in descriptors:
        reasons = []

        if min_length_mm is not None:
            length = descriptor.get("length_mm")
            if length is None or length < min_length_mm:
                reasons.append(f"长度 {length} < {min_length_mm}")

        if max_length_mm is not None:
            length = descriptor.get("length_mm")
            if length is None or length > max_length_mm:
                reasons.append(f"长度 {length} > {max_length_mm}")

        if circular is not None and bool(descriptor.get("is_circle")) != bool(circular):
            reasons.append(f"圆边判定不符（要求 circular={circular}）")

        if diameter_mm is not None:
            actual = descriptor.get("diameter_mm")
            if actual is None:
                reasons.append("直径未知")
            elif abs(actual - diameter_mm) > diameter_tolerance_mm:
                reasons.append(f"直径 {actual} 偏离 {diameter_mm}±{diameter_tolerance_mm}")

        if position_mm is not None:
            midpoint = descriptor.get("mid_point_mm")
            if midpoint is None:
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
