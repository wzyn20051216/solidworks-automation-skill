"""只读提取 SolidWorks 已显示尺寸的公差信息，输出须人工复核。

模型遍历不保证覆盖所有配置、隐藏尺寸或图纸视图。不会修改用户文档；文件输出不覆盖已有文件。
"""
from __future__ import annotations

import csv
import math
import os
import sys
from pathlib import Path
from typing import Any

try:
    from .sw_connect import get_com_member
except ImportError:
    from sw_connect import get_com_member

FIELDS = ("name", "owner", "dimension_kind", "unit", "nominal", "tolerance_type", "lower", "upper", "status")
TOLERANCE_TYPES = {0: "none", 1: "basic", 2: "bilateral", 3: "limit", 4: "symmetric",
                   5: "min", 6: "max", 7: "fit", 8: "fit_with_tol", 9: "fit_tol_only"}


def _optional(obj: Any, name: str, *args: Any) -> Any:
    if obj is None:
        return None
    try:
        return get_com_member(obj, name, *args)
    except Exception:
        return None


def _tolerance_bound(tolerance: Any, method: str) -> tuple[float | None, str | None]:
    """2026 API: 返回状态码，实际值通过 VT_BYREF | VT_R8 输出。"""
    try:
        import pythoncom
        from win32com.client import VARIANT
        output = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, 0.0)
        status = get_com_member(tolerance, method, output)
        value = output.value
        if isinstance(status, bool) or status != 0 or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None, f"{method} 返回非有效状态或非有限值"
        return float(value), None
    except Exception as exc:
        return None, f"{method} 读取失败: {type(exc).__name__}"


def _dimension_row(dimension: Any, owner: str) -> tuple[dict[str, Any] | None, str | None]:
    name = str(_optional(dimension, "FullName") or "")
    kind = _optional(dimension, "GetType")
    # swDimensionParamType_e: double linear=0，double angular=1。
    if isinstance(kind, bool) or kind not in (0, 1):
        return None, f"{name or '<unnamed>'}: 未支持的尺寸类型 {kind!r}"
    value = _optional(dimension, "GetSystemValue3", 1, None)  # swThisConfiguration
    if isinstance(value, (tuple, list)):
        value = value[0] if len(value) == 1 else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None, f"{name or '<unnamed>'}: 无法读取当前配置的尺寸值"
    scale = 1000.0 if kind == 0 else 180.0 / math.pi
    tolerance = _optional(dimension, "Tolerance")
    type_code = _optional(tolerance, "Type")
    if isinstance(type_code, bool) or not isinstance(type_code, int) or type_code not in TOLERANCE_TYPES:
        return None, f"{name or '<unnamed>'}: 公差类型不可用或未支持"
    lower = upper = None
    row_status = "not_toleranced" if type_code in (0, 1) else "measured"
    if type_code not in (0, 1):
        lower, error_min = _tolerance_bound(tolerance, "GetMinValue2")
        upper, error_max = _tolerance_bound(tolerance, "GetMaxValue2")
        if error_min or error_max:
            row_status = "incomplete"
        if lower is not None:
            lower *= scale
        if upper is not None:
            upper *= scale
    return {"name": name, "owner": owner, "dimension_kind": "linear" if kind == 0 else "angular",
            "unit": "mm" if kind == 0 else "deg", "nominal": float(value) * scale,
            "tolerance_type": TOLERANCE_TYPES[type_code], "lower": lower, "upper": upper,
            "status": row_status}, None


def extract_tolerances(model: Any) -> dict[str, Any]:
    """读取零件/装配特征或工程图视图上的已显示尺寸，不宣称完整覆盖。"""
    doc_type = _optional(model, "GetType")
    if doc_type not in (1, 2, 3):
        return {"status": "blocked", "rows": [], "warnings": ["文档类型未知或不受支持"], "reviewRequired": True}
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    owner = _optional(model, "GetFirstView" if doc_type == 3 else "FirstFeature")
    if owner is None:
        return {"status": "blocked", "rows": [], "warnings": ["无法读取文档的特征或视图，不能判断尺寸是否为空"], "reviewRequired": True}
    for _ in range(20000):
        if owner is None:
            break
        owner_name = str(_optional(owner, "GetName2") or _optional(owner, "Name") or "")
        display = _optional(owner, "GetFirstDisplayDimension5") or _optional(owner, "GetFirstDisplayDimension")
        for _ in range(2000):
            if display is None:
                break
            dimension = _optional(display, "GetDimension2", 0) or _optional(display, "GetDimension")
            if dimension is None:
                warnings.append("部分显示尺寸无法解析")
            else:
                row, error = _dimension_row(dimension, owner_name)
                if error:
                    warnings.append(error)
                elif row is not None:
                    # 同一模型尺寸可能经特征树重复枚举；无名称时保留并提示人工检查。
                    key = row["name"] if doc_type != 3 else f"{owner_name}\x00{row['name']}"
                    if not row["name"] or key not in seen:
                        rows.append(row)
                        if row["name"]:
                            seen.add(key)
                        else:
                            warnings.append("存在未命名尺寸，无法可靠去重")
            display = _optional(owner, "GetNextDisplayDimension", display)
        else:
            warnings.append("显示尺寸遍历达到上限，结果不完整")
        owner = _optional(owner, "GetNextView" if doc_type == 3 else "GetNextFeature")
    else:
        warnings.append("特征或视图遍历达到上限，结果不完整")
    if any(row["status"] == "incomplete" for row in rows):
        warnings.append("部分公差值未能读取，不能按零处理")
    warnings.append("仅覆盖当前配置的已显示尺寸，隐藏尺寸及其他配置需另行核对")
    return {"status": "review_required", "rows": rows, "warnings": warnings, "reviewRequired": True}


def write_csv(rows: list[dict[str, Any]], destination: str | Path) -> Path:
    path = Path(destination).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {key: ("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
                    for key, value in row.items()}
            writer.writerow(safe)
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="只读提取已显示尺寸的公差；输出必须是新文件。")
    parser.add_argument("model", help="已保存的 SLDPRT、SLDASM 或 SLDDRW")
    parser.add_argument("--output", required=True, help="不覆盖的 CSV 路径")
    args = parser.parse_args(argv)
    try:
        from .sw_session import SolidWorksSession
        from .sw_read_guard import SolidWorksReadGuard
    except ImportError:
        from sw_session import SolidWorksSession
        from sw_read_guard import SolidWorksReadGuard
    source = Path(os.path.expandvars(args.model)).expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() not in {".sldprt", ".sldasm", ".slddrw"}:
        parser.error("需要已保存的 SolidWorks 模型或图纸")
    with SolidWorksReadGuard():
        with SolidWorksSession(visible=True) as session:
            model = session.open(str(source), read_only=True, silent=True)
            result = extract_tolerances(model)
    if result["status"] == "blocked":
        print(json.dumps(result, ensure_ascii=True))
        return 1
    result["csv_path"] = str(write_csv(result["rows"], args.output))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
