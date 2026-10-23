"""@brief 真机 Golden 共用契约、运行环境配置与证据安全；不封装 COM 或模型操作。"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import struct
from datetime import datetime

CASE_REGISTRY = {"mounting_bracket": {"module": "solidworks_golden_mounting_bracket_2026",
                                     "basename": "mounting_bracket", "year": 2026, "blocked_runs": 5}}
VIEWS = ("isometric", "front", "top", "right")


def evidence_paths(case_id, run_id):
    """@brief 从注册契约生成必需文件集合，拒绝未知用例及路径注入。"""
    basename = CASE_REGISTRY[case_id]["basename"]
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
        raise ValueError("BLOCKED: run_id 必须只包含字母、数字、下划线和短横线")
    return {f"{basename}.SLDPRT", f"{basename}.step", "built.json", "reopened.json", "step_reopened.json",
            "runtime_config.json", "runtime_diagnostics.json", "preflight.log", "doctor.log", "run.log", "report.json",
            f"trace/events/{run_id}.jsonl", f"review/{basename}_review_report.json", f"review/{basename}_review_summary.md",
            *(f"review/{basename}_{view}.bmp" for view in VIEWS)}


def safe_output_path(root, path):
    """@brief 在读写/哈希之前拒绝越界、符号链接和 Windows junction，保护非测试文件。"""
    root, path = Path(root), Path(path)
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("EVIDENCE_PATH_OUTSIDE_RUN")
    current = path
    while current.is_relative_to(root):
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("EVIDENCE_LINK_FORBIDDEN")
        if current.is_file() and current.stat().st_nlink > 1:
            raise ValueError("EVIDENCE_HARDLINK_FORBIDDEN")
        if current == root:
            break
        current = current.parent
    return path


def valid_process_identity(pid, created_at):
    """@brief 实例身份必须含真实类型的 PID 和可解析、带时区的创建时间。"""
    try:
        return type(pid) is int and pid > 0 and datetime.fromisoformat(created_at).tzinfo is not None
    except (ValueError, TypeError):
        return False


def load_runtime_config(source=None):
    """@brief 只允许模板、材料库路径和有界超时；不能配置版本、容差或取消审查。"""
    config = {"part_template": None, "material_database": None, "connect_timeout_seconds": 60, "cleanup_timeout_seconds": 30}
    if source is not None:
        source = Path(source).resolve()
        value = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) - set(config):
            raise ValueError("BLOCKED: runtime-config 含未知或禁止的字段")
        config.update(value)
        for key in ("part_template", "material_database"):
            if config[key] is not None:
                path = Path(config[key])
                config[key] = str((source.parent / path).resolve() if not path.is_absolute() else path.resolve())
    for key, upper in (("connect_timeout_seconds", 120), ("cleanup_timeout_seconds", 60)):
        if type(config[key]) is not int or not 5 <= config[key] <= upper:
            raise ValueError(f"BLOCKED: {key} 必须为 5..{upper} 的整数")
    for key, extension in (("part_template", ".prtdot"), ("material_database", ".sldmat")):
        if config[key] is not None and (not Path(config[key]).is_file() or Path(config[key]).suffix.lower() != extension):
            raise ValueError(f"BLOCKED: {key} 文件缺失或扩展名错误")
    return config


def diagnose_runtime(config):
    """@brief 无 CAD 副作用的最小依赖诊断；缺失时由调用者保留 BLOCKED 证据。"""
    checks = {"windows": os.name == "nt", "python_64_bit": struct.calcsize("P") == 8}
    for name in ("pythoncom", "win32com", "comtypes"):
        try:
            checks[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            checks[name] = False
    return {"status": "pass" if all(checks.values()) else "blocked", "checks": checks, "config": config,
            "blocked_reasons": [key for key, passed in checks.items() if not passed]}


def resolve_material_database(config, executable):
    """@brief 从诊断到的安装根目录或受控配置读取材料库，不依赖本机盘符。"""
    if config["material_database"]:
        return Path(config["material_database"])
    install = Path(executable).parent
    for language in ("english", "chinese-simplified"):
        candidate = install / "lang" / language / "sldmaterials" / "solidworks materials.sldmat"
        if candidate.is_file():
            return candidate
    raise ValueError("BLOCKED: 安装目录及配置中均未找到材料库")


def process_created_at(pid):
    """@brief 使用 PID 与内核创建时间标识实例，避免 Windows PID 重用导致误判。"""
    import win32api
    import win32process
    handle = win32api.OpenProcess(0x1000, False, pid)
    try:
        return win32process.GetProcessTimes(handle)["CreationTime"].isoformat()
    finally:
        handle.Close()


def validate_core_trace(events, report, run_id):
    """@brief 核对关联、步骤、事件顺序和唯一终态，而非仅查找几个事件名称。"""
    if not events or any(event.get("run_id") != run_id for event in events):
        raise ValueError("CORE_TRACE_RUN_MISMATCH")
    core = report["execution_core"]
    step = core["step"]
    if core.get("run_id") != run_id or step.get("step_id") != f"{run_id}:step0":
        raise ValueError("CORE_STEP_ID_MISMATCH")
    if any(event.get("step_id", step["step_id"]) != step["step_id"] for event in events):
        raise ValueError("CORE_TRACE_STEP_MISMATCH")
    if step.get("verification") != core.get("verification"):
        raise ValueError("CORE_VERIFICATION_MISMATCH")
    types = [event["type"] for event in events]
    terminals = [kind for kind in types if kind in {"run.completed", "run.blocked", "run.failed"}]
    if terminals != ["run." + report["task_status"]] or types[-1] != terminals[0]:
        raise ValueError("CORE_TRACE_TERMINAL_MISMATCH")
    if report.get("blocking_reasons") == ["EXPECTED_MANUAL_REVIEW_REQUIRED"]:
        required = ["tool.called", "tool.succeeded", "verification.started", "verification.passed", "recovery.decision", "run.blocked"]
        if any(types.count(kind) != 1 for kind in required) or "tool.failed" in types:
            raise ValueError("CORE_TRACE_SEMANTICS_MISMATCH")
        if [types.index(kind) for kind in required] != sorted(types.index(kind) for kind in required):
            raise ValueError("CORE_TRACE_ORDER_MISMATCH")
