"""@brief comtypes Pack and Go 子进程 worker。

由 ``sw_delivery._comtypes_pack_and_go`` 以独立子进程方式启动，接收 JSON
载荷 (stdin)，输出单行 JSON 结果 (stdout)。进程级隔离确保 comtypes 的 COM
初始化不会破坏父进程中已存在的 pywin32 代理 (RPC_E_DISCONNECTED)。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

os.environ["CADSTUDIO_PACK_WORKER"] = "1"


def main() -> int:
    payload = json.loads(sys.stdin.read())
    target = payload.get("target")
    existing = payload.get("existing_files") or {}
    try:
        from sw_delivery import _comtypes_pack_and_go_impl

        result = _comtypes_pack_and_go_impl(
            payload["source_path"],
            Path(target),
            {key: tuple(value) if value is not None else None for key, value in existing.items()},
            include_drawings=bool(payload["include_drawings"]),
            include_simulation_results=bool(payload["include_simulation_results"]),
            include_toolbox_components=bool(payload["include_toolbox_components"]),
            include_suppressed=bool(payload["include_suppressed"]),
            flatten=bool(payload["flatten"]),
            dependencies=payload.get("dependencies"),
        )
        print(json.dumps({"result": result}, ensure_ascii=False))
        return 0
    except BaseException as exc:  # noqa: BLE001 - 完整回传给父进程
        print(
            json.dumps(
                {
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=6),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
