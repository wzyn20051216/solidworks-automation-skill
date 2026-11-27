"""对照零件的近似包围盒、解析尺寸和规格验收结果。"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_from_spec import build_from_spec
from scripts.design_spec import compare_verification
from scripts.sw_connect import (
    connect_solidworks,
    get_com_member as get,
    get_sw_version,
    new_document,
    open_document,
    save_document,
)
from scripts.sw_measure import collect_bounding_box, collect_exact_part_bounding_box
from scripts.sw_part import extrude_boss, sketch
from scripts.sw_review import collect_model_summary, save_preview
from scripts.sw_process import solidworks_processes


def _make_fixture(model):
    # 倾斜 30° 的椭圆。二维轴向极值可由两个半轴的投影解析计算。
    a, b, depth = 0.04, 0.01, 0.006
    sine, cosine = 0.5, math.sqrt(3) / 2
    with sketch(model, "Front Plane") as profile:
        manager = model.SketchManager
        add_to_db = manager.AddToDB
        try:
            manager.AddToDB = True
            ellipse = manager.CreateEllipse(
                0., 0., 0., a * cosine, a * sine, 0., -b * sine, b * cosine, 0.
            )
            assert ellipse is not None
        finally:
            manager.AddToDB = add_to_db
    feature = extrude_boss(model, profile, depth)
    assert feature is not None
    feature.Name = "倾斜椭圆柱"
    assert model.ForceRebuild3(False)
    model.ViewZoomtofit2()


def _measure(model):
    a, b, depth = 40., 10., 6.
    sine, cosine = 0.5, math.sqrt(3) / 2
    expected_mm = [
        2 * math.hypot(a * cosine, b * sine),
        2 * math.hypot(a * sine, b * cosine),
        depth,
    ]
    verify = {"envelope_mm": expected_mm, "tolerance_mm": 0.001}
    bodies = get(model, "GetBodies2", 0, False)
    assert len(bodies) == 1
    volume_mm3 = get(bodies[0], "GetMassProperties", 1.)[3] * 1e9
    # 此体积仅用于核对试件，SolidWorks 的质量属性积分有数值误差。
    assert math.isclose(volume_mm3, math.pi * a * b * depth, rel_tol=1e-4)
    summary = collect_model_summary(model)
    assert not summary.get("feature_error")
    assert not summary["faulty_features"] and not summary["warning_features"]
    assert not summary["unknown_feature_health"]
    approximate = collect_bounding_box(model)
    assert not approximate["errors"]
    geometric = collect_exact_part_bounding_box(model)
    assert not geometric["errors"]
    old = compare_verification({"envelope_mm": approximate["size_mm"]}, verify)
    current = build_from_spec(model, {"base": {"type": "none"}, "verify": verify})
    check = current["verification"]["checks"][0]
    assert check["passed"] and check["actual"] == geometric["size_mm"]
    return {
        "expected_mm": expected_mm,
        "volume_mm3": volume_mm3,
        "approximate_mm": approximate["size_mm"],
        "approximate_check": old["checks"][0],
        "extrema_mm": geometric["size_mm"],
        "spec_check": check,
    }


def _run(args):
    output = args.output.resolve()
    path = output / "spec-envelope-ellipse.SLDPRT"
    if args.reopen:
        assert path.is_file() and (output / "native-report.json").is_file()
    else:
        output.mkdir(parents=True, exist_ok=False)
    report_path = output / ("recheck.json" if args.reopen else "native-report.json")
    assert not report_path.exists()
    assert solidworks_processes() == {args.process_id: args.version}
    sw, _, metadata = connect_solidworks(args.version, visible=True, return_metadata=True)
    assert metadata["process_id"] == args.process_id and not metadata["started_by_cad_studio"]
    assert bool(get(sw, "Visible"))
    if args.blank_title:
        model = get(sw, "ActiveDoc")
        assert get(model, "GetTitle") == args.blank_title
        assert get(model, "GetType") == 1 and not get(model, "GetPathName")
        assert not get(model, "GetBodies2", 0, False)
        assert len(get(sw, "GetDocuments") or []) == 1
    else:
        assert not get(sw, "GetDocuments")
        model = None

    report = {
        "environment": get_sw_version(sw),
        "isolated_instance_started_by_test": False,
        "source_sha256": {
            name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
            for name in ("sw_measure.py", "build_from_spec.py")
        },
    }
    if not args.reopen:
        if model is None:
            model = new_document(sw, "part")
        print("建立并保存倾斜椭圆柱", flush=True)
        _make_fixture(model)
        report["before_close"] = _measure(model)
        save_preview(model, str(output / "ellipse.bmp"), "isometric")
        assert save_document(model, str(path)) and not get(model, "GetSaveFlag")
        assert Path(get(model, "GetPathName")).resolve() == path
        sw.CloseDoc(get(model, "GetTitle"))
        assert not get(sw, "GetDocuments")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    model = open_document(sw, str(path), silent=True, read_only=True, raise_on_error=True)
    assert Path(get(model, "GetPathName")).resolve() == path
    print("重开同一零件并对照规格验收", flush=True)
    try:
        assert model.ForceRebuild3(False)
        report["after_reopen"] = _measure(model)
    finally:
        sw.CloseDoc(get(model, "GetTitle"))
    assert not get(sw, "GetDocuments")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    report["model_sha256"] = digest
    report["remaining_documents"] = 0
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--process-id", type=int, required=True)
    parser.add_argument("--blank-title", help="可选，由 MCP 本轮新建的唯一空白零件标题")
    parser.add_argument("--reopen", action="store_true", help="使用上次输出的同一零件")
    args = parser.parse_args()
    if args.reopen and args.blank_title:
        parser.error("--reopen 与 --blank-title 不可同时使用")
    # 仅限本手工测试进程。connect_solidworks 仍核对实例身份。
    os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"
    _run(args)
