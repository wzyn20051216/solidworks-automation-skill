# 质量属性 API 参考

读取零件/装配体的质量、体积、表面积和重心。能力清单记录为 `mass_properties=pilot`
（SW2024 已在 3 个外购件上回归体积/表面积）。

## API 路径

```python
# model: 已打开的零件或装配体文档（IModelDoc2）。Extension 是属性，不要当方法调用。
extension = model.Extension                       # IModelDocExtension（属性）
status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
props = extension.GetMassProperties2(accuracy, status, default_density)
# accuracy:        0=普通精度
# default_density: 当几何未指定材料时使用的兜底密度（kg/m³），通常传 0.0
```

`GetMassProperties2` 返回一个浮点数组（顺序固定，SI 单位）：

| 索引 | 含义 | 单位 |
|---|---|---|
| 0,1,2 | 重心 X/Y/Z | m |
| 3 | 体积 | m³ |
| 4 | 表面积 | m² |
| 5 | 质量 | kg |
| 6 | 惯性主轴 xx | kg·m² |
| 7,8,9 | 惯性张量（绕重心） | kg·m² |

换算到毫米/克：体积 `m³ × 1e9 = mm³`，表面积 `m² × 1e6 = mm²`，重心 `m × 1000 = mm`。

## 必须经过 `sw.ActiveDoc.Extension`

`sw.OpenDoc6(...)` 在动态派发下返回**未类型化**的 IDispatch；在其上调用 `GetBox`、
`GetFirstFeature` 等文档级方法常报 “Member not found”。可靠做法：打开后取
`pdoc = sw.ActiveDoc`（属性，经 `get_com_member` 读取），再 `pdoc.Extension` →
`GetMassProperties2`。技能封装 `sw_connect.open_document()` 已处理这层激活与派发问题。

## 质量依赖材料密度

`props[5]`（质量）只有在该文档**已指定材料/密度**时才有意义：

- 未指定材料时，SolidWorks 用上一次的默认密度或 0；质量可能为 0 或荒谬值。
- `default_density` 参数只是几何**没有材料**时的兜底，不能替代真实材料赋值。
- 封装在检测到材料未赋或质量明显异常（如 0）时返回 `status="review_required"`，
  **不伪造数值**；调用方须先指定材料或人工确认。

> 材料赋值（`InsertMaterial` / `SetMaterialPropertyName`）目前**尚未封装**，关联
> `appearance` 能力为 TODO。在此之前，质量字段一律标记为需人工复核。

## 技能封装（`scripts/sw_mass_properties.py`）

```python
from sw_connect import connect_solidworks, open_document
from sw_mass_properties import mass_properties

sw, _ = connect_solidworks()
model = open_document(sw, r"D:\parts\bolt.sldprt")
report = mass_properties(model)
# -> {
#      "status": "pass" | "review_required",
#      "mass_kg": ...,            # 材料未赋时可能无意义 -> review_required
#      "volume_mm3": ...,
#      "surface_mm2": ...,
#      "center_of_mass_mm": [x, y, z],
#      "mass_meaningful": bool,
#      "accuracy": 0,
#      "review_required": True,    # 质量始终须人工复核材料
#      "limitations": [...],
#    }
```

`mass_properties(model)` 只读不改；不保存、不修改文档。

## 回归证据

SW2024 电机项目 3 个外购件实测（`probe_parts.py`）：

| 件 | 体积（mm³） | 表面积（mm²） |
|---|---|---|
| 螺栓M8（占位几何） | 1099.6 | — |
| 钻头M5（占位几何） | 484.9 | — |
| 钻夹头（占位几何） | 2650.7 | — |

> 这些是**占位几何**的体积，仅用于验证 API 通路；真实采购件体积/质量须以厂商图纸为准。
