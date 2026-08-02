"""DFM 规则复核回归。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.dfm_review import build_dfm_report, write_dfm_report
from scripts.dfm_profiles import validate_profile


def _write_document(path: Path, manufacturing: dict, *, features: list[dict] | None = None) -> Path:
    """@brief 写出测试用 NeutralCadDocument。"""
    payload = {
        "documentId": path.stem,
        "title": "DFM 测试件",
        "units": "mm",
        "features": features
        or [
            {"id": "base", "type": "box", "parameters": {"length": 120, "width": 70, "height": 8}},
            {"id": "hole-a", "type": "hole", "operation": "subtract", "parameters": {"x": -35, "y": 20, "diameter": 10}},
            {"id": "hole-b", "type": "hole", "operation": "subtract", "parameters": {"x": 35, "y": -20, "diameter": 10}},
        ],
        "metadata": {"manufacturing": manufacturing},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _profile(
    profile_id: str,
    limits: dict,
    *,
    processes: list[str] | None = None,
    source_type: str = "supplier",
) -> dict:
    """@brief 构造测试用严格 DFM Profile。"""
    return {
        "schema": "cadstudio.dfm-profile",
        "version": "1.0",
        "id": profile_id,
        "source": {"type": source_type, "name": f"测试来源 {profile_id}", "revision": "A"},
        "processes": processes or [],
        "limits": limits,
    }


def test_machining_dfm_passes_machine_rules_but_stays_review_required(tmp_path: Path) -> None:
    """@brief 规则通过也必须保留人工复核状态。"""
    source = _write_document(
        tmp_path / "machining.cadstudio.json",
        {
            "process": "machining",
            "material": "Al6061",
            "wallThickness": 3.0,
            "minimumWallThickness": 1.5,
            "minimumDrillDiameter": 2.0,
            "internalCornerRadius": 2.0,
        },
    )

    report = build_dfm_report(source)

    assert report["status"] == "review_required"
    assert report["manualReviewRequired"] is True
    assert report["manual_review_required"] is True
    assert report["process"] == "machining"
    assert report["error_code"] is None
    assert {item["id"] for item in report["checks"]} >= {"material_declared", "machining_min_wall", "machining_min_drill"}
    assert all(item["status"] != "fail" for item in report["checks"])
    assert report["sourceSha256"]


def test_sheet_metal_dfm_blocks_missing_k_factor_and_bend_radius(tmp_path: Path) -> None:
    """@brief 缺少钣金关键输入时必须阻断，不得伪造可交付。"""
    source = _write_document(
        tmp_path / "sheet.cadstudio.json",
        {"process": "sheet_metal", "material": "Q235B", "wallThickness": 1.5},
    )

    report = build_dfm_report(source)

    assert report["status"] == "blocked"
    assert report["error_code"] == "dfm_missing_inputs"
    assert "metadata.manufacturing.bendRadius" in report["missingInputs"]
    assert "metadata.manufacturing.kFactor" in report["missingInputs"]


def test_3d_printing_build_volume_failure_is_review_evidence_not_certification(tmp_path: Path) -> None:
    """@brief 超出成型空间形成 fail 检查，但顶层仍是待人工复核。"""
    source = _write_document(
        tmp_path / "printed.cadstudio.json",
        {
            "process": "FDM",
            "material": "PLA",
            "wallThickness": 1.6,
            "buildVolume": [100, 100, 100],
            "maxUnsupportedOverhangDeg": 50,
        },
        features=[{"id": "base", "type": "box", "parameters": {"length": 220, "width": 90, "height": 30}}],
    )

    report = build_dfm_report(source)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["status"] == "review_required"
    assert checks["printing_build_volume"]["status"] == "fail"
    assert checks["printing_overhang"]["status"] == "warning"
    assert report["reviewFindings"]


def test_dfm_report_output_is_versioned_and_records_artifact_hash(tmp_path: Path) -> None:
    """@brief 写报告不得覆盖旧文件，返回产物必须带本轮 SHA-256。"""
    source = _write_document(
        tmp_path / "laser.cadstudio.json",
        {"process": "laser_cutting", "material": "304", "wallThickness": 2.0, "kerf": 0.15},
    )
    output = tmp_path / "reports" / "laser_dfm.json"

    first = write_dfm_report(source, output)
    second = write_dfm_report(source, output)

    first_path = Path(first["artifacts"][0]["path"])
    second_path = Path(second["artifacts"][0]["path"])
    assert first_path.name == "laser_dfm.json"
    assert second_path.name == "laser_dfm_v2.json"
    assert first_path.exists()
    assert second_path.exists()
    assert first["artifacts"][0]["sha256"]
    assert second["artifacts"][0]["producedThisRun"] is True
    persisted = json.loads(first_path.read_text(encoding="utf-8"))
    assert persisted["reportPath"] == str(first_path)
    assert persisted["artifacts"][0]["producedThisRun"] is True


def test_supplier_profile_records_hash_applicability_and_capacity_violations(tmp_path: Path) -> None:
    """@brief 供应商材料、机台空间和刀具不足必须成为可追溯违反项。"""
    source = _write_document(
        tmp_path / "supplier.cadstudio.json",
        {
            "process": "machining",
            "material": "Al7075",
            "wallThickness": 3.0,
            "internalCornerRadius": 1.0,
        },
        features=[
            {"id": "base", "type": "box", "parameters": {"length": 220, "width": 80, "height": 20}},
            {"id": "hole", "type": "hole", "parameters": {"diameter": 5.0, "depth": 40}},
        ],
    )
    supplier = _profile(
        "supplier.small-mill",
        {
            "allowedMaterials": ["Al6061"],
            "workEnvelope": [180, 100, 100],
            "minimumDrillDiameter": 6,
            "minimumInternalCornerRadius": 2,
            "availableToolDiameters": [6, 8, 10],
            "maximumHoleDepthDiameterRatio": 5,
        },
        processes=["machining"],
    )

    report = build_dfm_report(source, profiles=[supplier])
    violations = {item["id"] for item in report["profileViolations"]}

    assert report["status"] == "review_required"
    assert report["profiles"][0]["applicable"] is True
    assert len(report["profiles"][0]["sha256"]) == 64
    assert violations >= {
        "profile_material_capability",
        "profile_equipment_envelope",
        "profile_minimum_drill",
        "profile_tool_inventory",
        "profile_internal_corner_tooling",
        "profile_hole_depth_ratio",
    }
    assert report["manualReviewRequired"] is True


def test_profile_merge_uses_strict_intersection_and_never_relaxes_limits(tmp_path: Path) -> None:
    """@brief 后加载 Profile 不能放宽最小刀具和设备空间约束。"""
    source = _write_document(
        tmp_path / "merge.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 4, "internalCornerRadius": 3},
    )
    broad = _profile(
        "machine.broad",
        {"allowedMaterials": ["Al6061", "Q235B"], "minimumDrillDiameter": 2, "workEnvelope": [500, 400, 300]},
    )
    strict = _profile(
        "supplier.strict",
        {"allowedMaterials": ["Al6061"], "minimumDrillDiameter": 6, "workEnvelope": [200, 250, 180]},
    )

    report = build_dfm_report(source, profiles=[strict, broad])

    assert report["effectiveProfileLimits"]["minimumDrillDiameter"] == 6
    assert report["effectiveProfileLimits"]["workEnvelope"] == [200, 250, 180]
    assert report["effectiveProfileLimits"]["allowedMaterials"] == ["Al6061"]


def test_empty_material_intersection_blocks_conflicting_profiles(tmp_path: Path) -> None:
    """@brief 两个 Profile 能力交集为空时必须阻断而非任选其一。"""
    source = _write_document(
        tmp_path / "conflict.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 4},
    )

    report = build_dfm_report(
        source,
        profiles=[
            _profile("supplier.al", {"allowedMaterials": ["Al6061"]}),
            _profile("machine.steel", {"allowedMaterials": ["Q235B"]}),
        ],
    )

    assert report["status"] == "blocked"
    assert report["error_code"] == "dfm_invalid_profile"
    assert "交集为空" in report["checks"][0]["message"]


def test_sheet_metal_profile_checks_forming_space_thickness_and_bend_tooling(tmp_path: Path) -> None:
    """@brief 钣金 Profile 必须覆盖成型空间、厚度和折弯模具边界。"""
    source = _write_document(
        tmp_path / "sheet-profile.cadstudio.json",
        {
            "process": "sheet_metal",
            "material": "Q235B",
            "wallThickness": 4,
            "bendRadius": 2,
            "kFactor": 0.4,
        },
        features=[{"id": "base", "type": "box", "parameters": {"length": 500, "width": 200, "height": 4}}],
    )
    press_brake = _profile(
        "press-brake.01",
        {
            "formingEnvelope": [400, 300, 100],
            "minimumThickness": 0.8,
            "maximumThickness": 3,
            "minimumBendRadius": 3,
            "minimumBendRadiusRatio": 1,
        },
        processes=["sheet_metal"],
        source_type="machine",
    )

    report = build_dfm_report(source, profiles=[press_brake])
    violations = {item["id"] for item in report["profileViolations"]}

    assert violations >= {
        "profile_equipment_envelope",
        "profile_material_thickness",
        "profile_bending_capability",
    }


def test_printer_profile_limits_material_build_volume_wall_and_overhang(tmp_path: Path) -> None:
    """@brief 打印机与材料 Profile 必须共同限制成型空间、壁厚和悬垂角。"""
    source = _write_document(
        tmp_path / "printer.cadstudio.json",
        {
            "process": "FDM",
            "material": "ABS",
            "wallThickness": 0.8,
            "buildVolume": [500, 500, 500],
            "maxUnsupportedOverhangDeg": 60,
        },
        features=[{"id": "base", "type": "box", "parameters": {"length": 260, "width": 230, "height": 40}}],
    )
    printer = _profile(
        "printer.fdm-a",
        {
            "allowedMaterials": ["PLA", "PETG"],
            "buildVolume": [220, 220, 250],
            "minimumWallThickness": 1.2,
            "maximumUnsupportedOverhangDeg": 45,
        },
        processes=["3d_printing"],
        source_type="printer",
    )

    report = build_dfm_report(source, profiles=[printer])
    violations = {item["id"] for item in report["profileViolations"]}

    assert violations >= {
        "profile_material_capability",
        "profile_equipment_envelope",
        "profile_minimum_wall",
        "profile_printing_overhang",
    }


def test_profile_rejects_unknown_fields_and_relative_path_escape(tmp_path: Path) -> None:
    """@brief 未知覆盖字段和相对路径逃逸必须在读取前阻断。"""
    source_dir = tmp_path / "model"
    source_dir.mkdir()
    source = _write_document(
        source_dir / "part.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
    )
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_profile("outside", {"minimumWallThickness": 2})), encoding="utf-8")
    escaped = build_dfm_report(source, profiles=["../outside.json"])

    invalid = _profile("invalid", {"minimumWallThickness": 2})
    invalid["limits"]["executeCommand"] = "Remove-Item -Recurse C:\\"
    unknown = build_dfm_report(source, profiles=[invalid])

    assert escaped["status"] == "blocked"
    assert escaped["error_code"] == "dfm_invalid_profile"
    assert "逃逸" in escaped["checks"][0]["message"]
    assert unknown["status"] == "blocked"
    assert "未知或不允许覆盖" in unknown["checks"][0]["message"]


def test_profile_requires_real_brep_and_rejects_handwritten_claim(tmp_path: Path) -> None:
    """@brief 要求实体证据时缺失或手写伪来源都必须阻断。"""
    source = _write_document(
        tmp_path / "brep-required.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
    )
    profile = _profile("strict-brep", {"requiresBrepEvidence": True})

    missing = build_dfm_report(source, profiles=[profile])
    fake = build_dfm_report(
        source,
        profiles=[profile],
        brep_evidence={"measurement_source": "manual parameters", "envelope_mm": {"length": 1, "width": 1, "height": 1}},
    )
    artifact = tmp_path / "tampered.sldprt"
    artifact.write_bytes(b"changed")
    tampered = build_dfm_report(
        source,
        profiles=[profile],
        brep_evidence={
            "backend": "solidworks_brep",
            "producedThisRun": True,
            "sourceArtifact": str(artifact),
            "sourceSha256": "0" * 64,
            "measurements": {
                "units": "mm",
                "measurement_source": "SolidWorks API GetPartBox(True) + B-Rep cylindrical faces",
                "envelope_mm": {"length": 1, "width": 1, "height": 1},
            },
        },
    )

    assert missing["status"] == "blocked"
    assert missing["error_code"] == "dfm_brep_evidence_required"
    assert any("不能证明 SolidWorks" in item or "缺少真实 B-Rep" in item for item in missing["limitations"])
    assert fake["status"] == "blocked"
    assert fake["error_code"] == "dfm_invalid_brep_evidence"
    assert tampered["status"] == "blocked"
    assert "SHA-256 不匹配" in tampered["checks"][0]["message"]


def test_verified_solidworks_brep_is_hashed_and_drives_envelope_check(tmp_path: Path) -> None:
    """@brief 真实格式的 SolidWorks B-Rep 测量证据应参与包络判断并记录哈希。"""
    source = _write_document(
        tmp_path / "brep-valid.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
        features=[{"id": "base", "type": "box", "parameters": {"length": 10, "width": 10, "height": 10}}],
    )
    profile = _profile("verified-brep", {"requiresBrepEvidence": True, "workEnvelope": [100, 100, 100]})
    artifact = tmp_path / "brep-valid.sldprt"
    artifact.write_bytes(b"test-only-solidworks-artifact")
    evidence = {
        "backend": "solidworks_brep",
        "producedThisRun": True,
        "sourceArtifact": str(artifact),
        "sourceSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "measurements": {
            "units": "mm",
            "measurement_source": "SolidWorks API GetPartBox(True) + B-Rep cylindrical faces",
            "envelope_mm": {"length": 120, "width": 50, "height": 20},
            "holes": [],
            "errors": [],
        },
    }

    report = build_dfm_report(source, profiles=[profile], brep_evidence=evidence)
    envelope_check = next(item for item in report["checks"] if item["id"] == "profile_equipment_envelope")

    assert report["status"] == "review_required"
    assert report["brepEvidence"]["backend"] == "solidworks_brep"
    assert len(report["brepEvidence"]["sha256"]) == 64
    assert envelope_check["status"] == "fail"
    assert envelope_check["evidenceSource"] == "brep_evidence"


def test_verified_occt_brep_requires_nonempty_topology(tmp_path: Path) -> None:
    """@brief OCCT B-Rep 证据必须绑定本轮 .brep 产物且至少含一个实体。"""
    source = _write_document(
        tmp_path / "occt-brep.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
    )
    profile = _profile("occt-required", {"requiresBrepEvidence": True, "workEnvelope": [100, 100, 100]})
    artifact = tmp_path / "part.brep"
    artifact.write_bytes(b"occt-brep-test")
    base_evidence = {
        "backend": "headless_occt",
        "units": "mm",
        "producedThisRun": True,
        "sourceArtifact": str(artifact),
        "sourceSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "geometryEvidence": {
            "bounds": {"min": [0, 0, 0], "max": [50, 40, 10]},
            "topology": {"solids": 1, "faces": 6, "edges": 12, "vertices": 8},
        },
    }

    ok = build_dfm_report(source, profiles=[profile], brep_evidence=base_evidence)
    failed = build_dfm_report(
        source,
        profiles=[profile],
        brep_evidence={**base_evidence, "geometryEvidence": {**base_evidence["geometryEvidence"], "topology": {"solids": 0}}},
    )

    assert ok["status"] == "review_required"
    assert ok["brepEvidence"]["backend"] == "headless_occt"
    assert failed["status"] == "blocked"
    assert "未证明存在实体" in failed["checks"][0]["message"]


def test_non_applicable_profile_is_recorded_but_not_applied(tmp_path: Path) -> None:
    """@brief 混合 Profile 库中的其他工艺必须记录适用性但不能污染当前约束。"""
    source = _write_document(
        tmp_path / "applicability.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
    )
    printer = _profile("printer-only", {"buildVolume": [1, 1, 1]}, processes=["3d_printing"])

    report = build_dfm_report(source, profiles=[printer])

    assert report["profiles"][0]["applicable"] is False
    assert report["profiles"][0]["appliedLimits"] == []
    assert report["effectiveProfileLimits"] == {}


def test_profile_hash_is_stable_for_equivalent_key_order() -> None:
    """@brief Profile 哈希必须基于规范化内容而非 JSON 键顺序。"""
    first = _profile("stable", {"minimumWallThickness": 2, "allowedMaterials": ["Q235B", "Al6061"]})
    second = {
        "limits": {"allowedMaterials": ["Al6061", "Q235B"], "minimumWallThickness": 2.0},
        "source": {"revision": "A", "name": "测试来源 stable", "type": "supplier"},
        "id": "stable",
        "version": "1.0",
        "schema": "cadstudio.dfm-profile",
        "processes": [],
    }

    assert validate_profile(first)["sha256"] == validate_profile(second)["sha256"]


def test_inch_document_is_normalized_before_profile_capacity_checks(tmp_path: Path) -> None:
    """@brief 英寸模型必须先换算为毫米，不能直接与毫米设备空间比较。"""
    source = _write_document(
        tmp_path / "inch.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 0.125, "unit": "inch"},
        features=[{"id": "base", "type": "box", "parameters": {"length": 10, "width": 2, "height": 0.5}}],
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["units"] = "inch"
    source.write_text(json.dumps(payload), encoding="utf-8")
    machine = _profile("metric-machine", {"workEnvelope": [250, 100, 100], "minimumWallThickness": 3})

    report = build_dfm_report(source, profiles=[machine])
    envelope = next(item for item in report["checks"] if item["id"] == "profile_equipment_envelope")

    assert report["units"] == "mm"
    assert report["sourceUnits"] == "inch"
    assert envelope["status"] == "fail"
    assert envelope["modelSize"][0] == 254.0


def test_profile_rejects_boolean_numeric_limit() -> None:
    """@brief Python boolean 不得被悄悄当作 1 mm 数值。"""
    invalid = _profile("boolean-limit", {"minimumWallThickness": True})

    try:
        validate_profile(invalid)
    except ValueError as exc:
        assert "boolean" in str(exc)
    else:
        raise AssertionError("boolean 数值限制应被拒绝")


def test_dfm_review_cli_accepts_profile_and_records_effective_limits(tmp_path: Path) -> None:
    """@brief dfm_review.py CLI 必须能读取 Profile 并写出能力快照。"""
    source = _write_document(
        tmp_path / "cli-profile.cadstudio.json",
        {"process": "machining", "material": "Al6061", "wallThickness": 3},
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_profile("cli-profile", {"minimumWallThickness": 2.5})), encoding="utf-8")
    output = tmp_path / "dfm.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/dfm_review.py",
            "--input",
            str(source),
            "--output",
            str(output),
            "--profile",
            str(profile_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["effectiveProfileLimits"]["minimumWallThickness"] == 2.5
    assert payload["profiles"][0]["applicable"] is True
    assert Path(payload["reportPath"]).exists()
