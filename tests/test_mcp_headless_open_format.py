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
