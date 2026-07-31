"""ezdxf 只读后端回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subskills" / "autocad-automation" / "scripts"))

from acad_headless import inspect_dxf  # noqa: E402


def test_inspect_dxf_reports_layers_entities_and_bbox(tmp_path):
    source = tmp_path / "plate.dxf"
    document = ezdxf.new("R2018")
    document.layers.add("OUTLINE")
    modelspace = document.modelspace()
    modelspace.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True, dxfattribs={"layer": "OUTLINE"})
    modelspace.add_circle((20, 20), 4, dxfattribs={"layer": "OUTLINE"})
    document.saveas(source)

    report = inspect_dxf(source)

    assert report["backend"] == "ezdxf-readonly"
    assert report["entityCount"] == 2
    assert report["layerCounts"]["OUTLINE"] == 2
    assert report["bbox"] is not None


def test_headless_backend_rejects_dwg(tmp_path):
    source = tmp_path / "drawing.dwg"
    source.write_bytes(b"not-a-dwg")
    with pytest.raises(ValueError, match="只接受 DXF"):
        inspect_dxf(source)
