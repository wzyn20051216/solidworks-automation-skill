---
name: solidworks-fillet-chamfer-cnc
description: SolidWorks CNC 零件的多圆角/倒角自动化子技能。用于安装座、连接块、支架、沉孔板等模型的参数预检、语义选边、恒定半径圆角、角度倒角、孔口倒角、CNC 友好口袋、有界降级和重建证据；不把未验证的可变半径、退刀圆角或复杂曲面过渡宣称为稳定能力。
---

# SolidWorks Fillet Chamfer CNC

## 先判定任务模式

圆角/倒角多的模型，主要风险是拓扑变化、错误选边和不可制造参数，不是 API 参数本身。

- 新建 CNC 安装座或验证参数时，先使用模板脚本的 `--dry-run`；计划通过后再连接 SolidWorks。
- 修改既有零件时，先读取 [详细经验](references/cnc-fillet-chamfer-lessons.md) 的“既有模型选边”部分，不套用模板的固定期望边数。
- 用户要求可变半径、面圆角、圆角保持线、退刀槽、倒角宽度-宽度、setback 或复杂曲面过渡时，先运行父技能能力探测并查官方 API；没有真机回归证据时保持 `pilot` 或人工复核。

## 模板入口

先做无 COM 预检：

```powershell
python subskills\solidworks-fillet-chamfer-cnc\scripts\create_cnc_mount_template.py `
  --dry-run `
  --set base_corner_radius=6 `
  --set chamfer_angle_deg=30 `
  --output-dir C:\CADAutomationWorkbench\cnc_mount
```

确认 `*_plan.json` 中 `validation.errors` 为空、语义目标和 `expected_edge_count` 符合设计，再删除 `--dry-run` 执行原生建模。大量参数优先放进 JSON：

```powershell
python subskills\solidworks-fillet-chamfer-cnc\scripts\create_cnc_mount_template.py `
  --params-json subskills\solidworks-fillet-chamfer-cnc\examples\cnc_mount_precision_params.json `
  --failure-policy strict `
  --output-dir C:\CADAutomationWorkbench\cnc_mount
```

`strict` 只接受请求尺寸；`progressive` 按 100%/75%/50% 尝试。发生降级时必须在交付摘要中写明实际尺寸，不能仍声称精确满足原值。

## 不可跳过的门禁

1. 原生建模前运行父技能 `scripts/sw_preflight.py`；`--dry-run` 不需要 SolidWorks。
2. 参数预检必须覆盖有限数值、圆角/倒角上限、孔槽碰撞、最小边壁、特征间净距、沉孔/口袋底壁和输出基名安全。
3. 新建模板按“基础体 → 立角圆角 → 外轮廓倒角 → 孔槽/口袋 → 孔口倒角”执行；既有模型根据依赖关系决定顺序。
4. 选边以几何签名和期望数量为证据。数量不符时停止，不用扩大坐标容差、`Edge1` 或屏幕点击猜边。
5. 每个圆角/倒角必须在重建后从特征树回读；COM 返回非空不等于持久化成功。
6. 生成后保存 SLDPRT、导出 STEP、运行 `sw_review.run_review()`，并人工查看等轴测和俯视预览。

## CNC 几何默认值

- 减重口袋默认使用 `rounded_slot`，避免把不可加工的零半径内角当作成品；明确需要后工序清角时才使用 `rectangle` 并保留 DFM 警告。
- 定位孔、中心槽和减重口袋必须用同一参数源做二维包络检查。模板 v2 默认把定位孔布置在 Y 方向，避免旧布局与中心槽相交。
- 恒定半径圆角和角度倒角是当前稳定路径。复杂过渡必须记录 API、SolidWorks 版本、输入拓扑、重建结果和预览证据后才能升级能力等级。

详细的选边签名、失败语义、既有模型策略和扩展路线见 [CNC 多圆角/倒角经验](references/cnc-fillet-chamfer-lessons.md)。

## 验证要求

每次完成后输出：

- `*.SLDPRT`
- `*.step`
- `*_parameters.json`
- `*_review_report.json`
- `*_isometric.bmp` 或转换后的 PNG

审查时至少检查：

- `evaluation.status` 是否为 `pass` 或可解释的 `warn`
- `expected_outputs_exist` 是否为 `True`
- `previews_not_blank` 是否为 `True`
- `validation.errors` 是否为空
- `treatment_evidence` 是否记录请求值、实际值、每次尝试和所选边签名
- `feature_evidence.missing_names` 是否为空
- 特征树是否包含预期的 `Fillet` / `Chamfer` / `Cut` 特征
