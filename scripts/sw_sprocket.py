"""SolidWorks 中生成用于外观和几何验证的近似链轮，不保证链条啮合。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

try:
    from .standard_parts_geometry import roller_sprocket_profile
    from .sw_connect import get_com_member
except ImportError:
    from standard_parts_geometry import roller_sprocket_profile
    from sw_connect import get_com_member


@dataclass(frozen=True)
class SprocketSpec:
    chain_pitch_mm: float
    roller_diameter_mm: float
    teeth: int
    thickness_mm: float
    bore_diameter_mm: float = 0.0
    seat_samples: int = 8


def create_approximate_sprocket(model, spec: SprocketSpec, plane_name: str = "Front Plane"):
    """在空零件中创建近似链轮；不保存文件，不宣称符合链轮标准。"""
    if isinstance(spec.thickness_mm, bool) or not math.isfinite(float(spec.thickness_mm)) or float(spec.thickness_mm) <= 0:
        raise ValueError("厚度必须是有限正数")
    geometry = roller_sprocket_profile(spec.chain_pitch_mm, spec.roller_diameter_mm, spec.teeth,
                                      bore_diameter_mm=spec.bore_diameter_mm, seat_samples=spec.seat_samples)
    if len(geometry.profile_xy_mm) > 2500:
        raise ValueError("离散链轮线段过多，拒绝创建")
    if get_com_member(model, "GetType") != 1:
        raise ValueError("必须传入 SolidWorks 零件文档")
    if tuple(get_com_member(model, "GetBodies2", 0, False) or ()):
        raise ValueError("近似链轮只允许创建在无实体的零件中")
    try:
        from .sw_part import extrude_boss, sketch, sketch_circle, sketch_line
    except ImportError:
        from sw_part import extrude_boss, sketch, sketch_circle, sketch_line

    manager = model.SketchManager
    old_add, old_display = None, None
    with sketch(model, plane_name) as sketch_name:
        try:
            old_add = bool(manager.AddToDB)
            old_display = bool(manager.DisplayWhenAdded)
            manager.AddToDB = True
            manager.DisplayWhenAdded = False
            points = geometry.profile_xy_mm
            for a, b in zip(points, points[1:] + points[:1]):
                if sketch_line(model, a[0] / 1000.0, a[1] / 1000.0, b[0] / 1000.0, b[1] / 1000.0) is None:
                    raise RuntimeError("创建链轮轮廓线段失败")
            if geometry.bore_diameter_mm > 0 and sketch_circle(model, 0, 0, geometry.bore_diameter_mm / 2000.0) is None:
                raise RuntimeError("创建链轮轴孔草图失败")
        finally:
            try:
                if old_add is not None:
                    manager.AddToDB = old_add
            finally:
                if old_display is not None:
                    manager.DisplayWhenAdded = old_display

    feature = extrude_boss(model, sketch_name, float(spec.thickness_mm) / 1000.0)
    if feature is None:
        raise RuntimeError("近似链轮轮廓拉伸失败")
    feature.Name = f"ApproxSprocket_z{spec.teeth}"
    model.ForceRebuild3(False)
    bodies = tuple(get_com_member(model, "GetBodies2", 0, False) or ())
    if len(bodies) != 1:
        raise RuntimeError(f"链轮实体数量异常: {len(bodies)}")
    evidence = {"status": "review_required", "input": asdict(spec), "feature_name": feature.Name,
                "profile": "polyline_approximation", "profile_segments": len(points),
                "pitch_diameter_mm": geometry.pitch_diameter_mm, "outside_diameter_mm": geometry.outside_diameter_mm,
                "nominal_root_diameter_mm": geometry.root_diameter_mm,
                "actual_profile_min_diameter_mm": geometry.profile_min_diameter_mm,
                "limitations": ["仅用于外观及几何验证，未验证链条啮合、强度或制造标准", "草图轮廓是离散折线，非精确曲线",
                                "轮廓草图尚未完全参数化或约束；修改参数需重新生成并复核"]}
    return feature, evidence
