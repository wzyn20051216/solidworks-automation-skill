# 装配体与运动配合参考

## 官方资料入口

- AddMate5: `https://help.solidworks.com/2023/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.iassemblydoc~addmate5.html`
- GetModelDoc2: `https://help.solidworks.com/2019/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.icomponent2~getmodeldoc2.html`
- GetCorresponding: `https://help.solidworks.com/2019/English/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.icomponent2~getcorresponding.html`
- IsCylinder / CylinderParams: `https://help.solidworks.com/2021/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISurface~IsCylinder.html`、`https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISurface~CylinderParams.html`
- Gear Mates: `https://help.solidworks.com/2024/English/solidworks/sldworks/t_Gear_Mates_SWassy.htm`
- Hinge Mates: `https://help.solidworks.com/2023/english/SolidWorks/sldworks/t_hinge_mates.htm`
- Mate Controller: `https://help.solidworks.com/2024/english/Solidworks/sldworks/c_assembly_mate_controller.htm`

## 添加组件

优先复用 `scripts/sw_assembly.py` 的 `add_component()`。SW2024 中文版 + pywin32 下，
`AddComponent4()` 可能无异常但返回 `None`；当前封装会优先走 `AddComponent5()` 的
8 参数签名，失败后再回退 `AddComponent4()`。若两者都返回空，封装会自动把零件
静默打开到 SolidWorks 会话、重新激活装配体，再重试 `AddComponent5()`。

```python
from sw_assembly import add_component

component = add_component(asm_model, r"E:\parts\base.SLDPRT", x=0, y=0, z=0)
```

底层稳定调用：

```python
component = asm_model.AddComponent5(
    CompPath, 0, "", False, ConfigName, X, Y, Z
)
```

`AddComponent4` / `AddComponent5` 失败时，先检查零件文件是否真实存在、装配体是否为活动文档、零件是否已保存到磁盘；必要时先打开零件再切回装配体。真实回归验证：

```powershell
py -3.13 tests\solidworks_add_component_regression.py --output-dir E:\desktop\CAD\solidworks_add_component_regression
```

## 运动型装配工作流

1. 先生成并保存每个零件，尽量关闭不再编辑的零件文档，避免 SolidWorks 打开的文档过多。
2. 新建装配体，添加底座、轴承座、轴、齿轮、上盖等组件。
3. 对所有需要读特征或面的组件先调用 `resolve_component(component)`；轻化/压缩组件会让 `GetModelDoc2()` 返回 `None`。
4. 用 `IComponent2.GetCorresponding()` 将零件内部基准面、圆柱面或草图实体映射到装配体上下文，再用 `Select2()` 选择。
5. 固定件可以用三基准面重合或距离 Mate 锁死；旋转件不要用三基准面完全锁死。
6. 轴/孔用同心 Mate，`lock_rotation=False`，保留绕轴旋转自由度。
7. 齿轮联动用 Gear Mate；选择齿轮轴线、孔圆柱面、圆柱面或轴实体，按齿数传入比例。
8. 上盖铰链可用同心 Mate 加一个平面重合/距离 Mate 表达一条旋转自由度；若需要 Motion 分析，优先在 GUI 中用官方 Hinge Mate 或用更高阶 MateFeatureData API 生成。
9. 创建后遍历 MateGroup 子特征，确认真实 Mate 写入特征树；预览动画只说明脚本能驱动，不等同于可在软件里拖动。
10. 最后运行 `sw_review.py` 导出多视角预览图，并在 SolidWorks 中手动拖动一个自由件验证运动。

## 在线工程经验摘要

- 官方 Mechanical Mates 文档强调：Gear Mate 只强制两个组件绕所选轴按比例相对转动；Hinge Mate 的效果等价于同心配合加重合配合，并可限制角度。
- GoEngineer 的 Mate 教程把 Mate 理解为零部件之间的几何约束；机械配合用于齿轮、齿条、螺旋、万向节等运动关系，不等同于接触仿真：`https://www.goengineer.com/blog/introduction-to-solidworks-mates`
- CodeStack 的轻化组件示例说明 `GetModelDoc2()` 对轻化/压缩组件会返回空，可通过解析或静默打开引用模型兜底：`https://www.codestack.net/solidworks-api/document/assembly/components/lightweight-get-model-doc/`
- CAD Booster 的 GetCorresponding 文章强调 part context 与 assembly context 不能混用；能拿对象引用时优先用 `GetCorresponding()` + `Select2()`，少依赖坐标点击：`https://cadbooster.com/entities-and-getcorresponding-in-the-solidworks-api/`
- 轻化组件导致 `GetModelDoc2()` 返回空是高频坑；做 Mate 前先解析组件，不要把 `None` 当作“零件没有特征”。

## AddMate5 参数

SolidWorks 2015+ 的 `AddMate5` 是 15 参数签名，Python COM 下 by-ref 错误码必须用 `VARIANT` 包装：

```python
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
mate = asm_model.AddMate5(
    mate_type,          # swMateType_e
    align,              # swMateAlign_e，常用 0=Aligned
    flip,               # bool
    distance,           # 距离配合值，单位米
    distance_upper,     # 距离上限；无限制时等于 distance
    distance_lower,     # 距离下限；无限制时等于 distance
    gear_num,           # Gear Mate 分子
    gear_den,           # Gear Mate 分母
    angle,              # 角度，单位弧度
    angle_upper,        # 角度上限
    angle_lower,        # 角度下限
    for_positioning_only,
    lock_rotation,      # 同心配合是否锁定旋转
    width_mate_option,  # Width Mate 选项
    errors,
)
```

优先复用 `scripts/sw_assembly.py`：

```python
from sw_assembly import (
    add_concentric_mate_by_cylinders,
    add_gear_mate_by_cylinders,
    collect_mate_feature_summary,
)

add_concentric_mate_by_cylinders(
    asm,
    shaft_comp,
    bearing_comp,
    radius_a=(0.004, 0.006),
    radius_b=(0.004, 0.006),
    name="shaft_bearing_concentric",
    lock_rotation=False,
)

add_gear_mate_by_cylinders(
    asm,
    small_gear_comp,
    large_gear_comp,
    teeth_a=18,
    teeth_b=26,
    radius_a=(0.004, 0.008),
    radius_b=(0.004, 0.008),
    name="small_large_gear_ratio_18_26",
)

print(collect_mate_feature_summary(asm))
```

## 配合类型枚举

本机 SW 2024 `SolidWorks.Interop.swconst.dll` 验证过的常用值：

| 值 | 名称 | 说明 |
|---:|---|---|
| 0 | `swMateCOINCIDENT` | 重合 |
| 1 | `swMateCONCENTRIC` | 同心 |
| 2 | `swMatePERPENDICULAR` | 垂直 |
| 3 | `swMatePARALLEL` | 平行 |
| 4 | `swMateTANGENT` | 相切 |
| 5 | `swMateDISTANCE` | 距离 |
| 6 | `swMateANGLE` | 角度 |
| 10 | `swMateGEAR` | 齿轮 |
| 11 | `swMateWIDTH` | 宽度 |
| 16 | `swMateLOCK` | 锁定 |
| 22 | `swMateHINGE` | 铰链 |

组件压缩状态常用值：

| 值 | 名称 | 说明 |
|---:|---|---|
| 0 | `swComponentSuppressed` | 压缩 |
| 1 | `swComponentLightweight` | 轻化 |
| 2 | `swComponentFullyResolved` | 完全解析 |
| 3 | `swComponentResolved` | 解析 |
| 4 | `swComponentFullyLightweight` | 完全轻化 |

## 选择与装配体上下文

稳定顺序：

```python
from sw_assembly import (
    get_component_feature,
    get_assembly_entity,
    find_component_by_name,
    resolve_component,
    select_entities_for_mate,
)

component_a = find_component_by_name(asm, "shaft")
component_b = find_component_by_name(asm, "bearing")
resolve_component(component_a)
resolve_component(component_b)

feature_a = get_component_feature(component_a, ["前视基准面", "Front Plane"])
feature_b = get_component_feature(component_b, ["前视基准面", "Front Plane"])
entity_a = get_assembly_entity(component_a, feature_a)
entity_b = get_assembly_entity(component_b, feature_b)

select_entities_for_mate(asm, entity_a, entity_b, mark=1)
```

注意事项：

- 先解析组件，再选择实体；`SetSuppression2()` 可能清空选择集。
- 第一个实体用 `Select2(False, 1)`，第二个实体用 `Select2(True, 1)` 追加。
- 创建 Mate 前检查 `SelectionManager.GetSelectedObjectCount2(-1) == 2`。
- Gear Mate、普通 Mate 选择标记通常用 `1`；Width Mate 用 `16`，Cam-Follower 用 `8`。

## 圆柱面识别

轴、孔、齿轮轴线常通过最大圆柱面识别：

```python
from sw_assembly import find_largest_cylinder_face

face = find_largest_cylinder_face(
    gear_component,
    min_radius=0.004,
    max_radius=0.008,
)
```

底层逻辑：

```python
bodies = part.GetBodies2(0, False)
for body in bodies:
    for face in body.GetFaces():
        surface = face.GetSurface()
        if surface.IsCylinder:
            params = surface.CylinderParams
            radius = params[6]  # 单位米
```

## 可以在软件里操作吗

可以，但前提是装配体里有真实 Mate 且没有被过约束：

- 在 SolidWorks 打开 `.SLDASM`。
- 使用 `移动零部件` / `Move Component` 拖动轴、齿轮或上盖。
- 如果 Gear Mate 正确，拖动一个齿轮绕轴旋转时，另一个齿轮会按比例反向/同向联动。
- 如果拖不动，优先检查：零件是否固定、同心 Mate 是否勾了 Lock Rotation、是否额外用平面 Mate 把旋转件锁死、Mate 是否报错或过定义。

脚本生成的 GIF/预览视频只能证明“可以被驱动到多个位置”；真正可交互要靠 SolidWorks Mate 求解器和自由度。

## 干涉与运动边界

Gear Mate 不负责防止齿轮实体穿透；它只建立旋转比例关系。需要几何安全时：

- 用 `InterferenceDetection` 或 GUI 中的干涉检查验证。
- 用 Limit Angle / Limit Distance 限制行程。
- 用 Mate Controller 保存几个关键位置并生成 Motion Study 动画。

```python
interference = asm.InterferenceDetection
interference.TreatSubAssembliesAsComponents = False
interference.TreatCoincidenceAsInterference = False
interference.Done()
count = interference.GetInterferenceCount()
```

## 大型装配体建议

- 超过 20 个零件时，分批生成零件，保存后关闭文档，再统一装配。
- 添加组件前确认所有路径存在，失败组件要记录清单。
- 自动化脚本中关闭不必要的图形刷新；最终恢复、重建、导出预览。
- 文档太多或 COM 报内部错误时，先 `CloseAllDocuments(False)`；仍不稳定再重启 SolidWorks 主进程。
