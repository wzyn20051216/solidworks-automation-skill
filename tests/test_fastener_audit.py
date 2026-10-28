"""沉头/紧固 3D 配合审计（纯函数）的无 COM 回归测试。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fastener_audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("fastener_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fastener_audit"] = module
    spec.loader.exec_module(module)
    return module


fa = _load()


def _ids(checks):
    out = {}
    for c in checks:
        out.setdefault(c["id"], c)
    return out


def test_nominal_from_thread():
    assert fa.nominal_from_thread("M6") == 6.0
    assert fa.nominal_from_thread("M8x1.25") == 8.0
    assert fa.nominal_from_thread(None) is None


def test_head_dimensions_table():
    assert fa.head_dimensions("socket_cap", 6)["dk"] == 10.0
    assert fa.head_dimensions("socket_cap", 6)["k"] == 6.0
    assert fa.head_dimensions("countersunk_flat", 6)["dk"] == 12.0
    assert fa.head_dimensions("socket_cap", 99) is None


def test_parse_fastener_hole():
    f = {"id": "C1", "type": "hole", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 11, "depth": 6.5, "side": "front"}, "matingSide": "back"}}
    h = fa.parse_fastener_hole(f)
    assert h["sink_type"] == "counterbore"
    assert h["head_type"] == "socket_cap"
    assert h["nominal_mm"] == 6.0
    assert h["sink_side"] == "front" and h["mating_side"] == "back"
    # 无沉头返回 None
    assert fa.parse_fastener_hole({"id": "X", "parameters": {"diameter": 6}}) is None


def test_invalid_counterbore_geometry():
    h = fa.parse_fastener_hole({"id": "C", "parameters": {"diameter": 10, "thread": "M6", "counterbore": {"diameter": 9, "depth": 5, "side": "front"}, "matingSide": "back"}})
    checks = _ids(fa.audit_fastener_hole(h))
    assert checks["DRC-CSK-001"]["status"] == "fail"  # 沉孔 9 <= 主孔 10


def test_head_accommodation():
    small = fa.parse_fastener_hole({"id": "C", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 9, "depth": 5, "side": "front"}, "matingSide": "back"}})
    checks = _ids(fa.audit_fastener_hole(small))
    assert checks["DRC-CSK-002"]["status"] == "fail"   # 9 < 10.5
    assert checks["DRC-CSK-003"]["status"] == "warning"  # 深度 5 < 头高 6


def test_orientation_toward_mating_face_fails():
    h = fa.parse_fastener_hole({"id": "C", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 11, "depth": 6.5, "side": "back"}, "matingSide": "back"}})
    checks = _ids(fa.audit_fastener_hole(h))
    assert checks["DRC-CSK-004"]["status"] == "fail"
    assert checks["DRC-CSK-004"]["severity"] == "critical"


def test_good_counterbore_all_pass():
    h = fa.parse_fastener_hole({"id": "C", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 11, "depth": 6.5, "side": "front"}, "matingSide": "back"}})
    checks = _ids(fa.audit_fastener_hole(h))
    assert all(checks[k]["status"] == "pass" for k in ("DRC-CSK-001", "DRC-CSK-002", "DRC-CSK-003", "DRC-CSK-004"))


def test_orientation_consistency_group():
    holes = [
        fa.parse_fastener_hole({"id": "C1", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 11, "depth": 6.5, "side": "front"}}}),
        fa.parse_fastener_hole({"id": "C2", "parameters": {"diameter": 6.6, "thread": "M6", "counterbore": {"diameter": 11, "depth": 6.5, "side": "back"}}}),
    ]
    checks = _ids(fa.audit_orientation_consistency(holes))
    assert checks["DRC-CSK-005"]["status"] == "warning"


def test_relief_pilot():
    fail = _ids(fa.audit_relief([{"id": "S1", "protrudes": True, "matingHasRelief": False, "gapMm": 0.0}]))
    assert fail["DRC-FIT-001"]["status"] == "fail"
    ok = _ids(fa.audit_relief([{"id": "S2", "protrudes": True, "matingHasRelief": True}]))
    assert ok["DRC-FIT-001"]["status"] == "pass"
    gap = _ids(fa.audit_relief([{"id": "S3", "protrudes": True, "matingHasRelief": False, "gapMm": 1.0}]))
    assert gap["DRC-FIT-001"]["status"] == "pass"


def test_counterbores_from_cylinders_pairs_coaxial():
    cyls = [
        {"diameter_mm": 6.6, "origin_mm": [10, 10, 5], "axis": [0, 0, 1]},
        {"diameter_mm": 11.0, "origin_mm": [10, 10, 1], "axis": [0, 0, 1]},
        {"diameter_mm": 6.6, "origin_mm": [50, 10, 5], "axis": [0, 0, 1]},  # 无沉孔配对
        {"diameter_mm": 8.0, "origin_mm": [80, 10, 5], "axis": [1, 0, 0]},  # 侧壁，滤除
    ]
    features = fa.counterbores_from_cylinders(cyls)
    assert len(features) == 1
    assert features[0]["main_diameter_mm"] == 6.6
    assert features[0]["sink_diameter_mm"] == 11.0
