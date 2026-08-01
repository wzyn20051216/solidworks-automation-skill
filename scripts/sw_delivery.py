"""SolidWorks BOM 清单与 Pack and Go 交付工具。"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
from typing import Any

import pywintypes
from win32com.client import gencache

try:
    from .sw_connect import get_com_member
    from .sw_document_data import read_custom_property
    from .sw_preflight import import_com_dependencies
except ImportError:
    from sw_connect import get_com_member
    from sw_document_data import read_custom_property
    from sw_preflight import import_com_dependencies


pythoncom, win32com_client, _VARIANT = import_com_dependencies()
SLDWORKS_TYPELIB_ID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
SW_DOC_TYPES = {
    ".sldprt": 1,
    ".sldasm": 2,
    ".slddrw": 3,
}


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


def _collect_new_outputs(target: Path, existing_files: dict[str, tuple[int, int] | None]) -> list[dict[str, Any]]:
    """@brief 收集本轮 Pack and Go 实际新写入或覆盖的输出文件。"""
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
    return outputs


def _document_dependency_paths(model, source_path: str) -> list[str]:
    """@brief 读取当前文档引用路径，用于校验 Pack and Go 是否漏包。"""
    try:
        dependencies = get_com_member(model, "GetDependencies2", False, True, False) or []
    except Exception:
        return []
    values = list(dependencies)
    source_name = Path(source_path).name.casefold()
    paths = []
    for index in range(1, len(values), 2):
        path = str(values[index] or "")
        if not path or Path(path).name.casefold() == source_name:
            continue
        paths.append(path)
    return paths


def _missing_dependency_paths(dependencies: list[str], outputs: list[dict[str, Any]]) -> list[str]:
    """@brief 按文件名检查原生 Pack and Go 输出是否缺少依赖文件。"""
    produced_names = {Path(item["path"]).name.casefold() for item in outputs}
    missing = []
    seen = set()
    for path in dependencies:
        name = Path(path).name.casefold()
        if name in seen:
            continue
        seen.add(name)
        if name not in produced_names:
            missing.append(path)
    return missing


def _active_solidworks_major() -> int | None:
    """@brief 返回当前 SolidWorks 类型库主版本，例如 SW2024 为 32。"""
    try:
        sw = win32com_client.GetActiveObject("SldWorks.Application")
        revision = str(get_com_member(sw, "RevisionNumber"))
        return int(revision.split(".", 1)[0])
    except Exception:
        return None


def _load_sldworks_typelib_module():
    """@brief 加载当前或最近注册的 SolidWorks 强类型 pywin32 模块。"""
    detected = _active_solidworks_major()
    candidates = [detected] if detected is not None else []
    candidates.extend(major for major in range(40, 19, -1) if major != detected)
    type_library_id = pywintypes.IID(SLDWORKS_TYPELIB_ID)
    errors = []
    for major in candidates:
        try:
            typelib = pythoncom.LoadRegTypeLib(type_library_id, major, 0, 0)
            attributes = typelib.GetLibAttr()
            return gencache.EnsureModule(
                attributes[0],
                attributes[1],
                attributes[3],
                attributes[4],
            )
        except Exception as exc:
            errors.append(f"{major}: {exc}")
    detail = "; ".join(errors[:3]) or "未发现注册版本"
    raise RuntimeError(f"无法加载 SolidWorks 类型库: {detail}")


def _model_doc_extension(model):
    """@brief 从强类型 IModelDoc2 取得正确的 IModelDocExtension。"""
    ole_object = getattr(model, "_oleobj_", None)
    if ole_object is None:
        return model.Extension
    module = _load_sldworks_typelib_module()
    typed_model = module.IModelDoc2(ole_object)
    extension = typed_model.Extension
    if extension is None:
        raise RuntimeError("SolidWorks 未返回 IModelDocExtension")
    return extension


def _coerce_dispatch(value):
    """@brief 将原始 IDispatch 包装为 pywin32 对象，普通假对象原样返回。"""
    if value is None:
        return None
    if hasattr(value, "_oleobj_") or hasattr(value, "SetSaveToName"):
        return value
    try:
        return win32com_client.Dispatch(value)
    except Exception:
        return value


def _get_pack_and_go(extension):
    """@brief 获取 IPackAndGo，兼容 pywin32 返回值和 by-ref 输出差异。"""
    errors: list[str] = []
    try:
        package = get_com_member(extension, "GetPackAndGo")
        if package is not None:
            return package
    except Exception as exc:
        errors.append(f"zero-arg: {exc}")

    output = _VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)
    member = getattr(extension, "GetPackAndGo", None)
    if callable(member):
        try:
            result = member(output)
            package = _coerce_dispatch(result) or _coerce_dispatch(output.value)
            if package is not None:
                return package
        except Exception as exc:
            errors.append(f"byref-method: {exc}")

    ole_object = getattr(extension, "_oleobj_", None)
    if ole_object is not None:
        try:
            dispid = ole_object.GetIDsOfNames("GetPackAndGo")
            result = ole_object.InvokeTypes(
                dispid,
                0,
                pythoncom.DISPATCH_METHOD,
                (pythoncom.VT_EMPTY, 0),
                ((pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, 0),),
                output,
            )
            package = _coerce_dispatch(result) or _coerce_dispatch(output.value)
            if package is not None:
                return package
        except Exception as exc:
            errors.append(f"byref-invoketypes: {exc}")

    detail = "; ".join(errors) or "未返回对象"
    raise RuntimeError(f"SolidWorks 未返回 IPackAndGo 对象: {detail}")


def _pywin32_pack_and_go(
    extension,
    target: Path,
    existing_files: dict[str, tuple[int, int] | None],
    *,
    include_drawings: bool,
    include_simulation_results: bool,
    include_toolbox_components: bool,
    include_suppressed: bool,
    flatten: bool,
) -> dict[str, Any]:
    """@brief 使用 pywin32 调用 SolidWorks 原生 Pack and Go。"""
    package = _get_pack_and_go(extension)
    package.IncludeDrawings = bool(include_drawings)
    package.IncludeSimulationResults = bool(include_simulation_results)
    package.IncludeToolboxComponents = bool(include_toolbox_components)
    package.IncludeSuppressed = bool(include_suppressed)
    package.FlattenToSingleFolder = bool(flatten)
    document_count = int(get_com_member(package, "GetDocumentNamesCount"))
    if not package.SetSaveToName(True, str(target) + os.sep):
        raise RuntimeError("IPackAndGo.SetSaveToName 拒绝目标目录")

    status_codes = _status_codes(extension.SavePackAndGo(package))
    outputs = _collect_new_outputs(target, existing_files)
    return {
        "backend": "pywin32",
        "document_count": document_count,
        "status_codes": status_codes,
        "outputs": outputs,
        "produced_count": len(outputs),
    }


def _comtypes_module():
    """@brief 加载 SolidWorks comtypes 早绑定模块。"""
    import comtypes.client

    detected = _active_solidworks_major()
    candidates = [detected] if detected is not None else []
    candidates.extend(major for major in range(40, 19, -1) if major != detected)
    errors = []
    for major in candidates:
        try:
            return comtypes.client.GetModule((SLDWORKS_TYPELIB_ID, major, 0))
        except Exception as exc:
            errors.append(f"{major}: {exc}")
    detail = "; ".join(errors[:3]) or "未发现注册版本"
    raise RuntimeError(f"无法加载 SolidWorks comtypes 类型库: {detail}")


def _extract_comtypes_model(value):
    """@brief 从 comtypes OpenDoc6 返回值中提取 IModelDoc2 指针。"""
    candidates = []

    def walk(item):
        if hasattr(item, "QueryInterface"):
            candidates.append(item)
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    if not candidates:
        raise RuntimeError(f"comtypes OpenDoc6 未返回 ModelDoc2: {value!r}")
    from comtypes.gen import SldWorks

    for candidate in candidates:
        try:
            return candidate.QueryInterface(SldWorks.IModelDoc2)
        except Exception:
            continue
    return candidates[0]


def _comtypes_active_model(sw, source_path: str):
    """@brief 在 OpenDoc6 返回空时，校验并返回当前活动文档。"""
    from comtypes.gen import SldWorks

    try:
        active = sw.ActiveDoc
    except Exception as exc:
        raise RuntimeError(f"comtypes 无法读取 ActiveDoc: {exc}") from exc
    if not active:
        raise RuntimeError("comtypes ActiveDoc 为空")
    document = active.QueryInterface(SldWorks.IModelDoc2)
    active_path = str(document.GetPathName() or "")
    if Path(active_path).resolve() != Path(source_path).resolve():
        raise RuntimeError(f"comtypes ActiveDoc 不是目标文档: {active_path}")
    return document


def _comtypes_pack_and_go(
    source_path: str,
    target: Path,
    existing_files: dict[str, tuple[int, int] | None],
    *,
    include_drawings: bool,
    include_simulation_results: bool,
    include_toolbox_components: bool,
    include_suppressed: bool,
    flatten: bool,
) -> dict[str, Any]:
    """@brief 使用 comtypes 早绑定兜底执行 SolidWorks 原生 Pack and Go。"""
    import comtypes.client

    _comtypes_module()
    from comtypes.gen import SldWorks
    major = _active_solidworks_major()
    progids = [f"SldWorks.Application.{major}"] if major is not None else []
    progids.append("SldWorks.Application")
    last_error = None
    sw = None
    for progid in progids:
        try:
            sw = comtypes.client.CreateObject(progid)
            break
        except Exception as exc:
            last_error = exc
    if sw is None:
        raise RuntimeError(f"comtypes 无法创建 SolidWorks 应用: {last_error}")

    document_type = SW_DOC_TYPES.get(Path(source_path).suffix.casefold())
    if document_type is None:
        raise ValueError(f"Pack and Go 不支持的文档类型: {source_path}")
    open_result = sw.OpenDoc6(str(source_path), document_type, 1 | 512, "")
    try:
        document = _extract_comtypes_model(open_result)
    except RuntimeError:
        document = _comtypes_active_model(sw, source_path)
    extension = document.Extension.QueryInterface(SldWorks.IModelDocExtension)
    package = extension.GetPackAndGo()
    package.IncludeDrawings = bool(include_drawings)
    package.IncludeSimulationResults = bool(include_simulation_results)
    package.IncludeToolboxComponents = bool(include_toolbox_components)
    package.IncludeSuppressed = bool(include_suppressed)
    package.FlattenToSingleFolder = bool(flatten)
    document_count = int(package.GetDocumentNamesCount())
    if not package.SetSaveToName(True, str(target) + os.sep):
        raise RuntimeError("IPackAndGo.SetSaveToName 拒绝目标目录")

    status_codes = _status_codes(extension.SavePackAndGo(package))
    outputs = _collect_new_outputs(target, existing_files)
    return {
        "backend": "comtypes",
        "document_count": document_count,
        "status_codes": status_codes,
        "outputs": outputs,
        "produced_count": len(outputs),
    }


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

    dependencies = _document_dependency_paths(model, source_path)
    fallback_errors = []
    try:
        extension = _model_doc_extension(model)
        result = _pywin32_pack_and_go(
            extension,
            target,
            existing_files,
            include_drawings=include_drawings,
            include_simulation_results=include_simulation_results,
            include_toolbox_components=include_toolbox_components,
            include_suppressed=include_suppressed,
            flatten=flatten,
        )
    except Exception as exc:
        fallback_errors.append(f"pywin32: {exc}")
        result = _comtypes_pack_and_go(
            source_path,
            target,
            existing_files,
            include_drawings=include_drawings,
            include_simulation_results=include_simulation_results,
            include_toolbox_components=include_toolbox_components,
            include_suppressed=include_suppressed,
            flatten=flatten,
        )

    missing_dependencies = _missing_dependency_paths(dependencies, result["outputs"])
    success = (
        bool(result["status_codes"])
        and all(code == 0 for code in result["status_codes"])
        and bool(result["outputs"])
        and not missing_dependencies
    )
    return {
        "success": success,
        "source": source_path,
        "output_dir": str(target),
        "backend": result["backend"],
        "document_count": result["document_count"],
        "status_codes": result["status_codes"],
        "outputs": result["outputs"],
        "produced_count": result["produced_count"],
        "dependencies": dependencies,
        "missing_dependencies": missing_dependencies,
        "fallback_errors": fallback_errors,
        "options": {
            "include_drawings": include_drawings,
            "include_simulation_results": include_simulation_results,
            "include_toolbox_components": include_toolbox_components,
            "include_suppressed": include_suppressed,
            "flatten": flatten,
        },
    }
