"""工程图 MCP 工具注册和输入契约测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "mcp-server"
if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

import server  # noqa: E402
from scripts.drawing_spec import validate_drawing_spec  # noqa: E402


def test_drawing_mcp_tools_are_registered():
    tools = server.mcp._tool_manager._tools

    assert {"solidworks_generate_drawing", "solidworks_review_drawing", "solidworks_inspect_drawing"} <= set(tools)


def test_generate_drawing_input_rejects_non_drawing_spec(tmp_path: Path):
    source = tmp_path / "spec.txt"
    source.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="DrawingSpec"):
        server.SolidWorksGenerateDrawingInput(spec_path=str(source), output_dir=str(tmp_path / "out"))


def test_drawing_spec_validation_can_be_used_without_loading_com(tmp_path: Path):
    source = tmp_path / "drawing.json"
    source.write_text(json.dumps({"schemaVersion": "1.0"}), encoding="utf-8")

    result = validate_drawing_spec(str(source))

    assert result["status"] == "blocked"
