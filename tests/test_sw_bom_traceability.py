from scripts.sw_delivery import build_bom_traceability


def test_bom_traceability_links_model_drawing_and_review():
    result = build_bom_traceability(
        [{"item": 1, "part_number": "PN-1", "file": "part.sldprt", "configuration": "Default", "quantity": 2}],
        model_path="assembly.sldasm",
        drawing_path="assembly.slddrw",
        review_path="review.json",
    )
    assert result["status"] == "pass"
    assert result["quantity_total"] == 2
    assert all(check["status"] == "pass" for check in result["checks"])


def test_bom_traceability_warns_without_drawing_reference():
    result = build_bom_traceability([], model_path="part.sldprt")
    assert result["status"] == "warning"
    assert result["manual_review_required"] is True
