"""@brief solidworks-threaded-holes 子技能的离线工程逻辑回归测试。"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "subskills"
    / "solidworks-threaded-holes"
    / "scripts"
    / "create_threaded_hole_template.py"
)
SPEC = importlib.util.spec_from_file_location("solidworks_threaded_hole_template", SCRIPT_PATH)
threaded = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threaded
SPEC.loader.exec_module(threaded)


def make_args(**overrides) -> argparse.Namespace:
    """@brief 生成可覆盖的默认 CLI 参数。"""
    values = {
        "thread": "M6",
        "block_length": 40.0,
        "block_width": 30.0,
        "block_thickness": 16.0,
        "hole_x": 0.0,
        "hole_y": 0.0,
        "tap_drill": None,
        "pilot_depth": None,
        "thread_depth": None,
        "mouth_chamfer": 0.6,
        "through": False,
        "hole_face": "top",
        "thread_class": "6H",
        "handedness": "right",
        "visible_thread": "fallback",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class FakeFeature:
    """@brief 模拟可改名的 SolidWorks 特征。"""

    Name = ""


class FakeFeatureManager:
    """@brief 记录 FeatureCut4 的终止条件。"""

    def __init__(self):
        self.cut_calls = []

    def FeatureCut4(self, *args):
        self.cut_calls.append(args)
        return FakeFeature()


class FakeCutModel:
    """@brief 提供切除函数需要的最小模型接口。"""

    def __init__(self):
        self.FeatureManager = FakeFeatureManager()


class FakeThreadEdge:
    """@brief 记录 ThreadFeatureData 引用圆边的选择标记。"""

    def __init__(self):
        self.select_calls = []

    def Select2(self, append, mark):
        self.select_calls.append((append, mark))
        return True


class FakeThreadData:
    """@brief 模拟可动态赋值的 IThreadFeatureData。"""

    def InitializeThreadData(self):
        return None


class FakeThreadFeatureManager:
    """@brief 模拟 ThreadFeatureData 创建链。"""

    def __init__(self):
        self.data = FakeThreadData()

    def CreateDefinition(self, feature_id):
        assert feature_id == threaded.SW_FM_SWEEP_THREAD
        return self.data

    def CreateFeature(self, data):
        assert data is self.data
        return FakeFeature()


class FakeThreadModel:
    """@brief 提供真实 Thread 创建函数所需的最小模型接口。"""

    def __init__(self):
        self.FeatureManager = FakeThreadFeatureManager()

    def ClearSelection2(self, _clear_all):
        return True


def test_through_hole_uses_through_all_end_condition(monkeypatch) -> None:
    """@brief --through 必须创建真正的 Through All，不能用超深盲孔伪装。"""
    model = FakeCutModel()
    monkeypatch.setattr(threaded, "select_sketch", lambda *_args: None)

    threaded.cut_hole_from_sketch(model, "Sketch1", 16.0, "贯穿攻丝底孔", through=True)

    assert model.FeatureManager.cut_calls[0][3] == threaded.SW_END_COND_THROUGH_ALL


def test_real_thread_uses_official_edge_mark_without_start_entity(monkeypatch) -> None:
    """@brief 平面圆边必须使用选择标记 1，不应再伪造 StartEntity。"""
    model = FakeThreadModel()
    edge = FakeThreadEdge()
    params = threaded.build_params(make_args())
    monkeypatch.setattr(threaded, "locate_hole_mouth_edge", lambda *_args, **_kwargs: (edge, (0.0, 0.0, 0.0)))

    threaded.add_real_thread_feature(model, params)

    assert edge.select_calls == [(False, 1)]
    assert model.FeatureManager.data.Edge is edge
    assert model.FeatureManager.data.Type == "Metric Tap"
    assert not hasattr(model.FeatureManager.data, "StartEntity")
    assert model.FeatureManager.data.DiameterOverride is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"thread_depth": 12.0, "pilot_depth": 5.0}, "螺纹深度"),
        ({"hole_x": 100.0}, "孔位 X"),
        ({"tap_drill": 8.0}, "底孔直径"),
        ({"mouth_chamfer": -1.0}, "mouth_chamfer"),
        ({"block_length": -40.0}, "block_length"),
        ({"hole_x": float("nan")}, "hole_x"),
    ],
)
def test_invalid_engineering_parameters_fail_before_com(overrides, message) -> None:
    """@brief 无效几何和加工参数必须在调用 COM 之前失败。"""
    with pytest.raises(ValueError, match=message):
        threaded.build_params(make_args(**overrides))


def test_through_hole_keeps_physical_depth_and_allows_partial_thread() -> None:
    """@brief 贯穿底孔证据应等于板厚，同时允许部分螺纹深度。"""
    params = threaded.build_params(make_args(through=True, thread_depth=10.0))

    assert params.pilot_depth_mm == 16.0
    assert params.thread_depth_mm == 10.0
    assert params.through_hole is True


def test_custom_metric_pitch_requires_explicit_tap_drill() -> None:
    """@brief 表外公制螺距不得猜测底孔，但可使用用户明确值。"""
    with pytest.raises(ValueError):
        threaded.build_params(make_args(thread="M8x1.0"))

    params = threaded.build_params(make_args(thread="M8x1.0", tap_drill=7.0))
    assert params.thread_label == "M8x1"
    assert params.pitch_mm == 1.0
    assert params.tap_drill_diameter_mm == 7.0


def test_visible_helix_preserves_pitch_and_stays_inside_hole() -> None:
    """@brief 螺旋线圈数可以是小数，轴向深度除以圈数必须等于指定螺距。"""
    params = threaded.build_params(
        make_args(thread="M8", block_thickness=20.0, thread_depth=16.0, pilot_depth=18.0)
    )
    plan = threaded.visible_helix_plan(params)

    assert plan["axial_depth_mm"] / plan["turns"] == pytest.approx(params.pitch_mm)
    assert plan["start_offset_mm"] + plan["axial_depth_mm"] <= params.pilot_depth_mm
    assert plan["segment_count"] == math.ceil(plan["turns"] * 32.0)


@pytest.mark.parametrize("basename", ["../escape", "folder/name", "bad:name", ".."])
def test_basename_cannot_escape_output_directory(basename) -> None:
    """@brief 输出基名不能携带路径或 Windows 非法字符。"""
    with pytest.raises(ValueError):
        threaded.validate_basename(basename)
