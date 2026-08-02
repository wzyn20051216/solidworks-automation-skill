"""@brief SolidWorks B-Rep 机器测量证据回归测试。"""

import math
from pathlib import Path

from scripts.sw_review import collect_geometry_measurements, inspect_bmp_preview, validate_hole_positions


class FakeSurface:
    """@brief 模拟圆柱曲面。"""

    IsCylinder = True

    def __init__(self, radius_m: float, origin=(0.0, 0.0, 0.0)):
        self.CylinderParams = (*origin, 0.0, 1.0, 0.0, radius_m)


class FakeFace:
    """@brief 模拟内部或外部圆柱面。"""

    def __init__(self, radius_m: float, internal: bool, length_m: float, edge_count=2, origin=(0.0, 0.0, 0.0)):
        self._surface = FakeSurface(radius_m, origin)
        self.FaceInSurfaceSense = internal
        self._area = 2 * math.pi * radius_m * length_m
        self._edge_count = edge_count

    def GetSurface(self):
        return self._surface

    def GetArea(self):
        return self._area

    def GetLoopCount(self):
        return 2 if self.FaceInSurfaceSense else 1

    def GetEdgeCount(self):
        return self._edge_count if self.FaceInSurfaceSense else 4


class FakeBody:
    """@brief 模拟包含一个孔壁和一个外圆角面的实体。"""

    def GetFaces(self):
        return [FakeFace(0.005, True, 0.012), FakeFace(0.002, False, 0.003)]


class FakeModel:
    """@brief 模拟 60 x 12 x 40 mm 零件。"""

    def GetPartBox(self, no_conversion):
        assert no_conversion is True
        return (-0.03, -0.012, -0.02, 0.03, 0.0, 0.02)

    def GetBodies2(self, body_type, visible_only):
        assert body_type == 0
        assert visible_only is False
        return [FakeBody()]


def test_geometry_measurements_distinguish_holes_from_external_fillets() -> None:
    measurements = collect_geometry_measurements(FakeModel())

    assert measurements["envelope_mm"] == {
        "length": 60.0,
        "width": 12.0,
        "height": 40.0,
        "axis_order": "model_xyz",
    }
    assert measurements["hole_count"] == 1
    assert measurements["holes"][0]["diameter_mm"] == 10.0
    assert measurements["holes"][0]["through_state"] == "unknown"
    assert len(measurements["cylindrical_faces"]) == 2
    assert measurements["errors"] == []


class FakeSlotBody:
    """@brief 模拟一个圆孔和长圆槽端部半圆柱面。"""

    def GetFaces(self):
        return [
            FakeFace(0.004, True, 0.010, edge_count=2, origin=(0.010, 0.0, 0.020)),
            FakeFace(0.005, True, 0.010, edge_count=4, origin=(0.030, 0.0, 0.020)),
        ]


class FakeSlotModel(FakeModel):
    """@brief 返回同时包含孔和槽端圆弧的测试实体。"""

    def GetBodies2(self, body_type, visible_only):
        return [FakeSlotBody()]


def test_slot_end_cylinder_is_not_counted_as_round_hole() -> None:
    measurements = collect_geometry_measurements(FakeSlotModel())

    assert measurements["hole_count"] == 1
    assert len(measurements["slot_arc_candidates"]) == 1
    assert measurements["slot_arc_candidates"][0]["diameter_mm"] == 10.0


def test_hole_position_acceptance_uses_axis_distance_and_diameter_tolerance() -> None:
    measurements = collect_geometry_measurements(FakeSlotModel())
    result = validate_hole_positions(
        measurements,
        [{"id": "H1", "diameter_mm": 8.0, "position_mm": [10.04, 15.0, 20.0]}],
        position_tolerance_mm=0.1,
    )

    assert result["status"] == "pass"
    assert result["checks"][0]["position_error_mm"] == 0.04


def test_hole_position_acceptance_fails_outside_tolerance() -> None:
    measurements = collect_geometry_measurements(FakeSlotModel())
    result = validate_hole_positions(
        measurements,
        [{"id": "H1", "diameter_mm": 8.2, "position_mm": [10.3, 15.0, 20.0]}],
        position_tolerance_mm=0.1,
        diameter_tolerance_mm=0.05,
    )

    assert result["status"] == "fail"
    assert result["checks"][0]["passed"] is False


def test_bmp_preview_samples_geometry_away_from_file_header(tmp_path: Path) -> None:
    """@brief 图框/几何在 BMP 中后段时不能误判为空白。"""
    # 2x2、24 位、底部一行黑像素的最小 BI_RGB BMP。
    pixels = b"\xff\xff\xff" * 2 + b"\x00\x00" + b"\x00\x00\x00" * 2 + b"\x00\x00"
    header = bytearray(b"BM")
    header.extend((54 + len(pixels)).to_bytes(4, "little"))
    header.extend(b"\x00\x00\x00\x00")
    header.extend((54).to_bytes(4, "little"))
    header.extend((40).to_bytes(4, "little"))
    header.extend((2).to_bytes(4, "little", signed=True))
    header.extend((2).to_bytes(4, "little", signed=True))
    header.extend((1).to_bytes(2, "little"))
    header.extend((24).to_bytes(2, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend(len(pixels).to_bytes(4, "little"))
    header.extend(b"\x00" * 16)
    target = tmp_path / "preview.bmp"
    target.write_bytes(bytes(header) + pixels)

    report = inspect_bmp_preview(target)
    assert report["likely_blank"] is False
    assert report["dark_pixel_ratio"] > 0
