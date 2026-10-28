"""标准零件几何纯函数的无 COM 回归测试。"""
from __future__ import annotations

import math

import pytest

from scripts import standard_parts_geometry as geo


def _radii(points):
    return [math.hypot(x, y) for x, y in points]


def test_spur_gear_standard_diameters():
    g = geo.spur_gear_profile(2.0, 20, pressure_angle_deg=20.0, bore_diameter_mm=10.0)
    assert g.pitch_diameter_mm == pytest.approx(40.0)
    assert g.base_diameter_mm == pytest.approx(40.0 * math.cos(math.radians(20.0)))
    assert g.addendum_diameter_mm == pytest.approx(44.0)
    assert g.root_diameter_mm == pytest.approx(35.0)
    assert g.tooth_thickness_mm == pytest.approx(math.pi * 2.0 / 2.0)
    assert not g.is_pointed


def test_spur_gear_profile_is_closed_ccw_and_bounded():
    g = geo.spur_gear_profile(2.0, 24)
    assert len(g.profile_xy_mm) > 24  # 至少每齿若干点
    assert geo.polygon_is_closed_ccw(g.profile_xy_mm)
    radii = _radii(g.profile_xy_mm)
    assert min(radii) >= g.root_diameter_mm / 2.0 - 1e-6
    assert max(radii) <= g.addendum_diameter_mm / 2.0 + 1e-6


def test_spur_gear_profile_shift_thickens_tooth():
    base = geo.spur_gear_profile(2.0, 20)
    shifted = geo.spur_gear_profile(2.0, 20, profile_shift_coeff=0.5)
    assert shifted.tooth_thickness_mm > base.tooth_thickness_mm
    assert shifted.addendum_diameter_mm > base.addendum_diameter_mm


def test_spur_gear_pointed_detection():
    pointed = geo.spur_gear_profile(3.0, 9, addendum_coeff=1.4)
    assert pointed.is_pointed


def test_spur_gear_rejects_bad_inputs():
    with pytest.raises(ValueError):
        geo.spur_gear_profile(2.0, 3)  # 齿数太少
    with pytest.raises(ValueError):
        geo.spur_gear_profile(-1.0, 20)  # 模数非正
    with pytest.raises(ValueError):
        geo.spur_gear_profile(2.0, 20, bore_diameter_mm=100.0)  # 孔比齿根圆大


def test_compression_spring_metrics_and_rate():
    s = geo.compression_spring_helix(3.0, 24.0, 60.0, 8.0, shear_modulus_mpa=79300.0)
    assert s.spring_index == pytest.approx(8.0)
    assert s.active_coils == pytest.approx(6.0)
    assert s.solid_length_mm == pytest.approx(24.0)
    assert s.outer_diameter_mm == pytest.approx(27.0)
    expected_rate = 79300.0 * 3.0**4 / (8.0 * 24.0**3 * 6.0)
    assert s.spring_rate_n_per_mm == pytest.approx(expected_rate)
    # 螺旋线沿 +Z 单调递增且首点在 z=0，末点在自由长度。
    zs = [z for _x, _y, z in s.helix_xyz_mm]
    assert zs[0] == pytest.approx(0.0)
    assert zs[-1] == pytest.approx(60.0)
    assert all(b >= a for a, b in zip(zs, zs[1:]))


def test_compression_spring_handedness_and_end_types():
    right = geo.compression_spring_helix(3.0, 24.0, 60.0, 8.0)
    left = geo.compression_spring_helix(3.0, 24.0, 60.0, 8.0, right_handed=False)
    # 第二个采样点的 y 符号相反（旋向不同）。
    assert right.helix_xyz_mm[1][1] * left.helix_xyz_mm[1][1] <= 0.0
    open_end = geo.compression_spring_helix(3.0, 24.0, 60.0, 8.0, end_type="open")
    assert open_end.active_coils == pytest.approx(8.0)


def test_compression_spring_rejects_bad_inputs():
    with pytest.raises(ValueError):
        geo.compression_spring_helix(3.0, 3.0, 60.0, 8.0)  # 中径不大于线径
    with pytest.raises(ValueError):
        geo.compression_spring_helix(3.0, 24.0, 20.0, 8.0)  # 实体长度>=自由长度
    with pytest.raises(ValueError):
        geo.compression_spring_helix(3.0, 24.0, 60.0, 1.0)  # 有效圈数非正


def test_roller_sprocket_standard_diameters():
    sp = geo.roller_sprocket_profile(12.7, 7.92, 17, bore_diameter_mm=20.0)
    half = math.pi / 17
    assert sp.pitch_diameter_mm == pytest.approx(12.7 / math.sin(half))
    assert sp.outside_diameter_mm == pytest.approx(12.7 * (0.6 + 1.0 / math.tan(half)))
    assert sp.root_diameter_mm == pytest.approx(sp.pitch_diameter_mm - 7.92)
    assert sp.seating_radius_mm == pytest.approx(0.505 * 7.92)
    assert geo.polygon_is_closed_ccw(sp.profile_xy_mm)


def test_roller_sprocket_rejects_bad_inputs():
    with pytest.raises(ValueError):
        geo.roller_sprocket_profile(12.7, 7.92, 5)  # 齿数太少
    with pytest.raises(ValueError):
        geo.roller_sprocket_profile(12.7, 20.0, 17)  # 滚子直径>=节距
    with pytest.raises(ValueError):
        geo.roller_sprocket_profile(12.7, 7.92, 17, bore_diameter_mm=100.0)  # 孔比齿根圆大


def test_involute_function():
    assert geo.involute(math.radians(20.0)) == pytest.approx(math.tan(math.radians(20.0)) - math.radians(20.0))
