"""
SolidWorks 文件导出工具
支持 STEP、STL、IGES、PDF、DXF/DWG、Parasolid 等格式
"""
import win32com.client
import pythoncom
from win32com.client import VARIANT
import os


def export_to_step(model, output_path):
    """导出为 STEP 格式"""
    return _export_generic(model, output_path)


def export_to_stl(model, output_path, quality="fine"):
    """
    导出为 STL 格式

    参数:
        quality: "coarse" | "fine" | "custom"
    """
    # 设置 STL 质量
    quality_map = {"coarse": 1, "fine": 0}
    if quality in quality_map:
        model.SetUserPreferenceIntegerValue(78, quality_map[quality])  # swSTLQuality
    return _export_generic(model, output_path)


def export_to_iges(model, output_path):
    """导出为 IGES 格式"""
    return _export_generic(model, output_path)


def export_to_parasolid(model, output_path):
    """导出为 Parasolid (.x_t) 格式"""
    return _export_generic(model, output_path)


def export_to_pdf(model, output_path, sheet_names=None):
    """
    导出工程图为 PDF

    参数:
        model: IModelDoc2（必须是工程图文档）
        output_path: PDF 文件路径
        sheet_names: 图纸名称列表，None=所有图纸
    """
    sw = model.GetSldWorksObject()
    pdf_data = sw.GetExportFileData(1)  # swExportPDFData

    if sheet_names is None:
        sheet_names = model.GetSheetNames()

    if pdf_data:
        pdf_data.SetSheets(0, sheet_names)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    _print_result("PDF", output_path, success, errors, warnings)
    return success


def export_to_dxf(model, output_path):
    """
    导出为 DXF/DWG 格式
    适用于工程图或钣金展开图
    """
    doc_type = model.GetType()
    if doc_type == 3:  # 工程图
        return _export_generic(model, output_path)
    else:
        # 零件（钣金展开图）
        return model.ExportToDWG2(
            output_path, model.GetPathName(),
            1, True, True, False, False, 0, None
        )


def export_flat_pattern_dxf(model, output_path):
    """
    导出钣金展开图为 DXF

    参数:
        model: 钣金零件的 IModelDoc2
    """
    return model.ExportToDWG2(
        output_path, "",
        1,      # 导出展开图
        True,   # 包含外轮廓
        True,   # 包含弯曲线
        False,  # 草图实体
        False,  # 隐藏边线
        0, None
    )


def batch_export(sw, file_paths, output_dir, format_ext=".step"):
    """
    批量导出多个文件

    参数:
        sw: ISldWorks 应用对象
        file_paths: 源文件路径列表
        output_dir: 输出目录
        format_ext: 输出格式扩展名（".step", ".stl", ".igs", ".pdf"）
    """
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for file_path in file_paths:
        # 打开文件
        ext = os.path.splitext(file_path)[1].lower()
        type_map = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}
        doc_type = type_map.get(ext, 1)

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        model = sw.OpenDoc6(file_path, doc_type, 1, "", errors, warnings)  # 静默打开
        if not model:
            results.append({"file": file_path, "success": False, "error": "无法打开"})
            continue

        # 导出
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_path = os.path.join(output_dir, base_name + format_ext)

        if format_ext == ".pdf":
            success = export_to_pdf(model, output_path)
        else:
            success = _export_generic(model, output_path)

        results.append({"file": file_path, "success": bool(success), "output": output_path})

        # 关闭文档
        sw.CloseDoc(model.GetTitle())

    # 汇总
    success_count = sum(1 for r in results if r["success"])
    print(f"批量导出完成: {success_count}/{len(results)} 成功")
    return results


def _export_generic(model, output_path):
    """通用导出函数（STEP/STL/IGES/Parasolid/DXF）"""
    model.ClearSelection2(True)
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    success = model.Extension.SaveAs(output_path, 0, 1, None, errors, warnings)

    ext = os.path.splitext(output_path)[1].upper()
    _print_result(ext, output_path, success, errors, warnings)
    return success


def _print_result(format_name, path, success, errors, warnings):
    """打印导出结果"""
    if success:
        print(f"{format_name} 导出成功: {path}")
    else:
        print(f"{format_name} 导出失败, 错误码: {errors.value}, 警告码: {warnings.value}")
