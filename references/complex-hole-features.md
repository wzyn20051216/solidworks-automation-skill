# 复杂孔槽自动化

## 支持范围

`scripts/sw_hole_features.py` 使用草图和切除特征创建以下结构：

- 定深盲孔。
- 完全贯穿孔。
- 通孔 + 圆柱沉孔的两级复合孔。
- 通孔 + 指定包含角的锥形沉头孔。
- 两端为半圆的直槽，支持贯穿或定深。
- 按显式坐标创建的孔阵列。

该模块不调用 `HoleWizard5`。Hole Wizard 的长参数和版本差异没有完成官方签名与真实版本验证前，禁止凭记忆拼接参数。

## 单位与基准

- 所有输入长度使用米，建议由 `sw_connect.mm()` 转换。
- `center`、`start`、`end` 是目标草图平面的局部二维坐标。
- 默认基准面是 `Front Plane`，中文版由 `sw_part.start_sketch()` 自动兼容。
- 创建参数证据同时输出米和毫米字段，但毫米字段只用于报告，不回传 COM。

## 示例

```python
from sw_connect import mm
from sw_hole_features import (
    create_blind_hole,
    create_counterbore_hole,
    create_countersink_hole,
    create_semicircular_slot,
)

blind = create_blind_hole(model, (mm(20), mm(20)), mm(8), mm(10), name="H1_盲孔")
counterbore = create_counterbore_hole(
    model,
    (mm(50), mm(20)),
    hole_diameter=mm(6),
    counterbore_diameter=mm(12),
    counterbore_depth=mm(4),
    name="H2_沉孔",
)
countersink = create_countersink_hole(
    model,
    (mm(80), mm(20)),
    hole_diameter=mm(5),
    countersink_diameter=mm(10),
    included_angle_deg=90,
    name="H3_沉头",
)
slot = create_semicircular_slot(
    model,
    (mm(30), mm(50)),
    (mm(60), mm(50)),
    width=mm(10),
    depth=0,
    name="S1_半圆端槽",
)
```

## 验收证据

创建函数返回的是参数证据，不是几何验收结论。交付前必须继续执行：

1. `sw_review.collect_geometry_measurements()` 读取 B-Rep 圆柱面。
2. `sw_review.validate_hole_positions()` 验证孔径和孔轴线位置。
3. 对盲孔深度、沉孔深度和沉头角度回读特征参数，或用剖视图人工复核。
4. 半圆槽端部圆柱面必须进入 `slot_arc_candidates`，不能被计入圆孔数量。
5. 复合孔应在 `compound_holes` 中出现同轴多直径孔段。

推荐每个孔至少记录：孔型、规格、数量、基准边定位、中心距、深度/贯穿状态、尺寸公差和证据来源。

## 已知限制

- 锥形沉头使用通孔入口圆边的角度/距离倒角。入口边按圆心、半径和基准面位置筛选，不依赖临时边线名称；倒角后仍必须查看剖视图确认入口方向。
- B-Rep 单独不能可靠区分盲孔和通孔；必须与创建参数或特征定义回读交叉验证。
- 当前孔阵列按显式孔位逐个建特征，优先保证可审计性；大量规则阵列后续可增加 Linear/Circular Pattern 封装。
