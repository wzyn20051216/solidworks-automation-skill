"""设计规则检查（DRC）引擎与声明式 Profile 的无 COM 回归测试。"""
from __future__ import annotations

import json

import pytest

from scripts import design_rule_check as drc
from scripts import design_rule_profiles as profiles


def _doc(**overrides):
    document = {
        "documentId": "demo",
        "units": "mm",
        "features": [
            {"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0, "edgeDistance": 1.0, "thread": "M6", "threadNominal": 6, "threadEngagement": 4}},
            {"id": "H2", "type": "hole", "parameters": {"diameter": 6, "x": 5, "y": 0}},
        ],
        "metadata": {
            "design": {"minWallThicknessMm": 0.8},
            "assembly": {"componentCount": 3, "mateCount": 0, "interferences": [{"a": "p1", "b": "p2"}]},
            "drawing": {"requiredDimensionsMissing": ["overall_length"], "dimensionsWithoutTolerance": 4},
        },
        "standardParts": [
            {"id": "G1", "type": "spur_gear", "teeth": 12, "is_pointed": False, "profile_shift_coeff": 0},
            {"id": "S1", "type": "compression_spring", "spring_index": 2.5, "solid_length_mm": 30, "free_length_mm": 25},
            {"id": "K1", "type": "roller_sprocket", "teeth": 11},
        ],
    }
    document.update(overrides)
    return document


def _by_id(report):
    result = {}
    for check in report["checks"]:
        result.setdefault(check["id"], check)
    return result


# ---- Profile 校验 ----


def test_profile_rejects_unknown_fields_and_operators():
    with pytest.raises(profiles.DrcProfileError):
        profiles.validate_profile({"thresholds": {"unknownKey": 1}})
    with pytest.raises(profiles.DrcProfileError):
        profiles.validate_profile({"customRules": [{"id": "X", "field": "d", "operator": "regex", "value": 1, "message": "m"}]})
    with pytest.raises(profiles.DrcProfileError):
        profiles.validate_profile({"customRules": [{"id": "bad id!", "field": "d", "operator": "lt", "value": 1, "message": "m"}]})
    with pytest.raises(profiles.DrcProfileError):
        profiles.validate_profile({"thresholds": {"holeEdgeDistanceRatio": -1}})
    with pytest.raises(profiles.DrcProfileError):
        profiles.validate_profile({"customRules": [{"id": "DRC-GEO-001", "field": "d", "operator": "lt", "value": 1, "message": "m"}]})


def test_profile_validates_and_normalizes_custom_rule():
    validated = profiles.validate_profile(
        {"customRules": [{"id": "C1", "appliesTo": "hole", "field": "diameter", "operator": "lt", "value": 8, "message": "small"}]}
    )
    rule = validated["customRules"][0]
    assert rule["category"] == "custom"
    assert rule["severity"] == "warning"
    assert rule["appliesTo"] == "hole"


def test_profile_merge_tightens_minimum_threshold():
    merged = profiles.merge_profiles(
        [{"thresholds": {"minWallThicknessMm": 1.0}}, {"thresholds": {"minWallThicknessMm": 2.0}}]
    )
    assert merged["thresholds"]["minWallThicknessMm"] == 2.0


# ---- 引擎 ----


def test_build_report_flags_all_categories():
    report = drc.build_drc_report(_doc())
    assert report["status"] == "fail"
    checks = _by_id(report)
    assert checks["DRC-GEO-001"]["status"] == "fail"
    assert checks["DRC-HOLE-001"]["status"] == "fail"
    assert checks["DRC-STD-004"]["status"] == "fail"
    assert checks["DRC-ASM-001"]["status"] == "fail"
    assert checks["DRC-DRW-001"]["status"] == "fail"
    assert report["reviewRequired"] is True


def test_thresholds_from_profile_change_outcome():
    doc = _doc(metadata={"design": {"minWallThicknessMm": 1.2}})
    # 默认阈值 1.0：1.2 > 1.0 但 < 1.5 -> warning
    default = _by_id(drc.build_drc_report(doc))
    assert default["DRC-GEO-001"]["status"] == "warning"
    # 提高阈值到 2.0 -> fail
    strict = _by_id(drc.build_drc_report(doc, profiles=[{"thresholds": {"minWallThicknessMm": 2.0}}]))
    assert strict["DRC-GEO-001"]["status"] == "fail"


def test_hole_edge_ratio_is_times_diameter_as_documented():
    doc = {"documentId": "ratio", "units": "mm", "features": [
        {"id": "H1", "type": "hole", "parameters": {"diameter": 6, "edgeDistance": 8, "x": 0, "y": 0}}
    ]}
    report = drc.build_drc_report(doc, profiles=[{"thresholds": {"holeEdgeDistanceRatio": 2}}])
    check = _by_id(report)["DRC-HOLE-001"]
    assert check["status"] == "fail"
    assert check["required_mm"] == 12


def test_fastener_geometry_is_converted_from_document_units():
    feature = {"id": "H1", "type": "hole", "parameters": {
        "diameter": 0.26, "thread": "M6", "headType": "socket_cap",
        "counterbore": {"diameter": 0.44, "depth": 0.26, "side": "front"}, "matingSide": "back"
    }}
    report = drc.build_drc_report({"documentId": "inch-part", "units": "in", "features": [feature]})
    checks = _by_id(report)
    assert checks["DRC-CSK-001"]["status"] == "pass"
    assert checks["DRC-CSK-002"]["status"] == "pass"
    assert checks["DRC-CSK-003"]["status"] == "pass"


def test_disabled_rule_is_skipped():
    report = drc.build_drc_report(_doc(), profiles=[{"disabledRules": ["DRC-ASM-001"]}])
    assert "DRC-ASM-001" not in _by_id(report)


def test_custom_rule_fires_per_target():
    profile = {"customRules": [{"id": "CUST-SMALL", "appliesTo": "hole", "field": "diameter", "operator": "lt", "value": 8, "message": "孔径过小"}]}
    report = drc.build_drc_report(_doc(), profiles=[profile])
    custom = [c for c in report["checks"] if c["id"] == "CUST-SMALL" and c["status"] == "warning"]
    assert len(custom) == 2  # H1 与 H2 都命中


def test_custom_rule_document_scalar():
    profile = {"customRules": [{"id": "CUST-COMP", "appliesTo": "document", "field": "componentCount", "operator": "gte", "value": 3, "severity": "major", "message": "组件多"}]}
    report = drc.build_drc_report(_doc(), profiles=[profile])
    hit = _by_id(report)["CUST-COMP"]
    assert hit["status"] == "fail"


def test_clean_document_with_missing_evidence_requires_review():
    clean = {
        "documentId": "clean",
        "units": "mm",
        "features": [{"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0, "edgeDistance": 5.0}}],
        "metadata": {"design": {"minWallThicknessMm": 3.0}},
        "standardParts": [{"id": "G", "type": "spur_gear", "teeth": 24, "is_pointed": False}],
    }
    report = drc.build_drc_report(clean)
    assert report["status"] == "review_required"
    assert report["summary"]["fail"] == 0
    assert report["summary"]["info"] > 0


def test_missing_all_design_evidence_is_not_a_pass():
    report = drc.build_drc_report({"documentId": "empty", "units": "mm", "features": [], "metadata": {}})
    assert report["status"] == "review_required"
    assert report["reviewRequired"] is True
    assert report["summary"]["pass"] == 0
    assert report["summary"]["info"] > 0


def test_partial_hole_assembly_and_drawing_evidence_is_not_a_pass():
    doc = {"documentId": "partial", "units": "mm",
           "features": [{"id": "H1", "type": "hole", "parameters": {}}],
           "metadata": {"assembly": {"componentCount": 2}, "drawing": {"title": "demo"}},
           "standardParts": [{"id": "G", "type": "gear"}]}
    checks = _by_id(drc.build_drc_report(doc))
    for name in ("DRC-HOLE-EVIDENCE", "DRC-ASM-EVIDENCE", "DRC-DRW-EVIDENCE", "DRC-STD-EVIDENCE"):
        assert checks[name]["status"] == "info"


def test_missing_document_id_blocks():
    report = drc.build_drc_report({"units": "mm"})
    assert report["status"] == "blocked"


def test_malformed_drive_and_unbounded_features_are_not_silently_skipped():
    report = drc.build_drc_report({"documentId": "d", "features": [], "metadata": {"drives": ["invalid"]}})
    assert _by_id(report)["DRC-DRV-900"]["status"] == "fail"
    report = drc.build_drc_report({"documentId": "d", "features": [{}] * 1001})
    assert report["status"] == "blocked"


def test_unit_conversion_inch_to_mm():
    doc = {
        "documentId": "in",
        "units": "in",
        "features": [{"id": "H", "type": "hole", "parameters": {"diameter": 0.25, "x": 0, "y": 0, "edgeDistance": 0.02}}],
    }
    report = drc.build_drc_report(doc)
    hole_edge = _by_id(report).get("DRC-HOLE-001")
    # 0.02in=0.508mm < 要求(半径 0.25in=3.175mm)，应 fail
    assert hole_edge is not None and hole_edge["status"] == "fail"


def test_list_rules_shape():
    catalog = drc.list_rules()
    assert catalog["rules"]
    assert "minWallThicknessMm" in catalog["defaultThresholds"]
    assert "lt" in catalog["customRule"]["operators"]


def test_ligament_rule_flags_thin_web():
    doc = {
        "documentId": "web",
        "units": "mm",
        "features": [
            {"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0}},
            {"id": "H2", "type": "hole", "parameters": {"diameter": 6, "x": 7, "y": 0}},
        ],
    }
    checks = _by_id(drc.build_drc_report(doc))
    # 中心距 7 - 3 - 3 = 1mm < 默认 2mm -> fail
    assert checks["DRC-HOLE-005"]["status"] == "fail"


def test_thread_vs_thickness_rule():
    doc = {
        "documentId": "thin",
        "units": "mm",
        "features": [{"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0, "thread": "M6", "threadNominal": 6}}],
        "metadata": {"plate": {"thicknessMm": 4.0}},
    }
    checks = _by_id(drc.build_drc_report(doc))
    # 4mm 板厚 < 1.0*6 默认? threadEngagementRatio 默认 1.0 -> required 6 > 4 -> warning
    assert checks["DRC-HOLE-006"]["status"] == "warning"


def test_relation_rules_datum_bom_coverage():
    doc = {
        "documentId": "rel",
        "units": "mm",
        "features": [{"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0}}],
        "metadata": {
            "gdt": [{"symbol": "position", "datums": ["A", "B", "C"]}],
            "datums": [{"id": "A"}, {"id": "B"}],
            "bom": [{"id": "b1", "featureType": "hole", "quantity": 3}],
            "drawing": {"holeCallouts": ["⌀8"]},
        },
    }
    checks = _by_id(drc.build_drc_report(doc))
    assert checks["DRC-REL-001"]["status"] == "fail"  # 基准 C 未声明
    assert checks["DRC-REL-002"]["status"] == "warning"  # ⌀6 未被 ⌀8 覆盖
    assert checks["DRC-REL-003"]["status"] == "warning"  # BOM 3 vs 特征 1


def test_checks_mark_unverified_references_as_hints():
    checks = _by_id(drc.build_drc_report(_doc()))
    assert checks["DRC-GEO-001"]["referenceHint"]
    assert checks["DRC-HOLE-005"]["referenceVerified"] is False


def test_report_has_fingerprint_and_risk():
    report = drc.build_drc_report(_doc())
    assert report["riskScore"]["band"] in {"none", "low", "medium", "high"}
    assert all("fingerprint" in c for c in report["checks"])
    assert "audit" in report


def test_rule_packs_listed_and_applied():
    from scripts import design_rule_profiles as prof

    names = [p["name"] for p in prof.list_rule_packs()]
    assert "drilling_panel" in names and "machined_bracket" in names
    # drilling_panel 的孔边距为 1.0 倍孔径：edge 5 对 ⌀6 -> required 6 -> fail
    doc = {
        "documentId": "pack",
        "units": "mm",
        "features": [{"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0, "edgeDistance": 5.0}}],
    }
    default = _by_id(drc.build_drc_report(doc))
    packed = _by_id(drc.build_drc_report(doc, rule_packs=["drilling_panel"]))
    assert "DRC-HOLE-001" not in default  # 默认 ratio 0.5 -> required 3 -> 不产生 fail
    assert packed["DRC-HOLE-001"]["status"] == "fail"


def test_baseline_diff_and_waiver_gate():
    doc = _doc()
    base = drc.build_drc_report(doc)
    waivers = [{"ruleId": "DRC-STD-004", "target": "S1", "reason": "客户签字", "owner": "赵工", "expiresOn": "2026-12-31"}]
    report = drc.build_drc_report(doc, baseline=base, waivers=waivers, as_of_date="2026-09-08")
    assert report["summary"]["waived"] >= 1
    assert report["audit"]["diff"]["counts"]["persisting"] >= 1


def test_bad_rule_pack_name_blocks():
    report = drc.build_drc_report(_doc(), rule_packs=["../evil"])
    assert report["status"] == "blocked"


def test_fastener_countersink_rules_integrated():
    doc = {
        "documentId": "csk",
        "units": "mm",
        "features": [
            {"id": "C1", "type": "hole", "parameters": {"diameter": 6.6, "thread": "M6", "headType": "socket_cap", "counterbore": {"diameter": 9.0, "depth": 5.0, "side": "back"}, "matingSide": "back"}},
        ],
        "metadata": {"fastenerStacks": [{"id": "S1", "holeId": "C1", "protrudes": True, "matingHasRelief": False, "gapMm": 0.0}]},
    }
    checks = _by_id(drc.build_drc_report(doc))
    assert checks["DRC-CSK-002"]["status"] == "fail"   # 头径不容纳
    assert checks["DRC-CSK-004"]["status"] == "fail"   # 沉头朝配合面
    assert checks["DRC-FIT-001"]["status"] == "fail"   # 跨零件无避让
    assert checks["DRC-CSK-004"]["referenceVerified"] is False


def test_no_countersink_skips_fastener_rules():
    report = drc.build_drc_report(_doc())
    checks = _by_id(report)
    # _doc() 的孔无沉头 -> DRC-CSK-000 info 跳过
    assert checks.get("DRC-CSK-000", {}).get("status") == "info"


def test_write_report_versions_and_hashes(tmp_path):
    doc_path = tmp_path / "d.json"
    doc_path.write_text(json.dumps(_doc()), encoding="utf-8")
    out = tmp_path / "drc.json"
    first = drc.write_drc_report(doc_path, out)
    assert first["artifacts"][0]["sha256"]
    assert first["reportPath"].endswith("drc.json")
    second = drc.write_drc_report(doc_path, out)
    assert second["reportPath"].endswith("drc.v1.json")  # 不覆盖旧文件


def test_gear_min_teeth_depends_on_pressure_angle_and_shift():
    f = drc.gear_min_teeth_without_undercut
    assert f(20.0, 1.0, 0.0) == 18      # 17.097 向上取整
    assert f(14.5, 1.0, 0.0) == 32      # 旧的固定常数 17 会在此漏报
    assert f(25.0, 1.0, 0.0) == 12      # 旧的固定常数 17 会在此误报
    assert f(20.0, 1.0, 0.5) < f(20.0, 1.0, 0.0)  # 正变位降低无根切下限
    assert f(20.0, 1.0, 0.0, override=20) == 20   # 用户 Profile 显式设置时采用，向后兼容


def _gear_doc(teeth, pressure=20.0, shift=0.0):
    return {
        "documentId": "g", "units": "mm", "features": [],
        "standardParts": [{"id": "G1", "type": "spur_gear", "teeth": teeth, "pressure_angle_deg": pressure, "profile_shift_coeff": shift}],
    }


def test_drc_undercut_uses_pressure_angle_not_fixed_17():
    # 14.5° 压力角、24 齿：旧逻辑(17)判无风险，实际需 >=32
    checks = _by_id(drc.build_drc_report(_gear_doc(24, pressure=14.5)))
    assert checks["DRC-STD-002"]["status"] == "warning"
    # 20°、17 齿：理论 17.097，已有轻微根切
    assert _by_id(drc.build_drc_report(_gear_doc(17)))["DRC-STD-002"]["status"] == "warning"
    # 20°、18 齿：刚好无根切 -> 不应产生 DRC-STD-002
    assert "DRC-STD-002" not in _by_id(drc.build_drc_report(_gear_doc(18)))
    # 变位 x=0.5 后 12 齿可无根切
    assert "DRC-STD-002" not in _by_id(drc.build_drc_report(_gear_doc(12, shift=0.5)))


def test_drc_gear_min_teeth_profile_override_still_works():
    report = drc.build_drc_report(_gear_doc(30), profiles=[{"thresholds": {"gearMinTeeth": 40}}])
    assert _by_id(report)["DRC-STD-002"]["status"] == "warning"


# ---- 回归门禁集成 ----


def _regress_doc(edge):
    return {"documentId": "r", "units": "mm", "features": [{"id": "H1", "type": "hole", "parameters": {"diameter": 6, "x": 0, "y": 0, "edgeDistance": edge}}]}


def test_drc_regression_gate_passes_on_improvement_and_fails_on_worse():
    worse = drc.build_drc_report(_regress_doc(1.0))   # 边距 1mm：fail
    better = drc.build_drc_report(_regress_doc(10.0))  # 边距充足
    ok = drc.build_drc_report(_regress_doc(10.0), baseline=worse, regression_gate=True)
    assert ok["regressionGate"]["passed"] is True
    bad = drc.build_drc_report(_regress_doc(1.0), baseline=better, regression_gate=True)
    assert bad["regressionGate"]["passed"] is False
    assert bad["regressionGate"]["delta"] > 0


def test_drc_regression_gate_requires_baseline():
    report = drc.build_drc_report(_regress_doc(1.0), regression_gate=True)
    assert report["regressionGate"]["passed"] is False
    assert report["regressionGate"]["error"] == "baseline_required"


def test_drc_without_gate_has_no_regression_key():
    assert "regressionGate" not in drc.build_drc_report(_regress_doc(1.0))


def test_drc_cli_exit_code_follows_regression_gate(tmp_path):
    import json as _json
    base = tmp_path / "base.json"
    base.write_text(_json.dumps(drc.build_drc_report(_regress_doc(10.0))), encoding="utf-8")
    doc = tmp_path / "d.json"
    doc.write_text(_json.dumps(_regress_doc(10.0)), encoding="utf-8")  # 与基线同等好 -> 门禁通过
    assert drc.main([str(doc), "--baseline", str(base), "--fail-on-regression"]) == 2
    worse = tmp_path / "w.json"
    worse.write_text(_json.dumps(_regress_doc(1.0)), encoding="utf-8")
    assert drc.main([str(worse), "--baseline", str(base), "--fail-on-regression"]) == 1


# ---- 电机扭矩核验并入 DRC ----


def _drive_doc(motor=None, **load):
    spec = {
        "id": "X轴",
        "load": {"mass_kg": 50, "incline_deg": 0, "friction_coeff": 0.1, **load},
        "motion": {"distance_mm": 500, "max_speed_mm_s": 500, "accel_mm_s2": 2000, "round_trip": False},
        "transmission": {"type": "lead_screw", "lead_mm": 10, "efficiency": 0.9, "screw_diameter_mm": 20, "screw_length_mm": 600},
        "motor": motor if motor is not None else {"peak_torque_nm": 1.5, "rated_torque_nm": 0.64, "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 0.5e-4},
    }
    return {"documentId": "d", "units": "mm", "features": [], "metadata": {"drives": [spec]}}


def test_drc_drive_torque_requires_review_with_adequate_motor():
    checks = _by_id(drc.build_drc_report(_drive_doc()))
    for rid in ("DRC-DRV-001", "DRC-DRV-002"):
        assert checks[rid]["status"] == "info", rid
    for rid in ("DRC-DRV-003", "DRC-DRV-004"):
        assert checks[rid]["status"] == "pass", rid
    assert checks["DRC-DRV-001"]["referenceVerified"] is False


def test_drc_drive_rules_fail_with_undersized_motor_and_feed_risk_score():
    small = {"peak_torque_nm": 0.5, "rated_torque_nm": 0.2, "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 0.5e-4}
    report = drc.build_drc_report(_drive_doc(motor=small))
    checks = _by_id(report)
    assert checks["DRC-DRV-001"]["status"] == "fail" and checks["DRC-DRV-002"]["status"] == "fail"
    assert report["riskScore"]["score"] >= 10.0  # 两个 major
    assert all("fingerprint" in c for c in report["checks"] if c["id"].startswith("DRC-DRV"))


def test_drc_drive_profile_override_flips_result():
    spec_doc = _drive_doc(motor={"peak_torque_nm": 0.7, "rated_torque_nm": 0.64, "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 0.5e-4})
    assert _by_id(drc.build_drc_report(spec_doc))["DRC-DRV-001"]["status"] == "info"
    strict = drc.build_drc_report(spec_doc, profiles=[{"thresholds": {"driveTorqueSafetyFactor": 2.0}}])
    assert _by_id(strict)["DRC-DRV-001"]["status"] == "fail"


def test_drc_drive_maximum_thresholds_merge_to_stricter_value():
    from scripts import design_rule_profiles as prof

    merged = prof.merge_profiles([
        {"thresholds": {"driveRmsUtilizationMax": 0.9, "driveInertiaRatioMax": 10}},
        {"thresholds": {"driveRmsUtilizationMax": 0.7, "driveInertiaRatioMax": 5}},
    ])
    assert merged["thresholds"]["driveRmsUtilizationMax"] == 0.7   # 取更小=更严
    assert merged["thresholds"]["driveInertiaRatioMax"] == 5


def test_drc_invalid_drive_spec_is_reported_not_skipped():
    doc = _drive_doc()
    doc["metadata"]["drives"][0]["load"]["mass_kg"] = -5
    checks = _by_id(drc.build_drc_report(doc))
    assert checks["DRC-DRV-900"]["status"] == "fail"
    assert "mass_kg" in checks["DRC-DRV-900"]["message"]


def test_drc_vertical_axis_without_brake_is_critical_in_report():
    report = drc.build_drc_report(_drive_doc(incline_deg=90))
    c = _by_id(report)["DRC-DRV-005"]
    assert c["status"] == "fail" and c["severity"] == "critical"


def test_drc_without_drives_skips_with_info():
    assert _by_id(drc.build_drc_report(_regress_doc(10.0)))["DRC-DRV-000"]["status"] == "info"


def test_drc_drive_regression_gate_catches_weaker_motor():
    good = drc.build_drc_report(_drive_doc())
    weak = {"peak_torque_nm": 0.5, "rated_torque_nm": 0.2, "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 0.5e-4}
    swapped = drc.build_drc_report(_drive_doc(motor=weak), baseline=good, regression_gate=True)
    assert swapped["regressionGate"]["passed"] is False   # 换了更小的电机 = 设计变差，门禁拒绝
