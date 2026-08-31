"""@brief 开源复杂 CNC 案例的离线来源与门槛测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "subskills" / "solidworks-fillet-chamfer-cnc" / "scripts" / "verify_open_source_complex_case.py"
MANIFEST = ROOT / "subskills" / "solidworks-fillet-chamfer-cnc" / "examples" / "open_source_corner_bracket_case.json"
SPEC = importlib.util.spec_from_file_location("open_source_cnc_case", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_pinned_manifest_contains_commit_hash_and_attribution() -> None:
    """@brief 网络案例必须固定提交、哈希、许可和署名。"""
    case = MODULE.load_case(MANIFEST)

    assert case["commit"] in case["download_url"]
    assert len(case["sha256"]) == 64
    assert case["license"] == "CC BY 3.0"
    assert "FreeCAD" in case["attribution"]
    assert case["advanced_operation"]["kind"] == "width_width_chamfer"
    assert case["advanced_operation"]["widths_mm"] == [0.2, 0.4]


def test_cached_source_is_verified_without_network(tmp_path) -> None:
    """@brief 已缓存源文件也必须逐字节校验 SHA-256。"""
    content = b"ISO-10303-21; pinned fixture"
    destination = tmp_path / "fixture.step"
    destination.write_bytes(content)
    case = {
        "download_url": "https://invalid.example/fixture.step",
        "sha256": hashlib.sha256(content).hexdigest(),
        "commit": "a" * 40,
        "license": "CC BY 3.0",
        "attribution": "fixture",
    }

    evidence = MODULE.fetch_pinned_source(case, destination)

    assert evidence["source"] == "cache"
    assert evidence["bytes"] == len(content)


def test_complexity_gate_rejects_empty_or_simplified_models() -> None:
    """@brief 单实体条件不能掩盖面边数量过低的错误导入。"""
    assert MODULE.topology_is_complex({"solids": 1, "faces": 40, "edges": 98, "vertices": 64})
    assert not MODULE.topology_is_complex({"solids": 1, "faces": 6, "edges": 12, "vertices": 8})
    assert not MODULE.topology_is_complex({"solids": 2, "faces": 40, "edges": 98, "vertices": 64})


def test_expected_source_topology_rejects_drift() -> None:
    """@brief 固定案例不能只满足下限，还必须匹配声明的精确拓扑。"""
    case = {"expected_source_topology": {"solids": 1, "faces": 40, "edges": 98}}
    MODULE.assert_expected_source_topology(case, {"solids": 1, "faces": 40, "edges": 98})

    with pytest.raises(RuntimeError, match="拓扑漂移"):
        MODULE.assert_expected_source_topology(case, {"solids": 1, "faces": 39, "edges": 98})
