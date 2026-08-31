# SolidWorks Fillet Chamfer CNC

`solidworks-fillet-chamfer-cnc` 是 `solidworks-automation` 仓库里的 CNC 圆角/倒角专项子技能，用来生成带参数预检、语义选边、尺寸降级证据、特征树回读和 STEP 审查的机加工零件。

## 适用场景

- CNC 铝合金安装座、连接块、支架、底板、沉孔安装板。
- 外轮廓大圆角、顶/底边倒角、孔口倒角。
- 三中间控制点可变半径、face fillet、full-round、三边角 setback、平面—圆柱面 G2 组合和 C2/C4 宽度-宽度倒角的环境探测与独立真机回归。
- 固定提交、SHA-256 和 CC BY 3.0 署名的 FreeCAD-library 复杂角支架往返回归，并在唯一几何签名边上施加 C0.2/C0.4 宽度-宽度倒角。
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

高级能力先探测接口，再选择性运行真机验证：

```powershell
py subskills\solidworks-fillet-chamfer-cnc\scripts\verify_advanced_fillets.py `
  --verify-solidworks `
  --modes variable face surface_combo full_round setback width_width_chamfer `
  --output-dir C:\CADAutomationWorkbench\advanced_fillet_verified
```

报告用 `interface_ready` 表示“接口存在”，用 `verified` 表示“真实建模、重建、保存、STEP、重开和预览审查全部通过”，两者不能混用。SolidWorks 2026 SP1.1 的上述六项样例已经完成真机闭环；保持线圆角仍因 `HoldLines` 数组封送读回为 0 而保持阻断，其它版本和其它拓扑也必须重新验证。

复杂开源案例：

```powershell
py subskills\solidworks-fillet-chamfer-cnc\scripts\verify_open_source_complex_case.py `
  --version 2026 `
  --output-dir C:\CADAutomationWorkbench\opensource_corner_bracket
```

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
│   ├── cnc_mount_precision_params.json
│   └── open_source_corner_bracket_case.json
└── scripts/
    ├── cnc_strategy.py
    ├── advanced_fillet_strategy.py
    ├── create_cnc_mount_template.py
    ├── verify_advanced_fillets.py
    └── verify_open_source_complex_case.py
```

## 关联能力

- 父技能：`solidworks-automation`
- 上游规划：`solidworks-vibecad`
- 若模型包含真实螺纹孔，配合 `solidworks-threaded-holes` 使用。
