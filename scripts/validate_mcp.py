"""
验证 SolidWorks MCP Server 的协议层可用性。

该脚本不调用 SolidWorks COM 工具，只启动本地 stdio MCP server 并检查
`tools/list` 是否包含关键工具，适合在提交前或 CI 中发现 schema/注册错误。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp-server" / "server.py"

REQUIRED_TOOLS = {
    "solidworks_health_check",
    "solidworks_connect",
    "solidworks_new_document",
    "solidworks_create_basic_part",
    "solidworks_open_document",
    "solidworks_add_component",
    "solidworks_set_component_fixed",
    "solidworks_save_document",
    "solidworks_close_documents",
    "solidworks_add_coincident_mate",
    "solidworks_add_distance_mate",
    "solidworks_add_concentric_mate",
    "solidworks_set_appearance",
    "solidworks_export_active",
    "solidworks_review_active",
    "solidworks_add_rotary_motor",
}


def _configure_stdio_utf8() -> None:
    """在 Windows 旧代码页下尽量使用 UTF-8 输出中文提示。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


async def _list_tools() -> set[str]:
    """启动 MCP server 并读取工具列表。"""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(ROOT),
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}


async def _main() -> int:
    """执行 MCP 工具清单检查。"""
    if not SERVER_PATH.exists():
        raise FileNotFoundError(f"找不到 MCP Server: {SERVER_PATH}")
    tool_names = await _list_tools()
    missing = sorted(REQUIRED_TOOLS - tool_names)
    if missing:
        raise AssertionError("MCP 缺少工具: " + ", ".join(missing))
    print(f"MCP 验证通过: {len(tool_names)} 个工具可见。")
    return 0


if __name__ == "__main__":
    _configure_stdio_utf8()
    try:
        raise SystemExit(asyncio.run(_main()))
    except Exception as exc:
        print(f"MCP 验证失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
