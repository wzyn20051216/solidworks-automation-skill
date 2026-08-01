# -*- coding: utf-8 -*-
"""@file acad_session.py
@brief AutoCAD COM 会话与常用绘图封装。

这些封装保持薄而透明，方便在官方文档和本机实测之间定位问题。
"""

from __future__ import annotations

import ctypes
import math
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
_RETRYABLE_COM_HRESULTS = {-2147418111, -2147417846}


def _retry_com_busy(operation, label: str, attempts: int = 10) -> Any:
    """@brief 对 AutoCAD 忙碌导致的瞬时 COM 拒绝执行有限退避重试。"""
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            hresult = getattr(exc, "hresult", exc.args[0] if exc.args else None)
            if hresult not in _RETRYABLE_COM_HRESULTS:
                raise
            last_error = exc
            time.sleep(0.08 + attempt * 0.06)
    raise RuntimeError(f"AutoCAD 持续忙碌，无法完成操作: {label}") from last_error


def _window_process_id(app: Any) -> Optional[int]:
    """@brief 从 AutoCAD 主窗口句柄取得精确进程 PID。"""
    try:
        hwnd = int(app.HWND)
        process_id = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value) or None
    except Exception:
        return None


def _process_is_running(process_id: int) -> bool:
    """@brief 使用 Win32 查询指定 PID 是否仍处于活动状态。"""
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(process_id))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _terminate_owned_process(process_id: int) -> bool:
    """@brief 终止已由窗口句柄确认归当前任务所有的精确 PID。"""
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(process_id))
        if not handle:
            return not _process_is_running(process_id)
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


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


def connect_autocad(
    create_if_missing: bool = True,
    visible: bool = True,
    *,
    return_ownership: bool = False,
) -> Any:
    """@brief 连接或启动 AutoCAD。

    @param create_if_missing 找不到运行实例时是否启动 AutoCAD。
    @param visible 是否显示 AutoCAD 窗口。
    @param return_ownership 是否同时返回本次调用是否启动了新实例。
    @return AutoCAD Application COM 对象。
    """
    require_pywin32()
    pythoncom.CoInitialize()
    started = False
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        if not create_if_missing:
            raise
        # Dispatch 可能重新附着到现有单例；DispatchEx 才能建立可靠的进程所有权。
        app = win32com.client.DispatchEx("AutoCAD.Application")
        started = True
    try:
        app.Visible = visible
    except Exception:
        pass
    return (app, started) if return_ownership else app


class AutoCADSession:
    """@brief 管理 AutoCAD COM 会话。"""

    def __init__(self, create_if_missing: bool = True, visible: bool = True) -> None:
        self.create_if_missing = create_if_missing
        self.visible = visible
        self.app: Any = None
        self.doc: Any = None
        self.started_by_session = False
        self.owned_process_id: Optional[int] = None
        self.forced_termination_used = False

    def connect(self) -> "AutoCADSession":
        """@brief 连接 AutoCAD，并尝试绑定活动文档。"""
        self.app, self.started_by_session = connect_autocad(
            self.create_if_missing,
            self.visible,
            return_ownership=True,
        )
        self.forced_termination_used = False
        self.ensure_visible()
        if self.started_by_session:
            for _ in range(30):
                self.owned_process_id = _window_process_id(self.app)
                if self.owned_process_id is not None:
                    break
                time.sleep(0.1)
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

    def refresh_document_proxy(self) -> Any:
        """@brief 重新绑定活动文档，绕开 AutoCAD 动态代理缓存错位。"""
        if self.app is None:
            self.connect()
        last_error: Optional[Exception] = None
        for attempt in range(8):
            try:
                document = self.app.ActiveDocument
                _ = document.Name
                self.doc = document
                return document
            except Exception as exc:
                last_error = exc
                time.sleep(0.08 + attempt * 0.04)
        if last_error is not None:
            raise RuntimeError("AutoCAD 活动文档代理刷新失败。") from last_error
        raise RuntimeError("AutoCAD 活动文档代理刷新失败。")

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
                try:
                    # AutoCAD 2024 动态代理可能隐藏 Count 和成员探测；
                    # 只要集合属性本身可取，就交给 Add/Open 调用和上层重试验证。
                    documents = self.app.Documents
                    return documents
                except Exception:
                    pass
                time.sleep(0.2)
        if last_error is not None:
            raise RuntimeError("AutoCAD Documents 集合当前不可用。") from last_error
        raise RuntimeError("AutoCAD Documents 集合当前不可用。")

    def new_document(self, template: Optional[str] = None) -> Any:
        """@brief 新建 DWG 文档。"""
        if self.app is None:
            self.connect()
        documents = self._documents_collection()
        add_error: Optional[Exception] = None
        added = False
        for attempt in range(20):
            try:
                if template:
                    documents.Add(str(template))
                else:
                    documents.Add()
                added = True
                break
            except Exception as exc:
                add_error = exc
                time.sleep(0.15 + attempt * 0.08)
        if not added:
            raise RuntimeError("AutoCAD 新建文档调用失败。") from add_error
        # AutoCAD 刚启动或刚新建图纸时，ActiveDocument 可能短暂返回不稳定代理；
        # 这里做一次小范围重试，并回退到 Documents 集合中的最后一张图。
        last_error: Optional[Exception] = None
        for _ in range(60):
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
            time.sleep(0.25)
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
        return _retry_com_busy(lambda: self.active_document().ModelSpace, "读取 ModelSpace")

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
            _retry_com_busy(lambda: layers.Add(name), f"创建图层 {name}")
            # SWIG/pywin32 可能把 Add 返回值包装为集合方法代理；必须按名称重新绑定。
            layer = _retry_com_busy(lambda: self.active_document().Layers.Item(name), f"重新绑定图层 {name}")
        if color is not None:
            _retry_com_busy(lambda: setattr(layer, "Color", int(color)), f"设置图层颜色 {name}")
        if linetype:
            try:
                _retry_com_busy(lambda: self.active_document().Linetypes.Load(linetype, "acad.lin"), f"加载线型 {linetype}")
            except Exception:
                pass
            layer = _retry_com_busy(lambda: self.active_document().Layers.Item(name), f"重新绑定图层 {name}")
            _retry_com_busy(lambda: setattr(layer, "Linetype", linetype), f"设置图层线型 {name}")
        return layer

    def set_current_layer(self, name: str) -> None:
        """@brief 设置当前图层。"""
        self.active_document().ActiveLayer = self.create_layer(name)

    def _apply_entity_options(self, entity: Any, layer: Optional[str] = None, color: Optional[int] = None) -> Any:
        """@brief 应用常用实体属性。"""
        if layer:
            _retry_com_busy(lambda: self.create_layer(layer), f"创建图层 {layer}")
            _retry_com_busy(lambda: setattr(entity, "Layer", layer), f"设置实体图层 {layer}")
        if color is not None:
            _retry_com_busy(lambda: setattr(entity, "Color", int(color)), "设置实体颜色")
        return entity

    def add_line(self, start: PointLike, end: PointLike, layer: Optional[str] = None, color: Optional[int] = None) -> Any:
        """@brief 添加直线。"""
        entity = _retry_com_busy(
            lambda: self.model.AddLine(acad_point(start), acad_point(end)),
            "创建直线",
        )
        return self._apply_entity_options(entity, layer, color)

    def add_circle(
        self,
        center: PointLike,
        radius: float,
        layer: Optional[str] = None,
        color: Optional[int] = None,
    ) -> Any:
        """@brief 添加圆。"""
        entity = _retry_com_busy(
            lambda: self.model.AddCircle(acad_point(center), float(radius)),
            "创建圆",
        )
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
        entity = _retry_com_busy(
            lambda: self.model.AddLightWeightPolyline(acad_double_array(flat)),
            "创建轻量多段线",
        )
        _retry_com_busy(lambda: setattr(entity, "Closed", bool(closed)), "设置多段线闭合状态")
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
        entity = _retry_com_busy(
            lambda: self.model.AddText(str(text), acad_point(point), float(height)),
            "创建文字",
        )
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
        entity = _retry_com_busy(
            lambda: self.model.AddMText(acad_point(point), float(width), str(text)),
            "创建多行文字",
        )
        return self._apply_entity_options(entity, layer, color)

    def add_dim_aligned(
        self,
        point1: PointLike,
        point2: PointLike,
        text_position: PointLike,
        layer: Optional[str] = "DIM",
        color: Optional[int] = None,
    ) -> Any:
        """@brief 创建真实对齐尺寸实体 AcDbAlignedDimension。"""
        entity = _retry_com_busy(
            lambda: self.model.AddDimAligned(
                acad_point(point1),
                acad_point(point2),
                acad_point(text_position),
            ),
            "创建对齐尺寸",
        )
        return self._apply_entity_options(entity, layer, color)

    def add_dim_rotated(
        self,
        point1: PointLike,
        point2: PointLike,
        dim_line_position: PointLike,
        rotation_degrees: float,
        layer: Optional[str] = "DIM",
        color: Optional[int] = None,
    ) -> Any:
        """@brief 创建真实旋转尺寸，输入角度使用工程师常用的度。"""
        entity = _retry_com_busy(
            lambda: self.model.AddDimRotated(
                acad_point(point1),
                acad_point(point2),
                acad_point(dim_line_position),
                math.radians(float(rotation_degrees)),
            ),
            "创建旋转尺寸",
        )
        return self._apply_entity_options(entity, layer, color)

    def add_dim_diametric(
        self,
        center: PointLike,
        radius: float,
        *,
        angle_degrees: float = 0.0,
        leader_length: float = 8.0,
        layer: Optional[str] = "DIM",
        color: Optional[int] = None,
    ) -> Any:
        """@brief 创建真实直径尺寸实体 AcDbDiametricDimension。"""
        xyz = list(center)
        if len(xyz) == 2:
            xyz.append(0.0)
        if len(xyz) != 3:
            raise ValueError(f"圆心必须是二维或三维点: {center!r}")
        angle = math.radians(float(angle_degrees))
        dx = math.cos(angle) * float(radius)
        dy = math.sin(angle) * float(radius)
        chord = (float(xyz[0]) + dx, float(xyz[1]) + dy, float(xyz[2]))
        far_chord = (float(xyz[0]) - dx, float(xyz[1]) - dy, float(xyz[2]))
        entity = _retry_com_busy(
            lambda: self.model.AddDimDiametric(
                acad_point(chord),
                acad_point(far_chord),
                float(leader_length),
            ),
            "创建直径尺寸",
        )
        return self._apply_entity_options(entity, layer, color)

    def send_command(self, command: str) -> None:
        """@brief 向 AutoCAD 命令行发送命令。

        命令可能异步执行，调用后必须保存并复核结果。
        """
        if not command.endswith("\n"):
            command += "\n"
        _retry_com_busy(lambda: self.active_document().SendCommand(command), "发送 AutoCAD 命令")


    def regen(self) -> None:
        """@brief 重生成当前文档。"""
        _retry_com_busy(lambda: self.active_document().Regen(1), "重生成图纸")

    def zoom_extents(self) -> None:
        """@brief 缩放到全图。"""
        if self.app is None:
            self.connect()
        _retry_com_busy(lambda: self.app.ZoomExtents(), "缩放到全图")

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
        """@brief 遍历 ModelSpace 实体，兼容不能直接枚举的动态代理。"""
        model_space = self.model
        try:
            count = int(_retry_com_busy(lambda: model_space.Count, "读取实体数量"))
        except Exception:
            yield from model_space
            return
        for index in range(count):
            yield _retry_com_busy(lambda index=index: model_space.Item(index), f"读取实体 {index}")

    def save_as(self, path: str | Path) -> Path:
        """@brief 保存当前图纸。

        @return 保存后的绝对路径。
        """
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        _retry_com_busy(lambda: self.active_document().SaveAs(str(target)), "保存 AutoCAD 图纸")
        return target

    def delete_selection_set(self, name: str) -> None:
        """@brief 删除同名 SelectionSet，若不存在则忽略。"""
        doc = self.refresh_document_proxy()
        try:
            doc.SelectionSets.Item(name).Delete()
        except Exception:
            pass

    def create_empty_selection_set(self, name: str) -> Any:
        """@brief 创建空 SelectionSet。

        DXF/EPS 导出会忽略选择集内容，但 ActiveX Export 方法仍要求传入
        SelectionSet 参数。
        """
        last_error: Optional[Exception] = None
        for attempt in range(8):
            try:
                doc = self.refresh_document_proxy()
                self.delete_selection_set(name)
                return doc.SelectionSets.Add(name)
            except Exception as exc:
                last_error = exc
                time.sleep(0.08 + attempt * 0.04)
        raise RuntimeError("AutoCAD SelectionSet 创建失败。") from last_error

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

        self.refresh_document_proxy()
        sset = self.create_empty_selection_set(selection_set_name)
        export_base = str(target.with_suffix(""))
        try:
            self.refresh_document_proxy().Export(export_base, "DXF", sset)
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
        self.refresh_document_proxy()
        sset = self.create_empty_selection_set(selection_set_name)
        try:
            # 5 是 AutoCAD ActiveX 的 acSelectionSetAll；用于把全图对象交给 Export。
            sset.Select(5)
            self.refresh_document_proxy().Export(str(target.with_suffix("")), "BMP", sset)
        finally:
            try:
                sset.Delete()
            except Exception:
                pass
        return target

    def close_document(self, save_changes: bool = False) -> None:
        """@brief 关闭当前文档。"""
        if self.doc is not None:
            last_error: Optional[Exception] = None
            for attempt in range(6):
                try:
                    self.refresh_document_proxy().Close(bool(save_changes))
                    self.doc = None
                    return
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.08 + attempt * 0.05)
            # 清理阶段不应覆盖图纸生成阶段的真实错误；调用方可继续退出。
            self.doc = None
            if last_error is not None:
                return

    def quit_owned_instance(self) -> bool:
        """@brief 仅退出由当前会话启动的 AutoCAD 实例。"""
        if self.app is None or not self.started_by_session:
            return False
        app = self.app
        process_id = self.owned_process_id
        self.doc = None
        self.app = None
        self.started_by_session = False
        self.owned_process_id = None
        try:
            _retry_com_busy(lambda: app.Quit(), "退出任务拥有的 AutoCAD")
            if process_id is not None:
                for _ in range(50):
                    if not _process_is_running(process_id):
                        return True
                    time.sleep(0.1)
                self.forced_termination_used = _terminate_owned_process(process_id)
                if self.forced_termination_used:
                    for _ in range(20):
                        if not _process_is_running(process_id):
                            return True
                        time.sleep(0.1)
                return False
            return True
        except Exception:
            return False


def point_tuple(value: Any) -> Tuple[float, float, float]:
    """@brief 将 COM 点转换为 Python 三元组。"""
    items = list(value)
    if len(items) == 2:
        items.append(0.0)
    return (float(items[0]), float(items[1]), float(items[2]))


SCRIPT_COMMANDS = {
    "zoom_extents": "_.ZOOM\n_E\n",
    "regen": "_.REGEN\n",
    "qsave": "_.QSAVE\n",
}


def run_whitelisted_script_command(session: AutoCADSession, command_id: str) -> dict[str, Any]:
    """@brief 执行固定白名单 AutoCAD 命令，禁止传入任意脚本文本。"""
    if command_id not in SCRIPT_COMMANDS:
        return {
            "backend": "autocad_script",
            "status": "blocked",
            "stage": "preflight",
            "artifacts": [],
            "limitations": ["仅允许预定义命令，不能执行任意 AutoLISP/SCR"],
            "retryable": False,
            "error_code": "SCRIPT_COMMAND_NOT_ALLOWED",
        }
    try:
        session.send_command(SCRIPT_COMMANDS[command_id])
    except Exception as exc:
        return {
            "backend": "autocad_script",
            "status": "failed",
            "stage": "create",
            "artifacts": [],
            "limitations": ["命令可能异步，执行后必须保存并复核"],
            "retryable": True,
            "error_code": "AUTOCAD_SCRIPT_COMMAND_FAILED",
            "error": str(exc),
        }
    return {
        "backend": "autocad_script",
        "status": "pilot",
        "stage": "create",
        "artifacts": [],
        "limitations": ["命令可能异步，执行后必须保存并复核"],
        "retryable": True,
        "error_code": None,
    }
