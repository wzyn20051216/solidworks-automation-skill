# 尺寸公差 API 参考

为工程图上的 `DisplayDimension` 设置尺寸公差（对称 ±、上下限、MIN/MAX 等），并按
GB/T 1804-m 通用公差按名义尺寸自动分档。能力清单记录为 `dimension_tolerances=pilot`
（SW2024 已在 5 个自制件工程图上连续回归，每张 W/H/D 三向 ±GB/T 1804-m）。

> 本能力只覆盖**线性尺寸公差**。GD&T 几何公差框（形位公差、基准、轮廓度等）仍为
> `reference_only`，关键配合（H7/g6 等）的配合公差须人工标注并复核。

## API 路径

```python
# display_dimension: 工程图上已存在的 IDisplayDimension（来自 InsertModelAnnotations3/4
# 或坐标扫描式标注 sw_drawing.edge_scan_dimension()）。
dimension = display_dimension.GetDimension()      # -> IDimension
dimension.SetToleranceType(tol_type)              # int: 见下表
dimension.SetToleranceValues(plus_m, minus_m)     # float, float —— 单位为米
```

- `GetDimension()` 返回 `IDimension`；公差类型与公差值都设在它上面。
- 技能封装统一经 `sw_connect.get_com_member()` 调用，兼容动态派发下属性/方法歧义。

## 公差类型枚举（swTolType_e）

| 值 | 枚举 | 说明 | SW2024 实证 |
|---|---|---|---|
| `0` | `swTolNONE` | 无公差 | — |
| `1` | `swTolMIN` | 最小值 | — |
| `2` | `swTolMAX` | 最大值 | — |
| `3` | `swTolBASIC` | 基本尺寸（框格） | — |
| `4` | `swTolSYMMETRIC` | 对称 ±（上下同值） | ✅ 已验证渲染 |
| `5` | `swTolBILATERAL` | 双向（上下不同） | — |
| `6` | `swTolLIMIT` | 极限尺寸 | — |

> 未在本机验证的枚举值请先以 `references/api-lookup.md` 的流程查证 `swconst.tlb` 再使用；
> 技能约定**硬编码整数 + 注释标明枚举来源**，不依赖 `SolidWorks.Interop.swconst.dll` 加载。

## 三个必踩的坑

1. **必须用 `SetToleranceType` 方法启用 ± 显示。** `dimension.Tolerance().Type = 4` 这类
   属性赋值只写内部数据、**不触发渲染**，图面上看不到公差。只有 `SetToleranceType(4)`
   会真正切换显示模式。
2. **公差带宽按“已知名义尺寸”查表，不要读尺寸回读值。** `GetValue2` / `SystemValue`
   在不同尺寸上的单位不一致（有的是 mm、有的是 m），直接拿回读值去查 GB/T 1804-m 会错档。
   本能力的封装一律由调用方传入名义尺寸（mm）。
3. **`SetToleranceValues` 取米。** ±0.2 mm 须传 `0.0002`，传 `0.2` 会得到荒谬结果。

## GB/T 1804-m 通用公差（中等级）

| 名义尺寸区间（mm） | 对称 ±（mm） |
|---|---|
| ≤ 6 | ±0.1 |
| > 6 ～ ≤ 30 | ±0.2 |
| > 30 ～ ≤ 120 | ±0.3 |
| > 120 ～ ≤ 400 | ±0.5 |
| > 400 | ±0.8 |

> 这是 GB/T 1804 一般公差的“中等级 m”。未注公差的线性尺寸默认套用此表；精密或粗加工
> 场合可改用 f（精密）/c（粗糙）/v（最粗）等级，但本封装只内置 m。

## 技能封装（`scripts/sw_drawing.py`）

```python
from sw_drawing import gb1804m_band, set_dimension_tolerance, apply_gb1804m

# 纯查表（可单测）
band_mm = gb1804m_band(nominal_mm=45)        # -> 0.2

# 显式对称 ±：plus/minus 留空时按 GB/T 1804-m 自动分档
report = set_dimension_tolerance(display_dimension, nominal_mm=45.0)   # ±0.2

# 便捷封装：直接套 GB/T 1804-m 对称公差
report = apply_gb1804m(display_dimension, nominal_mm=45.0)

# 显式上下限（双向，tol_type=5）
report = set_dimension_tolerance(
    display_dimension, nominal_mm=45.0, tol_type=5, plus_mm=0.2, minus_mm=0.1,
)
```

`set_dimension_tolerance` / `apply_gb1804m` 返回证据字典，遵循工程图模块的统一约定
（`status`、`tolerance_type`、`plus_mm`、`minus_mm`、`nominal_mm`、`band_source`、
`rendered_via`、`manual_review_required`）。`status="pass"` 表示 `SetToleranceType` +
`SetToleranceValues` 调用成功；但仍须目视复核图面是否真正显示公差（不同 SolidWorks
版本/语言下个别尺寸类型可能不渲染，须以导出 PDF/BMP 复核为准）。

## 回归证据

SW2024 电机项目：工件 / 夹爪 / 支架 / 桌腿 / 桌面 5 个自制件工程图，每张 W/H/D 三向
均按 GB/T 1804-m 标注对称公差，导出 PDF 目视确认 ± 公差正确显示。脚本来源为
`examples/gen_manufacturing_drawing.py`（端到端：建图→扫描标注→套公差→导出 PDF）。
