"""SW2026 多框/复合框及基准修饰的真实副本回归；不证明示例公差的制造合理性。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_gdt_copy import annotate_copy
from scripts.sw_session import SolidWorksSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True, help="已通过的四孔板源计划")
    args = parser.parse_args()
    base = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    output = Path(tempfile.mkdtemp(prefix="sw_gdt_advanced_"))
    cases = []
    for condition in ("M", "L", "S"):
        plan = deepcopy(base)
        plan["geometricTolerances"][0]["datums"] = [{"label": "A", "materialCondition": condition}]
        cases.append(("datum_" + condition, plan))
    for composite in (False, True):
        plan = deepcopy(base)
        row = plan["geometricTolerances"][0]
        for key in ("characteristic", "tolerance", "diameter", "datums", "materialCondition"):
            row.pop(key, None)
        first = {"characteristic": "position", "tolerance": "0.2", "diameter": True,
                 "datums": [{"label": "A", "materialCondition": "M"}]}
        row["frames"] = [first, {**deepcopy(first), "tolerance": "0.1", "composite": composite}]
        cases.append(("composite" if composite else "stacked", plan))
    with SolidWorksSession(version=2026, visible=True):
        for name, plan in cases:
            result = annotate_copy(args.source, plan, output / name)
            if result.get("nativeValidation") != "pass" or result["status"] != "review_required":
                raise AssertionError(f"{name}: {result}")
            print("PASS", name, flush=True)
    print("advanced output", output, flush=True)


if __name__ == "__main__":
    main()
