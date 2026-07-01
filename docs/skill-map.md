# Skill Map

This repository is managed as one SolidWorks automation skill family. The root skill owns the shared SolidWorks COM layer, while subskills own domain workflows and references.

## Root Skill

| Name | Role |
|---|---|
| `solidworks-automation` | SolidWorks session management, document IO, modeling helpers, export, review, MCP server, API lookup rules |

## Subskills

| Name | Status | Trigger Words | Main Output |
|---|---|---|---|
| `solidworks-vibecad` | experimental | text-to-CAD, VibeCAD, 参数化设计计划, 行业知识库, 提示词模板 | `design_plan.json`, execution outline |
| `solidworks-fillet-chamfer-cnc` | stable | CNC 安装座, 连接块, 支架, 圆角, 倒角, 减重口袋 | `SLDPRT`, `STEP`, parameters JSON, review report |
| `solidworks-threaded-holes` | stable | 螺纹孔, 攻牙孔, 攻丝底孔, M6x1, CosmeticThread | `SLDPRT`, `STEP`, threaded-hole parameters, review report |

## Recommended Agent Routing

```text
1. Need SolidWorks connection/export/review only
   -> solidworks-automation

2. Natural language brief with missing parameters
   -> solidworks-vibecad
   -> then route to execution subskill

3. CNC part with many fillets/chamfers/pockets
   -> solidworks-fillet-chamfer-cnc

4. Threaded or tapped holes
   -> solidworks-threaded-holes
```

## Shared Review Contract

Every CAD-generating subskill should produce or require:

- Native SolidWorks file when applicable.
- STEP/STL/PDF/DXF export according to the user request.
- Parameter JSON for reproducibility.
- `sw_review.run_review()` report.
- At least isometric preview; front/top/right when geometry needs inspection.

## Adding a New Subskill

Create:

```text
subskills/<name>/
├── SKILL.md
├── README.md
├── manifest.yaml
├── scripts/
├── references/
└── examples/
```

Then update:

- `SUBSKILLS.md`
- `README.md`
- `project.yaml`
- this file
