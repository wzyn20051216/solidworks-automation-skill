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
- 工程图交付必须导出 PDF，并将每个 COM 尺寸位置与最终 PDF 的矢量文字框一一关联；PDF 缺失、解析器缺失、关联不完整或文字碰撞都会阻断或要求复核。
- 本子技能不实现强化学习，也不暴露任意 Python/VBA 执行入口。

## 工作流

1. 读取并校验 `schemas/drawing_spec.schema.json`。
2. 运行根技能的 SolidWorks preflight 和能力探测。
3. 选择图框，创建图纸页，回读图幅和投影法。
4. 按执行器能力创建视图、尺寸、孔表和 BOM，并回读真实实体；不得静默忽略 DrawingSpec 字段。
5. 保存 `.slddrw`，导出 PDF 和 BMP/PNG。
6. 运行 `drawing_review.py`，生成机器证据和人工复核门禁。

## 能力边界

- 零件和装配工程图为 pilot：跨版本真机回归仍在持续；但在 PDF 尺寸文字框、视图边界、尺寸链、孔表和 BOM 证据全部通过时，工具会返回 `pass`，不会因 COM 缺少原生文字框而无条件降级。
- 通用 MCP 生成器当前只可靠执行空配置的 `front/top/right` 三视图、显式且可容纳的比例、模型尺寸导入、注释和模板化 BOM。轴测、剖视、局部视图、指定 ID 尺寸、孔标注/孔表、标题栏业务字段和钣金专用选项必须在修改文档前返回 `DRAWING_SPEC_CAPABILITY_UNSUPPORTED`，由专项脚本执行。
- 审查器按尺寸 ID/视图/种类/数值、孔规格/数量/位置、真实 BOM 类型/数据行/配置及标题栏字段回读做结构化核验；模板候选、任意表格或模糊子串不能作为通过证据。
- `professionalAnnotations` 可声明中心标记、中心线、孔标注、基准、GD&T、表面粗糙度和焊接符号。审查器只接受 SolidWorks 专用实体回读；普通 Note 文字不能替代。通用生成器尚未完成这些对象的跨版本写入验证，因此请求写入时保持能力阻断。
- 钣金工程图只有在本机存在可靠展开图证据时继续；缺证据返回 `blocked`，不宣称无人值守完成。
- 完整 GD&T 语义求解不在本版本范围内，只检查要求是否存在并可追溯。

## 依赖根技能

优先复用：`scripts/sw_connect.py`、`scripts/sw_session.py`、`scripts/sw_export.py`、
`scripts/sw_review.py`、`scripts/sw_document_data.py` 和 `scripts/sw_capability_probe.py`。
