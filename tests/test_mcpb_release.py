"""验证发布包包含运行时文件，以及无 uv 时可诊断。"""

import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts.build_mcpb import REQUIRED_FILES, ROOT, build_mcpb


def test_mcpb_contains_tracked_runtime_without_local_state(tmp_path, monkeypatch):
    from scripts import build_mcpb as builder

    # 模拟开发者在运行时目录残留本地配置，发布包应由 Git 跟踪范围约束。
    original_collect = builder.collect_runtime_files
    local = tmp_path / "local-secret.env"
    local.write_text("test fixture", encoding="utf-8")
    monkeypatch.setattr(
        builder, "collect_runtime_files",
        lambda root: {**original_collect(root), Path("mcp-server/local-secret.env"): local},
    )
    output = tmp_path / "release.mcpb"
    build_mcpb(ROOT, output)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert REQUIRED_FILES <= names
        assert "mcp-server/local-secret.env" not in names
        assert "config/runtime.local.json" not in names
        assert archive.read("uv.lock") == (ROOT / "uv.lock").read_bytes()
        config = json.loads(archive.read("manifest.json"))["server"]
        assert config["entry_point"] in names
    with pytest.raises(FileExistsError):
        build_mcpb(ROOT, output)


@pytest.mark.skipif(os.name != "nt", reason="Windows MCPB launcher")
def test_mcpb_missing_uv_prints_install_guidance_without_stdio_noise(tmp_path):
    env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"), "USERPROFILE": str(tmp_path)}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(ROOT / "mcp-server" / "start_mcpb.ps1")],
        env=env, cwd=tmp_path, capture_output=True, timeout=15,
    )
    assert result.returncode == 127
    assert result.stdout == b""
    assert b"winget install --id astral-sh.uv -e" in result.stderr
    assert b"exit and reopen your MCP client" in result.stderr
