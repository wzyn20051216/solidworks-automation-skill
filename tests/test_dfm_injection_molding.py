"""@brief 注塑声明型规则、单位和入口一致性，不声称真实模具认证。"""
import json
from pathlib import Path
import sys
import subprocess
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
from scripts.dfm_review import build_dfm_report


def source(path, **changes):
    """@brief 声明型测试输入，明确与 B-Rep 事实区分。"""
    manufacturing = {"process": "injection_molding", "material": "ABS", "wallThickness": 2,
        "draftAngleDeg": 2, "minimumDraftAngleDeg": 1.5,
        "ribThickness": 1, "maximumRibWallRatio": .6, "maxWallThickness": 2.2,
        "maximumWallThicknessVariation": 2, "undercutCount": 0, "gateOnCosmeticFace": False,
        "ejectorWaterClearanceMm": 5, "minimumEjectorWaterClearance": 4}
    manufacturing.update(changes)
    payload = {"documentId": "molding", "units": "mm", "features": [{"id": "base", "type": "box",
        "parameters": {"length": 30, "width": 20, "height": 8}}], "metadata": {"manufacturing": manufacturing}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_rules_pass_without_claiming_certification(tmp_path):
    report = build_dfm_report(source(tmp_path / "part.json"))
    assert report["status"] == "review_required"
    assert report["manualReviewRequired"] is True
    assert all(check["status"] != "fail" for check in report["checks"])


def test_zero_draft_and_undeclared_side_action_are_failures(tmp_path):
    report = build_dfm_report(source(tmp_path / "part.json", draftAngleDeg=0, undercutCount=1))
    failed = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert {"injection_draft_angle", "injection_undercut_side_action"} <= failed


def test_profile_only_tightens_declared_threshold(tmp_path):
    profile = {"schema": "cadstudio.dfm-profile", "version": "1.0", "id": "supplier",
        "source": {"type": "supplier", "name": "test", "revision": "A"},
        "processes": ["injection_molding"], "limits": {"maximumRibWallRatio": .4}}
    report = build_dfm_report(source(tmp_path / "part.json"), profiles=[profile])
    check = next(check for check in report["checks"] if check["id"] == "injection_rib_wall_ratio")
    assert check["status"] == "fail"
    assert check["limit"] == .4


def test_metadata_length_units_and_explicit_mm_remain_consistent(tmp_path):
    path = source(tmp_path / "inch.json", wallThickness=2 / 25.4, ribThickness=1 / 25.4,
        maxWallThickness=2.2 / 25.4, minimumEjectorWaterClearance=4 / 25.4)
    payload = json.loads(path.read_text())
    payload["metadata"]["manufacturing"]["unit"] = "inch"
    path.write_text(json.dumps(payload))
    report = build_dfm_report(path)
    ratio = next(check for check in report["checks"] if check["id"] == "injection_rib_wall_ratio")
    clearance = next(check for check in report["checks"] if check["id"] == "injection_ejector_water_clearance")
    assert ratio["value"] == .5
    assert clearance["value"] == 5
    assert clearance["limit"] == pytest.approx(4)


def test_mcp_accepts_the_same_process_name(tmp_path):
    import server
    path = source(tmp_path / "part.cadstudio.json")
    assert server.CadStudioDfmReviewInput(input_path=str(path), output_path=str(tmp_path / "report.json"), process="injection_molding").process == "injection_molding"


def test_cli_emits_injection_report_and_preserves_manual_review(tmp_path):
    """@brief 真实 CLI 接受同一工艺，落盘报告保留工程复核门禁。"""
    root = Path(__file__).resolve().parents[1]
    path = source(tmp_path / "part.cadstudio.json")
    output = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(root / "scripts/cad_studio.py"), "check-dfm",
        "--input", str(path), "--output", str(output), "--process", "injection_molding"],
        cwd=root, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["process"] == "injection_molding"
    assert report["manualReviewRequired"] is True
    assert report["status"] == "review_required"
