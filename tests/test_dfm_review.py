"""DFM 规则复核回归。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.dfm_review import build_dfm_report, write_dfm_report


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
