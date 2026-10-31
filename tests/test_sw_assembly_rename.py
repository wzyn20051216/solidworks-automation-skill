"""装配体改名计划的文件身份及冲突校验。"""
import pytest

from scripts import sw_assembly_rename as implementation
from scripts.sw_assembly_rename import prepare_assembly_plan, validate_reference_graph, _compare_assembly, _assembly_snapshot


def _plan(tmp_path):
    root = tmp_path / "top.sldasm"
    sub = tmp_path / "sub.sldasm"
    part = tmp_path / "part.sldprt"
    for item in (root, sub, part):
        item.write_bytes(b"test")
    return root, [{"source": str(p), "new_name": "new_" + p.name, "status": "planned"} for p in (root, sub, part)]


def test_accepts_two_level_explicit_mapping(tmp_path):
    root, plan = _plan(tmp_path)
    actual = prepare_assembly_plan(root, plan)
    assert len(actual) == 3
    assert actual[0] == {"source": str(root.resolve()), "new_name": "new_top.sldasm"}
    assert root.read_bytes() == b"test"


@pytest.mark.parametrize("change", ["missing_root", "duplicate_source", "duplicate_target", "cross_type", "path_escape", "original_name", "blocked"])
def test_rejects_unsafe_plans(tmp_path, change):
    root, plan = _plan(tmp_path)
    if change == "missing_root":
        plan.pop(0)
    elif change == "duplicate_source":
        plan[1]["source"] = plan[0]["source"]
    elif change == "duplicate_target":
        plan[1]["new_name"] = plan[0]["new_name"].upper()
    elif change == "cross_type":
        plan[0]["new_name"] = "new.sldprt"
    elif change == "path_escape":
        plan[0]["new_name"] = "../new.sldasm"
    elif change == "original_name":
        plan[0]["new_name"] = "sub.sldasm"
    else:
        plan[0]["status"] = "blocked"
    with pytest.raises(ValueError):
        prepare_assembly_plan(root, plan)
    assert root.read_bytes() == b"test"


def test_graph_orders_children_before_parents_and_handles_reuse(tmp_path):
    root, plan = _plan(tmp_path)
    entries = prepare_assembly_plan(root, plan)
    top, sub, part = [row["source"] for row in entries]
    assert validate_reference_graph(top, entries, {top: [sub, part], sub: [part], part: []}) == [part, sub, top]


@pytest.mark.parametrize("change", ["missing", "outside", "cycle", "unreachable", "relative"])
def test_graph_rejects_incomplete_or_cyclic_dependencies(tmp_path, change):
    root, plan = _plan(tmp_path)
    entries = prepare_assembly_plan(root, plan)
    top, sub, part = [row["source"] for row in entries]
    graph = {top: [sub], sub: [part], part: []}
    if change == "missing":
        del graph[part]
    elif change == "outside":
        graph[sub].append(str(tmp_path / "outside.sldprt"))
    elif change == "cycle":
        graph[part] = [top]
    elif change == "unreachable":
        graph[sub] = []
    else:
        graph[sub] = ["relative.sldprt"]
    with pytest.raises(ValueError):
        validate_reference_graph(root, entries, graph)


def test_component_snapshot_requires_matching_transform_and_mate_health(tmp_path):
    old, new = str(tmp_path / "old.sldprt"), str(tmp_path / "new.sldprt")
    item = {"path": old, "configuration": "default", "state": 2, "transform": [0.0] * 16}
    before = {"components": [item], "mates": [{"name": "M1", "type": "MateCoincident", "error_code": 0}]}
    after = {"components": [{**item, "path": new}], "mates": list(before["mates"])}
    _compare_assembly(before, after, {old.casefold(): new})
    after["components"][0]["transform"] = [0.1] + [0.0] * 15
    with pytest.raises(ValueError, match="变换"):
        _compare_assembly(before, after, {old.casefold(): new})
    after["components"][0]["transform"] = [0.0] * 16
    after["mates"] = []
    with pytest.raises(ValueError, match="配合"):
        _compare_assembly(before, after, {old.casefold(): new})


def test_assembly_external_reference_is_blocked():
    class Extension:
        def ListExternalFileReferencesCount(self):
            return 1

    extension = Extension()

    class Assembly:
        Extension = extension

        def GetType(self):
            return 2

        def GetSaveFlag(self):
            return False

        def GetConfigurationNames(self):
            return ["default"]

        def ListAuxiliaryExternalFileReferencesCount(self):
            return 0

    with pytest.raises(ValueError, match="外部文件引用"):
        _assembly_snapshot(Assembly())


def test_copy_stops_before_copy_when_graph_has_unplanned_dependency(tmp_path, monkeypatch):
    root, plan = _plan(tmp_path)
    outside = tmp_path / "outside.sldprt"
    outside.write_bytes(b"outside")

    class Guard:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Session(Guard):
        def __init__(self, **kwargs):
            self._owned_documents = []

    class Extension:
        ToolboxPartType = 0

    extension = Extension()

    class Model:
        Extension = extension

        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(implementation, "SolidWorksReadGuard", Guard)
    monkeypatch.setattr(implementation, "SolidWorksSession", Session)
    monkeypatch.setattr(implementation, "_open_checked", lambda session, path: Model(path))
    monkeypatch.setattr(implementation, "_direct_references", lambda model: [str(outside)] if model.path == root else [])
    monkeypatch.setattr(implementation, "_snapshot", lambda model: {})
    monkeypatch.setattr(implementation, "_assembly_snapshot", lambda model: {})
    result = implementation.copy_assembly(root, plan, tmp_path / "output")
    assert result["status"] == "blocked"
    assert "引用不在计划中" in result["error"]
    assert result["outputs"] == []
    assert list((tmp_path / "output").glob("*.sld*")) == []
    assert root.read_bytes() == b"test"
