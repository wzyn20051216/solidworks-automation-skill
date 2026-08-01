"""四周拓展综合回归；默认不启动 CAD，真实桌面验证使用 --real-cad。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_regression(real_cad: bool = False) -> dict:
    commands = [
        [sys.executable, "scripts/stability_regression.py"],
        [sys.executable, "subskills/autocad-automation/scripts/acad_dotnet_preflight.py"],
    ]
    if real_cad:
        commands.extend([
            [sys.executable, "tests/solidworks_week3_delivery_regression.py"],
            [sys.executable, "tests/autocad_week4_drawing_regression.py"],
        ])
    results = []
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        results.append({"command": command, "returncode": completed.returncode, "stdout_tail": completed.stdout[-4000:], "stderr_tail": completed.stderr[-2000:]})
    status = "pass" if all(item["returncode"] == 0 for item in results) else "failed"
    return {"status": status, "real_cad": real_cad, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="CAD Studio 四周拓展综合回归")
    parser.add_argument("--real-cad", action="store_true")
    args = parser.parse_args()
    result = run_regression(args.real_cad)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
