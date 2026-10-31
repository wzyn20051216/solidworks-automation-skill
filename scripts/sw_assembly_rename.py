"""装配体副本改名：计划、引用闭包及受控执行。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import math
import os
import shutil

try:
    from .sw_file_rename import _valid_filename
    from .sw_connect import get_com_member
    from .sw_read_guard import SolidWorksReadGuard
    from .sw_rename_copy import _open_checked, _sha256, _snapshot
    from .sw_session import SolidWorksSession
    from .sw_assembly import iter_feature_tree
    from .sw_review import _feature_health
except ImportError:
    from sw_file_rename import _valid_filename
    from sw_connect import get_com_member
    from sw_read_guard import SolidWorksReadGuard
    from sw_rename_copy import _open_checked, _sha256, _snapshot
    from sw_session import SolidWorksSession
    from sw_assembly import iter_feature_tree
    from sw_review import _feature_health


def prepare_assembly_plan(root: str | Path, plans: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """校验显式文件映射；不打开 SolidWorks，也不修改文件。"""
    root_path = Path(root).expanduser().resolve(strict=True)
    if not root_path.is_file() or root_path.suffix.casefold() != ".sldasm":
        raise ValueError("根文档必须是现有的 SLDASM")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 200:
        raise ValueError("计划必须包含 1..200 个文件")
    result, sources, targets, original_names = [], set(), set(), set()
    for row in plans:
        if not isinstance(row, Mapping) or row.get("status") not in ("planned", "unchanged"):
            raise ValueError("计划包含无效或被阻断的条目")
        source, name = row.get("source"), row.get("new_name")
        if not isinstance(source, str) or not source or not isinstance(name, str):
            raise ValueError("源文件和目标名称必须是字符串")
        source_path = Path(source).expanduser().absolute()
        if source_path.is_symlink() or not source_path.is_file() or source_path.name.startswith("~$"):
            raise ValueError("源文件不存在、为链接或为锁文件")
        extension = source_path.suffix.casefold()
        if extension not in (".sldprt", ".sldasm"):
            raise ValueError("只支持零件和装配体")
        if (Path(name).name != name or not _valid_filename(name) or name.startswith("~$")
                or Path(name).suffix.casefold() != extension):
            raise ValueError("目标名称无效或文件类型不匹配")
        source_path = source_path.resolve(strict=True)
        key, target_key = str(source_path).casefold(), name.casefold()
        if key in sources or target_key in targets:
            raise ValueError("源文件或目标名称重复")
        sources.add(key)
        targets.add(target_key)
        original_names.add(source_path.name.casefold())
        result.append({"source": str(source_path), "new_name": name})
    if str(root_path).casefold() not in sources:
        raise ValueError("计划未包含根装配体")
    if original_names & targets:
        raise ValueError("副本名称不得与任何源文档名称相同，以避免已打开文档同名冲突")
    return result


def validate_reference_graph(root: str | Path, entries: Sequence[Mapping[str, str]],
                             dependencies: Mapping[str, Sequence[str]]) -> list[str]:
    """校验完整闭包和循环，返回子文档先于父文档的路径顺序。"""
    by_key = {str(Path(item["source"]).resolve()).casefold(): str(Path(item["source"]).resolve()) for item in entries}
    root_key = str(Path(root).resolve()).casefold()
    if len(by_key) != len(entries) or root_key not in by_key:
        raise ValueError("源文件重复或根文档不在计划中")
    graph = {}
    for parent, children in dependencies.items():
        parent_key = str(Path(parent).resolve()).casefold()
        if parent_key not in by_key or parent_key in graph or not isinstance(children, (list, tuple)):
            raise ValueError("引用清单无效")
        resolved_children = []
        for child in children:
            if not isinstance(child, str) or not Path(child).is_absolute():
                raise ValueError("引用路径必须是可确认的绝对路径")
            child_key = str(Path(child).resolve()).casefold()
            if child_key not in by_key:
                raise ValueError("引用不在计划中，无法安全复制")
            if child_key not in resolved_children:
                resolved_children.append(child_key)
        graph[parent_key] = resolved_children
    if set(graph) != set(by_key):
        raise ValueError("每个源文档都必须具有已确认的引用清单")
    state, order = {}, []

    def visit(key):
        if state.get(key) == 1:
            raise ValueError("检测到循环引用")
        if state.get(key) == 2:
            return
        state[key] = 1
        for child in graph[key]:
            visit(child)
        state[key] = 2
        order.append(by_key[key])

    visit(root_key)
    if len(order) != len(by_key):
        raise ValueError("计划包含不属于根装配体引用闭包的文件")
    return order


def _direct_references(model) -> list[str]:
    """返回官方 GetDependencies2 的直接依赖；读取不完整时停止。"""
    values = get_com_member(model, "GetDependencies2", False, True, False)
    if not isinstance(values, (list, tuple)) or len(values) % 2:
        raise ValueError("无法确认直接引用清单")
    paths = []
    for index in range(1, len(values), 2):
        path = str(values[index] or "")
        if not path or not Path(path).is_absolute() or not Path(path).is_file():
            raise ValueError("引用缺失或路径无法确认")
        paths.append(str(Path(path).resolve()))
    return paths


def _assembly_snapshot(model) -> dict[str, Any]:
    if get_com_member(model, "GetType") != 2 or get_com_member(model, "GetSaveFlag") not in (False, 0):
        raise ValueError("必须是已保存且没有未保存修改的装配体")
    configurations = get_com_member(model, "GetConfigurationNames")
    if not isinstance(configurations, (tuple, list)) or len(configurations) != 1:
        raise ValueError("目前只支持单配置装配体")
    extension = get_com_member(model, "Extension")
    counts = (get_com_member(extension, "ListExternalFileReferencesCount"),
              get_com_member(model, "ListAuxiliaryExternalFileReferencesCount"))
    if any(isinstance(count, bool) or not isinstance(count, int) or count != 0 for count in counts):
        raise ValueError("装配体包含外部文件引用或无法确认引用数量")
    components = get_com_member(model, "GetComponents", False)
    if not isinstance(components, (tuple, list)) or not components:
        raise ValueError("无法确认装配体组件")
    records = []
    for component in components:
        path = str(get_com_member(component, "GetPathName") or "")
        state = get_com_member(component, "GetSuppression")
        virtual = get_com_member(component, "IsVirtual")
        model_ref = get_com_member(component, "GetModelDoc2")
        if not path or not Path(path).is_file() or state not in (2, 3) or virtual is not False or model_ref is None:
            raise ValueError("组件缺失、虚拟、压缩或未完全解析")
        if get_com_member(model_ref, "GetSaveFlag") not in (False, 0):
            raise ValueError("组件存在未保存修改")
        transform = get_com_member(component, "Transform2")
        matrix = get_com_member(transform, "ArrayData") if transform is not None else None
        if not isinstance(matrix, (tuple, list)) or len(matrix) != 16 or not all(math.isfinite(float(v)) for v in matrix):
            raise ValueError("无法确认组件变换")
        records.append({"path": str(Path(path).resolve()), "configuration": str(get_com_member(component, "ReferencedConfiguration") or ""),
                        "state": state, "transform": [float(v) for v in matrix]})
    mates = []
    for feature, _ in iter_feature_tree(model):
        kind = str(get_com_member(feature, "GetTypeName2") or "")
        if kind.startswith("Mate") and kind != "MateGroup":
            health = _feature_health(feature)
            if health.get("health_status") != "healthy":
                raise ValueError("存在异常或无法确认健康状态的配合")
            mates.append({"name": str(get_com_member(feature, "Name") or ""), "type": kind,
                          "error_code": health["error_code"]})
    return {"components": records, "mates": sorted(mates, key=lambda item: (item["name"], item["type"]))}


def _compare_assembly(before: Mapping[str, Any], after: Mapping[str, Any], destination_by_source: Mapping[str, str]) -> None:
    if before["mates"] != after["mates"] or len(before["components"]) != len(after["components"]):
        raise ValueError("装配体配合或组件数量不一致")
    remaining = list(after["components"])
    for item in before["components"]:
        expected = destination_by_source.get(item["path"].casefold())
        if expected is None:
            raise ValueError("组件引用未包含在计划中")
        for candidate in remaining:
            if (candidate["path"].casefold() == expected.casefold()
                    and candidate["configuration"] == item["configuration"] and candidate["state"] == item["state"]
                    and all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
                            for a, b in zip(item["transform"], candidate["transform"]))):
                remaining.remove(candidate)
                break
        else:
            raise ValueError("组件路径、配置、状态或变换不一致")


def copy_assembly(root: str | Path, plans: Sequence[Mapping[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    """复制单配置装配及依赖，仅在隔离副本中替换引用并重开核验。"""
    entries = prepare_assembly_plan(root, plans)
    target = Path(output_dir).expanduser().absolute()
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("输出目录必须不存在，且其父目录必须存在")
    target.mkdir(mode=0o700, exist_ok=False)
    report = {"status": "blocked", "reviewRequired": True, "outputs": [], "error": None,
              "limitations": ["只支持单配置、解析完成且无外部引用的零件和单配置装配体", "不更新源文件及其外部使用位置", "Toolbox、图纸、虚拟或压缩组件、多配置及其他外部引用未支持"]}
    try:
        with SolidWorksReadGuard(), SolidWorksSession(version=2026, visible=True) as session:
            hashes, snapshots, dependencies = {}, {}, {}
            for entry in entries:
                source = Path(entry["source"])
                hashes[str(source)] = _sha256(source)
                model = _open_checked(session, source)
                dependencies[str(source)] = _direct_references(model)
                if source.suffix.casefold() == ".sldprt":
                    toolbox = get_com_member(get_com_member(model, "Extension"), "ToolboxPartType")
                    if isinstance(toolbox, bool) or toolbox != 0:
                        raise ValueError("Toolbox 零件或无法确认其类型的零件不受支持")
                snapshots[str(source)] = _snapshot(model) if source.suffix.casefold() == ".sldprt" else _assembly_snapshot(model)
                if any(owned is model for owned in session._owned_documents):
                    session.close(model=model)
            order = validate_reference_graph(root, entries, dependencies)
            destinations = {item["source"].casefold(): str(target / item["new_name"]) for item in entries}
            for source in order:
                with Path(source).open("rb") as reader, Path(destinations[source.casefold()]).open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                if _sha256(Path(source)) != hashes[source] or _sha256(Path(destinations[source.casefold()])) != hashes[source]:
                    raise RuntimeError("源文件变化或副本校验失败")
            for source in order:
                for reference in dependencies[source]:
                    if not session.sw.ReplaceReferencedDocument(destinations[source.casefold()], reference, destinations[reference.casefold()]):
                        raise RuntimeError("副本引用替换失败")
            for source in order:
                copy_path = Path(destinations[source.casefold()])
                model = _open_checked(session, copy_path)
                if copy_path.suffix.casefold() == ".sldasm":
                    _compare_assembly(snapshots[source], _assembly_snapshot(model), destinations)
                else:
                    actual = _snapshot(model)
                    expected = snapshots[source]
                    if not math.isclose(actual["volume_mm3"], expected["volume_mm3"], rel_tol=1e-7, abs_tol=1e-5) or any(
                            not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-5) for a, b in zip(actual["size_mm"], expected["size_mm"])):
                        raise RuntimeError("零件副本几何不一致")
                if any(owned is model for owned in session._owned_documents):
                    session.close(model=model)
                report["outputs"].append({"source": source, "source_sha256": hashes[source], "path": str(copy_path), "sha256": _sha256(copy_path)})
            if any(_sha256(Path(path)) != digest for path, digest in hashes.items()):
                raise RuntimeError("源文件发生变化")
            report["status"] = "review_required"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    manifest = target / "assembly-copy-manifest.json"
    with manifest.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    report["manifest"] = str(manifest)
    return report


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="在新目录创建单配置装配体改名副本，并核对组件与配合。")
    parser.add_argument("--root", required=True, help="源根装配体")
    parser.add_argument("--plan", required=True, help="包含 plans 列表的 JSON 文件")
    parser.add_argument("--output-dir", required=True, help="必须不存在的新目录")
    args = parser.parse_args(argv)
    path = Path(args.plan).expanduser()
    if path.stat().st_size > 4 * 1024 * 1024:
        parser.error("计划文件超过 4 MiB")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        parser.error("计划必须是 JSON 对象")
    result = copy_assembly(args.root, plan.get("plans"), args.output_dir)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result["status"] == "review_required" else 1


if __name__ == "__main__":
    raise SystemExit(main())
