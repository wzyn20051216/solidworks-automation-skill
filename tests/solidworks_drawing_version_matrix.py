"""@file solidworks_drawing_version_matrix.py
@brief SolidWorks 2024/2025/2026 工程图真机回归矩阵。

仅对已注册的精确版本 ProgID 启动真机回归；未安装版本记录为 unavailable，
不得回退到默认 ProgID 后误报为目标版本通过。
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import winreg
except ImportError:  # pragma: no cover - 非 Windows 只允许生成 blocked 矩阵
    winreg = None


DEFAULT_YEARS = (2024, 2025, 2026)


def prog_id_for_year(year: int) -> str:
    """@brief 返回年份对应的精确 SolidWorks COM ProgID。"""
    year = int(year)
    if year < 2010 or year > 2035:
        raise ValueError(f"不支持的 SolidWorks 版本年份: {year}")
    return f"SldWorks.Application.{year - 1992}"


def is_version_registered(year: int) -> bool:
    """@brief 只检查精确版本 ProgID，避免默认 ProgID 指向其他年份。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id_for_year(year)):
            return True
    except OSError:
        return False


def discover_registered_versions(years: Iterable[int] = DEFAULT_YEARS) -> dict[int, bool]:
    """@brief 返回目标年份的 COM 注册状态。"""
    return {int(year): is_version_registered(int(year)) for year in years}


def _default_regression_runner(output_root: Path, *, version: int, run_id: str) -> dict[str, Any]:
    """@brief 延迟导入单版本真机脚本，保持离线矩阵测试不连接 COM。"""
    from solidworks_week4_drawing_regression import run_regression

    return run_regression(output_root, version=version, run_id=run_id)


def run_matrix(
    output_root: Path,
    *,
    years: Iterable[int] = DEFAULT_YEARS,
    registered_versions: dict[int, bool] | None = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """@brief 串行执行已安装版本并写出可审计矩阵报告。"""
    target_years = tuple(dict.fromkeys(int(year) for year in years))
    if not target_years:
        raise ValueError("至少指定一个 SolidWorks 年份")
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    registration = registered_versions if registered_versions is not None else discover_registered_versions(target_years)
    execute = runner or _default_regression_runner
    entries = []
    for year in target_years:
        prog_id = prog_id_for_year(year)
        if not registration.get(year, False):
            entries.append({
                "year": year,
                "prog_id": prog_id,
                "status": "unavailable",
                "reason": "exact_version_prog_id_not_registered",
            })
            continue
        version_root = output_root / f"SW{year}"
        try:
            result = execute(version_root, version=year, run_id=f"{run_id}_sw{year}")
            actual_year = int((result.get("solidworks") or {}).get("year", 0) or 0)
            if result.get("status") != "ok" or actual_year != year:
                entries.append({
                    "year": year,
                    "prog_id": prog_id,
                    "status": "failed",
                    "reason": "regression_failed_or_version_mismatch",
                    "actual_year": actual_year or None,
                    "result": result,
                })
            else:
                entries.append({
                    "year": year,
                    "prog_id": prog_id,
                    "status": "pass",
                    "actual_year": actual_year,
                    "revision": (result.get("solidworks") or {}).get("revision"),
                    "report": result.get("report"),
                    "output_dir": result.get("output_dir"),
                })
        except Exception as exc:
            entries.append({
                "year": year,
                "prog_id": prog_id,
                "status": "failed",
                "reason": "regression_exception",
                "error": str(exc),
            })
    passed = sum(item["status"] == "pass" for item in entries)
    failed = sum(item["status"] == "failed" for item in entries)
    unavailable = sum(item["status"] == "unavailable" for item in entries)
    status = "failed" if failed else "pass" if passed == len(entries) else "partial" if passed else "blocked"
    report = {
        "status": status,
        "run_id": run_id,
        "target_years": list(target_years),
        "summary": {"pass": passed, "failed": failed, "unavailable": unavailable},
        "versions": entries,
        "manual_review_required": True,
        "limitations": [
            "unavailable 只表示本机未注册该精确版本，不代表该版本不受支持。",
            "矩阵必须核对回读年份；默认 ProgID 的成功不能替代指定版本结果。",
        ],
    }
    report_path = output_root / f"solidworks-drawing-version-matrix-{run_id}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="运行 SolidWorks 工程图跨版本真机矩阵")
    parser.add_argument("--output-dir", default=str(Path(tempfile.gettempdir()) / "solidworks_drawing_version_matrix"))
    parser.add_argument("--years", nargs="+", type=int, default=list(DEFAULT_YEARS))
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    report = run_matrix(
        Path(args.output_dir),
        years=args.years,
        run_id=args.run_id or None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
