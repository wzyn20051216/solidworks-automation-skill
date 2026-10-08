"""@brief 回退 PID/版本、短期进程与失败契约；不启动 CAD。"""
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from scripts import sw_delivery
from scripts.sw_connect import SolidWorksConnectionError


def app(pid=7, revision="34.1.1"):
    """@brief 创建带真实形状身份字段的共享实例替身。"""
    return SimpleNamespace(GetProcessID=lambda: pid, RevisionNumber=lambda: revision)


def constructor_fixture(monkeypatch, before, target):
    """@brief ROT 不可用时返回指定对象，便于测量所有权。"""
    monkeypatch.setattr(sw_delivery, "solidworks_processes", lambda: before)
    monkeypatch.setattr(sw_delivery, "_LaunchGuard", nullcontext)
    class Client:
        calls = 0
        def GetActiveObject(self, _):
            raise RuntimeError("ROT unavailable")
        def CreateObject(self, _):
            self.calls += 1
            return target
    return Client()


def test_create_object_returning_existing_pid_is_not_owned(monkeypatch):
    target = app()
    client = constructor_fixture(monkeypatch, {7: 2026}, target)
    connected, owned, _ = sw_delivery._connect_comtypes_solidworks(client, ["fixture"], expected_pid=7)
    assert connected is target and owned is False


def test_unknown_snapshot_blocks_creation(monkeypatch):
    client = constructor_fixture(monkeypatch, None, app())
    with pytest.raises(SolidWorksConnectionError, match="SW_PROCESS_STATE_UNAVAILABLE"):
        sw_delivery._connect_comtypes_solidworks(client, ["fixture"])
    assert client.calls == 0


@pytest.mark.parametrize("target,code", [(app(8), "SW_INSTANCE_MISMATCH"), (app(7, "33.1.0"), "SW_VERSION_MISMATCH")])
def test_wrong_pid_or_year_is_blocked(monkeypatch, target, code):
    client = constructor_fixture(monkeypatch, {7: 2026}, target)
    with pytest.raises(SolidWorksConnectionError, match=code):
        sw_delivery._connect_comtypes_solidworks(client, ["fixture"], expected_pid=7)


def worker_call(monkeypatch, tmp_path, run):
    """@brief 封装实际包装器，所有 subprocess 调用由当前用例接管。"""
    monkeypatch.setattr(sw_delivery.win32com_client, "GetActiveObject", lambda _: app())
    monkeypatch.setattr(sw_delivery.subprocess, "run", run)
    return sw_delivery._comtypes_pack_and_go("中文😀.sldprt", tmp_path, {}, include_drawings=False,
        include_simulation_results=False, include_toolbox_components=False, include_suppressed=False, flatten=True)


def test_child_protocol_is_utf8_bound_to_parent_and_has_timeout(monkeypatch, tmp_path):
    def run(command, **options):
        payload = json.loads(options["input"])
        assert payload["expected_pid"] == 7
        assert payload["source_path"] == "中文😀.sldprt"
        assert options["timeout"] == 120
        assert options["env"]["PYTHONIOENCODING"] == "utf-8"
        assert command[0] == sys.executable and command[1].endswith("sw_delivery_comtypes_worker.py")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": {"process_id": 7, "backend": "comtypes"}}))
    assert worker_call(monkeypatch, tmp_path, run)["backend"] == "comtypes"


def test_timeout_cannot_be_reported_as_native_success(monkeypatch, tmp_path):
    def timeout(command, **_):
        raise subprocess.TimeoutExpired(command, 120)
    with pytest.raises(SolidWorksConnectionError, match="SW_PACK_AND_GO_TIMEOUT"):
        worker_call(monkeypatch, tmp_path, timeout)


@pytest.mark.parametrize("output", ['logs\n{"result": {}}', '{"result":{"process_id":8}}'])
def test_unverified_stdout_and_identity_are_blocked(monkeypatch, tmp_path, output):
    with pytest.raises(SolidWorksConnectionError, match="SW_PACK_AND_GO_WORKER_PROTOCOL"):
        worker_call(monkeypatch, tmp_path, lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=output))


def test_child_invalid_payload_is_json_failure_before_com_import():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/sw_delivery_comtypes_worker.py")],
        input=b'{"target":"fixture","expected_pid":0}', capture_output=True)
    assert result.returncode == 1
    assert "error" in json.loads(result.stdout)
