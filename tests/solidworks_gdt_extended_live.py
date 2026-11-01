"""SW2026 扩展 GD&T 原生矩阵：仅验证表达、持久关联和交付证据，不验证测试公差设计。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_gdt_copy import annotate_copy, validate_plan
from scripts.sw_session import SolidWorksSession
from scripts.sw_rename_copy import _sha256
from scripts.sw_connect import get_com_member


def extended_cases(base):
    cases = []

    def add(name, options=None, *, characteristic="position", diameter=True, datums=None, labels=()):
        plan = deepcopy(base)
        row = plan["geometricTolerances"][0]
        row.update(characteristic=characteristic, diameter=diameter, datums=["A"] if datums is None else datums)
        if options is not None:
            row["options"] = options
        for index, label in enumerate(labels):
            datum = deepcopy(base["datums"][0])
            datum.update(id="DAT-" + label, label=label, positionMm=[125 - 10 * index, 126])
            datum["target"] = {"kind": "line", "startMm": [-40, 30, 20], "endMm": [-40, -30, 20]}
            plan["datums"].append(datum)
        cases.append((name, plan))

    add("common", datums=[{"common": ["A", "B"]}], labels=["B"])
    add("common_material", datums=[{"common": [{"label": "A", "materialCondition": "M"}, {"label": "B", "materialCondition": "L"}]}], labels=["B"])
    add("sub_datums", datums=[{"common": ["A", "B"], "subDatums": [["C", "D"]]}], labels=["B", "C", "D"])
    add("projected", {"projectedZone": {"projection": "12"}})
    add("projected_range", {"projectedZone": {"projection": "12", "range": "4"}})
    add("profile_unequal", {"profileZone": {"unequalOutside": "0.05"}}, characteristic="surface_profile", diameter=False)
    add("profile_offsets", {"profileZone": {"offsets": [{"direction": "outside", "value": "0.1"}, {"direction": "inside", "value": "0.05"}],
                                            "dynamic": True, "combination": "CZ", "constraints": ["offset", "angularOffset", "orientationOnly"]}}, characteristic="surface_profile", diameter=False)
    add("combined_zone", {"profileZone": {"combination": "CZ"}})
    add("separate_zone", {"profileZone": {"combination": "SZ", "constraints": ["orientationOnly"]}})
    for condition in ("M", "L"):
        add("reciprocity_" + condition, {"reciprocity": True})
        cases[-1][1]["geometricTolerances"][0]["materialCondition"] = condition
    add("state_statistical", {"freeState": True, "statistical": True}, characteristic="flatness", diameter=False, datums=[])
    add("false_defaults", {"freeState": False, "statistical": False, "derivedFeature": False, "reciprocity": False},
        datums=[{"label": "A", "modifiers": {"freeState": False}, "constraints": {"rotationX": False}}])
    add("spherical_zone", {"zoneShape": "sphericalDiameter"})
    add("square_zone", {"zoneShape": "square"}, characteristic="flatness", diameter=False, datums=[])
    add("unit_max", {"unitZone": {"separator": "/", "value": "100", "symbol": "none", "limit": {"separator": "X", "value": "50", "symbol": "none"}},
                     "maxTolerance": {"value": "0.5", "diameter": True}}, characteristic="straightness", datums=[])
    add("associated_filters", {"associatedFeature": "LeastSquares", "derivedFeature": True,
                               "associatedCharacteristic": "C", "parametricCharacteristic": "P",
                               "filters": [{"symbol": "G", "cutOff": "0.8", "shortWave": True, "separator": "X",
                                            "second": {"cutOff": "2.5", "longWave": True}}]}, characteristic="circularity", diameter=False, datums=[])
    add("datum_constraints", datums=[{"label": "A", "constraints": {**{key: True for key in ("translationX", "translationY", "translationZ", "rotationX", "rotationY", "rotationZ", "contactFeature", "orientationOnly", "variableDistance")},
                                                                   "translation": ["1", "-2", "0"]}}])
    add("datum_modifiers", datums=[{"label": "A", "materialCondition": "M", "modifiers": {"situation": "plane", "section": "cross", "projection": "5", "freeState": True}}])
    add("datum_line_section", datums=[{"label": "A", "modifiers": {"situation": "straightLine", "section": "longitudinal"}}])
    add("datum_point", datums=[{"label": "A", "modifiers": {"situation": "point"}}])
    for library in ("asme", "gb"):
        add("library_" + library, {"symbolLibrary": library})
    # 新语义同时进入复合后续层，不能只覆盖旧单框调用。
    add("composite_extended", datums=[{"common": ["A", "B"]}], labels=["B"])
    row = cases[-1][1]["geometricTolerances"][0]
    frame = {key: row.pop(key) for key in ("characteristic", "diameter", "tolerance", "datums")}
    frame["options"] = {"projectedZone": {"projection": "12"}}
    row["frames"] = [frame, {**deepcopy(frame), "tolerance": "0.1", "composite": True}]
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="自建四孔板测试工程图")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="只执行指定用例；默认执行全部")
    parser.add_argument("--negative", action="store_true", help="追加缺失公共基准成员的真实前置阻断/源保护验证")
    args = parser.parse_args()
    base = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    cases = [(name, plan) for name, plan in extended_cases(base) if not args.only or name in args.only]
    if not cases or args.only and set(args.only) - {name for name, _ in cases}:
        raise ValueError("用例名称无效")
    for _, plan in cases:
        validate_plan(plan)
    output = Path(tempfile.mkdtemp(prefix="sw_gdt_extended_"))
    results = []
    with SolidWorksSession(version=2026, visible=True) as session:
        for name, plan in cases:
            result = annotate_copy(args.source, plan, output / name)
            passed = result.get("nativeValidation") == "pass" and result["status"] == "review_required"
            results.append({"case": name, "passed": passed, "error": result.get("error")})
            (output / "matrix.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print("PASS" if passed else "FAIL", name, result.get("error"), flush=True)
        if args.negative:
            before = sorted(str(get_com_member(doc, "GetPathName")) for doc in session._documents())
            digest = _sha256(args.source)
            missing = deepcopy(base)
            missing["geometricTolerances"][0]["datums"] = [{"common": ["A", "B"]}]
            blocked_dir = output / "missing_member"
            result = annotate_copy(args.source, missing, blocked_dir)
            assert result["status"] == "blocked" and not result["outputs"], result
            assert "不存在的基准" in result["error"], result
            assert not blocked_dir.exists() and _sha256(args.source) == digest
            assert sorted(str(get_com_member(doc, "GetPathName")) for doc in session._documents()) == before
            print("PASS negative_missing_member", flush=True)
    print("extended output", output, flush=True)
    assert all(item["passed"] for item in results), results


if __name__ == "__main__":
    main()
