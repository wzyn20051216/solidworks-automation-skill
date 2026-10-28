"""
@file sw_tolerance_extract.py
@brief 从 SolidWorks 零件/装配/工程图的尺寸中批量抽取公差，输出表格与 CSV。

对标 t84RT/SW-software---Macro-command 中的“自动提取公差”宏（第三方 VBA，与达索无隶属关系），
这里用 Python 重写并把可验证部分（公差分类、显示格式化、汇总统计）与需真机的 COM 尺寸遍历分离。

- 纯函数：`tolerance_type_label`、`format_tolerance`、`normalize_tolerance_row`、`summarize_tolerances`，
  可在无 SolidWorks 环境下离线单测。
- COM 函数：`extract_tolerances` 遍历特征/视图的 IDisplayDimension -> IDimension -> ITolerance。
- 输出：`write_tolerance_csv` 写 CSV，`write_tolerance_summary_property` 可选写回自定义属性。

长度统一以毫米（mm）呈现；SolidWorks 系统值为米，读取后乘 1000。
能力等级：pilot——公差逻辑已单测，尺寸遍历与 ITolerance 读取需真机与图纸人工复核。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from .sw_connect import get_com_member, safe_get_com_member
except ImportError:  # 直接以脚本方式运行
    from sw_connect import get_com_member, safe_get_com_member

# swTolType_e
SW_TOL_NONE = 0
SW_TOL_BASIC = 1
SW_TOL_BILAT = 2
SW_TOL_LIMIT = 3
SW_TOL_SYMMETRIC = 4
SW_TOL_MIN = 5
SW_TOL_MAX = 6
SW_TOL_FIT = 7
SW_TOL_FITWITHTOL = 8
SW_TOL_FITTOLONLY = 9

_TOL_LABELS = {
    SW_TOL_NONE: "none",
    SW_TOL_BASIC: "basic",
    SW_TOL_BILAT: "bilateral",
    SW_TOL_LIMIT: "limit",
    SW_TOL_SYMMETRIC: "symmetric",
    SW_TOL_MIN: "min",
    SW_TOL_MAX: "max",
    SW_TOL_FIT: "fit",
    SW_TOL_FITWITHTOL: "fit_with_tol",
    SW_TOL_FITTOLONLY: "fit_tol_only",
}

_TOLERANCED_TYPES = {
    SW_TOL_BILAT,
    SW_TOL_LIMIT,
    SW_TOL_SYMMETRIC,
    SW_TOL_MIN,
    SW_TOL_MAX,
    SW_TOL_FIT,
    SW_TOL_FITWITHTOL,
    SW_TOL_FITTOLONLY,
}

CSV_COLUMNS = ["name", "feature", "nominal_mm", "type", "upper_mm", "lower_mm", "toleranced", "display"]


def tolerance_type_label(type_code: int) -> str:
    """@brief 将 swTolType_e 数值转成稳定英文标签。"""
    return _TOL_LABELS.get(int(type_code), f"unknown({int(type_code)})")


def is_toleranced(type_code: int) -> bool:
    """@brief 判断该公差类型是否携带实际公差（排除 none/basic）。"""
    return int(type_code) in _TOLERANCED_TYPES


def _fmt(value: float) -> str:
    """@brief 数值格式化：去掉多余尾零。"""
    return f"{float(value):g}"


def format_tolerance(nominal_mm: float, type_code: int, upper_mm: float, lower_mm: float) -> str:
    """@brief 生成公差显示串。

    @param nominal_mm 公称尺寸 mm。
    @param type_code swTolType_e。
    @param upper_mm 上偏差 mm（相对公称，通常为正）。
    @param lower_mm 下偏差 mm（相对公称，通常为负）。
    @return 例如 "50 +0.05/-0.02"、"50 ±0.05"、"50 (10-15 limit)"。
    """
    nominal = _fmt(nominal_mm)
    code = int(type_code)
    if code in {SW_TOL_NONE, SW_TOL_BASIC}:
        return nominal
    if code == SW_TOL_SYMMETRIC:
        return f"{nominal} ±{_fmt(abs(upper_mm))}"
    if code == SW_TOL_MIN:
        return f"{nominal} min"
    if code == SW_TOL_MAX:
        return f"{nominal} max"
    if code == SW_TOL_LIMIT:
        upper = _fmt(nominal_mm + upper_mm)
        lower = _fmt(nominal_mm + lower_mm)
        return f"{upper}/{lower}"
    # bilateral / fit* 一律用上下偏差表示
    up = upper_mm
    lo = lower_mm
    sign_up = "+" if up >= 0 else "-"
    sign_lo = "+" if lo >= 0 else "-"
    return f"{nominal} {sign_up}{_fmt(abs(up))}/{sign_lo}{_fmt(abs(lo))}"


def normalize_tolerance_row(
    *,
    name: str,
    feature: str,
    nominal_mm: float,
    type_code: int,
    upper_mm: float,
    lower_mm: float,
) -> dict[str, Any]:
    """@brief 把一条原始尺寸公差数据归一为标准行（含显示串与是否带公差）。"""
    toleranced = is_toleranced(type_code)
    return {
        "name": str(name),
        "feature": str(feature),
        "nominal_mm": round(float(nominal_mm), 6),
        "type": tolerance_type_label(type_code),
        "upper_mm": round(float(upper_mm), 6) if toleranced else 0.0,
        "lower_mm": round(float(lower_mm), 6) if toleranced else 0.0,
        "toleranced": toleranced,
        "display": format_tolerance(nominal_mm, type_code, upper_mm, lower_mm),
    }


def summarize_tolerances(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """@brief 汇总统计：总数、带公差数、按类型计数、最紧公差带。"""
    by_type: dict[str, int] = {}
    tightest = None
    tightest_name = None
    toleranced_count = 0
    for row in rows:
        label = str(row.get("type", "unknown"))
        by_type[label] = by_type.get(label, 0) + 1
        if row.get("toleranced"):
            toleranced_count += 1
            band = abs(float(row.get("upper_mm", 0.0)) - float(row.get("lower_mm", 0.0)))
            if band > 0.0 and (tightest is None or band < tightest):
                tightest = band
                tightest_name = str(row.get("name", ""))
    return {
        "total": len(rows),
        "toleranced": toleranced_count,
        "by_type": by_type,
        "tightest_band_mm": tightest,
        "tightest_dimension": tightest_name,
    }


# ---------------------------------------------------------------------------
# COM 遍历（pilot，需真机验证）
# ---------------------------------------------------------------------------


def _maybe(obj, name: str, *args):
    """@brief 防御式读取 COM 成员；成员不存在或调用失败时返回 None，不抛出。"""
    if obj is None:
        return None
    try:
        return safe_get_com_member(obj, name, *args)
    except Exception:  # noqa: BLE001
        return None


def _read_tolerance(dimension) -> tuple[int, float, float]:
    """@brief 从 IDimension 读取公差类型与上下偏差（mm）。"""
    tol = _maybe(dimension, "Tolerance")
    if tol is None:
        return SW_TOL_NONE, 0.0, 0.0
    type_code = int(_maybe(tol, "Type") or SW_TOL_NONE)
    upper = _maybe(tol, "GetMaxValue2")
    lower = _maybe(tol, "GetMinValue2")
    if upper is None:
        upper = _maybe(tol, "GetMaxValue")
    if lower is None:
        lower = _maybe(tol, "GetMinValue")
    upper_mm = float(upper) * 1000.0 if upper is not None else 0.0
    lower_mm = float(lower) * 1000.0 if lower is not None else 0.0
    return type_code, upper_mm, lower_mm


def _dimension_nominal_mm(dimension) -> float:
    """@brief 读取尺寸公称值（系统米->毫米）。"""
    value = _maybe(dimension, "GetSystemValue3", 0, None)
    if value is None:
        value = _maybe(dimension, "Value")
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    return float(value) * 1000.0 if value is not None else 0.0


def _iter_display_dimensions_of(owner):
    """@brief 遍历特征或视图上的 IDisplayDimension（兼容链式与数组接口）。"""
    current = _maybe(owner, "GetFirstDisplayDimension5") or _maybe(owner, "GetFirstDisplayDimension")
    while current is not None:
        yield current
        current = _maybe(owner, "GetNextDisplayDimension", current)


def _iter_feature_chain(model):
    """@brief 遍历模型顶层特征链。"""
    feature = _maybe(model, "FirstFeature")
    guard = 0
    while feature is not None and guard < 20000:
        yield feature
        feature = _maybe(feature, "GetNextFeature")
        guard += 1


def extract_tolerances(model) -> list[dict[str, Any]]:
    """@brief 遍历零件/装配特征或工程图视图，抽取每个尺寸的公差行。

    对零件/装配：遍历特征链，读每个特征挂的 DisplayDimension。
    对工程图：遍历图纸各视图的 DisplayDimension。
    """
    rows: list[dict[str, Any]] = []
    doc_type = int(_maybe(model, "GetType") or 1)

    def collect(owner, feature_name: str) -> None:
        for disp in _iter_display_dimensions_of(owner):
            dimension = _maybe(disp, "GetDimension2", 0) or _maybe(disp, "GetDimension")
            if dimension is None:
                continue
            name = str(_maybe(dimension, "FullName") or _maybe(dimension, "Name") or "")
            type_code, upper_mm, lower_mm = _read_tolerance(dimension)
            rows.append(
                normalize_tolerance_row(
                    name=name,
                    feature=feature_name,
                    nominal_mm=_dimension_nominal_mm(dimension),
                    type_code=type_code,
                    upper_mm=upper_mm,
                    lower_mm=lower_mm,
                )
            )

    if doc_type == 3:  # swDocDRAWING
        view = _maybe(model, "GetFirstView")
        while view is not None:
            view_name = str(_maybe(view, "GetName2") or _maybe(view, "Name") or "view")
            collect(view, view_name)
            view = _maybe(view, "GetNextView")
    else:
        for feature in _iter_feature_chain(model):
            feature_name = str(_maybe(feature, "Name") or "")
            collect(feature, feature_name)

    return rows


def write_tolerance_csv(rows: Sequence[Mapping[str, Any]], output_path: str | Path) -> Path:
    """@brief 将公差行写入 UTF-8 BOM CSV（Excel 中文友好）。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    return path


def write_tolerance_summary_property(model, summary: Mapping[str, Any]) -> bool:
    """@brief 把公差汇总写入模型自定义属性（可选）。"""
    extension = _maybe(model, "Extension")
    manager = _maybe(extension, "CustomPropertyManager", "")
    if manager is None:
        return False
    total = int(summary.get("total", 0))
    toleranced = int(summary.get("toleranced", 0))
    tightest = summary.get("tightest_band_mm")
    manager.Add3("公差尺寸总数", 30, str(total), 2)
    manager.Add3("带公差尺寸数", 30, str(toleranced), 2)
    manager.Add3("最紧公差带", 30, f"{tightest:g} mm" if tightest else "无", 2)
    return True


def extract_and_export(model, output_csv: str | Path, *, write_property: bool = False) -> dict[str, Any]:
    """@brief 一站式：抽取公差 -> 写 CSV -> 汇总（可选写属性）。"""
    rows = extract_tolerances(model)
    csv_path = write_tolerance_csv(rows, output_csv)
    summary = summarize_tolerances(rows)
    if write_property:
        summary["property_written"] = write_tolerance_summary_property(model, summary)
    return {"csv_path": str(csv_path), "rows": rows, "summary": summary}


def _iter_rows_for_cli(rows: Iterable[Mapping[str, Any]]) -> None:
    """@brief 在终端打印公差行。"""
    for row in rows:
        print(f"  {row['name'] or '<匿名>'} [{row['feature']}]: {row['display']} ({row['type']})")


def main(argv: Sequence[str] | None = None) -> int:
    """@brief 命令行入口：打开模型/图纸，抽取公差并导出 CSV。"""
    import argparse

    parser = argparse.ArgumentParser(description="从 SolidWorks 模型/工程图抽取尺寸公差并导出 CSV。")
    parser.add_argument("input", help="SLDPRT/SLDASM/SLDDRW 文件路径；传 active 使用当前活动文档。")
    parser.add_argument("--output-csv", default="tolerances.csv", help="CSV 输出路径。")
    parser.add_argument("--write-property", action="store_true", help="把公差汇总写回模型自定义属性。")
    args = parser.parse_args(argv)

    from sw_session import SolidWorksSession

    session = SolidWorksSession(visible=True)
    model = session.active_doc if args.input.strip().lower() == "active" else session.open(args.input)
    if model is None:
        raise RuntimeError("未获取到可用的 SolidWorks 文档")
    result = extract_and_export(model, args.output_csv, write_property=args.write_property)
    print(f"CSV: {result['csv_path']}")
    print(f"汇总: {result['summary']}")
    _iter_rows_for_cli(result["rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
