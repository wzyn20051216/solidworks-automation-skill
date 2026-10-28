"""SolidWorks 公差抽取的无 COM 回归测试。"""
from __future__ import annotations

import csv

import pytest

from scripts import sw_tolerance_extract as tol


def test_tolerance_type_label_and_flag():
    assert tol.tolerance_type_label(tol.SW_TOL_BILAT) == "bilateral"
    assert tol.tolerance_type_label(tol.SW_TOL_SYMMETRIC) == "symmetric"
    assert tol.tolerance_type_label(999).startswith("unknown")
    assert tol.is_toleranced(tol.SW_TOL_LIMIT)
    assert not tol.is_toleranced(tol.SW_TOL_NONE)
    assert not tol.is_toleranced(tol.SW_TOL_BASIC)


def test_format_tolerance_variants():
    assert tol.format_tolerance(50, tol.SW_TOL_NONE, 0, 0) == "50"
    assert tol.format_tolerance(50, tol.SW_TOL_SYMMETRIC, 0.05, -0.05) == "50 ±0.05"
    assert tol.format_tolerance(50, tol.SW_TOL_BILAT, 0.05, -0.02) == "50 +0.05/-0.02"
    assert tol.format_tolerance(50, tol.SW_TOL_LIMIT, 0.05, -0.02) == "50.05/49.98"
    assert tol.format_tolerance(50, tol.SW_TOL_MIN, 0, 0) == "50 min"
    assert tol.format_tolerance(50, tol.SW_TOL_MAX, 0, 0) == "50 max"


def test_normalize_tolerance_row_zeroes_untoleranced():
    row = tol.normalize_tolerance_row(
        name="D1", feature="Boss", nominal_mm=20.0, type_code=tol.SW_TOL_NONE, upper_mm=0.3, lower_mm=-0.3
    )
    assert row["toleranced"] is False
    assert row["upper_mm"] == 0.0 and row["lower_mm"] == 0.0
    assert row["display"] == "20"


def test_summarize_tolerances_counts_and_tightest():
    rows = [
        tol.normalize_tolerance_row(name="A", feature="f", nominal_mm=10, type_code=tol.SW_TOL_BILAT, upper_mm=0.1, lower_mm=-0.1),
        tol.normalize_tolerance_row(name="B", feature="f", nominal_mm=10, type_code=tol.SW_TOL_SYMMETRIC, upper_mm=0.02, lower_mm=-0.02),
        tol.normalize_tolerance_row(name="C", feature="f", nominal_mm=10, type_code=tol.SW_TOL_NONE, upper_mm=0, lower_mm=0),
    ]
    summary = tol.summarize_tolerances(rows)
    assert summary["total"] == 3
    assert summary["toleranced"] == 2
    assert summary["by_type"]["bilateral"] == 1
    assert summary["tightest_dimension"] == "B"
    assert summary["tightest_band_mm"] == pytest.approx(0.04)


# ---- COM 遍历用 Fake 对象 ----


class FakeTolerance:
    def __init__(self, type_code, upper_m, lower_m):
        self._type = type_code
        self._upper = upper_m
        self._lower = lower_m

    @property
    def Type(self):
        return self._type

    def GetMaxValue2(self):
        return self._upper

    def GetMinValue2(self):
        return self._lower


class FakeDimension:
    def __init__(self, name, value_m, tolerance):
        self._name = name
        self._value = value_m
        self.Tolerance = tolerance

    @property
    def FullName(self):
        return self._name

    def GetSystemValue3(self, _mode, _cfg):
        return self._value


class FakeDisplayDimension:
    def __init__(self, dimension):
        self._dimension = dimension

    def GetDimension2(self, _index):
        return self._dimension


class FakeFeature:
    def __init__(self, name, display_dimensions):
        self.Name = name
        self._dims = display_dimensions
        self._next = None

    def GetFirstDisplayDimension5(self):
        return self._dims[0] if self._dims else None

    def GetNextDisplayDimension(self, current):
        index = self._dims.index(current)
        return self._dims[index + 1] if index + 1 < len(self._dims) else None

    def GetNextFeature(self):
        return self._next


class FakePartModel:
    def __init__(self, features):
        self._features = features
        for a, b in zip(features, features[1:]):
            a._next = b

    def GetType(self):
        return 1  # swDocPART

    @property
    def FirstFeature(self):
        return self._features[0] if self._features else None


def test_extract_tolerances_from_fake_part():
    dim1 = FakeDimension("D1@Boss", 0.05, FakeTolerance(tol.SW_TOL_BILAT, 0.00005, -0.00002))
    dim2 = FakeDimension("D2@Boss", 0.02, FakeTolerance(tol.SW_TOL_NONE, 0.0, 0.0))
    feature = FakeFeature("Boss-Extrude1", [FakeDisplayDimension(dim1), FakeDisplayDimension(dim2)])
    model = FakePartModel([feature])

    rows = tol.extract_tolerances(model)
    assert len(rows) == 2
    first = rows[0]
    assert first["name"] == "D1@Boss"
    assert first["feature"] == "Boss-Extrude1"
    assert first["nominal_mm"] == pytest.approx(50.0)
    assert first["type"] == "bilateral"
    assert first["upper_mm"] == pytest.approx(0.05)
    assert first["lower_mm"] == pytest.approx(-0.02)
    assert rows[1]["toleranced"] is False


def test_write_tolerance_csv_roundtrip(tmp_path):
    rows = [
        tol.normalize_tolerance_row(name="A", feature="f", nominal_mm=10, type_code=tol.SW_TOL_BILAT, upper_mm=0.1, lower_mm=-0.1),
    ]
    path = tol.write_tolerance_csv(rows, tmp_path / "t.csv")
    assert path.exists()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        parsed = list(csv.DictReader(handle))
    assert parsed[0]["name"] == "A"
    assert parsed[0]["type"] == "bilateral"
    assert parsed[0]["display"] == "10 +0.1/-0.1"
