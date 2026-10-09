"""@brief 2026 特征错误/警告、文档类型和领域证据的复核契约。"""
from types import SimpleNamespace
import pytest
from scripts import sw_review


def report(**changes):
    """@brief 只构造复核输入，不宣称真实几何。"""
    data = {"model":{"type":1}, "cad_spec":{"envelope_mm":{"length":10,"width":10,"height":10}},
        "checks":{"model_available":True,"previews_created":True,"previews_not_blank":True,
            "expected_outputs_exist":True,"feature_summary_available":True,"rebuild_succeeded":True},
        "previews":[{},{}],"expected_outputs":[]}
    data.update(changes)
    return data


def test_typed_error_and_warning_do_not_have_same_severity():
    error = SimpleNamespace(GetErrorCode2=lambda: (51, False))
    warning = SimpleNamespace(GetErrorCode2=lambda: (51, True))
    unknown = SimpleNamespace(GetErrorCode2=lambda: (51, None))
    assert sw_review._feature_health(error)["health_status"] == "error"
    assert sw_review._feature_health(warning)["health_status"] == "warning"
    assert sw_review._feature_health(unknown)["health_status"] == "unknown"


def test_confirmed_feature_failure_is_hard_fail():
    evaluated = sw_review.evaluate_review_report(report(model={"type":1,"faulty_features":[{"name":"fixture"}]}))
    assert evaluated["status"] == "fail"
    assert "feature_errors_present" in {item["code"] for item in evaluated["issues"]}


def test_nonzero_legacy_code_stays_unknown_until_reviewed():
    assert sw_review._feature_health(SimpleNamespace(GetErrorCode=lambda:51))["health_status"] == "unknown"


def test_zero_envelope_and_missing_drawing_views_are_failures():
    zero = report(cad_spec={"envelope_mm":{"length":0,"width":0,"height":0}})
    assert sw_review.evaluate_review_report(zero)["status"] == "fail"
    drawing = report(model={"type":3}, drawing_structure={"status":"blocked","error_code":"DRAWING_VIEWS_MISSING"})
    assert sw_review.evaluate_review_report(drawing)["status"] == "fail"


def test_assembly_does_not_call_part_measurement_members():
    model = SimpleNamespace(GetType=lambda:2)
    measured = sw_review.collect_geometry_measurements(model)
    assert measured["errors"] == [] and measured["unsupported_doc_type"] == 2


@pytest.mark.parametrize("envelope", [
    {"length": float("nan"), "width": 10, "height": 10},
    {"length": -1, "width": 10, "height": 10},
    {"length": "invalid", "width": 10, "height": 10},
    {"length": 10, "width": 10},
])
def test_invalid_envelope_is_reported_instead_of_crashing(envelope):
    """@brief 损坏的复核输入必须返回失败，不能中断诊断。"""
    evaluated = sw_review.evaluate_review_report(report(cad_spec={"envelope_mm": envelope}))
    assert "degenerate_envelope" in {item["code"] for item in evaluated["issues"]}
    assert evaluated["status"] == "fail"


def test_empty_successful_drawing_structure_does_not_pass():
    """@brief 结构读取成功仍必须存在模型视图。"""
    evaluated = sw_review.evaluate_review_report(report(model={"type": 3}, drawing_structure={"status": "pass", "views": []}))
    assert "drawing_views_missing" in {item["code"] for item in evaluated["issues"]}


def test_assembly_interference_is_reviewed_without_losing_volume():
    interference = {"status":"warn","interference_count":1,"items":[{"volume_mm3":4000}]}
    data = report(model={"type":2}, interference=interference)
    evaluated = sw_review.evaluate_review_report(data)
    assert evaluated["status"] == "warn" and evaluated["manual_review_required"] is True
    assert data["interference"]["items"][0]["volume_mm3"] == 4000
