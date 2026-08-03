"""SolidWorks 第 4 周工程图+BOM 真机回归。

需要 Windows + SolidWorks + pywin32/comtypes；不会被普通 pytest 收集。
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_connect import get_com_member, get_sw_version  # noqa: E402
from sw_drawing import (  # noqa: E402
    auto_arrange_drawing_dimensions,
    create_adaptive_standard_views,
    export_sheet_to_pdf,
    inspect_drawing_structure,
    insert_dimensions,
    plan_standard_view_layout,
    setup_current_sheet_as_a3,
)
from sw_part import auto_dimension_sketch, extrude_boss, sketch_rectangle  # noqa: E402
from sw_review import inspect_bmp_preview, review_drawing_layout, save_review_previews  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402


def _require_file(path: Path, label: str) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"{label}未生成或为空: {path}")
    return {"path": str(path), "size_bytes": path.stat().st_size}


def _sheet_format_candidates() -> list[str]:
    """@brief 返回本机可用的 A3/GB 图框候选路径。"""
    roots = [
        Path(r"E:\SolidWroks2026\SOLIDWORKS"),
        Path(r"E:\Solidworks\SOLIDWORKS"),
        Path(r"C:\ProgramData\SOLIDWORKS"),
    ]
    candidates: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            candidates.extend(str(path) for path in root.rglob("*.slddrt") if "a3" in path.name.casefold())
        except OSError:
            continue
    return candidates


def run_regression(output_root: Path, *, version: int | None = None, run_id: str | None = None) -> dict:
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    part_path = output_dir / "W4-001-plate.sldprt"
    drawing_path = output_dir / "W4-001-plate.slddrw"
    pdf_path = output_dir / "W4-001-plate.pdf"
    report_path = output_dir / "W4-001-drawing-report.json"
    visible = os.environ.get("CAD_STUDIO_VISIBLE", "true").lower() not in {"0", "false", "no"}
    session = SolidWorksSession(version=version, visible=visible, wait_seconds=20)
    part_title = None
    drawing_title = None
    try:
        part = session.new_part()
        part_title = str(get_com_member(part, "GetTitle"))
        with __import__("sw_part").sketch(part, "Front Plane") as sketch_name:
            rectangle_segments = sketch_rectangle(part, 0, 0, 0.12, 0.08)
            model_dimensions = auto_dimension_sketch(part, sketch_segments=rectangle_segments)
        feature = extrude_boss(part, sketch_name, 0.012)
        if feature is None:
            raise RuntimeError("安装板拉伸失败")
        if not session.save(part, str(part_path)):
            raise RuntimeError("安装板保存失败")
        # InsertModelAnnotations 从当前活动模型解析 DisplayDimension；工程图创建前
        # 保存后保持零件为活动文档，并显式显示特征尺寸，避免只存在于草图树中。
        try:
            get_com_member(part, "ShowFeatureDimensions")
            get_com_member(part, "GraphicsRedraw2")
        except Exception:
            pass
        _require_file(part_path, "零件")

        drawing = session.new_drawing()
        drawing_title = str(get_com_member(drawing, "GetTitle"))
        sheet_setup = setup_current_sheet_as_a3(drawing, _sheet_format_candidates(), require_gbt=True)
        if sheet_setup.get("status") != "pass":
            raise RuntimeError(f"A3/GB 图框设置失败: {sheet_setup}")
        layout = plan_standard_view_layout((0.12, 0.012, 0.08), paper_size="A3")
        created_views = create_adaptive_standard_views(drawing, str(part_path), layout)
        if created_views.get("status") != "pass" or created_views.get("view_count") != 3:
            raise RuntimeError(f"创建 A3 自适应三视图失败: {created_views}")
        # 部分版本只有在工程图首次保存、视图引用落盘后才稳定暴露可导入的模型
        # 尺寸。这里保存的是本轮新产物，不会覆盖旧交付版本。
        if not session.save(drawing, str(drawing_path)):
            raise RuntimeError("工程图首次保存失败")
        inserted_annotations = insert_dimensions(drawing)
        dimensions_inserted = bool(inserted_annotations)
        try:
            drawing.ForceRebuild3(False)
            drawing.GraphicsRedraw2()
        except Exception:
            pass
        official_arrangement = auto_arrange_drawing_dimensions(drawing, spacing_m=0.01)
        if official_arrangement.get("status") == "blocked":
            raise RuntimeError(f"SolidWorks 官方尺寸排列接口不可用: {official_arrangement}")
        structure = inspect_drawing_structure(
            drawing,
            paper_size_hint="A3",
            title_block_box=layout.get("title_block_box"),
        )
        if structure["status"] != "pass" or structure["view_count"] < 1:
            raise RuntimeError(f"工程图视图复核失败: {structure}")
        if not dimensions_inserted or structure.get("dimension_count", 0) < 1:
            raise RuntimeError(
                "工程图未读取到本轮插入的真实尺寸实体: "
                f"inserted={dimensions_inserted}, dimension_count={structure.get('dimension_count', 0)}"
            )
        if not session.save(drawing, str(drawing_path)):
            raise RuntimeError("工程图保存失败")
        _require_file(drawing_path, "工程图")
        if not export_sheet_to_pdf(drawing, str(pdf_path), sw_app=session.sw):
            raise RuntimeError("工程图 PDF 导出失败")
        _require_file(pdf_path, "PDF")
        preview_paths = save_review_previews(drawing, output_dir / "previews", basename="drawing", views=("front", "top", "right"))
        previews = [inspect_bmp_preview(path) for path in preview_paths]
        if not all(item["exists"] and not item["likely_blank"] for item in previews):
            raise RuntimeError(f"工程图预览为空或缺失: {previews}")
        layout_review = review_drawing_layout(structure, preview_evidence=previews)
        if layout_review.get("status") == "blocked":
            raise RuntimeError(f"工程图布局结构复核阻塞: {layout_review}")
        estimated_count = int(layout_review.get("evidence_summary", {}).get("estimated_dimension_box_count") or 0)
        if estimated_count and layout_review.get("error_code") not in {
            "DRAWING_LAYOUT_ESTIMATED_EVIDENCE_REQUIRES_VISUAL_REVIEW",
            "DRAWING_LAYOUT_ESTIMATED_COLLISION_RISK",
            "DRAWING_LAYOUT_COLLISION_DETECTED",
        }:
            raise RuntimeError(f"工程图估算边界未保持人工复核门禁: {layout_review}")
        result = {
            "status": "ok",
            "run_id": run_id,
            "output_dir": str(output_dir),
            "solidworks": get_sw_version(session.sw),
            "connection": session.connection_info,
            "outputs": {"part": _require_file(part_path, "零件"), "drawing": _require_file(drawing_path, "工程图"), "pdf": _require_file(pdf_path, "PDF")},
            "sheetSetup": sheet_setup,
            "viewLayout": layout,
            "createdViews": created_views,
            "drawingEvidence": structure,
            "drawingLayoutReview": layout_review,
            "dimensions_inserted": dimensions_inserted,
            "officialDimensionArrangement": official_arrangement,
            "modelDimensions": model_dimensions,
            "reviewFindings": structure.get("checks", []),
            "artifactRelations": [{"from": str(part_path), "to": str(drawing_path)}, {"from": str(drawing_path), "to": str(pdf_path)}],
            "previews": previews,
            "manual_review_required": True,
        }
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["report"] = _require_file(report_path, "报告")
        return result
    finally:
        if drawing_title:
            session.close(title=drawing_title)
        if part_title:
            session.close(title=part_title)
        session.quit_owned_instance()


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 SolidWorks 第 4 周工程图真机回归")
    parser.add_argument("--output-dir", default=str(Path(tempfile.gettempdir()) / "solidworks_week4_drawing_regression"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--version", type=int, help="指定 SolidWorks 年份，例如 2026；默认连接最新注册版本。")
    args = parser.parse_args()
    try:
        result = run_regression(
            Path(args.output_dir).expanduser().resolve(),
            version=args.version,
            run_id=args.run_id or None,
        )
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
