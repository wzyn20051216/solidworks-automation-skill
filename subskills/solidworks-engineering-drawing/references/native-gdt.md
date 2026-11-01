# SolidWorks 2026 原生 GD&T 图纸副本（pilot）

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
复合/多框公差、基准材料修饰、公共基准、投影公差带等复杂语义尚未支持，不接收任意 XML。

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
```

真机脚本只使用自建临时模型。矩阵须使用自建且包含 A 基准/圆孔的测试图纸，
验证 14 种符号和位置度的 M/L/S 三种材料条件的写入、保存重开及非悬空关联，**不验证这些测试公差的设计合理性**。
完整副本样例包含四孔板、8 个尺寸、A 基准和关联孔径尺寸的位置度，另测缺失目标与写入失败隔离。
真机脚本和 `test_sw_read_guard` 不应同时执行，因为它们共享进程间互斥锁。

API 依据：[新版框 XML](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.interop.sldworks~SolidWorks.interop.sldworks.IGtolFrame~SetSymbolXml.html)、
[GTol XML Schema](https://help.solidworks.com/2026/english/api/sldworksapiprogguide/Overview/Gtol_Frame_XML_Schema.htm)、
[基准样式](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IDatumTag~SetDisplayStyle.html)。
