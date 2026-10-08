"""@brief 阵列按官方签名与选择标记测试，不接受任意参数的假成功。"""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
from fakes import FakeEdge
import sw_pattern


class Manager:
    def __init__(self):
        self.calls = []

    def FeatureLinearPattern4(self, Num1, Spacing1, Num2, Spacing2, FlipDir1, FlipDir2,
        DName1, DName2, GeometryPattern, VaryInstance, HasOffset1, HasOffset2,
        CtrlByNum1, CtrlByNum2, FromCentroid1, FromCentroid2, RevOffset1, RevOffset2, Offset1, Offset2):
        self.calls.append((Num1, Spacing1, Num2, Spacing2, FlipDir1, FlipDir2, DName1, DName2))
        return SimpleNamespace(Name="LinearPattern1")

    def FeatureCircularPattern4(self, Number, Spacing, FlipDirection, DName, GeometryPattern, EqualSpacing, VaryInstance):
        self.calls.append((Number, Spacing, EqualSpacing))
        return SimpleNamespace(Name="CircularPattern1")


def model_with_edge(selectable=True):
    """@brief 只实现官方选择表面，记录 mark 和请求方向。"""
    model = SimpleNamespace(FeatureManager=Manager(), marks=[], cleared=[])
    edge = FakeEdge(start_m=(.04, 0, 0), end_m=(0, 0, 0))
    edge.Select4 = lambda append, data: model.marks.append(data.Mark) is None and selectable
    model.GetBodies2 = lambda *args: [SimpleNamespace(GetEdges=lambda: [edge])]
    model.FeatureByName = lambda name: SimpleNamespace(Select2=lambda append, mark: model.marks.append(mark) is None)
    model.SelectionManager = SimpleNamespace(CreateSelectData=lambda: SimpleNamespace(Mark=0))
    model.Extension = SimpleNamespace(SelectByID2=lambda *args: selectable)
    model.ClearSelection2 = lambda clear: model.cleared.append(clear)
    return model


def test_linear_pattern_direction_and_official_slots():
    """@brief 数量/间距正确且负向原生边被翻转，方向不会乘单位换算。"""
    model = model_with_edge()
    feature = sw_pattern.linear_pattern(model, "Seed", (1, 0, 0), .012, 4)
    assert feature.Name == "LinearPattern1"
    assert model.FeatureManager.calls == [(4, .012, 1, 0.0, True, False, "", "")]
    assert model.marks == [4, 1]
    assert model.cleared == [True, True]


def test_failed_direction_never_creates_a_pattern():
    model = model_with_edge(selectable=False)
    with pytest.raises(ValueError):
        sw_pattern.linear_pattern(model, "Seed", (1, 0, 0), .012, 4)
    assert model.FeatureManager.calls == []
    assert model.cleared[-1] is True


def test_circular_axis_selection_is_required():
    model = model_with_edge(selectable=False)
    with pytest.raises(ValueError):
        sw_pattern.circular_pattern(model, "Seed", "Axis1", 2 * math.pi, 6)
    assert model.FeatureManager.calls == []


def test_circular_pattern_uses_angular_spacing_contract():
    model = model_with_edge()
    sw_pattern.circular_pattern(model, "Seed", "Axis1", 2 * math.pi, 6)
    assert model.FeatureManager.calls == [(6, 2 * math.pi, True)]


@pytest.mark.parametrize("vector", [(0, 0, 0), (math.nan, 0, 0), (0, 1, 0)])
def test_missing_or_invalid_reference_cannot_succeed(vector):
    model = model_with_edge()
    with pytest.raises(ValueError):
        sw_pattern.linear_pattern(model, "Seed", vector, .012, 4)
    assert model.FeatureManager.calls == []
