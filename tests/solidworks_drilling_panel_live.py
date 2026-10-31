"""手动真机验收：创建临时四孔板并保持用户已有文档。需 SolidWorks 2026。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.design_rule_check import build_drc_report
from scripts.sw_connect import get_com_member, mm
from scripts.sw_document_data import set_custom_properties
from scripts.sw_file_rename import collect_entries, plan_renames
from scripts.sw_part import extrude_boss, extrude_cut, sketch, sketch_circle, sketch_rectangle
from scripts.sw_review import collect_geometry_measurements, run_review
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch
from scripts.sw_tolerance_extract import extract_tolerances


def load_panel_module():
    path = ROOT / "subskills/solidworks-engineering-drawing/scripts/drilling_panel_gdt.py"
    spec = importlib.util.spec_from_file_location("drilling_panel_gdt_live", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def set_test_tolerance(model):
    """仅在本次创建的测试件上设置已知双向公差。"""
    def optional(owner, name, *args):
        try:
            return get_com_member(owner, name, *args)
        except Exception:
            return None

    feature = optional(model, "FirstFeature")
    for _ in range(250):
        if feature is None:
            break
        display = optional(feature, "GetFirstDisplayDimension5") or optional(feature, "GetFirstDisplayDimension")
        dimension = optional(display, "GetDimension2", 0) if display else None
        if dimension is not None:
            tolerance = optional(dimension, "Tolerance")
            if tolerance is None:
                raise RuntimeError("测试尺寸没有公差对象")
            tolerance.Type = 2  # swTolBILAT
            # SW2026 实测 SetValues2 在此尺寸返回 false；先验证旧 API 返回值。
            if not tolerance.SetValues(-0.00005, 0.0001):
                raise RuntimeError("无法设置测试公差")
            return
        feature = optional(feature, "GetNextFeature")
    raise RuntimeError("未找到可设置的测试尺寸")


def main():
    panel = load_panel_module()
    output = Path(tempfile.mkdtemp(prefix="sw_pr36_live_"))
    model_path = output / "test_plate.sldprt"
    coordinates = [(-20, -15), (20, -15), (-20, 15), (20, 15)]

    with SolidWorksSession(version=2026, visible=True) as session:
        before = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_rectangle(model, 0, 0, mm(80), mm(60))
            fully_define_sketch(model)
        if extrude_boss(model, ref, mm(20), direction=False) is None:
            raise RuntimeError("基体拉伸失败")
        with sketch(model, "Front Plane") as ref:
            for x, y in coordinates:
                sketch_circle(model, mm(x), mm(y), mm(5))
            fully_define_sketch(model)
        if extrude_cut(model, ref, 0, direction=True) is None:
            raise RuntimeError("四孔切除失败")
        set_test_tolerance(model)
        if not set_custom_properties(model, {"part_no": "demo_001"})["success"]:
            raise RuntimeError("测试属性写入或回读失败")
        if not session.save(model, str(model_path)):
            raise RuntimeError("保存测试件失败")
        session.close(model=model)
        model = session.open(str(model_path), read_only=True, silent=True)
        original_title = str(get_com_member(model, "GetTitle") or "")
        with SolidWorksSession(version=2026, visible=True) as reader:
            entries = collect_entries(reader, output, ["part_no"])
            plan = plan_renames(entries, "{part_no}")
            if len(plan) != 1 or plan[0]["new_name"].casefold() != "demo_001.sldprt" or plan[0]["status"] != "planned":
                raise AssertionError(f"改名预览不符: {plan}")
        if original_title not in [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]:
            raise AssertionError("改名预览关闭了此前打开的模型")
        measured = collect_geometry_measurements(model)
        if measured.get("errors"):
            raise RuntimeError(f"B-Rep 回读失败: {measured['errors']}")
        tolerance_report = extract_tolerances(model)
        bilateral = [row for row in tolerance_report["rows"] if row["tolerance_type"] == "bilateral"]
        if len(bilateral) != 1 or abs(bilateral[0]["upper"] - 0.1) > 1e-8 or abs(bilateral[0]["lower"] + 0.05) > 1e-8:
            raise AssertionError(f"公差回读不符: {bilateral}")
        snapshot = panel.snapshot_holes_from_model(model)
        holes = snapshot["holes"]
        actual = {(round(h.x, 2), round(h.y, 2), round(h.diameter, 2)) for h in holes}
        expected = {(float(x), float(y), 10.0) for x, y in coordinates}
        if len(holes) != 4 or actual != expected:
            raise AssertionError(f"孔径或孔位不符: {actual}")
        candidate = panel.analyze_model(model)
        if candidate["status"] != "review_required" or candidate["analysis"]["gdt"]:
            raise AssertionError("候选分析错误地声明通过或猜测公差")
        if not any("近似包围盒" in text for text in candidate["analysis"]["limitations"]):
            raise AssertionError("未标明 GetPartBox 的近似边界限制")
        if Path(candidate["drawingSpec"]["sourceModel"]).resolve() != model_path.resolve():
            raise AssertionError("候选规格引用了错误的模型")
        document = {
            "documentId": "live-plate", "units": "mm",
            "features": [{"id": hole.id, "type": "hole", "parameters": {
                "diameter": hole.diameter, "x": hole.x, "y": hole.y,
                "edgeDistance": min(40 - abs(hole.x), 30 - abs(hole.y)),
            }} for hole in holes],
        }
        report = build_drc_report(document)
        if report["status"] not in ("review_required", "warning") or report["summary"]["fail"]:
            raise AssertionError(f"DRC 结果异常: {report['summary']}")
        review, review_path = run_review(model, str(output / "review"), basename="plate", expected_outputs=[str(model_path)])
        if review.get("evaluation", {}).get("status") != "pass":
            raise AssertionError("测试件自动审查未通过")
        session.close(model=model)
        after = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        if any(title not in after for title in before):
            raise AssertionError("用户已有文档消失")
        print(json.dumps({
            "test_dir": str(output), "existing_documents_preserved": len(before),
            "holes": sorted(actual), "normal_axis": snapshot["normalAxis"],
            "drc_status": report["status"], "review_status": review.get("evaluation", {}).get("status"),
            "linear_tolerance_mm": {"lower": bilateral[0]["lower"], "upper": bilateral[0]["upper"]},
            "rename_preview": plan[0]["new_name"],
            "review_report": str(review_path),
        }, ensure_ascii=True))


if __name__ == "__main__":
    main()
