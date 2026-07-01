# SolidWorks Threaded Holes

`solidworks-threaded-holes` 是 `solidworks-automation` 仓库里的螺纹孔专项子技能，用来稳定生成可审查的攻丝底孔、螺纹孔、孔口倒角、螺纹参数属性和 STEP 输出。

## 适用场景

- M3/M4/M5/M6/M8/M10/M12 内螺纹孔。
- 盲孔、通孔、攻牙孔、螺纹安装孔。
- 需要 Hole Wizard、ThreadFeatureData、CosmeticThread 或可见 3D 螺旋线表达。
- 需要输出 `SLDPRT + STEP + parameters_json + review_report_json + preview`。

## 核心原则

SolidWorks COM 创建真实 Thread 特征在不同版本和语言环境下不稳定，所以默认按稳定层级交付：

1. 攻丝底孔真实几何必须正确。
2. 孔口倒角必须正确。
3. 尝试真实 Thread 特征。
4. 失败时尝试 CosmeticThread。
5. 仍不稳定时保留可见 3D 螺旋线和自定义属性作为语义兜底。
6. 必须运行 `sw_review.run_review()`。

## 快速命令

在仓库根目录执行：

```powershell
py subskills\solidworks-threaded-holes\scripts\create_threaded_hole_template.py `
  --thread M6 `
  --output-dir E:\desktop\CAD\solidworks_threaded_hole_output
```

## 目录

```text
solidworks-threaded-holes/
├── SKILL.md
├── README.md
├── manifest.yaml
├── agents/
├── references/
│   └── threaded-hole-lessons.md
└── scripts/
    └── create_threaded_hole_template.py
```

## 关联能力

- 父技能：`solidworks-automation`
- 上游规划：`solidworks-vibecad`
- 若螺纹孔位于复杂 CNC 安装座中，配合 `solidworks-fillet-chamfer-cnc` 使用。
