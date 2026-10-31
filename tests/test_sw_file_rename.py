"""只读改名预览：名称安全、冲突和用户文档归属。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import sw_document_data, sw_file_rename as rename


def test_plan_reports_missing_unsafe_and_duplicate_names():
    entries = [
        {"path": "a.SLDPRT", "properties": {"图号": "A1"}},
        {"path": "b.SLDPRT", "properties": {"图号": "a1"}},
        {"path": "c.SLDPRT", "properties": {"图号": "CON"}},
        {"path": "d.SLDPRT", "properties": {}},
    ]
    plans = rename.plan_renames(entries, "{图号}")
    assert [plan["status"] for plan in plans] == ["blocked"] * 4
    assert "冲突" in plans[0]["reason"]
    assert "保留" in plans[2]["reason"]
    assert "缺少属性" in plans[3]["reason"]


def test_plan_detects_existing_source_name_and_allows_distinct_output():
    entries = [{"path": "a.SLDPRT", "properties": {"name": "b"}},
               {"path": "b.SLDPRT", "properties": {"name": "new"}}]
    plans = rename.plan_renames(entries, "{name}")
    assert plans[0]["status"] == "blocked"
    assert plans[1]["status"] == "planned" and plans[1]["new_name"] == "new.SLDPRT"


@pytest.mark.parametrize("template", ["{x.__class__}", "{x[0]}", "{x!r}", "{x:>3}", "missing fields"])
def test_rejects_non_declarative_templates(template):
    with pytest.raises(ValueError):
        rename.template_fields(template)


def test_collection_never_closes_preexisting_user_document(tmp_path, monkeypatch):
    for name in ("already.SLDPRT", "owned.SLDPRT", "~$already.SLDPRT"):
        (tmp_path / name).write_text("test")
    preexisting, owned = object(), object()
    closed = []

    class Session:
        _owned_documents = []
        def open(self, path, **kwargs):
            assert kwargs == {"read_only": True, "silent": True}
            if path.endswith("already.SLDPRT"):
                return preexisting
            self._owned_documents.append(owned)
            return owned
        def close(self, *, model):
            closed.append(model)
            self._owned_documents.remove(model)

    monkeypatch.setattr(sw_document_data, "read_custom_property", lambda model, name: {"exists": True, "was_resolved": True, "resolved": "P1"})
    entries = rename.collect_entries(Session(), tmp_path, ["编号"])
    assert len(entries) == 2
    assert closed == [owned]
    assert preexisting not in closed


def test_unresolved_property_does_not_become_a_filename(tmp_path, monkeypatch):
    (tmp_path / "part.SLDPRT").write_text("test")
    document = object()
    session = SimpleNamespace(_owned_documents=[], open=lambda *a, **k: document)
    monkeypatch.setattr(sw_document_data, "read_custom_property", lambda *a: {
        "exists": True, "was_resolved": False, "raw": "linked expression", "resolved": ""
    })
    entries = rename.collect_entries(session, tmp_path, ["编号"])
    assert rename.plan_renames(entries, "{编号}")[0]["status"] == "blocked"
