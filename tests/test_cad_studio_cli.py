"""CAD Studio CLI 与桌面端任务语义的一致性测试。"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.cad_studio import prepare_job_for_retry


def test_cli_retry_preserves_history_and_clears_current_evidence():
    job = {
        "schemaVersion": "2.0",
        "id": "job-cli-retry",
        "runId": "run-old",
        "status": "failed",
        "progress": 100,
        "result": {"message": "旧结果"},
        "artifacts": [{"path": "old.step", "producedThisRun": True}],
        "drawingEvidence": {"status": "failed", "stage": "review"},
        "reviewFindings": [{"id": "dimension-overlap"}],
        "reviewGate": {"status": "fail"},
        "error": "旧错误",
        "prompt": "不应复制到历史快照",
    }

    result = prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")

    assert result["status"] == "queued"
    assert result["runId"].startswith("retry-")
    assert result["retryPolicy"]["retryFromStage"] == "drawing-bom"
    assert result["retryPolicy"]["overwrite"] is False
    assert result["artifacts"] == []
    assert result["runHistory"][0]["artifacts"][0]["path"] == "old.step"
    assert "prompt" not in result["runHistory"][0]
    for field in ("result", "drawingEvidence", "reviewFindings", "reviewGate", "error"):
        assert field not in result


def test_cli_retry_keeps_only_latest_twenty_runs():
    job = {
        "runId": "run-current",
        "status": "blocked",
        "runHistory": [{"runId": f"old-{index}"} for index in range(20)],
    }

    result = prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")

    assert len(result["runHistory"]) == 20
    assert result["runHistory"][0]["runId"] == "old-1"
    assert result["runHistory"][-1]["runId"] == "run-current"


def test_cli_retry_rejects_active_job():
    job = {"runId": "run-active", "status": "running"}

    try:
        prepare_job_for_retry(job, "2026-08-02T00:00:00+00:00")
    except ValueError as exc:
        assert "不可重试" in str(exc)
    else:
        raise AssertionError("运行中任务不应允许重试")


def test_check_dfm_cli_generates_report(tmp_path: Path):
    """@brief check-dfm 命令必须输出真实 JSON 报告。"""
    source = tmp_path / "plate.cadstudio.json"
    source.write_text(
        json.dumps(
            {
                "documentId": "plate",
                "features": [{"id": "base", "type": "box", "parameters": {"length": 100, "width": 50, "height": 8}}],
                "metadata": {"manufacturing": {"process": "machining", "material": "Al6061", "wallThickness": 3}},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "dfm.json"
    completed = subprocess.run(
        [sys.executable, "scripts/cad_studio.py", "check-dfm", "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "review_required"
    assert Path(payload["reportPath"]).exists()
    assert payload["artifacts"][0]["producedThisRun"] is True


def _fea_request() -> dict:
    """@brief 返回 CLI prepare-fea 使用的最小静力请求。"""
    return {
        "schemaVersion": "1.0",
        "analysisId": "cli_static",
        "analysisType": "static_linear",
        "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {"name": "Al6061", "elasticModulusMPa": 68900, "poissonRatio": 0.33, "densityKgM3": 2700},
        "mesh": {
            "nodes": [
                {"id": 1, "x": 0, "y": 0, "z": 0},
                {"id": 2, "x": 10, "y": 0, "z": 0},
                {"id": 3, "x": 0, "y": 10, "z": 0},
                {"id": 4, "x": 0, "y": 0, "z": 10},
            ],
            "elements": [{"id": 1, "type": "C3D4", "nodeIds": [1, 2, 3, 4]}],
            "nodeSets": {"FixedNodes": [1, 2, 3], "LoadNode": [4]},
            "elementSets": {"AllElements": [1]},
        },
        "constraints": [{"id": "fixed_base", "type": "fixed", "nodeSet": "FixedNodes"}],
        "loads": [{"id": "tip_force", "type": "force", "nodeSet": "LoadNode", "dof": 3, "value": -100}],
    }


def _advanced_geometry_plan() -> dict:
    """@brief 返回 CLI 复杂几何门禁使用的最小有效计划。"""
    return {
        "schemaVersion": "1.0",
        "planId": "cli_surface",
        "units": "mm",
        "entities": [
            {"id": "profileA", "type": "profile", "source": "section:A"},
            {"id": "profileB", "type": "profile", "source": "section:B"},
        ],
        "operations": [
            {"id": "loftMain", "type": "loft", "profiles": ["profileA", "profileB"], "continuity": "G1", "output": "loftSurface"}
        ],
    }


def test_cli_prepare_fea_generates_versioned_calculix_input(tmp_path: Path):
    """@brief prepare-fea 必须生成本轮 CalculiX 输入且不依赖求解器安装。"""
    source = tmp_path / "fea.json"
    source.write_text(json.dumps(_fea_request()), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "scripts/cad_studio.py", "prepare-fea", "--input", str(source), "--out-dir", str(tmp_path / "fea-out")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "pass"
    artifact = Path(payload["artifacts"][0]["path"])
    assert artifact.is_file()
    assert artifact.read_text(encoding="ascii").startswith("** CAD Studio generated")


def test_cli_review_advanced_geometry_writes_report(tmp_path: Path):
    """@brief 复杂几何 CLI 只能输出 pilot/blocked 门禁报告，不声称产出几何。"""
    source = tmp_path / "surface.json"
    source.write_text(json.dumps(_advanced_geometry_plan()), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "scripts/cad_studio.py", "review-advanced-geometry", "--input", str(source), "--output", str(tmp_path / "surface_report.json")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode in {0, 1}
    payload = json.loads(completed.stdout)
    assert payload["status"] in {"pilot", "blocked"}
    assert payload["geometryProduced"] is False
    assert Path(payload["reportPath"]).exists()
