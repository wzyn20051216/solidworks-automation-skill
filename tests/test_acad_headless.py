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
    assert report["schemaVersion"] == "2.0"
    assert report["evaluation"]["status"] == "warn"


def test_inspect_dxf_reports_engineering_drawing_evidence(tmp_path):
    source = tmp_path / "a3_plate.dxf"
    document = ezdxf.new("R2018")
    for layer in ("FRAME", "OUTLINE", "CENTER", "DIM", "TEXT"):
        document.layers.add(layer)
    modelspace = document.modelspace()
    modelspace.add_lwpolyline(
        [(0, 0), (420, 0), (420, 297), (0, 297)],
        close=True,
        dxfattribs={"layer": "FRAME"},
    )
    modelspace.add_lwpolyline(
        [(60, 100), (180, 100), (180, 180), (60, 180)],
        close=True,
        dxfattribs={"layer": "OUTLINE"},
    )
    modelspace.add_circle((75, 115), 4.5, dxfattribs={"layer": "OUTLINE"})
    modelspace.add_line((65, 115), (85, 115), dxfattribs={"layer": "CENTER"})
    modelspace.add_linear_dim(
        base=(60, 90),
        p1=(60, 100),
        p2=(180, 100),
        dxfattribs={"layer": "DIM"},
    ).render()
    for index, text in enumerate(("图号 W4-001", "名称 安装板", "材料 Q235B", "比例 1:1", "单位 mm")):
        modelspace.add_text(text, dxfattribs={"layer": "TEXT", "height": 3}).set_placement((240, 15 + index * 5))
    document.saveas(source)

    report = inspect_dxf(source)

    assert report["trueDimensionEntityCount"] == 1
    assert report["frameCandidates"][0]["width"] == 420
    assert report["engineeringChecks"]["hasTitleBlockEvidence"] is True
    assert report["engineeringChecks"]["hasHoleCenters"] is True
    assert report["evaluation"]["status"] == "pass"


def test_headless_backend_rejects_dwg(tmp_path):
    source = tmp_path / "drawing.dwg"
    source.write_bytes(b"not-a-dwg")
    with pytest.raises(ValueError, match="只接受 DXF"):
        inspect_dxf(source)
