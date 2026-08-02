"""
SolidWorks 工程图操作工具
"""
try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import create_empty_dispatch_variant, get_com_member
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import create_empty_dispatch_variant, get_com_member

pythoncom, _win32com, VARIANT = import_com_dependencies()


def _safe_member(obj, name, *args, default=None):
    """@brief 读取工程图 COM 成员，失败时返回默认值。"""
    if obj is None:
        return default
    try:
        value = get_com_member(obj, name, *args)
        return default if value is None else value
    except Exception:
        return default


def _as_sequence(value):
    """@brief 统一 COM 数组、元组和单对象返回值。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def create_standard_views(drawing_model, part_path):
    """
    创建标准三视图（第三角投影法）

    参数:
        drawing_model: IDrawingDoc
        part_path: 零件文件路径
    """
    return drawing_model.Create3rdAngleViews2(part_path)


def add_view(drawing_model, part_path, view_name, x, y, scale=None):
    """
    添加单个视图

    参数:
        view_name: 视图方向名称
            "*Front", "*Back", "*Top", "*Bottom",
            "*Left", "*Right", "*Isometric",
            "*Trimetric", "*Dimetric"
        x, y: 视图放置位置（米）
        scale: 视图比例（如 0.5 表示 1:2），None 使用图纸默认
    """
    view = drawing_model.CreateDrawViewFromModelView3(
        part_path, view_name, x, y, 0
    )
    if view and scale:
        view.ScaleRatio = (1.0, 1.0 / scale)
    return view


def add_section_view(drawing_model, x, y):
    """在当前选择的剖切线位置创建剖视图"""
    return drawing_model.CreateSectionViewAt5(x, y, 0, "", 0, None, 0)


def add_detail_view(drawing_model, x, y, scale=2.0):
    """创建局部放大视图"""
    return drawing_model.CreateDetailViewAt4(x, y, 0, 0, scale, 0, "")


def insert_dimensions(drawing_model, view=None):
    """
    自动标注尺寸（模型项目）

    参数:
        view: 目标视图对象，None 则标注所有视图
    """
    # SolidWorks 2024 新增 InsertModelAnnotations4，返回实际插入的 IAnnotation
    # 数组；旧版/动态代理仍可能只有 InsertModelAnnotations3。优先使用 4，
    # 再回退到 3，避免把“方法返回 True”误当成已经插入尺寸。
    # SW2024 swInsertAnnotation_e：32768=标记为工程图的模型尺寸。
    # 8 是通用尺寸类型、524288 是未标记尺寸；本机 SW2024 对二者组合静默
    # 返回 None，而 32768 会返回真实 IAnnotation 数组。
    args4 = (
        0,          # swImportModelItemsFromEntireModel
        32768,      # swInsertDimensionsMarkedForDrawing
        True, False, False, False,
        False, False,
    )
    args3 = args4[:6]
    # 官方 API 示例要求先激活一个工程图视图；未激活时 SW2024 会静默返回空结果。
    try:
        sheet = _safe_member(drawing_model, "GetCurrentSheet")
        views = _as_sequence(_safe_member(sheet, "GetViews", default=[]))
        if views:
            # 三视图第一个通常是前视图；通过对象 Name 读取失败时使用已知顺序，
            # 但仍要求 SelectByID2/ActivateView 真正返回成功。
            first_view = views[0]
            name = _safe_member(first_view, "Name", default="")
            if name:
                extension = getattr(drawing_model, "Extension", None)
                if extension is not None:
                    get_com_member(
                        extension, "SelectByID2",
                        name, "DRAWINGVIEW", 0, 0, 0, False, 0,
                        create_empty_dispatch_variant(), 0,
                    )
                get_com_member(drawing_model, "ActivateView", name)
    except Exception:
        # 激活失败仍继续尝试，让结构复核决定是否有真实尺寸证据。
        pass
    owners = (drawing_model, getattr(drawing_model, "Extension", None))
    for owner in owners:
        if owner is None:
            continue
        try:
            method4 = getattr(owner, "InsertModelAnnotations4", None)
            if method4 is not None:
                inserted = get_com_member(owner, "InsertModelAnnotations4", *args4)
                if inserted is not None:
                    return inserted
            method3 = getattr(owner, "InsertModelAnnotations3", None)
            if method3 is not None:
                return get_com_member(owner, "InsertModelAnnotations3", *args3)
        except (AttributeError, TypeError, pythoncom.com_error):
            continue
    # 新建三视图后 SW2024 有时尚未建立可导入的视图缓存；强制重建后仅重试
    # 一次。使用“标记为工程图”与消重语义，不会靠重复调用制造重复尺寸。
    try:
        get_com_member(drawing_model, "ForceRebuild3", False)
        get_com_member(drawing_model, "GraphicsRedraw2")
        for owner in owners:
            if owner is not None and getattr(owner, "InsertModelAnnotations4", None) is not None:
                inserted = get_com_member(owner, "InsertModelAnnotations4", *args4)
                if inserted is not None:
                    return inserted
    except (AttributeError, TypeError, pythoncom.com_error):
        pass
    # 调用方可以继续做结构复核，但必须把缺少真实尺寸证据显示为 warning。
    return False


def add_note(drawing_model, x, y, text):
    """
    添加注释

    参数:
        x, y: 注释位置（米）
        text: 注释文本
    """
    return drawing_model.InsertNote(text)


def insert_bom_table(drawing_model, template_path, x, y, bom_type=1, config_name=""):
    """
    插入 BOM 表

    参数:
        template_path: BOM 模板路径（.sldbomtbt）
        x, y: 表格放置位置（米）
        bom_type: 1=顶层, 2=仅零件, 3=缩进
        config_name: 配置名称
    """
    return drawing_model.InsertBomTable4(
        template_path, x, y, bom_type, config_name, "", False
    )


def set_sheet_format(drawing_model, format_path):
    """
    设置图纸格式（图框）

    参数:
        format_path: 图纸格式文件路径（.slddrt）
    """
    sheet = drawing_model.GetCurrentSheet()
    return sheet.SetTemplateName(format_path)


def add_sheet(drawing_model, paper_size=7, template_path=""):
    """
    添加新图纸

    参数:
        paper_size: 纸张大小
            0=A, 1=B, 2=C, 3=D, 4=E,
            5=A4, 6=A3, 7=A2, 8=A1, 9=A0
        template_path: 图纸格式模板路径
    """
    return drawing_model.NewSheet4(
        "", paper_size, 12, 1.0, 1.0, True, template_path, 0, 0, "", 0, 0, 0, 0, 0, 0
    )


def get_all_views(drawing_model):
    """获取当前图纸上的所有视图"""
    sheet = get_com_member(drawing_model, "GetCurrentSheet")
    views = get_com_member(sheet, "GetViews")
    result = []
    if views:
        for view in views:
            result.append({
                "name": view.Name,
                "type": view.Type,
                "scale": view.ScaleRatio,
            })
    return result


def inspect_drawing_structure(drawing_model) -> dict:
    """@brief 读取工程图结构并返回可审计报告，不修改文档。"""
    sheets = _as_sequence(_safe_member(drawing_model, "GetSheetNames", default=[]))
    if not sheets:
        current_sheet = _safe_member(drawing_model, "GetCurrentSheet")
        current_name = _safe_member(current_sheet, "GetName", default="")
        if current_name:
            sheets = [current_name]
    views = []
    dimensions = []
    notes = []
    tables = []
    for sheet_name in sheets or [""]:
        sheet = _safe_member(drawing_model, "GetSheet", sheet_name) or _safe_member(drawing_model, "GetCurrentSheet")
        for view in _as_sequence(_safe_member(sheet, "GetViews", default=[])):
            views.append({
                "sheet": str(sheet_name),
                "name": _safe_member(view, "Name", default=""),
                "type": _safe_member(view, "Type", default=None),
                "scale": _safe_member(view, "ScaleRatio", default=None),
            })
            view_dimensions = _as_sequence(_safe_member(view, "GetDisplayDimensions", default=[]))
            if not view_dimensions:
                current = _safe_member(view, "GetFirstDisplayDimension5") or _safe_member(view, "GetFirstDisplayDimension")
                while current is not None:
                    view_dimensions.append(current)
                    current = _safe_member(view, "GetNextDisplayDimension", current)
            for dimension in view_dimensions:
                dimensions.append({
                    "sheet": str(sheet_name),
                    "view": _safe_member(view, "Name", default=""),
                    "name": _safe_member(dimension, "Name", default=""),
                    "type": _safe_member(dimension, "Type", default=None),
                    "text": _safe_member(dimension, "GetText", 0, default=""),
                })
            for note in _as_sequence(_safe_member(view, "GetNotes", default=[])):
                notes.append({"sheet": str(sheet_name), "text": _safe_member(note, "Text", default="")})
            for table in _as_sequence(_safe_member(view, "GetTableAnnotations", default=[])):
                tables.append({"sheet": str(sheet_name), "type": _safe_member(table, "Type", default=None)})
    current_sheet = _safe_member(drawing_model, "GetCurrentSheet")
    template = _safe_member(current_sheet, "GetTemplateName", default="")
    result = {
        "status": "pass" if views else "blocked",
        "stage": "review",
        "sheets": [str(item) for item in sheets],
        "views": views,
        "dimensions": dimensions,
        "notes": notes,
        "tables": tables,
        "template_path": str(template or ""),
        "view_count": len(views),
        "dimension_count": len(dimensions),
        "table_count": len(tables),
        "manual_review_required": True,
        "retryable": not bool(views),
        "error_code": None if views else "DRAWING_VIEWS_MISSING",
        "checks": [
            {"id": "drawing-views", "status": "pass" if views else "fail", "message": "工程图包含视图" if views else "未读取到工程图视图"},
            {"id": "drawing-template", "status": "pass" if template else "warning", "message": "已读取图框模板" if template else "图框模板需要人工确认"},
            {"id": "drawing-dimensions", "status": "pass" if dimensions else "warning", "message": "已读取真实尺寸实体" if dimensions else "未读取到尺寸实体"},
        ],
    }
    return result


def export_sheet_to_pdf(model, output_path, sheet_names=None, sw_app=None):
    """
    将工程图导出为 PDF

    参数:
        model: IModelDoc2（工程图文档）
        output_path: 输出 PDF 路径
        sheet_names: 图纸名称列表，None=所有图纸
        sw_app: 可选的 SldWorks.Application 对象；传入会话对象可避免 SW2024
            动态 IModelDoc2 未暴露 GetSldWorksObject 的兼容性问题。
    """
    sw = sw_app
    if sw is None:
        for prog_id in ("SldWorks.Application.32", "SldWorks.Application"):
            try:
                sw = _win32com.GetActiveObject(prog_id)
                break
            except Exception:
                continue
    if sw is None:
        return False
    try:
        pdf_data = get_com_member(sw, "GetExportFileData", 1)  # 1 = swExportPDFData
    except Exception:
        return False

    if sheet_names is None:
        drawing = model
        sheet_names = get_com_member(drawing, "GetSheetNames")

    try:
        pdf_data.SetSheets(0, sheet_names)  # 0 = swExportData_ExportSpecifiedSheets
    except Exception:
        return False

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    if success:
        print(f"PDF 导出成功: {output_path}")
    else:
        print(f"PDF 导出失败, 错误码: {errors.value}")
    return success
