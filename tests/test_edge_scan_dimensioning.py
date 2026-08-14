"""坐标扫描式尺寸标注无 COM 测试。

find_edge / find_solid_x 为纯函数（注入 picktype），直接测算法；
pickability_ok / force_view_scale 用 FakeView（ScaleRatio）测；
scan_view_dimensions 用模拟选择状态的 FakeDrawing 测端到端编排。
"""
from scripts.sw_drawing import (
    find_edge,
    find_solid_x,
    pickability_ok,
    force_view_scale,
    scan_view_dimensions,
)


# ---- 纯 picktype：模拟一个矩形零件的选择类型 ----

def _box_picktype(xmin, xmax, ymin, ymax, tol=0.0006):
    """@brief 矩形零件 picktype：空=0、边=1、面=2。"""
    def picktype(c, axis, fixed):
        if axis == 0:
            x, y = c, fixed
        else:
            x, y = fixed, c
        if not ((xmin - tol) <= x <= (xmax + tol) and (ymin - tol) <= y <= (ymax + tol)):
            return 0
        near = (abs(x - xmin) < tol or abs(x - xmax) < tol
                or abs(y - ymin) < tol or abs(y - ymax) < tol)
        return 1 if near else 2
    return picktype


# 视图轮廓含余量 [0,0,0.1,0.08]；零件实体 x[0.02,0.08] y[0.01,0.07]
_OUTLINE = [0.0, 0.0, 0.1, 0.08]
_PICK = _box_picktype(0.02, 0.08, 0.01, 0.07)


def test_find_edge_min_max_x():
    fmy = (_OUTLINE[1] + _OUTLINE[3]) / 2.0   # 0.04，落在实体 y 区间
    left = find_edge(_OUTLINE, 0, "min", fmy, _PICK)
    right = find_edge(_OUTLINE, 0, "max", fmy, _PICK)
    assert left is not None and right is not None
    # 落在真实边（0.02 / 0.08）的微扫范围内
    assert abs(left - 0.02) < 0.001
    assert abs(right - 0.08) < 0.001
    assert left < right


def test_find_edge_min_max_y():
    # 固定 X 落在实体面上
    hx = find_solid_x(_OUTLINE, (_OUTLINE[1] + _OUTLINE[3]) / 2.0, _PICK)
    bottom = find_edge(_OUTLINE, 1, "min", hx, _PICK)
    top = find_edge(_OUTLINE, 1, "max", hx, _PICK)
    assert bottom is not None and top is not None
    assert abs(bottom - 0.01) < 0.001
    assert abs(top - 0.07) < 0.001


def test_find_edge_no_geometry_returns_none():
    empty = lambda c, axis, fixed: 0
    assert find_edge(_OUTLINE, 0, "min", 0.04, empty) is None


def test_find_solid_x_lands_on_face():
    ymid = (_OUTLINE[1] + _OUTLINE[3]) / 2.0
    x = find_solid_x(_OUTLINE, ymid, _PICK)
    # 落在实体面区间内（严格内部，远离竖边）
    assert 0.02 < x < 0.08


def test_find_solid_x_fallback_midpoint_when_no_face():
    # 永远只返回边（1）没有面（2）-> 回退中点
    edge_only = lambda c, axis, fixed: 1
    x = find_solid_x(_OUTLINE, 0.04, edge_only)
    assert abs(x - 0.05) < 1e-9   # 轮廓 X 中点


# ---- pickability_ok / force_view_scale：FakeView 读/写 ScaleRatio ----

class _ScaleView:
    def __init__(self, ratio):
        self.ScaleRatio = ratio
        self.UseSheetScale = True
        self.UseParentScale = True
        self._decimal = None

    # ScaleDecimal 属性：force_view_scale 写它；回读走 ScaleRatio
    def _set_decimal(self, v):
        self._decimal = float(v)
        d = round(1.0 / float(v)) if v else 1
        self.ScaleRatio = (1.0, max(1, d))
    ScaleDecimal = property(lambda self: self._decimal, _set_decimal)


def test_pickability_ok_pass_and_blocked():
    assert pickability_ok(_ScaleView((1.0, 1.0)))["status"] == "pass"     # 1:1
    assert pickability_ok(_ScaleView((1.0, 2.0)))["status"] == "pass"     # 1:2 边界
    blocked = pickability_ok(_ScaleView((1.0, 3.0)))                      # 1:3 < 1:2
    assert blocked["status"] == "blocked"
    assert blocked["scale"] < 0.5


def test_force_view_scale_sets_decimal_and_verifies():
    vw = _ScaleView((1.0, 3.0))   # 初始 1:3（不可选）
    r = force_view_scale(vw, 1.0)
    assert r["status"] == "pass"
    assert r["verified"] is True
    assert vw.UseSheetScale is False
    assert vw.UseParentScale is False
    # 回读比例应为 1:1
    assert pickability_ok(vw)["status"] == "pass"


# ---- scan_view_dimensions：模拟选择状态的 FakeDrawing（前/俯视图分占图纸两区）----

class _ScanView:
    def __init__(self, outline):
        self._ol = outline

    def GetOutline(self):
        return self._ol


class _ScanDrawing:
    """@brief 模拟工程图选择：SelectByID2(x,y) -> 按 (x,y) 所在视图区返回 seltype。

    前视图区 y in [0.12,0.20]，实体 x[0.12,0.18] y[0.13,0.19]；
    俯视图区 y in [0.02,0.10]，实体 x[0.12,0.18] y[0.03,0.09]。
    """
    TOL = 0.0006

    def __init__(self):
        self.Extension = self
        self.SelectionManager = self
        self._sel = []

    # --- SelectionManager 接口 ---
    def GetSelectedObjectCount2(self, mark):
        return len(self._sel)

    def GetSelectedObjectType6(self, idx, mark):
        return self._sel[idx - 1] if 1 <= idx <= len(self._sel) else 0

    # --- Extension.SelectByID2（9 参）---
    def SelectByID2(self, name, typ, x, y, z, append, mark, callout, options):
        t = self._seltype_at(float(x), float(y))
        self._sel = self._sel + [t] if append else [t]
        return True

    # --- 文档接口 ---
    def ClearSelection(self):
        self._sel = []

    def AddDimension2(self, x, y, z):
        # 返回一个带 GetDimension 的假 DisplayDimension（供公差套用）
        class DD:
            def GetDimension(self_inner):
                class Dim:
                    def SetToleranceType(self_inner2, t):
                        self.t = t
                        return True

                    def SetToleranceValues(self_inner2, p, m):
                        self.p, self.m = p, m
                        return True
                return Dim()
        return DD()

    def _seltype_at(self, x, y):
        if 0.12 <= y <= 0.20:
            bxmin, bxmax, bymin, bymax = 0.12, 0.18, 0.13, 0.19
        elif 0.02 <= y <= 0.10:
            bxmin, bxmax, bymin, bymax = 0.12, 0.18, 0.03, 0.09
        else:
            return 0
        if not (bxmin - self.TOL <= x <= bxmax + self.TOL
                and bymin - self.TOL <= y <= bymax + self.TOL):
            return 0
        near = (abs(x - bxmin) < self.TOL or abs(x - bxmax) < self.TOL
                or abs(y - bymin) < self.TOL or abs(y - bymax) < self.TOL)
        return 1 if near else 2


def test_scan_view_dimensions_end_to_end():
    front = _ScanView([0.10, 0.12, 0.20, 0.20])
    top = _ScanView([0.10, 0.02, 0.20, 0.10])
    dwg = _ScanDrawing()
    report = scan_view_dimensions(
        dwg, front, top,
        nominal_width_mm=60.0, nominal_height_mm=60.0, nominal_depth_mm=60.0,
        apply_tolerance=True,
    )
    assert report["status"] == "pass"
    assert len(report["dimensions"]) == 3
    for d in report["dimensions"]:
        assert d["display_dimension_set"] is True
        tr = d["tolerance_report"]
        assert tr["status"] == "pass"
        assert tr["plus_mm"] == 0.3          # 60mm -> GB/T 1804-m ±0.3
    # 边坐标定位在两区实体范围内
    lw, rw = report["edges"]["W"]
    assert abs(lw - 0.12) < 0.001 and abs(rw - 0.18) < 0.001


def test_scan_view_dimensions_no_outline():
    class EmptyView:
        def GetOutline(self):
            return []

    report = scan_view_dimensions(
        _ScanDrawing(), EmptyView(), EmptyView(),
        nominal_width_mm=60.0, nominal_height_mm=60.0, nominal_depth_mm=60.0,
    )
    assert report["status"] == "review_required"
    assert report["error_code"] == "DRAWING_SCAN_NO_OUTLINE"
