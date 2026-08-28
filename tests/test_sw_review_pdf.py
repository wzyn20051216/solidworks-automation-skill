"""@brief SolidWorks PDF 矢量文字边界复核测试。"""
from pathlib import Path

import pytest

from scripts.sw_review import _import_pdf_parser, inspect_pdf_text_layout
from scripts.sw_drawing_review import review_drawing_artifacts


def test_pdf_vector_text_boxes_are_extracted_without_claiming_com_native(tmp_path: Path) -> None:
    """@brief PDF span 应保留真实边界来源，并识别尺寸候选。"""
    try:
        fitz = _import_pdf_parser()
    except ImportError:
        pytest.skip("PyMuPDF 未安装")
    target = tmp_path / "drawing.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), "DIM R10 mm", fontsize=12)
    document.save(target)
    document.close()

    report = inspect_pdf_text_layout(target)
    assert report["status"] == "review_required"
    assert report["source"] == "solidworks_pdf_vector_text"
    assert report["native_com_bounding_box_available"] is False
    assert report["text_span_count"] == 1
    assert report["numeric_text_span_count"] == 1
    assert report["pages"][0]["textSpans"][0]["bboxPt"][2] > report["pages"][0]["textSpans"][0]["bboxPt"][0]


def test_pdf_overlapping_vector_text_is_reported(tmp_path: Path) -> None:
    """@brief 同页实际文字框重叠应返回稳定错误码。"""
    try:
        fitz = _import_pdf_parser()
    except ImportError:
        pytest.skip("PyMuPDF 未安装")
    target = tmp_path / "overlap.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((50, 80), "R10 mm", fontsize=20)
    page.insert_text((55, 80), "R12 mm", fontsize=20)
    document.save(target)
    document.close()

    report = inspect_pdf_text_layout(target)
    assert report["error_code"] == "DRAWING_PDF_TEXT_OVERLAP_RISK"
    assert report["overlaps"]
    assert report["overlaps"][0]["confirmedGeometryOverlap"] is True
    assert report["overlaps"][0]["confirmedVisualDefect"] is False


def test_pdf_frame_labels_and_single_character_markers_are_not_overlap_defects(tmp_path: Path) -> None:
    """@brief 图框分区字母/单字符页码的字体盒相交不应阻断真实图纸。"""
    fitz = _import_pdf_parser()
    target = tmp_path / "frame-labels.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((50, 80), "签    字", fontsize=12)
    page.insert_text((50, 80), "F", fontsize=15)
    page.insert_text((150, 120), "共  张", fontsize=12)
    page.insert_text((150, 120), "1", fontsize=15)
    document.save(target)
    document.close()

    report = inspect_pdf_text_layout(target)

    assert report["overlaps"] == []


def test_pdf_overlapping_vector_text_blocks_drawing_delivery(tmp_path: Path) -> None:
    """@brief PDF 已确认文字框重叠时，工程图审查不能沿其它路径放行。"""
    fitz = _import_pdf_parser()
    target = tmp_path / "overlap-delivery.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), "R10 mm", fontsize=20)
    page.insert_text((77, 100), "R12 mm", fontsize=20)
    document.save(target)
    document.close()
    spec = {
        "schemaVersion": "1.0", "sourceModel": "C:/cad/part.sldprt", "documentType": "part",
        "standard": "GB_T", "projection": "first_angle", "paperSize": "A3",
        "modelSizeMm": [120, 80, 12],
        "views": {"front": {}, "top": {}, "right": {}},
        "outputs": {"slddrw": True, "pdf": True, "report": True},
    }
    structure = {
        "sheets": ["Sheet1"], "sheet_size": {"width_m": 0.42, "height_m": 0.297},
        "views": [
            {"name": "Front", "box": {"left": 0.20, "bottom": 0.10, "right": 0.32, "top": 0.18}},
            {"name": "Top", "box": {"left": 0.20, "bottom": 0.08, "right": 0.32, "top": 0.095}},
            {"name": "Right", "box": {"left": 0.08, "bottom": 0.10, "right": 0.18, "top": 0.18}},
        ], "dimensions": [],
        "title_block": {"box": {"left": 0.23, "bottom": 0.01, "right": 0.40, "top": 0.06}},
    }
    result = review_drawing_artifacts(spec, structure=structure, pdf_path=target)

    assert result["status"] == "blocked"
    assert result["manual_review_required"] is True
    assert any(item["code"] == "DRAWING_PDF_TEXT_OVERLAP_RISK" for item in result["findings"])
