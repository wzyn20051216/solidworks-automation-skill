"""工程图子技能的无 COM 契约和审视测试。"""
from __future__ import annotations

from pathlib import Path

from scripts.drawing_spec import validate_drawing_spec
from scripts.sw_drawing import plan_standard_view_layout
from scripts.sw_drawing_review import review_drawing_artifacts


def _spec(**overrides):
    payload = {
        "schemaVersion": "1.0",
        "sourceModel": "C:/cad/plate.sldprt",
        "documentType": "part",
        "standard": "GB_T",
        "projection": "first_angle",
        "paperSize": "A3",
        "modelSizeMm": [120, 80, 12],
        "views": {"front": {}, "top": {}, "right": {}},
        "outputs": {"slddrw": True, "pdf": True, "report": True},
    }
    payload.update(overrides)
    return payload


def test_gbt_drawing_spec_defaults_are_explicit_and_valid():
    result = validate_drawing_spec(_spec())

    assert result["status"] == "pass"
    assert result["capability"] == "solidworks-engineering-drawing"


def test_gbt_third_angle_is_blocked():
    result = validate_drawing_spec(_spec(projection="third_angle"))

    assert result["status"] == "blocked"
    assert any(item["code"] == "DRAWING_GBT_PROJECTION_CONFLICT" for item in result["issues"])


def test_hole_requirement_requires_count_and_each_location():
    result = validate_drawing_spec(_spec(holeRequirements=[{
        "id": "H1",
        "specification": "M6通孔",
        "count": 4,
        "locationsMm": [[-20, -10], [20, -10]],
    }]))

    assert result["status"] == "blocked"
    assert any(item["code"] == "DRAWING_HOLE_REQUIREMENT_INCOMPLETE" for item in result["issues"])


def test_sheet_metal_without_flat_pattern_evidence_is_pilot():
    result = validate_drawing_spec(_spec(documentType="sheet_metal"))

    assert result["status"] == "pilot"
    assert any(item["code"] == "DRAWING_SHEET_METAL_FLAT_PATTERN_EVIDENCE_MISSING" for item in result["issues"])


def test_assembly_bom_requires_a_real_template(tmp_path: Path):
    result = validate_drawing_spec(_spec(documentType="assembly", bom={"required": True, "templatePath": str(tmp_path / "missing.sldbomtbt")}))

    assert result["status"] == "blocked"
    assert any(item["code"] == "DRAWING_BOM_TEMPLATE_MISSING" for item in result["issues"])


def test_first_angle_layout_places_top_below_and_right_left():
    layout = plan_standard_view_layout((0.12, 0.08, 0.012), paper_size="A3", projection="first_angle")
    by_name = {item["name"]: item for item in layout["views"]}

    assert layout["projection"] == "first_angle"
    assert by_name["*Top"]["center"][1] < by_name["*Front"]["center"][1]
    assert by_name["*Right"]["center"][0] < by_name["*Front"]["center"][0]


def test_review_requires_dimension_and_layout_evidence():
    structure = {
        "views": [
            {"name": "Front", "box": {"left": 0.20, "bottom": 0.10, "right": 0.32, "top": 0.18}},
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.02, "right": 0.32, "top": 0.08}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ],
        "dimensions": [],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(_spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front"}]), structure=structure)

    assert result["status"] == "review_required"
    assert any(item["code"] == "DRAWING_REQUIRED_DIMENSIONS_MISSING" for item in result["findings"])
