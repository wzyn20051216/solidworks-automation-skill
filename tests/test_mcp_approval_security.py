"""审批账本的并发、范围及完整展示回归测试。"""
import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
from approval import ApprovalError, ApprovalLedger, MAX_APPROVAL_ARGUMENT_BYTES


def test_one_time_grant_is_consumed_once_across_processes(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    args = {"params": {"name": "sample"}}
    request = ledger.request("solidworks_create_basic_part", args, "write")
    ledger.approve(request["id"])
    module_dir = Path(__file__).resolve().parents[1] / "mcp-server"
    program = (
        "import sys,json; sys.path.insert(0,sys.argv[1]); "
        "from approval import ApprovalLedger; "
        "print(bool(ApprovalLedger(sys.argv[2]).consume("
        "'solidworks_create_basic_part', {'params': {'name': 'sample'}})))"
    )
    def run():
        return subprocess.run([sys.executable, "-c", program, str(module_dir), str(tmp_path)],
                              capture_output=True, text=True, check=True).stdout.strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: run(), range(8)))
    assert outcomes.count("True") == 1
    assert outcomes.count("False") == 7


def test_scope_does_not_allow_parent_traversal(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    ledger = ApprovalLedger(tmp_path / "ledger")
    scope = {"tools": ["solidworks_save_document"], "paths": [str(allowed)]}
    assert ledger._scope_covers(scope, "solidworks_save_document", [str(allowed / "ok.sldprt")])
    assert not ledger._scope_covers(scope, "solidworks_save_document", [str(allowed / ".." / "outside.sldprt")])


def test_scope_does_not_follow_symlink_outside(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    try:
        (allowed / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("环境不允许创建目录符号链接")
    ledger = ApprovalLedger(tmp_path / "ledger")
    scope = {"tools": ["solidworks_save_document"], "paths": [str(allowed)]}
    assert not ledger._scope_covers(scope, "solidworks_save_document", [str(allowed / "link" / "outside.sldprt")])


def test_approval_displays_full_arguments_or_refuses_oversized(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    args = {"long": "x" * 2000, "later": "important"}
    request = ledger.request("solidworks_save_document", args, "write")
    assert 'important' in request["summary"]
    assert len(request["summary"]) > 1200
    with pytest.raises(ApprovalError):
        ledger.request("solidworks_save_document", {"long": "x" * MAX_APPROVAL_ARGUMENT_BYTES}, "write")
    assert len(ledger.pending()) == 1


def test_scope_authorization_is_disabled(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    with pytest.raises(ApprovalError, match="Kapsam yetkilendirmesi devre dışı"):
        ledger.grant_scope(["solidworks_save_document"], [os.path.join("..", "outside")])


def test_existing_scope_grants_are_not_consumed(tmp_path):
    import time
    ledger = ApprovalLedger(tmp_path)
    ledger._issue({"kind": "scope", "id": "11223344", "tool": "*", "tools": ["*"],
                   "paths": [], "expires_at": time.time() + 1000, "max_uses": None, "used": 0})
    assert ledger.consume("solidworks_save_document", {"path": "unsafe"}) is None


def test_distinct_subjects_cannot_share_or_consume_grants(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    args = {"params": {"path": "part.sldprt"}}
    first = ledger.request("solidworks_save_document", args, "write", subject="session-a")
    same = ledger.request("solidworks_save_document", args, "write", subject="session-a")
    second = ledger.request("solidworks_save_document", args, "write", subject="session-b")
    assert first["id"] == same["id"]
    assert first["id"] != second["id"]
    ledger.approve(first["id"], expected_record=first)
    assert ledger.consume("solidworks_save_document", args, subject="session-b") is None
    assert ledger.consume("solidworks_save_document", args, subject="session-a") is not None


def test_approval_rejects_changed_request_after_display(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    original = ledger.request("solidworks_save_document", {"path": "safe"}, "write")
    changed = dict(original, digest="0" * 64)
    ledger._write(ledger.requests_dir / f"{original['id']}.json", changed)
    with pytest.raises(ApprovalError, match="gösterimden sonra değişti"):
        ledger.approve(original["id"], expected_record=original)
    assert not list(ledger.grants_dir.glob("*.json"))


def test_approval_rejects_digest_not_matching_displayed_arguments(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    request = ledger.request("solidworks_save_document", {"path": "safe"}, "write")
    forged = dict(request, digest="0" * 64)
    ledger._write(ledger.requests_dir / f"{request['id']}.json", forged)
    with pytest.raises(ApprovalError, match="parametre özeti ile yürütme içeriği uyuşmuyor"):
        ledger.approve(request["id"], expected_record=forged)
    assert not list(ledger.grants_dir.glob("*.json"))


def test_approval_rejects_forged_or_stale_effect(tmp_path):
    ledger = ApprovalLedger(tmp_path)
    request = ledger.request("solidworks_save_document", {"path": "safe"}, "write")
    forged = dict(request, effect="read")
    ledger._write(ledger.requests_dir / f"{request['id']}.json", forged)
    with pytest.raises(ApprovalError, match="yan etki düzeyi geçerli politikayla uyuşmuyor"):
        ledger.approve(request["id"], expected_record=forged)
    assert not list(ledger.grants_dir.glob("*.json"))
