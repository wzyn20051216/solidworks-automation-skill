"""两套独立齿轮实现的交叉校验：本分支纯函数 vs 上游真机验证的 sw_gear。

上游 scripts/sw_gear.py 在 SolidWorks 2026 SP1.1 做过真机回归（m=2, z=24, alpha=20°：
重开后 B-Rep 回读 52 x 52 x 10 mm，内孔 10 mm）。本分支 scripts/standard_parts_geometry.spur_gear_profile
是独立写的纯函数。这里让两者在多组参数上互相校验，并把上游真机数值作为锚点——任何一边公式写错都会在此暴露，
且无需 SolidWorks 即可持续回归。
"""
from __future__ import annotations

import math

import pytest

from scripts import sw_gear
from scripts import standard_parts_geometry as geo

CASES = [(1.0, 20), (2.0, 24), (2.5, 17), (3.0, 40), (0.5, 60), (4.0, 12)]


def _theirs(module, teeth, pressure=20.0):
    spec = sw_gear.SpurGearSpec(module_mm=module, teeth=teeth, face_width_mm=10.0, pressure_angle_deg=pressure)
    return sw_gear.calculate_external_spur_gear(spec)


@pytest.mark.parametrize("module,teeth", CASES)
def test_key_diameters_agree(module, teeth):
    mine = geo.spur_gear_profile(module, teeth)
    theirs = _theirs(module, teeth)
    assert mine.pitch_diameter_mm == pytest.approx(theirs.pitch_diameter_mm)
    assert mine.base_diameter_mm == pytest.approx(theirs.base_diameter_mm)
    assert mine.addendum_diameter_mm == pytest.approx(theirs.outside_diameter_mm)
    assert mine.root_diameter_mm == pytest.approx(theirs.root_diameter_mm)
    assert mine.tooth_thickness_mm == pytest.approx(theirs.tooth_thickness_at_pitch_mm)
    assert mine.circular_pitch_mm == pytest.approx(theirs.circular_pitch_mm)


def test_anchored_to_upstream_real_machine_result():
    """上游 SW2026 SP1.1 真机：m=2, z=24 -> 重开后包围尺寸 52 x 52 mm。"""
    mine = geo.spur_gear_profile(2.0, 24)
    assert mine.addendum_diameter_mm == pytest.approx(52.0)  # 真机回读的外径
    xs = [x for x, _ in mine.profile_xy_mm]
    ys = [y for _, y in mine.profile_xy_mm]
    # 轮廓外包络应不超过真机 52 mm 包围盒（齿顶圆），且与之同量级。
    assert max(xs) - min(xs) <= 52.0 + 1e-6
    assert max(ys) - min(ys) <= 52.0 + 1e-6
    assert max(xs) - min(xs) > 50.0


@pytest.mark.parametrize("module,teeth", CASES)
def test_profile_radial_envelope_agrees(module, teeth):
    mine = geo.spur_gear_profile(module, teeth)
    theirs = _theirs(module, teeth)
    my_r = [math.hypot(x, y) for x, y in mine.profile_xy_mm]
    their_r = [math.hypot(x * 1000.0, y * 1000.0) for x, y in theirs.outline_points_m]  # m -> mm
    assert max(my_r) == pytest.approx(max(their_r), rel=1e-6)
    assert min(my_r) == pytest.approx(min(their_r), rel=1e-6)


@pytest.mark.parametrize("teeth", [8, 12, 14, 16, 17, 18, 24])
def test_undercut_judgement_agrees_with_drc(teeth):
    """上游真机路径的理论根切判定与 DRC 现算的最小无根切齿数必须一致（20° 标准全齿：z_min=17.097 -> 18）。"""
    from scripts.design_rule_check import gear_min_teeth_without_undercut

    theirs = _theirs(2.0, teeth)
    z_min = gear_min_teeth_without_undercut(20.0, 1.0, 0.0)
    assert z_min == theirs.minimum_teeth_without_undercut == 18
    assert theirs.undercut_risk == (teeth < z_min)
