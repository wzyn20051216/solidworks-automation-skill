"""Verify that a released MCPB contains the complete runtime and no local state."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


REQUIRED_ENTRIES = (
    "manifest.json",
    "SKILL.md",
    "capabilities.yaml",
    "mcp-server/server.py",
    "scripts/drawing_spec.py",
    "scripts/sw_drawing.py",
    "references/mcp-server.md",
    "subskills/solidworks-engineering-drawing/schemas/drawing_spec.schema.json",
    "subskills/solidworks-engineering-drawing/schemas/gdt_copy_spec.schema.json",
    "subskills/solidworks-vibecad/schemas/design_plan.schema.json",
    "config/runtime.example.json",
)

FORBIDDEN_SUFFIXES = (".log", ".pyc", ".pyo")
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", "node_modules", "release-output"}
FORBIDDEN_PATHS = {"config/runtime.local.json"}


def verify_mcpb(path: Path, expected_version: str | None = None) -> dict[str, object]:
    """Validate bundle identity, required runtime files, and local-state exclusions."""
    archive_path = path.resolve(strict=True)
    with zipfile.ZipFile(archive_path) as archive:
        raw_names = archive.namelist()
        names = [name.replace("\\", "/") for name in raw_names]
        if len(names) != len(set(names)):
            raise ValueError("MCPB contains duplicate paths")
        missing = sorted(set(REQUIRED_ENTRIES) - set(names))
        if missing:
            raise ValueError(f"MCPB is missing required runtime files: {missing}")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        version = str(manifest.get("version") or "")
        if expected_version is not None and version != expected_version:
            raise ValueError(f"MCPB version mismatch: expected {expected_version}, got {version}")
        entry_point = (manifest.get("server") or {}).get("entry_point")
        if not isinstance(entry_point, str) or entry_point.replace("\\", "/") not in names:
            raise ValueError("MCPB server entry_point is missing from the archive")
        forbidden = []
        for name in names:
            normalized = name.replace("\\", "/")
            parts = set(normalized.split("/"))
            if normalized in FORBIDDEN_PATHS or parts.intersection(FORBIDDEN_PARTS):
                forbidden.append(normalized)
            elif normalized.casefold().endswith(FORBIDDEN_SUFFIXES):
                forbidden.append(normalized)
        if forbidden:
            raise ValueError(f"MCPB contains local or generated files: {forbidden[:10]}")
        uncompressed_bytes = sum(info.file_size for info in archive.infolist())
    return {
        "status": "pass",
        "version": version,
        "files": len(raw_names),
        "uncompressedBytes": uncompressed_bytes,
        "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--version")
    args = parser.parse_args()
    print(json.dumps(verify_mcpb(args.archive, args.version), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
