"""SolidWorks BOM 清单与 Pack and Go 交付工具。"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
from typing import Any

try:
    from .sw_connect import get_com_member
    from .sw_document_data import read_custom_property
except ImportError:
    from sw_connect import get_com_member
    from sw_document_data import read_custom_property


def _file_signature(path: Path):
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _property_value(model, configuration_name: str, names: tuple[str, ...]) -> str:
    if model is None:
        return ""
    for scope in (configuration_name, ""):
        for name in names:
            try:
                value = read_custom_property(model, name, configuration_name=scope)
            except Exception:
                continue
            if value["exists"]:
                return value["resolved"] or value["raw"]
    return ""


def collect_assembly_bom(model, *, include_excluded: bool = False) -> list[dict[str, Any]]:
    """收集装配体顶层组件并按文件路径和配置汇总数量。"""
    if int(get_com_member(model, "GetType")) != 2:
        raise ValueError("BOM 清单只支持装配体文档")
    components = get_com_member(model, "GetComponents", False) or []
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for component in components:
        excluded = bool(get_com_member(component, "ExcludeFromBOM"))
        if excluded and not include_excluded:
            continue
        path = str(get_com_member(component, "GetPathName") or "")
        configuration = str(get_com_member(component, "ReferencedConfiguration") or "")
        name = str(get_com_member(component, "Name2") or Path(path).stem or "虚拟组件")
        key = ((path or name).casefold(), configuration.casefold())
        if key in grouped:
            grouped[key]["quantity"] += 1
            continue
        referenced_model = get_com_member(component, "GetModelDoc2")
        part_number = _property_value(
            referenced_model,
            configuration,
            ("PartNumber", "Part Number", "零件代号", "零件号"),
        ) or Path(path).stem or name
        grouped[key] = {
            "item": 0,
            "part_number": part_number,
            "description": _property_value(referenced_model, configuration, ("Description", "描述")),
            "material": _property_value(referenced_model, configuration, ("Material", "材料")),
            "quantity": 1,
            "file": path,
            "configuration": configuration,
            "component": name,
            "excluded_from_bom": excluded,
        }
    rows = sorted(grouped.values(), key=lambda row: (row["part_number"].casefold(), row["configuration"].casefold()))
    for index, row in enumerate(rows, start=1):
        row["item"] = index
    return rows


def export_assembly_bom_csv(
    model,
    output_path,
    *,
    include_excluded: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """导出 UTF-8 BOM CSV，并返回文件大小与 SHA-256 证据。"""
    target = Path(os.path.expandvars(str(output_path))).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"BOM 文件已存在，未允许覆盖: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    before = _file_signature(target)
    rows = collect_assembly_bom(model, include_excluded=include_excluded)
    headers = [
        "item", "part_number", "description", "material", "quantity",
        "file", "configuration", "component", "excluded_from_bom",
    ]
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    after = _file_signature(target)
    produced = after is not None and after != before
    return {
        "success": produced,
        "path": str(target),
        "rows": rows,
        "row_count": len(rows),
        "quantity_total": sum(row["quantity"] for row in rows),
        "size_bytes": after[0] if after else 0,
        "sha256": _sha256(target) if produced else "",
        "produced_this_run": produced,
        "review_required": True,
        "limitations": ["CSV 为装配组件属性清单，必须与 SolidWorks 原生 BOM 和工程图人工核对"],
    }


def _status_codes(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    try:
        return [int(item) for item in value]
    except TypeError:
        return [int(value)]


def pack_and_go(
    model,
    output_dir,
    *,
    include_drawings: bool = True,
    include_simulation_results: bool = False,
    include_toolbox_components: bool = True,
    include_suppressed: bool = False,
    flatten: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """使用 SolidWorks 原生 Pack and Go 保存当前文档及引用文件。"""
    source_path = str(get_com_member(model, "GetPathName") or "")
    if not source_path or not Path(source_path).is_file():
        raise ValueError("当前文档必须先保存到磁盘，才能执行 Pack and Go")
    target = Path(os.path.expandvars(str(output_dir))).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    existing_files = {str(path): _file_signature(path) for path in target.rglob("*") if path.is_file()}
    if existing_files and not overwrite:
        raise FileExistsError(f"Pack and Go 目标目录非空，未允许覆盖: {target}")

    extension = model.Extension
    package = extension.GetPackAndGo()
    if package is None:
        raise RuntimeError("SolidWorks 未返回 IPackAndGo 对象")
    package.IncludeDrawings = bool(include_drawings)
    package.IncludeSimulationResults = bool(include_simulation_results)
    package.IncludeToolboxComponents = bool(include_toolbox_components)
    package.IncludeSuppressed = bool(include_suppressed)
    package.FlattenToSingleFolder = bool(flatten)
    document_count = int(package.GetDocumentNamesCount())
    if not package.SetSaveToName(True, str(target) + os.sep):
        raise RuntimeError("IPackAndGo.SetSaveToName 拒绝目标目录")

    status_codes = _status_codes(extension.SavePackAndGo(package))
    outputs = []
    for path in sorted(item for item in target.rglob("*") if item.is_file()):
        after = _file_signature(path)
        before = existing_files.get(str(path))
        produced = after is not None and after != before
        if produced:
            outputs.append({
                "path": str(path),
                "size_bytes": after[0],
                "sha256": _sha256(path),
                "produced_this_run": True,
            })
    success = bool(status_codes) and all(code == 0 for code in status_codes) and bool(outputs)
    return {
        "success": success,
        "source": source_path,
        "output_dir": str(target),
        "document_count": document_count,
        "status_codes": status_codes,
        "outputs": outputs,
        "produced_count": len(outputs),
        "options": {
            "include_drawings": include_drawings,
            "include_simulation_results": include_simulation_results,
            "include_toolbox_components": include_toolbox_components,
            "include_suppressed": include_suppressed,
            "flatten": flatten,
        },
    }
