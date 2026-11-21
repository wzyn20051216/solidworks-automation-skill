"""安装入口、只读健康探测及自检实例回收的回归。"""
import importlib.util
import json
from pathlib import Path
import runpy
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("cad_doctor_hardening", ROOT / "scripts/cad_doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


def test_legacy_setup_uses_release_version_without_client_install_hook(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(sys.modules, "setuptools", SimpleNamespace(setup=lambda **kwargs: calls.append(kwargs)))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for client in (".codex", ".claude"):
        target = tmp_path / client / "skills/solidworks-automation/scripts/user.py"
        target.parent.mkdir(parents=True)
        target.write_text("user customization", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(ROOT / "setup.py"))
    assert calls[0]["version"] == json.loads((ROOT / "package.json").read_text())["version"]
    assert not calls[0].get("cmdclass")
    assert all(path.read_text() == "user customization" for path in tmp_path.rglob("user.py"))


@pytest.mark.parametrize("mode", ["active", "not_running", "busy", "property_error", "empty_version"])
def test_readonly_live_probe_never_dispatches_or_mutates_application(monkeypatch, mode):
    initialized, released = Mock(), Mock()
    class ComError(Exception):
        hresult = -2147221021 if mode == "not_running" else -2147418111
    class App:
        @property
        def RevisionNumber(self):
            if mode == "property_error":
                raise ComError("busy")
            if mode == "empty_version":
                return None
            return lambda: "34.1.1"
        def __setattr__(self, *_):
            pytest.fail("只读探测修改了应用")
    active = Mock(side_effect=ComError("not available")) if mode in ("not_running", "busy") else Mock(return_value=App())
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(CoInitialize=initialized, CoUninitialize=released))
    monkeypatch.setitem(sys.modules, "win32com", SimpleNamespace(client=SimpleNamespace(GetActiveObject=active)))
    monkeypatch.setitem(sys.modules, "win32com.client", sys.modules["win32com"].client)
    report = doctor.probe_running_cad("solidworks", True)
    assert report["ok"] is (mode == "active")
    assert report["installed"] is True
    assert report["mode"] == {"active": "active", "not_running": "not_running", "busy": "unavailable", "property_error": "unavailable", "empty_version": "unavailable"}[mode]
    initialized.assert_called_once()
    released.assert_called_once()


@pytest.mark.parametrize(("owned", "documents", "cleanup_ok"), [(False, [], True), (True, [], True), (True, ["user-doc"], True), (True, [], False)])
def test_doctor_only_closes_empty_instance_it_started(monkeypatch, owned, documents, cleanup_ok):
    fake_sw = SimpleNamespace(
        connect_solidworks=Mock(return_value=(object(), None, {"started_by_cad_studio": owned, "process_id": 123})),
        get_com_member=Mock(return_value=documents),
        close_owned_solidworks=Mock(return_value=cleanup_ok),
    )
    monkeypatch.setitem(sys.modules, "sw_connect", fake_sw)
    monkeypatch.setattr(doctor, "_solidworks_installation", lambda: {"registered": True, "executables": [], "executable": ""})
    monkeypatch.setattr(doctor, "_is_writable", lambda _: True)
    report = doctor.run_doctor(probe_cad=True)
    assert next(check for check in report["checks"] if check["id"] == "cad.solidworks.com")["code"] == "SOLIDWORKS_COM_READY"
    assert fake_sw.close_owned_solidworks.call_count == int(owned and not documents)
    cleanup = [check for check in report["checks"] if check["id"] == "cad.solidworks.com.cleanup"]
    assert bool(cleanup) is (owned and (bool(documents) or not cleanup_ok))


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 原生 stderr 回归")
def test_codex_registration_handles_missing_server_stderr(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    marker = tmp_path / "added.txt"
    monkeypatch.setenv("PR71_TEST_MARKER", str(marker))
    (tmp_path / "codex.cmd").write_text(
        '@echo off\nif "%~2"=="add" (echo added>"%PR71_TEST_MARKER%" & exit /b 0)\n'
        'if exist "%PR71_TEST_MARKER%" (exit /b 0)\n'
        'echo server does not exist 1>&2\nexit /b 1\n', encoding="ascii")
    python_stub = tmp_path / "python-stub.cmd"
    python_stub.write_text("@echo off\nexit /b 0\n", encoding="ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(ROOT / "mcp-server/register_codex_mcp.ps1"),
         "-Name", "pr71-isolated-test", "-Python", str(python_stub)],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text().strip() == "added"


def test_doctor_json_remains_utf8_with_legacy_pipe_encoding():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/cad_doctor.py"), "--live-cad"],
        env={**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report["liveConnections"]) == {"solidworks", "autocad"}
