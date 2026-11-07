"""自动配置的离线、失败、哈希和不覆盖边界。"""
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts import api_environment as env


@pytest.fixture(autouse=True)
def reset_setup_state(monkeypatch, tmp_path):
    env._FAILED_UNTIL.clear()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SW_API_LOOKUP_NETWORK", raising=False)
    monkeypatch.delenv("SW_API_LOOKUP_AUTO_INSTALL", raising=False)
    yield
    env._FAILED_UNTIL.clear()


def test_offline_or_disabled_never_installs_python(monkeypatch):
    monkeypatch.setattr(env, "_missing", lambda modules: True)
    monkeypatch.setattr(env, "_run_setup", lambda *a, **k: pytest.fail("unexpected install"))
    assert "关闭" in env.ensure_python_packages(("httpx>=0.27.1,<1",), ("httpx",), allow_network=False)
    monkeypatch.setenv("SW_API_LOOKUP_AUTO_INSTALL", "off")
    assert "关闭" in env.ensure_python_packages(("httpx>=0.27.1,<1",), ("httpx",), allow_network=True)


def test_python_packages_install_only_when_missing_and_recheck(monkeypatch):
    checks = iter([True, True, False])
    monkeypatch.setattr(env, "_missing", lambda modules: next(checks))
    calls = []
    monkeypatch.setattr(env, "_run_setup", lambda args, timeout, cancelled: calls.append((args, timeout)))
    assert env.ensure_python_packages(("httpx>=0.27.1,<1",), ("httpx",), allow_network=True) is None
    assert calls[0][0][0] == env.sys.executable and "httpx>=0.27.1,<1" in calls[0][0]
    assert "--only-binary=:all:" in calls[0][0] and calls[0][1] == 180


def test_invalid_existing_portable_sevenzip_is_never_overwritten(monkeypatch):
    root = env._portable_root()
    root.mkdir(parents=True)
    (root / "7z.exe").write_bytes(b"existing-user-data")
    monkeypatch.setattr(env, "_download", lambda *a: pytest.fail("unexpected download"))
    if env.os.name != "nt":
        pytest.skip("Windows portable setup")
    monkeypatch.setattr(env.platform, "machine", lambda: "AMD64")
    path, warning = env.ensure_sevenzip(allow_network=True)
    assert path is None and "未覆盖" in warning
    assert (root / "7z.exe").read_bytes() == b"existing-user-data"


def test_7zip_download_checks_hash_and_size(monkeypatch, tmp_path):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b"tampered"
    monkeypatch.setattr(env.urllib.request, "urlopen", lambda *a, **k: Response())
    target = tmp_path / "binary.exe"
    with pytest.raises(ValueError, match="哈希"):
        env._download("https://example.test/file", "0" * 64, target)
    assert not target.exists()


def test_unavailable_sevenzip_reports_disabled_without_network(monkeypatch):
    if env.os.name != "nt":
        pytest.skip("Windows portable setup")
    monkeypatch.setattr(env.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(env, "_download", lambda *a: pytest.fail("unexpected download"))
    path, warning = env.ensure_sevenzip(allow_network=False)
    assert path is None and "离线" in warning


def test_cancelled_setup_terminates_child(monkeypatch):
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None): return self.returncode
        def terminate(self): self.returncode = -1
    proc = Process()
    monkeypatch.setattr(env.subprocess, "Popen", lambda *a, **k: proc)
    with pytest.raises(env.SetupCancelled):
        env._run_setup(["example"], 10, lambda: True)
    assert proc.returncode == -1


def test_setup_lock_serializes_processes_and_allows_cancellation():
    code = ("import time; from scripts.api_environment import _setup_lock; "
            "ctx=_setup_lock(None); acquired=ctx.__enter__(); "
            "print('locked' if acquired else 'failed', flush=True); time.sleep(10); ctx.__exit__(None,None,None)")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "locked"
        start = time.monotonic()
        with env._setup_lock(lambda: time.monotonic() - start > 0.3) as acquired:
            assert acquired is False
    finally:
        child.terminate()
        child.wait(timeout=5)
    with env._setup_lock(None) as acquired:
        assert acquired is True


def test_com_preflight_installs_without_prompt_and_can_be_disabled(monkeypatch):
    from scripts import sw_preflight as preflight
    checks = iter([["pywin32>=305"], []])
    monkeypatch.setattr(preflight, "missing_com_dependencies", lambda: next(checks))
    installed = []
    monkeypatch.setattr(preflight, "install_com_dependencies", lambda **kwargs: installed.append(kwargs["requirements"]))
    monkeypatch.delenv("SW_AUTO_INSTALL_DEPENDENCIES", raising=False)
    assert preflight.ensure_com_dependencies(input_func=lambda _: pytest.fail("unexpected approval")) == ["pywin32>=305"]
    assert installed == [("pywin32>=305",)]
    monkeypatch.setattr(preflight, "missing_com_dependencies", lambda: ["pywin32>=305"])
    monkeypatch.setenv("SW_AUTO_INSTALL_DEPENDENCIES", "off")
    with pytest.raises(preflight.DependencyInstallDeclined):
        preflight.ensure_com_dependencies()


def test_com_preflight_retries_official_pypi_after_primary_index_failure(monkeypatch):
    from scripts import sw_preflight as preflight

    calls = []

    def fake_check_call(command, timeout):
        calls.append((list(command), timeout))
        if len(calls) == 1:
            raise preflight.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(preflight.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(preflight.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(preflight.site, "addsitedir", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("SW_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SW_PIP_FALLBACK_INDEX_URL", raising=False)

    preflight.install_com_dependencies(requirements=("comtypes>=1.2.0",))

    assert len(calls) == 2
    assert "--index-url" in calls[1][0]
    assert "https://pypi.org/simple" in calls[1][0]


def test_help_restore_rejects_wrong_product_and_requires_hash(monkeypatch, tmp_path):
    from scripts import api_help_restore as restore
    msi = tmp_path / "solidworks.msi"
    def rows(path, query, columns):
        if "FROM `Property`" in query:
            return [["ProductCode", "{RIGHT}"], ["ProductVersion", "34.111.0011"]]
        if "FROM `File`" in query:
            return [["sldworksapi.chm", "sldworksapi.chm", "818", "1024"]]
        if "FROM `Media`" in query:
            return [["937", "HelpFi~2.cab"], ["847", "HelpFi~1.cab"]]
        return [["sldworksapi.chm", "-1", "2", "3", "4"]]
    monkeypatch.setattr(restore, "_msi_rows", rows)
    with pytest.raises(ValueError, match="产品或版本"):
        restore._msi_metadata(msi, "{WRONG}", "34.111.0011", "sldworksapi.chm")
    cabinet, key, digest, size = restore._msi_metadata(msi, "{RIGHT}", "34.111.0011", "sldworksapi.chm")
    assert cabinet.name == "HelpFi~1.cab" and key == "sldworksapi.chm"
    assert digest == [0xFFFFFFFF, 2, 3, 4]
    assert size == 1024


def test_missing_help_does_not_download_7zip_when_install_source_missing(monkeypatch, tmp_path):
    from scripts import local_api_evidence as local
    monkeypatch.setattr(local, "_registered_source", lambda *a: None)
    monkeypatch.setattr(local, "ensure_sevenzip", lambda **kwargs: pytest.fail("unexpected download"))
    warnings = []
    result = local.read_local_help(tmp_path / "SLDWORKS.exe", 2026, "ISketchManager", "CreateCircleByRadius",
        "https://help.solidworks.com/2026/english/api/a.html", allow_install=True, warnings=warnings)
    assert result is None and any("安装源" in warning for warning in warnings)


def test_offline_missing_help_never_verifies_installer_signature(monkeypatch, tmp_path):
    from scripts import local_api_evidence as local
    monkeypatch.setattr(local, "_registered_source", lambda *a: pytest.fail("unexpected installer check"))
    monkeypatch.setattr(local, "ensure_sevenzip", lambda **kwargs: pytest.fail("unexpected download"))
    warnings = []
    result = local.read_local_help(tmp_path / "SLDWORKS.exe", 2026, "ISketchManager", "CreateCircleByRadius",
        "https://help.solidworks.com/2026/english/api/a.html", allow_install=False, warnings=warnings)
    assert result is None and any("离线" in warning for warning in warnings)


def test_help_restore_refuses_unsigned_installer_without_extracting(monkeypatch, tmp_path):
    from scripts import api_help_restore as restore
    source = tmp_path / "solidworks.msi"
    source.write_bytes(b"untrusted")
    monkeypatch.setattr(restore, "_registered_source", lambda *a: (source, "{RIGHT}", "34.111.0011"))
    monkeypatch.setattr(restore, "_signed_by_solidworks", lambda *a: False)
    monkeypatch.setattr(restore, "_msi_metadata", lambda *a: pytest.fail("unsigned installer used"))
    path, warning = restore.restore_local_help(tmp_path / "SLDWORKS.exe", 2026, "sldworksapi.chm", "7z.exe")
    assert path is None and "无法" in warning
    assert not (tmp_path / "solidworks-automation").exists()


def test_help_extract_stops_when_exceeding_signed_size(monkeypatch, tmp_path):
    from scripts import api_help_restore as restore
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None): return self.returncode
        def terminate(self): self.returncode = -1
    process = Process()
    monkeypatch.setattr(restore.subprocess, "Popen", lambda *args, **kwargs: process)
    target = tmp_path / "topic.tmp"
    target.write_bytes(b"too large")
    with target.open("rb") as handle:
        with pytest.raises(ValueError, match="大小"):
            restore._extract_bounded("7z", tmp_path / "help.cab", "api.chm", target, handle, 4, None)
    assert process.returncode == -1
