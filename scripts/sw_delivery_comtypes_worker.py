"""@brief comtypes Pack and Go 子进程 worker。

由 ``sw_delivery._comtypes_pack_and_go`` 以独立子进程方式启动，接收 JSON
载荷 (stdin)，输出单行 JSON 结果 (stdout)。隔离 Python COM 库状态；
共享 CAD 服务的退出与文档清理仍必须按 PID 和文档归属单独校验。
"""
from __future__ import annotations

import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    """@brief 有界 JSON 输入，显式 COM 生命周期，stdout 只承载一次结果。"""
    initialized = False
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Pack and Go 请求超过 1 MiB")
        payload = json.loads(raw.decode("utf-8"))
        target = payload["target"]
        existing = payload.get("existing_files") or {}
        if not isinstance(payload.get("expected_pid"), int) or payload["expected_pid"] <= 0:
            raise ValueError("回退必须明确父实例 PID")
        import pythoncom
        pythoncom.CoInitialize()
        initialized = True
        from sw_delivery import _comtypes_pack_and_go_impl

        with redirect_stdout(sys.stderr):
            result = _comtypes_pack_and_go_impl(
                payload["source_path"], Path(target),
                {key: tuple(value) if value is not None else None for key, value in existing.items()},
                include_drawings=bool(payload["include_drawings"]),
                include_simulation_results=bool(payload["include_simulation_results"]),
                include_toolbox_components=bool(payload["include_toolbox_components"]),
                include_suppressed=bool(payload["include_suppressed"]),
                flatten=bool(payload["flatten"]), dependencies=payload.get("dependencies"),
                expected_pid=payload["expected_pid"],
            )
        print(json.dumps({"result": result}, ensure_ascii=True))
        return 0
    except BaseException as exc:  # noqa: BLE001 - 完整回传给父进程
        print(
            json.dumps(
                {
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "code": getattr(exc, "code", None),
                    "traceback": traceback.format_exc(limit=6),
                },
                ensure_ascii=True,
            )
        )
        return 1
    finally:
        if initialized:
            pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
