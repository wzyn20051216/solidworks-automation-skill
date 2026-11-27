# 设计规格驱动建模

用一份**可版本控制的设计规格文件**描述零件，再由执行器幂等地重建模型。

## 为什么需要它

祈使式调用（`sketch_circle` → `extrude_boss` → `save`）适合一次性的脚本，但不适合
产品的迭代：工程师真正要做的是"把安装板改成 8mm 厚、四个 M6 孔改成 M8"，
而不是重写整个建模序列。规格文件的三个价值：

1. **可 diff / 可 commit** — 提交的是设计意图，不是一次性脚本。
2. **幂等可重建** — 同一份规格任何时候构建出的特征树结构一致。
3. **内建验证** — `verify` 段在构建后自动回读几何并与期望比对。

## 最小可用规格

```json
{
  "schema_version": "1.0",
  "part_name": "motor_mount",
  "units": "mm",
  "base": { "type": "rect_plate", "width": 120, "height": 80, "thickness": 8 },
  "holes": [
    { "id": "H1", "type": "through", "diameter": 6.6, "position": [15, 15] },
    { "id": "H2", "type": "through", "diameter": 6.6, "position": [105, 15] },
    { "id": "H3", "type": "through", "diameter": 6.6, "position": [15, 65] },
    { "id": "H4", "type": "through", "diameter": 6.6, "position": [105, 65] }
  ],
  "fillets": [ { "radius": 4, "axis": "z", "convex_only": true } ],
  "verify": { "envelope_mm": [120, 80, 8], "hole_count": 4, "tolerance_mm": 0.1 }
}
```

## 坐标系约定（重要）

**原点在板料左下角**，板面位于 XY 平面第一象限，沿 +Z 拉伸。

因此 `position: [15, 15]` 就是图纸上"距左边 15、距下边 15"，不必做居中偏移的心算。
这是机械图纸标注孔位的默认方式，规格直接沿用。

> 孔中心若落在板外，或有孔壁超出边界，执行器会在建孔**之前**报错并列出越界的孔。
> 越界的孔在 SolidWorks 里会被静默拒绝（表现为"特征创建成功但不存在"），
> 提前校验能让你立刻知道是坐标问题而不是 API 问题。

## 字段参考

### base（基础实体）

| type | 必填字段 | 说明 |
|---|---|---|
| `rect_plate` | `width` `height` `thickness` | 矩形板，原点在左下角 |
| `cylinder` | `diameter` `height` | 圆柱，轴心在原点 |
| `none` | — | 不建基础实体，只建后续特征（须**显式**写出） |

省略 `base` 会报 `SPEC_EMPTY`：漏写与"只要后续特征"是两种意图，不能默认混同。

### holes（孔）

| type | 必填字段 |
|---|---|
| `through` | `diameter` `position` |
| `blind` | `diameter` `depth` `position` |
| `counterbore` | `diameter` `counterbore_diameter` `counterbore_depth` `position` |
| `countersink` | `diameter` `countersink_diameter` `angle`（默认 90，包含角） `position` |

`id` 建议总是提供。缺省时会自动编号（`H1`、`H2`…）并给出提醒——检验记录需要
稳定的追溯标识，自动编号在插入新孔后会整体错位。

**孔阵列**：在孔上附加 `pattern` 字段可一次定义多个孔，执行器展开为独立孔并重新编号：

```json
{ "id": "B", "type": "through", "diameter": 5.5, "position": [60, 40],
  "pattern": { "type": "circular", "count": 6, "radius": 30, "start_angle": 0 } }
```

```json
{ "id": "L", "type": "through", "diameter": 5.5, "position": [10, 10],
  "pattern": { "type": "linear", "count": 4, "dx": 20, "dy": 0 } }
```

`circular` 的孔位相对 `position` 偏移；`start_angle` 以度计，0 度为 +X 方向。

### fillets（圆角）

```json
{ "radius": 4, "axis": "z", "convex_only": true }
```

| 字段 | 说明 |
|---|---|
| `radius` | 圆角半径 |
| `axis` | `x` / `y` / `z` / `vertical` / `all`，只对平行于该轴的边倒圆角 |
| `convex_only` | 只倒凸边（外轮廓） |
| `concave_only` | 只倒凹边（内角） |

圆角半径超过板厚一半时会给出 DFM 警告（SolidWorks 可能无法生成或产生自交）。

选不到边线时该圆角被**跳过并记入警告**，不会退回"对当前选择集操作"——
后者会把圆角加到错误的边上，产生难以排查的模型。

### verify（构建后验证）

| 字段 | 说明 |
|---|---|
| `envelope_mm` | 期望的零件实体外形尺寸，按模型 `[X, Y, Z]` 轴排列 |
| `hole_count` | 期望的孔数 |
| `tolerance_mm` | 尺寸公差（默认 0.1） |
| `min_mass_g` / `max_mass_g` | 质量上下限 |

验证结果有三种状态：`pass`（全部符合）、`warn`（有偏差，需人工复核）、
`skipped`（未提供 verify 段）。**偏差不会自动判为失败**——设计变更也会导致
尺寸变化，必须由工程师判断。

## 单位

`units` 支持 `mm`（默认）、`cm`、`m`、`in`。规格内所有长度按该单位书写，
执行器统一换算为毫米。**不支持猜单位**：未知单位会直接报错。

## 使用方式

```
# 只校验，不建模型（改规格时反复调用）
design_spec_validate  { "spec_path": "D:/designs/motor_mount.json" }

# 校验并构建
design_spec_build     { "spec_path": "D:/designs/motor_mount.json",
                        "output_path": "D:/designs/motor_mount.sldprt" }
```

也可以直接调用 Python：

```python
from scripts.design_spec import load_design_spec
from scripts.build_from_spec import build_from_spec
from scripts.sw_connect import connect_solidworks, new_document, save_document

validation = load_design_spec("D:/designs/motor_mount.json")
assert validation["status"] == "ok", validation["errors"]

sw, _ = connect_solidworks()
model = new_document(sw, "part")
audit = build_from_spec(model, validation["normalized"])
print(audit["status"], audit["verification"])
save_document(model, "D:/designs/motor_mount.sldprt")
```

## 返回结构与证据

`build_from_spec` 返回的审计结果包含：

| 字段 | 含义 |
|---|---|
| `status` | `ok` / `warn` / `error` |
| `steps` | 每一步的实际执行情况（特征名、位置、是否成功） |
| `hole_count_requested` / `hole_count_created` | 规格要求的孔数 vs 实际创建的孔数 |
| `fillet_results` | 每个圆角选中的边数与特征名 |
| `warnings` | 不阻断的问题（DFM 提示、圆角跳过、材料未分配） |
| `errors` | 阻断性问题，附带可操作的下一步 |
| `measurements.bounding_box` | 毫米包围盒。要求核验 `verify.envelope_mm` 时，按当前配置全部实体的轴向极值测量；否则为近似包围盒。 |
| `measurements.mass_properties` | 回读的质量、体积、材料 |
| `verification` | 与 `verify` 段的比对结论 |

增量检查应看 `steps`：它逐条列出"哪个孔在什么位置、创建成了什么特征"，
便于与图纸逐项核对。

## 常见错误码

| 错误码 | 含义与处理 |
|---|---|
| `SPEC_UNIT_UNSUPPORTED` | 单位不在支持列表；改为 mm/cm/m/in |
| `SPEC_EMPTY` | 未定义 `base`；确认是否漏写，或显式写 `"type": "none"` |
| `SPEC_HOLE_ID_DUPLICATE` | 孔 id 重复，改为唯一值 |
| `SPEC_FIELD_MISSING` | 缺少该孔类型必填的尺寸字段 |
| `SPEC_NOT_POSITIVE` | 尺寸必须为正数 |
| `SPEC_HOLE_TYPE` | 未知孔类型 |
| `SPEC_HOLES_TOO_MANY` | 孔数超过 200 上限 |
| `SPEC_JSON_INVALID` | JSON 语法错误，附带解析位置 |
| `SPEC_FILE_MISSING` | 文件路径不存在（使用绝对路径） |

校验器**一次性返回全部错误**，而不是遇到第一个就停，便于一次改完。
