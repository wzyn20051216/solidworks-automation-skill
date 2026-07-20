"""
SolidWorks 友好会话 API

本模块在底层 COM helper 之上提供更顺手的门面接口，适合脚本和 AI 代理快速组合
“打开/新建/保存/导出/关闭”等常见流程。底层函数仍保留在 sw_connect.py、
sw_part.py、sw_export.py 等模块中，便于精细控制。
"""
from pathlib import Path
import os

try:
    from .sw_connect import connect_solidworks, get_com_member, new_document, open_document, save_document
    from .sw_export import export_to_dxf, export_to_iges, export_to_pdf, export_to_stl, export_to_step
except ImportError:
    from sw_connect import connect_solidworks, get_com_member, new_document, open_document, save_document
    from sw_export import export_to_dxf, export_to_iges, export_to_pdf, export_to_stl, export_to_step


EXPORTERS = {
    ".step": export_to_step,
    ".stp": export_to_step,
    ".stl": export_to_stl,
    ".iges": export_to_iges,
    ".igs": export_to_iges,
    ".pdf": export_to_pdf,
    ".dxf": export_to_dxf,
    ".dwg": export_to_dxf,
}


class SolidWorksSession:
    """
    SolidWorks 自动化会话。

    示例:
        session = SolidWorksSession()
        model = session.new_part()
        session.save(model, r"C:\\temp\\part.sldprt")
        session.export(model, r"C:\\temp\\part.step")
    """

    def __init__(self, version=None, wait_seconds=5, visible=True):
        """
        初始化并连接 SolidWorks。

        参数:
            version: SolidWorks 年份，例如 2024；None 表示自动连接默认 ProgID。
            wait_seconds: 新启动实例后的等待秒数。
            visible: 新启动实例是否显示窗口。
        """
        self.sw, self.model = connect_solidworks(
            version=version,
            wait_seconds=wait_seconds,
            visible=visible,
        )

    @property
    def active_doc(self):
        """返回当前活动文档并同步到 session.model。"""
        self.model = self.sw.ActiveDoc
        return self.model

    def new(self, doc_type="part", template_path=None):
        """
        新建文档。

        参数:
            doc_type: "part"、"assembly"、"drawing" 或常见扩展名。
            template_path: 指定模板路径；None 表示自动查找模板。
        """
        self.model = new_document(self.sw, doc_type=doc_type, template_path=template_path)
        return self.model

    def new_part(self, template_path=None):
        """新建零件文档。"""
        return self.new("part", template_path=template_path)

    def new_assembly(self, template_path=None):
        """新建装配体文档。"""
        return self.new("assembly", template_path=template_path)

    def new_drawing(self, template_path=None):
        """新建工程图文档。"""
        return self.new("drawing", template_path=template_path)

    def open(self, file_path, read_only=False, silent=False, raise_on_error=True):
        """
        打开文档。

        参数:
            file_path: SolidWorks 文件或中间格式文件路径。
            read_only: 是否只读打开。
            silent: 是否静默打开。
            raise_on_error: 打开失败时是否抛出异常。
        """
        self.model = open_document(
            self.sw,
            file_path,
            read_only=read_only,
            silent=silent,
            raise_on_error=raise_on_error,
        )
        return self.model

    def save(self, model=None, file_path=None):
        """
        保存文档。

        参数:
            model: 指定文档；None 表示当前活动文档。
            file_path: 另存为路径；None 表示保存到当前位置。
        """
        model = model or self.active_doc
        if model is None:
            raise RuntimeError("当前没有可保存的活动文档")
        return save_document(model, file_path=file_path)

    def export(self, model=None, output_path=None, format_ext=None, **kwargs):
        """
        按输出扩展名导出文档。

        参数:
            model: 指定文档；None 表示当前活动文档。
            output_path: 输出文件路径。
            format_ext: 显式格式扩展名；None 表示从 output_path 推断。
            **kwargs: 传给具体导出函数的附加参数，例如 STL quality。
        """
        model = model or self.active_doc
        if model is None:
            raise RuntimeError("当前没有可导出的活动文档")
        if not output_path:
            raise ValueError("必须提供 output_path")

        output = Path(os.path.expandvars(str(output_path))).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        ext = (format_ext or output.suffix).lower()
        if not ext.startswith("."):
            ext = f".{ext}"

        exporter = EXPORTERS.get(ext)
        if exporter is None:
            raise ValueError(f"暂不支持导出格式: {ext}")
        return exporter(model, str(output), **kwargs)

    def close(self, model=None, title=None):
        """
        关闭文档。

        参数:
            model: 指定文档；None 表示按 title 或当前活动文档关闭。
            title: 文档标题；适合关闭已知标题的文档。
        """
        if title is None:
            model = model or self.active_doc
            if model is None:
                return False
            title = get_com_member(model, "GetTitle")
        is_current_model = False
        if self.model:
            try:
                is_current_model = get_com_member(self.model, "GetTitle") == title
            except Exception:
                is_current_model = True
        self.sw.CloseDoc(title)
        if is_current_model:
            self.model = self.sw.ActiveDoc
        return True


def session(version=None, wait_seconds=5, visible=True):
    """
    创建 SolidWorksSession 的便捷函数。

    参数同 SolidWorksSession。
    """
    return SolidWorksSession(version=version, wait_seconds=wait_seconds, visible=visible)
