"""@brief 验证共享实例、用户文档和预算；不启动真实 CAD。"""
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import sw_connect, sw_session


class App:
    """@brief 用户实例与文档的只读/关闭替身。"""
    def __init__(self):
        self.docs = []
        self.closed = []
        self.exited = False
        self.ActiveDoc = None

    def RevisionNumber(self):
        return "34.1.1"

    def GetProcessID(self):
        return 7

    def GetDocuments(self):
        return list(self.docs)

    def CloseDoc(self, title):
        self.closed.append(title)
        self.docs = [doc for doc in self.docs if doc.GetTitle() != title]
        self.ActiveDoc = self.docs[0] if self.docs else None

    def ExitApp(self):
        self.exited = True


def connection_fixture(monkeypatch, app, before):
    """@brief 配置实例归属检查的独立上下文。"""
    monkeypatch.setattr(sw_connect, "ensure_solidworks_installed", lambda: None)
    monkeypatch.setattr(sw_connect, "solidworks_processes", lambda: before)
    monkeypatch.setattr(sw_connect, "_LaunchGuard", contextlib.nullcontext)


def test_unready_existing_instance_is_not_dispatched_again(monkeypatch):
    app = App()
    connection_fixture(monkeypatch, app, {7: 2026})
    dispatch = []
    def missing(_):
        raise RuntimeError("ROT unavailable")
    monkeypatch.setattr(sw_connect, "win32com_client", SimpleNamespace(GetActiveObject=missing,
        Dispatch=lambda _: dispatch.append(True)))
    with pytest.raises(sw_connect.SolidWorksConnectionError, match="SW_INSTANCE_NOT_READY"):
        sw_connect.connect_solidworks(version=2026, wait_seconds=.01)
    assert dispatch == []
    assert app.exited is False


def test_actual_revision_must_match_requested_year(monkeypatch):
    app = App()
    app.RevisionNumber = lambda: "33.0.0"
    connection_fixture(monkeypatch, app, {7: 2025})
    monkeypatch.setattr(sw_connect, "win32com_client", SimpleNamespace(GetActiveObject=lambda _: app))
    with pytest.raises(sw_connect.SolidWorksConnectionError, match="SW_VERSION_MISMATCH"):
        sw_connect.connect_solidworks(version=2024)
    assert app.exited is False


def test_dispatch_cannot_claim_a_preexisting_pid(monkeypatch):
    app = App()
    connection_fixture(monkeypatch, app, {7: 2024})
    def missing(_):
        raise RuntimeError("ROT unavailable")
    monkeypatch.setattr(sw_connect, "win32com_client", SimpleNamespace(GetActiveObject=missing, Dispatch=lambda _: app))
    _, _, metadata = sw_connect.connect_solidworks(version=2026, return_metadata=True)
    assert metadata["started_by_cad_studio"] is False


def test_context_closes_only_created_documents(monkeypatch):
    app = App()
    user = SimpleNamespace(GetTitle=lambda: "用户未保存零件", GetPathName=lambda: "")
    app.docs = [user]
    app.ActiveDoc = user
    monkeypatch.setattr(sw_session, "connect_solidworks", lambda **_: (app, user, {"started_by_cad_studio": False, "process_id": 7}))
    created = SimpleNamespace(GetTitle=lambda: "本轮零件", GetPathName=lambda: "")
    def new(*args, **kwargs):
        app.docs.append(created)
        app.ActiveDoc = created
        return created
    monkeypatch.setattr(sw_session, "new_document", new)
    with sw_session.SolidWorksSession() as session:
        session.new_part()
    assert app.closed == ["本轮零件"]
    assert app.docs == [user]
    assert app.exited is False


def test_budget_blocks_creation_without_closing_user_documents(monkeypatch):
    app = App()
    app.docs = [SimpleNamespace(GetTitle=lambda: "用户零件")]
    with pytest.raises(sw_connect.SolidWorksConnectionError, match="SW_DOCUMENT_BUDGET"):
        sw_connect.new_document(app, template_path="fixture.prtdot", max_documents=1)
    assert app.closed == []


def test_unreadable_document_list_blocks_creation_without_guessing_empty():
    """@brief COM 清单读取失败时，禁止把用户文档误判为空并继续创建。"""
    app = App()
    created = []
    app.NewDocument = lambda *args: created.append(args)
    def unavailable():
        raise RuntimeError("文档清单暂不可读")
    app.GetDocuments = unavailable
    with pytest.raises(sw_connect.SolidWorksConnectionError, match="SW_DOCUMENT_STATE_UNAVAILABLE"):
        sw_connect.new_document(app, template_path="fixture.prtdot")
    assert created == []
    assert app.closed == []
