"""CAD Studio 能力门禁、诊断和连接策略回归测试。"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "desktop"))

from cad_diagnostics import create_diagnostic_bundle, _redact  # noqa: E402
from cad_doctor import run_doctor  # noqa: E402
from capabilities import capability_index, load_capabilities, unattended_allowed  # noqa: E402
from cad_workbench.queue_worker import process_job, read_job  # noqa: E402
from sw_connect import _prog_id_for_version, close_owned_solidworks  # noqa: E402
from cad_installation import discover_installation, resolve_shortcut_target  # noqa: E402


def test_capability_manifest_marks_unverified_workflows():
    index = capability_index(load_capabilities())
    assert index["part_and_features"]["level"] == "verified"
    assert index["parameter_updates"]["level"] == "pilot"
    assert index["custom_properties_and_bom"]["level"] == "pilot"
    assert index["pack_and_go"]["level"] == "pilot"
    assert index["sheet_metal"]["level"] == "reference_only"
    assert unattended_allowed(["part_and_features"]) is True
    assert unattended_allowed(["sheet_metal"]) is False


def test_job_is_blocked_for_reference_only_capability(tmp_path):
    path = tmp_path / "job.json"
    job = {
        "schemaVersion": "2.0",
        "id": "job-blocked",
        "runId": "run-blocked",
        "kind": "create_shell",
        "title": "钣金任务",
        "detail": "门禁测试",
        "status": "queued",
        "progress": 0,
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "projectId": "project-test",
        "conversationId": "conversation-test",
        "inputs": [],
        "stage": "intake",
        "capabilitySnapshot": {},
        "assumptions": [],
        "requiredArtifacts": [],
        "verificationEvidence": [],
        "capabilities": ["sheet_metal"],
        "policy": {"approval": "never"},
    }
    path.write_text(json.dumps(job), encoding="utf-8")
    result = process_job(path, handlers={"create_shell": lambda _: {"message": "should not run"}})
    assert result is not None
    assert result["status"] == "blocked"
    assert result["stage"] == "blocked"
    assert "sheet_metal" in result["blockedReasons"][0]
    assert read_job(path)["status"] == "blocked"


def test_diagnostics_redacts_sensitive_values(tmp_path):
    redacted = _redact({"prompt": "secret prompt", "apiKey": "abc", "projectPath": r"C:\Users\Alice\job"})
    assert redacted == {"prompt": "[redacted]", "apiKey": "[redacted]", "projectPath": "[redacted]"}
    bundle = create_diagnostic_bundle(tmp_path / "diagnostics.zip", events={"prompt": "private"})
    with zipfile.ZipFile(bundle) as archive:
        payload = json.loads(archive.read("diagnostic.json"))
    assert payload["events"]["prompt"] == "[redacted]"
    for installation in payload["doctor"].get("installations", {}).values():
        executable = installation.get("executable")
        assert not executable or "\\" not in executable


def test_doctor_returns_machine_readable_summary():
    result = run_doctor()
    assert result["schemaVersion"] == "1.0"
    assert result["summary"]["status"] in {"passed", "warning", "error"}
    assert all({"id", "status", "code", "message"} <= set(item) for item in result["checks"])


def test_versioned_progid_is_used_for_attach_and_launch():
    assert _prog_id_for_version(2024) == "SldWorks.Application.32"
    assert _prog_id_for_version("2026") == "SldWorks.Application.34"


def test_only_owned_solidworks_instance_can_be_closed():
    class FakeSolidWorks:
        closed = False

        def ExitApp(self):
            self.closed = True

    app = FakeSolidWorks()
    assert close_owned_solidworks(app, False) is False
    assert app.closed is False
    assert close_owned_solidworks(app, True) is True
    assert app.closed is True


def test_installer_shortcut_resolves_real_solidworks_executable():
    candidates = resolve_shortcut_target(
        r"C:\WINDOWS\Installer\{demo}\i386_SldWorks.exe",
        r"E:\Solidworks\SOLIDWORKS",
        "SLDWORKS.exe",
    )
    assert Path(r"E:\Solidworks\SOLIDWORKS\SLDWORKS.exe") in candidates
    assert Path(r"C:\WINDOWS\Installer\{demo}\i386_SldWorks.exe") not in candidates


def test_direct_autocad_shortcut_target_is_preserved():
    candidates = resolve_shortcut_target(
        r"D:\AutoCAD 2024\acad.exe",
        r"D:\AutoCAD 2024\UserDataCache",
        "acad.exe",
    )
    assert Path(r"D:\AutoCAD 2024\acad.exe") in candidates


def test_discover_installation_supports_injected_filesystem():
    # 发现逻辑接受 exists 注入，CI 不需要安装 CAD 也能覆盖候选排序与结构。
    result = discover_installation("autocad", exists=lambda path: str(path).lower() == r"d:\autocad 2024\acad.exe")
    assert result["installed"] is True
    assert result["executable"].lower().endswith(r"autocad 2024\acad.exe")
