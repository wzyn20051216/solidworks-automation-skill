"""审批账本有界增长；不删除用户已有记录。"""
from __future__ import annotations

import concurrent.futures
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))
import approval


def test_request_limit_reuses_duplicate_and_preserves_existing_records(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "MAX_APPROVAL_REQUEST_RECORDS", 2)
    ledger = approval.ApprovalLedger(tmp_path)
    first = ledger.request("solidworks_create_basic_part", {"n": 1}, "write", subject="a")
    second = ledger.request("solidworks_create_basic_part", {"n": 2}, "write", subject="a")
    before = {path.name: path.read_bytes() for path in ledger.requests_dir.glob("*.json")}
    assert ledger.request("solidworks_create_basic_part", {"n": 1}, "write", subject="a") == first
    with pytest.raises(approval.ApprovalError, match="Onay isteği kayıtları kapasite sınırına ulaştı"):
        ledger.request("solidworks_create_basic_part", {"n": 3}, "write", subject="a")
    assert {path.name: path.read_bytes() for path in ledger.requests_dir.glob("*.json")} == before
    assert {r["id"] for r in ledger.pending()} == {first["id"], second["id"]}


def test_grant_limit_does_not_change_request_or_existing_grants(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "MAX_APPROVAL_GRANT_RECORDS", 1)
    ledger = approval.ApprovalLedger(tmp_path)
    pending = ledger.request("solidworks_create_basic_part", {"n": 1}, "write")
    existing = ledger.grants_dir / "existing.json"
    existing.write_text('{"owned":"keep"}', encoding="utf-8")
    before = existing.read_bytes()
    with pytest.raises(approval.ApprovalError, match="Onay yetki kayıtları kapasite sınırına ulaştı"):
        ledger.approve(pending["id"], expected_record=pending)
    assert existing.read_bytes() == before
    assert ledger.request_record(pending["id"]) == pending
    assert not (ledger.root / "secret.key").exists()
    assert list(ledger.grants_dir.glob("*.json")) == [existing]


def test_request_id_collision_does_not_overwrite_old_grant(tmp_path, monkeypatch):
    ledger = approval.ApprovalLedger(tmp_path)
    existing = ledger.grants_dir / "aaaaaaaa.json"
    existing.write_text('{"owned":"keep"}', encoding="utf-8")
    candidates = iter(["aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(approval.secrets, "token_hex", lambda _: next(candidates))
    request = ledger.request("solidworks_create_basic_part", {}, "write")
    assert request["id"] == "bbbbbbbb"
    assert existing.read_text(encoding="utf-8") == '{"owned":"keep"}'


def test_concurrent_processes_cannot_exceed_request_limit(tmp_path):
    module_dir = ROOT / "mcp-server"
    program = (
        "import sys; sys.path.insert(0,sys.argv[1]); import approval; "
        "approval.MAX_APPROVAL_REQUEST_RECORDS=2; "
        "ledger=approval.ApprovalLedger(sys.argv[2]); "
        "exec(\"try:\\n ledger.request('solidworks_create_basic_part', {'n':sys.argv[3]}, 'write')\\n print('created')\\n"
        "except approval.ApprovalError:\\n print('full')\")"
    )

    def run(index):
        return subprocess.run([sys.executable, "-c", program, str(module_dir), str(tmp_path), str(index)],
                              capture_output=True, text=True, check=True).stdout.strip()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(run, range(6)))
    assert outcomes.count("created") == 2
    assert outcomes.count("full") == 4
    assert len(list((tmp_path / "requests").glob("*.json"))) == 2
