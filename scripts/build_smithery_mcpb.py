"""为 Smithery 构建与运行模式一致的 MCPB 工具清单。"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


def collect_tool_cards(repo_root: Path, mode: str = "search") -> list[dict[str, object]]:
    """@brief 从完整注册表选择与运行模式一致的工具卡。"""
    if mode not in ("search", "full"):
        raise ValueError(f"未知 MCP 模式: {mode}")
    server_dir = repo_root / "mcp-server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    import server  # noqa: PLC0415
    from gate import DISCOVERY_TOOLS  # noqa: PLC0415

    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.parameters,
        }
        for tool in server.mcp._tool_manager._tools.values()
        if (tool.name in DISCOVERY_TOOLS) == (mode == "search")
    ]


def build_smithery_bundle(source: Path, target: Path, mode: str = "search", repo_root: Path | None = None) -> int:
    """@brief 将 MCPB 工具卡和启动模式同步，避免宣告不可见的工具。"""
    repo_root = (repo_root or source.resolve().parent.parent).resolve()
    tools = collect_tool_cards(repo_root, mode=mode)
    if not tools:
        raise RuntimeError("MCP Server 未注册任何工具")

    with zipfile.ZipFile(source, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        manifest.pop("tools_generated", None)
        manifest["tools"] = tools
        manifest.setdefault("server", {}).setdefault("mcp_config", {}).setdefault("env", {})["SW_MCP_DISCOVERY"] = mode
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as output:
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
    parser.add_argument("--mode", choices=("search", "full"), default="search", help="打包的工具模式")
    parser.add_argument("--repo-root", type=Path, help="仓库根目录，默认从包的上级目录推断")
    args = parser.parse_args()
    count = build_smithery_bundle(args.source, args.target, mode=args.mode, repo_root=args.repo_root)
    print(f"Smithery MCPB 已生成: {args.target} ({count} 个工具 schema)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
