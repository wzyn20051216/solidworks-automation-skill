"""从三维零件与 DrawingSpec 自动出图，真实核验尺寸、基本尺寸、复合框及基准修饰。"""
import json
from pathlib import Path
import sys
import tempfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, extrude_boss, extrude_cut
from scripts.sw_session import SolidWorksSession
from scripts.sw_drawing_package import generate_package
from scripts.sw_rename_copy import _sha256
from solidworks_week4_drawing_regression import _sheet_format_candidates


def specification(source):
    line = lambda a, b: {"kind": "line", "startMm": a, "endMm": b}
    circle = lambda x, y: {"kind": "circle", "centerMm": [x, y, 20], "radiusMm": 5}
    left = line([-40, 30, 20], [-40, -30, 20])
    bottom = line([-40, -30, 20], [40, -30, 20])
    rows = [
        {"id": "WIDTH", "kind": "overall", "view": "front", "axis": "horizontal", "valueMm": 80, "positionMm": [240, 120], "target": bottom},
        {"id": "HEIGHT", "kind": "overall", "view": "front", "axis": "vertical", "valueMm": 60, "positionMm": [320, 190], "target": left},
        {"id": "HOLES", "kind": "diameter", "view": "front", "valueMm": 10, "positionMm": [275, 242], "target": circle(20, 15), "prefix": "4X "},
        {"id": "PITCH_X", "kind": "linear", "view": "front", "axis": "horizontal", "valueMm": 40, "positionMm": [240, 135], "targets": [circle(-20, -15), circle(20, -15)], "basic": True},
        {"id": "PITCH_Y", "kind": "linear", "view": "front", "axis": "vertical", "valueMm": 30, "positionMm": [305, 190], "targets": [circle(-20, -15), circle(-20, 15)], "basic": True},
        {"id": "ORIGIN_X", "kind": "linear", "view": "front", "axis": "horizontal", "valueMm": 20, "positionMm": [240, 148], "targets": [left, circle(-20, -15)], "basic": True},
        {"id": "ORIGIN_Y", "kind": "linear", "view": "front", "axis": "vertical", "valueMm": 15, "positionMm": [292, 190], "targets": [bottom, circle(-20, -15)], "basic": True},
        {"id": "THICKNESS", "kind": "linear", "view": "right", "axis": "horizontal", "valueMm": 20, "positionMm": [140, 235], "target": line([-40, 30, 0], [-40, 30, 20])},
    ]
    frame = {"characteristic": "position", "tolerance": "0.2", "diameter": True,
             "datums": [{"label": "A", "materialCondition": "M"}]}
    return {"schemaVersion": "1.0", "sourceModel": str(source), "documentType": "part", "standard": "GB_T",
            "projection": "first_angle", "paperSize": "A3", "modelSizeMm": [80, 60, 20], "scale": "1:1",
            "views": {"front": {"positionMm": [240, 190]}, "top": {"positionMm": [240, 85]}, "right": {"positionMm": [140, 190]}},
            "templateCandidates": _sheet_format_candidates(), "insertModelDimensions": False, "requiredDimensions": rows,
            "professionalAnnotations": {"centerMarks": [{"id": "CENTERS", "view": "front", "count": 4, "targets": ["holes"]}],
                                        "datums": [{"id": "DAT_A", "view": "front", "label": "A", "displayStyle": "square", "positionMm": [185, 160], "target": left}],
                                        "geometricTolerances": [{"id": "GDT_POSITION", "view": "front", "target": {"kind": "dimension", "dimensionId": "HOLES"},
                                                                 "frames": [frame, {**frame, "tolerance": "0.1", "composite": True}]}]},
            "outputs": {"slddrw": True, "pdf": True, "bmp": True, "report": True}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="复用本测试先前生成的四孔板，仍只读打开")
    parser.add_argument("--paper-size", choices=("A3", "A2"), default="A3")
    parser.add_argument("--mcp", action="store_true", help="通过现有 MCP 工具的真实注册函数执行")
    parser.add_argument("--extra-dimensions", action="store_true", help="额外验证半径和两边夹角的原生尺寸")
    parser.add_argument("--extended-gdt", action="store_true", help="公共基准、投影公差带及不等轮廓/CZ 的自动落图回归")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="sw_gdt_generation_"))
    source = root / (root.name + ".sldprt")
    with SolidWorksSession(version=2026, visible=True) as session:
        if args.source:
            from scripts.sw_rename_copy import _open_checked
            source = args.source.resolve(strict=True)
            model = _open_checked(session, source)
        else:
            model = session.new_part()
            with sketch(model, "Front Plane") as ref:
                sketch_rectangle(model, 0, 0, .08, .06)
            assert extrude_boss(model, ref, .02, direction=False)
            with sketch(model, "Front Plane") as ref:
                for x, y in ((-.02, -.015), (.02, -.015), (-.02, .015), (.02, .015)):
                    sketch_circle(model, x, y, .005)
            assert extrude_cut(model, ref, 0, direction=True)
            assert session.save(model, str(source))
        digest = _sha256(source)
        spec = specification(source)
        if args.extended_gdt:
            annotations = spec["professionalAnnotations"]
            annotations["datums"].append({"id": "DAT_B", "view": "front", "label": "B", "displayStyle": "square", "positionMm": [335, 160],
                                          "target": {"kind": "line", "startMm": [40, -30, 20], "endMm": [40, 30, 20]}})
            for frame in annotations["geometricTolerances"][0]["frames"]:
                frame["datums"] = [{"common": [{"label": "A", "materialCondition": "M"}, "B"]}]
                frame["options"] = {"projectedZone": {"projection": "12"}}
            annotations["geometricTolerances"].append({"id": "GDT_PROFILE", "view": "front", "characteristic": "surface_profile", "tolerance": "0.2", "diameter": False, "datums": ["A"],
                                                       "target": {"kind": "circle", "centerMm": [-20, 15, 20], "radiusMm": 5}, "positionMm": [170, 260],
                                                       "options": {"profileZone": {"unequalOutside": "0.05", "combination": "CZ"}}})
        if args.extra_dimensions:
            spec["requiredDimensions"].extend([
                {"id": "RADIUS", "kind": "radius", "view": "front", "valueMm": 5, "positionMm": [190, 242],
                 "target": {"kind": "circle", "centerMm": [-20, 15, 20], "radiusMm": 5}},
                {"id": "ANGLE", "kind": "angular", "view": "front", "valueDegrees": 90, "positionMm": [210, 170],
                 "targets": [spec["requiredDimensions"][0]["target"], spec["requiredDimensions"][1]["target"]]},
            ])
        spec["paperSize"] = args.paper_size
        if args.paper_size != "A3":
            parents = {Path(path).parent for path in spec["templateCandidates"]}
            spec["templateCandidates"] = sorted({str(path) for parent in parents for path in parent.glob(args.paper_size.lower() + "*.slddrt")})
        (root / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.mcp:
            sys.path.insert(0, str(ROOT / "mcp-server"))
            import server
            result = json.loads(server.solidworks_generate_drawing(server.SolidWorksGenerateDrawingInput(
                spec_path=str(root / "spec.json"), output_dir=str(root / "delivery"), drawing_filename="generated.slddrw")))
        else:
            result = generate_package(spec, root / "delivery", "generated.slddrw")
        print(json.dumps({"status": result["status"], "native": result.get("native_validation"), "error": result.get("message"),
                          "review": (result.get("review") or {}).get("status"), "findings": (result.get("review") or {}).get("findings"),
                          "report": result.get("reportPath")}, ensure_ascii=False, indent=2), flush=True)
        assert result["status"] == "review_required" and result.get("native_validation") == "pass", result.get("reportPath") or result.get("message")
        assert result["review"]["status"] == "pass", result.get("reportPath")
        assert result["generation"]["structure"]["dimension_count"] == (10 if args.extra_dimensions else 8)
        assert _sha256(source) == digest
        print("generic GD&T generation PASS", root, flush=True)


if __name__ == "__main__":
    main()
