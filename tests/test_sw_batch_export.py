"""批量导出产物证据与文档所有权测试。"""
from pathlib import Path

from scripts import sw_export


class FakeModel:
    def __init__(self, title):
        self.title = title

    def GetTitle(self):
        return self.title


class FakeSolidWorks:
    def __init__(self, open_paths=()):
        self.open_paths = {str(Path(path).resolve()).casefold() for path in open_paths}
        self.closed = []

    def GetOpenDocumentByName(self, path):
        return object() if str(Path(path).resolve()).casefold() in self.open_paths else None

    def CloseDoc(self, title):
        self.closed.append(title)


def test_batch_export_records_real_outputs_and_preserves_open_document(tmp_path, monkeypatch):
    source_a = tmp_path / "a.sldprt"
    source_b = tmp_path / "b.sldprt"
    source_a.write_text("part-a", encoding="utf-8")
    source_b.write_text("part-b", encoding="utf-8")
    sw = FakeSolidWorks(open_paths=[source_a])

    monkeypatch.setattr(sw_export, "open_document", lambda _sw, path, **_kwargs: FakeModel(Path(path).name))
    monkeypatch.setattr(sw_export, "_activate_source_document", lambda *_args: True)

    def fake_export(_model, output_path, _extension, _quality):
        Path(output_path).write_bytes(b"solidworks-output")
        return True

    monkeypatch.setattr(sw_export, "_export_for_format", fake_export)
    report = sw_export.batch_export_formats(sw, [source_a, source_b], tmp_path / "out", ["step", "stl"])

    assert report["success"] is True
    assert report["summary"] == {"documents": 2, "outputs": 4, "succeeded": 4}
    assert all(output["produced_this_run"] for item in report["documents"] for output in item["outputs"])
    assert sw.closed == ["b.sldprt"]


def test_batch_export_blocks_existing_and_colliding_outputs(tmp_path, monkeypatch):
    first = tmp_path / "one" / "same.sldprt"
    second = tmp_path / "two" / "same.sldprt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "same.step").write_bytes(b"old")
    sw = FakeSolidWorks()
    monkeypatch.setattr(sw_export, "open_document", lambda _sw, path, **_kwargs: FakeModel(Path(path).name))
    monkeypatch.setattr(sw_export, "_activate_source_document", lambda *_args: True)

    report = sw_export.batch_export_formats(sw, [first, second], output_dir, ["step"])

    assert report["success"] is False
    assert "已存在" in report["documents"][0]["outputs"][0]["error"]
    assert "同名输出" in report["documents"][1]["outputs"][0]["error"]
    assert (output_dir / "same.step").read_bytes() == b"old"


def test_activate_source_document_verifies_active_path(tmp_path):
    source = tmp_path / "part.sldprt"
    source.write_text("part", encoding="utf-8")

    class ActiveModel(FakeModel):
        def GetPathName(self):
            return str(source)

    class ActivatingSolidWorks:
        def ActivateDoc3(self, title, _preferences, _option, _errors):
            assert title == source.name
            return ActiveModel(title)

    active = sw_export._activate_source_document(
        ActivatingSolidWorks(),
        ActiveModel(source.name),
        source,
    )

    assert active.GetPathName() == str(source)
