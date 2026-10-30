"""电机扭矩核验：手算锚点 + 物理等价/符号/退化分支 + 判定语义。纯函数，无需 SolidWorks。

锚点来自事先手算的完整算例（水平丝杠轴：m=50kg, μ=0.1, 导程10mm, η=0.9, 行程500mm, v=0.5m/s, a=2m/s²,
丝杠 ⌀20×600 钢, 转子惯量 0.5e-4 kg·m²）。平动负载的加速力经传动效率换算，常量独立按公式计算。
"""
from __future__ import annotations

import math

import pytest

from scripts import drive_sizing as ds

G = 9.80665


def _screw_spec(**over):
    spec = {
        "id": "X轴",
        "load": {"mass_kg": 50, "incline_deg": 0, "friction_coeff": 0.1},
        "motion": {"distance_mm": 500, "max_speed_mm_s": 500, "accel_mm_s2": 2000, "dwell_s": 0, "round_trip": False},
        "transmission": {"type": "lead_screw", "lead_mm": 10, "efficiency": 0.9, "screw_diameter_mm": 20, "screw_length_mm": 600},
        "motor": {"rotor_inertia_kgm2": 0.5e-4},
    }
    for key, value in over.items():
        spec[key] = {**spec[key], **value} if isinstance(value, dict) else value
    return spec


def test_hand_computed_anchors():
    r = ds.compute_drive(_screw_spec())
    assert r["t_static_forward_nm"] == pytest.approx(0.086710, rel=1e-4)
    assert r["t_acc_nm"] == pytest.approx(0.332642, rel=1e-4)
    assert r["t_peak_nm"] == pytest.approx(0.419352, rel=1e-4)
    assert r["n_max_rpm"] == pytest.approx(3000.0, rel=1e-9)
    assert r["inertia_ratio"] == pytest.approx(4.0127, rel=1e-4)
    assert r["t_rms_nm"] == pytest.approx(0.227550, rel=1e-4)
    p = r["profile"]
    assert (p["t_acc"], p["t_cruise"], p["triangular"]) == (pytest.approx(0.25), pytest.approx(0.75), False)


def test_decel_torque_is_negative_regeneration_and_peak_uses_abs():
    r = ds.compute_drive(_screw_spec())
    decel = next(p for p in r["phases"] if p["name"].endswith("减速"))
    assert decel["torque_nm"] == pytest.approx(-0.245933, rel=1e-4)  # 回馈近似值
    assert r["t_peak_nm"] == pytest.approx(max(abs(p["torque_nm"]) for p in r["phases"]))


def test_belt_equivalent_to_screw_when_radius_equals_lead_over_2pi():
    """物理等价：丝杠导程 p ≡ 皮带轮半径 r=p/2π，且效率相同、不计丝杠自身惯量 -> 转矩/惯量/转速必须一致。
    两条完全不同的代码路径，是对公式与单位换算的独立检验。"""
    p_mm = 10.0
    screw = _screw_spec(transmission={"screw_diameter_mm": None, "screw_length_mm": None})
    screw["transmission"].pop("screw_diameter_mm"); screw["transmission"].pop("screw_length_mm")
    belt = _screw_spec()
    belt["transmission"] = {"type": "belt", "pulley_radius_mm": p_mm / (2 * math.pi), "efficiency": 0.9}
    a, b = ds.compute_drive(screw), ds.compute_drive(belt)
    for key in ("t_static_forward_nm", "t_acc_nm", "t_peak_nm", "t_rms_nm", "n_max_rpm", "j_reflected_kgm2", "inertia_ratio"):
        assert a[key] == pytest.approx(b[key], rel=1e-9), key


def test_gear_ratio_reflection_laws():
    """减速比 i：电机轴转矩 ∝ 1/(i·η_g)，折算惯量 ∝ 1/i²，转速 ∝ i。"""
    base = ds.compute_drive(_screw_spec(motor={"rotor_inertia_kgm2": 1e-9}))
    geared = ds.compute_drive(_screw_spec(transmission={"gear_ratio": 4.0, "gear_efficiency": 0.8}, motor={"rotor_inertia_kgm2": 1e-9}))
    assert geared["t_static_forward_nm"] == pytest.approx(base["t_static_forward_nm"] / (4.0 * 0.8), rel=1e-9)
    assert geared["j_reflected_kgm2"] == pytest.approx(base["j_reflected_kgm2"] / 16.0, rel=1e-9)
    assert geared["n_max_rpm"] == pytest.approx(base["n_max_rpm"] * 4.0, rel=1e-9)


def test_triangular_profile_when_distance_too_short():
    prof = ds.motion_profile(distance_m=0.05, max_speed_m_s=0.5, accel_m_s2=2.0)  # 加速到0.5需0.0625m>0.025
    assert prof["triangular"] is True
    assert prof["v_peak"] == pytest.approx(math.sqrt(2.0 * 0.05))
    assert prof["t_cruise"] == 0.0
    assert prof["t_move"] == pytest.approx(2 * prof["v_peak"] / 2.0)
    # 位移守恒：对称三角形总位移 = v_peak * t_move / 2
    assert prof["v_peak"] * prof["t_move"] / 2.0 == pytest.approx(0.05)


def test_trapezoid_displacement_conservation():
    prof = ds.motion_profile(0.5, 0.5, 2.0)
    distance = prof["v_peak"] * (prof["t_move"] + prof["t_cruise"]) / 2.0  # 梯形面积
    assert distance == pytest.approx(0.5)


def test_vertical_return_gravity_assists():
    """竖直轴：正向克服重力，返程重力助力 -> 返程静态转矩小于正向，且（忽略摩擦时）符号相反。"""
    spec = _screw_spec(load={"incline_deg": 90, "friction_coeff": 0.0}, motion={"round_trip": True})
    r = ds.compute_drive(spec)
    assert r["t_static_forward_nm"] > 0 > r["t_static_return_nm"]
    assert r["t_static_forward_nm"] == pytest.approx(-r["t_static_return_nm"], rel=1e-9)
    assert r["holds_gravity"] is True


def test_friction_opposes_motion_in_both_directions():
    r = ds.compute_drive(_screw_spec(motion={"round_trip": True}))  # 水平：只有摩擦
    assert r["t_static_forward_nm"] == pytest.approx(r["t_static_return_nm"], rel=1e-12)
    assert r["t_static_forward_nm"] > 0


def test_dwell_without_brake_holds_gravity_only_on_inclined_axis():
    horiz = ds.compute_drive(_screw_spec(motion={"dwell_s": 1.0}))
    dwell_h = next(p for p in horiz["phases"] if p["name"].endswith("驻留"))
    assert dwell_h["torque_nm"] == pytest.approx(0.0, abs=1e-12)
    vert = ds.compute_drive(_screw_spec(load={"incline_deg": 90}, motion={"dwell_s": 1.0}))
    dwell_v = next(p for p in vert["phases"] if p["name"].endswith("驻留"))
    assert dwell_v["torque_nm"] > 0
    braked = ds.compute_drive(_screw_spec(load={"incline_deg": 90}, motion={"dwell_s": 1.0}, motor={"has_brake": True}))
    assert next(p for p in braked["phases"] if p["name"].endswith("驻留"))["torque_nm"] == 0.0


def test_kgcm2_inertia_unit():
    a = ds.compute_drive(_screw_spec(motor={"rotor_inertia_kgm2": 0.5e-4}))
    spec = _screw_spec(); spec["motor"] = {"rotor_inertia_kgcm2": 0.5}
    assert ds.compute_drive(spec)["inertia_ratio"] == pytest.approx(a["inertia_ratio"], rel=1e-12)


@pytest.mark.parametrize("bad", [
    {"load": {"mass_kg": 0}}, {"load": {"mass_kg": -1}}, {"motion": {"distance_mm": 0}},
    {"transmission": {"efficiency": 1.2}}, {"transmission": {"efficiency": 0}}, {"transmission": {"type": "magic"}},
    {"transmission": {"lead_mm": -3}}, {"motion": {"accel_mm_s2": float("nan")}},
])
def test_invalid_specs_rejected(bad):
    with pytest.raises(ValueError):
        ds.compute_drive(_screw_spec(**bad))


def test_missing_sections_rejected():
    with pytest.raises(ValueError):
        ds.compute_drive({"load": {"mass_kg": 1}})


# ---- 判定语义 ----


def _motor(**kw):
    base = {"peak_torque_nm": 1.5, "rated_torque_nm": 0.64, "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 0.5e-4}
    base.update(kw)
    return base


def _ids(out):
    return {c["id"]: c for c in out["checks"]}


def test_plausible_torque_still_requires_review_and_reports_margin():
    out = ds.evaluate_drive(_screw_spec(motor=_motor()))
    c = _ids(out)
    # 峰值 0.419352×1.5 ≤ 1.5，仍需核对未建模的反向效率。
    assert c["DRC-DRV-001"]["status"] == "info" and c["DRC-DRV-001"]["margin_pct"] == pytest.approx((1.5 - 0.419352 * 1.5) / 1.5 * 100, abs=0.05)
    assert c["DRC-DRV-002"]["status"] == "info"
    assert c["DRC-DRV-003"]["status"] == "pass"
    assert c["DRC-DRV-004"]["status"] == "pass"
    assert out["controlling"] in {"DRC-DRV-001", "DRC-DRV-002"}


def test_undersized_motor_fails_peak_and_rms():
    out = ds.evaluate_drive(_screw_spec(motor=_motor(peak_torque_nm=0.5, rated_torque_nm=0.2)))
    c = _ids(out)
    assert c["DRC-DRV-001"]["status"] == "fail" and c["DRC-DRV-002"]["status"] == "fail"


def test_overspeed_fails_and_above_rated_warns():
    assert _ids(ds.evaluate_drive(_screw_spec(motor=_motor(max_speed_rpm=2500))))["DRC-DRV-003"]["status"] == "fail"   # 3000>2500
    assert _ids(ds.evaluate_drive(_screw_spec(motor=_motor(rated_speed_rpm=2000, max_speed_rpm=5000))))["DRC-DRV-003"]["status"] == "warning"


def test_inertia_ratio_thresholds_and_profile_override():
    heavy = _screw_spec(load={"mass_kg": 400}, motor=_motor())   # 惯量比显著增大
    out = ds.evaluate_drive(heavy)
    ratio = out["result"]["inertia_ratio"]
    assert ratio > 10 and _ids(out)["DRC-DRV-004"]["status"] == "fail"
    relaxed = ds.evaluate_drive(heavy, {"driveInertiaRatioMax": ratio + 5, "driveInertiaRatioWarn": ratio + 1})
    assert _ids(relaxed)["DRC-DRV-004"]["status"] == "pass"


def test_vertical_axis_without_brake_is_critical():
    spec = _screw_spec(load={"incline_deg": 90}, motor=_motor())
    c = _ids(ds.evaluate_drive(spec))["DRC-DRV-005"]
    assert c["status"] == "fail" and c["severity"] == "critical"
    braked = _ids(ds.evaluate_drive(_screw_spec(load={"incline_deg": 90}, motor=_motor(has_brake=True))))["DRC-DRV-005"]
    assert braked["status"] == "info"


def test_missing_rotor_inertia_does_not_pass_torque_checks():
    spec = _screw_spec()
    spec["motor"] = {key: value for key, value in _motor().items() if key != "rotor_inertia_kgm2"}
    checks = _ids(ds.evaluate_drive(spec))
    assert checks["DRC-DRV-001"]["status"] == "info"
    assert checks["DRC-DRV-002"]["status"] == "info"


def test_missing_motor_data_gives_info_not_pass():
    spec = _screw_spec()
    spec["motor"] = {}   # 显式清空（辅助函数是“合并”语义，传 {} 会保留默认值，测不到缺数据路径）
    out = ds.evaluate_drive(spec)
    c = _ids(out)
    assert c["DRC-DRV-001"]["status"] == "info" and c["DRC-DRV-002"]["status"] == "info"
    assert c["DRC-DRV-004"]["status"] == "info"  # 缺转子惯量：不能当作通过


def test_safety_factor_override_flips_result():
    spec = _screw_spec(motor=_motor(peak_torque_nm=0.7))
    assert _ids(ds.evaluate_drive(spec))["DRC-DRV-001"]["status"] == "info"
    assert _ids(ds.evaluate_drive(spec, {"driveTorqueSafetyFactor": 2.0}))["DRC-DRV-001"]["status"] == "fail"


def test_acceleration_load_includes_transmission_and_gear_efficiency():
    spec = _screw_spec(transmission={"gear_ratio": 4, "gear_efficiency": 0.8})
    result = ds.compute_drive(spec)
    j_load = 50 * (0.01 / (2 * math.pi)) ** 2
    j_screw = math.pi * 7850 * 0.6 * 0.02 ** 4 / 32
    alpha = 2 * 2 * math.pi / 0.01 * 4
    expected = ((j_load / 0.9 + j_screw) / (4 ** 2 * 0.8) + 0.5e-4) * alpha
    assert result["t_acc_nm"] == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("section,key,value", [
    ("motor", "has_brake", "false"),
    ("motion", "round_trip", "false"),
    ("load", "incline_deg", -5),
    ("load", "incline_deg", 91),
    ("transmission", "screw_length_mm", None),
])
def test_rejects_ambiguous_or_incomplete_safety_inputs(section, key, value):
    spec = _screw_spec()
    spec[section][key] = value
    with pytest.raises(ValueError):
        ds.evaluate_drive(spec)


@pytest.mark.parametrize("limits", [
    {"driveRmsUtilizationMax": 0},
    {"driveRmsUtilizationMax": 1.1},
    {"driveTorqueSafetyFactor": float("nan")},
    {"driveTorqueSafetyFactor": 0.5},
    {"driveInertiaRatioWarn": 11},
    {"unknown": 1},
])
def test_rejects_invalid_safety_limits(limits):
    with pytest.raises(ValueError):
        ds.evaluate_drive(_screw_spec(), limits)


def test_missing_max_speed_is_not_reported_as_a_pass():
    spec = _screw_spec(motor={"rated_speed_rpm": 5000})
    result = ds.evaluate_drive(spec)
    assert _ids(result)["DRC-DRV-003"]["status"] == "info"
    assert result["reviewRequired"] is True
