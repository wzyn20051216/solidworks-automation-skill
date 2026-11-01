"""将明确的基准和形位公差写入全新工程图副本；源文件保持不变。"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sys

if not __package__:
    # 直接按脚本运行时也要让子技能的动态加载器找到同一份 scripts 包。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sw_connect import get_com_member
from scripts.sw_gdt_annotation import build_frame_xml, insert_datum, insert_gtol
from scripts.sw_read_guard import SolidWorksReadGuard
from scripts.sw_rename_copy import _open_checked, _sha256
from scripts.sw_session import SolidWorksSession

SCHEMA = Path(__file__).resolve().parents[1] / "subskills/solidworks-engineering-drawing/schemas/gdt_copy_spec.schema.json"


def inspect_targets(source):
    """只读列出计划可用的真实目标及源哈希，供自然语言任务构建明确计划。"""
    source = Path(source).expanduser().resolve(strict=True)
    if source.suffix.casefold() != ".slddrw":
        raise ValueError("必须提供 SLDDRW")
    digest = _sha256(source)
    with SolidWorksReadGuard(), SolidWorksSession(version=2026, visible=True) as session:
        drawing = _open_checked(session, source)
        if get_com_member(drawing, "GetSaveFlag") not in (False, 0):
            raise ValueError("图纸存在未保存修改")
        sheet = get_com_member(drawing, "GetCurrentSheet")
        result = {"sourceSha256": digest, "sheet": get_com_member(sheet, "GetName"), "views": []}
        for view in get_com_member(sheet, "GetViews") or ():
            components = get_com_member(view, "GetVisibleComponents") or ()
            if not components:
                continue
            if len(components) != 1:
                raise ValueError("只支持单零件视图")
            row = {"view": str(get_com_member(view, "Name")), "targets": []}
            for dimension in get_com_member(view, "GetDisplayDimensions") or ():
                row["targets"].append({"kind": "dimension", "name": str(get_com_member(dimension, "GetNameForSelection")),
                                       "systemValue": get_com_member(get_com_member(dimension, "GetDimension2", 0), "SystemValue")})
            for edge in get_com_member(view, "GetVisibleEntities2", components[0], 1) or ():
                curve = get_com_member(edge, "GetCurve")
                if get_com_member(curve, "IsLine"):
                    start, end = get_com_member(edge, "GetStartVertex"), get_com_member(edge, "GetEndVertex")
                    if start is not None and end is not None:
                        row["targets"].append({"kind": "line", "startMm": [1000 * value for value in get_com_member(start, "GetPoint")],
                                               "endMm": [1000 * value for value in get_com_member(end, "GetPoint")]})
                elif get_com_member(curve, "IsCircle"):
                    values = get_com_member(curve, "CircleParams")
                    row["targets"].append({"kind": "circle", "centerMm": [1000 * value for value in values[:3]], "radiusMm": 1000 * values[6]})
            if len(row["targets"]) > 500:
                raise ValueError("单个视图超过 500 个目标，请使用专项脚本")
            result["views"].append(row)
        if _sha256(source) != digest:
            raise RuntimeError("只读检查期间源文件变化")
        return result


def validate_plan(plan):
    """在接触 COM 和创建输出前校验全部字段及互斥关系。"""
    import jsonschema
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(plan)
    # JSON Schema number 不排除 NaN/Infinity；拒绝所有非标准 JSON 数值。
    json.dumps(plan, allow_nan=False)
    rows = [*plan["datums"], *plan["geometricTolerances"]]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("计划不能为空，且标注 ID 不得重复")
    labels = [row["label"] for row in plan["datums"]]
    if len(set(labels)) != len(labels):
        raise ValueError("计划中的基准标识重复")
    for row in plan["datums"]:
        if row["target"]["kind"] == "dimension":
            raise ValueError("基准当前只支持明确的边线目标")
    for row in plan["geometricTolerances"]:
        build_frame_xml(row["characteristic"], row["tolerance"], row["diameter"], row["datums"], material_condition=row.get("materialCondition"))
        if (row["target"]["kind"] == "dimension") == ("positionMm" in row):
            raise ValueError("尺寸关联公差自动定位；边线关联公差必须指定位置")
    return plan


def _near(a, b):
    return len(a) == len(b) and all(math.isfinite(float(x)) and math.isclose(float(x), float(y), rel_tol=0, abs_tol=1e-8) for x, y in zip(a, b))


def resolve_target(view, target):
    """精确匹配当前视图中的名称/数值或模型坐标；不使用 Edge1、最近点或模糊评分。"""
    kind = target["kind"]
    candidates = []
    if kind == "dimension":
        for dimension in get_com_member(view, "GetDisplayDimensions") or ():
            if str(get_com_member(dimension, "GetNameForSelection") or "") != target["name"]:
                continue
            value = get_com_member(get_com_member(dimension, "GetDimension2", 0), "SystemValue")
            if isinstance(value, (float, int)) and not isinstance(value, bool) and _near([value], [target["systemValue"]]):
                candidates.append(dimension)
    else:
        components = get_com_member(view, "GetVisibleComponents") or ()
        if len(components) != 1:
            raise ValueError("只支持单个零件的视图，不能猜测组件")
        for edge in get_com_member(view, "GetVisibleEntities2", components[0], 1) or ():
            curve = get_com_member(edge, "GetCurve")
            if kind == "line" and get_com_member(curve, "IsLine"):
                start_vertex, end_vertex = get_com_member(edge, "GetStartVertex"), get_com_member(edge, "GetEndVertex")
                if start_vertex is None or end_vertex is None:
                    continue
                a, b = get_com_member(start_vertex, "GetPoint"), get_com_member(end_vertex, "GetPoint")
                start, end = [v / 1000 for v in target["startMm"]], [v / 1000 for v in target["endMm"]]
                if _near(start, end):
                    raise ValueError("线段端点不能重合")
                if (_near(a, start) and _near(b, end)) or (_near(a, end) and _near(b, start)):
                    candidates.append(edge)
            elif kind == "circle" and get_com_member(curve, "IsCircle"):
                values = get_com_member(curve, "CircleParams")
                if _near(values[:3], [v / 1000 for v in target["centerMm"]]) and _near([values[6]], [target["radiusMm"] / 1000]):
                    candidates.append(edge)
    if len(candidates) != 1:
        raise ValueError(f"目标不能唯一确认：{kind}，候选数 {len(candidates)}")
    return candidates[0]


def _persistent_id(extension, entity):
    value = get_com_member(extension, "GetPersistReference3", entity)
    if not isinstance(value, (bytes, memoryview, list, tuple)) or not value:
        raise ValueError("对象不支持可靠的持久引用")
    return bytes(value)


def _same_id(extension, before, after):
    if hasattr(extension, "_FlagAsMethod"):
        extension._FlagAsMethod("IsSamePersistentID")
    return get_com_member(extension, "IsSamePersistentID", memoryview(before), memoryview(after)) == 1


def _resolve_plan(drawing, plan):
    sheet = get_com_member(drawing, "GetCurrentSheet")
    if str(get_com_member(sheet, "GetName")) != plan["sheet"]:
        raise ValueError("计划的图纸页与当前页不一致")
    properties = get_com_member(sheet, "GetProperties2")
    if not isinstance(properties, (list, tuple)) or len(properties) != 8 or not _near(properties[5:7], [.420, .297]):
        raise ValueError("当前图幅不是已验证的横向 A3")
    units = get_com_member(drawing, "GetUnits")
    if not isinstance(units, (list, tuple)) or not units or units[0] != 0:  # swMM
        raise ValueError("此入口要求图纸使用毫米单位")
    views = get_com_member(sheet, "GetViews") or ()
    labels = []
    for view in views:
        labels.extend(str(get_com_member(tag, "GetLabel")) for tag in get_com_member(view, "GetDatumTags") or ())
    requested_labels = [row["label"] for row in plan["datums"]]
    if len(labels) != len(set(labels)) or set(labels) & set(requested_labels):
        raise ValueError("图纸或计划包含重名基准，无法确认引用")
    available = set(labels) | set(requested_labels)
    resolved = []
    extension = get_com_member(drawing, "Extension")
    for kind, rows in (("datum", plan["datums"]), ("gtol", plan["geometricTolerances"])):
        for row in rows:
            matching = [view for view in views if str(get_com_member(view, "Name") or "") == row["view"]]
            if len(matching) != 1:
                raise ValueError("视图名称不唯一或不存在：" + row["view"])
            if kind == "gtol" and not set(row["datums"]) <= available:
                raise ValueError("公差引用了不存在的基准")
            target = resolve_target(matching[0], row["target"])
            resolved.append((kind, row, matching[0], target, _persistent_id(extension, target)))
    return resolved


def _verify_reopened(drawing, records):
    extension = get_com_member(drawing, "Extension")
    views = get_com_member(get_com_member(drawing, "GetCurrentSheet"), "GetViews") or ()
    for record in records:
        kind, row = record["kind"], record["request"]
        candidates = []
        for view in views:
            if str(get_com_member(view, "Name")) == row["view"]:
                for obj in get_com_member(view, "GetDatumTags" if kind == "datum" else "GetGTols") or ():
                    ann = get_com_member(obj, "GetAnnotation")
                    if _same_id(extension, record["annotation_id"], _persistent_id(extension, ann)):
                        candidates.append(obj)
        if len(candidates) != 1:
            raise RuntimeError("重开后标注身份不一致：" + row["id"])
        obj = candidates[0]
        ann = get_com_member(obj, "GetAnnotation")
        attached = get_com_member(ann, "GetAttachedEntities3")
        if (get_com_member(ann, "GetAttachedEntityCount3") != 1 or not isinstance(attached, (tuple, list))
                or len(attached) != 1 or attached[0] is None
                or not _same_id(extension, record["target_id"], _persistent_id(extension, attached[0]))):
            raise RuntimeError("重开后目标关联不一致：" + row["id"])
        if kind == "datum":
            if get_com_member(obj, "GetLabel") != row["label"] or get_com_member(obj, "GetDisplayStyle") != (1 if row["displayStyle"] == "square" else 2):
                raise RuntimeError("重开后基准内容不一致")
        else:
            xml = build_frame_xml(row["characteristic"], row["tolerance"], row["diameter"], row["datums"], material_condition=row.get("materialCondition"))
            if get_com_member(obj, "GetFrameCount") != 1 or get_com_member(get_com_member(obj, "GetFrame", 1), "GetSymbolXml") != xml:
                raise RuntimeError("重开后公差框内容不一致")
        position = get_com_member(ann, "GetPosition")
        if not _near(position[:2], record["position"][:2]):
            raise RuntimeError(f"重开后标注位置不一致：{row['id']}，预期 {record['position'][:2]}，实际 {position[:2]}")


def _capture_saved_positions(records):
    """以重建和保存后的布局为重开基线，显式请求的位置仍须满足。"""
    for record in records:
        position = get_com_member(get_com_member(record["object"], "GetAnnotation"), "GetPosition")
        if not isinstance(position, (list, tuple)) or len(position) < 2 or not _near(position[:2], position[:2]):
            raise RuntimeError("保存后标注位置无效")
        requested = record["request"].get("positionMm")
        if requested is not None and not all(math.isclose(actual, intended / 1000, rel_tol=0, abs_tol=1e-6) for actual, intended in zip(position[:2], requested)):
            raise RuntimeError("保存后标注偏离显式请求位置")
        record["position"] = position


def annotate_copy(source, plan, output_dir):
    """只接受单页、单零件 A3 图纸；验证全部目标后才写入独立副本。"""
    validate_plan(plan)
    source = Path(source).expanduser().absolute()
    output = Path(output_dir).expanduser().absolute()
    if source.is_symlink() or not source.is_file() or source.suffix.casefold() != ".slddrw":
        raise ValueError("源文件必须是现有的非链接 SLDDRW")
    if _sha256(source) != plan["sourceSha256"]:
        raise ValueError("源图纸已经变化，必须重新生成计划")
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("输出目录必须不存在，且父目录必须存在")
    report = {"status": "blocked", "reviewRequired": True, "source": str(source), "outputs": [], "error": None,
              "limitations": ["仅 SW2026 的单页单零件 A3 图纸副本", "不求解设计公差，不证明制造或标准合规", "尺寸应事先完整，复合公差框和基准材料修饰尚未支持"]}
    created_dir = False
    try:
        with SolidWorksReadGuard(), SolidWorksSession(version=2026, visible=True) as session:
            original = _open_checked(session, source)
            if get_com_member(original, "GetType") != 3 or get_com_member(original, "GetSaveFlag") not in (False, 0):
                raise ValueError("源图纸存在未保存修改或类型无效")
            if len(get_com_member(original, "GetSheetNames") or ()) != 1:
                raise ValueError("当前入口只支持单页工程图")
            dependencies = get_com_member(original, "GetDependencies2", True, True, False)
            if not isinstance(dependencies, (list, tuple)) or len(dependencies) % 2 or not dependencies:
                raise ValueError("无法确认图纸模型依赖")
            refs = {Path(str(dependencies[index])).resolve(strict=True) for index in range(1, len(dependencies), 2)}
            if len(refs) != 1 or any(path.suffix.casefold() != ".sldprt" for path in refs):
                raise ValueError("只支持引用一个零件的图纸")
            source_hashes = {path: _sha256(path) for path in {source.resolve(), *refs}}
            for view in get_com_member(get_com_member(original, "GetCurrentSheet"), "GetViews") or ():
                model = get_com_member(view, "ReferencedDocument", default=None)
                if model is not None and (get_com_member(model, "GetSaveFlag") not in (False, 0)
                        or Path(str(get_com_member(model, "GetPathName") or "")).resolve() not in refs):
                    raise ValueError("模型未保存或模型引用身份不一致")
            _resolve_plan(original, plan)  # 全量预解析，任何歧义在创建目录前阻断。
            if any(item is original for item in session._owned_documents):
                session.close(model=original)
            output.mkdir(exist_ok=False)
            created_dir = True
            copy = output / ("gdt_" + output.name + ".slddrw")
            with source.open("rb") as reader, copy.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            if _sha256(copy) != plan["sourceSha256"]:
                raise RuntimeError("副本字节与计划不一致")
            drawing = _open_checked(session, copy, read_only=False)
            resolved = _resolve_plan(drawing, plan)
            records = []
            extension = get_com_member(drawing, "Extension")
            annotation_ids = []
            for view in get_com_member(get_com_member(drawing, "GetCurrentSheet"), "GetViews") or ():
                for collection in ("GetDatumTags", "GetGTols"):
                    for existing in get_com_member(view, collection) or ():
                        annotation_ids.append(_persistent_id(extension, get_com_member(existing, "GetAnnotation")))
            for kind, row, view, target, target_id in resolved:
                position = tuple(value / 1000 for value in row["positionMm"]) if "positionMm" in row else None
                if kind == "datum":
                    obj = insert_datum(drawing, view, target, session.sw, row["label"], position, display_style=row["displayStyle"])
                else:
                    obj = insert_gtol(drawing, view, target, session.sw, characteristic=row["characteristic"], tolerance=row["tolerance"],
                                      diameter=row["diameter"], datums=row["datums"], position=position,
                                      target_kind="dimension" if row["target"]["kind"] == "dimension" else "edge", material_condition=row.get("materialCondition"))
                ann = get_com_member(obj, "GetAnnotation")
                annotation_id = _persistent_id(extension, ann)
                if any(_same_id(extension, previous, annotation_id) for previous in annotation_ids):
                    raise RuntimeError("写入复用了已有标注身份，副本不保存")
                annotation_ids.append(annotation_id)
                records.append({"kind": kind, "request": row, "object": obj, "annotation_id": annotation_id,
                                "target_id": target_id, "position": get_com_member(ann, "GetPosition")})
            if not get_com_member(drawing, "ForceRebuild3", False):
                raise RuntimeError("工程图重建失败")
            if not session.save(drawing, str(copy)):
                raise RuntimeError("副本保存失败")
            _capture_saved_positions(records)
            session.close(model=drawing)
            drawing = _open_checked(session, copy)
            _verify_reopened(drawing, records)
            from scripts.sw_drawing import export_sheet_to_pdf, inspect_drawing_structure
            from scripts.sw_drawing_review import inspect_pdf_dimension_rendering
            from scripts import sw_drawing_review
            from scripts.sw_review import review_drawing_layout, save_review_previews, inspect_bmp_preview
            pdf = output / "drawing.pdf"
            if not export_sheet_to_pdf(drawing, str(pdf), sw_app=session.sw):
                raise RuntimeError("PDF 导出失败")
            previews = save_review_previews(drawing, output / "previews", basename="drawing", views=("front",))
            structure = inspect_drawing_structure(drawing, paper_size_hint="A3")
            rendering = inspect_pdf_dimension_rendering(pdf, structure)
            if rendering.get("status") != "pass":
                raise RuntimeError("PDF 尺寸文字核验失败")
            rendered = sw_drawing_review._MODULE._with_rendered_dimension_boxes(structure, rendering)
            layout = review_drawing_layout(rendered, preview_evidence=[inspect_bmp_preview(path) for path in previews])
            report["layout"] = layout
            if layout.get("status") != "pass":
                raise RuntimeError("图纸布局核验失败")
            if any(_sha256(path) != digest for path, digest in source_hashes.items()):
                raise RuntimeError("源图纸或模型文件发生变化")
            report.update(status="review_required", nativeValidation="pass", annotationCount=len(records),
                          outputs=[str(copy), str(pdf), *map(str, previews)], sourceHashes={str(path): value for path, value in source_hashes.items()})
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    if created_dir:
        with (output / "gdt-copy-manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="在新目录的图纸副本中写入原生基准与 GD&T，并重开核验")
    parser.add_argument("--source", required=True)
    parser.add_argument("--inspect", action="store_true", help="只读列出真实目标及源哈希")
    parser.add_argument("--plan")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    if args.inspect:
        if args.plan or args.output_dir:
            parser.error("--inspect 不接受写入计划或输出目录")
        print(json.dumps(inspect_targets(args.source), ensure_ascii=True, indent=2, allow_nan=False))
        return 0
    if not args.plan or not args.output_dir:
        parser.error("写入时必须提供 --plan 和 --output-dir")
    plan_path = Path(args.plan)
    if plan_path.stat().st_size > 1024 * 1024:
        parser.error("计划不得超过 1 MiB")
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    result = annotate_copy(args.source, plan, args.output_dir)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result["status"] == "review_required" else 1


if __name__ == "__main__":
    raise SystemExit(main())
