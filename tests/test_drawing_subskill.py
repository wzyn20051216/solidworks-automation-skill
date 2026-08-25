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
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.08, "right": 0.32, "top": 0.095}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ],
        "dimensions": [],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(_spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front"}]), structure=structure)

    assert result["status"] == "blocked"
    assert any(item["code"] == "DRAWING_REQUIRED_DIMENSIONS_MISSING" for item in result["findings"])


def test_final_pdf_dimension_boxes_replace_com_estimates_for_delivery_pass(tmp_path: Path):
    """@brief COM 无文字框时，最终 PDF 的精确尺寸文字框可完成自动交付复核。"""
    import fitz

    pdf_path = tmp_path / "drawing.pdf"
    document = fitz.open()
    page = document.new_page(width=1190.55, height=841.89)
    # A3 横向坐标换算：m -> pt；PDF Y 轴和 SolidWorks 图纸 Y 轴方向相反。
    page.insert_text((456.3, 598.2), "120", fontsize=12)
    document.save(pdf_path)
    document.close()
    structure = {
        "sheets": ["Sheet1"],
        "sheet_size": {"width_m": 0.42, "height_m": 0.297},
        "views": [
            {"name": "Front", "box": {"left": 0.20, "bottom": 0.10, "right": 0.32, "top": 0.18}},
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.08, "right": 0.32, "top": 0.095}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ],
        "dimensions": [{
            "sheet": "Sheet1",
            "name": "D1@Front",
            "text": "",
            "box": {"left": 0.150, "bottom": 0.075, "right": 0.171, "top": 0.096},
            "box_source": "estimated",
            "box_confidence": "low",
            "box_evidence": {"position_m": [0.161, 0.086]},
        }],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(
        _spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front"}]),
        structure=structure,
        pdf_path=pdf_path,
        preview_evidence=[{"exists": True, "likely_blank": False}],
    )

    assert result["status"] == "pass"
    assert result["manual_review_required"] is False
    assert result["pdf_dimension_rendering"]["status"] == "pass"
    assert result["layout"]["evidence_summary"]["rendered_dimension_box_count"] == 1


def test_unmatched_final_pdf_dimension_keeps_review_gate(tmp_path: Path):
    """@brief 无法将最终文字框关联回 COM 尺寸时，不得放行。"""
    import fitz

    pdf_path = tmp_path / "drawing.pdf"
    document = fitz.open()
    page = document.new_page(width=1190.55, height=841.89)
    page.insert_text((100, 100), "120", fontsize=12)
    document.save(pdf_path)
    document.close()
    structure = {
        "sheets": ["Sheet1"],
        "sheet_size": {"width_m": 0.42, "height_m": 0.297},
        "views": [
            {"name": "Front", "box": {"left": 0.20, "bottom": 0.10, "right": 0.32, "top": 0.18}},
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.08, "right": 0.32, "top": 0.095}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ],
        "dimensions": [{
            "sheet": "Sheet1",
            "name": "D1@Front",
            "text": "",
            "box": {"left": 0.150, "bottom": 0.075, "right": 0.171, "top": 0.096},
            "box_source": "estimated",
            "box_evidence": {"position_m": [0.161, 0.086]},
        }],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(_spec(), structure=structure, pdf_path=pdf_path)

    assert result["status"] == "review_required"
    assert result["error_code"] == "DRAWING_PDF_DIMENSION_MATCH_INCOMPLETE"
