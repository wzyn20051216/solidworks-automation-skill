"""把无外部引用的单实体零件按预览计划复制到新目录，保留源文件。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

try:
    from .sw_connect import get_com_member
    from .sw_file_rename import _valid_filename
    from .sw_measure import collect_bounding_box, collect_mass_properties
    from .sw_read_guard import SolidWorksReadGuard
    from .sw_session import SolidWorksSession
except ImportError:
    from sw_connect import get_com_member
    from sw_file_rename import _valid_filename
    from sw_measure import collect_bounding_box, collect_mass_properties
    from sw_read_guard import SolidWorksReadGuard
    from sw_session import SolidWorksSession


def prepare_plan(plans: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """校验全部输入；不读取或修改 SolidWorks 文档。"""
    if not isinstance(plans, list) or not 1 <= len(plans) <= 100:
        raise ValueError("计划必须包含 1..100 个零件")
    result = []
    sources, targets = set(), set()
    for plan in plans:
        if not isinstance(plan, Mapping) or plan.get("status") not in {"planned", "unchanged"}:
            raise ValueError("计划存在被阻断或无效的条目")
        raw_source, new_name = plan.get("source"), plan.get("new_name")
        if not isinstance(raw_source, str) or not raw_source or not isinstance(new_name, str):
            raise ValueError("源路径或目标名称无效")
        source = Path(os.path.expandvars(raw_source)).expanduser().absolute()
        if source.name.startswith("~$") or source.is_symlink() or not source.is_file() or source.suffix.casefold() != ".sldprt":
            raise ValueError("仅支持非符号链接的现有 SLDPRT 零件")
        if new_name.startswith("~$") or Path(new_name).name != new_name or not _valid_filename(new_name) or Path(new_name).suffix.casefold() != ".sldprt":
            raise ValueError("目标必须是合法的 SLDPRT 文件名")
        source_key, target_key = str(source.resolve()).casefold(), new_name.casefold()
        if source_key in sources or target_key in targets:
            raise ValueError("源文件或目标名称重复")
        sources.add(source_key)
        targets.add(target_key)
        result.append({"source": str(source.resolve()), "new_name": new_name})
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(model) -> dict[str, Any]:
    kind, dirty = get_com_member(model, "GetType"), get_com_member(model, "GetSaveFlag")
    if isinstance(kind, bool) or kind != 1 or dirty not in (False, 0):
        raise ValueError("必须是没有未保存修改的零件")
    dependencies = get_com_member(model, "GetDependencies2", False, True, False)
    if dependencies is None or not isinstance(dependencies, (tuple, list)):
        raise ValueError("无法确认外部引用清单")
    if dependencies:
        raise ValueError("零件含外部引用；此入口不支持复制")
    configs = get_com_member(model, "GetConfigurationNames")
    if not isinstance(configs, (tuple, list)) or len(configs) != 1:
        raise ValueError("仅支持可确认的单配置零件")
    extension = get_com_member(model, "Extension")
    counts = (get_com_member(extension, "ListExternalFileReferencesCount"),
              get_com_member(model, "ListAuxiliaryExternalFileReferencesCount"))
    if any(isinstance(count, bool) or not isinstance(count, int) or count != 0 for count in counts):
        raise ValueError("存在外部引用或无法确认外部引用数量")
    bodies = tuple(get_com_member(model, "GetBodies2", 0, False) or ())
    if len(bodies) != 1:
        raise ValueError("仅支持一个实体的零件")
    mass = collect_mass_properties(model)
    box = collect_bounding_box(model)
    volume, dimensions = mass.get("volume_mm3"), box.get("size_mm")
    if (mass.get("errors") or box.get("errors") or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume <= 0 or not isinstance(dimensions, list)
            or len(dimensions) != 3 or any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in dimensions)):
        raise ValueError("不能确认零件体积和包围盒")
    return {"volume_mm3": volume, "size_mm": dimensions, "solid_bodies": len(bodies)}


def _open_checked(session, path: Path, *, read_only=True):
    """避免 SolidWorks 因同名已打开文档复用错误对象。"""
    requested = path.resolve()
    for document in session._documents():
        title = str(get_com_member(document, "GetTitle") or "")
        existing = str(get_com_member(document, "GetPathName") or "")
        existing_name = Path(existing).name if existing else title
        same_title = (existing_name.casefold() == path.name.casefold() or title.casefold() == path.name.casefold()
                      or (not existing and title.casefold() == path.stem.casefold()))
        if same_title and (not existing or Path(existing).resolve() != requested):
            raise ValueError("已打开其他同名文档，无法安全确认文件身份")
    model = session.open(str(path), read_only=read_only, silent=True)
    try:
        actual = str(get_com_member(model, "GetPathName") or "")
        matches = bool(actual) and Path(actual).resolve() == requested
    except Exception:
        matches = False
    if not matches:
        # 所有权无法确认，宁可保留未知对象，也不按错误标题关闭用户文档。
        session._owned_documents = [item for item in session._owned_documents if item is not model]
        raise RuntimeError("打开的文档与请求路径不一致")
    return model


def copy_batch(plans: Sequence[Mapping[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    """仅创建新目录及副本；失败停止并保留已生成文件与清单供复核。"""
    entries = prepare_plan(plans)
    target = Path(os.path.expandvars(str(output_dir))).expanduser().absolute()
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ValueError("输出目录必须不存在，且其父目录必须已存在")
    target.mkdir(mode=0o700, exist_ok=False)
    report: dict[str, Any] = {"status": "blocked", "reviewRequired": True, "outputs": [], "attempts": [], "error": None,
                              "limitations": ["仅支持引用检查为空的单配置、单实体已保存零件", "不支持装配、图纸、虚拟组件或已知外部引用", "引用源文件的其他文档不会更新；副本只作独立零件使用", "引用检查和几何快照不能证明所有潜在引用或行为完整，仍须复核"]}
    try:
        with SolidWorksReadGuard():
            with SolidWorksSession(version=2026, visible=True) as session:
                for item in entries:
                    source = Path(item["source"])
                    dest = target / item["new_name"]
                    attempt = {"source": str(source), "path": str(dest), "status": "attempting"}
                    report["attempts"].append(attempt)
                    before = _sha256(source)
                    model = _open_checked(session, source)
                    snapshot = _snapshot(model)
                    # 限于无外部引用的单零件：逐字节复制并独占创建，不执行 Pack and Go 或文件重命名。
                    with source.open("rb") as reader, dest.open("xb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        writer.flush()
                        os.fsync(writer.fileno())
                    if not dest.is_file() or dest.is_symlink() or dest.stat().st_size == 0:
                        raise RuntimeError("未生成有效副本")
                    copied_hash = _sha256(dest)
                    if _sha256(source) != before or copied_hash != before:
                        raise RuntimeError("源文件发生变化或副本字节不一致，停止并保留证据")
                    if any(owned is model for owned in session._owned_documents):
                        session.close(model=model)
                    copy = _open_checked(session, dest)
                    actual = _snapshot(copy)
                    if not math.isclose(snapshot["volume_mm3"], actual["volume_mm3"], rel_tol=1e-7, abs_tol=1e-5) or any(
                            not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-5) for a, b in zip(snapshot["size_mm"], actual["size_mm"])):
                        raise RuntimeError("副本重开后的几何快照与源文件不一致")
                    if any(owned is copy for owned in session._owned_documents):
                        session.close(model=copy)
                    report["outputs"].append({"source": str(source), "source_sha256": before, "path": str(dest),
                                              "sha256": copied_hash, "geometry": actual})
                    attempt["status"] = "verified"
        report["status"] = "review_required"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if report["attempts"] and report["attempts"][-1]["status"] == "attempting":
            report["attempts"][-1]["status"] = "blocked"
    manifest = target / "copy-manifest.json"
    with manifest.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    report["manifest"] = str(manifest)
    return report


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="将无外部引用的单实体零件复制改名到新目录；源文件不动。")
    parser.add_argument("--plan", required=True, help="sw_file_rename.py 生成的 JSON 预览")
    parser.add_argument("--output-dir", required=True, help="必须不存在的新目录")
    args = parser.parse_args(argv)
    plan_path = Path(args.plan).expanduser()
    if plan_path.stat().st_size > 4 * 1024 * 1024:
        parser.error("预览计划超过 4 MiB")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        parser.error("预览计划必须是 JSON 对象")
    result = copy_batch(plan.get("plans"), args.output_dir)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result["status"] == "review_required" else 1


if __name__ == "__main__":
    raise SystemExit(main())
