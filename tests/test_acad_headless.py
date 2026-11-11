"""ezdxf 只读后端回归测试。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subskills" / "autocad-automation" / "scripts"))

from acad_headless import inspect_dxf, main  # noqa: E402


def test_inspect_dxf_reports_layers_entities_and_bbox(tmp_path):
    source = tmp_path / "plate.dxf"
    document = ezdxf.new("R2018")
    document.layers.add("OUTLINE")
    modelspace = document.modelspace()
    modelspace.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "OUTLINE"})
    modelspace.add_circle((20, 20), 4, dxfattribs={"layer": "OUTLINE"})
    document.saveas(source)

    report = inspect_dxf(source)

    assert report["backend"] == "ezdxf-readonly"
    assert report["entityCount"] == 2
    assert report["layerCounts"]["OUTLINE"] == 2
    assert report["bbox"] is not None
    assert report["schemaVersion"] == "2.0"
    assert report["evaluation"]["status"] == "warn"


def test_inspect_dxf_reports_engineering_drawing_evidence(tmp_path):
    source = tmp_path / "a3_plate.dxf"
    document = ezdxf.new("R2018")
    for layer in ("FRAME", "OUTLINE", "CENTER", "DIM", "TEXT"):
        document.layers.add(layer)
    modelspace = document.modelspace()
    modelspace.add_lwpolyline(
        [(0, 0), (420, 0), (420, 297), (0, 297)],
        close=True,
        dxfattribs={"layer": "FRAME"},
    )
    modelspace.add_lwpolyline(
        [(60, 100), (180, 100), (180, 180), (60, 180)],
        close=True,
        dxfattribs={"layer": "OUTLINE"},
    )
    modelspace.add_circle((75, 115), 4.5, dxfattribs={"layer": "OUTLINE"})
    modelspace.add_line((65, 115), (85, 115), dxfattribs={"layer": "CENTER"})
    modelspace.add_linear_dim(
        base=(60, 90),
        p1=(60, 100),
        p2=(180, 100),
        dxfattribs={"layer": "DIM"},
    ).render()
    for index, text in enumerate(("图号 W4-001", "名称 安装板", "材料 Q235B", "比例 1:1", "单位 mm")):
        modelspace.add_text(text, dxfattribs={"layer": "TEXT", "height": 3}).set_placement((240, 15 + index * 5))
    document.saveas(source)

    report = inspect_dxf(source)

    assert report["trueDimensionEntityCount"] == 1
    assert report["frameCandidates"][0]["width"] == 420
    assert report["engineeringChecks"]["hasTitleBlockEvidence"] is True
    assert report["engineeringChecks"]["hasHoleCenters"] is True
    assert report["evaluation"]["status"] == "pass"


def test_headless_backend_rejects_dwg(tmp_path):
    source = tmp_path / "drawing.dwg"
    source.write_bytes(b"not-a-dwg")
    with pytest.raises(ValueError, match="只接受 DXF"):
        inspect_dxf(source)


def _checklist_fixture(tmp_path, *, paper_layout=False):
    source = tmp_path / "drawing.dxf"
    document = ezdxf.new("R2018", units=4)
    for name, weight in (("SHEET", 50), ("LABELS", 25), ("SIZE", 25)):
        document.layers.add(name, lineweight=weight)
    template = {
        "name": "A3 纵向项目模板",
        "sheet": {"size": "A3", "orientation": "portrait", "insetsMm": [10, 5, 10, 5]},
        "frameLayers": ["sheet"], "titleLayers": ["LABELS"], "titleFields": ["图号", "比例"],
        "titleSizeMm": [75, 20], "titleAnchorMm": [202, 0], "minDimensions": 2, "expectedDimensionValues": [120, 48],
        "dimensionLayers": ["SIZE"], "minTitleTextHeightMm": 3,
        "lineweightsMm": {"SHEET": 0.5}, "scaleLabel": "2:1",
    }
    layout = document.modelspace()
    if paper_layout:
        layout = document.layouts.new("Sheet A3")
        layout.dxf_layout.dxf.plot_paper_units = 1
        template["layout"] = layout.name
    layout.add_lwpolyline([(0, 0), (277, 0), (277, 410), (0, 410)], close=True, dxfattribs={"layer": "SHEET"})
    title = document.blocks.new("TITLE")
    title.add_lwpolyline([(0, 0), (75, 0), (75, 20), (0, 20)], close=True)
    title.add_text("图号 012", dxfattribs={"height": 3.5}).set_placement((2, 4))
    title.add_attdef("SCALE", (2, 10), dxfattribs={"height": 3.5})
    layout.add_blockref("TITLE", (202, 0), dxfattribs={"layer": "LABELS"}).add_auto_attribs({"SCALE": "比例 2:1"})
    layout.add_aligned_dim(p1=(10, 70), p2=(130, 70), distance=12, dxfattribs={"layer": "SIZE"}).render()
    layout.add_aligned_dim(p1=(20, 70), p2=(20, 118), distance=12, dxfattribs={"layer": "SIZE"}).render()
    document.saveas(source)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
    return source, path


@pytest.mark.parametrize("paper_layout", [False, True])
def test_template_pass_reports_layout_and_retains_manual_review(tmp_path, paper_layout):
    source, template = _checklist_fixture(tmp_path, paper_layout=paper_layout)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    checklist = inspect_dxf(source, template=template)["drawingChecklist"]
    assert checklist["layout"] == ("Sheet A3" if paper_layout else "Model")
    assert checklist["machineStatus"] == "pass"
    assert checklist["status"] == "review_required"
    assert checklist["sourceSha256"] == digest
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert checklist["manualChecks"][0]["id"] == "dimension_clearance"
    assert all(check["status"] == "review_required" for check in checklist["manualChecks"])
    assert "drawingChecklist" not in inspect_dxf(source)


def test_template_rejects_wrong_sheet_and_reports_failure_via_cli(tmp_path):
    source, template = _checklist_fixture(tmp_path)
    profile = json.loads(template.read_text(encoding="utf-8"))
    profile["sheet"]["orientation"] = "landscape"
    template.write_text(json.dumps(profile), encoding="utf-8")
    output = tmp_path / "report.json"
    assert main([str(source), "--template", str(template), "--json", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))["drawingChecklist"]
    assert report["status"] == "failed"
    assert next(check for check in report["checks"] if check["id"] == "sheet_frame")["status"] == "fail"


def test_template_rejects_wrong_dimension_and_hidden_title_layer(tmp_path):
    source, template = _checklist_fixture(tmp_path)
    document = ezdxf.readfile(source)
    document.layers.get("LABELS").off()
    dimension = document.modelspace().query("DIMENSION")[-1]
    dimension.dxf.defpoint3 = (20, 119)
    dimension.dxf.text = "48"
    document.saveas(source)
    checklist = inspect_dxf(source, template=template)["drawingChecklist"]
    checks = {check["id"]: check for check in checklist["checks"]}
    assert checks["expected_dimension_values"]["missing"] == [48]
    assert checks["dimensions"]["overrides"] == [dimension.dxf.handle]
    assert checks["title_fields"]["status"] == "fail"


def test_template_rejects_unknown_fields_and_output_collision(tmp_path):
    source, template = _checklist_fixture(tmp_path)
    profile = json.loads(template.read_text(encoding="utf-8"))
    profile["minDimension"] = 4
    template.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="minDimension"):
        inspect_dxf(source, template=template)
    with pytest.raises(SystemExit, match="2"):
        main([str(source), "--json", str(source)])
