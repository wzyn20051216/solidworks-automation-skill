"""MCPB release checks must reject incomplete bundles and local state."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_mcpb import REQUIRED_ENTRIES, verify_mcpb


def _bundle(path: Path, *, omit: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in REQUIRED_ENTRIES:
            if name == omit:
                continue
            payload = (
                json.dumps(
                    {
                        "version": "2.1.0",
                        "server": {"entry_point": "mcp-server/server.py"},
                    }
                )
                if name == "manifest.json"
                else name
            )
            archive.writestr(name, payload)
    return path


def test_complete_mcpb_passes(tmp_path: Path) -> None:
    result = verify_mcpb(_bundle(tmp_path / "complete.mcpb"), expected_version="2.1.0")
    assert result["status"] == "pass"
    assert result["version"] == "2.1.0"


def test_mcpb_without_drawing_schema_is_rejected(tmp_path: Path) -> None:
    archive = _bundle(
        tmp_path / "missing.mcpb",
        omit="subskills/solidworks-engineering-drawing/schemas/drawing_spec.schema.json",
    )
    with pytest.raises(ValueError, match="missing required runtime"):
        verify_mcpb(archive)


def test_mcpb_rejects_local_runtime_state(tmp_path: Path) -> None:
    archive = _bundle(tmp_path / "local-state.mcpb")
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("config/runtime.local.json", "{}")
    with pytest.raises(ValueError, match="local or generated"):
        verify_mcpb(archive)
