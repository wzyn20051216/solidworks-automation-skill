"""多语言后端路由 MCP 工具测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "mcp-server"
if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

import server  # noqa: E402
from scripts.validate_mcp import REQUIRED_TOOLS  # noqa: E402


def test_backend_router_mcp_tool_is_registered_and_release_gated() -> None:
    """@brief 路由工具必须出现在服务和发布门禁中。"""
    assert "cadstudio_resolve_backend" in server.mcp._tool_manager._tools
    assert "cadstudio_resolve_backend" in REQUIRED_TOOLS


def test_backend_router_mcp_selects_native_cpp_for_exact_pointer_api() -> None:
    """@brief MCP 调用也必须保持原始接口语义门禁。"""
    raw = server.cadstudio_resolve_backend(
        server.CadStudioBackendRouteInput(
            operation_id="solidworks_pointer_array_api",
            available_backends=["solidworks-com-pywin32", "solidworks-native-cpp"],
            exact_api=True,
        )
    )
    result = json.loads(raw)

    assert result["status"] == "ready"
    assert result["backend"] == "solidworks-native-cpp"
    assert result["semantics"] == "exact_native"
