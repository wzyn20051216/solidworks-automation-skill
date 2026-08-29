# SolidWorks Threaded Holes

`solidworks-threaded-holes` 是 `solidworks-automation` 的 ISO 公制内螺纹孔子技能。它不只生成“看起来像孔”的模型，还会校验攻丝底孔、终止条件、螺纹深度、孔位边界，并在重建后回读特征树。

## 当前能力

- M3/M4/M5/M6/M8/M10/M12 粗牙 ISO 公制内螺纹。
- 表外 ISO 公制规格：必须显式提供攻丝底孔，不自动猜测。
- 盲孔与真正 `Through All` 贯穿孔。
- `Metric Tap` 真实 Thread、CosmeticThread、精确螺距的 3D 证据螺旋线三级降级。
- 右旋/左旋、螺纹公差属性、孔口倒角、STEP、多视图与结构化审查证据。

SolidWorks 2026 已实测 M6×1 6H 右旋盲孔和贯穿孔，均在重建后识别到真实 Thread 特征并通过交付审查。

## 快速使用

```powershell
python scripts\sw_preflight.py

python subskills\solidworks-threaded-holes\scripts\create_threaded_hole_template.py `
  --thread M6 `
  --output-dir C:\CADAutomationWorkbench\solidworks_threaded_hole_output
```

贯穿孔和左旋示例：

```powershell
python subskills\solidworks-threaded-holes\scripts\create_threaded_hole_template.py `
  --thread M8x1 `
  --tap-drill 7.0 `
  --through `
  --handedness left `
  --thread-class 6H `
  --output-dir C:\CADAutomationWorkbench\m8x1_lh_output
```

## 交付证据

默认输出 `SLDPRT + STEP + parameters.json + review_report.json + 等轴测/三视图`。如果真实 Thread 和 CosmeticThread 都未留在特征树，还会生成独立的 `*_thread_evidence.bmp`；3D 螺旋线随后被隐藏，不污染标准预览。

## 暂未宣称稳定的能力

Hole Wizard/Advanced Hole、修改现有零件、外螺纹、UNC/UNF/NPT/BSP、多头螺纹、钻尖与攻丝退刀槽、工程图孔标注自动验收都属于后续扩展，见 [threaded-hole-roadmap.md](references/threaded-hole-roadmap.md)。

## 目录

```text
solidworks-threaded-holes/
├── SKILL.md
├── README.md
├── manifest.yaml
├── agents/
├── references/
│   ├── threaded-hole-lessons.md
│   └── threaded-hole-roadmap.md
└── scripts/
    └── create_threaded_hole_template.py
```
