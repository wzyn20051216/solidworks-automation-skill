"""DXF 到安全 PreviewScene 的独立回归。"""
import os
from pathlib import Path

import ezdxf
import pytest

from scripts.dxf_preview_scene import MAX_DXF_BYTES, dxf_to_preview_scene


def test_dxf_preview_scene_records_unsupported_entities_without_executing_them(tmp_path: Path):
    """@brief 不支持实体必须形成限制，已支持实体仍可安全显示。"""
    source = tmp_path / "mixed.dxf"
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (40, 0), dxfattribs={"layer": "OUTLINE"})
    modelspace.add_3dface([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    document.saveas(source)

    scene = dxf_to_preview_scene(source)

    assert len(scene["entities"]) == 1
    assert scene["entities"][0]["kind"] == "line"
    assert any("3DFACE" in warning for warning in scene["warnings"])


def test_dxf_preview_scene_rejects_oversized_input_before_parse(tmp_path: Path, monkeypatch):
    """@brief 文件安全上限在解析前生效。"""
    source = tmp_path / "oversized.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    resolved_source = source.resolve()
    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        value = original_stat(self, *args, **kwargs)
        if self == resolved_source:
            fields = list(value)
            fields[6] = MAX_DXF_BYTES + 1
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(ValueError, match="安全上限"):
        dxf_to_preview_scene(source)
