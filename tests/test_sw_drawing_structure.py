"""工程图结构复核无 COM 测试。"""
from pathlib import Path

import pytest

from scripts.sw_drawing import (
    add_a3_sheet,
    create_adaptive_standard_views,
    estimate_dimension_text_box,
    inspect_drawing_structure,
    insert_dimensions,
    plan_standard_view_layout,
    select_drawing_template,
    setup_current_sheet_as_a3,
)
from scripts.sw_review import review_drawing_layout


class FakeDimension:
    Name = "D1"
    Type = 2

    def GetText(self, _index):
        return "25"

    def GetAnnotation(self):
        return self

    def GetBox(self):
        return (0.05, 0.05, 0.0, 0.07, 0.06, 0.0)


class FakeView:
    Name = "Front"
    Type = 1
    ScaleRatio = (1.0, 2.0)

    def GetDisplayDimensions(self):
        return [FakeDimension()]

    def GetOutline(self):
        return (0.02, 0.03, 0.12, 0.15)

    def GetNotes(self):
        return []

    def GetTableAnnotations(self):
        return []


class FakeSheet:
    def GetViews(self):
        return [FakeView()]

    def GetTemplateName(self):
        return "A3.slddrt"


class FakeDrawing:
    def GetSheetNames(self):
        return ["Sheet1"]

    def GetSheet(self, _name):
        return FakeSheet()

    def GetCurrentSheet(self):
        return FakeSheet()


def test_inspect_drawing_structure_reports_views_dimensions_and_template():
    result = inspect_drawing_structure(FakeDrawing())
    assert result["status"] == "pass"
    assert result["view_count"] == 1
    assert result["dimension_count"] == 1
    assert result["template_path"] == "A3.slddrt"
    assert result["checks"][0]["status"] == "pass"
    assert result["paper_size"] == "A3"
    assert result["view_outline_count"] == 1
    assert result["dimension_box_count"] == 1


def test_inspect_drawing_structure_blocks_empty_drawing():
    class Empty:
        def GetSheetNames(self):
            return []

        def GetCurrentSheet(self):
            return None

    result = inspect_drawing_structure(Empty())
    assert result["status"] == "blocked"
    assert result["error_code"] == "DRAWING_VIEWS_MISSING"
    assert result["retryable"] is True


def test_insert_dimensions_prefers_document_api():
    """@brief SW2024 动态代理把尺寸接口放在文档对象时仍可调用。"""
    class Document:
        Extension = object()

        def InsertModelAnnotations3(self, *args):
            assert args == (0, 32768, True, False, False, False)
            return True

    assert insert_dimensions(Document()) is True


def test_insert_dimensions_prefers_sw2024_array_api():
    """@brief SW2024 InsertModelAnnotations4 返回实际注释数组时优先使用它。"""
    class Document:
        Extension = object()

        def InsertModelAnnotations4(self, *args):
            assert args == (0, 32768, True, False, False, False, False, False)
            return [object()]

    result = insert_dimensions(Document())
    assert isinstance(result, list) and len(result) == 1  # 返回实际注释数组


def test_insert_dimensions_returns_false_when_both_com_surfaces_are_missing():
    """@brief 缺少尺寸接口时返回可审计失败，不抛出未处理异常。"""
    class Document:
        Extension = object()

    assert insert_dimensions(Document()) is False


def test_select_drawing_template_requires_existing_a3_gbt_candidate(tmp_path):
    """@brief A3 选择不得把不存在或非国标命名模板当作通过。"""
    generic = tmp_path / "A3-generic.slddrt"
    gbt = tmp_path / "A3-GB-T-title-block.slddrt"
    generic.write_text("generic", encoding="utf-8")
    gbt.write_text("gbt", encoding="utf-8")

    result = select_drawing_template([generic, gbt, tmp_path / "A3-GB-T-missing.slddrt"])

    assert result["status"] == "pass"
    assert result["selected"] == str(gbt.resolve())
    assert result["gbt_content_verified"] is False
    assert result["manual_review_required"] is True


def test_select_drawing_template_prefers_simplified_chinese_gbt_candidate(tmp_path):
    """@brief 同版式模板并存时应优先中文简体 GB/T 候选。"""
    english_dir = tmp_path / "english" / "sheetformat"
    chinese_dir = tmp_path / "Chinese-Simplified" / "sheetformat"
    english_dir.mkdir(parents=True)
    chinese_dir.mkdir(parents=True)
    english = english_dir / "a3 - gb.slddrt"
    chinese = chinese_dir / "a3 - gb.slddrt"
    english.write_text("english", encoding="utf-8")
    chinese.write_text("chinese", encoding="utf-8")

    result = select_drawing_template([english, chinese])

    assert result["status"] == "pass"
    assert result["selected"] == str(chinese.resolve())
    assert next(item for item in result["candidates"] if item["path"] == str(chinese.resolve()))["localized_candidate"] is True


def test_a3_layout_keeps_three_views_above_title_block():
    """@brief A3 自适应布局必须保持三视图分离且不侵入底部标题栏。"""
    layout = plan_standard_view_layout((0.160, 0.080, 0.050), paper_size="A3")
    report = review_drawing_layout({
        "views": [{"name": item["name"], "box": item["box"]} for item in layout["views"]],
        "dimensions": [{"name": "D1", "view": "*Front", "box": {"left": 0.01, "bottom": 0.20, "right": 0.02, "top": 0.21}}],
        "title_block": {"box": layout["title_block_box"]},
    })

    assert layout["paper_size"] == "A3"
    assert len(layout["views"]) == 3
    assert all(item["box"]["bottom"] > layout["title_block_box"]["top"] for item in layout["views"])
    assert report["status"] == "pass"


def test_layout_uses_dynamic_scale_for_oversized_model():
    """@brief 超大模型必须继续缩小比例，不能以最小预设比例越界。"""
    layout = plan_standard_view_layout((100.0, 50.0, 20.0), paper_size="A3")

    assert layout["scale"] < 0.01
    assert max(item["box"]["right"] for item in layout["views"]) <= layout["working_area"]["right"] + 1e-12
    assert max(item["box"]["top"] for item in layout["views"]) <= layout["working_area"]["top"] + 1e-12


def test_create_adaptive_views_uses_planned_positions_and_scale():
    """@brief COM 封装必须逐个创建视图并应用相同比例。"""
    class View:
        ScaleRatio = None

    class Drawing:
        def __init__(self):
            self.calls = []
            self.views = []

        def CreateDrawViewFromModelView3(self, path, name, x, y, z):
            self.calls.append((path, name, x, y, z))
            view = View()
            self.views.append(view)
            return view

    drawing = Drawing()
    layout = plan_standard_view_layout((0.1, 0.05, 0.03))
    result = create_adaptive_standard_views(drawing, "part.sldprt", layout)

    assert result["status"] == "pass"
    assert result["view_count"] == 3
    assert [call[1] for call in drawing.calls] == ["*Front", "*Top", "*Right"]
    assert all(view.ScaleRatio == tuple(layout["scale_ratio"]) for view in drawing.views)


def test_create_adaptive_views_falls_back_to_native_third_angle_and_maps_orientation():
    """@brief 单视图 API 静默失败时必须按真实方向映射原生三视图。"""
    class View:
        def __init__(self, orientation):
            self.orientation = orientation
            self.Name = f"Drawing View {orientation}"
            self.ScaleRatio = None
            self.Position = None
            self.UseParentScale = True

        def GetOrientationName(self):
            return self.orientation

    class Sheet:
        def __init__(self, drawing):
            self.drawing = drawing

        def GetViews(self):
            return self.drawing.views

    class Drawing:
        def __init__(self):
            self.views = []
            self.native_calls = []

        def CreateDrawViewFromModelView3(self, *_args):
            return None

        def Create3rdAngleViews2(self, path):
            self.native_calls.append(path)
            self.views = [View("*Front"), View("*Top"), View("*Right")]
            return True

        def GetCurrentSheet(self):
            return Sheet(self)

        def ForceRebuild3(self, _top_only):
            return True

    drawing = Drawing()
    layout = plan_standard_view_layout((0.1, 0.05, 0.03))
    result = create_adaptive_standard_views(drawing, "part.sldprt", layout)

    assert result["status"] == "pass"
    assert result["backend"] == "native_3rd_angle"
    assert result["view_count"] == 3
    assert drawing.native_calls == ["part.sldprt"]
    expected_centers = {item["name"]: tuple(item["center"]) for item in layout["views"]}
    for view in drawing.views:
        assert view.Position == expected_centers[view.GetOrientationName()]
        assert view.ScaleRatio == tuple(layout["scale_ratio"])


def test_add_a3_sheet_blocks_without_gbt_template(tmp_path):
    """@brief 严格国标模式缺模板时不得调用 NewSheet4。"""
    class Drawing:
        def NewSheet4(self, *_args):
            raise AssertionError("缺少模板时不得创建工程图页")

    result = add_a3_sheet(Drawing(), [Path(tmp_path / "A3-generic.slddrt")])

    assert result["status"] == "blocked"
    assert result["error_code"] == "DRAWING_GBT_TEMPLATE_MISSING"


def test_setup_current_sheet_as_a3_uses_verified_signature(tmp_path):
    """@brief 当前页配置必须使用本机 Interop 核对过的 SetupSheet6 参数顺序。"""
    template = tmp_path / "a3 - gb.slddrt"
    template.write_text("gb", encoding="utf-8")

    class Sheet:
        def GetName(self):
            return "Sheet1"

    class Drawing:
        def __init__(self):
            self.args = None

        def GetCurrentSheet(self):
            return Sheet()

        def SetupSheet6(self, *args):
            self.args = args
            return True

    drawing = Drawing()
    result = setup_current_sheet_as_a3(drawing, [template])

    assert result["status"] == "pass"
    assert drawing.args[:7] == ("Sheet1", 6, 12, 1.0, 1.0, True, str(template.resolve()))
    assert len(drawing.args) == 17


def test_review_drawing_layout_reports_dimension_and_title_collisions():
    """@brief 尺寸互压及视图侵入标题栏必须返回稳定错误码。"""
    result = review_drawing_layout({
        "views": [
            {"name": "Front", "box": {"left": 0.01, "bottom": 0.01, "right": 0.10, "top": 0.10}},
            {"name": "Top", "box": {"left": 0.01, "bottom": 0.13, "right": 0.10, "top": 0.20}},
            {"name": "Right", "box": {"left": 0.13, "bottom": 0.08, "right": 0.20, "top": 0.15}},
        ],
        "dimensions": [
            {"name": "D1", "view": "Front", "box": {"left": 0.21, "bottom": 0.04, "right": 0.24, "top": 0.06}},
            {"name": "D2", "view": "Front", "box": {"left": 0.22, "bottom": 0.05, "right": 0.25, "top": 0.07}},
        ],
        "title_block": {"box": {"left": 0.0, "bottom": 0.0, "right": 0.18, "top": 0.05}},
    })

    assert result["status"] == "review_required"
    assert result["error_code"] == "DRAWING_LAYOUT_COLLISION_DETECTED"
    assert {item["code"] for item in result["findings"]} >= {
        "DRAWING_VIEW_TITLE_BLOCK_INTRUSION",
        "DRAWING_DIMENSION_TEXT_OVERLAP",
    }


def test_review_drawing_layout_never_passes_incomplete_boxes():
    """@brief 缺少 COM 包围盒时必须要求人工复核，不能误报无碰撞。"""
    result = review_drawing_layout({
        "views": [{"name": name, "box": None} for name in ("Front", "Top", "Right")],
        "dimensions": [{"name": "D1", "box": None}],
        "title_block": {"box": None},
    })

    assert result["status"] == "review_required"
    assert result["error_code"] == "DRAWING_LAYOUT_EVIDENCE_INCOMPLETE"


def test_estimate_dimension_text_box_records_provenance_and_padding():
    """@brief 估算边界必须记录来源、置信度、格式参数和保守 padding。"""
    class TextFormat:
        CharHeight = 0.004
        WidthFactor = 0.8
        CharSpacingFactor = 1.1

    class Annotation:
        def GetPosition(self):
            return (0.120, 0.080, 0.0)

        def GetTextFormat(self, index):
            assert index == 0
            return TextFormat()

    class Dimension:
        def GetAnnotation(self):
            return Annotation()

        def GetText(self, index):
            return "120.00" if index == 0 else ""

    evidence = estimate_dimension_text_box(Dimension())

    assert evidence["source"] == "estimated"
    assert evidence["confidence"] == "medium"
    assert evidence["native_bounding_box_available"] is False
    assert evidence["position_m"] == [0.120, 0.080]
    assert evidence["padding_m"] >= 0.001
    assert evidence["box"]["left"] < 0.120 < evidence["box"]["right"]
    assert evidence["text_format"]["char_height_m"] == 0.004
    assert evidence["orientation_assumption"] == "unknown_angle_conservative_square_envelope"


def test_estimate_dimension_text_box_uses_placeholder_when_rendered_value_is_hidden():
    """@brief GetText 不返回主尺寸值时必须使用保守占位，不能估成零宽。"""
    class Annotation:
        def GetPosition(self):
            return (0.100, 0.100, 0.0)

    class Dimension:
        def GetAnnotation(self):
            return Annotation()

        def GetText(self, _index):
            return ""

    evidence = estimate_dimension_text_box(Dimension())

    assert evidence["confidence"] == "low"
    assert evidence["text_evidence"]["rendered_value_available"] is False
    assert evidence["text_evidence"]["source"] == "conservative_value_placeholder"
    assert evidence["estimated_unrotated_size_m"]["width"] > 0.01
    assert evidence["box"] is not None


def test_inspect_drawing_structure_uses_estimated_dimension_box_without_claiming_native():
    """@brief 缺原生 GetBox 时结构报告应保留 estimated 来源而不是冒充 native。"""
    class TextFormat:
        CharHeight = 0.0035
        WidthFactor = 1.0
        CharSpacingFactor = 1.0

    class Dimension:
        def GetText(self, index):
            return "80" if index == 0 else ""

        def GetAnnotation(self):
            return self

        def GetPosition(self):
            return (0.08, 0.12, 0.0)

        def GetTextFormat(self, index):
            assert index == 0
            return TextFormat()

    class View(FakeView):
        def GetDisplayDimensions(self):
            return [Dimension()]

    class Sheet(FakeSheet):
        def GetViews(self):
            return [View()]

    class Drawing(FakeDrawing):
        def GetSheet(self, _name):
            return Sheet()

        def GetCurrentSheet(self):
            return Sheet()

    result = inspect_drawing_structure(Drawing())
    dimension = result["dimensions"][0]

    assert dimension["box"] is not None
    assert dimension["box_source"] == "estimated"
    assert dimension["box_confidence"] == "medium"
    assert result["native_dimension_box_count"] == 0
    assert result["estimated_dimension_box_count"] == 1
    assert next(item for item in result["checks"] if item["id"] == "drawing-dimension-boxes")["status"] == "warning"


def test_review_estimated_dimension_boxes_requires_visual_review_even_without_collision():
    """@brief 估算边界无碰撞也不得升级为 pass。"""
    result = review_drawing_layout({
        "views": [
            {"name": "Front", "box": {"left": 0.01, "bottom": 0.08, "right": 0.09, "top": 0.15}},
            {"name": "Top", "box": {"left": 0.01, "bottom": 0.18, "right": 0.09, "top": 0.24}},
            {"name": "Right", "box": {"left": 0.13, "bottom": 0.08, "right": 0.20, "top": 0.15}},
        ],
        "dimensions": [{
            "name": "D1",
            "view": "Front",
            "box": {"left": 0.22, "bottom": 0.18, "right": 0.25, "top": 0.20},
            "box_source": "estimated",
            "box_confidence": "medium",
        }],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }, preview_evidence=[{"exists": True, "likely_blank": False}])

    assert result["status"] == "review_required"
    assert result["error_code"] == "DRAWING_LAYOUT_ESTIMATED_EVIDENCE_REQUIRES_VISUAL_REVIEW"
    assert result["evidence_summary"]["estimated_dimension_box_count"] == 1
    assert result["evidence_summary"]["pixel_preview_available"] is True
    assert result["evidence_summary"]["estimated_evidence_is_native"] is False


def test_review_estimated_overlap_is_risk_not_confirmed_collision():
    """@brief 估算边界相交必须标记为保守风险，而不是确定碰撞。"""
    result = review_drawing_layout({
        "views": [
            {"name": "Front", "box": {"left": 0.01, "bottom": 0.08, "right": 0.09, "top": 0.15}},
            {"name": "Top", "box": {"left": 0.01, "bottom": 0.18, "right": 0.09, "top": 0.24}},
            {"name": "Right", "box": {"left": 0.13, "bottom": 0.08, "right": 0.20, "top": 0.15}},
        ],
        "dimensions": [
            {"name": "D1", "view": "Front", "box": {"left": 0.22, "bottom": 0.18, "right": 0.25, "top": 0.20}, "box_source": "estimated", "box_confidence": "medium"},
            {"name": "D2", "view": "Front", "box": {"left": 0.24, "bottom": 0.19, "right": 0.27, "top": 0.21}, "box_source": "estimated", "box_confidence": "low"},
        ],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    })

    finding = next(item for item in result["findings"] if item["code"] == "DRAWING_DIMENSION_TEXT_OVERLAP")
    assert finding["evidence_source"] == "estimated"
    assert finding["confidence"] == "low"
    assert finding["severity"] == "warning"
    assert finding["confirmed_collision"] is False
    assert result["error_code"] == "DRAWING_LAYOUT_ESTIMATED_COLLISION_RISK"
    assert next(item for item in result["checks"] if item["id"] == "drawing-layout-collisions")["status"] == "warning"
