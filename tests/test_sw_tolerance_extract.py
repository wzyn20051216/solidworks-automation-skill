"""尺寸公差提取的单位、证据缺失和输出安全回归。"""
from __future__ import annotations

import csv
import math
from types import SimpleNamespace

import pytest

from scripts import sw_tolerance_extract as tool


class FakeDimension:
    def __init__(self, kind, value, tolerance_type=2):
        self.FullName = "D1@Sketch1@part"
        self.Tolerance = SimpleNamespace(Type=tolerance_type)
        self.kind = kind
        self.value = value

    def GetType(self):
        return self.kind

    def GetSystemValue3(self, mode, names):
        assert mode == 1 and names is None
        return [self.value]


def test_linear_and_angular_values_and_tolerances_have_correct_units(monkeypatch):
    monkeypatch.setattr(tool, "_tolerance_bound", lambda obj, name: ((-0.001 if "Min" in name else 0.002), None))
    linear, error = tool._dimension_row(FakeDimension(0, 0.05), "Feature")
    assert error is None
    assert linear["unit"] == "mm" and linear["nominal"] == 50
    assert linear["lower"] == -1 and linear["upper"] == 2
    angular, error = tool._dimension_row(FakeDimension(1, math.pi / 2), "Feature")
    assert error is None
    assert angular["unit"] == "deg" and angular["nominal"] == pytest.approx(90)
    assert angular["upper"] == pytest.approx(math.degrees(0.002))


def test_unknown_tolerance_and_missing_values_are_not_guessed(monkeypatch):
    monkeypatch.setattr(tool, "_tolerance_bound", lambda obj, name: (None, "not valid"))
    row, error = tool._dimension_row(FakeDimension(0, 0.05), "Feature")
    assert error is None and row["status"] == "incomplete"
    assert row["lower"] is None and row["upper"] is None
    assert tool._dimension_row(FakeDimension(2, 10), "Feature")[0] is None
    assert tool._dimension_row(FakeDimension(0, None), "Feature")[0] is None
    assert tool._dimension_row(FakeDimension(0, 0.05, 100), "Feature")[0] is None


def test_not_toleranced_does_not_fabricate_limits(monkeypatch):
    monkeypatch.setattr(tool, "_tolerance_bound", lambda *_: pytest.fail("should not read bounds"))
    row, error = tool._dimension_row(FakeDimension(0, 0.04, 0), "Feature")
    assert error is None and row["status"] == "not_toleranced"
    assert row["lower"] is None and row["upper"] is None


def test_csv_prevents_overwrite_and_formula_interpretation(tmp_path):
    output = tmp_path / "tolerances.csv"
    tool.write_csv([{"name": "=1+1", "nominal": 5.0, "unit": "mm"}], output)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["name"] == "'=1+1"
    with pytest.raises(FileExistsError):
        tool.write_csv([], output)


def test_unknown_document_type_is_blocked():
    assert tool.extract_tolerances(SimpleNamespace(GetType=lambda: 99))["status"] == "blocked"


def test_unavailable_feature_tree_is_not_reported_as_an_empty_result():
    assert tool.extract_tolerances(SimpleNamespace(GetType=lambda: 1))["status"] == "blocked"
