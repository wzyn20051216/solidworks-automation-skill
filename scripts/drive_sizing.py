"""
@file drive_sizing.py
@brief 电机扭矩核验：给定机构与运动曲线，判断所选电机/减速机是否满足场景。

定位：选型**初筛与审计辅助**，不替代厂商选型软件与工程师签署。纯函数、无 COM 依赖、可离线单测；
结果以与 DRC 一致的 check 结构返回（id/category/status/severity/message），由 design_rule_check 并入
设计审计体系（指纹、让步单、基线 diff、风险分、回归门禁全部复用）。

约定（务必阅读，错一个符号就是错的）：
- 单位：质量 kg、力 N、转矩 N·m、惯量 kg·m²、长度 mm（输入）、时间 s、转速 rpm。
- 运动方向：“正向”= 朝**上坡/克服外力**方向。incline_deg 为轴相对水平面的倾角（0 水平，90 竖直向上）。
- **重复计数规避**：平动质量的惯性只通过“折算到电机轴的惯量 × 角加速度”计入加速转矩；
  静态负载力 **不含 m·a**。两处都计会把加速转矩算两遍。
- 摩擦力恒与运动方向相反：正向 +μ·m·g·cosθ，返程同样取 +（幅值），重力分量正向 +m·g·sinθ、返程 −m·g·sinθ。
- 传动效率按“电机驱动负载”取；减速段/返程出现的负转矩表示电机处于回馈，RMS 用平方、峰值取绝对值。
  反向驱动效率与自锁特性因丝杠而异，此处不建模，垂直/倾斜轴一律要求显式的抱闸或自锁声明。
- 阈值（安全系数、利用率、惯量比）是**工程惯例的起点，不是标准**，可经 DRC Profile 覆盖；
  惯量比上限尤其随厂商/伺服动态要求而异，报告里会把所用阈值原样输出。
"""
from __future__ import annotations

import math
from typing import Any, Mapping

G = 9.80665

DEFAULT_LIMITS: dict[str, float] = {
    "driveTorqueSafetyFactor": 1.5,   # T_peak × SF ≤ 电机峰值转矩
    "driveRmsUtilizationMax": 0.8,    # T_rms ≤ 利用率 × 额定转矩
    "driveInertiaRatioWarn": 5.0,     # 负载/转子惯量比：超过告警
    "driveInertiaRatioMax": 10.0,     # 超过判不通过
}


def _boolean(spec: Mapping[str, Any], key: str, default: bool, *, where: str) -> bool:
    """要求显式布尔值，避免字符串 'false' 被误判为已安装抱闸。"""
    value = spec.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{where}{key} 必须是布尔值")
    return value


def _num(spec: Mapping[str, Any], key: str, *, default: float | None = None, minimum: float | None = None,
         positive: bool = False, where: str = "") -> float:
    value = spec.get(key, default)
    if value is None:
        raise ValueError(f"{where}缺少必填项 {key}")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{where}{key} 必须是有限数值")
    number = float(value)
    if positive and number <= 0.0:
        raise ValueError(f"{where}{key} 必须大于 0")
    if minimum is not None and number < minimum:
        raise ValueError(f"{where}{key} 不能小于 {minimum:g}")
    return number


def motion_profile(distance_m: float, max_speed_m_s: float, accel_m_s2: float) -> dict[str, float | bool]:
    """@brief 对称梯形速度曲线；行程不足以加速到最高速时退化为三角形。"""
    if distance_m <= 0 or max_speed_m_s <= 0 or accel_m_s2 <= 0:
        raise ValueError("distance/max_speed/accel 必须大于 0")
    s_acc = max_speed_m_s ** 2 / (2.0 * accel_m_s2)
    if 2.0 * s_acc <= distance_m:
        t_acc = max_speed_m_s / accel_m_s2
        t_cruise = (distance_m - 2.0 * s_acc) / max_speed_m_s
        return {"t_acc": t_acc, "t_cruise": t_cruise, "t_dec": t_acc, "v_peak": max_speed_m_s, "triangular": False,
                "t_move": 2.0 * t_acc + t_cruise}
    v_peak = math.sqrt(accel_m_s2 * distance_m)  # 三角形：2·(v²/2a) = s
    t_acc = v_peak / accel_m_s2
    return {"t_acc": t_acc, "t_cruise": 0.0, "t_dec": t_acc, "v_peak": v_peak, "triangular": True, "t_move": 2.0 * t_acc}


def static_force_n(mass_kg: float, incline_deg: float, mu: float, f_ext_n: float, *, forward: bool = True) -> float:
    """@brief 匀速时的静态负载力（不含 m·a，惯性由折算惯量计入）。"""
    theta = math.radians(incline_deg)
    gravity = mass_kg * G * math.sin(theta)
    friction = mu * mass_kg * G * math.cos(theta)
    return (gravity if forward else -gravity) + friction + f_ext_n


def validate_drive_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验并规范化 drive-spec；非法输入抛 ValueError（含字段路径）。"""
    if not isinstance(spec, Mapping):
        raise ValueError("drive-spec 必须是对象")
    load = spec.get("load") if isinstance(spec.get("load"), Mapping) else None
    motion = spec.get("motion") if isinstance(spec.get("motion"), Mapping) else None
    trans = spec.get("transmission") if isinstance(spec.get("transmission"), Mapping) else None
    if load is None or motion is None or trans is None:
        raise ValueError("drive-spec 必须包含 load / motion / transmission")
    ttype = str(trans.get("type") or "").lower()
    if ttype not in {"lead_screw", "belt"}:
        raise ValueError("transmission.type 目前支持 lead_screw / belt")

    norm: dict[str, Any] = {"id": str(spec.get("id") or "drive")}
    norm["load"] = {
        "mass_kg": _num(load, "mass_kg", positive=True, where="load."),
        "incline_deg": _num(load, "incline_deg", default=0.0, where="load."),
        "friction_coeff": _num(load, "friction_coeff", default=0.0, minimum=0.0, where="load."),
        "external_force_n": _num(load, "external_force_n", default=0.0, where="load."),
        "return_external_force_n": _num(load, "return_external_force_n", default=0.0, where="load."),
    }
    if not 0.0 <= norm["load"]["incline_deg"] <= 90.0:
        raise ValueError("load.incline_deg 必须在 0..90 度之间")
    norm["motion"] = {
        "distance_m": _num(motion, "distance_mm", positive=True, where="motion.") / 1000.0,
        "max_speed_m_s": _num(motion, "max_speed_mm_s", positive=True, where="motion.") / 1000.0,
        "accel_m_s2": _num(motion, "accel_mm_s2", positive=True, where="motion.") / 1000.0,
        "dwell_s": _num(motion, "dwell_s", default=0.0, minimum=0.0, where="motion."),
        "round_trip": _boolean(motion, "round_trip", True, where="motion."),
    }
    eff = _num(trans, "efficiency", default=0.9, positive=True, where="transmission.")
    if eff > 1.0:
        raise ValueError("transmission.efficiency 必须在 (0, 1]")
    ratio = _num(trans, "gear_ratio", default=1.0, positive=True, where="transmission.")
    gear_eff = _num(trans, "gear_efficiency", default=1.0, positive=True, where="transmission.")
    if gear_eff > 1.0:
        raise ValueError("transmission.gear_efficiency 必须在 (0, 1]")
    t: dict[str, Any] = {"type": ttype, "efficiency": eff, "gear_ratio": ratio, "gear_efficiency": gear_eff,
                         "extra_inertia_kgm2": _num(trans, "extra_inertia_kgm2", default=0.0, minimum=0.0, where="transmission.")}
    if ttype == "lead_screw":
        t["lead_m"] = _num(trans, "lead_mm", positive=True, where="transmission.") / 1000.0
        d = trans.get("screw_diameter_mm")
        length = trans.get("screw_length_mm")
        if (d is None) != (length is None):
            raise ValueError("丝杠直径和长度必须同时提供，或同时省略")
        if d is not None and length is not None:
            t["screw_diameter_m"] = _num(trans, "screw_diameter_mm", positive=True, where="transmission.") / 1000.0
            t["screw_length_m"] = _num(trans, "screw_length_mm", positive=True, where="transmission.") / 1000.0
            t["screw_density"] = _num(trans, "screw_density_kg_m3", default=7850.0, positive=True, where="transmission.")
    else:
        t["pulley_radius_m"] = _num(trans, "pulley_radius_mm", positive=True, where="transmission.") / 1000.0
    norm["transmission"] = t

    motor = spec.get("motor") if isinstance(spec.get("motor"), Mapping) else {}
    m: dict[str, Any] = {"has_brake": _boolean(motor, "has_brake", False, where="motor.")}
    for key in ("rated_torque_nm", "peak_torque_nm", "rated_speed_rpm", "max_speed_rpm"):
        if motor.get(key) is not None:
            m[key] = _num(motor, key, positive=True, where="motor.")
    if motor.get("rotor_inertia_kgm2") is not None:
        m["rotor_inertia_kgm2"] = _num(motor, "rotor_inertia_kgm2", positive=True, where="motor.")
    elif motor.get("rotor_inertia_kgcm2") is not None:
        m["rotor_inertia_kgm2"] = _num(motor, "rotor_inertia_kgcm2", positive=True, where="motor.") * 1e-4
    norm["motor"] = m
    return norm


def compute_drive(spec: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 计算各运动段转矩、峰值/均方根、最高转速与惯量比（不含判定）。"""
    s = validate_drive_spec(spec)
    load, motion, trans = s["load"], s["motion"], s["transmission"]
    prof = motion_profile(motion["distance_m"], motion["max_speed_m_s"], motion["accel_m_s2"])
    ratio, gear_eff = trans["gear_ratio"], trans["gear_efficiency"]

    # 线速度(m/s) -> 传动轴角速度(rad/s) 的换算系数 k：ω_trans = v * k
    if trans["type"] == "lead_screw":
        k = 2.0 * math.pi / trans["lead_m"]
        force_to_torque = trans["lead_m"] / (2.0 * math.pi * trans["efficiency"])   # T = F·p / (2π·η)
        j_load = load["mass_kg"] * (trans["lead_m"] / (2.0 * math.pi)) ** 2
        j_screw = 0.0
        if "screw_diameter_m" in trans:
            j_screw = math.pi * trans["screw_density"] * trans["screw_length_m"] * trans["screw_diameter_m"] ** 4 / 32.0
    else:
        k = 1.0 / trans["pulley_radius_m"]
        force_to_torque = trans["pulley_radius_m"] / trans["efficiency"]            # T = F·r / η
        j_load = load["mass_kg"] * trans["pulley_radius_m"] ** 2
        j_screw = 0.0
    j_trans = j_load + j_screw + trans["extra_inertia_kgm2"]       # 传动轴侧总惯量
    j_reflected = j_trans / ratio ** 2                              # 折算到电机轴
    t_motor_per_trans = 1.0 / (ratio * gear_eff)                    # 传动轴转矩 -> 电机轴转矩

    alpha_motor = motion["accel_m_s2"] * k * ratio                  # 电机轴角加速度 rad/s²
    j_rotor = s["motor"].get("rotor_inertia_kgm2")
    # 折算惯量仍用于惯量比；驱动平动负载的加速转矩需考虑传动效率。
    # 丝杠及额外惯量位于减速机输出侧，不经过丝杠/皮带的线性传动效率。
    j_acc = (j_load / trans["efficiency"] + j_screw + trans["extra_inertia_kgm2"]) / (ratio ** 2 * gear_eff)
    t_acc = (j_acc + (j_rotor or 0.0)) * alpha_motor

    def trans_torque(force: float) -> float:
        return force * force_to_torque * t_motor_per_trans

    f_fwd = static_force_n(load["mass_kg"], load["incline_deg"], load["friction_coeff"], load["external_force_n"], forward=True)
    f_ret = static_force_n(load["mass_kg"], load["incline_deg"], load["friction_coeff"], load["return_external_force_n"], forward=False)
    t_fwd, t_ret = trans_torque(f_fwd), trans_torque(f_ret)

    # 驻留：有抱闸则电机不承担保持转矩；否则保持重力分量（保守地按同一传动比估算）。
    f_hold = load["mass_kg"] * G * math.sin(math.radians(load["incline_deg"]))
    t_hold = 0.0 if s["motor"]["has_brake"] else abs(trans_torque(f_hold))

    phases: list[dict[str, Any]] = []

    def add_move(name: str, t_static: float) -> None:
        phases.append({"name": f"{name}-加速", "torque_nm": t_static + t_acc, "time_s": prof["t_acc"]})
        if prof["t_cruise"] > 0:
            phases.append({"name": f"{name}-匀速", "torque_nm": t_static, "time_s": prof["t_cruise"]})
        phases.append({"name": f"{name}-减速", "torque_nm": t_static - t_acc, "time_s": prof["t_dec"]})
        if motion["dwell_s"] > 0:
            phases.append({"name": f"{name}-驻留", "torque_nm": t_hold, "time_s": motion["dwell_s"]})

    add_move("正向", t_fwd)
    if motion["round_trip"]:
        add_move("返程", t_ret)

    total_time = sum(p["time_s"] for p in phases)
    t_peak = max(abs(p["torque_nm"]) for p in phases)
    t_rms = math.sqrt(sum(p["torque_nm"] ** 2 * p["time_s"] for p in phases) / total_time)
    n_max_rpm = prof["v_peak"] * k * ratio * 60.0 / (2.0 * math.pi)

    return {
        "spec": s,
        "profile": prof,
        "phases": phases,
        "cycle_time_s": total_time,
        "t_peak_nm": t_peak,
        "t_rms_nm": t_rms,
        "t_acc_nm": t_acc,
        "t_static_forward_nm": t_fwd,
        "t_static_return_nm": t_ret,
        "n_max_rpm": n_max_rpm,
        "j_reflected_kgm2": j_reflected,
        "j_rotor_kgm2": j_rotor,
        "inertia_ratio": (j_reflected / j_rotor) if j_rotor else None,
        "holds_gravity": abs(f_hold) > 1e-6,
    }


def _check(check_id: str, status: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"id": check_id, "category": "drive", "status": status, "severity": severity, "message": message}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def evaluate_drive(spec: Mapping[str, Any], limits: Mapping[str, float] | None = None) -> dict[str, Any]:
    """@brief 计算并判定。返回 {result, checks, controlling, limits}；checks 可直接并入 DRC。"""
    lim = dict(DEFAULT_LIMITS)
    if limits:
        unknown = set(limits) - set(DEFAULT_LIMITS)
        if unknown:
            raise ValueError(f"未知电机选型阈值: {', '.join(sorted(unknown))}")
        for key in limits:
            lim[key] = _num(limits, key, positive=True, where="limits.")
    if lim["driveRmsUtilizationMax"] > 1:
        raise ValueError("limits.driveRmsUtilizationMax 必须在 (0, 1]")
    if lim["driveTorqueSafetyFactor"] < 1:
        raise ValueError("limits.driveTorqueSafetyFactor 不能小于 1")
    if lim["driveInertiaRatioWarn"] > lim["driveInertiaRatioMax"]:
        raise ValueError("惯量比告警阈值不能大于上限")
    r = compute_drive(spec)
    motor = r["spec"]["motor"]
    tid = r["spec"]["id"]
    checks: list[dict[str, Any]] = []
    margins: dict[str, float] = {}

    # DRC-DRV-001 峰值转矩
    t_max = motor.get("peak_torque_nm")
    if t_max is None:
        checks.append(_check("DRC-DRV-001", "info", "info", f"驱动 {tid} 未提供电机峰值转矩，仅给出需求峰值 {r['t_peak_nm']:.3f} N·m", target=tid))
    else:
        need = r["t_peak_nm"] * lim["driveTorqueSafetyFactor"]
        margin = (t_max - need) / t_max * 100.0
        margins["DRC-DRV-001"] = margin
        ok = need <= t_max
        status = "info" if ok else "fail"
        checks.append(_check("DRC-DRV-001", status, "info" if ok else "major",
                             f"驱动 {tid} 峰值转矩 {r['t_peak_nm']:.3f}×SF{lim['driveTorqueSafetyFactor']:g}={need:.3f} N·m "
                             f"{'≤' if ok else '>'} 电机峰值 {t_max:g} N·m（余量 {margin:.1f}%）", target=tid, margin_pct=round(margin, 2)))

    # DRC-DRV-002 均方根转矩
    t_rated = motor.get("rated_torque_nm")
    if t_rated is None:
        checks.append(_check("DRC-DRV-002", "info", "info", f"驱动 {tid} 未提供额定转矩，仅给出 RMS {r['t_rms_nm']:.3f} N·m", target=tid))
    else:
        allowed = lim["driveRmsUtilizationMax"] * t_rated
        margin = (allowed - r["t_rms_nm"]) / allowed * 100.0
        margins["DRC-DRV-002"] = margin
        ok = r["t_rms_nm"] <= allowed
        status = "info" if ok else "fail"
        checks.append(_check("DRC-DRV-002", status, "info" if ok else "major",
                             f"驱动 {tid} RMS 转矩 {r['t_rms_nm']:.3f} N·m {'≤' if ok else '>'} "
                             f"{lim['driveRmsUtilizationMax']:g}×额定 {t_rated:g}={allowed:.3f} N·m（余量 {margin:.1f}%）", target=tid, margin_pct=round(margin, 2)))

    # DRC-DRV-003 转速
    n_max, n_rated = motor.get("max_speed_rpm"), motor.get("rated_speed_rpm")
    if n_max is None and n_rated is None:
        checks.append(_check("DRC-DRV-003", "info", "info", f"驱动 {tid} 未提供电机转速限值，需求最高转速 {r['n_max_rpm']:.0f} rpm", target=tid))
    elif n_max is not None and r["n_max_rpm"] > n_max:
        checks.append(_check("DRC-DRV-003", "fail", "major", f"驱动 {tid} 需求转速 {r['n_max_rpm']:.0f} rpm 超过电机最高转速 {n_max:g} rpm", target=tid))
    elif n_rated is not None and r["n_max_rpm"] > n_rated:
        checks.append(_check("DRC-DRV-003", "warning", "warning", f"驱动 {tid} 需求转速 {r['n_max_rpm']:.0f} rpm 超过额定转速 {n_rated:g} rpm（额定转矩区之外，需核对转矩-转速曲线）", target=tid))
    elif n_max is None:
        checks.append(_check("DRC-DRV-003", "info", "info", f"驱动 {tid} 未提供最高转速，无法核对绝对转速上限", target=tid))
    else:
        checks.append(_check("DRC-DRV-003", "pass", "info", f"驱动 {tid} 需求转速 {r['n_max_rpm']:.0f} rpm 在电机转速范围内", target=tid))

    # DRC-DRV-004 惯量比
    ratio = r["inertia_ratio"]
    if ratio is None:
        checks.append(_check("DRC-DRV-004", "info", "info", f"驱动 {tid} 未提供转子惯量，无法核对惯量比", target=tid))
    elif ratio > lim["driveInertiaRatioMax"]:
        checks.append(_check("DRC-DRV-004", "fail", "major", f"驱动 {tid} 惯量比 {ratio:.2f} 超过上限 {lim['driveInertiaRatioMax']:g}（阈值随厂商/动态要求而异）", target=tid, value=round(ratio, 4)))
    elif ratio > lim["driveInertiaRatioWarn"]:
        checks.append(_check("DRC-DRV-004", "warning", "warning", f"驱动 {tid} 惯量比 {ratio:.2f} 超过建议值 {lim['driveInertiaRatioWarn']:g}，高动态场景整定困难", target=tid, value=round(ratio, 4)))
    else:
        checks.append(_check("DRC-DRV-004", "pass", "info", f"驱动 {tid} 惯量比 {ratio:.2f} 合理", target=tid, value=round(ratio, 4)))

    # DRC-DRV-005 垂直/倾斜轴保持
    if r["holds_gravity"]:
        if motor["has_brake"]:
            checks.append(_check("DRC-DRV-005", "info", "info", f"驱动 {tid} 声明带抱闸；必须核对保持转矩、失电状态和制动能力", target=tid))
        else:
            checks.append(_check("DRC-DRV-005", "fail", "critical", f"驱动 {tid} 为倾斜/垂直轴但未声明抱闸；断电/急停会坠落（丝杠自锁性因导程/效率而异，不能默认依赖）", target=tid))

    controlling = min(margins, key=margins.get) if margins else None
    return {"result": {k: v for k, v in r.items() if k != "spec"}, "checks": checks,
            "controlling": controlling, "limits": lim, "driveId": tid,
            "reviewRequired": True,
            "limitations": ["仅为选型初筛，需工程师核对实际负载与电机转矩-转速曲线",
                            "减速和反向驱动效率未单独建模；峰值及 RMS 转矩满足阈值时仍需复核，不视为通过",
                            "未建模自锁、丝杠临界转速、皮带张力及寿命",
                            "未提供转子或传动惯量时，转矩计算可能偏低；驻留假设已声明抱闸投入"]}


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行：读取 drive-spec JSON，打印核验结果。"""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="电机扭矩核验（选型初筛与审计辅助）。")
    parser.add_argument("spec", help="drive-spec JSON 路径。")
    args = parser.parse_args(argv)
    out = evaluate_drive(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if any(c["status"] == "fail" for c in out["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
