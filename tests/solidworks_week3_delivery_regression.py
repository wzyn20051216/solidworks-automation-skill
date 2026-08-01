"""第 3 周 SolidWorks 参数、属性与交付能力真机回归。

该脚本需要 Windows、SolidWorks 2024 和 pywin32/comtypes。它不会被普通
pytest 自动收集，必须人工或由 Windows 自托管 CI 显式执行。
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from sw_assembly import add_component, get_components, resolve_component  # noqa: E402
from sw_connect import get_com_member, mm  # noqa: E402
from sw_delivery import export_assembly_bom_csv, pack_and_go  # noqa: E402
from sw_document_data import set_custom_properties, update_dimension_mm  # noqa: E402
from sw_export import batch_export_formats  # noqa: E402
from sw_part import extrude_boss, sketch, sketch_rectangle  # noqa: E402
from sw_review import run_review  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402


def _default_output_dir() -> Path:
    """@brief 返回本周真机回归的默认输出根目录。"""
    return Path(tempfile.gettempdir()) / "solidworks_week3_delivery_regression"


def _require_file(path: Path, label: str) -> dict:
    """@brief 校验产物存在且非空，并返回文件证据。"""
    if not path.is_file():
        raise RuntimeError(f"{label}未生成: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"{label}为空文件: {path}")
    return {"path": str(path), "size_bytes": size}


def _assert_dimension_result(result: dict, expected_mm: float) -> None:
    """@brief 校验尺寸更新状态、重建结果和毫米值回读。"""
    if not result.get("success"):
        raise RuntimeError(f"尺寸更新失败: {result}")
    actual = float(result["after_mm"]["current"])
    if not math.isclose(actual, expected_mm, rel_tol=0.0, abs_tol=1e-6):
        raise RuntimeError(f"尺寸回读不一致: actual={actual}, expected={expected_mm}")


def _create_part(
    session: SolidWorksSession,
    path: Path,
    *,
    width_mm: float,
    height_mm: float,
    initial_depth_mm: float,
    final_depth_mm: float,
    properties: dict[str, str],
) -> dict:
    """@brief 创建零件，修改真实拉伸尺寸并写入、回读自定义属性。"""
    model = session.new_part()
    title = str(get_com_member(model, "GetTitle"))
    try:
        with sketch(model, "Front Plane") as sketch_name:
            sketch_rectangle(model, 0, 0, mm(width_mm), mm(height_mm))
        feature = extrude_boss(model, sketch_name, mm(initial_depth_mm))
        if feature is None:
            raise RuntimeError(f"零件拉伸失败: {path.name}")
        feature_name = str(get_com_member(feature, "Name"))
        dimension_name = f"D1@{feature_name}"
        dimension_result = update_dimension_mm(model, dimension_name, final_depth_mm)
        _assert_dimension_result(dimension_result, final_depth_mm)

        property_result = set_custom_properties(model, properties)
        if not property_result.get("success"):
            raise RuntimeError(f"自定义属性写入或回读失败: {property_result}")

        if not session.save(model, str(path)):
            raise RuntimeError(f"零件保存失败: {path}")
        file_evidence = _require_file(path, "零件")
        return {
            "file": file_evidence,
            "feature": feature_name,
            "dimension": dimension_result,
            "properties": property_result,
        }
    finally:
        session.close(title=title)


def _validate_batch_export(report: dict, expected_count: int) -> list[dict]:
    """@brief 验证所有批量导出文件均为本轮新生成的非空产物。"""
    if not report.get("success"):
        raise RuntimeError(f"批量导出失败: {report}")
    outputs = [
        output
        for document in report.get("documents", [])
        for output in document.get("outputs", [])
    ]
    if len(outputs) != expected_count:
        raise RuntimeError(f"批量导出数量错误: actual={len(outputs)}, expected={expected_count}")
    for output in outputs:
        if not output.get("produced_this_run") or int(output.get("size_bytes", 0)) <= 0:
            raise RuntimeError(f"批量导出缺少本轮产物证据: {output}")
    return outputs


def _validate_pack_and_go(report: dict, expected_sources: set[str]) -> None:
    """@brief 校验原生 Pack and Go 返回码及必要源文件。"""
    if not report.get("success"):
        raise RuntimeError(f"Pack and Go 失败: {report}")
    if any(code != 0 for code in report.get("status_codes", [])):
        raise RuntimeError(f"Pack and Go 返回非零状态码: {report['status_codes']}")
    packaged_names = {Path(item["path"]).name.casefold() for item in report.get("outputs", [])}
    missing = sorted(name for name in expected_sources if name.casefold() not in packaged_names)
    if missing:
        raise RuntimeError(f"Pack and Go 缺少引用文件: {missing}")


def _close_created_documents(session: SolidWorksSession, titles: list[str]) -> None:
    """@brief 尽力关闭本脚本创建的文档，不触碰用户原有文档。"""
    for title in reversed(titles):
        if not title:
            continue
        try:
            session.close(title=title)
        except Exception:
            pass


def run_regression(
    output_root: Path,
    *,
    visible: bool = True,
    wait_seconds: int = 20,
    run_id: str | None = None,
) -> dict:
    """@brief 执行第 3 周全部 SolidWorks 真实交付回归。"""
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    native_dir = output_dir / "native"
    export_dir = output_dir / "exports"
    package_dir = output_dir / "pack_and_go"
    review_dir = output_dir / "review"
    native_dir.mkdir()

    part_a = native_dir / "W3-PLATE-A.SLDPRT"
    part_b = native_dir / "W3-BLOCK-B.SLDPRT"
    assembly_path = native_dir / "W3-DELIVERY-ASSEMBLY.SLDASM"
    bom_path = output_dir / "W3-DELIVERY-BOM.csv"
    created_titles: list[str] = []
    session = SolidWorksSession(version=2024, visible=visible, wait_seconds=wait_seconds)
    result = {
        "run_id": run_id,
        "output_dir": str(output_dir),
        "revision": str(get_com_member(session.sw, "RevisionNumber")),
        "connection": session.connection_info,
    }

    try:
        result["parts"] = [
            _create_part(
                session,
                part_a,
                width_mm=48,
                height_mm=32,
                initial_depth_mm=8,
                final_depth_mm=12,
                properties={
                    "PartNumber": "W3-PLATE-A",
                    "Description": "第3周参数回归安装板",
                    "Material": "Q235B",
                },
            ),
            _create_part(
                session,
                part_b,
                width_mm=30,
                height_mm=22,
                initial_depth_mm=10,
                final_depth_mm=16,
                properties={
                    "PartNumber": "W3-BLOCK-B",
                    "Description": "第3周参数回归定位块",
                    "Material": "6061-T6",
                },
            ),
        ]

        assembly = session.new_assembly()
        assembly_title = str(get_com_member(assembly, "GetTitle"))
        created_titles.append(assembly_title)
        component_specs = (
            (part_a, 0.000),
            (part_a, 0.065),
            (part_b, 0.125),
        )
        for part_path, x in component_specs:
            component = add_component(assembly, str(part_path), x=x, y=0.0, z=0.0, sw=session.sw)
            if component is None:
                raise RuntimeError(f"添加装配组件失败: {part_path}")
            resolve_component(component)

        components = get_components(assembly)
        if len(components) != len(component_specs):
            raise RuntimeError(
                f"装配组件数量错误: actual={len(components)}, expected={len(component_specs)}"
            )
        assembly.ForceRebuild3(False)
        if not session.save(assembly, str(assembly_path)):
            raise RuntimeError(f"装配体保存失败: {assembly_path}")
        result["assembly"] = {
            "file": _require_file(assembly_path, "装配体"),
            "components": components,
            "component_count": len(components),
        }

        bom = export_assembly_bom_csv(assembly, bom_path)
        if not bom.get("success") or bom.get("row_count") != 2 or bom.get("quantity_total") != 3:
            raise RuntimeError(f"BOM 数量或产物证据错误: {bom}")
        _require_file(bom_path, "BOM")
        result["bom"] = bom

        package = pack_and_go(assembly, package_dir, flatten=True)
        _validate_pack_and_go(
            package,
            {part_a.name, part_b.name, assembly_path.name},
        )
        result["pack_and_go"] = package

        exports = batch_export_formats(
            session.sw,
            [part_a, part_b],
            export_dir,
            formats=(".step", ".stl"),
            overwrite=False,
            close_documents=True,
        )
        export_outputs = _validate_batch_export(exports, expected_count=4)
        result["batch_export"] = exports

        expected_outputs = [part_a, part_b, assembly_path, bom_path]
        expected_outputs.extend(Path(item["path"]) for item in package["outputs"])
        expected_outputs.extend(Path(item["path"]) for item in export_outputs)
        review, review_path = run_review(
            assembly,
            review_dir,
            basename="week3_delivery_assembly",
            views=("isometric", "front", "top", "right"),
            expected_outputs=[str(path) for path in expected_outputs],
        )
        if review.get("evaluation", {}).get("status") == "fail":
            raise RuntimeError(f"交付复核失败: {review.get('evaluation')}")
        blank_previews = [
            item for item in review.get("previews", []) if item.get("likely_blank")
        ]
        if blank_previews:
            raise RuntimeError(f"发现疑似空白预览: {blank_previews}")
        result["review"] = {
            "report_path": str(review_path),
            "evaluation": review.get("evaluation"),
            "checks": review.get("checks"),
            "previews": review.get("previews"),
        }
        result["status"] = "ok"
        return result
    finally:
        _close_created_documents(session, created_titles)
        result["owned_instance_closed"] = bool(session.quit_owned_instance())


def parse_args() -> argparse.Namespace:
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="运行第 3 周 SolidWorks 真实交付回归。")
    parser.add_argument(
        "--output-dir",
        default=str(_default_output_dir()),
        help="输出根目录；每次运行会创建独立时间戳子目录。",
    )
    parser.add_argument("--run-id", default="", help="指定本轮目录名，默认使用当前时间。")
    parser.add_argument("--hidden", action="store_true", help="尝试隐藏新启动的 SolidWorks 窗口。")
    parser.add_argument("--wait-seconds", type=int, default=20, help="启动 SolidWorks 的等待秒数。")
    return parser.parse_args()


def main() -> int:
    """@brief 命令行入口，始终写出结构化结果。"""
    args = parse_args()
    output_root = Path(args.output_dir).expanduser().resolve()
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = output_root / run_id / "week3_delivery_regression_result.json"
    try:
        result = run_regression(
            output_root,
            visible=not args.hidden,
            wait_seconds=args.wait_seconds,
            run_id=run_id,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "run_id": run_id,
            "output_dir": str(output_root / run_id),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
