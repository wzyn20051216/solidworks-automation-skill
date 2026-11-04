"""语义选边回归测试。

锁定真机实测发现的缺陷：``edge.Select4(True, None, False)`` 会抛
"类型不匹配"（0x80020005），因为第二个参数必须是 Dispatch VARIANT 而非 None。

本模块直接导入真实的 scripts.sw_edge_select，不在 sys.modules 里注入替身——
替身会残留在模块缓存中影响后续测试文件的收集。
"""
from pathlib import Path
import sys
import types
import math
import struct

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.sw_edge_select as sw_edge_select  # noqa: E402


class FakeCurve:
    """曲线替身。"""

    def __init__(self, edge):
        self.edge = edge

    def IsLine(self):
        return not self.edge._is_circle

    def IsCircle(self):
        return self.edge._is_circle

    def GetLength3(self, start, end):
        if self.edge._length is not None:
            return self.edge._length
        if self.edge._is_circle:
            return (self.edge._diameter or 0.01) / 2 * (end - start)
        return math.dist(self.edge._start, self.edge._end)

    @property
    def CircleParams(self):
        return [0, 0, 0, 0, 0, 1, (self.edge._diameter if self.edge._diameter is not None else 0.01) / 2]

    @property
    def LineParams(self):
        return [*self.edge._start, *[b-a for a, b in zip(self.edge._start, self.edge._end)]]


class FakeVertex:
    """顶点替身。"""

    def __init__(self, point_m):
        self._point = point_m

    def GetPoint(self):
        return list(self._point)


class FakeEdge:
    """边线替身。记录每次选择调用。"""

    def __init__(self, start_m, end_m, length_m=None, is_circle=False,
                 diameter_m=None, selectable=True, select4_raises=None):
        self._start = start_m
        self._end = end_m
        self._length = length_m
        self._is_circle = is_circle
        self._diameter = diameter_m
        self._selectable = selectable
        self._select4_raises = select4_raises
        self.select_calls = []
        self.selected = False

    def GetCurve(self):
        return FakeCurve(self)

    def GetStartVertex(self):
        return FakeVertex(self._start)

    def GetEndVertex(self):
        return FakeVertex(self._end)

    def GetCurveParams2(self):
        # 官方 IEdge 布局：起终点、参数区间、三项 packed double；这里没有半径。
        end_param = 2 * math.pi if self._is_circle else 1.0
        return [*self._start, *self._end, 0.0, end_param, 0.0, 0.0, struct.unpack("<d", struct.pack("<ii", 0, 1))[0]]

    def Select2(self, append, mark):
        self.select_calls.append(("Select2", append, mark))
        self.selected = self._selectable
        return self._selectable

    def Select4(self, append, callout):
        self.select_calls.append(("Select4", append, callout))
        if self._select4_raises is not None:
            raise self._select4_raises
        self.selected = self._selectable
        return self._selectable


class FakeBody:
    """实体替身。"""

    def __init__(self, edges):
        self._edges = edges

    def GetEdges(self):
        return list(self._edges)


class FakeModel:
    """文档替身。"""

    def __init__(self, edges):
        self._bodies = [FakeBody(edges)] if edges else []
        self.cleared = 0

    def GetBodies2(self, _type, _visible_only):
        return list(self._bodies)

    def ClearSelection2(self, _all):
        self.cleared += 1
        return True


# 一个 100x60x6 板料（米制）的 12 条边
def plate_edges():
    """构成长方体板料的边线集合。"""
    x, y, z = 0.1, 0.06, 0.006
    edges = []
    # 4 条竖直边（沿 Z）
    for corner in [(0, 0), (x, 0), (x, y), (0, y)]:
        edges.append(FakeEdge((corner[0], corner[1], 0.0), (corner[0], corner[1], z)))
    # 4 条沿 X 的边
    for base_z in (0.0, z):
        for y_pos in (0.0, y):
            edges.append(FakeEdge((0.0, y_pos, base_z), (x, y_pos, base_z)))
    # 4 条沿 Y 的边
    for base_z in (0.0, z):
        for x_pos in (0.0, x):
            edges.append(FakeEdge((x_pos, 0.0, base_z), (x_pos, y, base_z)))
    return edges


# ------------------------------------------------------------ 描述

def test_edge_length_and_midpoint_in_mm():
    """@brief 边长与中点必须换算为毫米。"""
    edge = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.01))

    descriptor = sw_edge_select.describe_edge(edge)

    assert descriptor["length_mm"] == pytest.approx(10.0)
    assert descriptor["mid_point_mm"] == pytest.approx([0.0, 0.0, 5.0])
    assert descriptor["is_circle"] is False


def test_edge_direction_is_normalised():
    """@brief 直线方向应归一化，便于按轴筛选。"""
    edge = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.02))

    descriptor = sw_edge_select.describe_edge(edge)

    assert descriptor["direction"] == pytest.approx((0.0, 0.0, 1.0))


def test_circular_edge_diameter_in_mm():
    """@brief 圆边直径换算为毫米。"""
    edge = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), length_m=0.0207, is_circle=True, diameter_m=0.0066)

    descriptor = sw_edge_select.describe_edge(edge)

    assert descriptor["is_circle"] is True
    assert descriptor["diameter_mm"] == pytest.approx(6.6)


def test_invalid_diameter_is_rejected():
    """@brief API 返回负半径时必须报告错误，不用绝对值掩盖非法数据。"""
    edge = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), length_m=0.001, is_circle=True, diameter_m=-0.5)

    descriptor = sw_edge_select.describe_edge(edge)

    assert descriptor["diameter_mm"] is None
    assert descriptor["errors"]


def test_edge_descriptor_reports_errors_without_raising():
    """@brief 成员读取失败时记录错误而不是抛异常。"""

    class BrokenEdge:
        def GetCurve(self):
            raise RuntimeError("boom")

    descriptor = sw_edge_select.describe_edge(BrokenEdge())

    assert descriptor["errors"]


# ------------------------------------------------------------ 筛选

def test_filter_by_z_axis_finds_vertical_edges():
    """@brief 沿 Z 轴筛选应恰好命中 4 条竖直边。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))

    selected, rejected = sw_edge_select.filter_edges(descriptors, axis="z")

    assert len(selected) == 4
    assert all(item["direction"][2] == pytest.approx(1.0) for item in selected)


def test_filter_axis_all_keeps_everything():
    """@brief axis="all" 不做方向过滤。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))

    selected, _ = sw_edge_select.filter_edges(descriptors, axis="all")

    assert len(selected) == len(descriptors) == 12


def test_filter_vertical_alias_matches_z():
    """@brief "vertical" 等价于 z 轴。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))

    by_z, _ = sw_edge_select.filter_edges(descriptors, axis="z")
    by_vertical, _ = sw_edge_select.filter_edges(descriptors, axis="vertical")

    assert len(by_z) == len(by_vertical)


def test_filter_by_length_range():
    """@brief 长度范围筛选。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))

    long_edges, _ = sw_edge_select.filter_edges(descriptors, axis="all", min_length_mm=50.0)

    assert all(item["length_mm"] >= 50.0 for item in long_edges)
    assert len(long_edges) == 8  # 4 条沿 X(100mm) + 4 条沿 Y(60mm)


def test_filter_circular_only():
    """@brief 只保留圆边。"""
    edges = plate_edges() + [
        FakeEdge((0.01, 0.01, 0.0), (0.01, 0.01, 0.0), length_m=0.0207, is_circle=True, diameter_m=0.0066)
    ]
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(edges))

    selected, _ = sw_edge_select.filter_edges(descriptors, circular=True)

    assert len(selected) == 1
    assert selected[0]["diameter_mm"] == pytest.approx(6.6)


def test_filter_by_diameter_tolerance():
    """@brief 直径带公差筛选。"""
    edges = [
        FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), length_m=0.02, is_circle=True, diameter_m=0.0066),
        FakeEdge((0.05, 0.0, 0.0), (0.05, 0.0, 0.0), length_m=0.03, is_circle=True, diameter_m=0.008),
    ]
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(edges))

    selected, _ = sw_edge_select.filter_edges(
        descriptors, circular=True, diameter_mm=6.6, diameter_tolerance_mm=0.05
    )

    assert len(selected) == 1


def test_filter_by_position():
    """@brief 按中点坐标筛选（position_mm 以毫米为单位）。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))
    # 板料有两条起点在 (0,0) 的竖直边：z=0->6 与 z=0->6 各一条，
    # 中点分别为 (0,0,3) 和 (0,0,3)（同一位置在板的前后两个角）。
    selected, _ = sw_edge_select.filter_edges(
        descriptors, axis="z", position_mm=[0.0, 0.0, 3.0], position_tolerance_mm=0.5
    )

    assert len(selected) == 1
    assert selected[0]["mid_point_mm"] == pytest.approx([0.0, 0.0, 3.0])


def test_rejected_entries_carry_reasons():
    """@brief 被排除的边要说明原因，便于用户调整条件。"""
    descriptors, _ = sw_edge_select.iter_model_edges(FakeModel(plate_edges()))

    _, rejected = sw_edge_select.filter_edges(descriptors, axis="z")

    assert len(rejected) == 8
    assert all(item["reasons"] for item in rejected)


# ------------------------------------------------------------ 选择

def test_select_edges_uses_select2():
    """@brief 正常路径走 Select2，避免 Callout 参数问题。"""
    model = FakeModel(plate_edges())

    result = sw_edge_select.select_edges(model, {"axis": "z"})

    assert result["status"] == "ok"
    assert result["selected_count"] == 4


def test_select_edge_passes_dispatch_variant_not_none(monkeypatch):
    """@brief 核心缺陷：Select4 的 Callout 必须是 Dispatch VARIANT，不能是 None。

    真机上报 "类型不匹配"（0x80020005）。这里让 Select2 不可用，强制走 Select4，
    验证传入的是 create_empty_dispatch_variant() 的返回值而不是 None。
    """
    sentinel = object()
    monkeypatch.setattr(sw_edge_select, "create_empty_dispatch_variant", lambda: sentinel)

    edge = FakeEdge((0.0, 0.0, 0.0), (0.0, 0.0, 0.01))
    edge.Select2 = None  # 模拟只有 Select4 的环境
    model = FakeModel([edge])

    sw_edge_select.select_edges(model, {"axis": "z"})

    assert edge.select_calls == [("Select4", True, sentinel)]
    assert edge.select_calls[0][2] is not None


def test_select_falls_back_to_select4_when_select2_fails(monkeypatch):
    """@brief Select2 抛错时回退 Select4，且 Callout 仍不是 None。"""
    sentinel = object()
    monkeypatch.setattr(sw_edge_select, "create_empty_dispatch_variant", lambda: sentinel)

    class Select2Broken(FakeEdge):
        def Select2(self, append, mark):
            self.select_calls.append(("Select2", append, mark))
            raise RuntimeError("类型不匹配")

    edge = Select2Broken((0.0, 0.0, 0.0), (0.0, 0.0, 0.01))
    model = FakeModel([edge])

    sw_edge_select.select_edges(model, {"axis": "z"})

    assert edge.select_calls[0][0] == "Select2"
    assert edge.select_calls[1][0] == "Select4"
    assert edge.select_calls[1][2] is sentinel


def test_select_edges_clears_selection_first():
    """@brief 选择前清空选择集，避免残留影响。"""
    model = FakeModel(plate_edges())

    sw_edge_select.select_edges(model, {"axis": "z"})

    assert model.cleared >= 1


def test_select_edges_errors_when_nothing_matches():
    """@brief 没有边匹配时返回 error，绝不静默继续。

    静默继续会让 SolidWorks 对"当前轮廓"执行圆角，产生难以排查的错误特征。
    """
    model = FakeModel(plate_edges())

    result = sw_edge_select.select_edges(model, {"axis": "z", "min_length_mm": 1000.0})

    assert result["status"] == "error"
    assert result["selected_count"] == 0
    assert result["errors"]
    assert result["rejected_sample"]


def test_select_edges_errors_on_empty_model():
    """@brief 模型没有边线时明确报错。"""
    result = sw_edge_select.select_edges(FakeModel([]), {"axis": "z"})

    assert result["status"] == "error"
    assert any("未找到任何边线" in item for item in result["errors"])


def test_select_edges_reports_partial_failures():
    """@brief 部分边选择失败时报告失败详情但仍返回成功项。"""
    edges = plate_edges()
    edges[0]._selectable = False
    model = FakeModel(edges)

    result = sw_edge_select.select_edges(model, {"axis": "z"})

    assert result["status"] == "ok"
    assert result["selected_count"] == 3
    assert result["errors"]


def test_describe_convexity_tolerates_missing_faces():
    """@brief 凸凹判定失败时返回 None，调用方据此放行而不误排除。"""

    class NoFaces(FakeEdge):
        def GetTwoAdjacentFaces2(self):
            return []

    assert sw_edge_select.describe_convexity(NoFaces((0, 0, 0), (0, 0, 1))) is None


def test_short_arc_can_have_diameter_much_larger_than_length():
    edge = FakeEdge((.25, 0, 0), (.25, .001, 0), length_m=.001, is_circle=True, diameter_m=.5)
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["length_mm"] == 1
    assert descriptor["diameter_mm"] == 500


@pytest.mark.parametrize("params", [[], [10, 20], [10, 20, 30], [0]*8, [0]*12,
                                    [0]*6+[float("nan"), 1, 0, 0, 0]])
def test_unknown_curve_layout_is_rejected(params):
    with pytest.raises(ValueError):
        sw_edge_select._curve_span(params)


def test_reversed_curve_parameters_are_restored_without_guessing():
    params = [0]*6 + [-10, -5, 0, 0, struct.unpack("<d", struct.pack("<ii", 0, 0))[0]]
    assert sw_edge_select._curve_span(params) == (5, 10)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_invalid_curve_length_is_reported(value):
    edge = FakeEdge((0, 0, 0), (.01, 0, 0), length_m=value)
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["length_mm"] is None
    assert any("边长" in error for error in descriptor["errors"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_invalid_circle_radius_is_reported(value):
    edge = FakeEdge((0, 0, 0), (.01, 0, 0), is_circle=True, diameter_m=value)
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["diameter_mm"] is None
    assert any("直径" in error for error in descriptor["errors"])


def test_curve_none_is_not_silent_success():
    edge = FakeEdge((0, 0, 0), (.01, 0, 0))
    edge.GetCurve = lambda: None
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["errors"]
    assert descriptor["is_line"] is None and descriptor["length_mm"] is None


def test_curve_failure_propagates_and_cannot_be_selected_as_non_circle():
    edge = FakeEdge((0, 0, 0), (.01, 0, 0))
    edge.GetCurve = lambda: None
    descriptors, errors = sw_edge_select.iter_model_edges(FakeModel([edge]))
    assert errors and "读取曲线失败" in errors[0]
    selected, rejected = sw_edge_select.filter_edges(descriptors, circular=False)
    assert not selected and rejected
    result = sw_edge_select.select_edges(FakeModel([edge]), {"axis": "all"})
    assert result["status"] == "error" and not edge.select_calls


def test_vertex_failure_uses_parameter_endpoint_difference():
    edge = FakeEdge((.05, .02, 0), (.06, .02, 0))
    edge.GetStartVertex = lambda: None
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["direction"] == pytest.approx((1, 0, 0))


def test_binding_fallback_uses_resolved_member_id(monkeypatch):
    from win32com.client import dynamic
    edge = FakeEdge((0, 0, 0), (.01, 0, 0))
    curve = edge.GetCurve()
    calls = []
    class Ole:
        def GetIDsOfNames(self, locale, name):
            assert name == "GetCurve"
            return 123
        def Invoke(self, dispid, locale, flags, result):
            calls.append(dispid)
            return curve
    edge._oleobj_ = Ole()
    def missing():
        raise AttributeError("member unavailable")
    edge.GetCurve = missing
    monkeypatch.setattr(dynamic, "Dispatch", lambda value: value)
    descriptor = sw_edge_select.describe_edge(edge)
    assert calls == [123]
    assert descriptor["length_mm"] == 10 and not descriptor["errors"]


def test_runtime_failure_is_not_retried_as_binding_failure():
    edge = FakeEdge((0, 0, 0), (.01, 0, 0))
    def broken():
        raise RuntimeError("server failure")
    edge.GetCurve = broken
    with pytest.raises(RuntimeError, match="server failure"):
        sw_edge_select._edge_curve(edge)


@pytest.mark.parametrize("field,criterion", [("length_mm", {"min_length_mm": 1}),
                                           ("diameter_mm", {"diameter_mm": 10})])
def test_nan_descriptor_cannot_pass_numeric_filter(field, criterion):
    descriptor = {field: 10.0, "index": 0, "is_line": field == "length_mm", "is_circle": field == "diameter_mm"}
    assert sw_edge_select.filter_edges([descriptor], **criterion)[0]
    descriptor[field] = float("nan")
    selected, rejected = sw_edge_select.filter_edges([descriptor], **criterion)
    assert not selected and rejected


@pytest.mark.parametrize("criteria", [{"axis": "zz"}, {"min_length_mm": float("nan")},
    {"diameter_tolerance_mm": float("inf")}, {"position_mm": [0, float("nan"), 0]},
    {"min_length_mm": 2, "max_length_mm": 1}, {"diameter_mm": -1}])
def test_invalid_criteria_are_rejected(criteria):
    with pytest.raises(ValueError):
        sw_edge_select.filter_edges([], **criteria)


def test_closed_circle_without_vertex_uses_official_endpoints():
    edge = FakeEdge((.01, 0, 0), (.01, 0, 0), is_circle=True)
    edge.GetStartVertex = edge.GetEndVertex = lambda: None
    descriptor = sw_edge_select.describe_edge(edge)
    assert descriptor["length_mm"] > 0 and not descriptor["errors"]


def test_binding_fallback_can_resolve_type_information(monkeypatch):
    from win32com.client import dynamic
    edge = FakeEdge((0, 0, 0), (.01, 0, 0))
    curve = edge.GetCurve()
    class Info:
        def GetTypeAttr(self): return types.SimpleNamespace(cFuncs=1)
        def GetFuncDesc(self, index): return types.SimpleNamespace(memid=456)
        def GetNames(self, dispid): return ["GetCurve"]
    class Ole:
        def GetIDsOfNames(self, *args): raise AttributeError("name binding failed")
        def GetTypeInfo(self): return Info()
        def Invoke(self, dispid, *args):
            assert dispid == 456
            return curve
    edge._oleobj_ = Ole()
    def missing(): raise AttributeError("member binding failed")
    edge.GetCurve = missing
    monkeypatch.setattr(dynamic, "Dispatch", lambda value: value)
    assert sw_edge_select._edge_curve(edge) is curve
