"""@brief .NET 出图执行器 Python 启动器/契约的无 COM 回归测试。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import sw_drawing_dotnet as launcher


def _good_spec(tmp_path):
    spec = {
        "schemaVersion": "1.0",
        "sourceModel": "panel.SLDPRT",
        "documentType": "part",
        "standard": "GB_T",
        "projection": "first_angle",
        "paperSize": "A3",
        "modelSizeMm": [300, 200, 25],
        "views": {"front": {}},
        "outputs": {"slddrw": True, "pdf": True, "report": True},
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_parse_evidence_good_bad_nondict():
    assert launcher.parse_evidence('{"status":"pass"}')["status"] == "pass"
    assert launcher.parse_evidence("not json")["status"] == "blocked"
    assert launcher.parse_evidence("[1,2]")["status"] == "blocked"


def test_summarize_result_classifies_stages():
    evidence = {
        "status": "pass",
        "stages": {
            "views": {"status": "ok"},
            "professionalAnnotations": {"status": "pilot"},
            "holeTable": {"status": "pilot"},
            "save": {"status": "ok"},
        },
        "artifacts": [
            {"kind": "slddrw", "path": "a.SLDDRW", "exists": True},
            {"kind": "pdf", "path": "a.pdf", "exists": False},
        ],
    }
    s = launcher.summarize_result(evidence)
    assert s["status"] == "pass"
    assert s["pilotStages"] == ["holeTable", "professionalAnnotations"]
    assert s["failedStages"] == []
    assert s["producedArtifacts"] == ["a.SLDDRW"]


def test_summarize_reports_failed_stage():
    evidence = {"status": "failed", "stages": {"save": {"status": "fail"}}}
    assert launcher.summarize_result(evidence)["failedStages"] == ["save"]


def test_resolve_executor_explicit_missing(tmp_path):
    assert launcher.resolve_executor(str(tmp_path / "nope.exe")) is None


def test_resolve_executor_env(monkeypatch, tmp_path):
    exe = tmp_path / "exec.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("CADSTUDIO_DRAWING_EXE", str(exe))
    assert launcher.resolve_executor() == str(exe)


def test_spec_gate_blocks_bad_spec(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"documentId":"x"}', encoding="utf-8")
    result = launcher.run_drawing_executor(bad)
    assert result["status"] == "blocked"
    assert "schema" in result["reason"]


def test_valid_spec_without_executor_blocks_with_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "resolve_executor", lambda explicit=None: None)
    result = launcher.run_drawing_executor(_good_spec(tmp_path))
    assert result["status"] == "blocked"
    assert result["reason"] == "executor_not_found"
    assert result["hint"]


def test_successful_launch_parses_evidence(tmp_path, monkeypatch):
    spec = _good_spec(tmp_path)
    monkeypatch.setattr(launcher, "resolve_executor", lambda explicit=None: str(tmp_path / "fake.exe"))

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        # 模拟 C# 执行器写 evidence 文件。
        evidence_out = Path(cmd[cmd.index("--evidence-out") + 1])
        evidence_out.write_text(
            json.dumps(
                {
                    "schema": "cadstudio.drawing-evidence",
                    "status": "pass",
                    "stages": {"views": {"status": "ok"}, "professionalAnnotations": {"status": "pilot"}, "save": {"status": "ok"}},
                    "artifacts": [{"kind": "slddrw", "path": "panel.SLDDRW", "exists": True}],
                }
            ),
            encoding="utf-8",
        )
        return _Completed()

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    result = launcher.run_drawing_executor(spec, output_dir=tmp_path)
    assert result["status"] == "pass"
    assert result["exitCode"] == 0
    assert result["pilotStages"] == ["professionalAnnotations"]
    assert result["evidencePath"] is not None


def test_timeout_returns_blocked(tmp_path, monkeypatch):
    spec = _good_spec(tmp_path)
    monkeypatch.setattr(launcher, "resolve_executor", lambda explicit=None: str(tmp_path / "fake.exe"))

    def fake_run(cmd, capture_output, text, timeout):
        raise launcher.subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    result = launcher.run_drawing_executor(spec, output_dir=tmp_path, timeout=5)
    assert result["status"] == "blocked"
    assert "超时" in result["reason"]
