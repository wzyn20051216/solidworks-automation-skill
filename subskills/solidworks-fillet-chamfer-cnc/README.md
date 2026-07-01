# SolidWorks Fillet Chamfer CNC

`solidworks-fillet-chamfer-cnc` 是 `solidworks-automation` 仓库里的 CNC 圆角/倒角专项子技能，用来稳定生成多圆角、多倒角、孔槽、减重口袋和 STEP 输出的机加工零件。

## 适用场景

- CNC 铝合金安装座、连接块、支架、底板、沉孔安装板。
- 外轮廓大圆角、顶/底边倒角、孔口倒角。
- 减重口袋、长圆槽、沉孔、定位孔。
- 需要稳定选边、STEP 导出和多视角预览审查。

## 核心原则

多圆角/倒角零件的难点不是 API 参数，而是稳定拓扑、稳定选边和特征顺序：

1. 先做简单基础体。
2. 大圆角、外轮廓倒角尽量放在孔槽切除之前。
3. 孔、槽、口袋放在主体边处理之后。
4. 孔口小倒角放最后。
5. 选边优先用 `edge.Select2()`，不要依赖 `Edge1` 或坐标点击。
6. 必须运行 `sw_review.run_review()`。

## 快速命令

在仓库根目录执行：

```powershell
py subskills\solidworks-fillet-chamfer-cnc\scripts\create_cnc_mount_template.py `
  --output-dir E:\desktop\CAD\solidworks_fillet_chamfer_output
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
└── scripts/
    └── create_cnc_mount_template.py
```

## 关联能力

- 父技能：`solidworks-automation`
- 上游规划：`solidworks-vibecad`
- 若模型包含真实螺纹孔，配合 `solidworks-threaded-holes` 使用。
