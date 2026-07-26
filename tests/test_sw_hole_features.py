"""@brief 复杂孔槽创建封装的离线回归测试。"""

from contextlib import contextmanager

import pytest

from scripts import sw_hole_features as holes


class FakeFeature:
    """@brief 模拟 SolidWorks Feature。"""

    Name = ""


class FakeFeatureManager:
    """@brief 记录沉头锥形切除参数。"""

    def __init__(self):
        self.cut_calls = []
        self.chamfer_calls = []

    def FeatureCut4(self, *args):
        self.cut_calls.append(args)
        return FakeFeature()

    def InsertFeatureChamfer(self, *args):
        self.chamfer_calls.append(args)
        return FakeFeature()


class FakeModel:
    """@brief 仅提供复杂孔模块直接访问的 FeatureManager。"""

    def __init__(self):
        self.FeatureManager = FakeFeatureManager()

    def ClearSelection2(self, clear_all):
        return clear_all


@pytest.fixture
def fake_ops(monkeypatch):
    """@brief 用可观测假对象替换草图与普通切除。"""
    calls = {"circles": [], "slots": [], "cuts": [], "selected": []}

    @contextmanager
    def fake_sketch(model, plane_name):
        yield f"Sketch_{plane_name}"

    def fake_circle(model, x, y, radius):
        calls["circles"].append((x, y, radius))
        return object()

    def fake_slot(model, x1, y1, x2, y2, radius):
        calls["slots"].append((x1, y1, x2, y2, radius))
        return [object()]

    def fake_cut(model, sketch_name, depth):
        calls["cuts"].append((sketch_name, depth))
        return FakeFeature()

    monkeypatch.setattr(holes, "sketch", fake_sketch)
    monkeypatch.setattr(holes, "sketch_circle", fake_circle)
    monkeypatch.setattr(holes, "sketch_slot", fake_slot)
    monkeypatch.setattr(holes, "extrude_cut", fake_cut)
    monkeypatch.setattr(holes, "_find_hole_entry_edge", lambda *args: object())
    monkeypatch.setattr(holes, "_select_com_object", lambda edge, append=False, mark=0: True)
    return calls


def test_counterbore_creates_through_and_recess_cuts(fake_ops) -> None:
    evidence = holes.create_counterbore_hole(FakeModel(), (0.02, 0.03), 0.006, 0.012, 0.004)

    assert fake_ops["circles"] == [(0.02, 0.03, 0.003), (0.02, 0.03, 0.006)]
    assert [depth for _sketch, depth in fake_ops["cuts"]] == [0.0, 0.004]
    assert evidence["feature_kind"] == "counterbore"
    assert evidence["counterbore_diameter_mm"] == 12.0
    assert evidence["counterbore_depth_mm"] == 4.0


def test_countersink_computes_depth_from_included_angle(fake_ops) -> None:
    model = FakeModel()
    evidence = holes.create_countersink_hole(model, (0.01, 0.02), 0.005, 0.010, included_angle_deg=90.0)

    assert evidence["feature_kind"] == "countersink"
    assert evidence["countersink_angle_deg"] == 90.0
    assert model.FeatureManager.chamfer_calls[0][0:2] == (4, 1)
    assert model.FeatureManager.chamfer_calls[0][2] == pytest.approx(0.0025)
    assert model.FeatureManager.chamfer_calls[0][3] == pytest.approx(0.7853981633974483)


def test_semicircular_slot_uses_half_width_as_slot_radius(fake_ops) -> None:
    evidence = holes.create_semicircular_slot(FakeModel(), (0.01, 0.02), (0.04, 0.02), 0.010, depth=0.0)

    assert fake_ops["slots"] == [(0.01, 0.02, 0.04, 0.02, 0.005)]
    assert fake_ops["cuts"][0][1] == 0.0
    assert evidence["through"] is True
    assert evidence["width_mm"] == 10.0


def test_hole_pattern_preserves_explicit_positions(fake_ops) -> None:
    evidence = holes.create_hole_pattern(
        FakeModel(),
        [(0.01, 0.02), (0.03, 0.04)],
        holes.create_blind_hole,
        diameter=0.008,
        depth=0.010,
        name="定位盲孔",
    )

    assert [item["center_mm"] for item in evidence] == [[10.0, 20.0], [30.0, 40.0]]
    assert [item["feature_names"][0] for item in evidence] == ["定位盲孔_1", "定位盲孔_2"]


@pytest.mark.parametrize(
    "call",
    [
        lambda model: holes.create_blind_hole(model, (0.0, 0.0), 0.0, 0.01),
        lambda model: holes.create_counterbore_hole(model, (0.0, 0.0), 0.008, 0.006, 0.003),
        lambda model: holes.create_countersink_hole(model, (0.0, 0.0), 0.005, 0.010, 180.0),
        lambda model: holes.create_semicircular_slot(model, (0.0, 0.0), (0.0, 0.0), 0.010),
    ],
)
def test_invalid_hole_parameters_fail_before_com(call, fake_ops) -> None:
    with pytest.raises(ValueError):
        call(FakeModel())
