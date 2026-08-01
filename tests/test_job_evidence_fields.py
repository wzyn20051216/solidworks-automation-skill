import json
from pathlib import Path

from apps.desktop.cad_workbench.queue_worker import process_job, read_job, write_job


def test_worker_promotes_drawing_and_bom_evidence_to_job(tmp_path: Path):
    path = tmp_path / "job.json"
    job = {
        "schemaVersion": "2.0", "id": "evidence-job", "runId": "run-1", "kind": "create_shell",
        "title": "工程图", "detail": "test", "status": "queued", "progress": 0,
        "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
        "projectId": "p", "conversationId": "c", "inputs": [], "stage": "intake",
        "capabilitySnapshot": {}, "assumptions": [], "requiredArtifacts": [], "verificationEvidence": [],
    }
    write_job(path, job)

    def handler(_job):
        return {
            "message": "等待复核",
            "outputs": [],
            "drawingEvidence": {"status": "pass", "view_count": 3},
            "bomEvidence": {"status": "warning", "bom_row_count": 1},
            "reviewFindings": [{"id": "drawing-template", "status": "warning"}],
            "artifactRelations": [{"from": "model.sldasm", "to": "drawing.slddrw"}],
        }

    result = process_job(path, handlers={"create_shell": handler})
    saved = read_job(path)
    assert result is not None
    assert saved["drawingEvidence"]["view_count"] == 3
    assert saved["bomEvidence"]["status"] == "warning"
    assert saved["reviewFindings"][0]["id"] == "drawing-template"
    assert saved["artifactRelations"][0]["to"] == "drawing.slddrw"
