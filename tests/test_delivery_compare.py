"""交付版本比较与重新生成请求测试。"""
from __future__ import annotations

from pathlib import Path

from scripts.delivery_compare import build_regeneration_request, compare_snapshots, snapshot_files


def test_compare_snapshots_detects_added_removed_changed_and_unchanged(tmp_path):
    unchanged = tmp_path / "same.step"
    changed = tmp_path / "changed.stl"
    removed = tmp_path / "removed.dwg"
    added = tmp_path / "added.dxf"
    unchanged.write_bytes(b"same")
    changed.write_bytes(b"new")
    removed.write_bytes(b"old")
    before = snapshot_files([unchanged, changed, removed])
    changed.write_bytes(b"changed")
    added.write_bytes(b"added")
    after = snapshot_files([unchanged, changed, added])

    comparison = compare_snapshots(before, after)

    assert comparison["counts"] == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}


def test_regeneration_request_preserves_previous_artifacts_and_review_gate():
    request = build_regeneration_request(
        project_id="p-1",
        source_job_id="job-1",
        failed_stage="drawing-bom",
        capabilities=["drawings_and_bom", "export_delivery", "drawings_and_bom"],
        assumptions=["单位 mm"],
        changed_inputs=["plate.sldprt"],
    )

    assert request["capabilitySnapshot"] == ["drawings_and_bom", "export_delivery"]
    assert request["policy"]["preservePreviousArtifacts"] is True
    assert request["policy"]["overwrite"] is False
    assert request["policy"]["scope"] == "failed_stage_and_downstream"
