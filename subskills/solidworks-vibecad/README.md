# SolidWorks VibeCAD

`solidworks-vibecad` 是 `solidworks-automation` 仓库里的参数化设计规划子技能，用来把自然语言机械设计需求转换为结构化设计计划、制造规则检查、SolidWorks API 执行摘要和审查门禁。

## 为什么放在子技能里

这个方向的价值不在于临时生成宏，而在于把重复机械设计沉淀成可复用工程资产：

```text
行业知识库 + 参数 schema + 提示词模板 + 稳定 API 封装 + 自动审查
```

因此它应该作为 SolidWorks 自动化大仓库的一部分，和 CNC 圆角/倒角、螺纹孔、装配、MCP 等能力并列管理。

## 当前能力

- 从自然语言需求生成参数化设计计划 JSON。
- 内置 M3-M12 攻丝底孔、通孔、CNC 圆角/倒角、最小壁厚等规则。
- 给 LLM 提供严格规划提示词，避免直接输出不稳定宏。
- 生成 SolidWorks API 执行摘要，明确每一步对应父技能的哪个稳定封装。
- 生成审查门禁，要求保存、导出、多视角预览和 review report。

## 目录

```text
solidworks-vibecad/
├── SKILL.md
├── README.md
├── manifest.yaml
├── knowledge/
│   └── manufacturing_rules.yaml
├── prompts/
│   └── solidworks_parametric_planner.md
├── schemas/
│   └── design_plan.schema.json
├── scripts/
│   ├── plan_from_brief.py
│   └── sw_execution_outline.py
├── examples/
│   ├── motor_mount_brief.txt
│   ├── motor_mount_plan.json
│   └── motor_mount_execution.md
└── references/
    └── vibecad-roadmap.md
```

## 快速运行

在 `solidworks-automation` 仓库根目录执行：

```powershell
py subskills\solidworks-vibecad\scripts\plan_from_brief.py `
  --brief-file subskills\solidworks-vibecad\examples\motor_mount_brief.txt `
  --out subskills\solidworks-vibecad\examples\motor_mount_plan.json

py subskills\solidworks-vibecad\scripts\sw_execution_outline.py `
  --plan subskills\solidworks-vibecad\examples\motor_mount_plan.json `
  --out subskills\solidworks-vibecad\examples\motor_mount_execution.md
```

## 示例输出

示例需求会识别：

- 底板：`90 x 60 x 8 mm`
- 固定孔：`M5` 螺丝通孔，通孔直径 `5.5 mm`
- 中心孔：`22 mm`
- 外轮廓圆角：`R6`
- 顶边倒角：`C1`
- 审查：`SLDPRT + STEP + parameters_json + review_report_json + isometric_preview`

## 下一步

优先把 `cnc_mount` 执行器接到父技能：

1. 读取 `design_plan.json`。
2. 调用 `sw_preflight.py`。
3. 使用 `SolidWorksSession()` 新建零件。
4. 按计划创建底板、孔、口袋、圆角、倒角。
5. 保存 `SLDPRT` 并导出 `STEP`。
6. 运行 `sw_review.run_review()`。
7. 不通过时按计划里的 `risk_register` 降级重试。
