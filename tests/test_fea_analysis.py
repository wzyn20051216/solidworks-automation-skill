"""开放 FEA Schema、门禁和 CalculiX 输入生成回归。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fea_analysis import build_calculix_input, discover_solver, run_analysis, validate_analysis


def _request() -> dict:
    """@brief 返回单四面体静力黄金输入。"""
    return {
        "schemaVersion": "1.0",
        "analysisId": "bracket_static",
        "analysisType": "static_linear",
        "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {"name": "Al6061", "elasticModulusMPa": 68900, "poissonRatio": 0.33, "densityKgM3": 2700},
        "mesh": {
            "nodes": [
                {"id": 1, "x": 0, "y": 0, "z": 0}, {"id": 2, "x": 10, "y": 0, "z": 0},
                {"id": 3, "x": 0, "y": 10, "z": 0}, {"id": 4, "x": 0, "y": 0, "z": 10},
            ],
            "elements": [{"id": 1, "type": "C3D4", "nodeIds": [1, 2, 3, 4]}],
            "nodeSets": {"FixedNodes": [1, 2, 3], "LoadNode": [4]},
            "elementSets": {"AllElements": [1]},
        },
        "constraints": [{"id": "fixed_base", "type": "fixed", "nodeSet": "FixedNodes"}],
        "loads": [{"id": "tip_force", "type": "force", "nodeSet": "LoadNode", "dof": 3, "value": -100}],
    }


def test_validate_analysis_accepts_consistent_mesh_and_references() -> None:
    """@brief 合法材料、网格、载荷和约束应通过。"""
    validated = validate_analysis(_request())
    assert validated["analysisId"] == "bracket_static"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update({"analysisId": "bad\n*INCLUDE"}), "analysisId"),
        (lambda payload: payload["mesh"]["elements"][0].update({"nodeIds": [1, 2, 3, 99]}), "缺失"),
        (lambda payload: payload["material"].update({"poissonRatio": 0.5}), "poissonRatio"),
        (lambda payload: payload["loads"][0].update({"nodeSet": "Missing"}), "nodeSet"),
    ],
)
def test_validate_analysis_rejects_injection_and_invalid_engineering_references(mutator, message: str) -> None:
    """@brief 注入、悬空拓扑引用和无效材料均必须阻断。"""
    payload = _request()
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        validate_analysis(payload)


def test_calculix_input_is_whitelisted_and_never_overwrites(tmp_path: Path) -> None:
    """@brief 输入文件只含固定模板，重复生成使用版本化文件。"""
    output = tmp_path / "job.inp"
    first = build_calculix_input(_request(), output)
    second = build_calculix_input(_request(), output)
    first_path = Path(first["artifacts"][0]["path"])
    second_path = Path(second["artifacts"][0]["path"])
    content = first_path.read_text(encoding="ascii")
    assert first["status"] == "pass"
    assert first_path.name == "job.inp"
    assert second_path.name == "job_v2.inp"
    assert "*NODE" in content and "*ELEMENT,TYPE=C3D4" in content
    assert "*BOUNDARY" in content and "*CLOAD" in content
    assert first["artifacts"][0]["sha256"]


def test_pressure_requires_explicit_element_face_and_gravity_uses_defined_all_set(tmp_path: Path) -> None:
    """@brief 实体压力必须指定面，重力必须引用生成器定义的全集。"""
    pressure = _request()
    pressure["loads"] = [{"id": "pressure_load", "type": "pressure", "elementSet": "AllElements", "magnitude": 2.5}]
    with pytest.raises(ValueError, match="P1-P6"):
        validate_analysis(pressure)
    pressure["loads"][0]["face"] = "P1"
    assert validate_analysis(pressure)

    gravity = _request()
    gravity["loads"] = [{"id": "gravity_load", "type": "gravity", "magnitude": 9810, "direction": [0, 0, -1]}]
    result = build_calculix_input(gravity, tmp_path / "gravity.inp")
    content = Path(result["artifacts"][0]["path"]).read_text(encoding="ascii")
    assert "*ELSET,ELSET=CADSTUDIO_ALL_ELEMENTS" in content
    assert "CADSTUDIO_ALL_ELEMENTS,GRAV,9810" in content


def test_tetrahedral_pressure_rejects_nonexistent_face() -> None:
    """@brief C3D4 四面体只有 P1-P4，不能生成无效 P5/P6 压力载荷。"""
    request = _request()
    request["loads"] = [{"id": "Pressure1", "type": "pressure", "elementSet": "AllElements", "face": "P5", "magnitude": 2.5}]
    with pytest.raises(ValueError, match="不适用于"):
        validate_analysis(request)


def test_missing_solver_is_blocked_without_fake_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """@brief 求解器缺失时不得创建求解目录或结果。"""
    monkeypatch.delenv("CADSTUDIO_CALCULIX_EXE", raising=False)
    monkeypatch.delenv("CADSTUDIO_ELMER_EXE", raising=False)
    monkeypatch.setattr("scripts.fea_analysis.shutil.which", lambda _name: None)
    preflight = discover_solver("calculix")
    output = tmp_path / "results"
    result = run_analysis(_request(), output)
    assert preflight["status"] == "blocked"
    assert preflight["error_code"] == "fea_solver_missing"
    assert result["status"] == "blocked"
    assert result["stage"] == "preflight"
    assert result["artifacts"] == []
    assert not output.exists()


def test_fea_json_schema_is_valid_and_accepts_golden_request() -> None:
    """@brief 公共 JSON Schema 本身及黄金请求均应通过 Draft 2020-12。"""
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[1] / "apps" / "desktop" / "cad_workbench" / "schemas" / "fea_analysis.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_request(), schema)
