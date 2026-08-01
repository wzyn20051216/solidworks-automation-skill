"""AutoCAD 会话薄封装的无 COM 回归测试。"""
from __future__ import annotations

import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subskills" / "autocad-automation" / "scripts"))

import acad_session  # noqa: E402


class FakeEntity:
    """@brief 记录尺寸实体的图层和颜色。"""

    def __init__(self, kind, args):
        self.kind = kind
        self.args = args
        self.Layer = "0"
        self.Color = 256


class FakeModelSpace:
    """@brief 模拟只支持 Count/Item 的 AutoCAD ModelSpace。"""

    def __init__(self):
        self.entities = []

    @property
    def Count(self):
        return len(self.entities)

    def Item(self, index):
        return self.entities[index]

    def AddDimAligned(self, *args):
        entity = FakeEntity("aligned", args)
        self.entities.append(entity)
        return entity

    def AddDimRotated(self, *args):
        entity = FakeEntity("rotated", args)
        self.entities.append(entity)
        return entity

    def AddDimDiametric(self, *args):
        entity = FakeEntity("diametric", args)
        self.entities.append(entity)
        return entity


class FakeLayers:
    def __init__(self):
        self.values = {}

    def Item(self, name):
        if name not in self.values:
            raise KeyError(name)
        return self.values[name]

    def Add(self, name):
        layer = type("Layer", (), {"Color": 256, "Linetype": "Continuous"})()
        self.values[name] = layer
        return layer


class FakeDocument:
    def __init__(self):
        self.ModelSpace = FakeModelSpace()
        self.Layers = FakeLayers()
        self.Name = "Drawing1.dwg"


class FakeDocumentsWithoutCount:
    """@brief 模拟 AutoCAD 动态代理只暴露 Add、不暴露 Count。"""

    def Add(self):
        return FakeDocument()


def test_connect_autocad_uses_dispatchex_for_owned_instance(monkeypatch):
    application = type("Application", (), {"Visible": False})()

    class FakeClient:
        def GetActiveObject(self, _progid):
            raise RuntimeError("not running")

        def Dispatch(self, _progid):
            raise AssertionError("不得用 Dispatch 声称新实例所有权")

        def DispatchEx(self, progid):
            assert progid == "AutoCAD.Application"
            return application

    monkeypatch.setattr(acad_session.pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(acad_session.win32com, "client", FakeClient())

    connected, started = acad_session.connect_autocad(return_ownership=True)

    assert connected is application
    assert started is True


def _session(monkeypatch):
    monkeypatch.setattr(acad_session, "acad_point", lambda value: tuple(value))
    session = acad_session.AutoCADSession()
    session.doc = FakeDocument()
    return session


def test_creates_real_dimension_entities_with_expected_arguments(monkeypatch):
    session = _session(monkeypatch)

    aligned = session.add_dim_aligned((0, 0, 0), (120, 0, 0), (60, -12, 0))
    rotated = session.add_dim_rotated((0, 0, 0), (0, 80, 0), (-12, 40, 0), 90)
    diameter = session.add_dim_diametric((15, 15, 0), 4.5, leader_length=8)

    assert [aligned.kind, rotated.kind, diameter.kind] == ["aligned", "rotated", "diametric"]
    assert all(entity.Layer == "DIM" for entity in (aligned, rotated, diameter))
    assert math.isclose(rotated.args[3], math.pi / 2)
    assert diameter.args[0] == (19.5, 15.0, 0.0)
    assert diameter.args[1] == (10.5, 15.0, 0.0)


def test_iter_model_entities_uses_count_item_proxy(monkeypatch):
    session = _session(monkeypatch)
    session.doc.ModelSpace.entities.extend(["line", "circle"])

    assert list(session.iter_model_entities()) == ["line", "circle"]


def test_refresh_document_proxy_rebinds_active_document(monkeypatch):
    session = acad_session.AutoCADSession()
    session.app = type("App", (), {"ActiveDocument": FakeDocument()})()
    stale = FakeDocument()
    session.doc = stale

    refreshed = session.refresh_document_proxy()

    assert refreshed is session.app.ActiveDocument
    assert refreshed is not stale


def test_model_rebinds_stale_document_without_modelspace():
    active = FakeDocument()
    session = acad_session.AutoCADSession()
    session.app = type("App", (), {"ActiveDocument": active})()
    session.doc = type("StaleDocument", (), {})()

    assert session.model is active.ModelSpace
    assert session.doc is active


def test_documents_collection_accepts_proxy_without_count():
    session = acad_session.AutoCADSession()
    session.app = type("App", (), {"Documents": FakeDocumentsWithoutCount()})()

    assert session._documents_collection() is session.app.Documents


def test_new_document_retries_busy_add_and_active_document():
    class BusyDocuments:
        def __init__(self):
            self.calls = 0

        def Add(self):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("busy")

    document = FakeDocument()
    documents = BusyDocuments()
    app = type("App", (), {"Documents": documents, "ActiveDocument": document})()
    session = acad_session.AutoCADSession()
    session.app = app

    assert session.new_document() is document
    assert documents.calls == 3


def test_create_layer_rebinds_item_after_add(monkeypatch):
    session = _session(monkeypatch)
    layer = session.create_layer("CENTER", color=1, linetype="CENTER")

    assert layer is session.doc.Layers.Item("CENTER")
    assert layer.Color == 1
    assert layer.Linetype == "CENTER"


def test_quit_owned_instance_never_closes_attached_autocad(monkeypatch):
    class FakeApplication:
        def __init__(self):
            self.quit_calls = 0

        def Quit(self):
            self.quit_calls += 1

    attached = FakeApplication()
    session = acad_session.AutoCADSession()
    session.app = attached
    session.started_by_session = False

    assert session.quit_owned_instance() is False
    assert attached.quit_calls == 0

    owned = FakeApplication()
    session.app = owned
    session.started_by_session = True
    session.owned_process_id = 1234
    running = iter((True, False))
    monkeypatch.setattr(acad_session, "_process_is_running", lambda _pid: next(running))
    monkeypatch.setattr(acad_session.time, "sleep", lambda _seconds: None)

    assert session.quit_owned_instance() is True
    assert owned.quit_calls == 1
    assert session.app is None


def test_retry_com_busy_retries_only_transient_hresult(monkeypatch):
    monkeypatch.setattr(acad_session.time, "sleep", lambda _seconds: None)
    calls = 0

    class BusyError(RuntimeError):
        hresult = -2147418111

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise BusyError("AutoCAD busy")
        return "ok"

    assert acad_session._retry_com_busy(operation, "测试操作") == "ok"
    assert calls == 3


def test_quit_owned_instance_force_terminates_only_recorded_pid(monkeypatch):
    application = type("App", (), {"Quit": lambda self: None})()
    session = acad_session.AutoCADSession()
    session.app = application
    session.started_by_session = True
    session.owned_process_id = 4321
    terminated = []
    monkeypatch.setattr(acad_session.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(acad_session, "_process_is_running", lambda _pid: not terminated)
    monkeypatch.setattr(
        acad_session,
        "_terminate_owned_process",
        lambda process_id: terminated.append(process_id) is None,
    )

    assert session.quit_owned_instance() is True
    assert terminated == [4321]
    assert session.forced_termination_used is True


def test_quit_owned_instance_waits_for_delayed_exit_after_termination(monkeypatch):
    """@brief 强制终止后系统状态短暂滞后时，不应误报清理失败。"""
    application = type("App", (), {"Quit": lambda self: None})()
    session = acad_session.AutoCADSession()
    session.app = application
    session.started_by_session = True
    session.owned_process_id = 2468
    terminated = []
    states = iter([True] * 51 + [True, True, False])
    monkeypatch.setattr(acad_session.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(acad_session, "_process_is_running", lambda _pid: next(states))
    monkeypatch.setattr(
        acad_session,
        "_terminate_owned_process",
        lambda process_id: terminated.append(process_id) is None,
    )

    assert session.quit_owned_instance() is True
    assert terminated == [2468]
    assert session.last_cleanup["process_exit_confirmed"] is True
    assert session.last_cleanup["forced_termination_used"] is True
