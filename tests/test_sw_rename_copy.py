"""只支持独立零件的改名副本：边界、失败停止及不覆盖测试。"""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import sw_rename_copy as tool


def plan(source: Path, name="renamed.sldprt", status="planned"):
    return {"source": str(source), "new_name": name, "status": status}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.sldprt"
    path.write_bytes(b"unchanged source bytes")
    return path


@pytest.mark.parametrize("name", ["../outside.sldprt", "CON.sldprt", "bad?.sldprt", "wrong.sldasm", "~$lock.sldprt", ""])
def test_invalid_output_names_are_rejected(source, name):
    with pytest.raises(ValueError):
        tool.prepare_plan([plan(source, name)])


def test_plan_rejects_conflicts_blocked_and_assembly(tmp_path, source):
    assembly = tmp_path / "assembly.sldasm"
    assembly.write_bytes(b"assembly")
    for plans in ([plan(source), plan(source, "other.sldprt")],
                  [plan(source, status="blocked")], [plan(assembly)]):
        with pytest.raises(ValueError):
            tool.prepare_plan(plans)


def test_existing_output_directory_is_never_modified(tmp_path, source):
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        tool.copy_batch([plan(source)], target)
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(target.iterdir()) == [sentinel]


class FakeSession:
    def __init__(self, **_):
        self._owned_documents = []
        self.sw = object()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def _documents(self):
        return list(self._owned_documents)

    def open(self, path, **_):
        model = SimpleNamespace(GetTitle=lambda: Path(path).name, GetPathName=lambda: path)
        self._owned_documents.append(model)
        return model

    def close(self, model):
        self._owned_documents.remove(model)


def fake_environment(monkeypatch):
    monkeypatch.setattr(tool, "SolidWorksSession", FakeSession)
    monkeypatch.setattr(tool, "SolidWorksReadGuard", nullcontext)
    monkeypatch.setattr(tool, "_snapshot", lambda _: {"volume_mm3": 1.0, "size_mm": [1., 1., 1.], "solid_bodies": 1})


def test_success_creates_identical_copy_and_manifest(tmp_path, source, monkeypatch):
    fake_environment(monkeypatch)
    output = tmp_path / "new"
    result = tool.copy_batch([plan(source)], output)
    copied = output / "renamed.sldprt"
    assert result["status"] == "review_required"
    assert copied.read_bytes() == source.read_bytes()
    assert result["outputs"][0]["sha256"] == result["outputs"][0]["source_sha256"]
    assert (output / "copy-manifest.json").is_file()


def test_unexpected_source_change_stops_with_evidence(tmp_path, source, monkeypatch):
    fake_environment(monkeypatch)
    original = tool.shutil.copyfileobj
    def mutate_after_copy(reader, writer, length):
        original(reader, writer, length)
        source.write_bytes(b"changed while copying")
    monkeypatch.setattr(tool.shutil, "copyfileobj", mutate_after_copy)
    result = tool.copy_batch([plan(source)], tmp_path / "out")
    assert result["status"] == "blocked" and "源文件发生变化" in result["error"]
    assert not result["outputs"] and Path(result["manifest"]).exists()


@pytest.mark.parametrize("read_only", [True, False])
def test_same_named_open_document_is_not_closed_or_reused(tmp_path, source, read_only):
    other = tmp_path / "other"
    other.mkdir()
    doc = SimpleNamespace(GetTitle=lambda: "source.sldprt", GetPathName=lambda: str(other / "source.sldprt"))
    session = FakeSession()
    session._owned_documents.append(doc)
    with pytest.raises(ValueError, match="同名"):
        tool._open_checked(session, source, read_only=read_only)
    assert session._owned_documents == [doc]


@pytest.mark.parametrize("read_only", [True, False])
def test_unknown_returned_document_is_disowned_without_closing(source, read_only):
    session = FakeSession()
    unknown = SimpleNamespace(GetPathName=lambda: "")
    def open_unknown(*_args, **_kwargs):
        session._owned_documents.append(unknown)
        return unknown
    session.open = open_unknown
    with pytest.raises(RuntimeError, match="路径不一致"):
        tool._open_checked(session, source, read_only=read_only)
    assert session._owned_documents == []


def test_checked_writable_open_keeps_identity_check(source):
    session = FakeSession()
    flags = []
    normal_open = session.open

    def open_recording(path, **kwargs):
        flags.append(kwargs)
        return normal_open(path, **kwargs)

    session.open = open_recording
    model = tool._open_checked(session, source, read_only=False)
    assert flags == [{"read_only": False, "silent": True}]
    assert model.GetPathName() == str(source)


@pytest.mark.parametrize("dirty,deps,bodies", [(True, (), [1]), (False, ("external", "ref.sldprt"), [1]), (False, None, [1]), (False, (), [])])
def test_unsafe_model_states_are_blocked(dirty, deps, bodies):
    model = SimpleNamespace(GetType=lambda: 1, GetSaveFlag=lambda: dirty,
                            GetDependencies2=lambda *_: deps, GetBodies2=lambda *_: bodies,
                            GetConfigurationNames=lambda: ("Default",),
                            ListAuxiliaryExternalFileReferencesCount=lambda: 0,
                            Extension=SimpleNamespace(ListExternalFileReferencesCount=lambda: 0))
    with pytest.raises(ValueError):
        tool._snapshot(model)


def test_multiconfiguration_and_unknown_dirty_state_are_blocked():
    model = SimpleNamespace(GetType=lambda: 1, GetSaveFlag=lambda: False,
                            GetDependencies2=lambda *_: (), GetBodies2=lambda *_: [1],
                            GetConfigurationNames=lambda: ("Default", "Other"))
    with pytest.raises(ValueError, match="单配置"):
        tool._snapshot(model)
    model.GetSaveFlag = lambda: None
    with pytest.raises(ValueError, match="未保存"):
        tool._snapshot(model)


def test_additional_external_reference_count_is_not_ignored():
    model = SimpleNamespace(GetType=lambda: 1, GetSaveFlag=lambda: False,
                            GetDependencies2=lambda *_: (), GetConfigurationNames=lambda: ("Default",),
                            ListAuxiliaryExternalFileReferencesCount=lambda: 1,
                            Extension=SimpleNamespace(ListExternalFileReferencesCount=lambda: 0))
    with pytest.raises(ValueError, match="外部引用"):
        tool._snapshot(model)
