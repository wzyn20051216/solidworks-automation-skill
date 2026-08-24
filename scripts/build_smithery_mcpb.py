"""为 Smithery 构建带完整 MCP 工具 schema 的 MCPB 发布包。"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


def collect_tool_cards(repo_root: Path) -> list[dict[str, object]]:
    """@brief 从 FastMCP 注册表读取工具名称、说明和真实 inputSchema。"""
    server_dir = repo_root / "mcp-server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    import server  # noqa: PLC0415

    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.parameters,
        }
        for tool in server.mcp._tool_manager._tools.values()
    ]


def build_smithery_bundle(source: Path, target: Path) -> int:
    """@brief 将标准 MCPB 的工具清单替换为 Smithery 所需的完整工具卡。"""
    repo_root = source.resolve().parent.parent
    tools = collect_tool_cards(repo_root)
    if not tools:
        raise RuntimeError("MCP Server 未注册任何工具")

    with zipfile.ZipFile(source, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        manifest.pop("tools_generated", None)
        manifest["tools"] = tools
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for info in archive.infolist():
                if info.filename != "manifest.json":
                    output.writestr(info, archive.read(info.filename))
            output.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
    return len(tools)


def main() -> int:
    """@brief 执行 Smithery MCPB 构建命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="mcpb pack 生成的标准 MCPB")
    parser.add_argument("target", type=Path, help="供 Smithery 发布的 MCPB")
    args = parser.parse_args()
    count = build_smithery_bundle(args.source, args.target)
    print(f"Smithery MCPB 已生成: {args.target} ({count} 个工具 schema)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
