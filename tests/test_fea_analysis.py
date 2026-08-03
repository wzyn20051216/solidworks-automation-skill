"""开放 FEA Schema、门禁和 CalculiX 输入生成回归。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fea_analysis import build_calculix_input, discover_solver, parse_calculix_results, run_analysis, validate_analysis


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


def _nonlinear_request() -> dict:
    """@brief 返回含材料塑性和面接触的 FEA 1.1 请求。"""
    request = _request()
    request.update({
        "schemaVersion": "1.1",
        "analysisId": "contact_nonlinear",
        "analysisType": "static_nonlinear",
        "nonlinearControls": {
            "initialIncrement": 0.05,
            "timePeriod": 1.0,
            "minimumIncrement": 1e-5,
            "maximumIncrement": 0.1,
            "maximumIncrements": 200,
        },
        "surfaces": {
            "MasterFace": {"elementSet": "MasterElements", "face": "S1"},
            "SlaveFace": {"elementSet": "SlaveElements", "face": "S2"},
        },
        "contacts": [{
            "id": "interface", "masterSurface": "MasterFace", "slaveSurface": "SlaveFace",
            "frictionCoefficient": 0.2, "normalStiffnessMPaPerMm": 21000,
            "tangentialStickSlopeMPaPerMm": 10500,
        }],
    })
    request["mesh"]["elements"].append({"id": 2, "type": "C3D4", "nodeIds": [1, 2, 3, 4]})
    request["mesh"]["elementSets"].update({"MasterElements": [1], "SlaveElements": [2]})
    request["material"]["plasticCurve"] = [
        {"yieldStressMPa": 250, "plasticStrain": 0.0},
        {"yieldStressMPa": 300, "plasticStrain": 0.05},
    ]
    return request


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


def test_calculix_sets_wrap_after_sixteen_ids(tmp_path: Path) -> None:
    """@brief NSET/ELSET 每行不得超过 CalculiX 的 16 项限制。"""
    request = _request()
    request["mesh"]["nodes"].extend(
        {"id": node_id, "x": node_id, "y": 0, "z": 0}
        for node_id in range(5, 21)
    )
    request["mesh"]["nodeSets"]["ManyNodes"] = list(range(1, 21))
    result = build_calculix_input(request, tmp_path / "wrapped.inp")
    content = Path(result["artifacts"][0]["path"]).read_text(encoding="ascii").splitlines()
    start = content.index("*NSET,NSET=ManyNodes")
    member_lines = content[start + 1:start + 3]
    assert [len(line.split(",")) for line in member_lines] == [16, 4]


def test_nonlinear_contact_input_uses_only_whitelisted_keywords(tmp_path: Path) -> None:
    """@brief 几何非线性、塑性和面接触应生成固定 CalculiX 关键字。"""
    request = _nonlinear_request()
    assert validate_analysis(request)["analysisType"] == "static_nonlinear"
    report = build_calculix_input(request, tmp_path / "nonlinear.inp")
    content = Path(report["artifacts"][0]["path"]).read_text(encoding="ascii")
    assert "*STEP,NLGEOM,INC=200" in content
    assert "*PLASTIC\n250,0\n300,0.05" in content
    assert "*EL FILE\nS,E,PEEQ" in content
    assert "*SURFACE,NAME=MasterFace,TYPE=ELEMENT\nMasterElements,S1" in content
    assert "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=LINEAR\n21000" in content
    assert "*FRICTION\n0.2,10500" in content
    assert "*CONTACT PAIR,INTERACTION=CADSTUDIO_CONTACT_interface,TYPE=SURFACE TO SURFACE" in content
    assert content.index("*CONTACT PAIR") < content.index("*STEP,NLGEOM")
    assert report["requestEvidence"] == {
        "geometricNonlinearity": True,
        "plasticCurvePointCount": 2,
        "contactPairCount": 1,
    }


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload["nonlinearControls"].update({"initialIncrement": 2}), "minimum <= initial"),
        (lambda payload: payload["surfaces"]["MasterFace"].update({"face": "S5"}), "不适用于"),
        (lambda payload: payload["contacts"][0].update({"masterSurface": "Missing"}), "已定义 surface"),
        (lambda payload: payload["material"]["plasticCurve"][1].update({"plasticStrain": 0}), "严格递增"),
    ],
)
def test_nonlinear_extensions_reject_invalid_increment_surface_contact_and_curve(mutator, message: str) -> None:
    """@brief 非法增量、单元面、接触引用和塑性曲线必须在写文件前阻断。"""
    request = _nonlinear_request()
    mutator(request)
    with pytest.raises(ValueError, match=message):
        validate_analysis(request)


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
    monkeypatch.setattr("scripts.fea_analysis._windows_user_environment", lambda _name: None)
    monkeypatch.setattr("scripts.fea_analysis._standard_solver_candidates", lambda _name: [])
    preflight = discover_solver("calculix")
    output = tmp_path / "results"
    result = run_analysis(_request(), output)
    assert preflight["status"] == "blocked"
    assert preflight["error_code"] == "fea_solver_missing"
    assert result["status"] == "blocked"
    assert result["stage"] == "preflight"
    assert result["artifacts"] == []
    assert not output.exists()


def test_discover_solver_reads_windows_user_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """@brief 当前进程未刷新时仍应读取 Windows 用户级求解器环境变量。"""
    executable = tmp_path / "ccx.exe"
    executable.write_bytes(b"ccx")
    monkeypatch.delenv("CADSTUDIO_CALCULIX_EXE", raising=False)
    monkeypatch.setattr("scripts.fea_analysis.shutil.which", lambda _name: None)
    monkeypatch.setattr("scripts.fea_analysis._windows_user_environment", lambda _name: str(executable))
    monkeypatch.setattr("scripts.fea_analysis._standard_solver_candidates", lambda _name: [])
    report = discover_solver("calculix")
    assert report["status"] == "pass"
    assert report["executable"] == str(executable.resolve())
    assert report["source"].startswith("HKCU")


def test_parse_calculix_results_reports_displacement_stress_and_convergence(tmp_path: Path) -> None:
    """@brief FRD/STA 解析必须返回有限位移、等效应力和收敛增量。"""
    stem = "job"
    (tmp_path / f"{stem}.frd").write_text(
        "    1UVERSION           Version 2.23\n"
        " -4  DISP        4    1\n"
        " -1         1 0.0 0.0 -2.0E-04\n -3\n"
        " -4  STRESS      6    1\n"
        " -1         1 -2.0 -2.0 -6.0 0.0 0.0 0.0\n -3\n"
        " -4  PE          1    1\n"
        " -1         1 1.25E-03\n -3\n"
        " 9999\n",
        encoding="ascii",
    )
    (tmp_path / f"{stem}.sta").write_text("     1          1     1     1  1.0  1.0  1.0\n", encoding="ascii")
    (tmp_path / f"{stem}.cvg").write_text(
        "     1     1     1     1       28  0.0  0.0  0.0  0.0\n",
        encoding="ascii",
    )
    report = parse_calculix_results(tmp_path, stem)
    assert report["status"] == "pass"
    assert report["summary"]["solverVersion"] == "2.23"
    assert report["summary"]["maximumDisplacementMm"] == pytest.approx(2.0e-4)
    assert report["summary"]["maximumVonMisesStressMPa"] == pytest.approx(4.0)
    assert report["summary"]["convergedIncrementCount"] == 1
    assert report["summary"]["maximumContactElementCount"] == 28
    assert report["summary"]["maximumEquivalentPlasticStrain"] == pytest.approx(1.25e-3)


def test_parse_calculix_results_uses_latest_complete_result_blocks(tmp_path: Path) -> None:
    """@brief 多增量 FRD 只汇总最后一个完整结果块，不混入旧位移和应力。"""
    stem = "multi_step"
    (tmp_path / f"{stem}.frd").write_text(
        "    1UVERSION           Version 2.23\n"
        " -4  DISP        4    1\n -1         1 0.0 0.0 9.0\n -3\n"
        " -4  STRESS      6    1\n -1         1 90.0 0.0 0.0 0.0 0.0 0.0\n -3\n"
        " -4  DISP        4    1\n -1         1 0.0 0.0 0.2\n -3\n"
        " -4  STRESS      6    1\n -1         1 2.0 2.0 6.0 0.0 0.0 0.0\n -3\n"
        " 9999\n",
        encoding="ascii",
    )
    (tmp_path / f"{stem}.sta").write_text("     1          1     1     1  1.0  1.0  1.0\n", encoding="ascii")
    report = parse_calculix_results(tmp_path, stem)
    assert report["status"] == "pass"
    assert report["summary"]["displacementNodeCount"] == 1
    assert report["summary"]["maximumDisplacementMm"] == pytest.approx(0.2)
    assert report["summary"]["maximumVonMisesStressMPa"] == pytest.approx(4.0)


def test_parse_calculix_results_rejects_nonfinite_plastic_strain(tmp_path: Path) -> None:
    """@brief 非有限 PEEQ 必须使非线性结果失败，不能只检查位移和应力。"""
    stem = "nonfinite_peeq"
    (tmp_path / f"{stem}.frd").write_text(
        "    1UVERSION           Version 2.23\n"
        " -4  DISP        4    1\n -1         1 0.0 0.0 0.2\n -3\n"
        " -4  STRESS      6    1\n -1         1 2.0 2.0 6.0 0.0 0.0 0.0\n -3\n"
        " -4  PE          1    1\n -1         1 1.0E309\n -3\n"
        " 9999\n",
        encoding="ascii",
    )
    (tmp_path / f"{stem}.sta").write_text(
        "     1          1     1     1  1.0  1.0  1.0\n",
        encoding="ascii",
    )

    report = parse_calculix_results(tmp_path, stem)

    assert report["status"] == "failed"
    assert report["error_code"] == "fea_result_incomplete_or_nonfinite"
    assert report["summary"]["finiteValues"] is False


@pytest.mark.parametrize("defect", ["truncated", "mismatched_nodes", "duplicate_node", "failed_marker"])
def test_parse_calculix_results_rejects_incomplete_or_inconsistent_evidence(tmp_path: Path, defect: str) -> None:
    """@brief 截断、节点不一致、重复节点和失败关键词均不得误报收敛。"""
    stem = "bad_job"
    displacement_rows = " -1         1 0.0 0.0 -2.0E-04\n"
    stress_rows = " -1         1 -2.0 -2.0 -6.0 0.0 0.0 0.0\n"
    terminator = " 9999\n"
    if defect == "mismatched_nodes":
        stress_rows = " -1         2 -2.0 -2.0 -6.0 0.0 0.0 0.0\n"
    elif defect == "duplicate_node":
        displacement_rows += displacement_rows
    elif defect == "truncated":
        terminator = ""
    (tmp_path / f"{stem}.frd").write_text(
        "    1UVERSION           Version 2.23\n"
        " -4  DISP        4    1\n" + displacement_rows + " -3\n"
        " -4  STRESS      6    1\n" + stress_rows + " -3\n" + terminator,
        encoding="ascii",
    )
    (tmp_path / f"{stem}.sta").write_text("     1          1     1     1  1.0  1.0  1.0\n" + ("ERROR: solver failed\n" if defect == "failed_marker" else ""), encoding="ascii")
    report = parse_calculix_results(tmp_path, stem)
    assert report["status"] == "failed"
    assert report["error_code"] == "fea_result_incomplete_or_nonfinite"


def test_run_non_static_analysis_blocks_before_creating_output(tmp_path: Path) -> None:
    """@brief 尚未实现的分析类型不能留下任务目录。"""
    request = _request()
    request["analysisType"] = "modal"
    result = run_analysis(request, tmp_path / "results")
    assert result["status"] == "blocked"
    assert result["error_code"] == "fea_calculix_analysis_unsupported"
    assert not (tmp_path / "results").exists()


def test_fea_json_schema_is_valid_and_accepts_golden_request() -> None:
    """@brief 公共 JSON Schema 本身及 1.0/1.1 黄金请求均应通过 Draft 2020-12。"""
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[1] / "apps" / "desktop" / "cad_workbench" / "schemas" / "fea_analysis.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_request(), schema)
    jsonschema.validate(_nonlinear_request(), schema)
