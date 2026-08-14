"""尺寸公差标注无 COM 测试：GB/T 1804-m 查表 + set_dimension_tolerance / apply_gb1804m。"""
from scripts.sw_drawing import (
    gb1804m_band,
    set_dimension_tolerance,
    apply_gb1804m,
    SW_TOL_SYMMETRIC,
    SW_TOL_BILATERAL,
)


# ---- GB/T 1804-m 查表（纯函数）----

def test_gb1804m_band_table():
    assert gb1804m_band(3.0) == 0.1      # <=6
    assert gb1804m_band(6.0) == 0.1      # 边界 <=6
    assert gb1804m_band(6.01) == 0.2     # >6, <=30
    assert gb1804m_band(30.0) == 0.2     # 边界 <=30
    assert gb1804m_band(45.0) == 0.3     # >30, <=120 区间
    assert gb1804m_band(120.0) == 0.3    # 边界 <=120
    assert gb1804m_band(250.0) == 0.5    # <=400
    assert gb1804m_band(400.0) == 0.5    # 边界 <=400
    assert gb1804m_band(401.0) == 0.8    # >400
    assert gb1804m_band(1000.0) == 0.8


def test_gb1804m_band_negative_is_absolute():
    # 名义尺寸取绝对值分档
    assert gb1804m_band(-45.0) == 0.3


# ---- 假 IDimension：记录 SetToleranceType / SetToleranceValues 调用（米）----

class FakeIDimension:
    def __init__(self):
        self.tol_type = None
        self.plus_m = None
        self.minus_m = None

    def SetToleranceType(self, t):
        self.tol_type = t
        return True

    def SetToleranceValues(self, plus_m, minus_m):
        self.plus_m = plus_m
        self.minus_m = minus_m
        return True


class FakeDisplayDimension:
    def __init__(self):
        self._dim = FakeIDimension()

    def GetDimension(self):
        return self._dim


def test_set_dimension_tolerance_symmetric_auto_band():
    dd = FakeDisplayDimension()
    # 45mm 名义 -> GB/T 1804-m ±0.3（<=120 分档，自动）
    r = set_dimension_tolerance(dd, nominal_mm=45.0)
    assert r["status"] == "pass"
    assert r["tolerance_type"] == SW_TOL_SYMMETRIC
    assert r["plus_mm"] == 0.3
    assert r["minus_mm"] == 0.3
    assert r["band_source"] == "gb1804m_m"   # 自动分档
    # 内部换算米调用：±0.3mm -> +0.0003 / -0.0003
    dim = dd.GetDimension()
    assert dim.tol_type == SW_TOL_SYMMETRIC
    assert abs(dim.plus_m - 0.0003) < 1e-12
    assert abs(dim.minus_m - (-0.0003)) < 1e-12


def test_set_dimension_tolerance_explicit_bilateral():
    dd = FakeDisplayDimension()
    r = set_dimension_tolerance(dd, 45.0, tol_type=SW_TOL_BILATERAL, plus_mm=0.2, minus_mm=0.1)
    assert r["status"] == "pass"
    assert r["plus_mm"] == 0.2
    assert r["minus_mm"] == 0.1
    assert r["band_source"] == "explicit"    # 显式给定，不查表
    dim = dd.GetDimension()
    assert dim.tol_type == SW_TOL_BILATERAL
    assert abs(dim.plus_m - 0.0002) < 1e-12
    assert abs(dim.minus_m - (-0.0001)) < 1e-12


def test_set_dimension_tolerance_band_by_small_nominal():
    dd = FakeDisplayDimension()
    # 5mm -> ±0.1
    r = set_dimension_tolerance(dd, nominal_mm=5.0)
    assert r["status"] == "pass"
    assert r["plus_mm"] == 0.1
    assert r["minus_mm"] == 0.1
    dim = dd.GetDimension()
    assert abs(dim.plus_m - 0.0001) < 1e-12


def test_apply_gb1804m_is_symmetric_wrapper():
    dd = FakeDisplayDimension()
    r = apply_gb1804m(dd, nominal_mm=250.0)   # <=400 -> ±0.5
    assert r["status"] == "pass"
    assert r["tolerance_type"] == SW_TOL_SYMMETRIC
    assert r["plus_mm"] == 0.5
    dim = dd.GetDimension()
    assert abs(dim.plus_m - 0.0005) < 1e-12


def test_set_dimension_tolerance_no_dimension_object():
    # GetDimension 返回 None -> 结构化失败而非抛错
    class EmptyDisplayDim:
        def GetDimension(self):
            return None

    r = set_dimension_tolerance(EmptyDisplayDim(), nominal_mm=45.0)
    assert r["status"] == "failed"
    assert r["error_code"] == "DRAWING_TOLERANCE_NO_DIMENSION"
