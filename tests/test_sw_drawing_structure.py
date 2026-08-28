"""工程图结构复核无 COM 测试。"""
from pathlib import Path

import pytest

from scripts.sw_drawing import (
    add_a3_sheet,
    auto_arrange_drawing_dimensions,
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


def test_auto_arrange_dimensions_calls_official_api_per_view():
    """@brief 每个视图至少两个尺寸时应调用官方 AutoArrange 枚举。"""
    class Annotation:
        def __init__(self):
            self.selected = False

        def Select2(self, append, mark):
            assert mark == 0
            self.selected = True
            return True

    class Dimension:
        def __init__(self):
            self.annotation = Annotation()

        def GetAnnotation(self):
            return self.annotation

    class View(FakeView):
        def GetDisplayDimensions(self):
            return [Dimension(), Dimension()]

    class Sheet(FakeSheet):
        def GetViews(self):
            return [View()]

    class Extension:
        def __init__(self):
            self.calls = []

        def AlignDimensions(self, mode, spacing):
            self.calls.append((mode, spacing))
            return True

    class Drawing(FakeDrawing):
        def __init__(self):
            self.Extension = Extension()

        def GetSheet(self, _name):
            return Sheet()

        def ClearSelection2(self, _all):
            return True

        def ForceRebuild3(self, _top_only):
            return True

        def GraphicsRedraw2(self):
            return True

    drawing = Drawing()
    result = auto_arrange_drawing_dimensions(drawing, spacing_m=0.008)

    assert result["status"] == "pass"
    assert result["method"] == "IModelDocExtension.AlignDimensions"
    assert result["enum_value"] == 0
    assert result["selected_dimension_count"] == 2
    assert drawing.Extension.calls == [(0, 0.008)]
    assert result["manual_review_required"] is True


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


def test_inspect_drawing_structure_reads_real_bom_type_cells_and_configuration():
    """@brief BOM 证据必须包含官方表类型、数据行和引用配置。"""
    class BomFeature:
        Configuration = "Default"

    class BomTable:
        Type = 2
        RowCount = 2
        ColumnCount = 3
        Title = "材料明细表"

        def __init__(self):
            self.BomFeature = BomFeature()

        def DisplayedText2(self, row, column, include_hidden):
            assert include_hidden is False
            return (("序号", "零件号", "数量"), ("1", "PLATE-01", "2"))[row][column]

        def GetAnnotation(self):
            return None

    class View(FakeView):
        def GetTableAnnotations(self):
            return [BomTable()]

    class Sheet(FakeSheet):
        def GetViews(self):
            return [View()]

    class Drawing(FakeDrawing):
        def GetSheet(self, _name):
            return Sheet()

    result = inspect_drawing_structure(Drawing())

    assert result["tables"][0]["kind"] == "bom"
    assert result["tables"][0]["row_count"] == 2
    assert result["tables"][0]["configuration"] == "Default"
    assert result["tables"][0]["cells"][1] == ["1", "PLATE-01", "2"]


def test_inspect_drawing_structure_maps_blank_projected_orientations_semantically():
    """@brief SW2026 投影视图方向名为空时，按基准关系与位置回读 front/top/right。"""
    class View:
        ScaleRatio = (1.0, 1.0)

        def __init__(self, name, orientation, position, base=None):
            self.Name = name
            self.Type = 7 if base is None else 4
            self.Position = position
            self.orientation = orientation
            self.base = base

        def GetOrientationName(self):
            return self.orientation

        def GetBaseView(self):
            return self.base

        def GetOutline(self):
            x, y = self.Position
            return (x - 0.02, y - 0.01, x + 0.02, y + 0.01)

        def GetDisplayDimensions(self):
            return []

        def GetNotes(self):
            return []

        def GetTableAnnotations(self):
            return []

    front = View("工程图视图1", "*前视", (0.15, 0.13))
    top = View("工程图视图2", "", (0.15, 0.22), front)
    right = View("工程图视图3", "", (0.26, 0.13), front)

    class Sheet(FakeSheet):
        def GetViews(self):
            return [front, top, right]

    class Drawing(FakeDrawing):
        def GetSheet(self, _name):
            return Sheet()

    result = inspect_drawing_structure(Drawing())

    assert {item["name"]: item["semantic_view"] for item in result["views"]} == {
        "工程图视图1": "front",
        "工程图视图2": "top",
        "工程图视图3": "right",
    }


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


def test_create_adaptive_first_angle_views_repositions_native_third_angle_fallback():
    """@brief SW 缺少第一角 API 时仍按第一角 DrawingSpec 回读并重排三视图。"""

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

        def CreateDrawViewFromModelView3(self, *_args):
            return None

        def Create3rdAngleViews2(self, _path):
            self.views = [View("*Front"), View("*Top"), View("*Right")]
            return True

        def GetCurrentSheet(self):
            return Sheet(self)

        def ForceRebuild3(self, _top_only):
            return True

    drawing = Drawing()
    layout = plan_standard_view_layout((0.1, 0.05, 0.03), projection="first_angle")
    result = create_adaptive_standard_views(drawing, "part.sldprt", layout)

    by_orientation = {view.orientation: view for view in drawing.views}
    assert result["status"] == "pass"
    assert result["backend"] == "native_first_angle_via_3rd_angle"
    assert by_orientation["*Top"].Position[1] < by_orientation["*Front"].Position[1]
    assert by_orientation["*Right"].Position[0] < by_orientation["*Front"].Position[0]
    assert result["view_count"] == 3
    expected_centers = {item["name"]: tuple(item["center"]) for item in layout["views"]}
    for view in drawing.views:
        assert view.Position == expected_centers[view.GetOrientationName()]
        assert view.ScaleRatio == tuple(layout["scale_ratio"])


def test_create_adaptive_views_refines_spacing_from_native_outlines():
    """@brief 实际投影包围盒大于模型估算时，必须二次排布并消除视图重叠。"""

    class View:
        def __init__(self, orientation, width, height):
            self.orientation = orientation
            self.Name = f"Drawing View {orientation}"
            self.width = width
            self.height = height
            self.Position = (0.0, 0.0)
            self.ScaleRatio = None
            self.UseParentScale = True

        def GetOrientationName(self):
            return self.orientation

        def GetOutline(self):
            x, y = self.Position
            return (x - self.width / 2, y - self.height / 2, x + self.width / 2, y + self.height / 2)

    class Sheet:
        def __init__(self, drawing):
            self.drawing = drawing

        def GetViews(self):
            return self.drawing.views

    class Drawing:
        def __init__(self):
            self.views = []

        def CreateDrawViewFromModelView3(self, *_args):
            return None

        def Create3rdAngleViews2(self, _path):
            self.views = [
                View("*Front", 0.100, 0.050),
                View("*Top", 0.100, 0.120),
                View("*Right", 0.120, 0.050),
            ]
            return True

        def GetCurrentSheet(self):
            return Sheet(self)

        def ForceRebuild3(self, _top_only):
            return True

    drawing = Drawing()
    layout = plan_standard_view_layout((0.1, 0.05, 0.03), projection="first_angle")
    result = create_adaptive_standard_views(drawing, "part.sldprt", layout)

    by_orientation = {view.orientation: view for view in drawing.views}
    front = by_orientation["*Front"].GetOutline()
    right = by_orientation["*Right"].GetOutline()
    assert result["status"] == "pass"
    assert result["layout_refinement"]["adjustments"]
    assert right[2] + layout["gap_m"] <= front[0] + 1e-9


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


def test_review_drawing_layout_checks_note_collisions_and_missing_boxes():
    """@brief 注释侵入视图或缺少边界时不能被当作无碰撞。"""
    result = review_drawing_layout({
        "views": [
            {"name": "Front", "sheet": "Sheet1", "box": {"left": 0.10, "bottom": 0.10, "right": 0.20, "top": 0.20}},
            {"name": "Top", "sheet": "Sheet1", "box": {"left": 0.10, "bottom": 0.23, "right": 0.20, "top": 0.29}},
            {"name": "Right", "sheet": "Sheet1", "box": {"left": 0.03, "bottom": 0.10, "right": 0.08, "top": 0.20}},
        ],
        "dimensions": [],
        "notes": [{
            "sheet": "Sheet1",
            "text": "Material: ABS",
            "box": {"left": 0.12, "bottom": 0.12, "right": 0.18, "top": 0.14},
        }],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    })

    assert result["status"] == "review_required"
    assert any(item["code"] == "DRAWING_NOTE_VIEW_INTRUSION" for item in result["findings"])

    missing_box = review_drawing_layout({
        "views": [
            {"name": "Front", "box": {"left": 0.10, "bottom": 0.10, "right": 0.20, "top": 0.20}},
            {"name": "Top", "box": {"left": 0.10, "bottom": 0.23, "right": 0.20, "top": 0.29}},
            {"name": "Right", "box": {"left": 0.03, "bottom": 0.10, "right": 0.08, "top": 0.20}},
        ],
        "dimensions": [],
        "notes": [{"text": "Material: ABS", "position_m": [0.02, 0.02, 0.0]}],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    })
    assert missing_box["status"] == "review_required"
    assert missing_box["error_code"] == "DRAWING_LAYOUT_EVIDENCE_INCOMPLETE"


def test_blank_section_view_label_is_not_reported_as_user_note_intrusion():
    """@brief 剖视图自带空标签框与所属视图相交不是技术注释侵入。"""
    result = review_drawing_layout({
        "views": [
            {"name": "Front", "type": 7, "sheet": "Sheet1", "box": {"left": 0.02, "bottom": 0.10, "right": 0.10, "top": 0.18}},
            {"name": "Top", "type": 4, "sheet": "Sheet1", "box": {"left": 0.02, "bottom": 0.20, "right": 0.10, "top": 0.27}},
            {"name": "Right", "type": 4, "sheet": "Sheet1", "box": {"left": 0.12, "bottom": 0.10, "right": 0.19, "top": 0.18}},
            {"name": "剖面视图 A-A", "type": 2, "sheet": "Sheet1", "box": {"left": 0.24, "bottom": 0.10, "right": 0.32, "top": 0.18}},
        ],
        "dimensions": [],
        "notes": [{
            "sheet": "Sheet1",
            "text": "",
            "box": {"left": 0.2636, "bottom": 0.175, "right": 0.2763, "top": 0.181},
        }],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    })

    assert not any(item["code"] == "DRAWING_NOTE_VIEW_INTRUSION" for item in result["findings"])


def test_inspection_marks_blank_section_owned_note_as_view_label():
    """@brief 新生成的结构证据应显式记录标签所属视图及标签类型。"""
    class Note:
        def GetText(self):
            return ""

        def GetExtent(self):
            return (0.24, 0.095, 0.0, 0.26, 0.102, 0.0)

        def GetAnnotation(self):
            return self

        def GetPosition(self):
            return (0.25, 0.10, 0.0)

    class SectionView(FakeView):
        Name = "剖面视图 A-A"
        Type = 2

        def GetNotes(self):
            return [Note()]

    class Sheet(FakeSheet):
        def GetViews(self):
            return [SectionView()]

    class Drawing(FakeDrawing):
        def GetSheet(self, _name):
            return Sheet()

    result = inspect_drawing_structure(Drawing())

    assert result["notes"][0]["note_kind"] == "view_label"
    assert result["notes"][0]["owner_view"] == "剖面视图 A-A"
