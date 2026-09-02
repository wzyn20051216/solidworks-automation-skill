"""SolidWorks 配置族 MCP 工具注册和输入契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "mcp-server"
if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

import server  # noqa: E402
from scripts.validate_mcp import REQUIRED_TOOLS  # noqa: E402


CONFIGURATION_TOOLS = {
    "solidworks_inspect_configurations",
    "solidworks_create_configuration",
    "solidworks_activate_configuration",
}


def test_configuration_mcp_tools_are_registered() -> None:
    """@brief 三个配置族入口必须实际注册到 MCP。"""
    assert CONFIGURATION_TOOLS <= set(server.mcp._tool_manager._tools)


def test_release_mcp_gate_requires_configuration_tools() -> None:
    """@brief 发布门禁必须覆盖配置族入口。"""
    assert CONFIGURATION_TOOLS <= REQUIRED_TOOLS


def test_configuration_input_rejects_invalid_duplicate_policy() -> None:
    """@brief 配置创建只允许幂等复用或严格报错。"""
    with pytest.raises(ValueError):
        server.SolidWorksConfigurationCreateInput(
            configuration_name="加工",
            if_exists="overwrite",
        )


def test_configuration_input_rejects_negative_option_mask() -> None:
    """@brief 枚举位掩码不能使用负数。"""
    with pytest.raises(ValueError):
        server.SolidWorksConfigurationCreateInput(
            configuration_name="加工",
            options=-1,
        )
