"""
@file sw_file_rename.py
@brief 按自定义属性模板批量规划并（可选）执行 SolidWorks 文件改名，兼顾切割清单改名。

对标 t84RT/SW-software---Macro-command 中的“文件改名 / 切割清单改名”宏（第三方 VBA，
与达索无隶属关系），用 Python 重写并把可验证部分（模板渲染、文件名净化、冲突/空操作检测、
改名计划）与需真机的 COM 属性读取、Pack and Go 参照安全改名、切割清单遍历分离。

安全默认：默认只生成改名计划与 CSV（dry-run），不改动任何文件。真正改名通过 SolidWorks
原生 Pack and Go 参照安全地写“改名副本”，保留原文件，且逐个核对产物存在——找不到产物即判 blocked，
不做会破坏外部参照的裸文件系统重命名。

能力等级：pilot。改名计划逻辑已离线单测；COM 属性读取与 Pack and Go 改名需真机与依赖人工复核。
"""
from __future__ import annotations

import csv
import re
import string
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .sw_connect import get_com_member
    from .sw_weldment import iter_features_recursive
except ImportError:
    from sw_connect import get_com_member
    from sw_weldment import iter_features_recursive

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NATIVE_EXTENSIONS = {".sldprt", ".sldasm", ".slddrw"}
PLAN_COLUMNS = ["old_name", "new_name", "status", "reason"]


class _SafeDict(dict):
    """@brief str.format_map 用：缺失键保留原占位符而不抛 KeyError。"""

    def __missing__(self, key):  # noqa: D401
        return "{" + key + "}"


def _template_fields(template: str) -> list[str]:
    """@brief 解析模板中的占位符字段名。"""
    return [name for _text, name, _spec, _conv in string.Formatter().parse(template) if name]


def sanitize_filename(name: str, *, replacement: str = "_") -> str:
    """@brief 去除 Windows 非法字符与首尾空白/点，得到安全文件名（不含扩展名）。"""
    cleaned = _ILLEGAL_CHARS.sub(replacement, str(name)).strip().strip(".")
    cleaned = re.sub(rf"{re.escape(replacement)}{{2,}}", replacement, cleaned)
    return cleaned


def render_name_template(template: str, properties: Mapping[str, Any]) -> tuple[str, list[str]]:
    """@brief 用属性字典渲染文件名模板。

    @param template 形如 "{图号}_{名称}" 的模板。
    @param properties 属性名->值。
    @return (渲染后的文件名（未含扩展名，已净化）, 缺失字段列表)。
    """
    values = {str(key): ("" if value is None else str(value)) for key, value in properties.items()}
    missing = [field for field in _template_fields(template) if not values.get(field)]
    rendered = template.format_map(_SafeDict(values))
    return sanitize_filename(rendered), missing


def plan_renames(
    entries: Sequence[Mapping[str, Any]],
    template: str,
    *,
    keep_extension: bool = True,
) -> list[dict[str, Any]]:
    """@brief 生成改名计划并标注状态。

    @param entries 每项含 {"path": 原路径, "properties": {...}}。
    @param template 文件名模板。
    @param keep_extension 保留原扩展名。
    @return 计划行列表；status ∈ rename/skip_noop/skip_missing/skip_empty/conflict。

    冲突检测：多个源渲染出同一目标名，或目标名与其它源的原名相同，标 conflict。
    """
    plans: list[dict[str, Any]] = []
    proposed: dict[str, int] = {}
    original_names = {Path(str(entry.get("path", ""))).name.casefold() for entry in entries}

    prepared = []
    for entry in entries:
        path = Path(str(entry.get("path", "")))
        properties = entry.get("properties") or {}
        extension = path.suffix if keep_extension else ""
        rendered, missing = render_name_template(template, properties)
        prepared.append((path, extension, rendered, missing))
        if rendered:
            new_full = (rendered + extension).casefold()
            proposed[new_full] = proposed.get(new_full, 0) + 1

    for path, extension, rendered, missing in prepared:
        old_name = path.name
        if not rendered:
            plans.append({"old_name": old_name, "new_name": "", "status": "skip_empty", "reason": "模板渲染为空"})
            continue
        if missing:
            plans.append(
                {
                    "old_name": old_name,
                    "new_name": "",
                    "status": "skip_missing",
                    "reason": f"缺少属性: {', '.join(missing)}",
                }
            )
            continue
        new_name = rendered + extension
        if new_name.casefold() == old_name.casefold():
            plans.append({"old_name": old_name, "new_name": new_name, "status": "skip_noop", "reason": "与原名相同"})
            continue
        conflict = proposed.get(new_name.casefold(), 0) > 1 or (
            new_name.casefold() in original_names and new_name.casefold() != old_name.casefold()
        )
        if conflict:
            plans.append(
                {"old_name": old_name, "new_name": new_name, "status": "conflict", "reason": "目标名与其它文件冲突"}
            )
            continue
        plans.append({"old_name": old_name, "new_name": new_name, "status": "rename", "reason": ""})
    return plans


def plan_cut_list_renames(items: Sequence[Mapping[str, Any]], template: str) -> list[dict[str, Any]]:
    """@brief 生成焊件切割清单条目改名计划。

    @param items 每项含 {"name": 当前折弯/切割清单名, "properties": {...}}。
    @param template 例如 "{材料}-{长度}" 或 "{数量}xL{长度}"。
    """
    plans: list[dict[str, Any]] = []
    for item in items:
        current = str(item.get("name", ""))
        rendered, missing = render_name_template(template, item.get("properties") or {})
        if not rendered:
            plans.append({"old_name": current, "new_name": "", "status": "skip_empty", "reason": "模板渲染为空"})
        elif missing:
            plans.append(
                {"old_name": current, "new_name": "", "status": "skip_missing", "reason": f"缺少属性: {', '.join(missing)}"}
            )
        elif rendered == current:
            plans.append({"old_name": current, "new_name": rendered, "status": "skip_noop", "reason": "与原名相同"})
        else:
            plans.append({"old_name": current, "new_name": rendered, "status": "rename", "reason": ""})
    return plans


def summarize_plan(plans: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """@brief 统计各状态数量。"""
    summary: dict[str, int] = {}
    for plan in plans:
        status = str(plan.get("status", "unknown"))
        summary[status] = summary.get(status, 0) + 1
    return summary


def write_plan_csv(plans: Sequence[Mapping[str, Any]], output_path: str | Path) -> Path:
    """@brief 将改名计划写入 UTF-8 BOM CSV。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_COLUMNS)
        writer.writeheader()
        for plan in plans:
            writer.writerow({key: plan.get(key, "") for key in PLAN_COLUMNS})
    return path


# ---------------------------------------------------------------------------
# COM 部分（pilot，需真机验证）
# ---------------------------------------------------------------------------


def _maybe(obj, name: str, *args):
    """@brief 防御式读取 COM 成员。"""
    if obj is None:
        return None
    try:
        return get_com_member(obj, name, *args)
    except Exception:  # noqa: BLE001
        return None


def read_document_properties(sw, file_path: str | Path, property_names: Sequence[str]) -> dict[str, str]:
    """@brief 只读打开一个文档，读取指定自定义属性后关闭。"""
    from sw_connect import open_document

    path = Path(file_path)
    model = open_document(sw, str(path), read_only=True, silent=True)
    if model is None:
        return {}
    try:
        extension = _maybe(model, "Extension")
        manager = _maybe(extension, "CustomPropertyManager", "")
        result: dict[str, str] = {}
        for name in property_names:
            value = _maybe(manager, "Get", name)
            if isinstance(value, (list, tuple)) and value:
                value = value[0]
            result[str(name)] = "" if value is None else str(value)
        return result
    finally:
        title = _maybe(model, "GetTitle")
        if title:
            try:
                sw.CloseDoc(title)
            except Exception:  # noqa: BLE001
                pass


def collect_rename_entries(sw, folder: str | Path, property_names: Sequence[str]) -> list[dict[str, Any]]:
    """@brief 扫描文件夹内 SolidWorks 原生文件并读取属性，供 plan_renames 使用。"""
    base = Path(folder)
    entries: list[dict[str, Any]] = []
    for path in sorted(base.iterdir()):
        if path.suffix.lower() not in NATIVE_EXTENSIONS:
            continue
        entries.append({"path": str(path), "properties": read_document_properties(sw, path, property_names)})
    return entries


def apply_cut_list_renames(model, name_map: Mapping[str, str]) -> list[dict[str, Any]]:
    """@brief 按 {旧名: 新名} 重命名焊件切割清单折弯/条目特征。"""
    results: list[dict[str, Any]] = []
    for feature in iter_features_recursive(model):
        current = str(_maybe(feature, "Name") or "")
        if current in name_map and name_map[current] != current:
            try:
                feature.Name = name_map[current]
                renamed = str(_maybe(feature, "Name") or "")
                results.append({"old": current, "new": name_map[current], "verified": renamed == name_map[current]})
            except Exception as exc:  # noqa: BLE001
                results.append({"old": current, "new": name_map[current], "verified": False, "error": str(exc)})
    return results


def apply_renames_via_pack_and_go(sw, model, plans: Sequence[Mapping[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    """@brief 通过 SolidWorks 原生 Pack and Go 把 rename 计划写成改名副本（参照安全，保留原文件）。

    只对 status=rename 的项设置 SetDocumentSaveToName；产物必须落盘核对，找不到即 blocked。
    该 COM 路径版本敏感，任何异常都返回 blocked 而不做破坏参照的裸重命名。
    """
    try:
        from sw_delivery import _get_pack_and_go, _model_doc_extension
    except ImportError:
        from .sw_delivery import _get_pack_and_go, _model_doc_extension  # type: ignore

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rename_map = {
        str(plan.get("old_name")): str(plan.get("new_name"))
        for plan in plans
        if plan.get("status") == "rename" and plan.get("new_name")
    }
    if not rename_map:
        return {"status": "skipped", "reason": "无 rename 项", "produced": []}

    try:
        extension = _model_doc_extension(model)
        package = _get_pack_and_go(extension)
        package.FlattenToSingleFolder = True
        if not package.SetSaveToName(True, str(target) + "\\"):
            return {"status": "blocked", "reason": "SetSaveToName 拒绝目标目录", "produced": []}
        document_names = list(get_com_member(package, "GetDocumentNames") or [])
        save_to = []
        for doc in document_names:
            base = Path(str(doc)).name
            new_name = rename_map.get(base, base)
            save_to.append(str(target / new_name))
        package.SetDocumentSaveToNames(save_to)
        extension.SavePackAndGo(package)
    except Exception as exc:  # noqa: BLE001
        return {"status": "blocked", "reason": f"Pack and Go 改名失败: {exc}", "produced": []}

    produced = [str(target / name) for name in rename_map.values() if (target / name).exists()]
    missing = [name for name in rename_map.values() if not (target / name).exists()]
    return {
        "status": "ok" if produced and not missing else "blocked",
        "reason": "" if not missing else f"缺少产物: {', '.join(missing)}",
        "produced": produced,
        "missing": missing,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """@brief 命令行入口：扫描文件夹、按属性模板生成改名计划（默认 dry-run）。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="按自定义属性模板批量规划 SolidWorks 文件改名。")
    parser.add_argument("folder", help="待改名文件所在文件夹。")
    parser.add_argument("--template", required=True, help='文件名模板，如 "{图号}_{名称}"。')
    parser.add_argument("--properties", nargs="+", required=True, help="模板用到的自定义属性名列表。")
    parser.add_argument("--output-csv", default="rename_plan.csv", help="改名计划 CSV 输出路径。")
    parser.add_argument("--apply", action="store_true", help="执行 Pack and Go 改名（写改名副本，保留原文件）。")
    parser.add_argument("--apply-output-dir", help="--apply 时改名副本的输出目录。")
    args = parser.parse_args(argv)

    from sw_session import SolidWorksSession

    session = SolidWorksSession(visible=True)
    entries = collect_rename_entries(session.sw, args.folder, args.properties)
    plans = plan_renames(entries, args.template)
    csv_path = write_plan_csv(plans, args.output_csv)
    print(f"改名计划 CSV: {csv_path}")
    print(f"汇总: {summarize_plan(plans)}")
    for plan in plans:
        print(f"  {plan['old_name']} -> {plan['new_name'] or '(跳过)'} [{plan['status']}] {plan['reason']}")

    if args.apply:
        if not args.apply_output_dir:
            raise SystemExit("--apply 需要同时指定 --apply-output-dir")
        model = session.active_doc
        if model is None and entries:
            model = session.open(entries[0]["path"])
        result = apply_renames_via_pack_and_go(session.sw, model, plans, args.apply_output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
