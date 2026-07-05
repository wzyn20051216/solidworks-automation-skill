# -*- coding: utf-8 -*-
"""@file acad_session.py
@brief AutoCAD COM 会话与常用绘图封装。

这些封装保持薄而透明，方便在官方文档和本机实测之间定位问题。
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence, Tuple

try:
    import pythoncom
    import win32com.client
except Exception as exc:  # pragma: no cover - 依赖环境相关
    pythoncom = None  # type: ignore[assignment]
    win32com = None  # type: ignore[assignment]
    _IMPORT_ERROR: Optional[BaseException] = exc
else:
    _IMPORT_ERROR = None


PointLike = Sequence[float]


def require_pywin32() -> None:
    """@brief 确认 pywin32 可用。"""
    if _IMPORT_ERROR is not None:
        raise RuntimeError("缺少 pywin32，请先执行: python -m pip install pywin32") from _IMPORT_ERROR


def mm(value: float) -> float:
    """@brief AutoCAD 数据库为无单位数值；默认约定 1 数值 = 1 mm。"""
    return float(value)


def acad_point(values: PointLike) -> Any:
    """@brief 转换为 AutoCAD COM 需要的三维点数组。

    @param values 二维或三维坐标。
    @return COM VARIANT 数组。
    """
    require_pywin32()
    xyz = list(values)
    if len(xyz) == 2:
        xyz.append(0.0)
    if len(xyz) != 3:
        raise ValueError(f"AutoCAD 点必须是 2 或 3 个数值: {values!r}")
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(float(v) for v in xyz))


def acad_double_array(values: Iterable[float]) -> Any:
    """@brief 转换为 AutoCAD COM 双精度数组。"""
    require_pywin32()
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        tuple(float(v) for v in values),
    )


def connect_autocad(create_if_missing: bool = True, visible: bool = True) -> Any:
    """@brief 连接或启动 AutoCAD。

    @param create_if_missing 找不到运行实例时是否启动 AutoCAD。
    @param visible 是否显示 AutoCAD 窗口。
    @return AutoCAD Application COM 对象。
    """
    require_pywin32()
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        if not create_if_missing:
            raise
        app = win32com.client.Dispatch("AutoCAD.Application")
    try:
        app.Visible = visible
    except Exception:
        pass
    return app


class AutoCADSession:
    """@brief 管理 AutoCAD COM 会话。"""

    def __init__(self, create_if_missing: bool = True, visible: bool = True) -> None:
        self.create_if_missing = create_if_missing
        self.visible = visible
        self.app: Any = None
        self.doc: Any = None

    def connect(self) -> "AutoCADSession":
        """@brief 连接 AutoCAD，并尝试绑定活动文档。"""
        self.app = connect_autocad(self.create_if_missing, self.visible)
        self.ensure_visible()
        try:
            self.doc = self.app.ActiveDocument
        except Exception:
            self.doc = None
        return self

    def active_document(self) -> Any:
        """@brief 返回活动文档；无活动文档时报错。"""
        if self.doc is not None:
            return self.doc
        if self.app is None:
            self.connect()
        try:
            self.doc = self.app.ActiveDocument
        except Exception as exc:
            raise RuntimeError("AutoCAD 当前没有活动文档，请先 new_document() 或 open_document()。") from exc
        return self.doc

    def _documents_collection(self) -> Any:
        """@brief 获取稳定的 Documents 集合代理。"""
        if self.app is None:
            self.connect()
        last_error: Optional[Exception] = None
        for _ in range(20):
            try:
                documents = self.app.Documents
                _ = documents.Count
                return documents
            except Exception as exc:
                last_error = exc
                time.sleep(0.2)
        if last_error is not None:
            raise RuntimeError("AutoCAD Documents 集合当前不可用。") from last_error
        raise RuntimeError("AutoCAD Documents 集合当前不可用。")

    def new_document(self, template: Optional[str] = None) -> Any:
        """@brief 新建 DWG 文档。"""
        if self.app is None:
            self.connect()
        documents = self._documents_collection()
        if template:
            documents.Add(str(template))
        else:
            documents.Add()
        # AutoCAD 刚启动或刚新建图纸时，ActiveDocument 可能短暂返回不稳定代理；
        # 这里做一次小范围重试，并回退到 Documents 集合中的最后一张图。
        last_error: Optional[Exception] = None
        for _ in range(20):
            try:
                self.doc = self.app.ActiveDocument
                _ = self.doc.Name
                return self.doc
            except Exception as exc:
                last_error = exc
            try:
                self.doc = documents.Item(documents.Count - 1)
                _ = self.doc.Name
                return self.doc
            except Exception as exc:
                last_error = exc
            time.sleep(0.2)
        if last_error is not None:
            raise RuntimeError("AutoCAD 新建文档后未能取得稳定文档对象。") from last_error
        return self.doc

    def open_document(self, path: str | Path, read_only: bool = False) -> Any:
        """@brief 打开 DWG/DXF 文档。"""
        if self.app is None:
            self.connect()
        target = Path(path).resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        last_error: Optional[Exception] = None
        for _ in range(20):
            documents = self._documents_collection()
            try:
                self.doc = documents.Open(str(target), bool(read_only))
                _ = self.doc.Name
                return self.doc
            except Exception as exc:
                last_error = exc
                time.sleep(0.2)
        if last_error is not None:
            raise RuntimeError(f"AutoCAD 打开文档失败: {target}") from last_error
        return self.doc

    def ensure_visible(self) -> None:
        """@brief 确保 AutoCAD 窗口可见。"""
        if self.app is None:
            self.connect()
        try:
            self.app.Visible = True
        except Exception:
            pass

    def activate_window(self) -> None:
        """@brief 尝试把 AutoCAD 主窗口切到前台，便于用户观看绘图过程。"""
        if self.app is None:
            self.connect()
        try:
            hwnd = int(self.app.HWND)
        except Exception:
            return
        try:
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 3)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    @property
    def model(self) -> Any:
        """@brief 当前文档 ModelSpace。"""
        return self.active_document().ModelSpace

    def create_layer(self, name: str, color: Optional[int] = None, linetype: Optional[str] = None) -> Any:
        """@brief 创建或获取图层。

        @param name 图层名。
        @param color AutoCAD ACI 颜色编号。
        @param linetype 线型名称。
        """
        doc = self.active_document()
        layers = doc.Layers
        try:
            layer = layers.Item(name)
        except Exception:
            layer = layers.Add(name)
        if color is not None:
            layer.Color = int(color)
        if linetype:
            try:
                doc.Linetypes.Load(linetype, "acad.lin")
            except Exception:
                pass
            layer.Linetype = linetype
        return layer

    def set_current_layer(self, name: str) -> None:
        """@brief 设置当前图层。"""
        self.active_document().ActiveLayer = self.create_layer(name)

    def _apply_entity_options(self, entity: Any, layer: Optional[str] = None, color: Optional[int] = None) -> Any:
        """@brief 应用常用实体属性。"""
        if layer:
            self.create_layer(layer)
            entity.Layer = layer
        if color is not None:
            entity.Color = int(color)
        return entity

    def add_line(self, start: PointLike, end: PointLike, layer: Optional[str] = None, color: Optional[int] = None) -> Any:
        """@brief 添加直线。"""
        entity = self.model.AddLine(acad_point(start), acad_point(end))
        return self._apply_entity_options(entity, layer, color)

    def add_circle(
        self,
        center: PointLike,
        radius: float,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 添加圆。"""
        entity = self.model.AddCircle(acad_point(center), float(radius))
        return self._apply_entity_options(entity, layer, color)

    def add_lwpolyline(
        self,
        points: Sequence[Sequence[float]],
        closed: bool = False,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 添加二维轻量多段线。"""
        if len(points) < 2:
            raise ValueError("多段线至少需要两个点。")
        flat = []
        for point in points:
            if len(point) < 2:
                raise ValueError(f"二维多段线点至少需要 x/y: {point!r}")
            flat.extend([float(point[0]), float(point[1])])
        entity = self.model.AddLightWeightPolyline(acad_double_array(flat))
        entity.Closed = bool(closed)
        return self._apply_entity_options(entity, layer, color)

    def add_rectangle(
        self,
        origin: Sequence[float],
        width: float,
        height: float,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 以左下角、宽、高添加闭合矩形。"""
        x = float(origin[0])
        y = float(origin[1])
        w = float(width)
        h = float(height)
        return self.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
            closed=True,
            layer=layer,
            color=color,
        )

    def add_text(
        self,
        text: str,
        point: PointLike,
        height: float,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 添加单行文字。"""
        entity = self.model.AddText(str(text), acad_point(point), float(height))
        return self._apply_entity_options(entity, layer, color)

    def add_mtext(
        self,
        text: str,
        point: PointLike,
        width: float,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 添加多行文字。"""
        entity = self.model.AddMText(acad_point(point), float(width), str(text))
        return self._apply_entity_options(entity, layer, color)

    def send_command(self, command: str) -> None:
        """@brief 向 AutoCAD 命令行发送命令。

        命令可能异步执行，调用后必须保存并复核结果。
        """
        if not command.endswith("\n"):
            command += "\n"
        self.active_document().SendCommand(command)

    def regen(self) -> None:
        """@brief 重生成当前文档。"""
        self.active_document().Regen(1)

    def zoom_extents(self) -> None:
        """@brief 缩放到全图。"""
        if self.app is None:
            self.connect()
        self.app.ZoomExtents()

    def live_update(self, step_delay_s: float = 0.0, zoom: bool = False) -> None:
        """@brief 刷新并短暂停顿，让 AutoCAD 绘图过程对用户可见。

        @param step_delay_s 每一步后的停顿秒数。
        @param zoom 是否在刷新时执行 ZoomExtents。
        """
        self.ensure_visible()
        self.activate_window()
        self.regen()
        if zoom:
            self.zoom_extents()
        if step_delay_s > 0:
            time.sleep(step_delay_s)

    def iter_model_entities(self) -> Iterator[Any]:
        """@brief 遍历 ModelSpace 实体。"""
        for entity in self.model:
            yield entity

    def save_as(self, path: str | Path) -> Path:
        """@brief 保存当前图纸。

        @return 保存后的绝对路径。
        """
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.active_document().SaveAs(str(target))
        return target

    def delete_selection_set(self, name: str) -> None:
        """@brief 删除同名 SelectionSet，若不存在则忽略。"""
        doc = self.active_document()
        try:
            doc.SelectionSets.Item(name).Delete()
        except Exception:
            pass

    def create_empty_selection_set(self, name: str) -> Any:
        """@brief 创建空 SelectionSet。

        DXF/EPS 导出会忽略选择集内容，但 ActiveX Export 方法仍要求传入
        SelectionSet 参数。
        """
        doc = self.active_document()
        self.delete_selection_set(name)
        return doc.SelectionSets.Add(name)

    def export_dxf(self, path: str | Path, selection_set_name: str = "CODEX_EMPTY_EXPORT_SET") -> Path:
        """@brief 使用 Document.Export 导出整张图为 DXF。

        @param path 目标 DXF 文件路径。
        @param selection_set_name 临时 SelectionSet 名称。
        @return 导出的 DXF 绝对路径。
        """
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()

        sset = self.create_empty_selection_set(selection_set_name)
        export_base = str(target.with_suffix(""))
        try:
            self.active_document().Export(export_base, "DXF", sset)
        finally:
            try:
                sset.Delete()
            except Exception:
                pass
        return target

    def export_bmp_preview(self, path: str | Path, selection_set_name: str = "CODEX_PREVIEW_SET") -> Path:
        """@brief 使用 AutoCAD 原生 Export 导出整张图的 BMP 预览。

        @param path 目标 BMP 文件路径。
        @param selection_set_name 临时 SelectionSet 名称。
        @return 导出的 BMP 绝对路径。
        """
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()

        self.regen()
        self.zoom_extents()
        sset = self.create_empty_selection_set(selection_set_name)
        try:
            # 5 是 AutoCAD ActiveX 的 acSelectionSetAll；用于把全图对象交给 Export。
            sset.Select(5)
            self.active_document().Export(str(target.with_suffix("")), "BMP", sset)
        finally:
            try:
                sset.Delete()
            except Exception:
                pass
        return target

    def close_document(self, save_changes: bool = False) -> None:
        """@brief 关闭当前文档。"""
        if self.doc is not None:
            self.doc.Close(bool(save_changes))
            self.doc = None


def point_tuple(value: Any) -> Tuple[float, float, float]:
    """@brief 将 COM 点转换为 Python 三元组。"""
    items = list(value)
    if len(items) == 2:
        items.append(0.0)
    return (float(items[0]), float(items[1]), float(items[2]))
