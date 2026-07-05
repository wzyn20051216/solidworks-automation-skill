# -*- coding: utf-8 -*-
"""@file acad_preflight.py
@brief AutoCAD 自动化入口自检脚本。

此脚本只检查 Python COM 依赖和 AutoCAD COM 可用性，不修改图纸。
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from typing import Any, Dict


def _result(status: str, **kwargs: Any) -> Dict[str, Any]:
    """@brief 构造统一 JSON 输出。"""
    data: Dict[str, Any] = {"status": status}
    data.update(kwargs)
    return data


def check_pywin32() -> Dict[str, Any]:
    """@brief 检查 pywin32 是否可导入。"""
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except Exception as exc:  # pragma: no cover - 依赖环境相关
        return _result(
            "missing",
            package="pywin32",
            error=repr(exc),
            install="python -m pip install pywin32",
        )
    return _result("ok", package="pywin32")


def check_autocad(launch: bool) -> Dict[str, Any]:
    """@brief 检查是否能连接或启动 AutoCAD COM。

    @param launch 为 True 时允许启动 AutoCAD。
    @return AutoCAD 连接状态。
    """
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:  # pragma: no cover
        return _result("missing_pywin32", error=repr(exc))

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        mode = "active"
    except Exception as active_exc:
        if not launch:
            return _result(
                "not_running",
                prog_id="AutoCAD.Application",
                error=repr(active_exc),
                hint="AutoCAD 未运行；如需自动启动，请加 --launch。",
            )
        try:
            app = win32com.client.Dispatch("AutoCAD.Application")
            mode = "launched"
        except Exception as launch_exc:
            return _result(
                "unavailable",
                prog_id="AutoCAD.Application",
                error=repr(launch_exc),
                hint="请确认已安装 Windows 桌面版 AutoCAD，并手动启动一次完成 COM 注册。",
            )

    try:
        app.Visible = True
    except Exception:
        pass

    doc_name = None
    try:
        doc_name = app.ActiveDocument.Name
    except Exception:
        doc_name = None

    return _result(
        "ok",
        prog_id="AutoCAD.Application",
        mode=mode,
        version=str(getattr(app, "Version", "")),
        caption=str(getattr(app, "Caption", "")),
        active_document=doc_name,
    )


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="AutoCAD 自动化自检")
    parser.add_argument("--launch", action="store_true", help="允许脚本启动 AutoCAD")
    args = parser.parse_args()

    report = {
        "python": sys.executable,
        "platform": platform.platform(),
        "pywin32": check_pywin32(),
    }
    if report["pywin32"]["status"] == "ok":
        report["autocad"] = check_autocad(args.launch)
    else:
        report["autocad"] = _result("skipped", reason="pywin32_missing")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["pywin32"]["status"] != "ok":
        return 2
    if report["autocad"]["status"] != "ok":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

