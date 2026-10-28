"""SolidWorks 属性驱动批量改名的无 COM 回归测试。"""
from __future__ import annotations

import csv

from scripts import sw_file_rename as rename


def test_sanitize_filename():
    assert rename.sanitize_filename("a/b:c*d") == "a_b_c_d"
    assert rename.sanitize_filename("  ..name..  ") == "name"
    assert rename.sanitize_filename("x///y") == "x_y"


def test_render_name_template_and_missing():
    name, missing = rename.render_name_template("{图号}_{名称}", {"图号": "A-001", "名称": "底板"})
    assert name == "A-001_底板"
    assert missing == []
    name2, missing2 = rename.render_name_template("{图号}_{名称}", {"图号": "A-001"})
    assert missing2 == ["名称"]


def test_plan_renames_statuses():
    entries = [
        {"path": "/x/old1.SLDPRT", "properties": {"图号": "A-001", "名称": "底板"}},
        {"path": "/x/A-002_盖板.SLDASM", "properties": {"图号": "A-002", "名称": "盖板"}},
        {"path": "/x/nomiss.SLDPRT", "properties": {"图号": "", "名称": "x"}},
        {"path": "/x/blank.SLDPRT", "properties": {}},
    ]
    plans = rename.plan_renames(entries, "{图号}_{名称}")
    by_old = {p["old_name"]: p for p in plans}
    assert by_old["old1.SLDPRT"]["status"] == "rename"
    assert by_old["old1.SLDPRT"]["new_name"] == "A-001_底板.SLDPRT"
    assert by_old["A-002_盖板.SLDASM"]["status"] == "skip_noop"
    assert by_old["nomiss.SLDPRT"]["status"] == "skip_missing"
    assert by_old["blank.SLDPRT"]["status"] in {"skip_missing", "skip_empty"}


def test_plan_renames_detects_conflict():
    entries = [
        {"path": "/x/a.SLDPRT", "properties": {"图号": "SAME", "名称": "n"}},
        {"path": "/x/b.SLDPRT", "properties": {"图号": "SAME", "名称": "n"}},
    ]
    plans = rename.plan_renames(entries, "{图号}_{名称}")
    assert all(p["status"] == "conflict" for p in plans)


def test_plan_cut_list_renames():
    items = [
        {"name": "切割清单项目1", "properties": {"材料": "Q235", "长度": "1200"}},
        {"name": "Q235-800", "properties": {"材料": "Q235", "长度": "800"}},
        {"name": "切割清单项目3", "properties": {"材料": "", "长度": "500"}},
    ]
    plans = rename.plan_cut_list_renames(items, "{材料}-{长度}")
    assert plans[0]["status"] == "rename" and plans[0]["new_name"] == "Q235-1200"
    assert plans[1]["status"] == "skip_noop"
    assert plans[2]["status"] == "skip_missing"


def test_summarize_and_write_plan_csv(tmp_path):
    plans = rename.plan_renames(
        [{"path": "/x/old.SLDPRT", "properties": {"图号": "A", "名称": "b"}}], "{图号}_{名称}"
    )
    summary = rename.summarize_plan(plans)
    assert summary["rename"] == 1
    path = rename.write_plan_csv(plans, tmp_path / "plan.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["old_name"] == "old.SLDPRT"
    assert rows[0]["new_name"] == "A_b.SLDPRT"
    assert rows[0]["status"] == "rename"


class FakeCutListFeature:
    def __init__(self, name):
        self.Name = name


def test_apply_cut_list_renames(monkeypatch):
    features = [FakeCutListFeature("切割清单项目1"), FakeCutListFeature("Keep")]
    monkeypatch.setattr(rename, "get_com_member", lambda obj, name, *a: getattr(obj, name))
    monkeypatch.setattr(rename, "iter_features_recursive", lambda _model: features)
    results = rename.apply_cut_list_renames(object(), {"切割清单项目1": "Q235-1200"})
    assert len(results) == 1
    assert results[0]["verified"] is True
    assert features[0].Name == "Q235-1200"
    assert features[1].Name == "Keep"
