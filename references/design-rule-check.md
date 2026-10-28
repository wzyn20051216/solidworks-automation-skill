# 设计规则检查（DRC / 设计审计）

`scripts/design_rule_check.py` 是面向**设计意图层**的规则检查器，与 `dfm_review.py`（制造性）分工：

- **DFM**：能不能按某工艺造出来（壁厚、割缝、成形空间、供应商能力…）。
- **DRC**：设计本身是否合理、完整、自洽（几何健全性、孔位规则、标准件合理性、装配约束、
  工程图完整性），按严重度聚合成一份可审计报告。

两者都消费同一个 NeutralCadDocument，可组合使用；DRC 不重复实现 DFM/几何/图纸审查，而是把它们
作为证据源。

## 通过 MCP 调用与补充

DRC 面向 harness 通过 MCP 使用：

- `cadstudio_list_drc_rules`：列出内置规则、默认阈值和自定义规则 schema。**先调它**，让代理知道
  哪些能配置。
- `cadstudio_check_drc`：在中性文档上运行检查，可传入声明式 Profile（内联对象或文件路径）。

CLI 等价：

```bash
python scripts/cad_studio.py list-drc-rules
python scripts/cad_studio.py check-drc --input part.cadstudio.json --output out/drc.json --profile strict.json
```

## 自然语言配置与补充（声明式 Profile）

规则集通过 **Profile**（`scripts/design_rule_profiles.py`，schema `cadstudio.drc-profile`）配置。Profile
是纯声明式数据，**不包含也不执行任何代码或路径**，因此代理可以安全地把用户的自然语言翻译成 Profile：

用户说：“螺纹孔到边缘至少 2 倍孔径、壁厚不低于 1.5mm、弹簧指数控制在 5 到 10、孔径小于 3mm 要报警”

代理生成：

```json
{
  "schema": "cadstudio.drc-profile",
  "thresholds": {
    "holeEdgeDistanceRatio": 2.0,
    "minWallThicknessMm": 1.5,
    "springIndexMin": 5.0,
    "springIndexMax": 10.0
  },
  "disabledRules": [],
  "customRules": [
    {"id": "CUST-SMALL-HOLE", "appliesTo": "hole", "field": "diameter", "operator": "lt", "value": 3.0, "severity": "warning", "message": "孔径小于3mm，注意钻头刚性"}
  ]
}
```

- `thresholds`：覆盖内置规则阈值（白名单字段，见 `THRESHOLD_FIELDS`）。
- `disabledRules`：停用指定规则 id。
- `customRules`：**补充**数据驱动的新规则——选定 `appliesTo`（hole/feature/standard_part/document）、
  `field`、`operator`（lt/lte/gt/gte/eq/ne）、`value` 与 `severity`，命中即报。

多个 Profile 合并时，minimum 类阈值取更严值，disabledRules 取并集，customRules 按 id 去重。

## 内置标准规则

| 规则 | 类别 | 说明 | 阈值 |
|---|---|---|---|
| DRC-GEO-001 | geometry | 最小壁厚 | minWallThicknessMm |
| DRC-HOLE-001 | holes | 孔到边缘距离 | holeEdgeDistanceRatio / holeEdgeDistanceMinMm |
| DRC-HOLE-002 | holes | 孔间距 | holeSpacingRatio |
| DRC-HOLE-003 | holes | 螺纹啮合深度 | threadEngagementRatio |
| DRC-HOLE-004 | holes | 孔尺寸有效性 | — |
| DRC-STD-001 | standard_parts | 齿轮尖齿 | — |
| DRC-STD-002 | standard_parts | 齿轮根切齿数：按压力角/齿顶高系数/变位现算 `z_min=2(ha*-x)/sin²α`（20° 为 17.097→18），`gearMinTeeth` 仅作可选覆盖；与上游真机验证的 `sw_gear` 判定交叉校验一致 | （现算）/ gearMinTeeth 覆盖 |
| DRC-STD-003 | standard_parts | 弹簧指数范围 | springIndexMin/Max/HardMin/HardMax |
| DRC-STD-004 | standard_parts | 弹簧实体/自由长度 | — |
| DRC-STD-005 | standard_parts | 链轮最小齿数 | sprocketMinTeeth |
| DRC-ASM-001 | assembly | 装配干涉 | — |
| DRC-ASM-002 | assembly | 装配欠约束 | — |
| DRC-DRW-001 | drawing | 缺必需尺寸 | — |
| DRC-DRW-002 | drawing | 尺寸缺公差 | — |

## 中性文档需要的截面

- `features[]` 中 `type=hole` 的 `parameters`：diameter/radius、depth、edgeDistance、thread、
  threadNominal、threadEngagement、x、y。
- `metadata.design.minWallThicknessMm`（或退化到 `metadata.manufacturing.wallThickness`）。
- `standardParts[]`（或 `metadata.standardParts`）：`{type, teeth, is_pointed, spring_index,
  solid_length_mm, free_length_mm, ...}`，可直接由 `standard_parts_geometry.py` 的派生量填充。
- `metadata.assembly`：componentCount、mateCount、interferences[] 或 interferenceCount。
- `metadata.drawing`：requiredDimensionsMissing[]、dimensionsWithoutTolerance。

缺失的截面按 `info` 跳过，**不代表合格**。报告始终 `reviewRequired=true`。

## 深化一：审计工作流（可追溯门禁）

`scripts/design_audit.py` 把 DRC 从一次性 linter 升级为可复核、可签署、可回归的过程，`build_drc_report`
默认集成，报告新增 `audit` 块与 `riskScore`，每条 finding 带 `fingerprint` 与标准条款出处：

- **指纹**：每条 finding 一个稳定 id（规则+类别+目标），跨多次运行追踪同一问题。
- **基线 diff**：传 `baseline`（上一版报告），报告 `audit.diff` 给出 new / fixed / persisting，评审只看增量。
- **让步单 waiver**：传 `waivers`（每条含 `fingerprint` 或 `ruleId`[+`target`]、`reason`、`owner`、可选
  `expiresOn`）。命中且未过期的 finding 打 `waived` 标记、退出门禁但留痕；过期/未用的让步单单列。
  `status` 是**门禁状态**（忽略 waived），`rawStatus` 是原始状态。
- **风险评分**：`riskScore` 按严重度加权（critical 10 / major 5 / warning 2 / minor 1）汇总未让步的
  finding，给出分数与等级（none/low/medium/high），可用 `risk_weights` 覆盖。

CLI：`check-drc --baseline prev.json --waivers waivers.json --as-of 2026-09-08`。

## 深化二：实测（B-Rep）与关系型规则

- **DRC-HOLE-005 孔间腹板厚度（实测）**：腹板=中心距−半径a−半径b，由真实孔位/孔径算出面板最薄材料桥。
- **DRC-HOLE-006 螺纹啮合 vs 实际板厚**：贯穿攻丝孔在薄板上啮合不足（用 `metadata.plate.thicknessMm`）。
- **DRC-REL-001 GD&T 基准存在性**：`metadata.gdt` 引用的基准必须在 `metadata.datums` 声明。
- **DRC-REL-002 孔表/孔标注覆盖度**：每种孔规格都应被 `metadata.drawing.holeCallouts` 覆盖。
- **DRC-REL-003 BOM 与特征数一致性**：`metadata.bom[].featureType/quantity` 与实际特征数一致。

这些规则天然衔接“真机 3D→分析”打通链路：孔位/孔径来自 `sw_review.collect_geometry_measurements`。

## 深化四：3D 配合务实审计（沉头/紧固）

`scripts/fastener_audit.py` 面向“沉头装反/头部装不平/配合件没让位”这类真实装配会翻车的问题。
单件沉头判据为纯函数离线单测，跨零件避让依赖装配元数据为 pilot。规则族 DRC-CSK-* / DRC-FIT-*：

- **DRC-CSK-001 沉头几何有效性**：沉孔直径 > 主孔径、柱形沉孔深度 > 0。
- **DRC-CSK-002 头部直径容纳**：沉孔直径 ≥ 头径 + 余量（内置 GB/T 70.1 内六角圆柱头、GB/T 70.3 沉头尺寸表）。
- **DRC-CSK-003 深度容纳头高**：柱形沉孔深度 ≥ 头高，否则螺栓头不齐平。
- **DRC-CSK-004 沉头朝向（务实）**：沉头开口不应朝向配合(贴合)面——朝配合面则螺钉头顶在结合面上装不平（critical）。
- **DRC-CSK-005 朝向一致性**：同一紧固组的沉头应朝同一侧。
- **DRC-FIT-001 跨零件避让（pilot）**：柱头/沉头凸出侧的配合件应有避让特征或足够间隙，否则顶死/干涉。

中性文档约定（hole.parameters）：
```json
{"diameter": 6.6, "thread": "M6",
 "counterbore": {"diameter": 11.0, "depth": 6.5, "side": "front"},
 "matingSide": "back", "headType": "socket_cap", "fastenerGroup": "top-cover"}
```
锪埋头用 `"countersink": {"diameter": 12, "angle": 90, "side": "front"}`。跨零件避让走
`metadata.fastenerStacks: [{"id","holeId","protrudes":true,"matingHasRelief":false,"gapMm":0}]`。
真机可用 `counterbores_from_cylinders`（pilot）把同轴两级圆柱配成沉头特征，朝向仍需结合面法向复核。

## 深化三：行业规则包（开箱即用）

`profiles/drc/*.json` 预置四个行业规则包，用 `rule_packs` 叠加（可与内联 profile 合并，profile 覆盖包）：

- `machined_bracket` 机加工支架、`injection_shell` 注塑外壳、`sheet_metal_panel` 钣金面板、`drilling_panel` 钻孔面板。

发现可配置项：`list-drc-rule-packs` / MCP `cadstudio_list_drc_rule_packs`；用法
`check-drc --rule-pack drilling_panel`。规则包本身也是声明式数据，可复制改成企业自有包。

## 回归门禁（设计变更把关）

`design_audit.assert_no_regression(baseline, candidate)`：候选版本相对基线**风险分变高**，或**新增 critical**（即使总分因别处改善而下降），即拒绝；已让步(waived)的不计。
用法：`check-drc --baseline prev.json --fail-on-regression [--regression-tolerance N]`，或 MCP `cadstudio_check_drc` 的 `regression_gate=true`；结果在 `report.regressionGate`，未提供 baseline 时**明确失败**而非静默通过。

## 电机扭矩核验（DRC-DRV-*）

见 [`drive-sizing.md`](drive-sizing.md)。输入为 `metadata.drives[]`，阈值 `driveTorqueSafetyFactor / driveRmsUtilizationMax / driveInertiaRatioWarn / driveInertiaRatioMax` 可经 Profile 覆盖（多 Profile 合并取更严）。

## 边界

- 从活动 SolidWorks 模型抽取快照为 pilot，需真机验证。
- DRC 不判定安全/认证，只做规则级审计；fail/warning 都要工程复核。
- 新规则优先用声明式 customRules 表达；确需复杂逻辑时再在 `BUILTIN_RULES` 增补纯函数并补单测。
