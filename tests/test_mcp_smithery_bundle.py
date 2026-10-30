"""发布包清单应与默认及兼容模式的实际工具面一致。"""
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_smithery_mcpb import build_smithery_bundle, collect_tool_cards

ROOT = Path(__file__).resolve().parents[1]


def test_mcpb_excludes_local_handoff_and_evidence():
    rules = (ROOT / ".mcpbignore").read_text(encoding="utf-8").splitlines()
    assert "HANDOFF.md" in rules
    assert "docs/" in rules
    assert "*.private.pem" in rules
    assert ".cad-governance/" in rules
    assert ".env" in rules


def test_tool_cards_match_search_and_full_surfaces():
    search = {card["name"] for card in collect_tool_cards(ROOT, "search")}
    full = {card["name"] for card in collect_tool_cards(ROOT, "full")}
    assert search == {"sw_search_tools", "sw_describe_tool", "sw_call_tool"}
    assert len(full) == 69
    assert search.isdisjoint(full)
    with pytest.raises(ValueError):
        collect_tool_cards(ROOT, "unknown")


@pytest.mark.parametrize("mode,expected", [("search", 3), ("full", 69)])
def test_bundle_manifest_matches_selected_runtime(tmp_path, monkeypatch, mode, expected):
    source = tmp_path / "source.mcpb"
    target = tmp_path / "output.mcpb"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"server": {"mcp_config": {"env": {}}}}))
        archive.writestr("marker.txt", "kept")
    # 测试只重定向仓库根路径，保留真实工具卡生成逻辑。
    monkeypatch.setattr("scripts.build_smithery_mcpb.collect_tool_cards",
                        lambda _root, mode: collect_tool_cards(ROOT, mode))
    assert build_smithery_bundle(source, target, mode) == expected
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("marker.txt") == b"kept"
    assert len(manifest["tools"]) == expected
    assert manifest["server"]["mcp_config"]["env"]["SW_MCP_DISCOVERY"] == mode
