"""受控 DrawingSpec 出图包：创建、保存重开、原生核验及 PDF 制造交付审视。"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.drawing_spec import validate_drawing_spec
from scripts.sw_connect import get_com_member
from scripts.sw_file_rename import _valid_filename
from scripts.sw_read_guard import SolidWorksReadGuard
from scripts.sw_rename_copy import _open_checked, _sha256
from scripts.sw_session import SolidWorksSession


def generate_package(spec_source, output_dir, drawing_filename="drawing.slddrw", *, overwrite=False):
    from scripts.sw_drawing import validate_generic_drawing_generation, generate_drawing_from_spec, inspect_drawing_structure, export_sheet_to_pdf
    from scripts.sw_drawing_review import review_drawing_artifacts
    from scripts.sw_review import save_review_previews, inspect_bmp_preview, collect_geometry_measurements
    from scripts.sw_gdt_copy import _capture_saved_positions, _verify_reopened
    from scripts.sw_drawing_native import verify_dimensions

    validation = validate_drawing_spec(spec_source)
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite 必须是布尔值")
    if validation["status"] == "blocked":
        return validation
    spec = validation["spec"]
    capability = validate_generic_drawing_generation(spec)
    if capability["status"] != "pass":
        return capability
    source = Path(spec["sourceModel"]).expanduser().resolve(strict=True)
    if source.suffix.casefold() != (".sldasm" if spec["documentType"] == "assembly" else ".sldprt"):
        raise ValueError("源文件类型与 DrawingSpec.documentType 不一致")
    if Path(drawing_filename).name != drawing_filename or not _valid_filename(drawing_filename) or Path(drawing_filename).suffix.casefold() != ".slddrw":
        raise ValueError("drawing_filename 必须是合法的 SLDDRW 文件名")
    output = Path(output_dir).expanduser().resolve()
    drawing_path = output / drawing_filename
    pdf_path = drawing_path.with_suffix(".pdf")
    report_path = output / (drawing_path.stem + "_review_report.json")
    for path in (drawing_path, pdf_path, report_path):
        if path.is_symlink() or (path.exists() and not overwrite):
            raise ValueError("输出已存在或为符号链接，拒绝覆盖")
    native = bool(spec.get("requiredDimensions")) or any((spec.get("professionalAnnotations") or {}).get(key) for key in ("datums", "geometricTolerances"))
    hashes = {source: _sha256(source)}
    result = {"status": "blocked", "capability": "solidworks-engineering-drawing", "sourceModel": str(source),
              "outputs": {}, "manual_review_required": True}
    try:
        with SolidWorksReadGuard(), SolidWorksSession(version=2026 if native else None, visible=True) as session:
            # 排队等待锁期间可能有其他进程完成同名输出；不得覆盖其结果或报告。
            if any(path.is_symlink() or (path.exists() and not overwrite) for path in (drawing_path, pdf_path, report_path)):
                return {**result, "error_code": "DRAWING_OUTPUT_EXISTS", "message": "等待期间同名输出已出现，拒绝覆盖"}
            model = _open_checked(session, source)
            if get_com_member(model, "GetSaveFlag") not in (False, 0):
                raise ValueError("源模型存在未保存修改")
            expected_type = 2 if spec["documentType"] == "assembly" else 1
            if get_com_member(model, "GetType") != expected_type:
                raise ValueError("源模型实际类型与规格不一致")
            dependencies = get_com_member(model, "GetDependencies2", True, True, False)
            if not isinstance(dependencies, (list, tuple)) or len(dependencies) % 2:
                raise ValueError("不能确认模型依赖清单")
            for index in range(1, len(dependencies), 2):
                path = Path(str(dependencies[index])).resolve(strict=True)
                hashes[path] = _sha256(path)
            if native:
                from scripts.sw_measure import collect_bounding_box
                bounds = collect_bounding_box(model)
                if bounds.get("errors") or len(bounds.get("size_mm") or []) != 3 or any(not math.isclose(a, b, abs_tol=.01, rel_tol=0) for a, b in zip(bounds["size_mm"], spec["modelSizeMm"])):
                    raise ValueError("modelSizeMm 与真实模型包围盒不一致")
            for document in session._documents():
                path = str(get_com_member(document, "GetPathName") or "")
                title = str(get_com_member(document, "GetTitle") or "")
                if (Path(path).name.casefold() == drawing_path.name.casefold() or title.casefold() in {drawing_path.name.casefold(), drawing_path.stem.casefold()}):
                    raise ValueError("已打开同名输出文档，拒绝复用或关闭用户文档")
            output.mkdir(parents=True, exist_ok=True)
            drawing = session.new_drawing()
            context = {}
            generation = generate_drawing_from_spec(drawing, spec, str(source), template_candidates=spec.get("templateCandidates"),
                                                    sw_app=session.sw, initial_save_path=drawing_path, evidence_context=context)
            if generation.get("status") in {"failed", "blocked"}:
                result.update(generation=generation, error_code=generation.get("error_code"), stage=generation.get("stage"))
            else:
                if not get_com_member(drawing, "ForceRebuild3", False) or not session.save(drawing, str(drawing_path)):
                    raise RuntimeError("最终工程图重建或保存失败")
                records = context.get("native_records") or []
                _capture_saved_positions(records)
                dimensions = context.get("dimensions") or {}
                for record in dimensions.values():
                    record["saved_position"] = get_com_member(get_com_member(record["object"], "GetAnnotation"), "GetPosition")
                session.close(model=drawing)
                drawing = _open_checked(session, drawing_path)
                if native:
                    from scripts.sw_drawing_native import map_views
                    sheet = get_com_member(drawing, "GetCurrentSheet")
                    properties = get_com_member(sheet, "GetProperties2")
                    if len(properties) != 8 or not math.isclose(properties[2] / properties[3], generation["layout"]["scale"], abs_tol=1e-8, rel_tol=0):
                        raise RuntimeError("重开后图纸比例不一致")
                    for view in map_views(drawing, generation["views"]).values():
                        ratio = get_com_member(view, "ScaleRatio")
                        if not math.isclose(ratio[0] / ratio[1], generation["layout"]["scale"], abs_tol=1e-8, rel_tol=0):
                            raise RuntimeError("重开后视图比例不一致")
                _verify_reopened(drawing, records)
                verify_dimensions(drawing, dimensions)
                structure = inspect_drawing_structure(drawing, paper_size_hint=spec["paperSize"], title_block_box=generation["layout"].get("title_block_box"))
                generation["structure"] = structure
                pdf_ok = export_sheet_to_pdf(drawing, str(pdf_path), sw_app=session.sw)
                previews = save_review_previews(drawing, output / "previews", basename=drawing_path.stem, views=("front",))
                preview_evidence = [inspect_bmp_preview(path) for path in previews]
                geometry = collect_geometry_measurements(model) if spec.get("holeRequirements") else None
                review = review_drawing_artifacts(spec, structure=structure, pdf_path=pdf_path if pdf_ok else None,
                                                 preview_evidence=preview_evidence, model_evidence=geometry)
                status = review.get("status", "review_required")
                if native and status == "pass":
                    status = "review_required"
                if get_com_member(model, "GetSaveFlag") not in (False, 0):
                    raise RuntimeError("出图期间源模型出现未保存修改")
                result.update(status=status, generation=generation, review=review, native_validation="pass",
                              manual_review_required=native or bool(review.get("manual_review_required", True)),
                              outputs={"slddrw": {"path": str(drawing_path), "exists": drawing_path.is_file(), "size_bytes": drawing_path.stat().st_size if drawing_path.is_file() else 0},
                                       "pdf": {"path": str(pdf_path), "exists": pdf_path.is_file(), "size_bytes": pdf_path.stat().st_size if pdf_path.is_file() else 0}, "previews": preview_evidence})
                if status in {"blocked", "failed", "fail"}:
                    result["draftArtifacts"] = result.pop("outputs")
                    result["outputs"] = {}
    except Exception as error:
        result.update(status="blocked", error_code="DRAWING_PACKAGE_FAILED", message=f"{type(error).__name__}: {error}", outputs={})
    if any(_sha256(path) != digest for path, digest in hashes.items()):
        result.update(status="blocked", error_code="DRAWING_SOURCE_CHANGED", outputs={})
    if output.is_dir() and not report_path.is_symlink() and (overwrite or not report_path.exists()):
        result["reportPath"] = str(report_path)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="从结构化 DrawingSpec 自动创建并重开核验原生工程图")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--filename", default="drawing.slddrw")
    args = parser.parse_args(argv)
    result = generate_package(args.spec, args.output_dir, args.filename)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "pass" else 2 if result["status"] in {"pilot", "review_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
