"""基于 SolidWorks 文件属性生成批量改名预览；不移动或修改任何模型。"""
from __future__ import annotations

import json
import os
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

NATIVE_EXTENSIONS = {".sldprt", ".sldasm", ".slddrw"}
INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)


def template_fields(template: str) -> list[str]:
    if not isinstance(template, str) or not template or len(template) > 200:
        raise ValueError("模板必须是 1..200 字符的字符串")
    fields = []
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ValueError("模板括号无效") from exc
    for _, name, fmt, conversion in parts:
        if name is None:
            continue
        if not name or any(ch in name for ch in ".[]{}\\/") or fmt or conversion:
            raise ValueError("模板仅支持简单属性占位符，不支持属性访问、格式表达式或转换")
        if name not in fields:
            fields.append(name)
    if not fields or len(fields) > 32:
        raise ValueError("模板需要 1..32 个属性占位符")
    return fields


def _valid_filename(name: str) -> bool:
    return bool(name and len(name) <= 180 and not INVALID_NAME.search(name)
                and name not in {".", ".."} and not name.endswith((" ", ".")) and not RESERVED.match(name))


def plan_renames(entries: Sequence[Mapping[str, Any]], template: str) -> list[dict[str, Any]]:
    fields = template_fields(template)
    if len(entries) > 2000:
        raise ValueError("文件数量超过 2000，请拆分预览")
    originals = {Path(str(entry.get("path", ""))).name.casefold() for entry in entries}
    plans = []
    for entry in entries:
        path = Path(str(entry.get("path", "")))
        props = entry.get("properties") if isinstance(entry.get("properties"), Mapping) else {}
        missing = [key for key in fields if key not in props or not str(props[key]).strip()]
        plan = {"source": str(path), "old_name": path.name, "new_name": "", "status": "blocked", "reason": ""}
        if path.suffix.casefold() not in NATIVE_EXTENSIONS:
            plan["reason"] = "不是支持的 SolidWorks 原生文件"
        elif missing:
            plan["reason"] = "缺少属性: " + ", ".join(missing)
        else:
            candidate = template.format_map({key: str(props[key]) for key in fields}) + path.suffix
            plan["new_name"] = candidate
            if not _valid_filename(candidate):
                plan["reason"] = "目标文件名无效或为 Windows 保留名称"
            elif candidate.casefold() == path.name.casefold():
                plan.update(status="unchanged", reason="文件名未改变")
            elif candidate.casefold() in originals:
                plan["reason"] = "目标名称与源目录中的文件冲突"
            else:
                plan["status"] = "planned"
        plans.append(plan)
    proposed = Counter(item["new_name"].casefold() for item in plans if item["status"] == "planned")
    for plan in plans:
        if plan["status"] == "planned" and proposed[plan["new_name"].casefold()] > 1:
            plan.update(status="blocked", reason="多个文件的目标名称冲突")
    return plans


def collect_entries(session: Any, folder: str | Path, properties: Sequence[str]) -> list[dict[str, Any]]:
    """使用受控会话只读属性，只关闭本次真正打开的文档。"""
    try:
        from .sw_document_data import read_custom_property
    except ImportError:
        from sw_document_data import read_custom_property
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("输入目录不存在")
    files = sorted((p for p in root.iterdir() if p.is_file() and not p.is_symlink()
                    and p.suffix.casefold() in NATIVE_EXTENSIONS), key=lambda p: p.name.casefold())
    if len(files) > 2000:
        raise ValueError("文件数量超过 2000，请拆分预览")
    entries = []
    for path in files:
        model = session.open(str(path), read_only=True, silent=True)
        try:
            values = {}
            for name in properties:
                result = read_custom_property(model, name)
                if result.get("exists") and result.get("was_resolved"):
                    values[name] = result.get("resolved") or ""
            entries.append({"path": str(path), "properties": values})
        finally:
            if any(owned is model for owned in session._owned_documents):
                session.close(model=model)
    return entries


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="只读生成 SolidWorks 文件属性改名预览；不会执行改名。")
    parser.add_argument("folder")
    parser.add_argument("--template", required=True, help="例如 {图号}_{名称}")
    parser.add_argument("--output", required=True, help="不覆盖已有文件的 JSON 报告路径")
    args = parser.parse_args(argv)
    fields = template_fields(args.template)
    try:
        from .sw_session import SolidWorksSession
        from .sw_read_guard import SolidWorksReadGuard
    except ImportError:
        from sw_session import SolidWorksSession
        from sw_read_guard import SolidWorksReadGuard
    with SolidWorksReadGuard():
        with SolidWorksSession(visible=True) as session:
            entries = collect_entries(session, Path(os.path.expandvars(args.folder)), fields)
            plans = plan_renames(entries, args.template)
    report = {"status": "review_required", "reviewRequired": True, "plans": plans,
              "limitations": ["仅预览；不执行重命名、不修改引用或源文件", "属性、名称和所有引用需要人工复核"]}
    output = Path(args.output).expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "output": str(output), "count": len(plans)}, ensure_ascii=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
