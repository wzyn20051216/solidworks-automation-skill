"""SolidWorks 2026 健康探测、冷启动回收和已有文档保护真机验收。"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from cad_doctor import probe_running_cad
from scripts.sw_connect import get_com_member
from scripts.sw_process import solidworks_processes
from scripts.sw_session import SolidWorksSession


def doctor_probe():
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/cad_doctor.py"), "--probe-cad"],
        capture_output=True, encoding="utf-8", timeout=240)
    assert process.returncode == 0, process.stderr + process.stdout
    report = json.loads(process.stdout)
    result = next(item for item in report["checks"] if item["id"] == "cad.solidworks.com")
    assert result["status"] == "passed" and result["code"] == "SOLIDWORKS_COM_READY", result
    assert not any(item["id"] == "cad.solidworks.com.cleanup" for item in report["checks"]), report


def main():
    before = solidworks_processes()
    assert before is not None
    cold_cleanup = False
    if not before:
        assert probe_running_cad("solidworks", True)["mode"] == "not_running"
        assert solidworks_processes() == before
        print("验证冷启动探测和实例清理", flush=True)
        doctor_probe()
        deadline = time.monotonic() + 30
        while solidworks_processes() and time.monotonic() < deadline:
            time.sleep(.5)
        assert solidworks_processes() == before
        cold_cleanup = True

    with SolidWorksSession(version=2026) as session:
        before_docs = {get_com_member(doc, "GetTitle") for doc in session._documents()}
        model = session.new_part()
        title = get_com_member(model, "GetTitle")
        pid = get_com_member(session.sw, "GetProcessID")
        visible = bool(get_com_member(session.sw, "Visible"))
        status = probe_running_cad("solidworks", True)
        assert status["ok"] is True and status["revision"].startswith("34."), status
        print("验证已有实例与文档保护", flush=True)
        doctor_probe()
        assert get_com_member(session.sw, "GetProcessID") == pid
        assert bool(get_com_member(session.sw, "Visible")) == visible
        assert title in {get_com_member(doc, "GetTitle") for doc in session._documents()}
        session.close(model)
        assert {get_com_member(doc, "GetTitle") for doc in session._documents()} == before_docs
    print(json.dumps({"status": "pass", "revision": status["revision"], "cold_cleanup": cold_cleanup,
                      "attached_document_preserved": True, "visibility_preserved": True}))


if __name__ == "__main__":
    main()
