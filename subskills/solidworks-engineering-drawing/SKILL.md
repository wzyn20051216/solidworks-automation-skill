---
name: solidworks-engineering-drawing
description: "SolidWorks 工程图生成与制造交付审视子技能，支持 GB/T 第一角零件图、装配图、尺寸链、孔表、BOM、PDF/BMP 证据和钣金能力门禁。"
metadata: { "openclaw": { "os": ["win32"], "requires": { "anyBins": ["python", "py"] } } }
---

# SolidWorks 工程图生成与审视

本子技能专注二维工程图。它依赖根技能 `solidworks-automation` 提供 SolidWorks COM
会话、模型、导出和通用几何证据；自身负责 `DrawingSpec v1`、工程图工作流和制造交付审视。

## 何时调用

- 生成零件工程图或装配工程图。
- 需要 GB/T 图框、第一角投影、尺寸链、孔表、BOM 或标题栏。
- 检查工程图视图重叠、尺寸文字、PDF 文字、标题栏侵入或交付证据。
- 钣金任务需要审视展开图证据时。

## 默认规则

- `standard=GB_T` 默认使用 `projection=first_angle`。
- GB/T + 第三角投影会被 `DrawingSpec` 前置检查阻断。
- 所有孔、槽和接口必须有规格、数量和定位信息。
- 估算尺寸包围盒、PDF 文字框和非空 BMP 只能作为风险证据，不能替代人工目视终审。
- 本子技能不实现强化学习，也不暴露任意 Python/VBA 执行入口。

## 工作流

1. 读取并校验 `schemas/drawing_spec.schema.json`。
2. 运行根技能的 SolidWorks preflight 和能力探测。
3. 选择图框，创建图纸页，回读图幅和投影法。
4. 创建视图、剖视/局部视图、尺寸、孔表和 BOM，并回读真实实体。
5. 保存 `.slddrw`，导出 PDF 和 BMP/PNG。
6. 运行 `drawing_review.py`，生成机器证据和人工复核门禁。

## 能力边界

- 零件和装配工程图为 pilot：生成和机器检查可用，但 GB/T 内容、尺寸链和可制造性仍需人工终审。
- 钣金工程图只有在本机存在可靠展开图证据时继续；缺证据返回 `blocked`，不宣称无人值守完成。
- 完整 GD&T 语义求解不在本版本范围内，只检查要求是否存在并可追溯。

## 依赖根技能

优先复用：`scripts/sw_connect.py`、`scripts/sw_session.py`、`scripts/sw_export.py`、
`scripts/sw_review.py`、`scripts/sw_document_data.py` 和 `scripts/sw_capability_probe.py`。

