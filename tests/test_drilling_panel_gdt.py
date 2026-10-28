"""@brief 钻孔面板 GD&T 分析内核的无 COM 回归测试。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "subskills"
    / "solidworks-engineering-drawing"
    / "scripts"
    / "drilling_panel_gdt.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("drilling_panel_gdt", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["drilling_panel_gdt"] = module
    spec.loader.exec_module(module)
    return module


dpg = _load_module()


def _panel_holes():
    H = dpg.Hole
    holes = [H(f"G{r}{c}", 25 + c * 50, 25 + r * 40, 6.0, "tapped") for r in range(4) for c in range(5)]
    holes += [H(f"L{i}", 25 + i * 50, 180, 9.0, "clearance") for i in range(6)]
    holes += [H("D1", 10, 10, 6.0, "dowel"), H("D2", 290, 10, 6.0, "dowel")]
    return holes


def test_grid_pattern_detection():
    patterns = dpg.detect_hole_patterns(_panel_holes())
    by_kind = {(p.hole_kind): p for p in patterns}
    grid = by_kind["tapped"]
    assert grid.kind == "grid"
    assert grid.rows == 4 and grid.cols == 5
    assert grid.pitch_x_mm == pytest.approx(50.0)
    assert grid.pitch_y_mm == pytest.approx(40.0)
    assert grid.regular and grid.complete
    assert grid.count == 20


def test_linear_pattern_detection():
    patterns = dpg.detect_hole_patterns(_panel_holes())
    linear = next(p for p in patterns if p.hole_kind == "clearance")
    assert linear.kind == "linear"
    assert linear.count == 6
    assert linear.pitch_x_mm == pytest.approx(50.0)
    assert linear.regular


def test_dowel_pair_becomes_cluster_and_datum_candidate():
    holes = _panel_holes()
    patterns = dpg.detect_hole_patterns(holes)
    dowel = next(p for p in patterns if p.hole_kind == "dowel")
    assert dowel.count == 2
    datums = dpg.infer_datums(holes, {"widthMm": 300, "heightMm": 200})
    assert datums.dowel_candidates == ["D1", "D2"]


def test_datum_scheme_321():
    datums = dpg.infer_datums(_panel_holes(), {"widthMm": 300, "heightMm": 200, "originXMm": 0, "originYMm": 0})
    assert datums.origin_mm == (0.0, 0.0)
    assert datums.primary_axis == "x"  # 宽>高，长边沿 X
    ids = [d["id"] for d in datums.datums]
    assert ids == ["A", "B", "C"]
    assert datums.datums[0]["type"] == "plane"
    assert datums.datums[1]["type"] == "edge"


def test_gdt_generation_position_and_flatness():
    holes = _panel_holes()
    patterns = dpg.detect_hole_patterns(holes)
    datums = dpg.infer_datums(holes, {"widthMm": 300, "heightMm": 200})
    frames = dpg.generate_gdt(patterns, datums)
    symbols = {f.symbol for f in frames}
    assert "flatness" in symbols and "position" in symbols
    flat = next(f for f in frames if f.symbol == "flatness")
    assert "⌀" not in flat.text  # 平面度不是圆柱公差域
    # 间隙孔位置度带 MMC，定位销位置度更紧且 RFS
    positions = [f for f in frames if f.symbol == "position"]
    assert any("Ⓜ" in f.text for f in positions)  # 至少一组带最大实体
    assert any(f.material_condition is None and f.tolerance_mm <= 0.05 for f in positions)  # 定位销 RFS 从严


def test_gdt_profile_override():
    holes = _panel_holes()
    patterns = dpg.detect_hole_patterns(holes)
    datums = dpg.infer_datums(holes, {"widthMm": 300, "heightMm": 200})
    frames = dpg.generate_gdt(patterns, datums, {"positionToleranceMm": 0.1})
    clearance_pos = [f for f in frames if f.symbol == "position" and f.material_condition == "M"]
    assert all(f.tolerance_mm == pytest.approx(0.1) for f in clearance_pos)


def test_hole_table_and_ordinates():
    holes = _panel_holes()
    analysis = dpg.analyze_drilling_panel(holes, plate={"widthMm": 300, "heightMm": 200})
    table = analysis["holeTable"]
    assert len(table) == 3
    assert any("栅格" in row["description"] for row in table)
    ordinates = analysis["ordinateDimensions"]
    assert ordinates["origin_mm"] == [0.0, 0.0]
    assert 25.0 in ordinates["x_ordinates_mm"]
    assert 180.0 in ordinates["y_ordinates_mm"]


def test_build_drawing_spec_structure():
    holes = _panel_holes()
    analysis = dpg.analyze_drilling_panel(holes, plate={"widthMm": 300, "heightMm": 200})
    spec = dpg.build_drawing_spec(analysis, source_model="panel.SLDPRT", thickness_mm=25)
    assert spec["standard"] == "GB_T"
    assert spec["paperSize"] in {"A4", "A3", "A2", "A1", "A0"}
    assert spec["modelSizeMm"] == [300.0, 200.0, 25.0]
    assert spec["outputs"] == {"slddrw": True, "pdf": True, "report": True}
    assert "front" in spec["views"]
    pa = spec["professionalAnnotations"]
    assert [d["text"] for d in pa["datums"]] == ["A", "B", "C"]
    assert pa["geometricTolerances"]  # 至少一条 GD&T
    # 栅格孔的 locationsMm 数量与 count 一致且精确
    grid_req = next(h for h in spec["holeRequirements"] if h["pattern"] == "grid")
    assert len(grid_req["locationsMm"]) == grid_req["count"] == 20
    assert grid_req["locationsMm"][0] == [25.0, 25.0]


def test_drawing_spec_passes_schema_when_validator_available():
    pytest.importorskip("jsonschema")
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    from drawing_spec import validate_drawing_spec  # subskill validator

    holes = _panel_holes()
    analysis = dpg.analyze_drilling_panel(holes, plate={"widthMm": 300, "heightMm": 200})
    spec = dpg.build_drawing_spec(analysis, source_model="panel.SLDPRT", thickness_mm=25)
    result = validate_drawing_spec(spec)
    assert result["status"] == "pass", result.get("issues")


def test_holes_from_neutral_document_unit_conversion():
    document = {
        "documentId": "p",
        "units": "in",
        "features": [
            {"id": "H1", "type": "hole", "parameters": {"diameter": 0.25, "x": 1.0, "y": 2.0}},
            {"id": "N1", "type": "boss", "parameters": {}},
        ],
    }
    holes = dpg.holes_from_neutral_document(document)
    assert len(holes) == 1
    assert holes[0].diameter == pytest.approx(6.35)
    assert holes[0].x == pytest.approx(25.4)


def test_empty_holes_rejected():
    with pytest.raises(ValueError):
        dpg.analyze_drilling_panel([])


# ---- 打通真机 3D -> 分析：几何证据适配层（纯函数） ----


def _measurements():
    return {
        "envelope_mm": {"length": 300.0, "width": 200.0, "height": 25.0, "axis_order": "model_xyz"},
        "holes": [
            {"diameter_mm": 6.0, "position_mm": [25, 25, 12.5], "axis": [0, 0, 1]},
            {"diameter_mm": 6.0, "position_mm": [75, 25, 12.5], "axis": [0, 0, 1]},
            {"diameter_mm": 6.0, "position_mm": [25, 65, 12.5], "axis": [0, 0, 1]},
            {"diameter_mm": 6.0, "position_mm": [75, 65, 12.5], "axis": [0, 0, 1]},
            {"diameter_mm": 12.0, "position_mm": [25, 25, 2.0], "axis": [0, 0, 1]},  # 沉孔叠层
            {"diameter_mm": 8.0, "position_mm": [150, 100, 12.5], "axis": [1, 0, 0]},  # 侧壁
        ],
    }


def test_adapter_detects_normal_axis_and_filters_side_walls():
    res = dpg.holes_from_geometry_measurements(_measurements(), part_box_mm=[0, 0, 0, 300, 200, 25])
    assert res["normalAxis"] == "z"
    # 4 个通孔；侧壁圆柱被滤除
    assert len(res["holes"]) == 4


def test_adapter_merges_counterbore_to_min_diameter():
    res = dpg.holes_from_geometry_measurements(_measurements(), part_box_mm=[0, 0, 0, 300, 200, 25])
    at_corner = [h for h in res["holes"] if abs(h.x - 25) < 0.1 and abs(h.y - 25) < 0.1]
    assert len(at_corner) == 1
    assert at_corner[0].diameter == pytest.approx(6.0)  # 取最小直径为功能孔径


def test_adapter_plate_from_part_box():
    res = dpg.holes_from_geometry_measurements(_measurements(), part_box_mm=[0, 0, 0, 300, 200, 25])
    plate = res["plate"]
    assert plate["widthMm"] == 300.0 and plate["heightMm"] == 200.0 and plate["thicknessMm"] == 25.0
    assert plate["originXMm"] == 0.0 and plate["originYMm"] == 0.0


def test_adapter_plate_fallback_from_holes_when_no_box():
    res = dpg.holes_from_geometry_measurements(_measurements())
    assert any("外扩" in w for w in res["warnings"])
    assert res["plate"]["thicknessMm"] == 25.0  # 厚度仍来自包围盒最薄方向


def test_adapter_end_to_end_to_grid():
    res = dpg.holes_from_geometry_measurements(_measurements(), part_box_mm=[0, 0, 0, 300, 200, 25])
    analysis = dpg.analyze_drilling_panel(res["holes"], plate=res["plate"])
    grid = next(p for p in analysis["patterns"] if p["kind"] == "grid")
    assert grid["count"] == 4
    assert grid["pitchXMm"] == pytest.approx(50.0)
    assert grid["pitchYMm"] == pytest.approx(40.0)


def test_adapter_normal_axis_y_plate():
    # 面板法向沿 Y（厚度在 width 方向最薄）
    meas = {
        "envelope_mm": {"length": 300.0, "width": 20.0, "height": 200.0, "axis_order": "model_xyz"},
        "holes": [
            {"diameter_mm": 6.0, "position_mm": [25, 10, 25], "axis": [0, 1, 0]},
            {"diameter_mm": 6.0, "position_mm": [75, 10, 25], "axis": [0, 1, 0]},
        ],
    }
    res = dpg.holes_from_geometry_measurements(meas, part_box_mm=[0, 0, 0, 300, 20, 200])
    assert res["normalAxis"] == "y"
    # 平面内坐标取 x,z
    assert res["holes"][0].x == pytest.approx(25.0)
    assert res["holes"][0].y == pytest.approx(25.0)


def test_adapter_empty_measurements_warns():
    res = dpg.holes_from_geometry_measurements({"envelope_mm": {"length": 100, "width": 100, "height": 10}, "holes": []})
    assert res["holes"] == []
    assert res["warnings"]
