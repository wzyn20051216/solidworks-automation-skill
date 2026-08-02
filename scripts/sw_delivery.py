"""SolidWorks BOM 清单与 Pack and Go 交付工具。"""
from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import shutil
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


def build_bom_traceability(bom_rows, *, model_path="", drawing_path="", review_path="") -> dict[str, Any]:
    """@brief 建立 BOM、模型、工程图和复核报告之间的可追溯关系。"""
    rows = list(bom_rows or [])
    checks = [
        {"id": "bom-not-empty", "status": "pass" if rows else "warning", "message": "BOM 包含组件行" if rows else "BOM 为空，需要确认是否为单零件或读取失败"},
        {"id": "model-reference", "status": "pass" if model_path else "warning", "message": "已关联模型路径" if model_path else "未提供模型路径"},
        {"id": "drawing-reference", "status": "pass" if drawing_path else "warning", "message": "已关联工程图路径" if drawing_path else "未提供工程图路径"},
        {"id": "review-reference", "status": "pass" if review_path else "warning", "message": "已关联复核报告" if review_path else "未提供复核报告"},
    ]
    return {
        "status": "pass" if rows and model_path and drawing_path else "warning",
        "stage": "review",
        "bom_row_count": len(rows),
        "quantity_total": sum(int(row.get("quantity") or 0) for row in rows),
        "model_path": str(model_path or ""),
        "drawing_path": str(drawing_path or ""),
        "review_path": str(review_path or ""),
        "rows": [{"item": row.get("item"), "part_number": row.get("part_number"), "file": row.get("file"), "configuration": row.get("configuration"), "quantity": row.get("quantity")} for row in rows],
        "checks": checks,
        "manual_review_required": True,
        "retryable": False,
        "error_code": None,
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


def _safe_staged_destination(source: Path, sources: list[Path], target: Path, *, flatten: bool) -> Path:
    """@brief 计算依赖暂存路径，并阻止写出目标目录。"""
    target_root = target.resolve()
    if flatten:
        relative = Path(source.name)
    else:
        try:
            common_root = Path(os.path.commonpath([str(item.resolve()) for item in sources]))
            relative = source.resolve().relative_to(common_root)
        except (OSError, ValueError):
            # 不同盘符或外部引用没有共同根目录时，使用稳定的外部引用目录。
            relative = Path("external") / hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:12] / source.name
    destination = (target_root / relative).resolve()
    try:
        destination.relative_to(target_root)
    except ValueError as exc:
        raise RuntimeError(f"Pack and Go 暂存路径越界: {destination}") from exc
    return destination


def _stage_pack_and_go_dependencies(
    source_path: str,
    dependencies: list[str],
    target: Path,
    existing_files: dict[str, tuple[int, int] | None],
    *,
    flatten: bool,
) -> dict[str, Any]:
    """@brief 在原生清单不完整时生成可审计的依赖暂存包。

    该后端只复制 SolidWorks 已报告的源文件，不修改 CAD 文件内容，也不宣称
    这是原生 Pack and Go。每个文件和 manifest 都带有本轮产物与 SHA-256 证据。
    """
    raw_sources = [str(Path(source_path).expanduser().resolve()), *dependencies]
    source_paths: list[Path] = []
    seen_sources: set[str] = set()
    for raw in raw_sources:
        path = Path(raw).expanduser().resolve()
        key = str(path).casefold()
        if key in seen_sources:
            continue
        seen_sources.add(key)
        if not path.is_file():
            raise FileNotFoundError(f"Pack and Go 暂存源文件不存在: {path}")
        source_paths.append(path)

    destinations: dict[str, Path] = {}
    for source in source_paths:
        destination = _safe_staged_destination(source, source_paths, target, flatten=flatten)
        key = str(destination).casefold()
        previous = destinations.get(key)
        if previous is not None and previous.resolve() != source.resolve():
            raise RuntimeError(f"Pack and Go 暂存文件重名冲突: {previous.name} <- {previous}, {source}")
        destinations[key] = source

    staged_files: list[dict[str, Any]] = []
    for key, source in destinations.items():
        destination = _safe_staged_destination(source, source_paths, target, flatten=flatten)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == destination.resolve():
            raise RuntimeError(f"Pack and Go 暂存目标不能覆盖源文件: {source}")
        shutil.copy2(source, destination)
        signature = _file_signature(destination)
        if signature is None or signature[0] <= 0:
            raise RuntimeError(f"Pack and Go 暂存文件为空: {destination}")
        staged_files.append({
            "source": str(source),
            "path": str(destination),
            "size_bytes": signature[0],
            "sha256": _sha256(destination),
            "produced_this_run": str(destination) not in existing_files or existing_files.get(str(destination)) != signature,
        })

    manifest_path = target / "cadstudio-pack-manifest.json"
    if manifest_path.exists() and str(manifest_path) in existing_files:
        raise FileExistsError(f"Pack and Go 暂存清单已存在，未允许覆盖: {manifest_path}")
    manifest = {
        "schemaVersion": "1.0",
        "backend": "staged_dependencies",
        "nativeFormat": "SolidWorks",
        "source": str(Path(source_path).expanduser().resolve()),
        "dependencies": [str(Path(item).expanduser().resolve()) for item in dependencies],
        "files": staged_files,
        "limitations": [
            "这是基于 SolidWorks GetDependencies2 的本地暂存包，不是原生 IPackAndGo 清单",
            "外部引用、Toolbox、配置和工程图仍需人工在 SolidWorks 中复核",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_signature = _file_signature(manifest_path)
    if manifest_signature is None or manifest_signature[0] <= 0:
        raise RuntimeError(f"Pack and Go 暂存清单为空: {manifest_path}")
    staged_files.append({
        "path": str(manifest_path),
        "size_bytes": manifest_signature[0],
        "sha256": _sha256(manifest_path),
        "produced_this_run": str(manifest_path) not in existing_files or existing_files.get(str(manifest_path)) != manifest_signature,
        "kind": "manifest",
    })
    return {
        "backend": "staged_dependencies",
        "outputs": staged_files,
        "produced_count": len(staged_files),
        "manifest": str(manifest_path),
    }


def _comtypes_document_names(package, document_count: int) -> list[str]:
    """@brief 通过 IPackAndGo::IGetDocumentNames 读取固定长度原生数组。

    SW2024 的 Automation ``GetDocumentNames`` 在部分 Python COM 代理上只返回
    顶层文档。官方同时提供了基于 ``GetDocumentNamesCount`` 的原生
    ``IGetDocumentNames``；这里显式分配 BSTR 数组，避免 SAFEARRAY 封送差异。
    """
    if document_count <= 0:
        return []
    names = (ctypes.c_wchar_p * document_count)()
    # comtypes 会自动分配 [out] 数组，只需传入 Count。
    result = package.IGetDocumentNames(document_count)
    # comtypes 对 [out, retval] 的 VARIANT_BOOL 可能直接返回 bool，也可能返回元组。
    if result is False:
        raise RuntimeError("IPackAndGo.IGetDocumentNames 返回 False")
    returned_names = result[0] if isinstance(result, tuple) and result else result
    if isinstance(returned_names, (list, tuple)):
        return [str(item) for item in returned_names if item]
    # 少数生成器仍直接填充本地缓冲；保留兼容路径。
    return [str(item) for item in names if item]


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
    """@brief 获取 IPackAndGo，优先遵循当前类型库的无参数返回值签名。"""
    errors: list[str] = []
    try:
        package = get_com_member(extension, "GetPackAndGo")
        if package is not None:
            return package
    except Exception as exc:
        errors.append(f"zero-arg: {exc}")

    ole_object = getattr(extension, "_oleobj_", None)
    if ole_object is not None:
        try:
            dispid = ole_object.GetIDsOfNames("GetPackAndGo")
            result = ole_object.InvokeTypes(
                dispid,
                0,
                pythoncom.DISPATCH_METHOD,
                (pythoncom.VT_DISPATCH, 0),
                (),
            )
            package = _coerce_dispatch(result)
            if package is not None:
                return package
        except Exception as exc:
            errors.append(f"noarg-invoketypes: {exc}")

    # 仅保留给旧版异常包装器的兼容路径；当前官方类型库不是 by-ref 签名。
    output = _VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)
    member = getattr(extension, "GetPackAndGo", None)
    if callable(member):
        try:
            result = member(output)
            package = _coerce_dispatch(result) or _coerce_dispatch(output.value)
            if package is not None:
                return package
        except Exception as exc:
            errors.append(f"legacy-byref-method: {exc}")

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


def _connect_comtypes_solidworks(client, progids: list[str]):
    """@brief 优先附着活动实例，返回应用对象、所有权标记和最后错误。"""
    last_error = None
    for progid in progids:
        try:
            return client.GetActiveObject(progid), False, last_error
        except Exception as exc:
            last_error = exc
    for progid in progids:
        try:
            return client.CreateObject(progid), True, last_error
        except Exception as exc:
            last_error = exc
    return None, False, last_error


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
    dependencies: list[str] | None = None,
) -> dict[str, Any]:
    """@brief 使用 comtypes 早绑定兜底执行 SolidWorks 原生 Pack and Go。"""
    import comtypes.client

    _comtypes_module()
    from comtypes.gen import SldWorks
    major = _active_solidworks_major()
    progids = [f"SldWorks.Application.{major}"] if major is not None else []
    progids.append("SldWorks.Application")
    sw, started_here, last_error = _connect_comtypes_solidworks(comtypes.client, progids)
    if sw is None:
        raise RuntimeError(f"comtypes 无法创建 SolidWorks 应用: {last_error}")

    document = None
    try:
        document_type = SW_DOC_TYPES.get(Path(source_path).suffix.casefold())
        if document_type is None:
            raise ValueError(f"Pack and Go 不支持的文档类型: {source_path}")
        # 强制加载完整模型并覆盖轻量化默认设置，否则 Pack and Go 只会看到顶层文档。
        open_result = sw.OpenDoc6(str(source_path), document_type, 1 | 16 | 64 | 512, "")
        try:
            document = _extract_comtypes_model(open_result)
        except RuntimeError:
            document = _comtypes_active_model(sw, source_path)
        extension = document.Extension.QueryInterface(SldWorks.IModelDocExtension)
        if document_type == 2:
            try:
                document.QueryInterface(SldWorks.IAssemblyDoc).ResolveAllLightWeightComponents(True)
                document.ForceRebuild3(False)
            except Exception:
                pass
        package = extension.GetPackAndGo()
        package.IncludeDrawings = bool(include_drawings)
        package.IncludeSimulationResults = bool(include_simulation_results)
        package.IncludeToolboxComponents = bool(include_toolbox_components)
        package.IncludeSuppressed = bool(include_suppressed)
        package.FlattenToSingleFolder = bool(flatten)
        document_count = int(package.GetDocumentNamesCount())
        enumerated_names = _comtypes_document_names(package, document_count)
        enumerated_paths = {Path(path).resolve() for path in enumerated_names if path}
        enumeration_missing = [
            str(Path(path).resolve())
            for path in (dependencies or [])
            if Path(path).resolve() not in enumerated_paths
        ]
        # AddExternalDocuments 用于附加非模型依赖文件，不保证接受装配体的原生零件引用。
        # 即使枚举不完整也执行原生保存，随后以实际落盘文件审计是否缺失依赖。
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
            "enumeration_missing": enumeration_missing,
        }
    finally:
        if started_here:
            if document is not None:
                try:
                    sw.CloseDoc(str(document.GetTitle()))
                except Exception:
                    pass
            try:
                sw.ExitApp()
            except Exception:
                pass


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
    fallback_policy: str = "stage_dependencies",
) -> dict[str, Any]:
    """执行原生 Pack and Go，并按策略处理不同版本的依赖枚举缺失。

    ``fallback_policy=stage_dependencies`` 会在原生 API 已保存但漏枚举依赖时
    生成明确标记的本地暂存包；``blocked`` 保持严格原生门禁。
    """
    if fallback_policy not in {"stage_dependencies", "blocked"}:
        raise ValueError("fallback_policy 必须是 stage_dependencies 或 blocked")
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
    native_error: str | None = None
    result: dict[str, Any]
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
        try:
            result = _comtypes_pack_and_go(
                source_path,
                target,
                existing_files,
                include_drawings=include_drawings,
                include_simulation_results=include_simulation_results,
                include_toolbox_components=include_toolbox_components,
                include_suppressed=include_suppressed,
                flatten=flatten,
                dependencies=dependencies,
            )
        except Exception as comtypes_exc:
            fallback_errors.append(f"comtypes: {comtypes_exc}")
            native_error = str(comtypes_exc)
            result = {
                "backend": "native_unavailable",
                "document_count": 0,
                "status_codes": [],
                "outputs": [],
                "produced_count": 0,
                "enumeration_missing": dependencies,
            }

    missing_dependencies = _missing_dependency_paths(dependencies, result["outputs"])
    success = (
        bool(result["status_codes"])
        and all(code == 0 for code in result["status_codes"])
        and bool(result["outputs"])
        and not missing_dependencies
    )
    staged = None
    native_status = "pass" if success else "blocked" if missing_dependencies and result["status_codes"] and all(code == 0 for code in result["status_codes"]) else "failed"
    if success:
        status = "pass"
        stage = "save"
        error_code = None
        retryable = False
        manual_review_required = True
        limitations = ["Pack and Go 产物仍需人工抽查外部引用、Toolbox 和工程图"]
    elif missing_dependencies and fallback_policy == "stage_dependencies":
        try:
            staged = _stage_pack_and_go_dependencies(
                source_path,
                dependencies,
                target,
                existing_files,
                flatten=flatten,
            )
        except Exception as exc:
            fallback_errors.append(f"staged_dependencies: {exc}")
            staged = None
        if staged is not None:
            success = True
            status = "pilot"
            stage = "review"
            error_code = "SW_PACK_AND_GO_NATIVE_ENUMERATION_INCOMPLETE"
            retryable = True
            manual_review_required = True
            limitations = [
                "原生 IPackAndGo 未枚举全部依赖；已生成基于 GetDependencies2 的暂存包",
                "暂存包不是原生 Pack and Go，外部引用、Toolbox、配置和工程图必须人工复核",
            ]
            result = {
                **result,
                "backend": "solidworks-native+staged_dependencies",
                "outputs": staged["outputs"],
                "produced_count": staged["produced_count"],
                "manifest": staged["manifest"],
            }
            missing_dependencies = []
        else:
            # 暂存失败时保留原生漏包证据，不能把失败变成成功。
            status = "blocked"
            stage = "review"
            error_code = "SW_PACK_AND_GO_DEPENDENCY_ENUMERATION_INCOMPLETE"
            retryable = True
            manual_review_required = True
            limitations = ["SolidWorks 原生 Pack and Go 未枚举全部依赖，暂存回退也未完成"]
    elif missing_dependencies and result["status_codes"] and all(code == 0 for code in result["status_codes"]):
        # 严格原生策略：保留证据并阻止误交付。
        status = "blocked"
        stage = "review"
        error_code = "SW_PACK_AND_GO_DEPENDENCY_ENUMERATION_INCOMPLETE"
        retryable = True
        manual_review_required = True
        limitations = ["SolidWorks 原生 Pack and Go 未枚举全部依赖；fallback_policy=blocked，未复制补齐"]
    else:
        if fallback_policy == "stage_dependencies" and dependencies:
            try:
                staged = _stage_pack_and_go_dependencies(
                    source_path,
                    dependencies,
                    target,
                    existing_files,
                    flatten=flatten,
                )
            except Exception as exc:
                fallback_errors.append(f"staged_dependencies: {exc}")
                staged = None
            if staged is not None:
                success = True
                status = "pilot"
                stage = "review"
                error_code = "SW_PACK_AND_GO_NATIVE_FAILED_STAGED"
                retryable = True
                manual_review_required = True
                limitations = [
                    "原生 Pack and Go 调用失败；已按 GetDependencies2 生成暂存包",
                    "暂存包不是原生 Pack and Go，必须人工复核",
                ]
                result = {
                    **result,
                    "backend": "solidworks-native+staged_dependencies",
                    "outputs": staged["outputs"],
                    "produced_count": staged["produced_count"],
                    "manifest": staged["manifest"],
                }
                missing_dependencies = []
            else:
                status = "failed"
                stage = "save"
                error_code = "SW_PACK_AND_GO_SAVE_FAILED"
                retryable = True
                manual_review_required = False
                limitations = []
        else:
            status = "failed"
            stage = "save"
            error_code = "SW_PACK_AND_GO_SAVE_FAILED"
            retryable = True
            manual_review_required = False
            limitations = []
    return {
        "success": success,
        "status": status,
        "stage": stage,
        "error_code": error_code,
        "retryable": retryable,
        "manual_review_required": manual_review_required,
        "limitations": limitations,
        "source": source_path,
        "output_dir": str(target),
        "backend": result["backend"],
        "native_backend": result.get("backend") if staged is None else "solidworks-native",
        "native_status": native_status,
        "document_count": result["document_count"],
        "status_codes": result["status_codes"],
        "outputs": result["outputs"],
        "produced_count": result["produced_count"],
        "dependencies": dependencies,
        "missing_dependencies": missing_dependencies,
        "native_missing_dependencies": _missing_dependency_paths(dependencies, result.get("outputs", [])) if staged is None else list(dependencies),
        "fallback_policy": fallback_policy,
        "fallback_used": staged is not None,
        "manifest": result.get("manifest"),
        "fallback_errors": fallback_errors,
        "options": {
            "include_drawings": include_drawings,
            "include_simulation_results": include_simulation_results,
            "include_toolbox_components": include_toolbox_components,
            "include_suppressed": include_suppressed,
            "flatten": flatten,
        },
    }
