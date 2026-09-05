"""@brief 在真实 SolidWorks 会话中加载并验证 C# Add-in 宿主。"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import win32com.client


ADDIN_GUID = "8EE76E8D-9B47-4DE0-AFA2-B2E36621A134"


def _com_value(owner, name: str, *args):
    """@brief 兼容 pywin32 将无参 COM 方法暴露为属性或可调用对象的差异。"""
    member = getattr(owner, name)
    # CDispatch 表示 pywin32 在取属性时已经执行了无参 COM 调用；它虽然
    # 也实现了 __call__，再次调用却会尝试访问并不存在的默认成员。
    if not args and hasattr(member, "_oleobj_"):
        return member
    return member(*args) if callable(member) else member


def _diagnostic_path() -> Path:
    """@brief 返回 Add-in 与测试共享的当前用户诊断路径。"""
    return Path(os.environ["LOCALAPPDATA"]) / "CAD Studio" / "SolidWorksAddin" / "host-status.json"


def _wait_for_connected(path: Path, timeout_seconds: float = 20.0, *, require_property_page: bool = True) -> dict:
    """@brief 等待 Add-in 写出已连接和 UI 子系统就绪的证据。"""
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict = {}
    while time.monotonic() < deadline:
        if path.exists():
            try:
                last_payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                time.sleep(0.2)
                continue
            if (
                last_payload.get("status") == "connected"
                and str(last_payload.get("hostProcessName", "")).casefold() == "sldworks"
                and last_payload.get("callbackRegistered") is True
                and last_payload.get("commandGroupReady") is True
                and last_payload.get("taskPaneReady") is True
                and (last_payload.get("propertyManagerPageReady") is True or not require_property_page)
            ):
                return last_payload
        time.sleep(0.2)
    raise RuntimeError(f"Add-in 未在 {timeout_seconds:.0f}s 内就绪：{last_payload}")


def run_regression(assembly: Path, *, keep_loaded: bool = True, start_solidworks: bool = False) -> dict:
    """@brief 加载宿主、触发应用事件并核验机器可读诊断证据。"""
    assembly = assembly.expanduser().resolve()
    if not assembly.is_file():
        raise FileNotFoundError(assembly)
    diagnostics = _diagnostic_path()
    if diagnostics.exists():
        diagnostics.unlink()

    started_solidworks = False
    try:
        sw_app = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        if not start_solidworks:
            raise RuntimeError("SolidWorks 未运行；传入 --start 可启动本机默认版本。")
        sw_app = win32com.client.Dispatch("SldWorks.Application")
        sw_app.Visible = True
        started_solidworks = True
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            try:
                _com_value(sw_app, "RevisionNumber")
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("SolidWorks 启动后 45s 内未就绪。")
    load_status = int(sw_app.LoadAddIn(str(assembly)))
    if load_status not in {0, 2}:
        raise RuntimeError(f"LoadAddIn 失败，swLoadAddinError_e={load_status}")
    initial = _wait_for_connected(diagnostics, require_property_page=False)
    revision = str(_com_value(sw_app, "RevisionNumber"))
    if initial.get("solidWorksRevision") != revision:
        raise AssertionError((initial.get("solidWorksRevision"), revision))

    created = _com_value(sw_app, "NewPart")
    if created is None:
        raise RuntimeError("NewPart 未返回文档，无法验证 FileNewNotify2。")
    title = str(_com_value(created, "GetTitle"))
    sw_app.CloseDoc(title)
    event_payload = _wait_for_event(diagnostics, "file_new")
    event_payload = _wait_for_event(diagnostics, "active_model_doc_change")
    documents_after_close = int(_com_value(sw_app, "GetDocumentCount"))
    if documents_after_close != 0:
        raise RuntimeError(f"CloseDoc 后仍有 {documents_after_close} 个文档打开。")

    unload_status = None
    if not keep_loaded:
        unload_status = int(sw_app.UnloadAddIn(str(assembly)))
        if unload_status != 0:
            raise RuntimeError(f"UnloadAddIn 失败，状态={unload_status}")

    return {
        "status": "pass",
        "addin_guid": ADDIN_GUID,
        "assembly": str(assembly),
        "assembly_bytes": assembly.stat().st_size,
        "load_status": load_status,
        "unload_status": unload_status,
        "solidworks_revision": revision,
        "solidworks_started_by_probe": started_solidworks,
        "diagnostics": str(diagnostics),
        "command_group_ready": event_payload["commandGroupReady"],
        "task_pane_ready": event_payload["taskPaneReady"],
        "property_manager_page_ready": event_payload["propertyManagerPageReady"],
        "event_counts": event_payload["eventCounts"],
        "documents_after_close": documents_after_close,
        "errors": event_payload["errors"],
    }


def _wait_for_event(path: Path, name: str, timeout_seconds: float = 10.0) -> dict:
    """@brief 等待指定事件至少触发一次。"""
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict = {}
    while time.monotonic() < deadline:
        try:
            last_payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            time.sleep(0.2)
            continue
        if int(last_payload.get("eventCounts", {}).get(name, 0)) >= 1:
            return last_payload
        time.sleep(0.2)
    raise RuntimeError(f"未观察到事件 {name}：{last_payload}")


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", required=True, type=Path)
    parser.add_argument("--unload", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_regression(
        args.assembly,
        keep_loaded=not args.unload,
        start_solidworks=args.start,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
