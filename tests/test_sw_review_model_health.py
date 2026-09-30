"""sw_review 模型健康度规则(重建/特征错误/几何门禁/干涉/工程图)无 COM 测试。"""
from __future__ import annotations

from scripts.sw_review import (
    evaluate_review_report,
    collect_geometry_measurements,
    collect_model_summary,
    _safe_basename,
    _ensure_writable_report_path,
)


def test_safe_basename_strips_path_components():
    assert _safe_basename("review") == "review"
    assert _safe_basename("../../evil") == "evil"
    assert _safe_basename("a/b\\c") == "c"
    assert _safe_basename("..\\..\\x") == "x"
    assert _safe_basename("  spaced  ") == "spaced"
    assert _safe_basename("") == "review"
    assert _safe_basename("../../") == "review"


def test_report_path_guard_rejects_parent_escape():
    import pytest
    from pathlib import Path

    with pytest.raises(ValueError):
        _ensure_writable_report_path(Path("out") / ".." / "escape.json")
    with pytest.raises(ValueError):
        _ensure_writable_report_path(r"D:\out\..\evil.json")
    assert _ensure_writable_report_path(Path("ok.json")).name == "ok.json"


def _base_report(**overrides):
    report = {
        "model": {"type": 1, "faulty_features": []},
        "cad_spec": {"envelope_mm": {"length": 10.0, "width": 10.0, "height": 10.0}},
        "previews": [],
        "expected_outputs": [],
        "checks": {
            "model_available": True,
            "previews_created": True,
            "previews_not_blank": True,
            "expected_outputs_exist": None,
            "feature_summary_available": True,
            "geometry_measurements_available": True,
            "geometry_measurements_error_free": True,
            "rebuild_ok": True,
            "feature_errors_absent": True,
        },
    }
    report.update(overrides)
    return report


def _codes(evaluation):
    return [issue["code"] for issue in evaluation["issues"]]


def test_rebuild_failed_is_hard_fail():
    report = _base_report()
    report["checks"]["rebuild_ok"] = False
    evaluation = evaluate_review_report(report)
    assert evaluation["status"] == "fail"
    assert "rebuild_failed" in _codes(evaluation)


def test_rebuild_unknown_does_not_fail():
    report = _base_report()
    report["checks"]["rebuild_ok"] = None
    evaluation = evaluate_review_report(report)
    assert "rebuild_failed" not in _codes(evaluation)


def test_feature_errors_are_hard_fail_with_detail():
    report = _base_report()
    report["model"]["faulty_features"] = [
        {"name": "Boss-Extrude1", "type": "Extrusion", "error_code": 51},
        {"name": "Boss-Extrude2", "type": "ICE", "error_code": 51},
    ]
    evaluation = evaluate_review_report(report)
    assert evaluation["status"] == "fail"
    assert "feature_errors_present" in _codes(evaluation)
    issue = next(i for i in evaluation["issues"] if i["code"] == "feature_errors_present")
    assert "Boss-Extrude1" in issue["message"]
    assert "2" in issue["message"]


def test_degenerate_zero_envelope_is_hard_fail_for_part():
    report = _base_report()
    report["cad_spec"]["envelope_mm"] = {"length": 0.0, "width": 0.0, "height": 0.0}
    evaluation = evaluate_review_report(report)
    assert evaluation["status"] == "fail"
    assert "degenerate_envelope" in _codes(evaluation)


def test_geometry_unavailable_warns_for_part_only():
    part_report = _base_report()
    part_report["checks"]["geometry_measurements_available"] = False
    assert "geometry_measurements_unavailable" in _codes(evaluate_review_report(part_report))

    asm_report = _base_report()
    asm_report["model"]["type"] = 2
    asm_report["checks"]["geometry_measurements_available"] = False
    assert "geometry_measurements_unavailable" not in _codes(evaluate_review_report(asm_report))


def test_interference_reported_as_warn_with_components():
    report = _base_report()
    report["model"]["type"] = 2
    report["interference"] = {
        "status": "warn",
        "api": "modern",
        "interference_count": 2,
        "interfering_components": ["housing-1", "shaft-1"],
    }
    evaluation = evaluate_review_report(report)
    assert "interference_detected" in _codes(evaluation)
    issue = next(i for i in evaluation["issues"] if i["code"] == "interference_detected")
    assert "housing-1" in issue["message"]
    assert evaluation["status"] == "warn"


def test_interference_blocked_is_warn_not_silent():
    report = _base_report()
    report["model"]["type"] = 2
    report["interference"] = {"status": "blocked", "error": "<unknown>.InterferenceDetection"}
    assert "interference_check_blocked" in _codes(evaluate_review_report(report))


def test_drawing_views_missing_is_hard_fail():
    report = _base_report()
    report["model"]["type"] = 3
    report["drawing_structure"] = {"status": "blocked", "error_code": "DRAWING_VIEWS_MISSING"}
    evaluation = evaluate_review_report(report)
    assert evaluation["status"] == "fail"
    assert "drawing_views_missing" in _codes(evaluation)


def test_drawing_layout_estimated_evidence_warns():
    report = _base_report()
    report["model"]["type"] = 3
    report["drawing_layout"] = {
        "status": "review_required",
        "error_code": "DRAWING_LAYOUT_ESTIMATED_EVIDENCE_REQUIRES_VISUAL_REVIEW",
    }
    assert "drawing_layout_review_required" in _codes(evaluate_review_report(report))


class _Feature:
    def __init__(self, name, ftype, error_code):
        self.Name = name
        self._type = ftype
        self._error_code = error_code
        self.next = None

    def GetTypeName2(self):
        return self._type

    def GetErrorCode(self):
        return self._error_code

    def GetNextFeature(self):
        return self.next


class _PartModel:
    """零件文档假对象: 特征链 + IPartDoc 成员。"""

    def __init__(self, features):
        self._features = features

    def GetType(self):
        return 1

    def FirstFeature(self):
        return self._features[0] if self._features else None

    def GetTitle(self):
        return "fake.SLDPRT"

    def GetPathName(self):
        return r"D:\fake.SLDPRT"

    def GetPartBox(self, ignored):
        return [0.0, 0.0, 0.0, 0.01, 0.01, 0.01]

    def GetBodies2(self, *_args):
        return []


def test_collect_model_summary_lists_faulty_features():
    healthy = _Feature("Sketch1", "ProfileFeature", 0)
    faulty = _Feature("Boss-Extrude1", "Extrusion", 51)
    healthy.next = faulty
    summary = collect_model_summary(_PartModel([healthy]))
    assert summary["faulty_features"] == [
        {"name": "Boss-Extrude1", "type": "Extrusion", "error_code": 51}
    ]
    assert summary["features"][0]["error_code"] == 0


class _AssemblyModel:
    def GetType(self):
        return 2

    def GetPartBox(self, *_args):
        raise AssertionError("GetPartBox 是 IPartDoc 成员, 装配体不应调用")

    def GetBodies2(self, *_args):
        raise AssertionError("GetBodies2 是 IPartDoc 成员, 装配体不应调用")


def test_geometry_measurement_gates_out_assembly_docs():
    measurements = collect_geometry_measurements(_AssemblyModel())
    assert measurements["unsupported_doc_type"] == 2
    assert measurements["envelope_mm"] is None
    assert measurements["errors"] == []


def test_geometry_measurement_runs_for_parts():
    measurements = collect_geometry_measurements(_PartModel([]))
    assert measurements["envelope_mm"] == {"length": 10.0, "width": 10.0, "height": 10.0, "axis_order": "model_xyz"}
