# -*- coding: utf-8 -*-
"""@file sw_live_probe.py
@brief SolidWorks 活体 COM 探针。

只挂到已经运行的 SolidWorks 实例；默认不启动新进程，避免健康检查把
几十秒的冷启动带进 UI。需要明确加 ``--launch`` 才会 Dispatch 启动。
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cad_installation import discover_installation  # noqa: E402


def _result(status: str, **kwargs: Any) -> Dict[str, Any]:
    """@brief 构造统一 JSON 结果。"""
    data: Dict[str, Any] = {"status": status}
    data.update(kwargs)
    return data


def check_pywin32() -> Dict[str, Any]:
    """@brief 检查 pywin32 是否可导入。"""
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except Exception as exc:
        return _result(
            "missing",
            package="pywin32",
            error=repr(exc),
            install="python -m pip install pywin32",
        )
    return _result("ok", package="pywin32")


def check_solidworks(launch: bool) -> Dict[str, Any]:
    """@brief 检查能否连接到正在运行的 SolidWorks。"""
    installation = discover_installation("solidworks")
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:  # pragma: no cover - 依赖环境相关
        return _result("missing_pywin32", error=repr(exc))

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("SldWorks.Application")
        mode = "active"
    except Exception as active_exc:
        if not launch:
            return _result(
                "not_running",
                prog_id="SldWorks.Application",
                installed=installation["installed"],
                executable=installation["executable"],
                installed_version=installation.get("version"),
                error=repr(active_exc),
                hint="SolidWorks 已安装但未运行，启动后可自动连接。",
            )
        try:
            app = win32com.client.Dispatch("SldWorks.Application")
            mode = "launched"
        except Exception as launch_exc:
            return _result(
                "unavailable",
                prog_id="SldWorks.Application",
                installed=installation["installed"],
                executable=installation["executable"],
                error=repr(launch_exc),
                hint="无法启动 SolidWorks COM，请手动打开一次完成注册。",
            )

    try:
        app.Visible = True
    except Exception:
        pass

    revision = ""
    try:
        revision = str(app.RevisionNumber)
    except Exception:
        pass

    document = ""
    document_path = ""
    try:
        active = app.ActiveDoc
    except Exception:
        active = None
    if active is not None:
        try:
            document = str(active.GetTitle())
        except Exception:
            document = ""
        try:
            document_path = str(active.GetPathName())
        except Exception:
            document_path = ""

    process_id = None
    try:
        process_id = int(app.GetProcessID())
    except Exception:
        process_id = None

    return _result(
        "ok",
        prog_id="SldWorks.Application",
        installed=installation["installed"],
        executable=installation["executable"],
        installed_version=installation.get("version"),
        service_pack=installation.get("servicePack"),
        mode=mode,
        revision=revision,
        document=document,
        document_path=document_path,
        process_id=process_id,
    )


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="SolidWorks 活体 COM 自检")
    parser.add_argument("--launch", action="store_true", help="允许脚本启动 SolidWorks")
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "python": sys.executable,
        "platform": platform.platform(),
        "pywin32": check_pywin32(),
    }
    if report["pywin32"]["status"] == "ok":
        report["solidworks"] = check_solidworks(args.launch)
    else:
        report["solidworks"] = _result("skipped", reason="pywin32_missing")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["pywin32"]["status"] != "ok":
        return 2
    if report["solidworks"]["status"] != "ok":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
