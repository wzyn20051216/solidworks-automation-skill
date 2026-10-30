"""DRC 审计工作流（指纹/diff/让步单/风险评分）的无 COM 回归测试。"""
from __future__ import annotations

import pytest

from scripts import design_audit as audit


def test_regression_gate_does_not_treat_missing_evidence_as_a_fix():
    baseline = [{"id": "DRC-HOLE-001", "category": "holes", "status": "fail", "severity": "major", "target": "H1"}]
    candidate = [{"id": "DRC-HOLE-EVIDENCE", "category": "holes", "status": "info", "severity": "info"}]
    result = audit.assert_no_regression(baseline, candidate)
    assert result["passed"] is False
    assert result["unverifiedFixed"] == [{"id": "DRC-HOLE-001", "target": "H1"}]


def _checks():
    return [
        {"id": "DRC-HOLE-001", "category": "holes", "status": "fail", "severity": "major", "target": "H1", "message": "边距不足"},
        {"id": "DRC-GEO-001", "category": "geometry", "status": "warning", "severity": "minor", "message": "壁厚接近"},
        {"id": "DRC-STD-004", "category": "standard_parts", "status": "fail", "severity": "critical", "target": "S1", "message": "实体>=自由"},
        {"id": "DRC-HOLE-OK", "category": "holes", "status": "pass", "severity": "info", "message": "ok"},
    ]


def test_fingerprint_is_stable_and_target_sensitive():
    a = {"id": "DRC-HOLE-001", "category": "holes", "target": "H1"}
    b = {"id": "DRC-HOLE-001", "category": "holes", "target": "H1"}
    c = {"id": "DRC-HOLE-001", "category": "holes", "target": "H2"}
    assert audit.finding_fingerprint(a) == audit.finding_fingerprint(b)
    assert audit.finding_fingerprint(a) != audit.finding_fingerprint(c)


def test_diff_new_fixed_persisting():
    baseline = [
        {"id": "DRC-HOLE-001", "category": "holes", "status": "fail", "severity": "major", "target": "H1"},
        {"id": "DRC-ASM-001", "category": "assembly", "status": "fail", "severity": "critical", "target": None},
    ]
    current = audit.attach_fingerprints(_checks())
    diff = audit.diff_findings(baseline, current)
    assert diff["counts"] == {"new": 2, "fixed": 1, "persisting": 1}


def test_waiver_requires_reason_and_owner():
    with pytest.raises(ValueError):
        audit.validate_waiver({"ruleId": "X", "reason": "r"})  # 缺 owner
    with pytest.raises(ValueError):
        audit.validate_waiver({"reason": "r", "owner": "o"})  # 缺匹配键


def test_apply_waiver_excludes_from_gate():
    checks = audit.attach_fingerprints(_checks())
    waivers = [{"ruleId": "DRC-STD-004", "target": "S1", "reason": "客户接受", "owner": "张工", "expiresOn": "2026-12-31"}]
    result = audit.apply_waivers(checks, waivers, as_of_date="2026-09-08")
    assert len(result["applied"]) == 1
    waived = [c for c in result["checks"] if c.get("waived")]
    assert waived and waived[0]["id"] == "DRC-STD-004"
    # H1 fail 仍在 -> 门禁仍 fail
    assert audit.gated_status(result["checks"]) == "fail"


def test_expired_waiver_does_not_apply():
    checks = audit.attach_fingerprints(_checks())
    waivers = [{"ruleId": "DRC-STD-004", "reason": "r", "owner": "o", "expiresOn": "2025-01-01"}]
    result = audit.apply_waivers(checks, waivers, as_of_date="2026-09-08")
    assert len(result["applied"]) == 0
    assert len(result["expired"]) == 1


def test_default_date_never_applies_an_old_expired_waiver():
    waiver = {"ruleId": "DRC-STD-004", "reason": "r", "owner": "o", "expiresOn": "2000-01-01"}
    result = audit.apply_waivers(_checks(), [waiver])
    assert not result["applied"]
    assert len(result["expired"]) == 1


def test_waiver_dates_are_valid_and_future_waivers_do_not_apply():
    with pytest.raises(ValueError):
        audit.validate_waiver({"ruleId": "X", "reason": "r", "owner": "o", "expiresOn": "2026-99-99"})
    waiver = {"ruleId": "DRC-STD-004", "reason": "r", "owner": "o", "createdOn": "2026-12-01"}
    result = audit.apply_waivers(_checks(), [waiver], as_of_date="2026-01-01")
    assert not result["applied"]
    assert len(result["notYetValid"]) == 1


def test_risk_score_weights_and_band():
    checks = audit.attach_fingerprints(_checks())
    risk = audit.risk_score(checks)
    # critical(10) + major(5) + minor(1) = 16 -> medium
    assert risk["score"] == pytest.approx(16.0)
    assert risk["band"] == "medium"


def test_risk_score_excludes_waived():
    checks = audit.attach_fingerprints(_checks())
    waived = audit.apply_waivers(checks, [{"ruleId": "DRC-STD-004", "reason": "r", "owner": "o"}], as_of_date="2026-09-08")["checks"]
    risk = audit.risk_score(waived)
    assert risk["score"] == pytest.approx(6.0)  # 去掉 critical(10)


def test_summarize_audit_end_to_end():
    baseline = [{"id": "DRC-HOLE-001", "category": "holes", "status": "fail", "severity": "major", "target": "H1"}]
    result = audit.summarize_audit(
        _checks(),
        baseline_checks=baseline,
        waivers=[{"ruleId": "DRC-STD-004", "target": "S1", "reason": "r", "owner": "o"}],
        as_of_date="2026-09-08",
    )
    assert result["gatedStatus"] == "fail"
    assert result["risk"]["band"] in {"low", "medium", "high", "none"}
    assert result["waivers"]["applied"]
    assert "diff" in result


# ---- 回归门禁 ----


def _f(rid, status, severity, target=None, **extra):
    d = {"id": rid, "category": "x", "status": status, "severity": severity, "target": target, "message": rid}
    d.update(extra)
    return d


def test_regression_gate_passes_when_improved():
    baseline = [_f("A", "fail", "major", "H1"), _f("B", "warning", "warning")]
    candidate = [_f("B", "warning", "warning")]  # A 已修复
    r = audit.assert_no_regression(baseline, candidate)
    assert r["passed"] is True
    assert r["delta"] < 0 and r["fixedCount"] == 1 and r["newCount"] == 0


def test_regression_gate_passes_when_unchanged():
    checks = [_f("A", "fail", "major", "H1")]
    assert audit.assert_no_regression(checks, checks)["passed"] is True


def test_regression_gate_rejects_higher_risk():
    baseline = [_f("B", "warning", "warning")]
    candidate = [_f("B", "warning", "warning"), _f("C", "fail", "major", "H2")]
    r = audit.assert_no_regression(baseline, candidate)
    assert r["passed"] is False
    assert r["delta"] == pytest.approx(5.0)
    assert any("风险分" in reason for reason in r["reasons"])


def test_regression_gate_rejects_new_critical_even_if_score_drops():
    """修好了两个 major(-10)，却引入一个新的 critical(+10)：总分持平/下降也不能放行。"""
    baseline = [_f("A", "fail", "major", "H1"), _f("B", "fail", "major", "H2"), _f("K", "fail", "critical", "S9")]
    candidate = [_f("K", "fail", "critical", "S9"), _f("N", "fail", "critical", "S1")]  # 新增 critical N
    r = audit.assert_no_regression(baseline, candidate, tolerance=100.0)  # 容差放大，只剩 critical 规则起作用
    assert r["passed"] is False
    assert r["newBlocking"] == [{"id": "N", "target": "S1", "severity": "critical"}]


def test_regression_gate_tolerance_allows_small_increase():
    baseline = [_f("B", "warning", "warning")]
    candidate = [_f("B", "warning", "warning"), _f("M", "warning", "minor")]  # +1
    assert audit.assert_no_regression(baseline, candidate, tolerance=0.0)["passed"] is False
    assert audit.assert_no_regression(baseline, candidate, tolerance=1.0)["passed"] is True


def test_regression_gate_ignores_waived_findings():
    baseline = [_f("B", "warning", "warning")]
    candidate = [_f("B", "warning", "warning"), _f("N", "fail", "critical", "S1", waived=True)]
    assert audit.assert_no_regression(baseline, candidate)["passed"] is True  # 已让步的新 critical 不计
