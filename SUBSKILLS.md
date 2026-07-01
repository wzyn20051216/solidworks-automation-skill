# SolidWorks Automation 子技能矩阵

本仓库采用“大仓库 + 多子技能”的组织方式。根技能 `solidworks-automation` 提供 SolidWorks 连接、文档管理、建模 API、导出、自审查和 MCP Server；专项能力放在 `subskills/` 下，每个子技能自包含 `SKILL.md`、`README.md`、`manifest.yaml`、脚本、参考文档和示例。

这种结构参考多技能仓库的管理方式：根 README 负责总入口、安装方式、能力地图和调用路由；每个子技能负责某一类稳定工作流。

## 技能索引

| 子技能 | 状态 | 用途 | 入口 |
|---|---|---|---|
| `solidworks-vibecad` | experimental | 自然语言需求 -> 参数化设计计划、制造规则检查、执行摘要、审查门禁 | `subskills/solidworks-vibecad/SKILL.md` |
| `solidworks-fillet-chamfer-cnc` | stable | CNC 安装座、连接块、支架、多圆角/倒角、孔槽和减重口袋 | `subskills/solidworks-fillet-chamfer-cnc/SKILL.md` |
| `solidworks-threaded-holes` | stable | M3-M12 螺纹孔、攻丝底孔、孔口倒角、螺纹属性和 STEP 输出 | `subskills/solidworks-threaded-holes/SKILL.md` |

## 推荐路由

```text
自然语言需求
  -> solidworks-vibecad
  -> 结构化 design_plan.json
  -> 按零件类型路由到专项子技能
  -> 父技能 scripts/sw_*.py 执行 SolidWorks COM
  -> sw_review.run_review() 审查
```

## 什么时候用哪个

### solidworks-vibecad

用户说：

- “把这个需求参数化”
- “做一个 text-to-CAD 工作流”
- “把行业知识库和提示词模板固化”
- “先别直接建模，先出设计计划”

使用：

```text
subskills/solidworks-vibecad/SKILL.md
```

### solidworks-fillet-chamfer-cnc

用户说：

- “CNC 安装座”
- “连接块/支架”
- “很多圆角和倒角”
- “减重口袋/长圆槽/沉孔板”

使用：

```text
subskills/solidworks-fillet-chamfer-cnc/SKILL.md
```

### solidworks-threaded-holes

用户说：

- “M6 螺纹孔”
- “攻牙孔”
- “攻丝底孔”
- “Hole Wizard / ThreadFeatureData / CosmeticThread”

使用：

```text
subskills/solidworks-threaded-holes/SKILL.md
```

## 子技能目录规范

新增子技能时保持：

```text
subskills/<skill-name>/
├── SKILL.md             # AI 调用入口和工作流
├── README.md            # 人类阅读入口
├── manifest.yaml        # 索引元数据
├── scripts/             # 可复用脚本
├── references/          # 实测经验、避坑和 API 说明
├── examples/            # 示例输入/输出
└── agents/              # 可选，不同客户端配置
```

## 质量门禁

每个子技能必须说明：

- 适用场景和不适用场景。
- 推荐调用父技能的哪些 `scripts/sw_*.py`。
- SolidWorks API 的稳定策略和降级策略。
- 输出文件和审查要求。
- 新踩坑应沉淀到 `references/`。
