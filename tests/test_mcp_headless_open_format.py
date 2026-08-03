"""MCP 无头开放格式工具回归。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf
import pytest

from apps.desktop.cad_workbench.cad_core_contracts import NeutralCadDocument, NeutralFeature, write_json_contract

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "mcp-server"
if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

import server  # noqa: E402


def test_mcp_headless_open_format_tool_writes_without_com(tmp_path: Path):
    """@brief 验证 MCP 开放格式工具不加载 SolidWorks COM 也能产出证据。"""
    input_path = write_json_contract(
        tmp_path / "mcp_plate.cadstudio.json",
        NeutralCadDocument(
            documentId="mcp_plate",
            features=[NeutralFeature(id="base", type="box", parameters={"length": 80, "width": 50, "height": 6})],
        ),
    )

    params = server.CadStudioOpenFormatInput(
        input_path=str(input_path),
        output_dir=str(tmp_path / "out"),
        formats=["cadstudio", "dxf", "png"],
    )
    payload = json.loads(server.cadstudio_write_open_format(params))

    assert payload["backend"] == "headless_open_format"
    assert payload["status"] == "pass"
    assert server._automation_loaded is False
    assert {item["kind"] for item in payload["artifacts"]} >= {"cadstudio", "dxf", "png", "preview_scene", "preview_manifest"}


def test_mcp_builds_safe_dxf_preview_scene_and_refuses_overwrite(tmp_path: Path):
    """@brief 验证 MCP 只读转换和不覆盖门禁。"""
    source = tmp_path / "drawing.dxf"
    document = ezdxf.new("R2018")
    document.modelspace().add_line((0, 0), (50, 20), dxfattribs={"layer": "OUTLINE"})
    document.saveas(source)
    output = tmp_path / "drawing.scene.json"
    params = server.CadStudioDxfPreviewInput(source_path=str(source), output_path=str(output))

    payload = json.loads(server.cadstudio_build_dxf_preview_scene(params))

    assert payload["status"] == "pass"
    assert payload["backend"] == "ezdxf-preview-scene"
    assert payload["entityCount"] == 1
    assert output.is_file()
    with pytest.raises(ValueError, match="overwrite"):
        server.CadStudioDxfPreviewInput(source_path=str(source), output_path=str(output))


def _fea_request() -> dict:
    """@brief 返回 MCP prepare_fea 使用的最小静力请求。"""
    return {
        "schemaVersion": "1.0",
        "analysisId": "mcp_static",
        "analysisType": "static_linear",
        "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {"name": "Al6061", "elasticModulusMPa": 68900, "poissonRatio": 0.33, "densityKgM3": 2700},
        "mesh": {
            "nodes": [
                {"id": 1, "x": 0, "y": 0, "z": 0},
                {"id": 2, "x": 10, "y": 0, "z": 0},
                {"id": 3, "x": 0, "y": 10, "z": 0},
                {"id": 4, "x": 0, "y": 0, "z": 10},
            ],
            "elements": [{"id": 1, "type": "C3D4", "nodeIds": [1, 2, 3, 4]}],
            "nodeSets": {"FixedNodes": [1, 2, 3], "LoadNode": [4]},
            "elementSets": {"AllElements": [1]},
        },
        "constraints": [{"id": "fixed_base", "type": "fixed", "nodeSet": "FixedNodes"}],
        "loads": [{"id": "tip_force", "type": "force", "nodeSet": "LoadNode", "dof": 3, "value": -100}],
    }


def test_mcp_prepare_fea_writes_without_loading_solidworks_automation(tmp_path: Path):
    """@brief FEA MCP 工具只生成白名单输入，不加载 SolidWorks COM 自动化模块。"""
    source = tmp_path / "fea.json"
    source.write_text(json.dumps(_fea_request()), encoding="utf-8")
    params = server.CadStudioFeaPrepareInput(input_path=str(source), output_dir=str(tmp_path / "fea-out"))

    payload = json.loads(server.cadstudio_prepare_fea(params))

    assert payload["status"] == "pass"
    assert Path(payload["artifacts"][0]["path"]).is_file()
    assert server._automation_loaded is False


def test_mcp_run_fea_uses_structured_runner_without_loading_solidworks(tmp_path: Path, monkeypatch):
    """@brief FEA 执行工具只调用结构化求解器封装，不加载 SolidWorks 自动化。"""
    source = tmp_path / "fea.json"
    source.write_text(json.dumps(_fea_request()), encoding="utf-8")
    expected = {"status": "review_required", "stage": "review", "artifacts": []}
    monkeypatch.setattr("scripts.fea_analysis.run_analysis", lambda *_args, **_kwargs: expected)
    params = server.CadStudioFeaRunInput(input_path=str(source), output_dir=str(tmp_path / "fea-run"), timeout_seconds=30)

    payload = json.loads(server.cadstudio_run_fea(params))

    assert payload == expected
    assert server._automation_loaded is False


def test_mcp_run_fea_convergence_uses_whitelisted_sequence_runner(tmp_path: Path, monkeypatch):
    """@brief 收敛工具只调用结构化序列执行器，不暴露任意求解器命令。"""
    source = tmp_path / "convergence.json"
    source.write_text("{}", encoding="utf-8")
    expected = {"status": "review_required", "converged": False, "artifacts": []}
    monkeypatch.setattr("scripts.fea_convergence.run_convergence_study", lambda *_args, **_kwargs: expected)
    params = server.CadStudioFeaConvergenceInput(
        input_path=str(source), output_dir=str(tmp_path / "convergence-out"), timeout_seconds_per_case=30
    )

    payload = json.loads(server.cadstudio_run_fea_convergence(params))

    assert payload == expected
    assert server._automation_loaded is False


def test_mcp_create_ocp_loft_uses_restricted_backend(tmp_path: Path, monkeypatch):
    """@brief OCP Loft MCP 只调用结构化几何封装，不加载 SolidWorks。"""
    source = tmp_path / "loft.json"
    source.write_text("{}", encoding="utf-8")
    expected = {"status": "review_required", "geometryProduced": True, "artifacts": []}
    monkeypatch.setattr("scripts.advanced_geometry_ocp.execute_ocp_loft", lambda *_args: expected)
    params = server.CadStudioOcpLoftInput(input_path=str(source), output_dir=str(tmp_path / "loft-out"))
    payload = json.loads(server.cadstudio_create_ocp_loft(params))
    assert payload == expected
    assert server._automation_loaded is False


def test_mcp_create_ocp_surface_uses_restricted_backend(tmp_path: Path, monkeypatch):
    """@brief 高级曲面 MCP 工具只调用结构化 OCP 后端。"""
    source = tmp_path / "surface.json"
    source.write_text("{}", encoding="utf-8")
    expected = {"status": "review_required", "geometryProduced": True, "artifacts": []}
    monkeypatch.setattr("scripts.advanced_surface_ocp.execute_advanced_surface", lambda *_args: expected)
    params = server.CadStudioOcpSurfaceInput(input_path=str(source), output_dir=str(tmp_path / "surface-out"))
    payload = json.loads(server.cadstudio_create_ocp_surface(params))
    assert payload == expected
    assert server._automation_loaded is False


def test_mcp_routing_review_reports_neutral_evidence(tmp_path: Path):
    """@brief Routing MCP 工具必须输出中性证据和报告文件。"""
    source = tmp_path / "route.json"
    source.write_text(
        json.dumps(
            {
                "routeType": "cable",
                "minimumBendRadius": 20,
                "maximumSupportSpacing": 80,
                "endpoints": [{"id": "A", "position": [0, 0, 0]}, {"id": "B", "position": [30, 40, 0]}],
                "segments": [{"id": "S1", "start": "A", "end": "B", "bendRadius": 25, "diameter": 8}],
            }
        ),
        encoding="utf-8",
    )
    params = server.CadStudioRoutingReviewInput(input_path=str(source), output_path=str(tmp_path / "route_report.json"))

    payload = json.loads(server.cadstudio_check_routing(params))

    assert payload["status"] == "review_required", payload
    assert payload["totalLength"] == 50
    assert Path(payload["reportPath"]).is_file()
    assert server._automation_loaded is False
