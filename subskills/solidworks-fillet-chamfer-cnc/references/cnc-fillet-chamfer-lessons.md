# CNC 多圆角/倒角建模与验收经验

## v2 能力边界

当前真机路径除恒定半径边圆角、角度倒角和孔口倒角外，已经覆盖六条彼此隔离的高级路径。能力必须按“版本 + 输入拓扑”声明，不能因为 SolidWorks UI 支持就跨环境标记稳定：

- 三中间控制点可变半径、setback corner、face fillet、full-round、平面—圆柱面 G2 组合和非对称宽度-宽度倒角已有 SolidWorks 2026 SP1.1 最小真机回归。
- 保持线/保持面圆角在本机 SW2026 SP1.1 仍为 `blocked`：投影分割线和 mark `2/4/8` 能确定性生成；Python、C# PIA、SWBasic 和官方要求的进程内非托管 C++ 均已实测，故障边界收敛到 `ISetHoldLines`，不是 Python 单一语言限制。原生探测可能令 SolidWorks 服务器故障，默认禁止，只有隔离实例显式授权才复测。
- 顶点倒角、自由曲面间 G1/G2、复杂退刀槽和五轴曲面清根仍未覆盖。

扩展这些能力时，先查目标 SolidWorks 版本的官方 API，再用最小零件完成创建、保存、关闭、重开、特征树回读、STEP 导出和多视角预览。只有连续回归通过后才能修改能力等级。

## v2 离线门禁

`scripts/cnc_strategy.py` 在 COM 之前检查：

- 所有数值有限且尺寸为正；允许为零的圆角/倒角会明确禁用对应操作。
- 凸台相对基体的台阶宽度，圆角半径和倒角深度上限。
- 安装沉孔、定位孔、中心槽、减重口袋的包络、边壁和特征间净距。
- 沉孔和口袋的剩余底壁，以及沉孔直径必须大于通孔直径。
- 矩形减重口袋的尖锐内角 DFM 警告；默认使用长圆槽口袋。

模板默认定位孔改为 `(0, ±24)` mm。旧值 `(±32, 0)` mm 会与总长 62 mm、宽 16 mm 的中心槽相交，不能继续作为“独立定位孔”交付。

## 这次学到的事

本次“CNC 铝合金安装座”验证表明，SolidWorks COM 自动化可以稳定生成多圆角/倒角模型，但必须控制建模顺序和选边方法。成功模型包含底板、中心凸台、安装孔、沉孔、定位孔、中心长槽、减重口袋、真实 Fillet 和 Chamfer 特征，并通过 `sw_review` 规则审查。

最重要的结论：

- 圆角/倒角多的零件，要先让主体拓扑简单，再逐步增加复杂度。
- 大圆角和外轮廓倒角放在孔槽之前，比放在所有切除之后稳定。
- 用实体边对象选择比用自动边名或坐标点击稳定。
- 每个 SolidWorks 特征返回值都要检查 `None` / `False`，失败就立刻中止或降级。
- 同名输出文件如果已在 SolidWorks 打开，保存会失败，典型表现为 `SaveAs` 错误码 `1`。

## 推荐 API 和封装

必须优先调用父技能已有封装：

```python
from sw_session import SolidWorksSession
from sw_connect import mm, get_com_member, create_empty_dispatch_variant
from sw_export import export_to_step
from sw_review import run_review
from sw_appearance import set_document_appearance
```

常用 SolidWorks API：

```python
model.FeatureManager.FeatureExtrusion3(...)
model.FeatureManager.FeatureCut4(...)
model.FeatureManager.FeatureFillet(195, radius, 0, 0, None, None, None)
model.FeatureManager.InsertFeatureChamfer(4, 1, distance, math.pi / 4, 0, 0, 0, 0)
edge.Select2(append, 0)
model.GetBodies2(0, False)
body.GetEdges()
edge.GetCurve()
curve.IsLine()
curve.IsCircle()
curve.CircleParams()
```

pywin32 下 `GetStartVertex`、`GetEndVertex`、`FirstFeature` 等成员可能表现为伪可调用属性，读取时用 `get_com_member()`。

## 稳定选边模式

不要依赖 `Edge1`、`Edge2` 或空名称坐标选择。推荐模式：

```python
def edge_points(edge):
    start_vertex = get_com_member(edge, "GetStartVertex")
    end_vertex = get_com_member(edge, "GetEndVertex")
    if not start_vertex or not end_vertex:
        return None
    return (
        tuple(get_com_member(start_vertex, "GetPoint")),
        tuple(get_com_member(end_vertex, "GetPoint")),
    )

def midpoint(edge):
    points = edge_points(edge)
    if not points:
        return None
    start, end = points
    return tuple((start[i] + end[i]) / 2.0 for i in range(3))

def select_edges(model, predicate):
    model.ClearSelection2(True)
    count = 0
    for body in get_com_member(model, "GetBodies2", 0, False) or []:
        for edge in get_com_member(body, "GetEdges") or []:
            if predicate(edge) and edge.Select2(count > 0, 0):
                count += 1
    return count
```

按端点、圆心、半径、方向和所在平面分类边线。模板使用 0.05 mm 几何容差，并对每类目标声明精确期望数量：基础体立角 4 条，圆角后的外轮廓 8 条，四个沉孔加两个定位孔的孔口圆边 6 条。

每次选择都要记录与 `Edge1` 无关的签名：

```json
{
  "curve": "circle",
  "center_mm": [46.0, 28.0, 18.0],
  "radius_mm": 6.5
}
```

数量不符是拓扑歧义，不是“容差不够”。此时停止并输出全部候选签名；禁止自动放宽到毫米级容差或继续调用特征 API。

### 既有模型选边

模板的 4/8/6 数量断言只适用于对应安装座拓扑。修改既有零件时：

1. 先导出候选边签名清单和等轴测预览。
2. 用用户给出的基准面、特征、尺寸范围和相邻面限定目标，不复用模板固定数量。
3. 把新的期望数量写进该任务的操作计划，并由人工确认一次。
4. 操作完成后重新枚举边；不要复用圆角/倒角前缓存的 COM Edge 对象。

## 推荐特征顺序

用于 CNC 安装座、连接块、机加工基座：

1. 基础矩形底板拉伸。
2. 顶部凸台拉伸。
3. 外轮廓大圆角和顶/底边倒角。
4. 减重口袋。
5. 贯穿安装孔。
6. 沉孔/沉头台阶。
7. 定位孔。
8. 中心长圆槽。
9. 孔口小倒角。
10. 保存、导出 STEP、审查预览。

如果步骤 3 放在孔槽之后，SolidWorks 可能在复杂拓扑上求解很久。若必须后置，先减少半径、减少边数，逐类测试。

## 半径和降级策略

保守默认值：

- 底板立角大圆角：R6-R10
- 凸台立角圆角：R3-R6
- 外轮廓倒角：C0.8-C2
- 凸台顶面倒角：C0.5-C1
- 孔口倒角：C0.3-C0.8

模板提供两种明确策略：

- `strict`：只尝试请求尺寸，失败即停止，适合尺寸不可协商的图纸交付。
- `progressive`：依次尝试请求值的 100%、75%、50%，最小不低于 0.1 mm。

`progressive` 不是静默修复。参数 JSON 必须同时记录 `requested_value_mm`、`actual_value_mm`、状态 `degraded` 和每次失败信息；对外说明必须使用实际尺寸。

人工排障顺序：

1. 减小半径/倒角距离。
2. 减少一次选择的边数。
3. 把大圆角前置到孔槽之前。
4. 若用户允许，显式把非关键槽口/口袋圆角设置为 `0` 后重新生成计划。
5. 关键圆角或倒角不得自动跳过；无法满足时保持阻断。

特征 API 返回非空后仍需 `ForceRebuild3(False)`，并用特征名从树中回读。返回 `None` 才允许进入下一档尺寸；若返回非空但重建后特征消失，应停止而不是继续叠加新特征。

## 推荐扩展路线

按收益与风险排序：

1. **通用既有模型边清单**：导出边-面邻接、曲线类型、长度、包围盒和几何签名，供用户确认语义分组。
2. **更多加工特征**：键槽、燕尾槽、T 型槽、退刀槽、O 形圈槽和沉头孔；每类先补参数/碰撞检查，再接 COM。
3. **多实体和配置**：为每个实体、配置独立保存选边证据，禁止跨配置复用临时拓扑引用。
4. **高级圆角/倒角**：多控制点可变半径、face/full-round、setback、G2 曲面组合和宽度-宽度倒角采用六条独立执行路径与证据，不做一个万能封装；保持线保留独立负向探测。

## SolidWorks 2026 高级圆角实测结论

- 可变半径：`FeatureFillet3`，目标边使用 mark 1，中间 `POINTREF` 使用 mark 256；25%/50%/75% 控制点分别回读 R3/R6/R4，位置读回值是百分数 `25/50/75`，不是比例 `0.25/0.5/0.75`。
- face fillet：`CreateDefinition(swFmFillet)` → `Initialize(swFaceFillet)` → `SetFaces`；两组面分别回读 `Type=2`。
- G2 曲面组合：圆柱顶平面与圆柱侧面分别写入两个 face set，设置 `CurvatureContinuous=true`；重开后必须仍读回 `Type=2` 和 G2 标志。
- full-round：同样使用 `ISimpleFilletFeatureData2`，侧面组 1、中心面组、侧面组 2 分开写入并检查数量，回读 `Type=3`。
- setback：`FeatureFillet3` 中三条交汇边 mark 1、角点 mark 0；距离必须使用 `SAFEARRAY<double>`。在 pywin32 下，普通 `tuple` 可被 COM 接受但求解返回 `None`，必须用 `VARIANT(VT_ARRAY | VT_R8, ...)`。
- 宽度-宽度倒角：`InsertFeatureChamfer` 的 `ChamferType=2`，两侧宽度写入 `Width/OtherDist`，不是顶点倒角参数槽；`GetEdgeChamferDistance` 的 side 索引为 `0/1`。
- 六项均应独立生成零件，避免前一个高级圆角改变后续拓扑；只有保存、STEP、重开、FeatureData 和审查报告全通过才标记 `verified`。
- 保持线：官方要求面组 mark `2/4`、保持线 mark `8` 并设置 `HoldLines`；`ISetHoldLines` 又明确仅支持进程内非托管 C++。当前实现因此包含 C# PIA、SWBasic 和 MSVC x64 原生桥接，不再把后端固定为 Python。SW2026 SP1.1 / Revision 34.1.1 在原生 `ISetHoldLines` 调用处仍复现服务器故障，默认返回结构化阻断；当前回归严格要求创建后及重开后 `GetHoldLineCount=1`，不会把普通 `Fillet` 或分割线特征误报为成功。

官方接口依据：

- [IFeatureManager.FeatureFillet3](https://help.solidworks.com/2026/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~FeatureFillet3.html)
- [ISimpleFilletFeatureData2](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISimpleFilletFeatureData2.html)
- [HoldLines](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISimpleFilletFeatureData2~HoldLines.html)
- [ISetHoldLines（仅进程内非托管 C++）](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISimpleFilletFeatureData2~ISetHoldLines.html)
- [InsertFeatureChamfer](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~InsertFeatureChamfer.html)

## 开源复杂支架回归

第二条复杂回归采用 MIT 许可的 [parametric-bracket-library](https://github.com/archimedes-market/parametric-bracket-library) `l_gusset`，锁定提交 `5b285130...`、CadQuery 2.8.0 和生成 STEP 的 SHA-256 `cc2d38a4...`。CadQuery 源模型包含两块垂直安装板、三角加强筋与六孔；SW2026 STEP 导入基线为 `1 solid / 18 faces / 49 edges`。增强脚本在同一实体上创建四中间控制点可变半径圆角（位置 `20/40/60/80%`，半径 `1.2/1.8/0.9/1.5 mm`）和 C0.8/C1.4 宽度-宽度倒角，并以处理后 `20 faces / 55 edges`、重开 FeatureData 和四视角审查作为闭环证据。

原有 FreeCAD-library 案例继续提供另一套独立来源和几何签名验证：

选用 FreeCAD-library 的 `2020_corner_bracket-Corner.step`，固定提交 `b342740f...` 与 SHA-256 `25e3fbc1...`。该件包含底板、立板、加强结构、孔和长圆槽；源拓扑回读为 `1 solid / 40 faces / 98 edges / 64 vertices`。脚本按清单锁定端点 `(-0,-20,3)→(-0,-3,20) mm`、长度 `24.041631 mm` 的唯一斜边，实际创建 C0.2/C0.4 宽度-宽度倒角；处理与重开拓扑均为 `1 solid / 41 faces / 101 edges / 66 vertices`。复杂件结果补充证明真实拓扑上的求解和持久化，六个受控样例仍负责高级参数的独立精确读回。

案例采用 FreeCAD-library 的 [CC BY 3.0](https://github.com/FreeCAD/FreeCAD-library) 许可，贡献者署名和下载哈希写入 `examples/open_source_corner_bracket_case.json`。
5. **制造验收**：加入刀具直径、刀长、最小内圆角、装夹方向、可达性和工序建议；规则通过仍需 CAM/工艺人员复核。

## 常见故障

### 拉伸返回 None

常见原因是复杂圆角草图没有闭合。改用简单矩形草图拉伸，再对立角做真实 Fillet。

### 圆角/倒角卡很久

多半是切孔后拓扑复杂、半径过大或选边过宽。先单独测试每一类边：底板立角、凸台立角、顶边、底边、孔口。

### SaveAs 错误码 1

目标文件可能已经在 SolidWorks 中打开。新建前关闭同名文档：

```python
try:
    session.close(title=Path(output_part).name)
except Exception:
    pass
```

### 预览偏透明或颜色怪

不要把外观问题当作几何失败。先确认审查报告和预览非空。外观要求高时使用 `set_document_appearance(model, "silver")` 或拆装配体分组件上色。

## 审查清单

完成后读取 review report，至少确认：

- `evaluation.status`
- `checks.previews_created`
- `checks.previews_not_blank`
- `checks.expected_outputs_exist`
- `model.features` 中是否有 `Fillet`、`Chamfer`、`Cut` 特征

若规则审查通过，还要人工看 `isometric` 和 `top` 预览，确认主体比例、孔位、沉孔、长槽、口袋和圆角方向。
