# SolidWorks 2026 原生 GD&T 与结构化自动落图（pilot）

已完成的尺寸图可以通过 `scripts/sw_gdt_copy.py` 添加真正的 DatumTag 和新版 XML GTol。
此入口只处理 **SW2026、单页、单零件、横向 A3、毫米单位** 的图纸；不修改源图纸和零件。
源模型必须已保存且引用可确认。它与通用 `solidworks_generate_drawing` 的能力前置检查分开，
不会把旧版 DrawingSpec 中的自由文字要求当成可执行 GD&T。

## 自然语言任务的执行顺序

用户要求“给图纸添加基准/位置度/其他形位公差”时，Agent 应先读取本文件，再只读列出目标：

```powershell
python scripts/sw_gdt_copy.py --source C:\work\plate.slddrw --inspect
```

结果包含 `sourceSha256`、实际图纸页/视图名称、尺寸选择名称及 SI 数值、可见直线端点和圆边中心/半径。
边线坐标是**模型坐标，单位毫米**，不是图纸坐标；`positionMm` 是图纸坐标。
同心或投影重合等多候选目标不会按最近点、Edge1 或模糊评分猜选。
尺寸选择同时要求名称和 `systemValue` 精确匹配，后者使用 SolidWorks 的 SI 单位。

基准面、被控要素、公差值、材料条件和基准顺序必须来自用户的工程要求。
检索官方 API 可以解决调用方式，不能代替这些设计输入。缺失设计输入时继续只读分析，不能自行填入生产公差。

按 `schemas/gdt_copy_spec.schema.json` 构建计划，再执行：

```powershell
python scripts/sw_gdt_copy.py --source C:\work\plate.slddrw --plan C:\work\gdt-plan.json --output-dir C:\work\annotated-copy
```

计划包含 `schemaVersion="1.0"`、源 SHA-256、实际 `sheet`、`paperSize="A3"`、`datums` 和
`geometricTolerances` 数组。每项具有唯一 `id` 和实际 `view`。

- 基准：`label`、`displayStyle="square"` 或 `"round_gb"`、`positionMm`、明确边线 `target`。
- 公差：`characteristic`、正十进制字符串 `tolerance`（毫米）、布尔 `diameter`、顺序明确的 `datums`、`target`。
- 可选 `materialCondition`：`null`、`"M"`、`"L"`、`"S"`；当前只开放圆柱位置度和轴线直线度的材料条件。
- 边线目标需要 `positionMm`；尺寸目标由 SolidWorks 自动锚定，不能同时指定位置。
- 直线目标为 `{ "kind": "line", "startMm": [x,y,z], "endMm": [x,y,z] }`。
- 圆边目标为 `{ "kind": "circle", "centerMm": [x,y,z], "radiusMm": r }`；圆边不自动证明孔型或完整圆周。
- 尺寸目标为 `{ "kind": "dimension", "name": "实际选择名称", "systemValue": 0.01 }`。

形状公差不能引用基准；需要基准的公差不能省略基准；基准必须已经存在或在本计划中创建，重名基准被阻断。
单框原生符号支持：`straightness`、`flatness`、`circularity`、`cylindricity`、`line_profile`、
`surface_profile`、`parallelism`、`perpendicularity`、`angularity`、`position`、`concentricity`、
`symmetry`、`circular_runout`、`total_runout`。符号可写入不代表它适合所选标准或被控几何。
支持 1..8 层独立叠加框和复合框。使用 `frames` 数组时不能同时提供旧单框字段；每层显式提供
`characteristic`、`tolerance`、`diameter`、`datums`，后续复合层设置 `composite: true`。
首层必须保留特征符号，复合后续层沿用相同特征及公差带类型、公差不增大；
只能按前层顺序保留基准及修饰的前缀，允许后层省略基准。
基准引用兼容 `"A"`，也接受 `{ "label": "A", "materialCondition": "M" }`（M/L/S/null），
它与公差本体的 `materialCondition` 独立。修饰是否适合相应尺寸要素仍由设计者确认。
公共基准/子基准组、投影公差带、轮廓偏置、CZ/SZ、局部范围/最大公差、互易要求及其他框内修饰，
使用 [gdt-extended-options.md](gdt-extended-options.md) 的结构化输入；不接收任意 XML。

## 从三维模型自动落图

现有 MCP `solidworks_generate_drawing` 与以下 CLI 共用同一条出图和保存重开核验流程，
无需新增工具。DrawingSpec 的标准视图使用 `front`、`top`、`right`，支持第一角和第三角。

```powershell
python scripts/sw_drawing_package.py --spec C:\work\drawing.json --output-dir C:\work\delivery
```

原生路径要求 SW2026、毫米单位的单零件、明确 `modelSizeMm` 与已保存源模型；
图幅可选 A4/A3/A2/A1/A0；本轮真机覆盖 A3 和 A2，其余图幅尚未逐一实测。
`templateCandidates` 提供与图幅和标准一致的本机图框候选，缺失时明确阻断。
源模型和依赖只读打开，逐一记录并核对哈希。
`requiredDimensions` 每项提供唯一 `id`、`kind`（linear/overall/diameter/radius/angular）、
标准 `view`、`valueMm`（角度为 `valueDegrees`）、图纸坐标 `positionMm`，以及
一个明确 `target` 或一对 `targets`。线性尺寸额外提供 `axis: horizontal/vertical`。
`basic: true` 创建真实基本尺寸方框；孔数量可使用 `prefix: "4X "`。
提供显式尺寸时不允许再启用批量 `insertModelDimensions: true`。
视图默认留出标注间距，也可用 `views.front.positionMm` 等明确指定。

`professionalAnnotations.datums` 和 `geometricTolerances` 使用上述结构化标注字段，
但 `view` 使用标准视图别名。公差框既可关联明确边线，也可关联本轮新建尺寸：

```json
{
  "id": "POSITION", "view": "front",
  "target": {"kind": "dimension", "dimensionId": "HOLES"},
  "frames": [
    {"characteristic": "position", "tolerance": "0.2", "diameter": true,
     "datums": [{"label": "A", "materialCondition": "M"}]},
    {"characteristic": "position", "tolerance": "0.1", "diameter": true,
     "datums": [{"label": "A", "materialCondition": "M"}], "composite": true}
  ]
}
```

这里的数值只展示 API 契约，不能直接作为生产设计。全部基准必须在当前规格中声明，
尺寸 ID 必须存在且位于同一视图。旧自由文字 `text` 仍只用于审查，不会猜测并落图。
缺失/歧义选择器、错误数值、跨视图引用、缺失基准或非法复合层会阻断，不回退为 Note。
孔表、螺纹、粗糙度、焊接符号等未实现的专业字段仍被明确阻断。

尺寸及标注持久身份、原生类型、基本尺寸、前缀、全部层 XML、基准修饰和实际关联
均在保存重开后核对；生成报告还检查必要尺寸、PDF 数值和布局。
原生验证通过后仍为 `review_required`：必须复核尺寸链、引线交叉和设计公差，不能声称自动证明制造合规。

## 成功和失败的含义

全部目标在创建输出目录前预解析；源文件发生变化、目标缺失/歧义或缺失基准都会阻断。
写入只发生在独占创建的新副本。写入失败时会关闭本轮自有文档，丢弃未保存修改；
如果已保存后才发现问题，副本和失败清单保留供排查，`outputs` 不会报告成功交付。
不会原位撤销用户的其他编辑，也不删除用户文档。

全部标注写入后先重建并保存，以保存后的布局作为重开基线；用户显式指定的位置在保存后仍必须满足，不能用新坐标掩盖偏移。
每个新标注在重开后核对标注持久身份、目标持久身份、基准样式/公差 XML 和实际位置；新建操作也不能复用旧标注的身份。
尺寸关联 GTol 的 `SetPosition` 即使返回成功，也可能被 SolidWorks 忽略，所以该目标使用自动位置回读。
随后导出 PDF/BMP，将尺寸与 PDF 文字框关联，并执行布局检查和源文件 SHA-256 检查。
成功输出 `SLDDRW`、`PDF`、预览图和 `gdt-copy-manifest.json`，状态仍为 `review_required`（CLI 退出码 2）。
必须目视检查新增公差框、基准引线、尺寸链和标题栏；自动布局检查不能证明全部 GD&T 引线无穿越。
本入口不计算合理公差、不补齐所有尺寸，也不宣称完成制造或标准合规验收。

## 可复现验证

```powershell
python -m pytest -q tests/test_sw_gdt_annotation.py tests/test_sw_gdt_copy.py
python tests/solidworks_gdt_attachment_probe.py --copy-workflow
python tests/solidworks_gdt_symbol_matrix.py C:\test\attachment.slddrw
python tests/solidworks_gdt_advanced_live.py --source C:\test\attachment.slddrw --plan C:\test\gdt-plan.json
python tests/solidworks_gdt_generation_live.py
python tests/solidworks_gdt_generation_live.py --source C:\test\self-created-plate.sldprt --paper-size A2 --mcp
python tests/solidworks_gdt_generation_live.py --source C:\test\self-created-plate.sldprt --extra-dimensions
python tests/solidworks_drawing_failure_live.py --source C:\test\self-created-plate.sldprt
```

真机脚本只使用自建临时模型。矩阵须使用自建且包含 A 基准/圆孔的测试图纸，
验证 14 种符号和位置度的 M/L/S 三种材料条件的写入、保存重开及非悬空关联，**不验证这些测试公差的设计合理性**。
完整副本样例包含四孔板、8 个尺寸、A 基准和关联孔径尺寸的位置度，另测缺失目标与写入失败隔离。
扩展回归验证独立双框、复合双框及基准 M/L/S；自动落图回归验证 8 个原生尺寸、4 个基本尺寸、
基准和尺寸关联复合框，包含 A3 脚本入口、A2 真实 MCP 注册函数入口、保存重开/比例/PDF/布局，
扩展样例另核验半径和角度尺寸（共 10 个尺寸）及角度符号的 PDF 文字识别，
以及目标缺失、尺寸值错误时的源哈希和自有文档清理。调用 MCP 注册函数不代替所有客户端 UI 兼容测试。
真机脚本和 `test_sw_read_guard` 不应同时执行，因为它们共享进程间互斥锁。

API 依据：[新版框 XML](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.interop.sldworks~SolidWorks.interop.sldworks.IGtolFrame~SetSymbolXml.html)、
[GTol XML Schema](https://help.solidworks.com/2026/english/api/sldworksapiprogguide/Overview/Gtol_Frame_XML_Schema.htm)、
[基准样式](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDatumTag~SetDisplayStyle.html)。
