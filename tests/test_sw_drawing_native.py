"""结构化自动落图的可执行契约与原生证据审查。"""
from copy import deepcopy
import json

import pytest

from scripts.drawing_spec import validate_drawing_spec
from scripts.sw_drawing import validate_generic_drawing_generation
from scripts.sw_drawing_native import dimension_binding, target_matches
from scripts.sw_gdt_annotation import build_gtol_xmls
from scripts import sw_drawing_review


def spec():
    edge = {"kind": "line", "startMm": [-40, 30, 20], "endMm": [-40, -30, 20]}
    frame = {"characteristic": "position", "tolerance": "0.2", "diameter": True,
             "datums": [{"label": "A", "materialCondition": "M"}]}
    return {"schemaVersion": "1.0", "sourceModel": "C:/work/plate.sldprt", "documentType": "part", "standard": "GB_T",
            "projection": "first_angle", "paperSize": "A3", "modelSizeMm": [80, 60, 20],
            "views": {"front": {}, "top": {}, "right": {}}, "insertModelDimensions": False,
            "requiredDimensions": [{"id": "HOLE", "kind": "diameter", "view": "front", "valueMm": 10, "positionMm": [275, 208],
                                    "target": {"kind": "circle", "centerMm": [20, 15, 20], "radiusMm": 5}, "prefix": "4X "}],
            "professionalAnnotations": {"datums": [{"id": "DAT_A", "label": "A", "view": "front", "displayStyle": "square", "positionMm": [185, 186], "target": edge}],
                                        "geometricTolerances": [{"id": "POS", "view": "front", "target": {"kind": "dimension", "dimensionId": "HOLE"},
                                                                 "frames": [frame, {**deepcopy(frame), "tolerance": "0.1", "composite": True}]}]},
            "outputs": {"slddrw": True, "pdf": True, "report": True}}


def test_structured_native_spec_is_executable_without_text_guessing():
    assert validate_drawing_spec(spec())["status"] == "pass"
    assert validate_generic_drawing_generation(spec())["status"] == "pass"


@pytest.mark.parametrize("change", ["missing_target", "missing_datum", "looser", "wrong_view", "duplicate_id", "nonfinite", "unknown_selector", "mixed_dimension_modes", "assembly", "outside_sheet"])
def test_invalid_or_ambiguous_native_specs_block_before_com(change, tmp_path, monkeypatch):
    value = spec()
    row = value["professionalAnnotations"]["geometricTolerances"][0]
    if change == "missing_target":
        value["requiredDimensions"][0].pop("target")
    elif change == "missing_datum":
        value["professionalAnnotations"]["datums"] = []
    elif change == "looser":
        row["frames"][1]["tolerance"] = "0.3"
    elif change == "wrong_view":
        row["view"] = "right"
    elif change == "duplicate_id":
        row["id"] = "HOLE"
    elif change == "nonfinite":
        value["requiredDimensions"][0]["valueMm"] = float("inf")
    elif change == "unknown_selector":
        value["requiredDimensions"][0]["target"]["nearest"] = True
    elif change == "mixed_dimension_modes":
        value["insertModelDimensions"] = True
    elif change == "assembly":
        value["documentType"] = "assembly"
    else:
        value["requiredDimensions"][0]["positionMm"] = [500, 100]
    from scripts import sw_drawing_package
    def forbidden(*args, **kwargs):
        raise AssertionError("无效计划不应连接 SolidWorks")
    monkeypatch.setattr(sw_drawing_package, "SolidWorksSession", forbidden)
    result = sw_drawing_package.generate_package(value, tmp_path / "output")
    assert result["status"] == "blocked"
    assert not (tmp_path / "output").exists()


def test_binding_name_cannot_override_real_native_dimension_type():
    assert dimension_binding("CAD_DIM__diameter__HOLE", 6) == {"id": "HOLE", "kind": "diameter"}
    assert dimension_binding("CAD_DIM__diameter__HOLE", 3) == {}
    assert not target_matches({"kind": "dimension", "dimensionId": "D1"}, {"kind": "dimension", "dimensionId": "D10"})


def test_rendered_number_cannot_mask_wrong_native_dimension_value():
    mismatches = sw_drawing_review._MODULE._dimension_mismatches(
        {"valueMm": 10}, {"value_mm": 11, "text": "10"})
    assert "valueMm" in mismatches


def test_queued_output_collision_does_not_overwrite_existing_report(tmp_path, monkeypatch):
    from scripts import sw_drawing_package as package
    value = spec()
    source = tmp_path / "plate.sldprt"
    source.write_bytes(b"source")
    value["sourceModel"] = str(source)
    output = tmp_path / "out"
    report = output / "drawing_review_report.json"

    class Guard:
        def __enter__(self):
            output.mkdir()
            report.write_text("previous-result", encoding="utf-8")
        def __exit__(self, *args):
            pass

    class Session:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(package, "SolidWorksReadGuard", Guard)
    monkeypatch.setattr(package, "SolidWorksSession", Session)
    result = package.generate_package(value, output)
    assert result["status"] == "blocked" and not result["outputs"]
    assert result["error_code"] == "DRAWING_OUTPUT_EXISTS"
    assert report.read_text(encoding="utf-8") == "previous-result"


@pytest.mark.parametrize("change", ["tolerance", "modifier", "frame_missing", "target", "id", "note"])
def test_structured_gdt_review_rejects_wrong_native_evidence(change):
    value = spec()
    row = value["professionalAnnotations"]["geometricTolerances"][0]
    frames = build_gtol_xmls(row)
    record = {"id": "POS", "semantic_view": "front", "target": {"kind": "dimension", "dimensionId": "HOLE"},
              "frames": [{"xml": xml} for xml in frames]}
    if change == "tolerance":
        record["frames"][1]["xml"] = frames[1].replace("0.1", "0.09")
    elif change == "modifier":
        record["frames"][0]["xml"] = frames[0].replace("MaximumMaterialCondition", "LeastMaterialCondition")
    elif change == "frame_missing":
        record["frames"].pop()
    elif change == "target":
        record["target"]["dimensionId"] = "OTHER"
    elif change == "id":
        record["id"] = "POS2"
    structure = {"professional_annotations": {"geometric_tolerances": [] if change == "note" else [record]},
                 "notes": [{"text": "position 0.2 M A M / 0.1"}]}
    report = sw_drawing_review._MODULE._professional_annotation_report(value, structure)
    assert "POS" in report["missing"]


def test_copy_and_drawing_frame_contracts_stay_in_sync():
    from scripts.sw_gdt_copy import SCHEMA
    from pathlib import Path
    copy_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    drawing_schema = json.loads((Path(__file__).resolve().parents[1] / "subskills/solidworks-engineering-drawing/schemas/drawing_spec.schema.json").read_text(encoding="utf-8"))
    for key in ("frame", "datumReference", "gtol", "datum"):
        assert copy_schema["$defs"][key] == drawing_schema["$defs"][key]
