"""SolidWorks 2024 第 4 周工程图+BOM 真机回归。

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

from sw_connect import get_com_member  # noqa: E402
from sw_drawing import create_standard_views, export_sheet_to_pdf, inspect_drawing_structure, insert_dimensions  # noqa: E402
from sw_part import extrude_boss, sketch_rectangle  # noqa: E402
from sw_review import inspect_bmp_preview, save_review_previews  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402


def _require_file(path: Path, label: str) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"{label}未生成或为空: {path}")
    return {"path": str(path), "size_bytes": path.stat().st_size}


def run_regression(output_root: Path, *, run_id: str | None = None) -> dict:
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    part_path = output_dir / "W4-001-plate.sldprt"
    drawing_path = output_dir / "W4-001-plate.slddrw"
    pdf_path = output_dir / "W4-001-plate.pdf"
    report_path = output_dir / "W4-001-drawing-report.json"
    visible = os.environ.get("CAD_STUDIO_VISIBLE", "true").lower() not in {"0", "false", "no"}
    session = SolidWorksSession(version=2024, visible=visible, wait_seconds=12)
    part_title = None
    drawing_title = None
    try:
        part = session.new_part()
        part_title = str(get_com_member(part, "GetTitle"))
        with __import__("sw_part").sketch(part, "Front Plane") as sketch_name:
            sketch_rectangle(part, 0, 0, 0.12, 0.08)
        feature = extrude_boss(part, sketch_name, 0.012)
        if feature is None:
            raise RuntimeError("安装板拉伸失败")
        if not session.save(part, str(part_path)):
            raise RuntimeError("安装板保存失败")
        _require_file(part_path, "零件")

        drawing = session.new_drawing()
        drawing_title = str(get_com_member(drawing, "GetTitle"))
        if not create_standard_views(drawing, str(part_path)):
            raise RuntimeError("创建标准三视图失败")
        insert_dimensions(drawing)
        structure = inspect_drawing_structure(drawing)
        if structure["status"] != "pass" or structure["view_count"] < 1:
            raise RuntimeError(f"工程图视图复核失败: {structure}")
        if not session.save(drawing, str(drawing_path)):
            raise RuntimeError("工程图保存失败")
        _require_file(drawing_path, "工程图")
        if not export_sheet_to_pdf(drawing, str(pdf_path)):
            raise RuntimeError("工程图 PDF 导出失败")
        _require_file(pdf_path, "PDF")
        preview_paths = save_review_previews(drawing, output_dir / "previews", basename="drawing", views=("front", "top", "right"))
        previews = [inspect_bmp_preview(path) for path in preview_paths]
        if not all(item["exists"] and not item["likely_blank"] for item in previews):
            raise RuntimeError(f"工程图预览为空或缺失: {previews}")
        result = {
            "status": "ok",
            "run_id": run_id,
            "output_dir": str(output_dir),
            "outputs": {"part": _require_file(part_path, "零件"), "drawing": _require_file(drawing_path, "工程图"), "pdf": _require_file(pdf_path, "PDF")},
            "drawingEvidence": structure,
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
    args = parser.parse_args()
    try:
        result = run_regression(Path(args.output_dir).expanduser().resolve(), run_id=args.run_id or None)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
