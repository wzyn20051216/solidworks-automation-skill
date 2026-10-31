"""手动真机回归：创建、导出并重开开放端等螺距弹簧。"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sw_connect import get_com_member
from scripts.sw_measure import collect_mass_properties
from scripts.sw_review import collect_model_summary, run_review
from scripts.sw_session import SolidWorksSession
from scripts.sw_spring import (OpenHelicalSpringSpec, create_open_helical_spring,
                               exact_body_bounds_mm, expected_body_bounds_mm, verify_helix_definition)


def verify(model, spec):
    bodies = tuple(get_com_member(model, "GetBodies2", 0, False) or ())
    mass = collect_mass_properties(model)
    expected_length = math.sqrt((math.pi * spec.mean_diameter_mm * spec.turns) ** 2 + spec.helix_height_mm ** 2)
    expected_volume = math.pi * (spec.wire_diameter_mm / 2) ** 2 * expected_length
    if len(bodies) != 1 or mass["errors"] or not math.isclose(mass["volume_mm3"], expected_volume, rel_tol=.005):
        raise AssertionError(f"实体体积读取异常: {mass}")
    actual = sorted(exact_body_bounds_mm(bodies[0]))
    expected = expected_body_bounds_mm(spec, spec.helix_height_mm / spec.turns)
    if any(not math.isclose(a, b, rel_tol=.002, abs_tol=.03) for a, b in zip(actual, expected)):
        raise AssertionError(f"实体极值尺寸异常: {actual} != {expected}")
    features = collect_model_summary(model).get("features", [])
    helixes = [item for item in features if item.get("type") == "Helix"]
    if len(helixes) != 1:
        raise AssertionError("未找到真实螺旋线特征")
    if not any(item.get("name") == "OpenHelicalSpring" for item in features):
        raise AssertionError("未找到真实扫描特征")
    helix = get_com_member(model, "FeatureByName", helixes[0]["name"])
    helix_data = verify_helix_definition(helix, spec, spec.helix_height_mm / spec.turns)
    return {"volume_mm3": mass["volume_mm3"], "expected_volume_mm3": expected_volume,
            "extreme_bounds_mm": actual, "helix_readback": helix_data}


def main():
    root = Path(tempfile.mkdtemp(prefix="sw_pr36_spring_live_"))
    cases = [OpenHelicalSpringSpec(3, 24, 48, 6), OpenHelicalSpringSpec(2, 16, 25, 5.5, True)]
    results = []
    with SolidWorksSession(version=2026, wait_seconds=60, visible=False) as session:
        before = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        for index, spec in enumerate(cases):
            native, step = root / f"open_spring_{index}.sldprt", root / f"open_spring_{index}.step"
            model = session.new_part()
            _, evidence = create_open_helical_spring(model, spec)
            created = verify(model, spec)
            if not session.save(model, str(native)) or not session.export(model, str(step)):
                raise RuntimeError("弹簧保存或 STEP 导出失败")
            review, review_path = run_review(model, str(root / f"review_{index}"), basename="spring", expected_outputs=[str(native), str(step)])
            evaluation = review.get("evaluation", {})
            if evaluation.get("status") not in ("pass", "warn") or any(
                    item.get("code") != "sketch_quality_review_required" for item in evaluation.get("issues", [])):
                raise AssertionError(f"自动审查存在其他问题: {evaluation}")
            session.close(model=model)
            model = session.open(str(native), read_only=True, silent=True)
            reopened = verify(model, spec)
            session.close(model=model)
            results.append({"created": created, "reopened": reopened, "review": evaluation,
                            "evidence": evidence, "review_report": str(review_path)})
        after = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        if any(title not in after for title in before):
            raise AssertionError("用户已有文档消失")
    print(json.dumps({"status": "review_required", "geometry_verification": "pass", "directory": str(root),
                      "cases": results, "existing_documents_preserved": len(before)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
