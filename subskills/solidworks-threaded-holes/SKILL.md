---
name: solidworks-threaded-holes
description: SolidWorks ISO 公制内螺纹孔自动化子技能。用于创建和审查 M3-M12 粗牙或用户明确底孔的自定义公制内螺纹，覆盖攻丝底孔、盲孔/贯穿孔、孔口倒角、右旋/左旋、ThreadFeatureData/CosmeticThread 降级和交付证据。用户要求 Hole Wizard、修改现有零件、外螺纹、英制/管螺纹或显式牙型时也应读取本技能，但这些能力必须按路线图标为 pilot 或人工复核，不得宣称已稳定实现。
---

# SolidWorks Threaded Holes

## 先判定能力等级

当前稳定脚本是 `scripts/create_threaded_hole_template.py`，它在新建矩形样件上生成 ISO 公制内螺纹孔。

- `verified`：M3/M4/M5/M6/M8/M10/M12 粗牙内螺纹，盲孔或真正 `Through All` 底孔，孔口倒角，右旋/左旋，公差属性，真实 `Metric Tap` Thread 特征，STEP 和审查证据。已在 SolidWorks 2026 实测盲孔与贯穿孔。
- `reviewed`：表外 ISO 公制规格；必须由用户显式提供 `--tap-drill`，不得猜测底孔。
- `pilot`：对现有零件定位并改孔、Hole Wizard/Advanced Hole、外螺纹、英制/UN/UNF/NPT/BSP、多头螺纹、显式牙型与钻尖/退刀槽。执行前读取 [扩展路线图](references/threaded-hole-roadmap.md)。

## 稳定工作流

1. 从仓库根目录运行 `python scripts/sw_preflight.py`。
2. 确认螺纹规格、内/外螺纹、公差等级、旋向、盲孔/贯穿、螺纹深度、底孔深度、孔位和是否要求真实牙型。
3. 在 COM 前校验所有值为有限数，底孔小于公称直径，螺纹深度不超过底孔/零件厚度，孔位保留螺纹大径和倒角边界。
4. 先创建真实底孔几何：盲孔用 `swEndCondBlind=0`，贯穿孔必须用 `swEndCondThroughAll=1`，不得用“板厚 + 1 mm”盲孔伪装。
5. 按圆心、半径和入口面枚举圆边，不依赖 `Edge1` 或屏幕坐标。
6. 尝试真实 Thread：`Type="Metric Tap"`，平面圆边使用选择标记 `1`，不要把同一圆边写入 `StartEntity`，不要调用不存在的 `LoadReferences`，不要用公称直径覆盖底孔圆柱直径。
7. Thread 失败时尝试 `InsertCosmeticThread3`；贯穿装饰螺纹用 `swEndConditionThrough=2`。COM 返回非空不等于持久化成功，必须重建后遍历特征树。
8. 只有真实/装饰螺纹均未留在特征树时，`--visible-thread fallback` 才创建 3D 草图螺旋线。螺旋线允许小数圈以保持真实螺距；单独导出 `*_thread_evidence.bmp` 后将草图隐藏，避免污染标准预览。
9. 创建孔口倒角，写入螺纹规格、底孔、深度、公差、旋向、终止条件和最终表达状态。
10. 隐藏参考平面，保存 SLDPRT，导出 STEP，运行 `sw_review.run_review()`，目视检查等轴测/三视图。

## 模板用法

默认 M6×1 右旋 6H 盲孔：

```powershell
python subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py `
  --thread M6 `
  --output-dir C:\CADAutomationWorkbench\solidworks_threaded_hole_output
```

M8×1 表外细牙、左旋、贯穿孔：

```powershell
python subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py `
  --thread M8x1 `
  --tap-drill 7.0 `
  --through `
  --handedness left `
  --thread-class 6H `
  --output-dir C:\CADAutomationWorkbench\m8x1_lh_output
```

`--visible-thread` 支持 `fallback`（默认）、`always` 和 `never`。正常交付保持 `fallback`；调试螺旋线时才使用 `always`。

## 交付与验证

必须生成：

- `*.SLDPRT`
- `*.step`
- `*_parameters.json`
- `*_review_report.json`
- `*_isometric.bmp` 及三视图
- 仅在创建可见螺旋线时生成 `*_thread_evidence.bmp`

`*_parameters.json` 中必须同时检查 `thread_attempts`、`thread_evidence` 和 `thread_status`。只有下列条件同时满足才可交付：

- `has_tap_drill_cut=true` 且 `has_mouth_chamfer=true`。
- `representation` 为 `real-thread`、`cosmetic-thread` 或可解释的 `visible-helix`；`metadata-only` 必须阻断模板交付。
- review 的 `expected_outputs_exist` 和 `previews_not_blank` 为 `true`。
- 标准预览不显示参考平面，不出现穿透实体的 3D 草图虚线，孔位和倒角正确。

详细实测接口、故障原因和官方文档链接见 [螺纹孔实测经验](references/threaded-hole-lessons.md)；未实现能力和验收门槛见 [扩展路线图](references/threaded-hole-roadmap.md)。
