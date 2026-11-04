# 语义选边：圆角与倒角的正确做法

## 为什么不能用 SelectByID2 选边

SolidWorks 传统的选边方式是：

```python
model.Extension.SelectByID2("Edge1", "EDGE", 0.05, 0.03, 0.0, False, 0, None, 0)
```

这里的 `x, y, z` 是**实体的坐标魔法值**。它有两个致命问题：

1. **模型一改就失效**。改了板厚、加了个孔，坐标全部偏移，选择静默失败。
2. **失败是静默的**。`SelectByID2` 返回 `False` 时，后续的 `FeatureFillet` 不会
   报错——它会对"当前选择集"（可能是空的，也可能是上一次操作的残留）执行圆角，
   产生难以定位的错误特征。

## 正确做法：按 B-Rep 几何选边

`scripts/sw_edge_select.py` 遍历模型的 B-Rep 拓扑，按**几何条件**挑选边线，
再用边对象自身的 `Select2` 建立选择集。不依赖名称和坐标字符串，模型重建后依然可用。

```python
from scripts.sw_edge_select import select_edges
from scripts.sw_part import fillet
from scripts.sw_connect import mm

# 只倒平行于 Z 轴的凸边（即立板的外轮廓竖边）
result = select_edges(model, {"axis": "z", "convex_only": True})
if result["status"] == "ok" and not result["errors"]:
    fillet(model, mm(4))
```

对应的 MCP 工具：

```
solidworks_list_edges  { "axis": "z" }              # 先看有哪些边
solidworks_fillet      { "radius_mm": 4, "axis": "z", "convex_only": true, "dry_run": true }
solidworks_fillet      { "radius_mm": 4, "axis": "z", "convex_only": true }
```

**建议先用 `dry_run: true`** 确认选中的边正是你想倒的那些，再执行。

## 筛选条件

| 参数 | 取值 | 说明 |
|---|---|---|
| `axis` | `x` / `y` / `z` / `vertical` / `all` | 只保留平行于该轴的**直边**；`all` 不做方向过滤 |
| `min_length_mm` / `max_length_mm` | 数值 | 按边长筛选 |
| `circular` | `true` / `false` | 只保留圆边 / 只保留非圆边 |
| `diameter_mm` + `diameter_tolerance_mm` | 数值 | 按圆边直径筛选（用于选孔的入口边） |
| `position_mm` + `position_tolerance_mm` | `[x,y,z]` | 边中点必须靠近该坐标 |
| `convex_only` | `true` | 只保留凸边（外轮廓），用于外圆角 |
| `concave_only` | `true` | 只保留凹边（内角），用于内圆角 |

`convex_only` 与 `concave_only` 不能同时为真。

## 典型用法

**板料四角外圆角**

```json
{ "axis": "z", "convex_only": true }
```

**沉头孔入口倒角**（按孔径定位圆边）

```json
{ "circular": true, "diameter_mm": 6.6, "diameter_tolerance_mm": 0.05 }
```

**只倒长边**（避免倒到短边形成"圆角打架"）

```json
{ "axis": "all", "min_length_mm": 50 }
```

**减重口袋的内圆角**

```json
{ "axis": "z", "concave_only": true }
```

## 返回值

```json
{
  "status": "ok",
  "selected_count": 4,
  "selected": [
    { "index": 3, "length_mm": 8.0, "mid_point_mm": [0.0, 0.0, 4.0],
      "is_circle": false, "diameter_mm": null, "convexity": "convex" }
  ],
  "rejected_count": 8,
  "rejected_sample": [ { "index": 0, "reasons": ["方向不平行于 z 轴"] } ]
}
```

`rejected_sample` 会说明每条边**为什么被排除**，便于调整条件而不是盲目放宽。

**选不到边时返回 `status: "error"`，绝不继续创建特征。** 这是刻意设计：
静默继续会把圆角加到错误的边上。错误信息会附上调用
`solidworks_list_edges` 的建议。

## 凸凹判定

`convexity` 通过边两侧面的法向关系计算，这是凸凹的几何定义，不依赖 SolidWorks
的显示选项。

判定需要读取相邻面的参数。**读取失败时返回 `null`，该边不会被排除**——宁可多选
也不漏选用户明确要求的边。此时请用 `solidworks_list_edges` 复核结果。

## 已知边界

- 圆边没有"轴向"概念，`axis` 筛选会把它排除；选孔的入口边请用 `circular` + `diameter_mm`。
- 曲面间的相切边（例如已有圆角产生的切边）会被当作普通边返回。**在同一模型上
  连续做多组圆角/倒角时，后一组可能选到前一组产生的切边**——每组操作前用
  `solidworks_list_edges` 确认当前拓扑，或把不同组的特征拆到不同阶段。
- 保持线（hold line）圆角仍为受限能力，见 `subskills/solidworks-fillet-chamfer-cnc/`。

## API 注意事项

`IEdge::Select4(Append, Callout)` 的第二个参数是 **Callout 对象**，
必须是 Dispatch VARIANT。传 Python 的 `None` 会得到
`类型不匹配`（`0x80020005`）。

`IEdge::Select2(Append, Mark)` 没有这个问题，因此封装**优先走 Select2，失败才退到
Select4**。写自己的选边代码时请沿用同样的顺序。

```python
# 正确
edge.Select2(True, 0)
# 需要 Select4 时
from scripts.sw_connect import create_empty_dispatch_variant
edge.Select4(True, create_empty_dispatch_variant())
```

## 圆角 API 的一个坑

`IFeatureManager::FeatureFillet` 只接受 **4 个参数**：

```python
model.FeatureManager.FeatureFillet(195, radius, 0, 0)   # (Options, Radius, R1, R2)
```

不要传 7 个参数（在末尾补 `None`）——这会在 SolidWorks 2024/2026 上抛
`非选择性的参数`（`0x8002000F`）。旧版本文档和早期封装里有这个错误写法。

同理，所选边必须非空；`sw_part.fillet()` 已经显式校验选择集，为空时抛
`ValueError` 并提示改用 `select_edges()`。


## 长度、直径与 COM 兼容契约

长度读取必须使用 `ICurve.GetLength3(start, end)`，IEdge 没有 `GetLength`。`GetCurveParams2` 的官方返回值是 11 个 double：前六项为起终点，索引 6/7 为曲线参数，末三项为打包整数。半径在 `ICurve.CircleParams` 的第七项中，不能从边线参数中推测。

实现先取得 ICurve，再读取参数并校验官方布局和有限数值。反向边按打包的 SenseFlag 恢复曲线参数；未知布局、无效参数、NaN、Infinity 和非正长度均报告错误。短圆弧的直径可以远大于弧长，因此不能以“直径与弧长同量级”作为合法性条件。

整圆可能没有起止顶点，此时使用已验证的曲线参数端点。直线方向使用端点差或 `LineParams` 的方向向量，不能把终点坐标直接当方向。`position_mm` 当前比较的是起止端点平均位置，不代表一般曲线的弧长中点；复杂曲线定位需要另外的几何证据。

pywin32 成员绑定失败时，兼容路径从实际对象的名称绑定或类型信息取得 GetCurve 的成员 ID，再调用 COM；不硬编码 DISPID。SolidWorks 的部分实际边线对象不提供类型信息；如果名称绑定也不可用，就明确报错。真实执行错误不会被当作绑定失败盲目重试。获取失败时保留错误，不能以空 `errors` 冒充成功。

自动化调用应同时检查 `status`、`selected_count` 和 `errors`。不匹配任何边线时返回错误。无效方向、非有限筛选阈值和倒置的长度区间被拒绝。

```powershell
python -m pytest -q tests/test_sw_edge_select.py
python tests/solidworks_edge_select_live.py
```

真机脚本仅操作临时模型：100×60×6 mm 长方体、直径 20 mm 圆柱、偏离原点的 5° 环扇形。保存重开前后验证长度、直径、选择数量和不匹配行为，并用真实 IEdge 强制验证两条 COM 兼容路径；保存预览和 JSON 证据，核对源文件哈希及用户文档集合。

官方依据：

- [IEdge.GetCurveParams2](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.iedge~getcurveparams2.html)
- [ICurve.GetLength3](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurve~GetLength3.html?format=P&value=)
- [ICurve.CircleParams](https://help.solidworks.com/2021/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurve~CircleParams.html)
- [ICurve.LineParams](https://help.solidworks.com/2016/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurve~LineParams.html)
