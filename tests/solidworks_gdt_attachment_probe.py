"""SW2026 工程图真实边线关联与标注保存试验。"""
from pathlib import Path
import sys
import tempfile
import argparse
import json
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import get_com_member
from scripts.sw_session import SolidWorksSession
from scripts.sw_drawing import create_adaptive_standard_views, plan_standard_view_layout, export_sheet_to_pdf, setup_current_sheet_as_a3, insert_dimensions, inspect_drawing_structure
from scripts.sw_review import save_review_previews, inspect_bmp_preview, review_drawing_layout
from scripts import sw_drawing_review
from scripts.sw_gdt_annotation import insert_datum, insert_gtol, build_frame_xml
from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, auto_dimension_sketch, extrude_boss, extrude_cut
from solidworks_week4_drawing_regression import _sheet_format_candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--copy-workflow", action="store_true", help="验证副本执行入口及失败隔离")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="sw_gdt_attachment_probe_"))
    part = root / "part.sldprt"
    with SolidWorksSession(version=2026, visible=True) as session:
        part_model = session.new_part()
        with sketch(part_model, "Front Plane") as ref:
            segments = sketch_rectangle(part_model, 0, 0, .08, .06)
            print("model dimensions", auto_dimension_sketch(part_model, sketch_segments=segments), flush=True)
        if not extrude_boss(part_model, ref, .02, direction=False):
            raise RuntimeError("测试板拉伸失败")
        with sketch(part_model, "Front Plane") as holes:
            for x, y in ((-.02, -.015), (.02, -.015), (-.02, .015), (.02, .015)):
                sketch_circle(part_model, x, y, .005)
        if not extrude_cut(part_model, holes, 0, direction=True) or not session.save(part_model, str(part)):
            raise RuntimeError("测试孔或零件保存失败")
        get_com_member(part_model, "ShowFeatureDimensions")
        drawing = session.new_drawing()
        setup = setup_current_sheet_as_a3(drawing, _sheet_format_candidates(), require_gbt=True)
        if setup.get("status") != "pass":
            raise RuntimeError(f"A3 图纸设置失败: {setup}")
        layout = plan_standard_view_layout((.08, .06, .02), paper_size="A3")
        created = create_adaptive_standard_views(drawing, str(part), layout)
        if created.get("status") != "pass":
            raise RuntimeError(f"视图创建失败: {created}")
        path = root / "attachment.slddrw"
        if not session.save(drawing, str(path)):
            raise RuntimeError("图纸首次保存失败")
        # 为避免重复，仅针对明确识别的边线创建尺寸。
        record = next(item for item in created["views"] if item["name"] == "*Front")
        sheet = get_com_member(drawing, "GetCurrentSheet")
        # 增加上视图与主视图之间的空间，留给孔径及其关联公差框。
        top_record = next(item for item in created["views"] if item["name"] == "*Top")
        top_view = next(item for item in get_com_member(sheet, "GetViews") if get_com_member(item, "Name") == top_record["actual_name"])
        top_position = list(get_com_member(top_view, "Position"))
        top_position[1] += .025
        import pythoncom
        from win32com.client import VARIANT
        top_view.Position = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, top_position)
        if abs(get_com_member(top_view, "Position")[1] - top_position[1]) > 1e-7:
            raise AssertionError("上视图移动未生效")
        view = next(item for item in get_com_member(sheet, "GetViews") if get_com_member(item, "Name") == record["actual_name"])
        name = str(get_com_member(view, "Name"))
        get_com_member(drawing, "ActivateView", name)
        components = get_com_member(view, "GetVisibleComponents") or []
        print("view", name, "components", len(components), flush=True)
        edges = get_com_member(view, "GetVisibleEntities2", components[0], 1) or []
        print("edges", len(edges), flush=True)
        circles = [edge for edge in edges if get_com_member(get_com_member(edge, "GetCurve"), "IsCircle")]
        lines = [edge for edge in edges if get_com_member(get_com_member(edge, "GetCurve"), "IsLine")]
        if len(circles) < 4 or not lines:
            raise RuntimeError(f"无法识别四孔和基准边: 圆={len(circles)} 线={len(lines)}")
        for line in lines:
            print("edge vertices", get_com_member(get_com_member(line, "GetStartVertex"), "GetPoint"), get_com_member(get_com_member(line, "GetEndVertex"), "GetPoint"), flush=True)
        for circle in circles:
            print("circle params", get_com_member(get_com_member(circle, "GetCurve"), "CircleParams"), flush=True)
        selection = get_com_member(drawing, "SelectionManager")
        data = get_com_member(selection, "CreateSelectData")
        data.View = view
        outline = get_com_member(view, "GetOutline")
        print("view outline", outline, flush=True)
        vertical = next(line for line in lines if abs(abs(get_com_member(get_com_member(line, "GetStartVertex"), "GetPoint")[1] - get_com_member(get_com_member(line, "GetEndVertex"), "GetPoint")[1]) - .06) < 1e-7)
        horizontal = next(line for line in lines if abs(abs(get_com_member(get_com_member(line, "GetStartVertex"), "GetPoint")[0] - get_com_member(get_com_member(line, "GetEndVertex"), "GetPoint")[0]) - .08) < 1e-7)
        for kind, edge, method, position, expected in (
            ("width", horizontal, "AddHorizontalDimension2", ((outline[0] + outline[2]) / 2, outline[1] - .04), .08),
            ("height", vertical, "AddVerticalDimension2", (outline[0] - .04, (outline[1] + outline[3]) / 2), .06),
            ("hole_diameter", circles[1], "AddDiameterDimension2", (outline[2] - .005, outline[3] + .022), .01),
        ):
            get_com_member(drawing, "ClearSelection2", True)
            if not get_com_member(edge, "Select4", False, data):
                raise RuntimeError(f"{kind} 边线选择失败")
            display = get_com_member(drawing, method, *position, 0.0)
            if display is None:
                raise RuntimeError(f"{kind} 尺寸创建失败")
            value = get_com_member(get_com_member(display, "GetDimension2", 0), "SystemValue")
            print("manual dimension", kind, value, flush=True)
            if abs(value - expected) > 1e-8:
                raise AssertionError(f"{kind} 尺寸错误: {value}")
            if kind == "hole_diameter":
                get_com_member(display, "SetText", 1, "4X ")
                if "4X" not in str(get_com_member(display, "GetText", 1) or ""):
                    raise AssertionError("孔数量前缀回读失败")
                hole_dimension = display
        ordered = sorted(circles, key=lambda edge: tuple(get_com_member(get_com_member(edge, "GetCurve"), "CircleParams")[i] for i in (1, 0)))
        left = next(line for line in lines if all(abs(get_com_member(get_com_member(line, vertex), "GetPoint")[0] + .04) < 1e-7 for vertex in ("GetStartVertex", "GetEndVertex")))
        bottom = next(line for line in lines if all(abs(get_com_member(get_com_member(line, vertex), "GetPoint")[1] + .03) < 1e-7 for vertex in ("GetStartVertex", "GetEndVertex")))
        for kind, pair, method, position, expected in (
            ("horizontal_pitch", (ordered[0], ordered[1]), "AddHorizontalDimension2", ((outline[0] + outline[2]) / 2, outline[1] - .025), .04),
            ("vertical_pitch", (ordered[0], ordered[2]), "AddVerticalDimension2", (outline[0] - .025, (outline[1] + outline[3]) / 2), .03),
            ("horizontal_origin", (left, ordered[0]), "AddHorizontalDimension2", ((outline[0] + outline[2]) / 2, outline[1] - .012), .02),
            ("vertical_origin", (bottom, ordered[0]), "AddVerticalDimension2", (outline[0] - .012, (outline[1] + outline[3]) / 2), .015),
        ):
            get_com_member(drawing, "ClearSelection2", True)
            if not get_com_member(pair[0], "Select4", False, data) or not get_com_member(pair[1], "Select4", True, data):
                raise RuntimeError(f"{kind} 孔边选择失败")
            display = get_com_member(drawing, method, *position, 0.0)
            if display is None:
                raise RuntimeError(f"{kind} 尺寸创建失败")
            value = get_com_member(get_com_member(display, "GetDimension2", 0), "SystemValue")
            print("manual dimension", kind, value, flush=True)
            if abs(value - expected) > 1e-8:
                raise AssertionError(f"{kind} 尺寸错误: {value}")
        right_record = next(item for item in created["views"] if item["name"] == "*Right")
        right = next(item for item in get_com_member(sheet, "GetViews") if get_com_member(item, "Name") == right_record["actual_name"])
        get_com_member(drawing, "ActivateView", get_com_member(right, "Name"))
        right_component = (get_com_member(right, "GetVisibleComponents") or [])[0]
        right_edges = get_com_member(right, "GetVisibleEntities2", right_component, 1) or []
        thickness_edge = next(edge for edge in right_edges if get_com_member(get_com_member(edge, "GetCurve"), "IsLine") and abs(abs(get_com_member(get_com_member(edge, "GetStartVertex"), "GetPoint")[2] - get_com_member(get_com_member(edge, "GetEndVertex"), "GetPoint")[2]) - .02) < 1e-7)
        right_data = get_com_member(selection, "CreateSelectData")
        right_data.View = right
        get_com_member(drawing, "ClearSelection2", True)
        if not get_com_member(thickness_edge, "Select4", False, right_data):
            raise RuntimeError("厚度边线选择失败")
        right_outline = get_com_member(right, "GetOutline")
        thickness = get_com_member(drawing, "AddHorizontalDimension2", (right_outline[0] + right_outline[2]) / 2, right_outline[3] + .015, 0.0)
        if thickness is None or abs(get_com_member(get_com_member(thickness, "GetDimension2", 0), "SystemValue") - .02) > 1e-8:
            raise AssertionError("板厚尺寸不正确")
        print("manual dimension thickness 0.02", flush=True)
        if args.copy_workflow:
            from scripts.sw_gdt_copy import annotate_copy, inspect_targets
            from scripts.sw_rename_copy import _sha256
            if not session.save(drawing, str(path)):
                raise RuntimeError("副本测试源保存失败")
            plan = {"schemaVersion": "1.0", "sourceSha256": _sha256(path), "sheet": get_com_member(sheet, "GetName"), "paperSize": "A3",
                    "datums": [{"id": "DAT-A", "view": name, "label": "A", "positionMm": [235, 126], "displayStyle": "square",
                                "target": {"kind": "line", "startMm": [40, -30, 20], "endMm": [40, 30, 20]}}],
                    "geometricTolerances": [{"id": "G-POS", "view": name, "characteristic": "position", "tolerance": "0.2", "diameter": True,
                                             "datums": ["A"], "target": {"kind": "dimension", "name": get_com_member(hole_dimension, "GetNameForSelection"), "systemValue": .01}}]}
            (root / "gdt-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            session.close(model=drawing)
            inspected = inspect_targets(path)
            assert inspected["sourceSha256"] == plan["sourceSha256"] and inspected["sheet"] == plan["sheet"]
            found_view = next(row for row in inspected["views"] if row["view"] == name)
            requested_dimension = plan["geometricTolerances"][0]["target"]
            assert sum(item["kind"] == "dimension" and item["name"] == requested_dimension["name"]
                       and abs(item["systemValue"] - .01) < 1e-8 for item in found_view["targets"]) == 1
            result = annotate_copy(path, plan, root / "annotated")
            print("copy workflow", json.dumps(result, ensure_ascii=False), flush=True)
            if result["status"] != "review_required" or result.get("annotationCount") != 2 or result.get("nativeValidation") != "pass":
                raise AssertionError("原生 GD&T 副本执行器未通过")
            missing = deepcopy(plan)
            missing["geometricTolerances"][0]["target"]["name"] = "nonexistent@view"
            blocked = annotate_copy(path, missing, root / "missing-target")
            assert blocked["status"] == "blocked" and not (root / "missing-target").exists()
            failed = deepcopy(plan)
            failed["datums"][0]["positionMm"] = [70, 100]
            failure = annotate_copy(path, failed, root / "invalid-position")
            assert failure["status"] == "blocked" and not failure["outputs"]
            assert "实际位置" in failure["error"]
            isolated = list((root / "invalid-position").glob("*.slddrw"))
            assert len(isolated) == 1 and _sha256(isolated[0]) == plan["sourceSha256"]
            assert _sha256(path) == plan["sourceSha256"]
            print("copy workflow and failure isolation PASS", root, flush=True)
            return
        xml = build_frame_xml("position", "0.2", True, ["A"])
        target_refs = {}
        for action, edge in (("datum", lines[0]), ("gtol", hole_dimension)):
            if action == "datum":
                obj = insert_datum(drawing, view, edge, session.sw, "A", (.141, .1))
            else:
                obj = insert_gtol(drawing, view, edge, session.sw, characteristic="position", tolerance="0.2", diameter=True, datums=["A"], target_kind="dimension")
            if obj:
                ann = get_com_member(obj, "GetAnnotation")
                count = get_com_member(ann, "GetAttachedEntityCount3")
                attached = get_com_member(ann, "GetAttachedEntities3") or ()
                print("attachment", action, count, attached, flush=True)
                if count != 1 or len(attached) != 1 or attached[0] is None or session.sw.IsSame(edge, attached[0]) != 1:
                    raise RuntimeError("标注没有可靠的边线关联")
                print("annotation position", action, get_com_member(ann, "GetPosition"), flush=True)
                target_refs[action] = get_com_member(get_com_member(drawing, "Extension"), "GetPersistReference3", attached[0])
                if not target_refs[action]:
                    raise RuntimeError("不能持久化目标边线引用")
        if not session.save(drawing, str(path)):
            raise RuntimeError("保存失败")
        pdf = root / "attachment.pdf"
        if not export_sheet_to_pdf(drawing, str(pdf), sw_app=session.sw):
            raise RuntimeError("导出 PDF 失败")
        previews = save_review_previews(drawing, root / "previews", basename="drawing", views=("front",))
        session.close(model=drawing)
        drawing = session.open(str(path), read_only=True, silent=True)
        structure = inspect_drawing_structure(drawing, paper_size_hint="A3", title_block_box=layout.get("title_block_box"))
        print("dimension count", structure.get("dimension_count"), flush=True)
        rendering = sw_drawing_review.inspect_pdf_dimension_rendering(pdf, structure)
        print("pdf dimensions", rendering.get("status"), rendering.get("error_code"), flush=True)
        if rendering.get("status") != "pass":
            raise AssertionError(f"PDF 尺寸文字核验未通过: {rendering.get('unmatched_dimension_indexes')}")
        rendered = sw_drawing_review._MODULE._with_rendered_dimension_boxes(structure, rendering)
        layout_report = review_drawing_layout(rendered, preview_evidence=[inspect_bmp_preview(item) for item in previews])
        print("drawing layout", layout_report.get("status"), layout_report.get("error_code"), layout_report.get("findings"), flush=True)
        if layout_report.get("status") != "pass":
            raise AssertionError("工程图布局未通过")
        sheet = get_com_member(drawing, "GetCurrentSheet")
        datums, gtols = [], []
        for view in get_com_member(sheet, "GetViews") or ():
            datums.extend(get_com_member(view, "GetDatumTags") or ())
            gtols.extend(get_com_member(view, "GetGTols") or ())
        assert len(datums) == 1 and get_com_member(datums[0], "GetLabel") == "A"
        assert get_com_member(datums[0], "GetDisplayStyle") == 1
        assert len(gtols) == 1
        for action, obj in (("datum", datums[0]), ("gtol", gtols[0])):
            ann = get_com_member(obj, "GetAnnotation")
            attached = get_com_member(ann, "GetAttachedEntities3") or ()
            assert get_com_member(ann, "GetAttachedEntityCount3") == 1 and len(attached) == 1 and attached[0] is not None
            extension = get_com_member(drawing, "Extension")
            actual_ref = get_com_member(extension, "GetPersistReference3", attached[0])
            if hasattr(extension, "_FlagAsMethod"):
                extension._FlagAsMethod("IsSamePersistentID")
            if extension.IsSamePersistentID(target_refs[action], actual_ref) != 1:
                raise AssertionError(f"{action} 重开后关联到不同实体")
        assert get_com_member(gtols[0], "GetFrameCount") == 1
        assert get_com_member(get_com_member(gtols[0], "GetFrame", 1), "GetSymbolXml") == xml
        print("saved and reopened attached GTol", path, pdf, flush=True)


if __name__ == "__main__":
    main()
