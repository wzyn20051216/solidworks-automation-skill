"""原生 GD&T 副本计划、精确目标解析与前置阻断。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError
import subprocess
import sys

from scripts.sw_gdt_copy import validate_plan, resolve_target, annotate_copy
from scripts.sw_rename_copy import _sha256


def plan():
    return {"schemaVersion": "1.0", "sourceSha256": "a" * 64, "sheet": "Sheet1", "paperSize": "A3",
            "datums": [{"id": "DAT-A", "view": "Front", "label": "A", "positionMm": [141, 100],
                        "displayStyle": "square", "target": {"kind": "line", "startMm": [-40, -30, 20], "endMm": [40, -30, 20]}}],
            "geometricTolerances": [{"id": "G1", "view": "Front", "characteristic": "position", "tolerance": "0.2",
                                     "diameter": True, "datums": ["A"], "target": {"kind": "dimension", "name": "RD3@Front", "systemValue": .01}}]}


def test_plan_has_explicit_units_source_identity_and_targets():
    value = plan()
    assert validate_plan(value) is value


@pytest.mark.parametrize("change", ["unknown", "nonfinite", "duplicate_id", "duplicate_label", "dimension_datum", "dimension_position", "edge_no_position", "unsupported", "zero", "empty"])
def test_invalid_plan_is_rejected_before_com(change):
    value = plan()
    if change == "unknown":
        value["writeSource"] = True
    elif change == "nonfinite":
        value["geometricTolerances"][0]["target"]["systemValue"] = float("nan")
    elif change == "duplicate_id":
        value["geometricTolerances"][0]["id"] = "DAT-A"
    elif change == "duplicate_label":
        value["datums"].append({**deepcopy(value["datums"][0]), "id": "DAT-A2"})
    elif change == "dimension_datum":
        value["datums"][0]["target"] = value["geometricTolerances"][0]["target"]
    elif change == "dimension_position":
        value["geometricTolerances"][0]["positionMm"] = [100, 100]
    elif change == "edge_no_position":
        value["geometricTolerances"][0]["target"] = value["datums"][0]["target"]
    elif change == "unsupported":
        value["geometricTolerances"][0]["characteristic"] = "anything"
    elif change == "zero":
        value["geometricTolerances"][0]["tolerance"] = "0"
    else:
        value["datums"] = value["geometricTolerances"] = []
    with pytest.raises((ValidationError, ValueError)):
        validate_plan(value)


def test_changed_source_is_blocked_without_creating_output(tmp_path):
    source = tmp_path / "source.slddrw"
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="源图纸已经变化"):
        annotate_copy(source, plan(), tmp_path / "new")
    assert not (tmp_path / "new").exists()
    assert source.read_bytes() == b"changed"


def test_existing_output_is_never_overwritten(tmp_path):
    source = tmp_path / "source.slddrw"
    source.write_bytes(b"test")
    output = tmp_path / "existing"
    output.mkdir()
    important = output / "drawing.slddrw"
    important.write_bytes(b"user work")
    value = plan()
    value["sourceSha256"] = _sha256(source)
    with pytest.raises(ValueError, match="输出目录必须不存在"):
        annotate_copy(source, value, output)
    assert important.read_bytes() == b"user work"


class Dimension:
    def __init__(self, name, value):
        self.name, self.value = name, value

    def GetNameForSelection(self):
        return self.name

    def GetDimension2(self, index):
        return self

    @property
    def SystemValue(self):
        return self.value


class View:
    def __init__(self, dimensions):
        self.dimensions = dimensions

    def GetDisplayDimensions(self):
        return self.dimensions


def test_dimension_target_requires_exact_name_value_and_unique_candidate():
    right, wrong = Dimension("RD3@Front", .01), Dimension("RD4@Front", .01)
    target = plan()["geometricTolerances"][0]["target"]
    assert resolve_target(View([wrong, right]), target) is right
    for dimensions in ([wrong], [right, Dimension("RD3@Front", .01)], [Dimension("RD3@Front", .02)]):
        with pytest.raises(ValueError, match="唯一确认"):
            resolve_target(View(dimensions), target)


def test_line_target_matches_model_coordinates_in_either_direction_but_not_nearby_edge():
    def line(start, end):
        return SimpleNamespace(GetCurve=lambda: SimpleNamespace(IsLine=lambda: True),
                               GetStartVertex=lambda: SimpleNamespace(GetPoint=lambda: start),
                               GetEndVertex=lambda: SimpleNamespace(GetPoint=lambda: end))

    edge = line([-.04, -.03, .02], [.04, -.03, .02])
    nearby = line([-.04, -.03001, .02], [.04, -.03001, .02])
    view = SimpleNamespace(GetVisibleComponents=lambda: [object()], GetVisibleEntities2=lambda *_: [nearby, edge])
    target = plan()["datums"][0]["target"]
    assert resolve_target(view, target) is edge
    assert resolve_target(view, {**target, "startMm": target["endMm"], "endMm": target["startMm"]}) is edge
    view.GetVisibleEntities2 = lambda *_: [edge, line([.04, -.03, .02], [-.04, -.03, .02])]
    with pytest.raises(ValueError, match="候选数 2"):
        resolve_target(view, target)


def test_persistent_identity_unknown_is_not_success():
    from scripts.sw_gdt_copy import _same_id
    extension = SimpleNamespace(IsSamePersistentID=lambda a, b: 2)
    assert _same_id(extension, b"source", b"copy") is False


def test_saved_layout_is_baseline_for_automatically_positioned_symbol():
    from scripts.sw_gdt_copy import _capture_saved_positions
    annotation = SimpleNamespace(GetPosition=lambda: (.2, .21, 0.))
    record = {"object": SimpleNamespace(GetAnnotation=lambda: annotation), "request": {}, "position": (.2, .20, 0.)}
    _capture_saved_positions([record])
    assert record["position"] == (.2, .21, 0.)
    record["request"] = {"positionMm": [200, 200]}
    with pytest.raises(RuntimeError, match="显式请求位置"):
        _capture_saved_positions([record])


def test_script_entry_point_imports_project_from_unrelated_directory(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/sw_gdt_copy.py"
    result = subprocess.run([sys.executable, str(script), "--help"], cwd=tmp_path,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert b"--inspect" in result.stdout
