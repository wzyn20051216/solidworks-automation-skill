"""@brief SolidWorks PDF 矢量文字边界复核测试。"""
from pathlib import Path

import pytest

from scripts.sw_review import _import_pdf_parser, inspect_pdf_text_layout


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
