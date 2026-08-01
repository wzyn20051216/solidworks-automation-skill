from apps.desktop.cad_workbench.queue_worker import _domain_evidence_status


def test_domain_evidence_blocks_environment_failures():
    assert _domain_evidence_status({"drawingEvidence": {"status": "blocked"}})[0] == "blocked"


def test_domain_evidence_fails_invalid_artifacts():
    status, message = _domain_evidence_status({"bomEvidence": {"status": "fail"}})
    assert status == "failed"
    assert "复核失败" in message


def test_domain_evidence_requires_manual_review():
    status, _ = _domain_evidence_status({"drawingEvidence": {"status": "pass", "manual_review_required": True}})
    assert status == "review_required"
