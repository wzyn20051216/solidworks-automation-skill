"""OCCT/OCP 无头几何服务回归。"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("OCP")
pytest.importorskip("trimesh")

from apps.desktop.cad_workbench.cad_core_contracts import NeutralCadDocument, NeutralFeature, write_json_contract
from scripts.headless_occt_service import export_occt


def _plate_document() -> NeutralCadDocument:
    return NeutralCadDocument(
        documentId="occt_plate",
        title="OCCT 带孔安装板",
        features=[
            NeutralFeature(id="base", type="box", parameters={"length": 120, "width": 70, "height": 8}),
            NeutralFeature(
                id="hole-a",
                type="hole",
                operation="subtract",
                parameters={"x": -30, "y": 0, "diameter": 12},
            ),
            NeutralFeature(
                id="hole-b",
                type="hole",
                operation="subtract",
                parameters={"x": 30, "y": 0, "diameter": 12},
            ),
        ],
    )


def test_occt_service_writes_real_brep_and_mesh_formats(tmp_path: Path):
    """@brief 验证带孔实体真实写出并回读几何证据。"""
    input_path = write_json_contract(tmp_path / "occt_plate.cadstudio.json", _plate_document())

    result = export_occt(input_path, tmp_path / "out", ["step", "iges", "brep", "stl", "obj", "glb"])

    assert result["status"] == "pass"
    artifacts = {item["kind"]: Path(item["path"]) for item in result["artifacts"]}
    assert set(artifacts) == {"step", "iges", "brep", "stl", "obj", "glb"}
    assert all(path.is_file() and path.stat().st_size > 100 for path in artifacts.values())
    assert artifacts["glb"].read_bytes()[:4] == b"glTF"
    evidence = result["geometryEvidence"]
    expected_volume = 120 * 70 * 8 - 2 * math.pi * 6 * 6 * 8
    assert evidence["valid"] is True
    assert evidence["topology"]["solids"] == 1
    assert evidence["topology"]["faces"] >= 8
    assert evidence["volume"] == pytest.approx(expected_volume, rel=1e-6)


def test_occt_service_versions_outputs_instead_of_overwriting(tmp_path: Path):
    """@brief 验证重复生成默认保留旧产物。"""
    input_path = write_json_contract(tmp_path / "occt_plate.cadstudio.json", _plate_document())
    first = export_occt(input_path, tmp_path / "out", ["step", "glb"])
    first_paths = {item["kind"]: Path(item["path"]) for item in first["artifacts"]}
    first_bytes = {kind: path.read_bytes() for kind, path in first_paths.items()}

    second = export_occt(input_path, tmp_path / "out", ["step", "glb"])
    second_paths = {item["kind"]: Path(item["path"]) for item in second["artifacts"]}

    assert first_paths["step"] != second_paths["step"]
    assert first_paths["glb"] != second_paths["glb"]
    assert first_paths["step"].read_bytes() == first_bytes["step"]
    assert first_paths["glb"].read_bytes() == first_bytes["glb"]
    assert "_v2" in second_paths["step"].stem
    assert "_v2" in second_paths["glb"].stem
