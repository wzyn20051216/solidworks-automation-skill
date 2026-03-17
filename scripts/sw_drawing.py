"""
SolidWorks 工程图操作工具
"""
import win32com.client
import pythoncom
from win32com.client import VARIANT


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
    return drawing_model.Extension.InsertModelAnnotations3(
        0,  # swImportModelItemsFromEntireModel
        32, # swInsertDimensionsMarkedForDrawing
        True, True, False, False
    )


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
    sheet = drawing_model.GetCurrentSheet()
    views = sheet.GetViews()
    result = []
    if views:
        for view in views:
            result.append({
                "name": view.Name,
                "type": view.Type,
                "scale": view.ScaleRatio,
            })
    return result


def export_sheet_to_pdf(model, output_path, sheet_names=None):
    """
    将工程图导出为 PDF

    参数:
        model: IModelDoc2（工程图文档）
        output_path: 输出 PDF 路径
        sheet_names: 图纸名称列表，None=所有图纸
    """
    sw = model.GetSldWorksObject()
    pdf_data = sw.GetExportFileData(1)  # 1 = swExportPDFData

    if sheet_names is None:
        drawing = model
        sheet_names = drawing.GetSheetNames()

    pdf_data.SetSheets(0, sheet_names)  # 0 = swExportData_ExportSpecifiedSheets

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    if success:
        print(f"PDF 导出成功: {output_path}")
    else:
        print(f"PDF 导出失败, 错误码: {errors.value}")
    return success
