# AutoCAD 自动化排查

## Python 依赖

症状：`ModuleNotFoundError: No module named 'win32com'`

处理：

```powershell
python -m pip install pywin32
python -m pywin32_postinstall -install
```

如果本机有多个 Python，使用执行脚本的同一个解释器安装。

## 找不到 AutoCAD COM

症状：`Invalid class string`、`Operation unavailable`、`AutoCAD.Application` 创建失败。

处理：

1. 确认安装的是 Windows 桌面版 AutoCAD。
2. 手动启动 AutoCAD 一次，让 COM 注册和首次配置完成。
3. 确认不是无桌面服务会话、远程无 GUI 会话或权限受限环境。
4. 如果安装多个版本，先用默认 `AutoCAD.Application`，必要时查注册表确认版本化 ProgID。

## AutoCAD 已打开但无活动文档

症状：连接成功，访问 `ActiveDocument` 报错。

处理：调用 `Documents.Add()` 新建图纸，或显式打开目标 DWG。

## 新建文档后访问 `Layers` / `ModelSpace` 失败

症状：`Documents.Add()` 后返回对象访问 `Layers` 报 `AttributeError: Add.Layers`。

处理：在 AutoCAD 2024 + pywin32 动态代理环境中，`Documents.Add()` 的返回值可能不是稳定的 `AcadDocument` 代理。调用 `Documents.Add()` 后重新绑定：

```python
app.Documents.Add()
doc = app.ActiveDocument
```

`scripts/acad_session.py` 的 `new_document()` 已按此方式实现。

## `SendCommand` 没有效果

常见原因：

- 命令字符串缺少最后的换行。
- 命令异步执行，脚本立刻保存导致命令尚未完成。
- 本地化界面导致命令名变化。
- 命令正在等待用户输入。

建议：

- 优先用 COM 对象模型。
- 命令前加 `_.`，例如 `_.ZOOM _E`。
- 每条命令显式提供所有参数和换行。
- 发送后等待并用 `acad_review.py` 验证结果。

## 保存失败或覆盖风险

处理：

- 输出路径使用绝对路径。
- 保存前创建目录。
- 修改既有 DWG 前另存副本。
- 关闭占用该文件的其他程序。
- 失败时记录异常，不要继续导出衍生文件。

## DXF 导出失败

症状：`Document.SaveAs("xxx.dxf")` 失败，或 AutoCAD 返回乱码 COM 错误。

处理：DXF 不要依赖 `SaveAs` 扩展名推断，使用 `Document.Export(fileBase, "DXF", selectionSet)`。ActiveX `Export` 即使导出整张图也要求传入 `SelectionSet` 参数，可创建临时空选择集。`scripts/acad_session.py` 的 `export_dxf()` 已封装此流程。

## 图片线稿里出现奇怪的外围轮廓、椭圆、三角形或彩色线

症状：

- 用户截图指出“外围这是啥”“这都是啥”。
- 人像外侧出现大弧线、长折线，脸上出现椭圆/折线，Logo 附近出现三角形/斜线，水花处出现彩色波浪线。
- 复核图层里存在 `PORTRAIT_OUTLINE`、`BODY_OUTLINE`、`JERSEY_OUTLINE`、`FACE_FEATURES`、`LOGO_GEOMETRY`、`WATER_SPLASH`、`JERSEY_STRIPE`、`TEXT_LOGO`、`TEXT_BRAND`、`REVIEW_NOTES` 等非原图描线层。

原因：

- 为了让图像“更像”参考图，脚本手工补了外围轮廓、五官、Logo、水花或替代文字。
- 这些增强线在 CAD 里会被用户理解成真实图纸对象或错误辅助线，而不是艺术化补笔。
- 图内审查说明、评分文字也会污染最终模型空间。

处理：

1. 普通“照图画 CAD”最终版只保留原图矢量化线条，例如 `TRACE_DARK`、`TRACE_LIGHT`。
2. 删除或关闭所有手工增强/构造层；不要仅依赖口头说明。
3. 审查说明、评分、生成参数写入 JSON/Markdown 报告，不写进最终 ModelSpace。
4. 复核时把禁止层列入检查清单，并要求实体数为 0：

```python
aux_layers = [
    "PORTRAIT_OUTLINE", "BODY_OUTLINE", "JERSEY_OUTLINE",
    "OUTER_GUIDE", "CONSTRUCTION", "FACE_FEATURES",
    "LOGO_GEOMETRY", "WATER_SPLASH", "JERSEY_STRIPE",
    "TEXT_LOGO", "TEXT_BRAND", "REVIEW_NOTES",
]
assert all(layer_counts.get(name, 0) == 0 for name in aux_layers)
```

5. 如果用户明确要求增强或重构，增强对象必须放独立图层，并在最终回复说明“这些是手工增强层，可关闭”。

复盘教训：

- 不要把“可辨识”误解成“可以手工猜线”。参考图线稿任务的第一目标是干净、忠实、无多余实体。
- 彩色辅助层、水波线、替代文字和构造几何即使在技术上提高评分，也可能降低用户信任。
- 最终审查标准要包含负向检查：没有额外辅助层、没有图内说明文字、没有非原图装饰线。

## AutoCAD COM 短暂拒绝调用或返回乱码错误

症状：

- 批量落线或创建图层时出现 `pywintypes.com_error: (-2147418111, ...)`，错误文本可能是乱码。
- `Layers.Item()`、`Layers.Add()`、`ModelSpace.AddLine()` 偶发失败，重跑又可能成功。

原因：

- AutoCAD 桌面 COM 是单线程/交互式自动化目标，绘图、重生成、打开文档或导出时会短暂忙碌。
- 并行访问同一个 AutoCAD 实例会放大这种不稳定。

处理：

1. AutoCAD COM 操作串行执行，不要并行跑复核、预览和绘图。
2. 对高频 COM 调用加有限重试和退避，尤其是建层、`AddLine`、`SelectionSets`、`Export`、`SaveAs`。
3. 新建或打开文档后等待 1-2 秒，再重新绑定 `app.ActiveDocument`。
4. 批量生成大量实体时，每隔几百个实体 `Regen()` / `live_update()` 一次，但不要过于频繁。

示例：

```python
for attempt in range(12):
    try:
        ent = model.AddLine(p0, p1)
        break
    except Exception:
        if attempt == 11:
            raise
        time.sleep(0.08 + attempt * 0.04)
```

## ModelSpace 不能直接枚举

症状：`for entity in session.model` 报 `TypeError: This object does not support enumeration`。

原因：某些 AutoCAD/pywin32 动态代理下，`ModelSpace` 不提供 Python 可迭代接口，但仍支持 `Count` 和 `Item(index)`。

处理：复核脚本使用 `Count` / `Item(i)` 兼容方式遍历：

```python
ms = doc.ModelSpace
for i in range(int(ms.Count)):
    entity = ms.Item(i)
```

## `SaveAs` 覆盖当前已打开 DWG 失败

症状：生成完成但 `SaveAs(target)` 报“保存文档时出错”，目标文件已存在或正在 AutoCAD 中打开。

处理：

1. 不要强制覆盖用户已打开的旧文件。
2. 输出到带版本/语义的新文件名，例如 `_approved`、`_trace_only`。
3. 保存后检查文件存在和大小，再继续导出 DXF/预览。

## `SelectionSets` 或 `Export` 代理异常

症状：

- `doc.SelectionSets.Add(name)` 报 `AttributeError: <unknown>.Add`。
- `doc.Export(...)` 报 `AttributeError: Open.Export` 或其它代理错位错误。
- DXF 或 BMP 预览导出单独失败，但 DWG 已保存。

原因：

- AutoCAD 正在忙碌、活动文档代理错位，或刚打开只读图纸后 COM 动态代理未稳定。

处理：

1. 串行执行，避免同时跑 `acad_review.py` 和 `acad_preview.py`。
2. 打开源文件后等待，再重新获取 `app.ActiveDocument`。
3. 创建 SelectionSet 前删除同名残留；失败时重试。
4. 若 BMP 预览失败但 DWG/DXF 和实体复核已通过，最终回复要明确“原生预览导出失败”，并给出已完成的复核证据，不要伪造截图。

## 窗口截图被遮挡或黑屏

症状：OS 截图成功但画面被其它前景窗口遮住，或只得到黑色小图。

处理：

1. 窗口截图只能证明桌面当前可见内容，不能证明 DWG 本身正确。
2. 优先用 `scripts/acad_preview.py` 通过 AutoCAD `Document.Export(..., "BMP", selectionSet)` 导出原生预览。
3. 导出前调用 `Regen()` 和 `ZoomExtents()`；导出后用图片查看工具检查图框、视图、文字、尺寸和重叠。
4. 如仍需 OS 截图，先确认 AutoCAD 窗口无遮挡，再调用 screenshot helper；被遮挡截图不可作为通过依据。

## 画图过程不可见

症状：脚本虽然成功生成 DWG，但用户看不到 AutoCAD 被打开或看不到逐步落图过程。

处理：

1. 使用 `scripts/acad_draw.py` 的默认模式，不要加 `--fast`。
2. 确认 `live_preview` 没被设为 `false`；默认应为 `true`。
3. 调用 `AutoCADSession.activate_window()` 把 AutoCAD 尽量切到前台，再在每步之后执行 `live_update()`。
4. 如果桌面上有其它窗口频繁抢焦点，逐步绘图仍可能被遮挡；此时 AutoCAD 原生预览仍要作为最终审查依据。

## SelectionSet 名称冲突

症状：创建选择集时报名称已存在。

处理：先遍历 `doc.SelectionSets`，删除同名 SelectionSet，再创建。

## 包围盒读取失败

部分对象、空对象或代理对象不支持 `GetBoundingBox`。复核脚本应跳过并记录错误，不应整体失败。

## PDF/Plot 不稳定

PDF 输出依赖打印机、PC3、页面设置、CTB/STB、后台打印配置。自动化时：

- 首选已有模板的 PageSetup。
- 关闭后台打印或等待 Plot 完成。
- 输出后检查 PDF 文件大小。
- 关键交付前人工打开 PDF 看图框、方向、比例和线宽。
