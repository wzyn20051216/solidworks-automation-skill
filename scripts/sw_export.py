"""
SolidWorks 文件导出工具
支持 STEP、STL、IGES、PDF、DXF/DWG、Parasolid 等格式
"""
import os
from pathlib import Path

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import create_empty_dispatch_variant, get_com_member, open_document
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import create_empty_dispatch_variant, get_com_member, open_document

pythoncom, _win32com, VARIANT = import_com_dependencies()

SUPPORTED_BATCH_FORMATS = {".step", ".stp", ".stl", ".igs", ".iges", ".x_t", ".pdf", ".dxf", ".dwg"}


def _ensure_parent_dir(file_path):
    """确保输出文件的父目录存在。"""
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


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
        sheet_names = get_com_member(model, "GetSheetNames")

    if pdf_data:
        pdf_data.SetSheets(0, sheet_names)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    _print_result("PDF", output_path, success, errors, warnings)
    return success


SW_EXPORT_TO_DWG_SHEET_METAL = 1
SW_SHEET_METAL_EXPORT_GEOMETRY = 1
SW_SHEET_METAL_EXPORT_HIDDEN_EDGES = 2
SW_SHEET_METAL_EXPORT_BEND_LINES = 4
SW_SHEET_METAL_EXPORT_SKETCHES = 8
SW_SHEET_METAL_EXPORT_MERGE_COPLANAR_FACES = 16
SW_SHEET_METAL_EXPORT_LIBRARY_FEATURES = 32
SW_SHEET_METAL_EXPORT_FORMING_TOOLS = 64
SW_SHEET_METAL_EXPORT_BOUNDING_BOX = 2048


def _sheet_metal_alignment_variant(alignment=None):
    """@brief 创建 ``ExportToDWG2`` 要求的 12 个双精度对齐参数。"""
    values = tuple(alignment or (0.0,) * 12)
    if len(values) != 12:
        raise ValueError("钣金 DXF 对齐参数必须包含 12 个双精度数值")
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values)


def export_to_dxf(model, output_path):
    """
    导出为 DXF/DWG 格式
    适用于工程图或钣金展开图
    """
    doc_type = get_com_member(model, "GetType")
    if doc_type == 3:  # 工程图
        return _export_generic(model, output_path)
    else:
        # 零件默认按“展开几何 + 折弯线”导出；其余选项由位掩码控制。
        return export_flat_pattern_dxf(model, output_path)


def export_flat_pattern_dxf(
    model,
    output_path,
    *,
    include_bend_lines=True,
    include_sketches=False,
    include_hidden_edges=False,
    include_bounding_box=False,
    merge_coplanar_faces=False,
    alignment=None,
):
    """
    导出钣金展开图为 DXF

    参数:
        model: 钣金零件的 IModelDoc2
    """
    model_path = str(get_com_member(model, "GetPathName") or "")
    if not model_path:
        raise ValueError("导出展开 DXF 前必须先保存钣金零件")

    output_path = os.path.abspath(os.path.expandvars(os.path.expanduser(output_path)))
    _ensure_parent_dir(output_path)
    options = SW_SHEET_METAL_EXPORT_GEOMETRY
    if include_bend_lines:
        options |= SW_SHEET_METAL_EXPORT_BEND_LINES
    if include_sketches:
        options |= SW_SHEET_METAL_EXPORT_SKETCHES
    if include_hidden_edges:
        options |= SW_SHEET_METAL_EXPORT_HIDDEN_EDGES
    if include_bounding_box:
        options |= SW_SHEET_METAL_EXPORT_BOUNDING_BOX
    if merge_coplanar_faces:
        options |= SW_SHEET_METAL_EXPORT_MERGE_COPLANAR_FACES

    return bool(model.ExportToDWG2(
        output_path,
        model_path,
        SW_EXPORT_TO_DWG_SHEET_METAL,
        True,
        _sheet_metal_alignment_variant(alignment),
        False,
        False,
        options,
        None,
    ))


def batch_export(sw, file_paths, output_dir, format_ext=".step"):
    """
    批量导出多个文件

    参数:
        sw: ISldWorks 应用对象
        file_paths: 源文件路径列表
        output_dir: 输出目录
        format_ext: 输出格式扩展名（".step", ".stl", ".igs", ".pdf"）
    """
    report = batch_export_formats(sw, file_paths, output_dir, [format_ext])
    results = []
    for document in report["documents"]:
        output = document.get("outputs", [{}])[0]
        results.append({
            "file": document["source"],
            "success": document["success"],
            "output": output.get("path"),
            "error": document.get("error") or output.get("error"),
        })
    return results


def _normalize_format(format_ext):
    """规范化并校验批量导出扩展名。"""
    extension = str(format_ext).strip().lower()
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension not in SUPPORTED_BATCH_FORMATS:
        raise ValueError(f"暂不支持批量导出格式: {extension}")
    return extension


def _file_signature(path):
    """返回文件存在性证据，用于识别本轮真实产物。"""
    target = Path(path)
    if not target.is_file():
        return None
    stat = target.stat()
    return stat.st_size, stat.st_mtime_ns


def _activate_source_document(sw, model, source_path):
    """@brief 激活并回读源文档，防止 STL 等导出器误用当前活动装配体。"""
    title = str(get_com_member(model, "GetTitle") or "")
    if not title:
        raise RuntimeError("源文档没有可激活的标题")
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        active = sw.ActivateDoc3(title, False, 0, errors)
    except TypeError:
        ole_object = getattr(sw, "_oleobj_", None)
        if ole_object is None:
            raise
        dynamic_sw = _win32com.dynamic.DumbDispatch(ole_object, "SldWorks.Application")
        active = dynamic_sw.ActivateDoc3(title, False, 0, errors)
    except Exception:
        try:
            sw.ActivateDoc2(title, False, errors)
        except TypeError:
            ole_object = getattr(sw, "_oleobj_", None)
            if ole_object is None:
                raise
            dynamic_sw = _win32com.dynamic.DumbDispatch(ole_object, "SldWorks.Application")
            dynamic_sw.ActivateDoc2(title, False, errors)
        active = get_com_member(sw, "ActiveDoc")
    if active is None:
        raise RuntimeError(f"SolidWorks 无法激活源文档: {source_path}")
    active_path = str(get_com_member(active, "GetPathName") or "")
    if not active_path or Path(active_path).resolve() != Path(source_path).resolve():
        raise RuntimeError(f"活动文档与导出源不一致: active={active_path}, source={source_path}")
    return active


def _export_for_format(model, output_path, extension, stl_quality):
    """按已验证封装路由导出格式。"""
    if extension in {".step", ".stp"}:
        return export_to_step(model, output_path)
    if extension == ".stl":
        return export_to_stl(model, output_path, quality=stl_quality)
    if extension in {".igs", ".iges"}:
        return export_to_iges(model, output_path)
    if extension == ".x_t":
        return export_to_parasolid(model, output_path)
    if extension == ".pdf":
        return export_to_pdf(model, output_path)
    if extension in {".dxf", ".dwg"}:
        return export_to_dxf(model, output_path)
    raise ValueError(f"没有导出器: {extension}")


def batch_export_formats(
    sw,
    file_paths,
    output_dir,
    formats=(".step",),
    *,
    overwrite=False,
    close_documents=True,
    stl_quality="fine",
):
    """将多个 SolidWorks 文档批量导出为多个格式。

    返回每个输出的文件大小和 ``produced_this_run`` 证据。原本已经在
    SolidWorks 中打开的文档不会被本函数关闭。
    """
    source_paths = [str(Path(os.path.expandvars(str(path))).expanduser().resolve()) for path in file_paths]
    if not source_paths:
        raise ValueError("file_paths 不能为空")
    extensions = list(dict.fromkeys(_normalize_format(item) for item in formats))
    if not extensions:
        raise ValueError("formats 不能为空")
    output_root = Path(os.path.expandvars(str(output_dir))).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    claimed_outputs = set()
    documents = []

    for source_path in source_paths:
        source = Path(source_path)
        document_result = {"source": source_path, "success": False, "outputs": [], "was_open": False}
        if not source.is_file():
            document_result["error"] = "源文件不存在"
            documents.append(document_result)
            continue
        try:
            existing_model = sw.GetOpenDocumentByName(source_path)
        except Exception:
            existing_model = None
        was_open = bool(existing_model)
        document_result["was_open"] = was_open
        model = existing_model or open_document(sw, source_path, silent=True, raise_on_error=False)
        if model is None:
            document_result["error"] = "SolidWorks 无法打开源文件"
            documents.append(document_result)
            continue

        try:
            for extension in extensions:
                output_path = output_root / f"{source.stem}{extension}"
                output_key = str(output_path).casefold()
                before = _file_signature(output_path)
                output_result = {"format": extension, "path": str(output_path), "success": False}
                if output_key in claimed_outputs:
                    output_result["error"] = "不同源文件产生同名输出，已阻止覆盖"
                    document_result["outputs"].append(output_result)
                    continue
                claimed_outputs.add(output_key)
                if before is not None and not overwrite:
                    output_result["error"] = "目标文件已存在；未显式允许覆盖"
                    document_result["outputs"].append(output_result)
                    continue
                try:
                    _activate_source_document(sw, model, source_path)
                    api_success = bool(_export_for_format(model, str(output_path), extension, stl_quality))
                    after = _file_signature(output_path)
                    produced = api_success and after is not None and after != before
                    output_result.update({
                        "success": bool(produced),
                        "api_success": api_success,
                        "exists": after is not None,
                        "size_bytes": after[0] if after else 0,
                        "produced_this_run": bool(produced),
                    })
                    if api_success and not produced:
                        output_result["error"] = "SolidWorks 返回成功，但没有检测到本轮新产物"
                except Exception as error:
                    output_result["error"] = str(error)
                document_result["outputs"].append(output_result)
        finally:
            if close_documents and not was_open:
                sw.CloseDoc(get_com_member(model, "GetTitle"))
        document_result["success"] = bool(document_result["outputs"]) and all(
            output["success"] for output in document_result["outputs"]
        )
        documents.append(document_result)

    output_count = sum(len(item["outputs"]) for item in documents)
    success_count = sum(
        1 for item in documents for output in item["outputs"] if output["success"]
    )
    report = {
        "success": bool(documents) and all(item["success"] for item in documents),
        "output_dir": str(output_root),
        "formats": extensions,
        "documents": documents,
        "summary": {"documents": len(documents), "outputs": output_count, "succeeded": success_count},
    }
    print(f"批量导出完成: {success_count}/{output_count} 个输出成功")
    return report


def _export_generic(model, output_path):
    """通用导出函数（STEP/STL/IGES/Parasolid/DXF）"""
    model.ClearSelection2(True)
    output_path = os.path.abspath(os.path.expandvars(os.path.expanduser(output_path)))
    _ensure_parent_dir(output_path)
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    success = model.Extension.SaveAs(
        output_path, 0, 1, create_empty_dispatch_variant(), errors, warnings
    )

    ext = os.path.splitext(output_path)[1].upper()
    _print_result(ext, output_path, success, errors, warnings)
    return success


def _print_result(format_name, path, success, errors, warnings):
    """打印导出结果"""
    if success:
        print(f"{format_name} 导出成功: {path}")
    else:
        print(f"{format_name} 导出失败, 错误码: {errors.value}, 警告码: {warnings.value}")
