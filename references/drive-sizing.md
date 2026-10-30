# 电机扭矩核验（drive sizing）

`scripts/drive_sizing.py` 判断“所选电机/减速机能否满足这个机构与运动曲线”。**选型初筛与审计辅助**，
不替代厂商选型软件与工程师签署；报告始终 `reviewRequired=true`。已并入 DRC（规则族 `DRC-DRV-*`），
因此自动获得指纹、让步单、基线 diff、风险分、回归门禁和 MCP（`cadstudio_check_drc`）。

## 输入：`metadata.drives[]`（drive-spec，声明式 JSON，可由自然语言经代理生成）

```json
{
  "id": "X轴",
  "load": {"mass_kg": 50, "incline_deg": 0, "friction_coeff": 0.1, "external_force_n": 0, "return_external_force_n": 0},
  "motion": {"distance_mm": 500, "max_speed_mm_s": 500, "accel_mm_s2": 2000, "dwell_s": 0.5, "round_trip": true},
  "transmission": {"type": "lead_screw", "lead_mm": 10, "efficiency": 0.9, "screw_diameter_mm": 20, "screw_length_mm": 600,
                   "gear_ratio": 1, "gear_efficiency": 1},
  "motor": {"peak_torque_nm": 1.5, "rated_torque_nm": 0.64, "rated_speed_rpm": 3000, "max_speed_rpm": 5000,
            "rotor_inertia_kgcm2": 0.5, "has_brake": false}
}
```
传动类型：`lead_screw`（导程、效率、可选丝杠 ⌀/长度算自身惯量）、`belt`（皮带轮半径、效率）。转子惯量可用 `kg·m²` 或 `kg·cm²`。

## 约定（错一个符号就是错的）

- **正向** = 朝上坡/克服外力方向；`incline_deg` 0 水平、90 竖直向上。
- **不重复计数**：平动质量的惯性只通过“折算惯量 × 角加速度”进入加速转矩，静态力**不含 m·a**。
- 摩擦恒与运动反向（正向、返程都取 +μ·m·g·cosθ）；重力分量正向 +、返程 −。
- 减速/返程出现的**负转矩 = 电机回馈**：RMS 用平方，峰值取绝对值。
- 反向驱动效率与丝杠自锁性因导程/效率而异，**不建模**；垂直/倾斜轴必须显式声明抱闸，否则 `critical`。

## 判据

| 规则 | 判据 | 默认阈值（可经 Profile 覆盖） |
|---|---|---|
| DRC-DRV-001 | `T_peak × SF ≤ 电机峰值转矩` | `driveTorqueSafetyFactor`=1.5 |
| DRC-DRV-002 | `T_rms ≤ 利用率 × 额定转矩` | `driveRmsUtilizationMax`=0.8 |
| DRC-DRV-003 | 需求最高转速 ≤ 电机最高转速；超额定转速给告警 | — |
| DRC-DRV-004 | 负载/转子惯量比 | warn 5 / max 10（随厂商与动态要求而异） |
| DRC-DRV-005 | 垂直/倾斜轴需抱闸 | — |
| DRC-DRV-900 | drive-spec 无效（给出字段路径） | — |

**阈值是工程惯例的起点，不是标准**；输出里会原样给出所用阈值与每项“余量 %”及“控制性约束”。
缺电机数据时对应项是 `info`（**不当作通过**）。

## 公式

线速度→传动轴：丝杠 `ω=v·2π/p`，皮带 `ω=v/r`；静态转矩：丝杠 `T=F·p/(2π·η)`，皮带 `T=F·r/η`；
经减速比 `i`：电机轴 `T/(i·η_g)`，折算惯量 `J/i²`，转速 `×i`。
负载折算惯量：丝杠 `m·(p/2π)²`，皮带 `m·r²`；丝杠自身 `π·ρ·L·d⁴/32`。
加速转矩 `T_acc=[(J_load/η+J_screw+J_extra)/(i²·η_g)+J_rotor]·α`；惯量比仍使用不含效率的物理折算惯量。
减速及反向驱动效率未分别建模，所以峰值和 RMS 满足阈值时仅输出 `info`，不能视为选型通过。
各段 → `T_peak`（取绝对值）、`T_rms=√(ΣT²·t/Σt)`。可参考 [Kollmorgen 应用选型指南](https://www.kollmorgen.com/sites/default/files/public_downloads/Application_Sizing_Guide_en-US.pdf)。
运动曲线为对称梯形，行程不足以加速到最高速时退化为三角形。

## 验证

`tests/test_drive_sizing.py`：事先手算的完整算例作锚点；**皮带≡丝杠物理等价**（两条不同代码路径在 9 个量上一致）；
减速比反射定律；梯形/三角形位移守恒；垂直轴返程重力助力符号；非法输入全部拒绝。

## 边界与后续

- 暂未覆盖：丝杠临界转速与压杆稳定、皮带张力、寿命、转矩-转速曲线（弧段）、旋转负载直驱。
- 输入 `has_brake` 和 `round_trip` 必须是 JSON 布尔值；未提供转子或传动惯量时需求转矩可能偏低。驻留计算假设声明的抱闸已实际投入，必须由工程师确认。
- 质量、行程和电机数据需要提供可靠来源；本工具不会自动读取模型质量或厂商电机目录。
