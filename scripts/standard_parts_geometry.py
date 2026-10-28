"""
@file standard_parts_geometry.py
@brief 标准机械零件（直齿轮、压缩弹簧、滚子链链轮）的纯几何生成函数。

本模块不导入任何 COM 依赖，可在无 SolidWorks / 无 pywin32 的环境下离线单测。
COM 生成器（subskills/solidworks-standard-parts/scripts/*）消费这里的坐标与派生量，
把“几何是否正确”这一可验证部分与“SolidWorks 特征是否落盘”这一需真机验证部分分离。

单位约定：所有输入与输出长度均为毫米（mm），角度输入为度、内部换算为弧度。
坐标系：轮廓点位于 XY 平面，零件回转轴为 Z 轴，原点在轴心。
灵感来源：t84RT/SW-software---Macro-command 中的齿轮/弹簧/链条宏命令（第三方 VBA，
与达索无隶属关系）。本实现为独立的 Python 重写，不复制其编译宏代码。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _finite(name: str, value: float) -> float:
    """@brief 校验有限数值。"""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数值")
    return number


def _positive(name: str, value: float) -> float:
    """@brief 校验正有限数值。"""
    number = _finite(name, value)
    if number <= 0.0:
        raise ValueError(f"{name} 必须大于 0")
    return number


def involute(angle_rad: float) -> float:
    """@brief 渐开线函数 inv(a) = tan(a) - a。"""
    return math.tan(angle_rad) - angle_rad


def _polar_to_xy(radius: float, angle_rad: float) -> tuple[float, float]:
    """@brief 极坐标转直角坐标。"""
    return radius * math.cos(angle_rad), radius * math.sin(angle_rad)


# ---------------------------------------------------------------------------
# 直齿圆柱齿轮（渐开线全齿廓）
# ---------------------------------------------------------------------------


@dataclass
class SpurGearGeometry:
    """@brief 直齿轮派生几何量与闭合外轮廓点。"""

    module_mm: float
    teeth: int
    pressure_angle_deg: float
    pitch_diameter_mm: float
    base_diameter_mm: float
    addendum_diameter_mm: float
    root_diameter_mm: float
    bore_diameter_mm: float
    circular_pitch_mm: float
    tooth_thickness_mm: float
    is_pointed: bool
    profile_xy_mm: list[tuple[float, float]] = field(default_factory=list)


def spur_gear_profile(
    module_mm: float,
    teeth: int,
    *,
    pressure_angle_deg: float = 20.0,
    addendum_coeff: float = 1.0,
    dedendum_coeff: float = 1.25,
    profile_shift_coeff: float = 0.0,
    bore_diameter_mm: float = 0.0,
    samples_per_flank: int = 12,
) -> SpurGearGeometry:
    """@brief 生成标准渐开线直齿轮的闭合外齿廓。

    @param module_mm 模数 m，单位 mm。
    @param teeth 齿数 z，>= 4。
    @param pressure_angle_deg 压力角 α，通常 20 度。
    @param addendum_coeff 齿顶高系数 ha*，标准 1.0。
    @param dedendum_coeff 齿根高系数 hf*，标准 1.25。
    @param profile_shift_coeff 变位系数 x，正变位使齿变厚。
    @param bore_diameter_mm 中心孔直径，0 表示不打孔（仅记录）。
    @param samples_per_flank 每条渐开线齿廓采样点数。
    @return SpurGearGeometry；profile_xy_mm 为按逆时针排列的闭合点列（首尾不重复）。

    齿廓自齿根圆逐齿生成：右侧齿廓上行 -> 齿顶圆弧 -> 左侧齿廓下行 -> 齿根圆弧到下一齿。
    渐开线仅在基圆以上有效，基圆低于齿根圆时用径向线延伸到齿根（近似根切）。
    """
    z = int(teeth)
    if z < 4:
        raise ValueError("齿数至少为 4")
    m = _positive("module", module_mm)
    alpha = math.radians(_finite("pressure_angle", pressure_angle_deg))
    if not (0.0 < alpha < math.pi / 2.0):
        raise ValueError("压力角必须在 0 到 90 度之间")
    ha = _finite("addendum_coeff", addendum_coeff)
    hf = _finite("dedendum_coeff", dedendum_coeff)
    x_shift = _finite("profile_shift_coeff", profile_shift_coeff)
    samples = max(3, int(samples_per_flank))

    r_pitch = m * z / 2.0
    r_base = r_pitch * math.cos(alpha)
    r_add = r_pitch + m * (ha + x_shift)
    r_root = r_pitch - m * (hf - x_shift)
    if r_root <= 0.0:
        raise ValueError("齿根圆半径非正，请增大齿数或减小齿根高系数")
    if r_add <= r_base:
        raise ValueError("齿顶圆不高于基圆，无法生成有效渐开线齿廓")

    bore = _finite("bore_diameter_mm", bore_diameter_mm)
    if bore < 0.0:
        raise ValueError("中心孔直径不能为负")
    if bore >= 2.0 * r_root:
        raise ValueError("中心孔直径必须小于齿根圆直径")

    inv_alpha = involute(alpha)
    # 分度圆上半齿角 + 变位修正。
    half_tooth_angle = math.pi / (2.0 * z) + 2.0 * x_shift * math.tan(alpha) / z

    def flank_offset(radius: float) -> float:
        """@brief 半齿廓相对齿中心线的角度；radius>=base 时按渐开线，否则按基圆处角度。"""
        rho = max(radius, r_base)
        alpha_rho = math.acos(max(-1.0, min(1.0, r_base / rho)))
        return half_tooth_angle + inv_alpha - involute(alpha_rho)

    r_flank_start = max(r_root, r_base)
    radii = [r_flank_start + (r_add - r_flank_start) * i / (samples - 1) for i in range(samples)]

    tip_offset = flank_offset(r_add)
    is_pointed = tip_offset <= 1e-6

    points: list[tuple[float, float]] = []
    for i in range(z):
        beta = 2.0 * math.pi * i / z
        # 若齿根圆低于基圆，先从齿根径向上到基圆（近似）。
        if r_root < r_base:
            points.append(_polar_to_xy(r_root, beta - flank_offset(r_base)))
        # 右（trailing）齿廓上行：半径升，角度趋向齿中心。
        for radius in radii:
            points.append(_polar_to_xy(radius, beta - flank_offset(radius)))
        # 齿顶圆弧：从右齿顶到左齿顶。
        if not is_pointed:
            arc_steps = max(2, samples // 3)
            for s in range(1, arc_steps):
                ang = (beta - tip_offset) + (2.0 * tip_offset) * s / arc_steps
                points.append(_polar_to_xy(r_add, ang))
        # 左（leading）齿廓下行：半径降，角度继续增大。
        for radius in reversed(radii):
            points.append(_polar_to_xy(radius, beta + flank_offset(radius)))
        if r_root < r_base:
            points.append(_polar_to_xy(r_root, beta + flank_offset(r_base)))
        # 齿根圆弧：连到下一齿右齿廓起点。
        next_beta = 2.0 * math.pi * (i + 1) / z
        start_angle = beta + flank_offset(r_flank_start)
        end_angle = next_beta - flank_offset(r_flank_start)
        root_steps = max(2, samples // 3)
        for s in range(1, root_steps):
            ang = start_angle + (end_angle - start_angle) * s / root_steps
            points.append(_polar_to_xy(r_root, ang))

    return SpurGearGeometry(
        module_mm=m,
        teeth=z,
        pressure_angle_deg=float(pressure_angle_deg),
        pitch_diameter_mm=2.0 * r_pitch,
        base_diameter_mm=2.0 * r_base,
        addendum_diameter_mm=2.0 * r_add,
        root_diameter_mm=2.0 * r_root,
        bore_diameter_mm=bore,
        circular_pitch_mm=math.pi * m,
        tooth_thickness_mm=math.pi * m / 2.0 + 2.0 * x_shift * m * math.tan(alpha),
        is_pointed=is_pointed,
        profile_xy_mm=points,
    )


# ---------------------------------------------------------------------------
# 圆柱压缩弹簧（等螺距螺旋线）
# ---------------------------------------------------------------------------


@dataclass
class CompressionSpringGeometry:
    """@brief 压缩弹簧派生量与螺旋中心线采样点。"""

    wire_diameter_mm: float
    mean_diameter_mm: float
    outer_diameter_mm: float
    free_length_mm: float
    total_coils: float
    active_coils: float
    pitch_mm: float
    solid_length_mm: float
    spring_index: float
    end_type: str
    right_handed: bool
    spring_rate_n_per_mm: float | None
    helix_xyz_mm: list[tuple[float, float, float]] = field(default_factory=list)


def compression_spring_helix(
    wire_diameter_mm: float,
    mean_diameter_mm: float,
    free_length_mm: float,
    total_coils: float,
    *,
    end_type: str = "closed_ground",
    right_handed: bool = True,
    shear_modulus_mpa: float | None = None,
    samples_per_coil: int = 36,
) -> CompressionSpringGeometry:
    """@brief 生成圆柱压缩弹簧的等螺距螺旋扫描中心线与力学派生量。

    @param wire_diameter_mm 线径 d。
    @param mean_diameter_mm 中径 D（螺旋中心线直径）。
    @param free_length_mm 自由长度 L。
    @param total_coils 总圈数 Nt。
    @param end_type closed_ground / closed / open，决定有效圈数与实体长度。
    @param right_handed 右旋为 True。
    @param shear_modulus_mpa 剪切模量 G（MPa），提供则计算刚度。
    @param samples_per_coil 每圈采样点数。
    @return CompressionSpringGeometry；helix_xyz_mm 沿 +Z 递增。

    实体长度按端型近似：closed_ground=Nt*d，closed=(Nt+1)*d，open=(Nt+1)*d。
    有效圈数：closed/closed_ground 取 Nt-2，open 取 Nt。
    """
    d = _positive("wire_diameter", wire_diameter_mm)
    mean_d = _positive("mean_diameter", mean_diameter_mm)
    length = _positive("free_length", free_length_mm)
    nt = _positive("total_coils", total_coils)
    end = str(end_type).strip().lower()
    if end not in {"closed_ground", "closed", "open"}:
        raise ValueError("end_type 必须为 closed_ground、closed 或 open")
    if mean_d <= d:
        raise ValueError("中径必须大于线径")

    if end == "closed_ground":
        active = nt - 2.0
        solid = nt * d
    elif end == "closed":
        active = nt - 2.0
        solid = (nt + 1.0) * d
    else:
        active = nt
        solid = (nt + 1.0) * d
    if active <= 0.0:
        raise ValueError("有效圈数非正，请增大总圈数")
    if solid >= length:
        raise ValueError("实体长度不小于自由长度，请增大自由长度或减少圈数")

    pitch = (length - (solid - active * d)) / active if end != "open" else length / nt
    radius = mean_d / 2.0
    winding = 1.0 if right_handed else -1.0
    total_points = max(2, int(round(samples_per_coil * nt)) + 1)
    points: list[tuple[float, float, float]] = []
    for i in range(total_points):
        frac = i / (total_points - 1)
        angle = winding * 2.0 * math.pi * nt * frac
        z = length * frac
        points.append((radius * math.cos(angle), radius * math.sin(angle), z))

    spring_index = mean_d / d
    rate = None
    if shear_modulus_mpa is not None:
        g = _positive("shear_modulus", shear_modulus_mpa)
        # k = G*d^4 / (8*D^3*Na)，单位 N/mm（G 用 MPa=N/mm^2）。
        rate = g * d**4 / (8.0 * mean_d**3 * active)

    return CompressionSpringGeometry(
        wire_diameter_mm=d,
        mean_diameter_mm=mean_d,
        outer_diameter_mm=mean_d + d,
        free_length_mm=length,
        total_coils=nt,
        active_coils=active,
        pitch_mm=pitch,
        solid_length_mm=solid,
        spring_index=spring_index,
        end_type=end,
        right_handed=bool(right_handed),
        spring_rate_n_per_mm=rate,
        helix_xyz_mm=points,
    )


# ---------------------------------------------------------------------------
# 滚子链链轮（ANSI/ISO 简化齿形）
# ---------------------------------------------------------------------------


@dataclass
class RollerSprocketGeometry:
    """@brief 滚子链链轮派生量与简化齿形闭合轮廓。"""

    chain_pitch_mm: float
    roller_diameter_mm: float
    teeth: int
    pitch_diameter_mm: float
    outside_diameter_mm: float
    root_diameter_mm: float
    seating_radius_mm: float
    bore_diameter_mm: float
    profile_xy_mm: list[tuple[float, float]] = field(default_factory=list)


def roller_sprocket_profile(
    chain_pitch_mm: float,
    roller_diameter_mm: float,
    teeth: int,
    *,
    bore_diameter_mm: float = 0.0,
    seat_samples: int = 8,
) -> RollerSprocketGeometry:
    """@brief 生成滚子链链轮的简化闭合齿形。

    @param chain_pitch_mm 链节距 P。
    @param roller_diameter_mm 滚子直径 Dr。
    @param teeth 齿数 N，>= 6。
    @param bore_diameter_mm 中心孔直径。
    @param seat_samples 每个滚子座圆弧采样点数。
    @return RollerSprocketGeometry；profile_xy_mm 逆时针闭合。

    采用 ANSI B29.1 常用近似：
      节圆直径 PD = P / sin(pi/N)
      齿顶圆直径 OD = P*(0.6 + cot(pi/N))
      滚子座半径 Rs = 0.505*Dr
      齿根圆直径 RD = PD - Dr
    滚子座（凹弧）位于每个节点，齿顶位于相邻节点之间，齿廓侧面用直线近似连接。
    该齿形用于生成可视化/打印级链轮；精确啮合齿形仍需人工按标准复核。
    """
    n = int(teeth)
    if n < 6:
        raise ValueError("链轮齿数至少为 6")
    p = _positive("chain_pitch", chain_pitch_mm)
    dr = _positive("roller_diameter", roller_diameter_mm)
    if dr >= p:
        raise ValueError("滚子直径必须小于链节距")

    half_angle = math.pi / n
    pd = p / math.sin(half_angle)
    od = p * (0.6 + 1.0 / math.tan(half_angle))
    rd = pd - dr
    seat_radius = 0.505 * dr
    r_pitch = pd / 2.0
    r_out = od / 2.0

    bore = _finite("bore_diameter_mm", bore_diameter_mm)
    if bore < 0.0:
        raise ValueError("中心孔直径不能为负")
    if bore >= rd:
        raise ValueError("中心孔直径必须小于齿根圆直径")

    seats = max(3, int(seat_samples))
    points: list[tuple[float, float]] = []
    for i in range(n):
        seat_angle = 2.0 * math.pi * i / n
        seat_center = _polar_to_xy(r_pitch, seat_angle)
        # 滚子座凹弧：以节点为圆心、seat_radius 为半径，开口朝外，从一侧扫到另一侧。
        seat_span = math.pi  # 半圆座
        base_dir = seat_angle + math.pi  # 指向轴心方向
        for s in range(seats + 1):
            arc = base_dir - seat_span / 2.0 + seat_span * s / seats
            px = seat_center[0] + seat_radius * math.cos(arc)
            py = seat_center[1] + seat_radius * math.sin(arc)
            points.append((px, py))
        # 齿顶点：相邻节点之间。
        tip_angle = 2.0 * math.pi * (i + 0.5) / n
        points.append(_polar_to_xy(r_out, tip_angle))

    return RollerSprocketGeometry(
        chain_pitch_mm=p,
        roller_diameter_mm=dr,
        teeth=n,
        pitch_diameter_mm=pd,
        outside_diameter_mm=od,
        root_diameter_mm=rd,
        seating_radius_mm=seat_radius,
        bore_diameter_mm=bore,
        profile_xy_mm=points,
    )


def polygon_is_closed_ccw(points: list[tuple[float, float]]) -> bool:
    """@brief 判断闭合多边形（首尾不重复）是否按逆时针排列，用于自检。"""
    if len(points) < 3:
        return False
    area2 = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        area2 += x1 * y2 - x2 * y1
    return area2 > 0.0
