"""工程图结构复核无 COM 测试。"""
from scripts.sw_drawing import inspect_drawing_structure, insert_dimensions


class FakeDimension:
    Name = "D1"
    Type = 2

    def GetText(self, _index):
        return "25"


class FakeView:
    Name = "Front"
    Type = 1
    ScaleRatio = (1.0, 2.0)

    def GetDisplayDimensions(self):
        return [FakeDimension()]

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
            assert args == (0, 32, True, True, False, False)
            return True

    assert insert_dimensions(Document()) is True


def test_insert_dimensions_returns_false_when_both_com_surfaces_are_missing():
    """@brief 缺少尺寸接口时返回可审计失败，不抛出未处理异常。"""
    class Document:
        Extension = object()

    assert insert_dimensions(Document()) is False
