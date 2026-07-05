# AutoCAD Automation 子技能

本子技能是 `solidworks-automation-skill` 技能库中的 AutoCAD / DWG / DXF 专项能力。父技能负责 SolidWorks 三维建模、装配、工程图和导出；本子技能负责 Windows 桌面 AutoCAD 的 Python COM 自动化，包括二维绘图、批量改图、图层/文字/标注处理、DWG/DXF/PDF 导出、线稿矢量化和图纸自检。

## 适用场景

- 用户要求“画 DWG / DXF / AutoCAD 图纸”。
- 需要把图片线稿转为 CAD 线条，并保存为 DWG/DXF。
- 需要批量检查图层、实体数量、包围盒、文字、块、外部参照或输出文件。
- 需要在 AutoCAD 中可见地逐步绘制，并导出原生预览用于审查。
- SolidWorks 工程流中需要补充二维 AutoCAD 图纸、加工轮廓、激光切割 DXF 或图纸清理。

## 与父技能的关系

- `solidworks-automation`：SolidWorks COM 连接、零件/装配体/工程图建模、STEP/STL/PDF 导出和三维审查。
- `autocad-automation`：AutoCAD COM 连接、DWG/DXF 二维图纸绘制、图层/标注/块处理、AutoCAD 原生预览和图纸自检。

当任务要求 SolidWorks 原生零件、装配体或工程图时，优先使用父技能；当任务明确涉及 AutoCAD、DWG、DXF、二维 CAD 图纸、线稿转 CAD 或批量改 DWG 时，读取本子技能。

## 快速命令

```powershell
python subskills\autocad-automation\scripts\acad_preflight.py --launch
```

```powershell
python subskills\autocad-automation\scripts\acad_draw.py `
  --input C:\temp\plan.json `
  --output C:\temp\result.dwg `
  --new
```

```powershell
python subskills\autocad-automation\scripts\acad_review.py C:\temp\result.dwg `
  --launch `
  --json C:\temp\review.json
```

```powershell
python subskills\autocad-automation\scripts\acad_preview.py `
  --source C:\temp\result.dwg `
  --output C:\temp\preview.png `
  --launch
```

## 线稿转 CAD 的硬规则

普通“照图画 CAD”的最终交付必须只保留原图矢量化线条。不要把手工猜测的外围轮廓、五官椭圆、Logo 三角线、水波线、替代文字或图内审查说明留在最终 DWG/DXF 中。

最终审查时要确认这些辅助层为 0：

```text
PORTRAIT_OUTLINE, BODY_OUTLINE, JERSEY_OUTLINE,
OUTER_GUIDE, CONSTRUCTION, FACE_FEATURES,
LOGO_GEOMETRY, WATER_SPLASH, JERSEY_STRIPE,
TEXT_LOGO, TEXT_BRAND, REVIEW_NOTES
```

这条规则来自一次真实线稿 demo 复盘：AI 为了“增强识别”补出的轮廓线、椭圆、三角形和彩色水波线，在 CAD 用户眼里会变成多余实体。后续普通线稿任务以干净、忠实、无多余实体为第一目标。

## 参考文档

- `SKILL.md`：AI 调用入口和完整工作流。
- `references/api-lookup.md`：AutoCAD API 查证路线。
- `references/engineering-patterns.md`：图层、单位、块、标注和批处理经验。
- `references/troubleshooting.md`：本机 COM、DXF/BMP 导出、线稿污染和复核避坑。
