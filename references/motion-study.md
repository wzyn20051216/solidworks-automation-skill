# Motion Study 与旋转马达自动化

本文沉淀 SolidWorks 2024 SP3.1 + Python 3.13 + pywin32 实测通过的 Motion Study 自动化流程。目标是创建真实运动算例和马达特征，而不是用脚本假动画替代机械自由度。

## 适用场景

- 用户要求“新建运动算例”“Motion Study”“添加马达”“60RPM 匀速旋转”。
- 装配体已有真实 Mate，旋转件通过同心配合保留旋转自由度。
- 需要在 SolidWorks 的运动算例时间轴中生成可计算、可播放的动画。

不适用：

- 只想演示某个角度变化，可用 `sw_assembly.apply_component_transform_x()` 生成帧。
- 需要复杂接触、摩擦、碰撞、力学结果时，应检查 Motion / Simulation 加载项和许可证，再做专门验证。

## 推荐工作流

1. 先生成并保存零件。
2. 新建装配体，添加组件。
3. 解析组件，用 `GetCorresponding()` 选择装配体上下文实体。
4. 对旋转件创建同心 Mate，`lock_rotation=False`。
5. 用一个平面重合或距离 Mate 限制轴向窜动，但不要再用三基准面完全锁死旋转件。
6. 固定静止件；旋转件保持浮动。
7. 调用 `sw_motion.create_motion_study()` 创建算例。
8. 调用 `add_constant_speed_rotary_motor_by_cylinders()` 添加匀速旋转马达。
9. 调用 `calculate_and_play()` 计算并播放。

## 最小示例

```python
import sys
sys.path.insert(0, r"C:\Users\you\.codex\skills\solidworks-automation\scripts")

from sw_connect import mm
from sw_motion import (
    create_motion_study,
    add_constant_speed_rotary_motor_by_cylinders,
    calculate_and_play,
)

# 前提：asm 是装配体文档；stand_comp 是静止轴/支架；impeller_comp 是叶轮。
# 前提：叶轮已用同心 Mate 装到轴上，且该同心 Mate 未锁定旋转。
study = create_motion_study(
    asm,
    name="叶轮_60RPM_循环转动",
    duration=4.0,
)

motor = add_constant_speed_rotary_motor_by_cylinders(
    study,
    shaft_component=stand_comp,
    rotor_component=impeller_comp,
    shaft_radius=(mm(4.5), mm(5.5)),
    rotor_radius=(mm(10.5), mm(11.5)),
    rpm=60.0,
    name="叶轮旋转马达_60RPM",
)

ok = calculate_and_play(study)
print(ok)
```

## 类型库与动态 COM 坑

Motion Study 的 `IMotionStudyManager` 位于 `swmotionstudy.tlb`，不在主 `SolidWorks.Interop.sldworks.dll` 类型库里。未生成 pywin32 包装时，动态对象常出现以下怪相：

- `model.Extension.GetMotionStudyManager` 是属性，不是方法。
- `motion_mgr.CreateMotionStudy` 是属性，读取即创建算例；调用 `CreateMotionStudy()` 反而报“找不到成员”。
- `study.Activate`、`study.Calculate`、`study.Play` 可能是布尔属性，不是方法。
- `study.SetDuration()`、`study.CreateDefinition()`、`study.CreateFeature()` 通常仍是方法。

稳定做法：优先复用 `sw_motion.motion_member()` 和 `sw_motion.ensure_motion_type_library()`。

```python
from sw_motion import ensure_motion_type_library, motion_member

ensure_motion_type_library()
motion_mgr = motion_member(asm.Extension, "GetMotionStudyManager")
study = motion_member(motion_mgr, "CreateMotionStudy")
motion_member(study, "SetDuration", 4.0)
calculated = motion_member(study, "Calculate")
```

## 旋转马达关键 API

创建旋转马达使用 `MotionStudy.CreateDefinition(swFmAEMRotationalMotor)`：

```python
SW_FM_AEM_ROTATIONAL_MOTOR = 78
motor_data = study.CreateDefinition(SW_FM_AEM_ROTATIONAL_MOTOR)
motor_data.DirectionReference = shaft_axis_face
motor_data.ConstantSpeedMotor(60.0)  # 单位：RPM
motor_data.RelativeComponent = stand_comp
motor_data.Location = rotor_face
motor_data.LoadReferences = (rotor_face,)
motor_feature = study.CreateFeature(motor_data)
```

实测注意：

- `DirectionReference` 选择静止轴的装配体上下文圆柱面最稳定。
- `LoadReferences` 可传 tuple/list；部分环境需要 `VARIANT(VT_ARRAY | VT_VARIANT, [...])` 或 `VT_DISPATCH`。
- `ConstantSpeedMotor(60.0)` 的参数单位为 RPM；不要换算成 rad/s。
- 如果 `CreateFeature()` 返回 `None`，先检查方向引用和载荷引用是否都是装配体上下文实体。

## 与 Mate 自由度的关系

Motion Motor 只能驱动仍有旋转自由度的组件。常见失败原因：

- 叶轮组件被 `FixComponent()` 固定。
- 同心 Mate 创建时 `lock_rotation=True`。
- 叶轮又被多个基准面重合，绕轴自由度被锁死。
- 选了零件上下文面，而不是 `component.GetCorresponding()` 后的装配体上下文面。

推荐约束：

- 静止件：底座、立柱、防护盖固定。
- 旋转件：只用同心 Mate + 一个轴向定位 Mate；组件保持浮动。
- 同心 Mate：`lock_rotation=False`。

## 会话清理与同标题文档

多次调试自动生成零件时，SolidWorks 会话里容易残留同名文档，导致：

```text
OpenDoc6 errors=65536
swFileWithSameTitleAlreadyOpen
AddComponent4 返回 None
```

稳定做法：

1. 批量脚本开始前，确认是否可以关闭当前文档；无人值守流程可调用 `sw.CloseAllDocuments(True)`。
2. 每个零件保存后，用 `sw.CloseDoc(title)` 关闭，装配时再按路径添加。
3. `OpenDoc6` 返回 `65536` 时不要直接判定为“文件损坏”，它通常表示同标题已打开。

## 实测记录

环境：

- SolidWorks Premium 2024 SP3.1
- Python 3.13
- pywin32 动态 COM

已跑通案例：

- 4 零件桌面迷你散热风扇：底座、中心立柱、带叶片叶轮、圆形防护前盖。
- 装配体 Mate：底座/立柱同轴+重合，叶轮/轴同轴未锁转+轴向重合，前盖同轴+角向定位。
- 固定状态：底座/立柱/前盖固定，叶轮浮动。
- Motion Study：创建 `叶轮_60RPM_循环转动`，添加 `叶轮旋转马达_60RPM`，`Calculate=True`。

仓库中的 `examples/08_mini_fan_motion_assembly.py` 是可重复运行的基准示例。该示例重点验证自动建模、装配、真实 Mate、Motion Study 和审查导出；圆角/倒角没有作为成功标准，叶片也采用稳定矩形叶片而非复杂弧面叶片。
