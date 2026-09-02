"""SolidWorks 配置族创建、切换、配置尺寸和保存重开真机回归。

该脚本不会被普通 pytest 自动收集；需要 Windows、SolidWorks 和 pywin32，
用于把配置能力从接口存在推进到真实文档证据。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_connect import get_com_member, mm  # noqa: E402
from sw_document_data import (  # noqa: E402
    activate_configuration,
    create_configuration,
    inspect_configurations,
    set_custom_properties,
    update_dimension_mm,
)
from sw_part import extrude_boss, sketch, sketch_rectangle  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402


EXPECTED_DEPTHS_MM = {"默认": 12.0, "薄型": 7.5, "加强型": 20.0}


def _default_output_dir() -> Path:
    """@brief 返回真机回归默认输出目录。"""
    return Path(tempfile.gettempdir()) / "solidworks_configuration_family_regression"


def _assert_close(actual: float, expected: float, label: str) -> None:
    """@brief 按微米级绝对容差校验尺寸回读。"""
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6):
        raise RuntimeError(f"{label}尺寸不一致: actual={actual}, expected={expected}")


def run(output_dir: Path, *, version: int | None, visible: bool) -> dict:
    """@brief 创建三配置零件，保存重开并逐配置验证尺寸和属性。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / "configuration_family_plate.SLDPRT"
    report_path = output_dir / "configuration_family_report.json"
    session = SolidWorksSession(version=version, visible=visible, wait_seconds=20)
    created_title = ""
    reopened_title = ""
    report: dict = {
        "schema_version": "1.0",
        "status": "blocked",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "solidworks": session.connection_info,
        "output_part": str(part_path),
        "expected_depths_mm": EXPECTED_DEPTHS_MM,
    }
    try:
        model = session.new_part()
        created_title = str(get_com_member(model, "GetTitle"))
        with sketch(model, "Front Plane") as sketch_name:
            sketch_rectangle(model, 0, 0, mm(80.0), mm(50.0))
        feature = extrude_boss(model, sketch_name, mm(EXPECTED_DEPTHS_MM["默认"]))
        if feature is None:
            raise RuntimeError("基础拉伸失败")
        dimension_name = f"D1@{get_com_member(feature, 'Name')}"

        creation_results = []
        for name in ("薄型", "加强型"):
            result = create_configuration(
                model,
                name,
                comment=f"CAD Studio 真机回归：{name}",
                activate=True,
            )
            if not result.get("success"):
                raise RuntimeError(f"配置创建或回读失败: {result}")
            creation_results.append(result)

        dimension_results = []
        for name, value_mm in EXPECTED_DEPTHS_MM.items():
            result = update_dimension_mm(
                model,
                dimension_name,
                value_mm,
                configuration_mode="specific",
                configuration_names=[name],
            )
            if not result.get("success"):
                raise RuntimeError(f"配置尺寸更新失败: {result}")
            _assert_close(float(result["after_mm"][name]), value_mm, name)
            dimension_results.append(result)
            properties = set_custom_properties(
                model,
                {"ConfigurationClass": name, "NominalDepthMM": str(value_mm)},
                configuration_name=name,
            )
            if not properties.get("success"):
                raise RuntimeError(f"配置属性写入失败: {properties}")

        if not session.save(model, str(part_path)):
            raise RuntimeError("三配置零件保存失败")
        created_title = str(get_com_member(model, "GetTitle"))
        session.close(title=created_title)
        created_title = ""

        reopened = session.open(str(part_path), silent=True)
        reopened_title = str(get_com_member(reopened, "GetTitle"))
        inspection = inspect_configurations(reopened)
        if set(inspection["configurations"]) != set(EXPECTED_DEPTHS_MM):
            raise RuntimeError(f"保存重开后的配置清单不一致: {inspection}")

        dimension = reopened.Parameter(dimension_name)
        if dimension is None:
            raise RuntimeError(f"保存重开后找不到尺寸: {dimension_name}")
        readback_mm = {}
        activation_results = []
        for name, expected_mm in EXPECTED_DEPTHS_MM.items():
            activation = activate_configuration(reopened, name, rebuild=True, save=False)
            if not activation.get("success"):
                raise RuntimeError(f"配置激活失败: {activation}")
            activation_results.append(activation)
            actual_mm = float(dimension.GetSystemValue2(name)) * 1000.0
            _assert_close(actual_mm, expected_mm, name)
            readback_mm[name] = actual_mm

        report.update({
            "status": "pass",
            "dimension_name": dimension_name,
            "creation_results": creation_results,
            "dimension_results": dimension_results,
            "inspection_after_reopen": inspection,
            "activation_results": activation_results,
            "readback_depths_mm": readback_mm,
            "part_size_bytes": part_path.stat().st_size,
        })
    except Exception as exc:
        report.update({
            "status": "blocked",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        if reopened_title:
            try:
                session.close(title=reopened_title)
            except Exception:
                pass
        if created_title:
            try:
                session.close(title=created_title)
            except Exception:
                pass
        session.quit_owned_instance()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="运行 SolidWorks 配置族真机回归。")
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--version", type=int)
    parser.add_argument("--hidden", action="store_true")
    args = parser.parse_args()
    report = run(args.output_dir.resolve(), version=args.version, visible=not args.hidden)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
