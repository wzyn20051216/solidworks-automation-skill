"""
验证 SolidWorks MCP Server 的协议层可用性。

该脚本不调用 SolidWorks COM 工具，只启动本地 stdio MCP server 检查两种表面：
- `full`：原生命名工具全部可见（兼容模式）；
- `search`：默认只暴露三个发现入口，且每个必需工具都能按名称检索并读到 Schema。

适合在提交前或 CI 中发现 schema/注册错误。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp-server" / "server.py"
DISCOVERY_TOOLS = {"sw_search_tools", "sw_describe_tool", "sw_call_tool"}

REQUIRED_TOOLS = {
    "solidworks_inspect_native_geometry",
    "solidworks_build_round_sweeps",
    "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform",
    "solidworks_exclude_reviewed_bodies",
    "cadstudio_read_artifact",
    "cadstudio_resolve_backend",
    "cadstudio_write_open_format",
    "cadstudio_build_dxf_preview_scene",
    "cadstudio_check_dfm",
    "cadstudio_check_drc",
    "cadstudio_list_drc_rules",
    "cadstudio_check_routing",
    "cadstudio_routing_preflight",
    "solidworks_addin_host_status",
    "cadstudio_fea_preflight",
    "cadstudio_prepare_fea",
    "cadstudio_run_fea",
    "cadstudio_run_fea_convergence",
    "cadstudio_review_advanced_geometry",
    "cadstudio_create_ocp_loft",
    "cadstudio_create_ocp_surface",
    "solidworks_health_check",
    "solidworks_lookup_api",
    "solidworks_recover",
    "solidworks_connect",
    "solidworks_new_document",
    "solidworks_create_basic_part",
    "solidworks_open_document",
    # 建模工具：这些是机械工程师实际画零件用的入口，回归保护必须覆盖。
    "solidworks_sketch_and_extrude",
    "solidworks_revolve",
    "solidworks_fillet",
    "solidworks_chamfer",
    "solidworks_shell",
    "solidworks_pattern",
    "solidworks_mirror_feature",
    "solidworks_list_edges",
    # 几何自检工具：机械设计必须能回读实测尺寸和质量。
    "solidworks_mass_properties",
    "solidworks_bounding_box",
    "solidworks_interference_check",
    "solidworks_document_units",
    # 规格驱动建模：可版本控制、幂等、自带验证。
    "design_spec_validate",
    "design_spec_build",
    "solidworks_add_component",
    "solidworks_set_component_fixed",
    "solidworks_save_document",
    "solidworks_close_documents",
    "solidworks_add_coincident_mate",
    "solidworks_add_distance_mate",
    "solidworks_add_concentric_mate",
    "solidworks_set_appearance",
    "solidworks_export_active",
    "solidworks_inspect_configurations",
    "solidworks_create_configuration",
    "solidworks_activate_configuration",
    "solidworks_update_dimension",
    "solidworks_set_custom_properties",
    "solidworks_batch_export_files",
    "solidworks_export_assembly_bom",
    "solidworks_pack_and_go",
    "solidworks_review_active",
    "solidworks_create_hole_feature",
    "solidworks_inspect_hole_features",
    "solidworks_add_rotary_motor",
    "solidworks_inspect_motion_studies",
    "solidworks_validate_motion_study",
    "solidworks_generate_drawing",
    "solidworks_review_drawing",
    "solidworks_inspect_drawing",
}


def _configure_stdio_utf8() -> None:
    """在 Windows 旧代码页下尽量使用 UTF-8 输出中文提示。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _server_env(mode: str) -> dict[str, str]:
    return {
        **os.environ,
        "SW_MCP_DISCOVERY": mode,
        "SW_MCP_APPROVAL": "auto",
        "SW_MCP_APPROVAL_DIR": os.path.join(tempfile.gettempdir(), "sw-mcp-validate-approvals"),
    }


async def _with_session(mode: str, check) -> str:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(ROOT),
        env=_server_env(mode),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await check(session)


async def _check_full(session: ClientSession) -> str:
    names = {tool.name for tool in (await session.list_tools()).tools}
    if names & DISCOVERY_TOOLS:
        raise AssertionError(f"完整模式不应暴露发现入口: {sorted(names & DISCOVERY_TOOLS)}")
    missing = sorted(REQUIRED_TOOLS - names)
    if missing:
        raise AssertionError("完整模式缺少工具: " + ", ".join(missing))
    return f"完整模式 {len(names)} 个工具可见。"


async def _check_search(session: ClientSession) -> str:
    listed = {tool.name for tool in (await session.list_tools()).tools}
    if listed != DISCOVERY_TOOLS:
        raise AssertionError(f"发现模式应只暴露 {sorted(DISCOVERY_TOOLS)}，实际 {sorted(listed)}")

    for name in sorted(REQUIRED_TOOLS):
        found = await session.call_tool("sw_search_tools", {"query": name, "limit": 5})
        if found.isError:
            raise AssertionError(f"检索 {name} 失败: {found.content[0].text}")
        payload = json.loads(found.content[0].text)
        hits = [item["name"] for item in payload["results"]]
        if name not in hits:
            raise AssertionError(f"按名称检索不到 {name}，实际候选: {hits}")

        described = await session.call_tool("sw_describe_tool", {"name": name})
        if described.isError:
            raise AssertionError(f"读取 {name} 的 Schema 失败: {described.content[0].text}")
        detail = json.loads(described.content[0].text)
        if detail.get("name") != name or not detail.get("inputSchema"):
            raise AssertionError(f"{name} 的 describe 结果不完整: {detail}")

    return f"发现模式 3 个入口，{len(REQUIRED_TOOLS)} 个必需工具均可按名称检索并读取 Schema。"


async def _main(mode: str) -> int:
    """执行 MCP 工具清单检查。"""
    if not SERVER_PATH.exists():
        raise FileNotFoundError(f"找不到 MCP Server: {SERVER_PATH}")
    if mode in ("both", "full"):
        print("MCP 验证通过: " + await _with_session("full", _check_full))
    if mode in ("both", "search"):
        print("MCP 验证通过: " + await _with_session("search", _check_search))
    return 0


if __name__ == "__main__":
    _configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="校验 SolidWorks MCP 的 tools/list 表面")
    parser.add_argument("--mode", choices=("both", "full", "search"), default="both",
                        help="校验哪种模式（默认 both）")
    options = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main(options.mode)))
    except Exception as exc:
        print(f"MCP 验证失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
