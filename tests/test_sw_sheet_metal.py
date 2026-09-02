"""原生钣金封装的离线契约测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_export import (  # noqa: E402
    SW_SHEET_METAL_EXPORT_BEND_LINES,
    SW_SHEET_METAL_EXPORT_BOUNDING_BOX,
    SW_SHEET_METAL_EXPORT_GEOMETRY,
    export_flat_pattern_dxf,
)
from sw_sheet_metal import BaseFlangeSpec  # noqa: E402


class FakePart:
    """@brief 记录 ExportToDWG2 入参的最小零件替身。"""

    def __init__(self, path: str):
        self.path = path
        self.args = None

    def GetPathName(self):
        return self.path

    def ExportToDWG2(self, *args):
        self.args = args
        return True


def test_flat_pattern_export_uses_alignment_array_and_option_bitmask(tmp_path):
    model_path = tmp_path / "sample.SLDPRT"
    model_path.write_bytes(b"native")
    part = FakePart(str(model_path))
    output = tmp_path / "flat.dxf"

    assert export_flat_pattern_dxf(part, output, include_bend_lines=True, include_bounding_box=True)
    assert part.args[0] == str(output.resolve())
    assert part.args[1] == str(model_path)
    assert part.args[2] == 1
    assert len(tuple(part.args[4].value)) == 12
    assert part.args[7] == (
        SW_SHEET_METAL_EXPORT_GEOMETRY
        | SW_SHEET_METAL_EXPORT_BEND_LINES
        | SW_SHEET_METAL_EXPORT_BOUNDING_BOX
    )


def test_flat_pattern_export_requires_saved_model(tmp_path):
    with pytest.raises(ValueError, match="必须先保存"):
        export_flat_pattern_dxf(FakePart(""), tmp_path / "flat.dxf")


@pytest.mark.parametrize(
    "spec,message",
    [
        (BaseFlangeSpec(0, 0.001, 0.1), "厚度"),
        (BaseFlangeSpec(0.002, -0.001, 0.1), "半径"),
        (BaseFlangeSpec(0.002, 0.001, 0), "深度"),
        (BaseFlangeSpec(0.002, 0.001, 0.1, k_factor=1.0), "K 因子"),
    ],
)
def test_base_flange_spec_rejects_invalid_manufacturing_values(spec, message):
    with pytest.raises(ValueError, match=message):
        spec.validate()
