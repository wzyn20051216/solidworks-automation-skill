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
