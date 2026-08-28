"""工程图子技能的无 COM 契约和审视测试。"""
from __future__ import annotations

from pathlib import Path

from scripts.drawing_spec import validate_drawing_spec
from scripts.sw_drawing import add_note, plan_standard_view_layout
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


def test_existing_model_dimension_switch_is_supported_by_schema():
    """@brief 兼容工程图工作流已公开使用的 insertModelDimensions 字段。"""
    result = validate_drawing_spec(_spec(insertModelDimensions=True))

    assert result["status"] == "pass"


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


def test_drawing_spec_rejects_schema_shape_errors_and_unknown_fields():
    """@brief JSON Schema 错误不能被业务层的部分手写检查漏放。"""
    result = validate_drawing_spec(_spec(unexpected=True, modelSizeMm=[120, "bad", 12]))

    assert result["status"] == "blocked"
    assert sum(item["code"] == "DRAWING_SPEC_SCHEMA_INVALID" for item in result["issues"]) >= 2


def test_first_angle_layout_places_top_below_and_right_left():
    layout = plan_standard_view_layout((0.12, 0.08, 0.012), paper_size="A3", projection="first_angle")
    by_name = {item["name"]: item for item in layout["views"]}

    assert layout["projection"] == "first_angle"
    assert by_name["*Top"]["center"][1] < by_name["*Front"]["center"][1]
    assert by_name["*Right"]["center"][0] < by_name["*Front"]["center"][0]


def test_note_creation_reads_back_text_and_sheet_position():
    """@brief 不能仅以 InsertNote 未抛异常认定注释真实落图。"""
    class Annotation:
        def __init__(self):
            self.position = None

        def SetPosition2(self, x, y, z):
            self.position = (x, y, z)
            return True

        def GetPosition(self):
            return self.position

    class Note:
        def __init__(self, text):
            self.text = text
            self.annotation = Annotation()

        def GetText(self):
            return self.text

        def GetAnnotation(self):
            return self.annotation

        def GetExtent(self):
            return (0.02, 0.018, 0.0, 0.05, 0.023, 0.0)

    class Drawing:
        def InsertNote(self, text):
            return Note(text)

    result = add_note(Drawing(), 0.02, 0.02, "Material: ABS")

    assert result["status"] == "pass"
    assert result["verified"] is True
    assert result["text_evidence"] == "Material: ABS"
    assert result["position_evidence_m"] == [0.02, 0.02, 0.0]


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


def test_review_names_missing_model_dimensions_when_auto_insert_is_requested():
    """@brief 自动插入尺寸失败时报告明确原因，不把它归因于包围盒限制。"""
    structure = {
        "views": [
            {"name": "Front", "box": {"left": 0.20, "bottom": 0.10, "right": 0.32, "top": 0.18}},
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.08, "right": 0.32, "top": 0.095}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ],
        "dimensions": [],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(_spec(insertModelDimensions=True), structure=structure)

    assert result["status"] == "blocked"
    assert any(item["code"] == "DRAWING_MODEL_DIMENSIONS_MISSING" for item in result["findings"])


def test_final_pdf_dimension_boxes_replace_com_estimates_for_delivery_pass(tmp_path: Path):
    """@brief COM 无文字框时，最终 PDF 的精确尺寸文字框可完成自动交付复核。"""
    import fitz

    pdf_path = tmp_path / "drawing.pdf"
    document = fitz.open()
    page = document.new_page(width=1190.55, height=841.89)
    # A3 横向坐标换算：m -> pt；PDF Y 轴和 SolidWorks 图纸 Y 轴方向相反。
    page.insert_text((456.3, 598.2), "120", fontsize=12)
    page.insert_text((100, 700), "Material: ABS", fontsize=12)
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
            "kind": "overall",
            "text": "",
            "box": {"left": 0.150, "bottom": 0.075, "right": 0.171, "top": 0.096},
            "box_source": "estimated",
            "box_confidence": "low",
            "box_evidence": {"position_m": [0.161, 0.086]},
        }],
        "notes": [{"sheet": "Sheet1", "text": "Material: ABS", "position_m": [0.02, 0.02, 0.0]}],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(
        _spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front"}], notes=["Material: ABS"]),
        structure=structure,
        pdf_path=pdf_path,
        preview_evidence=[{"exists": True, "likely_blank": False}],
    )

    assert result["status"] == "pass"
    assert result["manual_review_required"] is False
    assert result["pdf_dimension_rendering"]["status"] == "pass"
    assert result["note_evidence"]["status"] == "pass"
    assert result["layout"]["evidence_summary"]["rendered_dimension_box_count"] == 1


def test_required_dimension_id_does_not_use_substring_matching():
    """@brief D1 不能被 D10 或 110 的文字误判为已满足。"""
    structure = {
        "views": [{"name": "Front", "box": {"left": 0.1, "bottom": 0.1, "right": 0.2, "top": 0.2}}],
        "dimensions": [{"name": "D10@Front", "view": "Front", "kind": "overall", "text": "110"}],
    }

    result = review_drawing_artifacts(
        _spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front", "valueMm": 10}]),
        structure=structure,
    )

    assert result["dimension_evidence"]["status"] == "fail"
    assert result["dimension_evidence"]["checks"][0]["mismatches"] == ["id"]


def test_required_dimension_checks_view_kind_and_value():
    """@brief ID 相同但视图、种类或数值错误时仍必须失败。"""
    structure = {
        "views": [{"name": "Top", "box": {"left": 0.1, "bottom": 0.1, "right": 0.2, "top": 0.2}}],
        "dimensions": [{"name": "D1@Top", "view": "Top", "kind": "diameter", "text": "20"}],
    }

    result = review_drawing_artifacts(
        _spec(requiredDimensions=[{"id": "D1", "kind": "overall", "view": "Front", "valueMm": 10}]),
        structure=structure,
    )

    assert result["dimension_evidence"]["status"] == "fail"
    assert set(result["dimension_evidence"]["checks"][0]["mismatches"]) == {"view", "kind", "valueMm"}


def test_m8_hole_requirement_is_not_satisfied_by_other_hole_groups():
    """@brief M8 螺纹要求不能由 M3/M4 文字或足够多的无关孔组放行。"""
    requirement = {
        "id": "H-M8",
        "specification": "M8",
        "count": 2,
        "locationsMm": [[10, 10, 0], [30, 10, 0]],
    }
    model_evidence = {
        "hole_groups": [
            {"position_mm": [10, 10, 0], "diameters_mm": [2.5], "thread": "M3"},
            {"position_mm": [30, 10, 0], "diameters_mm": [3.3], "thread": "M4"},
        ]
    }

    result = review_drawing_artifacts(_spec(holeRequirements=[requirement]), structure={}, model_evidence=model_evidence)

    assert result["hole_evidence"]["status"] == "fail"
    assert result["hole_evidence"]["checks"][0]["matched_count"] == 0


def test_diameter_holes_require_exact_count_positions_and_diameter():
    """@brief 光孔按孔径和逐孔位置一一匹配，不能重复使用同一孔组。"""
    requirement = {
        "id": "H-D8",
        "specification": "Ø8",
        "count": 2,
        "locationsMm": [[10, 10, 0], [30, 10, 0]],
    }
    model_evidence = {
        "hole_groups": [
            {"position_mm": [10.04, 10, 0], "diameters_mm": [8.0]},
            {"position_mm": [30, 10, 0], "diameters_mm": [8.04]},
        ]
    }

    result = review_drawing_artifacts(_spec(holeRequirements=[requirement]), structure={}, model_evidence=model_evidence)

    assert result["hole_evidence"]["status"] == "pass"
    assert result["hole_evidence"]["checks"][0]["matched_count"] == 2


def test_general_table_cannot_satisfy_required_bom():
    """@brief 任意普通表格不能冒充有数据行的 BOM。"""
    result = review_drawing_artifacts(
        _spec(documentType="assembly", bom={"required": True, "templatePath": __file__}),
        structure={"tables": [{"type": 0, "kind": "general", "row_count": 4}]},
    )

    assert result["bom_evidence"]["status"] == "fail"
    assert result["bom_evidence"]["tables"] == []


def test_title_block_candidate_without_content_is_not_a_pass():
    """@brief 仅识别到图框模板不能证明标题栏字段已填写。"""
    result = review_drawing_artifacts(
        _spec(titleBlock={"required": True, "format": "GB_T"}),
        structure={"title_block": {"candidate": True, "gbt_candidate": True, "content_verified": False}},
    )

    assert result["title_block_evidence"]["status"] == "review_required"
    assert result["title_block_evidence"]["content_verified"] is False


def test_note_absent_from_final_pdf_blocks_delivery(tmp_path: Path):
    """@brief COM 中存在但 PDF 缺失的注释不能作为交付证据。"""
    import fitz

    pdf_path = tmp_path / "drawing.pdf"
    document = fitz.open()
    document.new_page(width=1190.55, height=841.89)
    document.save(pdf_path)
    document.close()
    structure = {
        "sheets": ["Sheet1"],
        "sheet_size": {"width_m": 0.42, "height_m": 0.297},
        "views": [],
        "dimensions": [],
        "notes": [{"sheet": "Sheet1", "text": "Material: ABS", "position_m": [0.02, 0.02, 0.0]}],
        "title_block": {"candidate": True},
    }

    result = review_drawing_artifacts(_spec(notes=["Material: ABS"]), structure=structure, pdf_path=pdf_path)

    assert result["status"] == "blocked"
    assert result["note_evidence"]["missing_pdf"] == ["Material: ABS"]
    assert result["note_evidence"]["error_code"] == "DRAWING_NOTE_EVIDENCE_INCOMPLETE"


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
