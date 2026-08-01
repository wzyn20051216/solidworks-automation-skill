"""双入口、双后端公共 CAD Core 契约测试。"""
from pathlib import Path

from apps.desktop.cad_workbench.cad_core_contracts import (
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NeutralCadDocument,
    NeutralFeature,
    enrich_job_with_core_contracts,
    preview_manifest_for_artifact,
    read_json_contract,
    write_json_contract,
)


def test_neutral_cad_document_roundtrip(tmp_path: Path):
    document = NeutralCadDocument(
        documentId="bracket-001",
        title="无头支架",
        features=[NeutralFeature(id="base", type="box", parameters={"length": 80, "width": 40, "height": 8})],
    )
    path = write_json_contract(tmp_path / "bracket.cadstudio.json", document)

    payload = read_json_contract(path)

    assert payload["schemaVersion"] == "1.0"
    assert payload["features"][0]["type"] == "box"


def test_preview_manifest_binds_source_preview_and_hash(tmp_path: Path):
    preview = tmp_path / "part.glb"
    preview.write_bytes(b"glb-demo")

    manifest = preview_manifest_for_artifact("part.step", preview, fallback_image="part.png", evidence_refs=["node:base"])
    path = write_json_contract(tmp_path / "preview.json", manifest)
    payload = read_json_contract(path)

    assert payload["previewVersion"] == "1.0"
    assert payload["sourceArtifact"] == "part.step"
    assert payload["sha256"]
    assert payload["evidenceRefs"] == ["node:base"]


def test_evidence_graph_uses_stable_from_key(tmp_path: Path):
    graph = EvidenceGraph(
        nodes=[EvidenceNode(id="req:hole", type="requirement"), EvidenceNode(id="feature:hole", type="feature")],
        edges=[EvidenceEdge(from_="req:hole", to="feature:hole", relation="implemented_by")],
    )
    path = write_json_contract(tmp_path / "evidence.json", graph)
    payload = read_json_contract(path)

    assert payload["edges"][0]["from"] == "req:hole"
    assert payload["edges"][0]["relation"] == "implemented_by"


def test_job_contract_adds_backend_and_preview_fields():
    job = {"schemaVersion": "2.0", "requiredArtifacts": ["model", "preview"]}

    enriched = enrich_job_with_core_contracts(job, preferred_backend="headless", preview_manifest="preview.json")

    assert enriched["preferredBackend"] == "headless"
    assert enriched["requiredOutputs"] == ["model", "preview"]
    assert enriched["fallbackPolicy"] == "allow_open_formats"
    assert enriched["previewManifest"] == "preview.json"
