# SolidWorks Fillet Chamfer CNC

`solidworks-fillet-chamfer-cnc` 是 `solidworks-automation` 仓库里的 CNC 圆角/倒角专项子技能，用来生成带参数预检、语义选边、尺寸降级证据、特征树回读和 STEP 审查的机加工零件。

## 适用场景

- CNC 铝合金安装座、连接块、支架、底板、沉孔安装板。
- 外轮廓大圆角、顶/底边倒角、孔口倒角。
- CNC 友好长圆口袋、中心槽、沉孔、定位孔和特征间净距检查。
- 需要稳定选边、STEP 导出和多视角预览审查。

## 核心原则

多圆角/倒角零件的难点不是 API 参数，而是稳定拓扑、稳定选边和特征顺序：

1. 先做简单基础体。
2. COM 前检查孔槽碰撞、最小边壁、净距和剩余底壁。
3. 大圆角、外轮廓倒角尽量放在孔槽切除之前。
4. 孔、槽、口袋放在主体边处理之后，孔口小倒角放最后。
5. 选边使用几何签名、`edge.Select2()` 和精确数量断言，不依赖 `Edge1` 或屏幕坐标。
6. 特征必须在重建后回读，并运行 `sw_review.run_review()`。

## 快速命令

先在仓库根目录离线预检：

```powershell
py subskills\solidworks-fillet-chamfer-cnc\scripts\create_cnc_mount_template.py `
  --dry-run `
  --set base_corner_radius=6 `
  --output-dir C:\CADAutomationWorkbench\solidworks_fillet_chamfer_output
```

检查生成的 `CNC_Mount_Template_plan.json` 后，删除 `--dry-run` 执行 SolidWorks 建模。也可以使用参数文件：

```powershell
py subskills\solidworks-fillet-chamfer-cnc\scripts\create_cnc_mount_template.py `
  --params-json subskills\solidworks-fillet-chamfer-cnc\examples\cnc_mount_precision_params.json `
  --failure-policy strict `
  --output-dir C:\CADAutomationWorkbench\solidworks_fillet_chamfer_output
```

`strict` 不允许改变请求尺寸；`progressive` 会尝试 100%/75%/50%，但降级结果必须按实际尺寸交付。

## 目录

```text
solidworks-fillet-chamfer-cnc/
├── SKILL.md
├── README.md
├── manifest.yaml
├── agents/
├── references/
│   └── cnc-fillet-chamfer-lessons.md
├── examples/
│   └── cnc_mount_precision_params.json
└── scripts/
    ├── cnc_strategy.py
    └── create_cnc_mount_template.py
```

## 关联能力

- 父技能：`solidworks-automation`
- 上游规划：`solidworks-vibecad`
- 若模型包含真实螺纹孔，配合 `solidworks-threaded-holes` 使用。
