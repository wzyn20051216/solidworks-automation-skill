---
name: solidworks-fillet-chamfer-cnc
description: SolidWorks CNC 零件的多圆角/倒角自动化子技能。用于安装座、连接块、支架、沉孔板等模型的参数预检、语义选边、多控制点可变半径、face/full-round/setback、G2 曲面组合、宽度-宽度倒角、角度倒角、孔口倒角、CNC 友好口袋、有界降级和重建证据。
---

# SolidWorks Fillet Chamfer CNC

## 先判定任务模式

圆角/倒角多的模型，主要风险是拓扑变化、错误选边和不可制造参数，不是 API 参数本身。

- 新建 CNC 安装座或验证参数时，先使用模板脚本的 `--dry-run`；计划通过后再连接 SolidWorks。
- 修改既有零件时，先读取 [详细经验](references/cnc-fillet-chamfer-lessons.md) 的“既有模型选边”部分，不套用模板的固定期望边数。
- 用户要求可变半径、面圆角、full-round 或 setback 时，先运行本子技能的高级能力探测；SolidWorks 版本或输入拓扑不同于已验证样例时保持 `pilot`，不要跨版本直接宣称稳定。
- 多控制点、曲面组合和宽度-宽度倒角已经有 SW2026 SP1.1 独立真机证据，但换版本或换拓扑仍须复跑；保持线圆角的 Python COM 数组封送仍未通过，必须保持 `pilot/blocked`，不能退化成普通面圆角后声称成功。

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

## 高级圆角入口

先只读探测本机类型库，不启动 SolidWorks：

```powershell
python subskills\solidworks-fillet-chamfer-cnc\scripts\verify_advanced_fillets.py `
  --output-dir C:\CADAutomationWorkbench\advanced_fillet_probe
```

执行当前六项已通过的独立真机回归：

```powershell
python subskills\solidworks-fillet-chamfer-cnc\scripts\verify_advanced_fillets.py `
  --verify-solidworks `
  --modes variable face surface_combo full_round setback width_width_chamfer `
  --output-dir C:\CADAutomationWorkbench\advanced_fillet_verified
```

只有报告中的能力状态为 `verified`，且对应 SLDPRT、STEP、重开证据和审查报告都存在，才能声明该环境支持。当前在 SolidWorks 2026 SP1.1 验证的最小样例为：

- 单边端点可变半径 R2→R5，特征类型回读为 `VarFillet`。
- 同一条边 25%/50%/75% 三个中间控制点分别回读 R3/R6/R4；`GetControlPointRadiusAtIndex` 的位置值按百分数 `25/50/75` 解释。
- 两组相邻面的 R4 face fillet，`ISimpleFilletFeatureData2.Type=2`。
- 平面—圆柱面组合的 R3 G2 面圆角，重开后 `CurvatureContinuous=true`。
- 三组面各 1 个面的 full-round，`ISimpleFilletFeatureData2.Type=3`。
- 三边角 R3、逐边 setback 1 mm，回读 setback 顶点数为 1。
- C2/C4 距离-距离倒角，`IChamferFeatureData2.Type=2`，两侧距离按 side `0/1` 回读为 `2/4 mm`。

setback 的距离数组必须显式封装为 `VT_ARRAY | VT_R8`。普通 Python `tuple` 可能不抛 COM 异常，却让 `FeatureFillet` 返回 `None`，不得把这种结果降级为普通圆角。

保持线模式使用投影分割线、两组面 mark `2/4` 和保持线 mark `8`，并要求 `GetHoldLineCount=1`。SW2026 SP1.1 中 pywin32 的普通数组被静默丢弃，`SAFEARRAY<IDispatch>` 会产生 COM 服务器异常；因此 `--modes hold_line` 当前用于负向能力探测，返回非零是预期的阻断证据。

## 开源复杂案例回归

复杂模型回归固定使用 FreeCAD-library 的 `2020_corner_bracket-Corner.step`，锁定提交、SHA-256 和 CC BY 3.0 署名；不使用会随主分支变化的裸链接：

```powershell
python subskills\solidworks-fillet-chamfer-cnc\scripts\verify_open_source_complex_case.py `
  --version 2026 `
  --output-dir C:\CADAutomationWorkbench\opensource_corner_bracket
```

脚本按清单中的唯一端点/长度签名选中 24.041631 mm 斜边，真实施加 C0.2/C0.4 宽度-宽度倒角。只有下载哈希、源拓扑精确为 `1 solid / 40 faces / 98 edges`、倒角 FeatureData 读回、处理后 `41 faces / 101 edges / 66 vertices` 重开保持、SLDPRT/STEP 和四视角审查全部通过，案例才标记 `verified`。网络不可用时可复用已缓存文件，但仍必须重新计算 SHA-256。

## CNC 几何默认值

- 减重口袋默认使用 `rounded_slot`，避免把不可加工的零半径内角当作成品；明确需要后工序清角时才使用 `rectangle` 并保留 DFM 警告。
- 定位孔、中心槽和减重口袋必须用同一参数源做二维包络检查。模板 v2 默认把定位孔布置在 Y 方向，避免旧布局与中心槽相交。
- 恒定半径圆角和角度倒角是通用稳定路径；多控制点可变半径、face/full-round/setback、平面—圆柱面 G2 组合和宽度-宽度倒角已有 SolidWorks 2026 SP1.1 最小真机回归，但应用到其它拓扑或版本时仍须重新运行能力脚本。复杂过渡必须记录 API、SolidWorks 版本、输入拓扑、重建结果和预览证据后才能升级能力等级。

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
