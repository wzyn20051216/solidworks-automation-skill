"""@brief SolidWorks Add-in 宿主部署探测器测试。"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.sw_addin_host as host


def test_probe_does_not_treat_current_user_com_as_in_process_ready(monkeypatch, tmp_path: Path) -> None:
    """@brief 仅 HKCU COM 激活不得冒充 SolidWorks HKLM 发现链。"""
    assembly = tmp_path / "host.dll"
    assembly.write_bytes(b"MZ")
    states = iter([True, False, False, False, False, False])
    monkeypatch.setattr(host.platform, "system", lambda: "Windows")
    monkeypatch.setattr(host, "_registry_key_exists", lambda *_args: next(states))
    monkeypatch.setattr(host, "_read_diagnostics", lambda: (tmp_path / "status.json", None, None))

    result = host.probe_addin_host(assembly)

    assert result["status"] == "blocked"
    assert result["current_user_com_registered"] is True
    assert result["machine_solidworks_discovery_registered"] is False
    assert "HKLM_ADDIN_REGISTRATION_MISSING" in {item["code"] for item in result["blockers"]}
    assert "TYPE_LIBRARY_REGISTRATION_MISSING" in {item["code"] for item in result["blockers"]}


def test_probe_requires_all_callback_and_ui_evidence(monkeypatch, tmp_path: Path) -> None:
    """@brief ConnectToSW 状态和三类 UI 证据全部为真才可 ready。"""
    assembly = tmp_path / "host.dll"
    assembly.write_bytes(b"MZ")
    assembly.with_suffix(".tlb").write_bytes(b"MSFT")
    diagnostics = {
        "status": "connected",
        "hostProcessId": 4242,
        "hostProcessName": "SLDWORKS",
        "callbackRegistered": True,
        "commandGroupReady": True,
        "taskPaneReady": True,
        "propertyManagerPageReady": True,
        "errors": [],
    }
    monkeypatch.setattr(host.platform, "system", lambda: "Windows")
    monkeypatch.setattr(host, "_registry_key_exists", lambda *_args: True)
    monkeypatch.setattr(host, "_read_diagnostics", lambda: (tmp_path / "status.json", diagnostics, None))
    monkeypatch.setattr(host, "_process_is_running", lambda process_id: process_id == 4242)

    result = host.probe_addin_host(assembly)

    assert result["status"] == "ready"
    assert result["ui_ready"] is True
    assert result["in_process_host"] is True
    assert result["blockers"] == []
