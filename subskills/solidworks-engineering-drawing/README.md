# SolidWorks Engineering Drawing

工程图生成与制造交付审视子技能。它可以被根 `solidworks-automation`、VibeCAD、孔槽/CNC
子技能或工程编排器按需连接，不要求其他建模子技能反向依赖它。

## 输入

使用 `schemas/drawing_spec.schema.json` 描述：

- 源 `.sldprt` / `.sldasm` / 钣金模型
- GB/T 或 ISO 标准、图幅和投影法
- 视图、比例、剖视和局部放大
- 必需尺寸、孔槽规格/数量/定位
- 标题栏、技术要求、BOM 和交付输出

## 输出

- `.slddrw`
- PDF
- BMP/PNG 预览
- `drawing_evidence.json`
- `drawing_review_report.json`
- Markdown 审查摘要

## 兼容入口

历史调用仍可使用根路径：

```python
from scripts.sw_drawing import plan_standard_view_layout
```

新代码应优先使用本子技能脚本，并通过根技能提供的 COM/session API 执行。

## 状态

当前为 `pilot`。机器检查通过不等于 GB/T 图纸最终交付通过，必须人工检查图框、标题栏、
尺寸链、孔表、BOM、线型和文字重叠。

