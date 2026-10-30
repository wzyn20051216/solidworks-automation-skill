"""手动真机回归：在临时目录创建并重开近似链轮，保护原有文档。"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.standard_parts_geometry import roller_sprocket_profile
from scripts.sw_connect import get_com_member
from scripts.sw_measure import collect_mass_properties
from scripts.sw_review import collect_geometry_measurements, run_review
from scripts.sw_session import SolidWorksSession
from scripts.sw_sprocket import SprocketSpec, create_approximate_sprocket


def verify(model, spec, geometry):
    if len(tuple(get_com_member(model, "GetBodies2", 0, False) or ())) != 1:
        raise AssertionError("链轮不是单一实体")
    measurement = collect_geometry_measurements(model)
    if measurement.get("errors"):
        raise AssertionError(f"几何回读失败: {measurement['errors']}")
    hole_diameters = [float(h.get("diameter_mm") or 0) for h in measurement.get("holes", [])]
    if not any(abs(value - spec.bore_diameter_mm) < .02 for value in hole_diameters):
        raise AssertionError(f"未回读到指定轴孔: {hole_diameters}")
    points = geometry.profile_xy_mm
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
    expected_volume = (area - math.pi * (spec.bore_diameter_mm / 2) ** 2) * spec.thickness_mm
    mass = collect_mass_properties(model)
    volume = mass.get("volume_mm3")
    if volume is None or abs(volume - expected_volume) > expected_volume * .001:
        raise AssertionError(f"实体体积不符: {volume} != {expected_volume}")
    envelope = measurement.get("envelope_mm") or {}
    actual = sorted(float(envelope.get(k) or 0) for k in ("length", "width", "height"))
    xs, ys = zip(*points)
    expected = sorted((max(xs) - min(xs), max(ys) - min(ys), spec.thickness_mm))
    if any(abs(a - b) > .03 for a, b in zip(actual, expected)):
        raise AssertionError(f"包围盒不符: {actual} != {expected}")
    return {"volume_mm3": volume, "expected_volume_mm3": expected_volume,
            "axes_mm": actual, "hole_diameters_mm": hole_diameters}


def main():
    output = Path(tempfile.mkdtemp(prefix="sw_pr36_sprocket_"))
    part = output / "approx_sprocket.sldprt"
    step = output / "approx_sprocket.step"
    spec = SprocketSpec(12.7, 7.92, 17, 6, 10)
    geometry = roller_sprocket_profile(spec.chain_pitch_mm, spec.roller_diameter_mm, spec.teeth,
                                      bore_diameter_mm=spec.bore_diameter_mm, seat_samples=spec.seat_samples)
    with SolidWorksSession(version=2026, visible=True) as session:
        before = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        model = session.new_part()
        _, evidence = create_approximate_sprocket(model, spec)
        created = verify(model, spec, geometry)
        if not session.save(model, str(part)) or not session.export(model, str(step)):
            raise RuntimeError("保存或 STEP 导出失败")
        review, review_path = run_review(model, str(output / "review"), basename="sprocket",
                                         expected_outputs=[str(part), str(step)])
        evaluation = review.get("evaluation", {})
        # 近似轮廓暂未完全约束，必须如实保留该告警；其他问题不允许放行。
        issue_codes = {issue.get("code") for issue in evaluation.get("issues", [])}
        if evaluation.get("status") != "warn" or issue_codes != {"sketch_quality_review_required"}:
            raise AssertionError(f"自动审查出现预期以外的问题: {evaluation}")
        session.close(model=model)
        model = session.open(str(part), read_only=True, silent=True)
        reopened = verify(model, spec, geometry)
        session.close(model=model)
        after = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        if any(title not in after for title in before):
            raise AssertionError("用户原有文档消失")
    print(json.dumps({"status": "review_required", "geometry_verification": "pass", "directory": str(output), "existing_documents_preserved": len(before),
                      "created": created, "reopened": reopened, "evidence": evidence,
                      "review_report": str(review_path)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
