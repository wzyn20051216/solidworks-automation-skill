"""四周拓展综合回归；默认不启动 CAD，真实桌面验证使用 --real-cad。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _decode_output(raw: bytes | None) -> str:
    """@brief 兼容 Python UTF-8/GB18030 与 AutoCAD Core Console UTF-16 输出。"""
    if not raw:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or raw.count(b"\x00") > len(raw) // 4:
        return raw.decode("utf-16", errors="replace") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030", errors="strict")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def run_regression(real_cad: bool = False) -> dict:
    commands = [
        [sys.executable, "scripts/stability_regression.py"],
        [sys.executable, "subskills/autocad-automation/scripts/acad_dotnet_preflight.py"],
    ]
    if real_cad:
        commands.extend([
            [sys.executable, "tests/solidworks_week3_delivery_regression.py"],
            [sys.executable, "tests/autocad_week4_drawing_regression.py"],
            [sys.executable, "subskills/autocad-automation/scripts/acad_dotnet_regression.py", "--real-cad"],
        ])
    results = []
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
        results.append({
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": _decode_output(completed.stdout)[-4000:],
            "stderr_tail": _decode_output(completed.stderr)[-2000:],
        })
    status = "pass" if all(item["returncode"] == 0 for item in results) else "failed"
    return {"status": status, "real_cad": real_cad, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="CAD Studio 四周拓展综合回归")
    parser.add_argument("--real-cad", action="store_true")
    args = parser.parse_args()
    result = run_regression(args.real_cad)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
