---
name: solidworks-vibecad
description: SolidWorks VibeCAD 参数化设计规划子技能。用于把自然语言机械设计需求转成结构化设计计划、制造规则检查、SolidWorks API 执行摘要和审查门禁；当任务涉及 text-to-CAD、vibecoding 固化、行业知识库、提示词模板、参数化建模计划、CNC 安装座/连接块/支架批量生成时使用。
---

# SolidWorks VibeCAD

## 核心定位

本子技能把“自然语言想法”转成可执行、可审查的 SolidWorks 参数化设计计划。它不是临时生成 VBA 宏，而是把重复机械设计固化成：

```text
行业知识库 + 参数 schema + 提示词模板 + 稳定 API 封装 + 自动审查
```

LLM 负责理解意图和补齐参数；SolidWorks API 负责确定性执行；知识库负责工程正确性；审查链路负责防止“看起来成功但几何错误”。

## 适用任务

- 用户用自然语言描述零件，希望生成参数化建模计划。
- 需要把高频机械件模板化，如 CNC 安装座、连接块、L 型支架、底板、孔阵列。
- 需要沉淀行业知识库，如攻丝底孔、通孔、沉孔、倒角、圆角、最小壁厚。
- 需要给 SolidWorks 自动化执行器提供 JSON 计划和风险门禁。
- 需要把成功案例变成可复用模板，而不是每次重新写宏。

## 工作流

1. 读取用户需求，确认零件族、工艺、材料、输出格式和约束。
2. 参考 `knowledge/manufacturing_rules.yaml` 补齐保守默认值。
3. 用 `prompts/solidworks_parametric_planner.md` 约束 LLM 输出结构化计划。
4. 用 `schemas/design_plan.schema.json` 校验计划字段。
5. 运行 `scripts/plan_from_brief.py` 生成本地规则计划，或把 LLM 输出保存为同 schema JSON。
6. 运行 `scripts/sw_execution_outline.py` 生成 SolidWorks 执行摘要。
7. 后续执行时交给父技能 `scripts/sw_session.py`、`scripts/sw_part.py`、`scripts/sw_review.py` 和相关专项子技能。

## 快速命令

```powershell
py subskills\solidworks-vibecad\scripts\plan_from_brief.py `
  --brief-file subskills\solidworks-vibecad\examples\motor_mount_brief.txt `
  --out subskills\solidworks-vibecad\examples\motor_mount_plan.json

py subskills\solidworks-vibecad\scripts\sw_execution_outline.py `
  --plan subskills\solidworks-vibecad\examples\motor_mount_plan.json `
  --out subskills\solidworks-vibecad\examples\motor_mount_execution.md
```

## 与父技能的关系

- `solidworks-automation`：连接 SolidWorks、建模、导出、审查的主技能。
- `solidworks-vibecad`：自然语言 -> 参数化设计计划。
- `solidworks-fillet-chamfer-cnc`：复杂 CNC 圆角/倒角执行经验。
- `solidworks-threaded-holes`：螺纹孔、攻丝底孔和螺纹表达执行经验。

当计划中出现圆角/倒角密集的 CNC 件，继续读取：

```text
subskills/solidworks-fillet-chamfer-cnc/SKILL.md
```

当计划中出现 M3/M4/M5/M6/M8 螺纹孔，继续读取：

```text
subskills/solidworks-threaded-holes/SKILL.md
```

## 少走弯路

- 不要让 LLM 直接输出 SolidWorks 长参数 COM 调用。
- 不要把计划 JSON 当作几何成功；必须经过真实 SolidWorks 执行和 `sw_review` 审查。
- 不确定参数可以用保守默认值，但必须写入 `assumptions`。
- 螺丝固定孔要区分通孔、沉孔、攻丝孔；不能把 `M5 螺丝固定孔` 默认误建成 M5 攻丝孔。
- 输出计划必须包含 `review_plan`，否则不能进入自动建模。

## 当前状态

当前阶段已实现需求文本到设计计划和执行摘要的最小闭环。真实 SolidWorks 执行器应作为下一阶段接入父技能稳定 API。
