# 外观与材质参考

## 核心规则

SolidWorks 的九位材质数组必须以 `SAFEARRAY(double)` 传给 COM。不要直接把 Python
`list` 赋给 `MaterialPropertyValues`；在 pywin32 动态分派下，普通列表可能被错误编组，
表现为 RGB 落入第 2、5、8 位，最终模型几乎只显示绿色。

稳定封装位于 `scripts/sw_appearance.py`：

- `material_variant()`：把九位数组封装为 `VT_ARRAY | VT_R8`。
- `set_document_appearance()`：写入并回读文档级 RGB。
- `set_feature_appearance()`：写入并回读特征级 RGB。
- `set_component_appearance()`：写入并回读装配组件级 RGB。
- `apply_component_palette()`：批量上色并生成逐组件审计结果。
- `verify_appearance()`：比较预期 RGB 与 COM 回读值。

## 推荐用法

```python
from sw_appearance import (
    apply_component_palette,
    set_document_appearance,
    set_feature_appearance,
    verify_appearance,
)

set_document_appearance(model, "iron_red")
set_feature_appearance(feature, "armor_gold")
assert verify_appearance(model, "iron_red")["ok"]

reports = apply_component_palette([
    (body_component, "aqua_blue"),
    (glass_component, "glass_tint"),
    (rear_light_component, "signal_red"),
    (rim_component, "silver"),
])
assert all(item["ok"] for item in reports)
```

## 预设颜色

| 名称 | 说明 |
|---|---|
| `iron_red` | 深红装甲 |
| `armor_gold` | 金色装甲 |
| `dark_gunmetal` | 深色金属/关节 |
| `arc_blue` | 蓝色发光件 |
| `silver` | 银色金属 |
| `black` | 黑色 |
| `white` | 白色 |
| `aqua_blue` | 青蓝车身色 |
| `glass_tint` | 深色玻璃 |
| `signal_red` | 尾灯/警示红 |
| `light_cyan` | 浅蓝发光件 |
| `tire_black` | 轮胎黑 |
| `graphite` | 石墨灰 |

## 已验证 API 签名

本机 SolidWorks 2024 SP3.1 的 `SolidWorks.Interop.sldworks.dll` 反射结果：

```text
IModelDoc2.MaterialPropertyValues = Object
IModelDocExtension.SetMaterialPropertyValues(Object, Int32, Object) -> void
IFeature.SetMaterialPropertyValues(Object) -> bool
IFeature.SetMaterialPropertyValues2(Object, Int32, Object) -> void
IComponent2.SetMaterialPropertyValues2(Object, Int32, Object) -> void
IComponent2.GetMaterialPropertyValues2(Int32, Object) -> Object
```

配置选项：`swThisConfiguration=1`、`swAllConfiguration=2`、
`swSpecifyConfiguration=3`。返回 `void` 的 setter 只要没有 COM 异常即表示调用完成，
不能写成 `bool(method(...))` 判断成败；最终必须以 `verify_appearance()` 回读为准。

## 多色装配工作流

1. 在源零件文档级设置基础颜色并保存。
2. 添加组件后按需设置组件级覆盖色。
3. 每次写入后回读前三位 RGB；不匹配立即停止。
4. 保存前调用 `assembly.ClearSelection2(True)`。
5. 预览前再次清除选择并重绘，避免绿色选择高亮覆盖真实外观。
6. 至少检查一张彩色等轴测图和一张能看到灯组/轮毂的正投影视图。

## 稳定性建议

- 单零件多特征上色可能受 SolidWorks 版本、显示状态、特征合并影响。
- 对颜色要求高的模型，优先拆成多个零件，并对每个零件使用文档级外观。
- 复杂项目建议输出装配体，由组件层级表达颜色、材质和可替换模块。
- 不要把“setter 未抛异常”当作颜色正确；必须回读 RGB。
- 不要在仍有选中组件/面/边时截图；绿色选择色会干扰视觉判断。
- 生成后必须用 `sw_review.py` 导出预览图检查颜色和层次是否可见。
