"""SolidWorks 三维模型错误检查能力真机回归。

该脚本需要 Windows、受支持的 SolidWorks 和 pywin32。它不会被普通 pytest
自动收集，必须人工或由 Windows 自托管 CI 显式执行。

覆盖 2026-08 修复的错误检查缺口(分支 fix/error-check-hardening):
  1. 故障特征零件(空草图 -> 特征错误码 + 重建失败 + 零包络)必须被 run_review
     判为 fail 并给出 rebuild_failed / feature_errors_present / degenerate_envelope。
  2. 受控干涉装配体(同位置双件)必须被检出 interference_detected;
     分离双件装配体必须 pass 且不产生干涉 issue。
  3. 空工程图必须被判为 fail 并给出 drawing_views_missing。
  4. 损坏文件(文本改名 .sldprt)必须抛 SolidWorksDocumentOpenError,
     错误码分类为 swFileRequiresRepairError。
  5. 健康零件不得误报(无 rebuild_failed / feature_errors_present)。
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from sw_assembly import add_component, get_interference_detection  # noqa: E402
from sw_connect import (  # noqa: E402
    SolidWorksDocumentOpenError,
    classify_sw_file_load_errors,
    connect_solidworks,
    get_com_member,
    new_document,
    open_document,
    save_document,
)
from sw_part import (  # noqa: E402
    _select_com_object,
    current_sketch_name,
    end_sketch,
    extrude_boss,
    sketch_corner_rectangle,
    start_sketch,
)
from sw_review import run_review  # noqa: E402


def _default_output_dir() -> Path:
    """@brief 返回本回归的默认输出根目录。"""
    return Path(tempfile.gettempdir()) / "solidworks_errorcheck_regression"


def _fresh_target(sw, path: Path) -> None:
    """@brief 关闭同名文档并删除旧文件, 避免残留产物干扰本轮断言。"""
    try:
        sw.CloseDoc(path.name)
    except Exception:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _issue_codes(report: dict) -> list:
    return [item["code"] for item in report["evaluation"]["issues"]]


def _iter_features(model):
    """@brief 遍历特征 COM 对象(动态派发兼容: 属性/方法歧义统一走 get_com_member)。"""
    feature = get_com_member(model, "FirstFeature")
    while feature is not None:
        yield feature
        feature = get_com_member(feature, "GetNextFeature")


def _feature_error_code(feature):
    """@brief 读取特征错误码; 动态派发下可能是属性, 无参 get_com_member 兼容。"""
    try:
        return int(get_com_member(feature, "GetErrorCode") or 0)
    except Exception:
        return 0


def _build_healthy_box(model) -> None:
    """@brief 前视基准面 10x10mm 矩形拉伸 10mm(注意: sw_part 草图坐标单位是米)。"""
    start_sketch(model, "Front Plane")
    sketch_corner_rectangle(model, -0.005, -0.005, 0.005, 0.005)
    end_sketch(model)
    boss = extrude_boss(model, current_sketch_name(model), 0.01)
    if boss is None:
        raise RuntimeError("基体拉伸特征创建失败")


def _break_base_sketch(model) -> None:
    """@brief 清空 Sketch1 的全部草图段, 使两级拉伸特征进入错误态。"""
    sketch1 = None
    for feature in _iter_features(model):
        if get_com_member(feature, "Name") == "Sketch1":
            sketch1 = feature
            break
    if sketch1 is None:
        raise RuntimeError("未找到 Sketch1")
    _select_com_object(sketch1)
    get_com_member(model, "EditSketch")
    sketch_obj = get_com_member(sketch1, "GetSpecificFeature2")
    segments = get_com_member(sketch_obj, "GetSketchSegments") or []
    if not segments:
        raise RuntimeError("Sketch1 没有可删除的草图段")
    for segment in segments:
        _select_com_object(segment, append=True)
    if not get_com_member(model, "DeleteSelection", False):
        raise RuntimeError("草图段删除失败")
    get_com_member(model, "InsertSketch")  # 退出草图编辑


def scenario_faulty_part(sw, out_dir: Path) -> dict:
    """@brief 场景1: 故障特征零件必须 fail 且三条硬失败齐备。"""
    part_path = out_dir / "faulty_part.SLDPRT"
    _fresh_target(sw, part_path)
    model = new_document(sw, "part")
    _build_healthy_box(model)
    # 直接清空基体草图: 拉伸特征失去轮廓 -> 错误码 + 重建失败 + 零包络
    _break_base_sketch(model)
    save_document(model, str(part_path))

    # 地面真值: 重建必须失败且特征错误码非 0
    rebuild_ok = bool(get_com_member(model, "ForceRebuild3", False))
    faulty = [
        get_com_member(feature, "Name")
        for feature in _iter_features(model)
        if _feature_error_code(feature)
    ]
    if rebuild_ok or not faulty:
        raise RuntimeError(f"故障件构造未生效: rebuild_ok={rebuild_ok}, faulty={faulty}")

    report, report_path = run_review(model, str(out_dir / "review_faulty"), basename="faulty")
    codes = _issue_codes(report)
    for expected in ("rebuild_failed", "feature_errors_present", "degenerate_envelope"):
        if expected not in codes:
            raise RuntimeError(f"故障件未报 {expected}: {codes}")
    if report["evaluation"]["status"] != "fail":
        raise RuntimeError(f"故障件状态应为 fail: {report['evaluation']}")
    return {"scenario": "faulty_part", "status": "fail(预期)", "codes": codes,
            "faulty_features": faulty, "report": str(report_path)}


def _build_two_box_assembly(sw, out_dir: Path, overlapping: bool) -> Path:
    """@brief 新建装配体并两次放置同一个零件(重叠或分离)。"""
    part_path = out_dir / ("shared_box.SLDPRT" if overlapping else "shared_box_far.SLDPRT")
    asm_path = out_dir / ("interference_asm.SLDASM" if overlapping else "clean_asm.SLDASM")
    _fresh_target(sw, part_path)
    _fresh_target(sw, asm_path)
    part_model = new_document(sw, "part")
    _build_healthy_box(part_model)
    save_document(part_model, str(part_path))
    if not part_path.is_file() or part_path.stat().st_size <= 0:
        raise RuntimeError(f"零件保存失败: {part_path}")
    asm_model = new_document(sw, "assembly")
    offset = 0.0 if overlapping else 0.05
    add_component(asm_model, str(part_path), 0, 0, 0, sw=sw)
    add_component(asm_model, str(part_path), offset, 0, 0, sw=sw)
    save_document(asm_model, str(asm_path))
    if not asm_path.is_file() or asm_path.stat().st_size <= 0:
        raise RuntimeError(f"装配体保存失败: {asm_path}")
    return asm_path


def scenario_interference(sw, out_dir: Path) -> dict:
    """@brief 场景2: 重叠装配体检出干涉, 分离装配体不误报。"""
    overlapping_path = _build_two_box_assembly(sw, out_dir, overlapping=True)
    asm = open_document(sw, str(overlapping_path), silent=True, raise_on_error=True)
    detection = get_interference_detection(asm)
    if detection["status"] != "warn" or not detection["interference_count"]:
        raise RuntimeError(f"重叠装配体未检出干涉: {detection}")
    report, report_path = run_review(asm, str(out_dir / "review_interference"), basename="interference")
    codes = _issue_codes(report)
    if "interference_detected" not in codes:
        raise RuntimeError(f"run_review 未报 interference_detected: {codes}")
    if detection["api"] not in ("modern", "legacy"):
        raise RuntimeError(f"干涉 API 代际异常: {detection['api']}")

    clean_path = _build_two_box_assembly(sw, out_dir, overlapping=False)
    clean_asm = open_document(sw, str(clean_path), silent=True, raise_on_error=True)
    clean_detection = get_interference_detection(clean_asm)
    clean_report, _ = run_review(clean_asm, str(out_dir / "review_clean"), basename="clean")
    if clean_detection["status"] != "pass" or clean_detection["interference_count"] != 0:
        raise RuntimeError(f"分离装配体被误报干涉: {clean_detection}")
    if "interference_detected" in _issue_codes(clean_report):
        raise RuntimeError("分离装配体 run_review 误报 interference_detected")
    return {"scenario": "interference", "overlapping": detection, "clean": "pass",
            "report": str(report_path)}


def scenario_empty_drawing(sw, out_dir: Path) -> dict:
    """@brief 场景3: 空工程图必须 fail 并报 drawing_views_missing。"""
    model = new_document(sw, "drawing")
    report, report_path = run_review(model, str(out_dir / "review_empty_drawing"), basename="empty_drw")
    codes = _issue_codes(report)
    if "drawing_views_missing" not in codes:
        raise RuntimeError(f"空工程图未报 drawing_views_missing: {codes}")
    if report["evaluation"]["status"] != "fail":
        raise RuntimeError("空工程图状态应为 fail")
    return {"scenario": "empty_drawing", "status": "fail(预期)", "codes": codes,
            "report": str(report_path)}


def scenario_corrupt_file(sw, out_dir: Path) -> dict:
    """@brief 场景4: 损坏文件必须结构化失败并携带分类错误码。"""
    fake_path = out_dir / "fake.sldprt"
    fake_path.write_text("not a real solidworks file\n", encoding="utf-8")
    try:
        open_document(sw, str(fake_path), silent=True, raise_on_error=True)
    except SolidWorksDocumentOpenError as exc:
        if not (exc.error_code & 2097152):
            raise RuntimeError(f"损坏文件错误码异常: {exc.error_code}") from exc
        label = classify_sw_file_load_errors(exc.error_code)
        if "swFileRequiresRepairError" not in label:
            raise RuntimeError(f"错误码未分类为 swFileRequiresRepairError: {label}") from exc
        return {"scenario": "corrupt_file", "error_code": exc.error_code, "label": label}
    raise RuntimeError("损坏文件未抛 SolidWorksDocumentOpenError")


def scenario_healthy_part(sw, out_dir: Path) -> dict:
    """@brief 场景5: 健康零件不得误报健康度 issue。"""
    model = new_document(sw, "part")
    _build_healthy_box(model)
    report, report_path = run_review(model, str(out_dir / "review_healthy"), basename="healthy")
    codes = _issue_codes(report)
    for forbidden in ("rebuild_failed", "feature_errors_present", "degenerate_envelope",
                      "geometry_measurements_unavailable"):
        if forbidden in codes:
            raise RuntimeError(f"健康零件误报 {forbidden}: {codes}")
    if report["evaluation"]["status"] == "fail":
        raise RuntimeError(f"健康零件被判 fail: {codes}")
    return {"scenario": "healthy_part", "status": report["evaluation"]["status"], "codes": codes,
            "report": str(report_path)}


SCENARIOS = (
    ("faulty_part", scenario_faulty_part),
    ("interference", scenario_interference),
    ("empty_drawing", scenario_empty_drawing),
    ("corrupt_file", scenario_corrupt_file),
    ("healthy_part", scenario_healthy_part),
)


def main() -> int:
    """@brief 顺序执行全部场景并输出 JSON 汇总; 任一失败返回 1。"""
    parser = argparse.ArgumentParser(description="SolidWorks 三维模型错误检查真机回归")
    parser.add_argument("--output-dir", default=str(_default_output_dir()))
    args = parser.parse_args()

    # 每次运行使用独立时间戳子目录, 避免与上一轮残留的同名文档/文件冲突
    # (SW 中同名已打开文档会使 SaveAs 报 swGenericSaveError)。
    out_dir = Path(args.output_dir) / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    sw, _ = connect_solidworks()

    results = []
    failed = False
    for name, scenario in SCENARIOS:
        try:
            result = scenario(sw, out_dir)
            results.append(result)
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001 - 回归脚本需汇总全部失败
            failed = True
            results.append({"scenario": name, "error": str(exc),
                            "traceback": traceback.format_exc(limit=4)})
            print(f"[FAIL] {name}: {exc}")
        try:
            sw.CloseDoc(f"{name}.SLDPRT")
        except Exception:
            pass

    summary_path = out_dir / "errorcheck_regression_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    print(f"汇总: {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
