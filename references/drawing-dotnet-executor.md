# .NET C# 自动出图执行器（drawing_spec → SLDDRW）

把「自动出图」交给 **.NET C# PIA 执行器**，Python 只做「非原生精度」工作。这是仓库多后端路由
（`references/language-backend-routing.md`）的自然落点：出图 API 封送最重（`IView`/`IDisplayDimension`、
坐标标注、`InsertDatumTag2`、`InsertGtol`、`IHoleTable`、尺寸公差对象，大量 `object/out`/`SAFEARRAY`/枚举），
C# 强类型 `out/ref/enum` 比 Python COM 稳。

## 分工与契约

```
Python（非原生·离线可验证）                        .NET C#（原生精度·pilot）
─ NL→计划 / 钻孔面板孔位·基准·GD&T 分析            dotnet/CadStudio.SolidWorks.Drawing
─ DRC 审计 / 风险 / 让步                            ├ Program.cs      CLI：--spec/--evidence-out/...
─ drawing_spec 生成（已 schema 校验） ──spec JSON──▶ ├ DrawingExecutor 连接 SW→建视图/尺寸/GD&T/孔表/BOM/注释/保存/PDF
─ scripts/sw_drawing_dotnet.py 调度 ◀─evidence JSON─ ├ JsonUtil        spec 字典安全读取
─ 解析 evidence、交 review                          └ 回写 cadstudio.drawing-evidence JSON
```

- **入**：中性 `drawing_spec` JSON（工程图子技能 schema，Python 侧 `validate_drawing_spec` 门禁通过才启动）。
- **出**：`*_drawing_evidence.json`（每阶段 status=ok/pilot/fail、落盘产物、warnings），供 Python review 判定。

## 编译与运行（Windows + SolidWorks）

```powershell
# 1) 编译（指向本机 SolidWorks PIA redist 目录）
dotnet build dotnet/CadStudio.SolidWorks.Drawing/CadStudio.SolidWorks.Drawing.csproj -c Release `
  -p:SolidWorksApiDir="C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist"

# 2) Python 侧生成 spec（示例：钻孔面板）后调度 C# 出图
python scripts/sw_drawing_dotnet.py path\to\panel_spec.json --source-model path\to\panel.SLDPRT `
  --output-dir out
# 或用环境变量指定 exe
$env:CADSTUDIO_DRAWING_EXE="...\CadStudio.SolidWorks.Drawing.exe"
```

Python launcher 在以下情况**不启动** C# 并返回 `blocked`：spec 未过 schema 校验；找不到 exe（给出编译提示）；执行超时。

## 能力等级

- **可离线验证（verified 级逻辑）**：`scripts/sw_drawing_dotnet.py` 的 spec 门禁、exe 解析、evidence 解析与结果汇总（`tests/test_sw_drawing_dotnet.py`）。
- **pilot（需真机）**：C# 执行器本身——需 Windows+SolidWorks+PIA 才能编译/运行，本环境无法验证。
  - 可靠自动化段直接执行：命名视图（front/top/right/iso）、`InsertModelAnnotations3` 模型尺寸、技术要求注释、保存 SLDDRW、导出 PDF。
  - 依赖具体实体选择的段标 pilot，尝试并如实回写 evidence，不谎报：某边 `InsertGtol`/`InsertDatumTag2`、某面 `IHoleTable`、`BOM`、剖视/局部视图、运行时投影角切换——真机应结合 `drilling_panel_gdt` 的几何证据与语义引用（`sw_entity_reference`）选中实体后落地。

## 路由

`capabilities.yaml` 新增能力 `drawing_dotnet_generation` 与同名 operation_route，候选 `solidworks-csharp-pia`
优先级 10、`solidworks-com-pywin32` 回退 20——即「出图优先 C#，Python COM 兜底」。
