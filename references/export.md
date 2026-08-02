# 文件导出参考

## 支持的导出格式

| 格式 | 扩展名 | 需要 ExportData | 说明 |
|---|---|---|---|
| STEP | `.step` `.stp` | 否 | 通用 3D 交换格式 |
| IGES | `.igs` `.iges` | 否 | 传统交换格式 |
| STL | `.stl` | 否 | 3D 打印/网格 |
| Parasolid | `.x_t` `.x_b` | 否 | 高精度内核格式 |
| PDF | `.pdf` | 是（IExportPdfData） | 工程图导出 |
| DXF/DWG | `.dxf` `.dwg` | 否 | 2D 图纸/展开图 |
| 3D PDF | `.pdf` | 是 | 3D 嵌入式 PDF |
| eDrawings | `.eprt` `.easm` `.edrw` | 否 | 轻量查看格式 |

## SaveAs 错误码

| 值 | 名称 | 说明 |
|---|---|---|
| 0 | swGenericSaveError | 通用错误 |
| 1 | swReadOnlySaveError | 只读文件 |
| 2 | swFileNameEmpty | 文件名为空 |
| 3 | swFileNameContainsAtSign | 文件名包含 @ |
| 5 | swFileSaveFormatNotAvailable | 格式不可用 |
| 6 | swFileSaveAsDoNotOverwrite | 不覆盖现有文件 |
| 9 | swFileSaveAsInvalidFileExtension | 无效扩展名 |

## SaveAs 警告码

| 值 | 名称 | 说明 |
|---|---|---|
| 1 | swFileSaveWarning_RebuildError | 重建错误 |
| 2 | swFileSaveWarning_NeedsRebuild | 需要重建 |
| 4 | swFileSaveWarning_ViewsNeedUpdate | 视图需更新 |

## STL 导出质量设置

```python
# 设置 STL 输出质量
# swUserPreferenceIntegerValue_e.swExportStlUnits = 78
model.SetUserPreferenceIntegerValue(78, 0)  # 0=Fine, 1=Coarse

# 设置自定义偏差和角度
# swSTLDeviation
model.SetUserPreferenceDoubleValue(0x00000F, 0.005)  # 偏差（米）
# swSTLAngleTolerance
model.SetUserPreferenceDoubleValue(0x000010, 0.174)  # 角度容差（弧度，约10°）
```

## 批量转换示例

```python
import os
from sw_connect import open_document

def batch_convert(sw, input_dir, output_dir, input_ext=".sldprt", output_ext=".step"):
    """批量转换目录下的所有文件"""
    os.makedirs(output_dir, exist_ok=True)

    for filename in os.listdir(input_dir):
        if filename.lower().endswith(input_ext):
            input_path = os.path.join(input_dir, filename)
            base = os.path.splitext(filename)[0]
            output_path = os.path.join(output_dir, base + output_ext)

            # 打开；STEP/STP/IGES/IGS 会自动走 LoadFile4(..., "r", ...)
            errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            model = open_document(sw, input_path, silent=True)

            if model:
                # 导出
                model.Extension.SaveAs(output_path, 0, 1, None, errors, warnings)
                sw.CloseDoc(model.GetTitle())
                print(f"已转换: {filename} -> {base + output_ext}")
```

## 可审计批量导出

`scripts/sw_export.py::batch_export_formats()` 支持多个输入、多个输出格式，并对每个输出记录：

- SolidWorks API 返回值；
- 文件是否存在、字节数；
- 文件签名是否在本轮发生变化；
- 原文档是否已由用户打开。

默认不覆盖已有文件，也不关闭用户原先打开的 SolidWorks 文档。同名源文件会产生相同目标名时直接阻止，不以最后写入者覆盖前一个结果。

## Pack and Go

`scripts/sw_delivery.py::pack_and_go()` 使用 SolidWorks 原生 `IModelDocExtension.GetPackAndGo()`、`IPackAndGo.SetSaveToName()` 和 `IModelDocExtension.SavePackAndGo()`。这些签名已由本机 SolidWorks 2024 Interop 与官方 API Help 交叉核对。

兼容性说明：官方与 Interop 都把 `GetPackAndGo()` 暴露为零参数返回 `IPackAndGo`；但本机 SW2024 + pywin32 运行时对象会报“非选择性的参数”。封装函数会先走 pywin32 官方零参数路径，失败后改用 `comtypes` 早绑定调用原生 Pack and Go，并保留 pywin32 错误上下文。

安全边界：

1. 当前文档必须已经保存到磁盘。
2. 目标目录非空时默认拒绝；只有显式 `overwrite=True` 才继续。
3. 原生清单完整时不自行复制引用文件；若原生清单不完整且 `fallback_policy=stage_dependencies`（默认），才按 `GetDependencies2` 返回的实际路径生成明确标记的暂存包。
4. 返回逐文件大小、SHA-256 和 `produced_this_run`；状态码非零、本轮没有真实文件或暂存源文件缺失时不得标记成功。
5. 本机 SW2024 真机回归显示：装配依赖 API 能看到 `.SLDPRT` 引用，但原生 `IPackAndGo.GetDocumentNames()` 可能只返回顶层 `.SLDASM`。此时报告保留 `native_missing_dependencies`，暂存包使用 `backend=solidworks-native+staged_dependencies`、`status=pilot`，并生成 `cadstudio-pack-manifest.json`。
6. 需要严格原生语义时传 `fallback_policy=blocked`；无论哪种模式，外部引用、Toolbox、配置、压缩组件和工程图仍需人工抽查。

严格模式漏依赖时返回稳定门禁字段：`status=blocked`、`stage=review`、
`error_code=SW_PACK_AND_GO_DEPENDENCY_ENUMERATION_INCOMPLETE`。默认暂存模式会返回
`status=pilot`、`error_code=SW_PACK_AND_GO_NATIVE_ENUMERATION_INCOMPLETE`，这表示文件包可继续交付但不是原生 Pack and Go，必须人工复核。

批量导出每种格式前都会激活源文档，并回读 `ActiveDoc.GetPathName()`。这是因为 SW2024
对 STL 等导出器可能使用活动文档，即使对另一个 `IModelDoc2.Extension.SaveAs()` 调用返回成功；
路径不一致时必须停止，避免把装配体组件错误导出成目标零件 STL。

## 拆分 STEP 再装配的坐标规则

把一个复杂 STEP/Compound 拆成多个 STEP 以便 SolidWorks 稳定导入时，不要假设分件在
SolidWorks 中仍以局部原点表示。部分导出器会保留实体原始绝对坐标；此时
`AddComponent5(..., x=0, y=0, z=0)` 可能把每个分件按包围盒中心放到装配原点，造成组件全部重叠。

推荐 manifest 同时保存：

- `label`：稳定组件名。
- `step`：分件 STEP 路径。
- `color_hex`：预期颜色。
- `bbox.center_mm` / `bbox.center_m`：分件导出前的全局包围盒中心。
- `bbox.size_mm`：用于导入后核对尺度。

装配时按 `bbox.center_m` 插入组件，并在保存前抽查总装包围盒、关键组件 Transform 和四视图。

```python
center = item["bbox"]["center_m"]
component = add_component(
    assembly,
    item["native_path"],
    x=center[0],
    y=center[1],
    z=center[2],
    sw=session.sw,
)
```

验证重点：

1. 车、机架、壳体等总装外形尺寸应接近原始 STEP。
2. 不要只验证组件数；组件全部叠在原点时数量和颜色回读也可能全部通过。
3. `run_review()` 结果必须配合 PNG/BMP 目视检查。
