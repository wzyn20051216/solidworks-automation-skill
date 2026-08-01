"""第 4 周 AutoCAD 工程图、尺寸、DXF 与原生预览真机回归。

需要 Windows + AutoCAD 2024 + pywin32；不会被普通 pytest 自动收集。
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[1]
ACAD_SCRIPTS = ROOT / "subskills" / "autocad-automation" / "scripts"
sys.path.insert(0, str(ACAD_SCRIPTS))

from acad_headless import inspect_dxf, render_dxf  # noqa: E402
from acad_review import review_active  # noqa: E402
from acad_session import AutoCADSession  # noqa: E402
from acad_preview import convert_bmp_to_png  # noqa: E402


def _default_output_dir() -> Path:
    """@brief 返回第 4 周 AutoCAD 回归默认目录。"""
    return Path(tempfile.gettempdir()) / "autocad_week4_drawing_regression"


def _require_file(path: Path, label: str) -> dict:
    """@brief 检查文件存在、非空并返回证据。"""
    if not path.is_file():
        raise RuntimeError(f"{label}未生成: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"{label}为空文件: {path}")
    return {"path": str(path), "size_bytes": size}


def _draw_frame(session: AutoCADSession) -> None:
    """@brief 绘制 A3 横向中性 GB/T 风格图框和标题栏。"""
    session.create_layer("FRAME", color=7)
    session.create_layer("OUTLINE", color=7)
    session.create_layer("CENTER", color=1, linetype="CENTER")
    session.create_layer("HOLE", color=1)
    session.create_layer("DIM", color=2)
    session.create_layer("TEXT", color=3)

    # A3 横向 420 x 297 mm，左装订边 25 mm，其余边 5 mm。
    session.add_rectangle((0, 0), 420, 297, layer="FRAME")
    session.add_rectangle((25, 5), 390, 287, layer="FRAME")
    # 右下标题栏：宽 180，高 35，使用真实线段分格。
    x0, y0, width, height = 235, 5, 180, 35
    session.add_rectangle((x0, y0), width, height, layer="FRAME")
    for x in (x0 + 60, x0 + 120):
        session.add_line((x, y0), (x, y0 + height), layer="FRAME")
    session.add_line((x0, y0 + 17.5), (x0 + width, y0 + 17.5), layer="FRAME")
    for text, point in (
        ("CAD STUDIO", (x0 + 5, y0 + 23)),
        ("图号 W4-001", (x0 + 65, y0 + 23)),
        ("名称 安装板", (x0 + 125, y0 + 23)),
        ("材料 Q235B", (x0 + 5, y0 + 7)),
        ("比例 1:1", (x0 + 65, y0 + 7)),
        ("单位 mm", (x0 + 125, y0 + 7)),
    ):
        session.add_text(text, (*point, 0), 3, layer="TEXT")


def _draw_plate(session: AutoCADSession) -> None:
    """@brief 绘制安装板实体、中心线、孔和真实尺寸。"""
    left, bottom, width, height = 70.0, 105.0, 120.0, 80.0
    session.add_rectangle((left, bottom), width, height, layer="OUTLINE")
    hole_radius = 4.5
    hole_margin = 15.0
    hole_points = [
        (left + hole_margin, bottom + hole_margin),
        (left + width - hole_margin, bottom + hole_margin),
        (left + width - hole_margin, bottom + height - hole_margin),
        (left + hole_margin, bottom + height - hole_margin),
    ]
    for x, y in hole_points:
        session.add_circle((x, y, 0), hole_radius, layer="HOLE")
        session.add_line((x - 8, y), (x + 8, y), layer="CENTER")
        session.add_line((x, y - 8), (x, y + 8), layer="CENTER")

    session.add_dim_aligned(
        (left, bottom, 0),
        (left + width, bottom, 0),
        (left + width / 2, bottom - 14, 0),
    )
    session.add_dim_aligned(
        (left, bottom, 0),
        (left, bottom + height, 0),
        (left - 14, bottom + height / 2, 0),
    )
    session.add_dim_aligned(
        (left, bottom, 0),
        (left + hole_margin, bottom, 0),
        (left + hole_margin / 2, bottom - 7, 0),
    )
    session.add_dim_diametric(hole_points[0], hole_radius, angle_degrees=35, leader_length=12)
    session.add_text("4x Ø9 通孔，中心距 90 x 50，基准边定位 15", (left, bottom - 28, 0), 3, layer="TEXT")
    session.add_text("安装板 120 x 80 x 12，孔位和尺寸需按实体复核", (left, bottom + height + 12, 0), 3, layer="TEXT")


def run_regression(output_root: Path, *, run_id: str | None = None) -> dict:
    """@brief 执行 AutoCAD 第 4 周黄金图纸回归。"""
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    dwg_path = output_dir / "W4-001-mounting-plate.dwg"
    dxf_path = output_dir / "W4-001-mounting-plate.dxf"
    bmp_path = output_dir / "W4-001-mounting-plate.bmp"
    png_path = output_dir / "W4-001-mounting-plate.png"
    dxf_png_path = output_dir / "W4-001-mounting-plate-headless.png"
    report_path = output_dir / "W4-001-drawing-report.json"

    session = AutoCADSession(create_if_missing=True, visible=True).connect()
    created_document = False
    # AutoCAD 2024 动态代理可能无法调用 Documents.Add；优先复用已启动的活动空图纸。
    if session.doc is None:
        session.new_document()
        created_document = True
    try:
        _draw_frame(session)
        _draw_plate(session)
        session.regen()
        session.zoom_extents()
        dwg = session.save_as(dwg_path)
        _require_file(dwg, "DWG")
        dxf = session.export_dxf(dxf_path)
        _require_file(dxf, "DXF")
        bmp = session.export_bmp_preview(bmp_path)
        _require_file(bmp, "AutoCAD 原生 BMP")
        png_result = convert_bmp_to_png(bmp, png_path)
        if png_result.get("status") != "ok":
            raise RuntimeError(f"BMP 转 PNG 失败: {png_result}")
        _require_file(png_path, "AutoCAD 原生 PNG")

        native_review = review_active(session)
        if native_review["modelspace_entity_count"] < 20:
            raise RuntimeError(f"AutoCAD 实体数量过少: {native_review}")
        dxf_review = inspect_dxf(dxf)
        if dxf_review["evaluation"]["status"] != "pass":
            raise RuntimeError(f"DXF 工程图审查未通过: {dxf_review['evaluation']}")
        headless_render = render_dxf(dxf, dxf_png_path)
        _require_file(dxf_png_path, "DXF 无头 PNG")
        if headless_render.get("pixelCheck", {}).get("likelyBlank"):
            raise RuntimeError(f"DXF 无头预览疑似空白: {headless_render}")

        result = {
            "status": "ok",
            "run_id": run_id,
            "output_dir": str(output_dir),
            "assumptions": {
                "units": "mm",
                "drawing_standard": "GB/T 风格中性 A3 横向；未替代企业模板",
                "source": "new AutoCAD document",
            },
            "outputs": {
                "dwg": _require_file(dwg, "DWG"),
                "dxf": _require_file(dxf, "DXF"),
                "bmp": _require_file(bmp, "AutoCAD 原生 BMP"),
                "png": _require_file(png_path, "AutoCAD 原生 PNG"),
                "headless_png": _require_file(dxf_png_path, "DXF 无头 PNG"),
            },
            "native_review": native_review,
            "dxf_review": dxf_review,
            "headless_render": headless_render,
            "manual_review_required": [
                "企业图框、字体、线宽、打印机和比例仍需工程师确认",
                "BOM、技术要求和制造可行性不由本回归自动判定",
            ],
        }
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["report"] = _require_file(report_path, "JSON 报告")
        return result
    finally:
        if created_document:
            session.close_document(save_changes=False)


def parse_args() -> argparse.Namespace:
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="运行 AutoCAD 第 4 周工程图真机回归")
    parser.add_argument("--output-dir", default=str(_default_output_dir()))
    parser.add_argument("--run-id", default="")
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口。"""
    args = parse_args()
    output_root = Path(args.output_dir).expanduser().resolve()
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        result = run_regression(output_root, run_id=run_id)
    except Exception as exc:
        result = {
            "status": "failed",
            "run_id": run_id,
            "output_dir": str(output_root / run_id),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        result_path = output_root / run_id / "W4-001-drawing-report.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
