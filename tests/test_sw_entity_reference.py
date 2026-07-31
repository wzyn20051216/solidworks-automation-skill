from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_entity_reference import geometry_signature, reference_from_metadata, resolve_semantic_reference  # noqa: E402


def test_geometry_signature_is_stable_for_rounded_values():
    left = geometry_signature({"center": [1.23456789, 2.0], "radius": 3.0})
    right = geometry_signature({"radius": 3, "center": [1.23456801, 2]})
    assert left == right


def test_semantic_reference_resolves_without_face_number():
    reference = reference_from_metadata("cylindrical_face", "MountingHole", {"center": [10, 20, 0], "radius": 0.002})
    candidates = [
        {"id": "Face7", "entity_type": "cylindrical_face", "feature_name": "MountingHole", "geometry_signature": reference.geometry_signature},
        {"id": "Face1", "entity_type": "planar_face", "feature_name": "Top"},
    ]
    result = resolve_semantic_reference(reference, candidates)
    assert result["status"] == "resolved"
    assert result["entity"]["id"] == "Face7"


def test_semantic_reference_reports_ambiguity():
    reference = reference_from_metadata("edge", "Seam", {"length": 12})
    candidates = [
        {"id": "Edge3", "entity_type": "edge", "feature_name": "Seam"},
        {"id": "Edge8", "entity_type": "edge", "feature_name": "Seam"},
    ]
    assert resolve_semantic_reference(reference, candidates)["status"] == "ambiguous"
