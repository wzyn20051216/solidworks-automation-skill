"""
SolidWorks 连接工具
提供连接到 SolidWorks 实例的各种方法
"""
import win32com.client
import pythoncom
from win32com.client import VARIANT
import time
import os
import glob


def connect_solidworks(version=None, wait_seconds=5):
    """
    连接到 SolidWorks 实例

    参数:
        version: SolidWorks 版本年份（如 2024），None 则自动检测
        wait_seconds: 启动新实例后等待秒数

    返回:
        (sw, model) 元组，model 可能为 None（无打开的文档时）
    """
    sw = None

    # 优先连接已运行的实例
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
        print("已连接到运行中的 SolidWorks 实例")
    except Exception:
        # 启动新实例
        prog_id = "SldWorks.Application"
        if version:
            revision = (version - 2000) + 8
            prog_id = f"SldWorks.Application.{revision}"

        sw = win32com.client.Dispatch(prog_id)
        sw.Visible = True
        print(f"启动了新的 SolidWorks 实例（ProgID: {prog_id}）")
        time.sleep(wait_seconds)

    # 获取当前活动文档
    model = sw.ActiveDoc
    if model:
        doc_types = {1: "零件", 2: "装配体", 3: "工程图"}
        doc_type = model.GetType()
        print(f"当前文档: {model.GetTitle()} (类型: {doc_types.get(doc_type, '未知')})")
    else:
        print("当前没有打开的文档")

    return sw, model


def get_sw_version(sw):
    """获取 SolidWorks 版本信息"""
    rev = sw.RevisionNumber()
    major = int(rev.split(".")[0])
    year = major - 8 + 2000
    return {"revision": rev, "year": year, "major": major}


def find_template(sw, doc_type="part"):
    """
    自动查找 SolidWorks 文档模板

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"

    返回:
        模板文件路径字符串
    """
    # 从 SolidWorks 设置获取默认模板
    type_map = {
        "part": (sw.GetUserPreferenceStringValue(24), "*.prtdot"),
        "assembly": (sw.GetUserPreferenceStringValue(25), "*.asmdot"),
        "drawing": (sw.GetUserPreferenceStringValue(26), "*.drwdot"),
    }

    default_path, pattern = type_map.get(doc_type, type_map["part"])
    if default_path and os.path.exists(default_path):
        return default_path

    # 搜索常见模板目录
    search_dirs = [
        r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\chinese-simplified",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english",
    ]
    for search_dir in search_dirs:
        matches = glob.glob(os.path.join(search_dir, pattern))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"无法找到 {doc_type} 模板文件，请手动指定路径")


def new_document(sw, doc_type="part", template_path=None):
    """
    创建新文档

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"
        template_path: 模板路径，None 则自动查找

    返回:
        新建的 IModelDoc2 对象
    """
    if not template_path:
        template_path = find_template(sw, doc_type)

    type_enum = {"part": 1, "assembly": 2, "drawing": 3}
    sw.NewDocument(template_path, 0, 0, 0)
    model = sw.ActiveDoc
    print(f"已创建新{{'part': '零件', 'assembly': '装配体', 'drawing': '工程图'}[doc_type]}文档")
    return model


def open_document(sw, file_path, read_only=False):
    """
    打开已有文档

    参数:
        sw: SolidWorks 应用对象
        file_path: 文件完整路径
        read_only: 是否以只读模式打开

    返回:
        IModelDoc2 对象
    """
    ext = os.path.splitext(file_path)[1].lower()
    type_map = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3, ".step": 1, ".stp": 1, ".igs": 1, ".iges": 1}
    doc_type = type_map.get(ext, 1)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    options = 2 if read_only else 0  # swOpenDocOptions_ReadOnly = 2

    model = sw.OpenDoc6(file_path, doc_type, options, "", errors, warnings)
    if model:
        print(f"已打开: {file_path}")
    else:
        print(f"打开失败, 错误码: {errors.value}")
    return model


def save_document(model, file_path=None):
    """
    保存文档

    参数:
        model: IModelDoc2 对象
        file_path: 另存为路径，None 则保存到当前位置

    返回:
        bool 成功/失败
    """
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    if file_path:
        success = model.Extension.SaveAs(file_path, 0, 1, None, errors, warnings)
    else:
        success = model.Save3(1, errors, warnings)

    if success:
        print(f"保存成功: {file_path or model.GetPathName()}")
    else:
        print(f"保存失败, 错误码: {errors.value}, 警告码: {warnings.value}")
    return bool(success)


def mm(value):
    """毫米转米（SolidWorks API 单位）"""
    return value / 1000.0


def deg(value):
    """角度转弧度"""
    import math
    return value * math.pi / 180.0
