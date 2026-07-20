"""
SolidWorks 连接工具
提供连接到 SolidWorks 实例的各种方法
"""
import glob
import os
import time

try:
    from .sw_preflight import ensure_solidworks_installed, import_com_dependencies
except ImportError:
    from sw_preflight import ensure_solidworks_installed, import_com_dependencies

pythoncom, win32com_client, VARIANT = import_com_dependencies()


DOC_TYPE_MAP = {
    "part": 1,
    "prt": 1,
    "sldprt": 1,
    "assembly": 2,
    "asm": 2,
    "sldasm": 2,
    "drawing": 3,
    "drw": 3,
    "slddrw": 3,
}

DOC_TYPE_LABELS = {
    "part": "零件",
    "assembly": "装配体",
    "drawing": "工程图",
}

DEFAULT_TEMPLATE_PREFS = {
    "part": 8,       # swUserPreferenceStringValue_e.swDefaultTemplatePart
    "assembly": 9,   # swUserPreferenceStringValue_e.swDefaultTemplateAssembly
    "drawing": 10,   # swUserPreferenceStringValue_e.swDefaultTemplateDrawing
}

SW_ALWAYS_USE_DEFAULT_TEMPLATES = 111


def get_com_member(obj, attr_name, *args):
    """
    兼容 pywin32 中“同一成员在不同环境下可能是属性也可能是方法”的情况。

    参数:
        obj: COM 对象
        attr_name: 成员名称
        *args: 当成员可调用时传入的参数

    返回:
        成员值或调用结果
    """
    member = getattr(obj, attr_name)
    if args:
        return member(*args)
    try:
        return member() if callable(member) else member
    except Exception as exc:
        message = str(exc)
        if "-2147352573" in message or "找不到成员" in message or "Member not found" in message:
            return member
        raise


def safe_get_com_member(obj, attr_name, *args):
    """
    读取 COM 成员，兼容 pywin32 中伪可调用属性。

    保留该别名便于其它模块表达“安全读取”的意图；核心逻辑统一在 get_com_member。
    """
    return get_com_member(obj, attr_name, *args)


def create_empty_dispatch_variant():
    """创建可传给 COM 接口的空 Dispatch 参数。"""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def normalize_doc_type(doc_type):
    """
    规范化文档类型名称。

    参数:
        doc_type: "part"、"assembly"、"drawing" 或常见缩写/扩展名

    返回:
        (name, enum_value) 元组
    """
    key = str(doc_type).strip().lower().lstrip(".")
    enum_value = DOC_TYPE_MAP.get(key)
    if enum_value is None:
        raise ValueError(f"未知文档类型: {doc_type}")

    name_map = {1: "part", 2: "assembly", 3: "drawing"}
    return name_map[enum_value], enum_value


def _expand_path(file_path):
    """展开用户目录和环境变量，并返回绝对路径。"""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(file_path)))


def _ensure_parent_dir(file_path):
    """确保输出文件的父目录存在。"""
    parent = os.path.dirname(_expand_path(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def connect_solidworks(version=None, wait_seconds=5, visible=True):
    """
    连接到 SolidWorks 实例。

    参数:
        version: SolidWorks 版本年份（如 2024），None 则自动检测
        wait_seconds: 启动新实例后等待秒数
        visible: 启动新实例后是否显示窗口

    返回:
        (sw, model) 元组，model 可能为 None（无打开的文档时）
    """
    ensure_solidworks_installed()
    sw = None

    # 优先连接已运行的实例。
    try:
        sw = win32com_client.GetActiveObject("SldWorks.Application")
        print("已连接到运行中的 SolidWorks 实例")
    except Exception:
        prog_id = "SldWorks.Application"
        if version:
            revision = (version - 2000) + 8
            prog_id = f"SldWorks.Application.{revision}"

        sw = win32com_client.Dispatch(prog_id)
        sw.Visible = visible
        print(f"启动了新的 SolidWorks 实例（ProgID: {prog_id}）")
        time.sleep(wait_seconds)

    model = sw.ActiveDoc
    if model:
        doc_types = {1: "零件", 2: "装配体", 3: "工程图"}
        doc_type = get_com_member(model, "GetType")
        title = get_com_member(model, "GetTitle")
        print(f"当前文档: {title} (类型: {doc_types.get(doc_type, '未知')})")
    else:
        print("当前没有打开的文档")

    return sw, model


def get_sw_version(sw):
    """获取 SolidWorks 版本信息。"""
    rev = get_com_member(sw, "RevisionNumber")
    major = int(rev.split(".")[0])
    year = major - 8 + 2000
    return {"revision": rev, "year": year, "major": major}


def find_template(sw, doc_type="part"):
    """
    自动查找 SolidWorks 文档模板。

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"

    返回:
        模板文件路径字符串
    """
    doc_type, _ = normalize_doc_type(doc_type)

    type_map = {
        "part": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["part"]), "*.prtdot"),
        "assembly": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["assembly"]), "*.asmdot"),
        "drawing": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["drawing"]), "*.drwdot"),
    }

    default_path, pattern = type_map.get(doc_type, type_map["part"])
    if default_path:
        for candidate_root in str(default_path).split(";"):
            candidate_root = _expand_path(candidate_root.strip().strip('"'))
            if not candidate_root:
                continue

            if os.path.isfile(candidate_root):
                return candidate_root

            if os.path.isdir(candidate_root):
                matches = glob.glob(os.path.join(candidate_root, pattern))
                if matches:
                    return matches[0]

    search_dirs = [
        r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\chinese-simplified",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english",
    ]
    for search_dir in search_dirs:
        matches = glob.glob(os.path.join(os.path.expandvars(search_dir), pattern))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"无法找到 {doc_type} 模板文件，请手动指定路径")


def ensure_default_templates(sw):
    """
    @brief 配置默认模板并关闭新建文件模板选择提示。
    @param sw SolidWorks 应用对象。
    @return 字典，包含已确认的默认模板路径。
    """
    templates = {}
    for doc_type, preference in DEFAULT_TEMPLATE_PREFS.items():
        template_path = find_template(sw, doc_type)
        templates[doc_type] = template_path
        current_path = str(sw.GetUserPreferenceStringValue(preference) or "")
        if _expand_path(current_path) != _expand_path(template_path):
            sw.SetUserPreferenceStringValue(preference, template_path)
    try:
        sw.SetUserPreferenceToggle(SW_ALWAYS_USE_DEFAULT_TEMPLATES, True)
    except Exception as exc:
        print(f"提示: 无法设置始终使用默认模板: {exc}")
    return templates


def new_document(sw, doc_type="part", template_path=None):
    """
    创建新文档。

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"
        template_path: 模板路径，None 则自动查找

    返回:
        新建的 IModelDoc2 对象
    """
    doc_type, _ = normalize_doc_type(doc_type)
    if not template_path:
        template_path = find_template(sw, doc_type)
    else:
        template_path = _expand_path(template_path)

    model = sw.NewDocument(template_path, 0, 0, 0)
    if model is None:
        for _ in range(20):
            model = sw.ActiveDoc
            if model is not None:
                break
            time.sleep(0.25)

    if model is None:
        raise RuntimeError(f"创建{DOC_TYPE_LABELS.get(doc_type, doc_type)}文档失败，SolidWorks 未返回活动文档")

    print(f"已创建新{DOC_TYPE_LABELS.get(doc_type, doc_type)}文档")
    return model


def open_document(sw, file_path, read_only=False, silent=False, raise_on_error=False):
    """
    打开已有文档。

    参数:
        sw: SolidWorks 应用对象
        file_path: 文件完整路径
        read_only: 是否以只读模式打开
        silent: 是否静默打开
        raise_on_error: 打开失败时是否抛出异常

    返回:
        IModelDoc2 对象
    """
    file_path = _expand_path(file_path)
    if not os.path.exists(file_path):
        message = f"文件不存在: {file_path}"
        if raise_on_error:
            raise FileNotFoundError(message)
        print(message)
        return None

    ext = os.path.splitext(file_path)[1].lower()
    foreign_exts = {".step", ".stp", ".igs", ".iges"}
    type_map = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    options = 2 if read_only else 0  # swOpenDocOptions_ReadOnly = 2
    if silent:
        options |= 1  # swOpenDocOptions_Silent = 1

    if ext in foreign_exts:
        if read_only:
            print("提示: LoadFile4 导入外来 CAD 文件时不支持 read_only，已忽略该参数")
        if silent:
            print("提示: LoadFile4 导入外来 CAD 文件时不支持 OpenDoc6 silent 选项，已忽略该参数")
        ensure_default_templates(sw)
        import_data = sw.GetImportFileData(file_path)
        if import_data is None:
            message = f"获取导入数据失败: {file_path}"
            if raise_on_error:
                raise RuntimeError(message)
            print(message)
            return None
        # 非 DXF/DWG、非 Pro/E 外来文件应传 "r"，表示导入为新的 SolidWorks 文档；
        # 空字符串会在部分 SW2024 环境中弹出模板选择对话框并阻塞自动化。
        model = sw.LoadFile4(file_path, "r", import_data, errors)
        warnings.value = 0
    else:
        doc_type = type_map.get(ext, 1)
        model = sw.OpenDoc6(file_path, doc_type, options, "", errors, warnings)
    if model:
        print(f"已打开: {file_path}")
    else:
        message = f"打开失败, 错误码: {errors.value}, 警告码: {warnings.value}"
        if raise_on_error:
            raise RuntimeError(message)
        print(message)
    return model


def save_document(model, file_path=None):
    """
    保存文档。

    参数:
        model: IModelDoc2 对象
        file_path: 另存为路径，None 则保存到当前位置

    返回:
        bool 成功/失败
    """
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    if file_path:
        file_path = _expand_path(file_path)
        _ensure_parent_dir(file_path)
        success = model.Extension.SaveAs(
            file_path, 0, 1, create_empty_dispatch_variant(), errors, warnings
        )
    else:
        success = model.Save3(1, errors, warnings)

    if success:
        print(f"保存成功: {file_path or get_com_member(model, 'GetPathName')}")
    else:
        print(f"保存失败, 错误码: {errors.value}, 警告码: {warnings.value}")
    return bool(success)


def mm(value):
    """毫米转米（SolidWorks API 单位）。"""
    return value / 1000.0


def deg(value):
    """角度转弧度。"""
    import math
    return value * math.pi / 180.0
