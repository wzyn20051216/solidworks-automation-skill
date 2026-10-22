---
name: solidworks-standard-parts
description: SolidWorks 标准机械零件参数化生成子技能。用于按工程参数生成渐开线直齿圆柱齿轮、圆柱压缩弹簧和滚子链链轮：输入模数/齿数/压力角、线径/中径/圈数、链节距/滚子直径/齿数，输出带自定义属性的 SLDPRT、STEP 与审查证据。用户说“生成一个齿轮/弹簧/链轮”“做一个 M2 20 齿齿轮”“画一根压缩弹簧”“ANSI #40 链轮”时读取本技能。齿廓与力学几何已离线单测，但真实特征落盘、啮合精度和端圈工艺仍为 pilot，须真机与工程复核。
---

# SolidWorks Standard Parts

标准件生成器是很多 SolidWorks 宏命令集的核心价值（如 t84RT/SW-software---Macro-command 中的
齿轮/弹簧/链条宏）。本子技能用 Python 重写这类能力，把“几何是否正确”与“SolidWorks 特征
是否落盘”分离：前者由纯几何模块 `scripts/standard_parts_geometry.py` 保证并离线单测，后者由
COM 生成器执行并做重建后回读与自审查。

## 先判定能力等级

- `reference/verified-geometry`：分度圆、基圆、齿顶/齿根圆、变位、弹簧指数 C、实体长度、
  刚度 k=G·d⁴/(8·D³·Na)、链轮节圆直径 PD=P/sin(π/N) 与齿顶圆 OD 已离线单测。
- `pilot`：真实 SolidWorks 特征落盘（拉伸齿体、扫描线材、链轮齿形切除）、变位根切边界、
  齿轮啮合精度、弹簧端圈并紧/磨平与压并高度、链轮精确啮合齿形。必须真机运行并工程复核。

不适用：斜齿轮/锥齿轮/蜗轮蜗杆、拉伸/扭转弹簧、双节距链与非标齿形——这些先走
`solidworks-vibecad` 规划或人工建模，不要用本子技能的直齿/压簧/滚子链公式硬套。

## 与上游已真机验证的齿轮实现的关系

上游 `scripts/sw_gear.py`（`references/gears.md`）已在 SolidWorks 2026 SP1.1 做过真机回归
（m=2、z=24、α=20°：重开后 B-Rep 回读 52×52×10 mm、内孔 10 mm，单实体，SLDPRT/STEP 落盘，四视图 pass/100），
与本子技能 `create_spur_gear.py` 覆盖同一类零件。选择建议：

- **标准外啮合直齿轮、要落 SolidWorks 实体** → 优先用上游 `sw_gear.create_external_spur_gear`（有真机证据）。
- **需要变位系数、非标齿顶/齿根高系数、或离线校验几何/力学量** → 用本子技能的纯函数
  `standard_parts_geometry.spur_gear_profile`（支持变位 x，不依赖 SolidWorks）。
- 两套实现的直径/齿厚/包络已由 `tests/test_gear_cross_validation.py` 交叉校验一致，并以上游真机 52 mm 外径为锚点；
  根切判定统一为 `z_min=2(ha*-x)/sin²α`（20° → 18）。
- 弹簧、链轮上游没有对应实现，仍以本子技能为准（pilot）。

## 稳定工作流

1. 从仓库根目录运行 `python scripts/sw_preflight.py`。
2. 确认零件类型与关键参数、单位（本子技能一律 mm）、中心孔、齿宽/厚度/自由长度、输出目录。
3. COM 前先用纯几何模块校验派生量是否合理（尖齿、根切、实体长度≥自由长度等会直接报错）。
4. 运行对应生成器，重建后回读特征/实体，导出 STEP，`run_review()` 出等轴测与三视图。
5. 交付前目视复核预览图：齿数是否正确、齿廓是否尖化、弹簧螺旋是否连续、链轮齿是否均布。

## 生成器用法

直齿轮（默认 m2 z20 压力角 20°，中心孔 φ10，齿宽 15）：

```powershell
python subskills\solidworks-standard-parts\scripts\create_spur_gear.py `
  --module 2 --teeth 20 --pressure-angle 20 --face-width 15 --bore 10 `
  --output-dir C:\CADAutomationWorkbench\standard_parts_output
```

圆柱压缩弹簧（线径 3，中径 24，自由长 60，8 圈，闭合磨平，给出弹簧钢 G 计算刚度）：

```powershell
python subskills\solidworks-standard-parts\scripts\create_compression_spring.py `
  --wire-diameter 3 --mean-diameter 24 --free-length 60 --total-coils 8 `
  --end-type closed_ground --shear-modulus 79300 `
  --output-dir C:\CADAutomationWorkbench\standard_parts_output
```

滚子链链轮（ANSI #40，节距 12.7，滚子 7.92，17 齿，厚 6，中心孔 φ20）：

```powershell
python subskills\solidworks-standard-parts\scripts\create_roller_sprocket.py `
  --chain-pitch 12.7 --roller-diameter 7.92 --teeth 17 --thickness 6 --bore 20 `
  --output-dir C:\CADAutomationWorkbench\standard_parts_output
```

## 交付与验证

每个生成器都会产出 `*.SLDPRT`、`*_parameters.json`、`*_review_report.json` 与预览图，
直齿轮/链轮额外产出 `*.step`。压缩弹簧优先尝试圆形轮廓扫描成实体（`representation=swept-solid`
时导出 STEP）；扫描 COM 失败时降级为 `representation=helix-centerline`，只交付螺旋中心线证据与
`*_helix_evidence.bmp`，并明确说明未生成实体——不得把中心线当成实体线材交付。

`*_parameters.json` 必须核对：齿轮 `is_pointed=false`（除非确需尖齿）、`profile_point_count>0`；
弹簧 `representation`、`spring_index` 与 `solid_length_mm<free_length_mm`；链轮 PD/OD/RD 与手册一致。

详细 COM 接口风险、齿形近似边界与官方文档链接见
[标准件实测经验](references/standard-parts-lessons.md)。
