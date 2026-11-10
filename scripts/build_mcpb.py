"""使用发布运行时清单构建 Windows MCP Bundle。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import zipfile

try:
    from .build_skill_release import release_version
    from .sync_bundled_skill import ROOT, collect_runtime_files
except ImportError:
    from build_skill_release import release_version
    from sync_bundled_skill import ROOT, collect_runtime_files

EXTRA_FILES = ("manifest.json", "pyproject.toml", "uv.lock", "LICENSE", "config/runtime.example.json")
REQUIRED_FILES = {
    "mcp-server/server.py",
    "mcp-server/start_mcpb.ps1",
    "references/mcp-server.md",
    "subskills/solidworks-engineering-drawing/schemas/drawing_spec.schema.json",
    "subskills/solidworks-engineering-drawing/schemas/gdt_copy_spec.schema.json",
}


def build_mcpb(root: Path, output: Path) -> int:
    """只从 Git 跟踪的文件取材，并回读 ZIP 检查内容与来源一致。"""
    root = root.resolve(strict=True)
    tracked = set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        .decode("utf-8").split("\0")
    )
    files = {path.as_posix(): source for path, source in collect_runtime_files(root).items()}
    files.update({name: root / name for name in EXTRA_FILES})
    files = {name: source for name, source in files.items() if name in tracked}
    missing = (REQUIRED_FILES | set(EXTRA_FILES)) - files.keys()
    if missing:
        raise ValueError(f"MCPB 缺少受 Git 跟踪的运行时文件: {sorted(missing)}")
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError("MCPB 有 Windows 文件名冲突")

    payload = {}
    for name, source in files.items():
        if not source.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"MCPB 源文件越出仓库: {name}")
        payload[name] = source.read_bytes()

    manifest = json.loads(payload["manifest.json"])
    if manifest.get("manifest_version") != "0.4" or manifest.get("version") != release_version(root):
        raise ValueError("MCPB 清单格式或发布版本不一致")
    if manifest["server"]["entry_point"] not in payload:
        raise ValueError("MCPB 启动入口缺失")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        if archive.namelist() != sorted(payload) or any(archive.read(name) != data for name, data in payload.items()):
            raise ValueError("MCPB 回读校验失败")
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "release-output" / f"SolidWorks-Automation-Skill-{release_version(ROOT)}.mcpb"
    count = build_mcpb(ROOT, output)
    print(f"MCPB: {output} ({count} files)")


if __name__ == "__main__":
    main()
