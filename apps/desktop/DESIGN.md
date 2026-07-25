# Design System: CAD 自动化交付工作台

## 1. Visual Theme & Atmosphere

气质定位为“安静的工程控制室”: 密度 7/10，变化 4/10，动效 2/10。

界面应该让机械工程师感觉可靠、清楚、能反复使用。视觉重点不是炫技，而是把项目状态、参数完整性、P0 复核和交付输出摆在清晰的位置。整体像精密仪器面板: 稳、克制、有秩序。

## 2. Color Palette & Roles

- **Drafting Canvas** (#EDEEEA) - 主背景，接近工程图纸纸面但不偏黄。
- **Instrument Surface** (#FAFAF7) - 表单、复核区和主要内容面板。
- **Charcoal Console** (#141B1F) - 左侧导航和底部状态，不能使用纯黑。
- **Ink Primary** (#182024) - 标题、标签和主要内容。
- **Steel Text** (#56636B) - 辅助说明、路径、状态描述。
- **Hairline Border** (#D8DDD7) - 1px 结构线、输入框边界。
- **Copper Accent** (#B87333) - 唯一强调色，用于主按钮、选中态、关键门禁状态。

禁止紫蓝霓虹、纯黑、发光阴影和高饱和渐变。

## 3. Typography Rules

- **Display:** Microsoft YaHei UI Semibold - 中文工程软件优先，字号克制，靠字重建立层级。
- **Body:** Microsoft YaHei UI - 行高放松，表单文字不小于 13px。
- **Mono:** Cascadia Mono / Consolas - 日志、文件路径、数值清单。
- **Banned:** 不使用 serif 字体，不使用大面积负字距，不用营销式超大标题。

## 4. Component Stylings

- **Buttons:** 扁平、有边界，主按钮使用 Copper Accent。按下时用更深铜色，不做外发光。
- **Panels:** 只用于实际功能区域。半径 10px 以下，边框清楚，避免卡片套卡片。
- **Inputs:** 标签靠左对齐，输入区域高度稳定，聚焦态只改变边框色。
- **Tables:** 表头淡灰底，数值列清晰，保留紧凑工程密度。
- **Status:** P0/P1 结果用文字和颜色表达，不用装饰图标堆叠。
- **Empty States:** 明确告诉用户下一步动作，例如“保存参数后生成项目目录”。

## 5. Layout Principles

- 左侧为导航和产品身份，中间为工作参数，右侧为复核和输出。
- 顶部保留命令条，主要动作永远在右上。
- 摘要条显示当前流程的四个核心事实: 本地运行、GB/T 风格、P0 门禁、Mock 状态。
- 不使用三等分营销卡片，不做视觉噪声装饰。
- 所有文本必须完整显示，按钮宽度不能压缩文字。

## 6. Motion & Interaction

桌面端当前不做复杂动画。交互反馈依赖 hover、pressed、focus 和状态文本变化。后续如果接入长时间 CAD 执行，使用阶段进度条和日志流，不使用旋转加载圈。

## 7. Anti-Patterns

- 不用纯黑。
- 不用紫色/蓝色霓虹渐变。
- 不用装饰性发光。
- 不用营销话术。
- 不用 emoji。
- 不让文字被按钮挤压。
- 不把表单做成大面积空白 demo。
- 不把复核结果藏在 JSON 里，界面必须直接显示关键问题。
