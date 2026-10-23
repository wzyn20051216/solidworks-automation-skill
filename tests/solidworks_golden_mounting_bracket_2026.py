"""@brief P0-1 真机验收；显式运行，普通 pytest 不启动 CAD，无替代后端。

@details 每轮独占新目录、新 SolidWorks 2026 进程；未知证据与人工复核均阻止完成。
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import gc
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from evals.runner import load_golden_workflows
from scripts.core.execution import execute_with_core
from apps.desktop.cad_workbench.artifact_ledger import write_artifact_ledger, sha256_file
from golden_workflow_support import (CASE_REGISTRY, evidence_paths, safe_output_path, load_runtime_config,
                                     diagnose_runtime, resolve_material_database, process_created_at, validate_core_trace, valid_process_identity)

VIEWS = ("isometric", "front", "top", "right")
MANUAL_REVIEW_BLOCK = "EXPECTED_MANUAL_REVIEW_REQUIRED"
REVIEW_CHECKS = ("rebuild_succeeded", "model_available", "previews_created", "previews_not_blank",
                 "expected_outputs_exist", "feature_summary_available", "geometry_measurements_available",
                 "geometry_measurements_error_free", "feature_errors_absent")


def write_json(path, payload):
    """@brief 写入本轮目录内的 JSON 证据。"""
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_case():
    """@brief 复用 deterministic runner 的定义加载器，不执行其 mock 场景。"""
    workflows = load_golden_workflows()["workflows"]
    workflow = next(item for item in workflows if item["id"] == "mounting_bracket")
    spec = workflow["real_acceptance_2026"]
    if spec["size_mm"] != [120, 80, 10] or spec["hole_diameter_mm"] != 7:
        raise ValueError("P0-1 定义与指定验收尺寸不一致")
    if sorted(spec["hole_centers_mm"]) != [[-48, -28], [-48, 28], [48, -28], [48, 28]] or spec["material"] != "6061-T6":
        raise ValueError("P0-1 孔位或材料定义不一致")
    return workflow, spec


def expected_volume(spec):
    """@brief 按板体积减去四个圆柱孔计算解析体积，单位 mm³。"""
    x, y, z = spec["size_mm"]
    return x * y * z - len(spec["hole_centers_mm"]) * math.pi * (spec["hole_diameter_mm"] / 2) ** 2 * z


def close_enough(actual, expected, tolerance):
    """@brief 缺失、非有限或超差数据不能通过。"""
    return isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - expected) <= tolerance


def step_boundary_groups(snapshot):
    """@brief 按同轴圆柱面面积与圆弧真实长度归并 STEP 接缝；不改写原始测量。

    @details SW 的 STEP 导入可把一个圆柱壁/圆边拆成两半；必须证明合计完整圆周。
    """
    groups = {}
    for face in snapshot["geometry"].get("cylindrical_faces", []):
        if not face["internal"]:
            continue
        key = tuple(round(v, 5) for v in [face["diameter_mm"], *face["origin_mm"][:2], *map(abs, face["axis"])])
        hole = groups.setdefault(key, {"diameter_mm": face["diameter_mm"], "position_mm": face["origin_mm"],
                                       "axis": face["axis"], "area_mm2": 0.0})
        hole["area_mm2"] += face["area_mm2"]
    for hole in groups.values():
        hole["axial_length_mm"] = hole["area_mm2"] / (math.pi * hole["diameter_mm"])
    circles = {}
    for edge in snapshot["circular_edges"]:
        key = tuple(round(v, 5) for v in edge[:4])
        circle = circles.setdefault(key, [*edge[:4], True, 0.0])
        circle[4] &= edge[4]
        circle[5] += edge[5]
    return list(groups.values()), list(circles.values())


def validate_snapshot(snapshot, spec, native=True):
    """@brief 独立核对 B-Rep、解析质量与原生特征证据；不依赖创建 API success。"""
    tol = spec["length_tolerance_mm"]
    checks = {"single_solid": snapshot["body_count"] == 1,
              "measurements_error_free": not snapshot["geometry"].get("errors") and not snapshot["mass"].get("errors"),
              "volume": close_enough(snapshot["mass"].get("volume_mm3"), expected_volume(spec), spec["volume_tolerance_mm3"])}
    envelope = snapshot["geometry"].get("envelope_mm") or {}
    checks["dimensions"] = all(close_enough(envelope.get(k), v, tol) for k, v in zip(("length", "width", "height"), spec["size_mm"]))
    # 六个实际平面的法向坐标证明板体边界；GetPartBox 只是额外交叉检查。
    targets = [(0, -60), (0, 60), (1, -40), (1, 40), (2, 0), (2, 10)]
    planes = snapshot["planes"]
    checks["brep_plate_boundaries"] = len(planes) == 6 and all(
        any(p["axis"] == axis and close_enough(p["coordinate_mm"], value, tol) for p in planes) for axis, value in targets)
    holes = snapshot["geometry"].get("holes") or []
    circular_edges = snapshot["circular_edges"]
    if not native:
        holes, circular_edges = step_boundary_groups(snapshot)
    checks["four_holes"] = len(holes) == 4
    matched = set()
    for i, (x, y) in enumerate(spec["hole_centers_mm"]):
        candidates = [(j, h) for j, h in enumerate(holes) if j not in matched
                      and close_enough(h.get("diameter_mm"), 7, tol)
                      and len(h.get("position_mm", [])) == 3
                      and close_enough(h["position_mm"][0], x, tol) and close_enough(h["position_mm"][1], y, tol)
                      and len(h.get("axis", [])) == 3 and close_enough(abs(h["axis"][2]), 1, 1e-6)
                      and close_enough(h.get("axial_length_mm"), 10, tol)]
        checks[f"hole_{i + 1}_diameter_position_axis_depth"] = len(candidates) == 1
        if len(candidates) == 1:
            matched.add(candidates[0][0])
        # 同一孔的两个圆边须分别邻接 z=0 和 z=10 板面，排除盲孔、内部空腔。
        edges = [e for e in circular_edges if close_enough(e[0], x, tol)
                 and close_enough(e[1], y, tol) and close_enough(e[3], 3.5, tol)]
        checks[f"hole_{i + 1}_through_boundaries"] = len(edges) == 2 and all(
            any(close_enough(e[2], z, tol) and e[4] for e in edges) for z in (0, 10))
        checks[f"hole_{i + 1}_full_circumferences"] = len(edges) == 2 and all(close_enough(e[5], math.pi * 7, tol) for e in edges)
    checks["eight_circular_boundaries"] = len(circular_edges) == 8
    if native:
        summary = snapshot["features"]
        checks["healthy_features"] = not any(summary.get(k) for k in ("feature_error", "faulty_features", "warning_features", "unknown_feature_health"))
        types = [f.get("underlying_type", f["type"]) for f in summary["features"]]
        checks["boss_and_cut"] = sum(t in {"Boss", "Extrusion"} for t in types) == 1 and types.count("Cut") == 1
        quality = snapshot["sketch_quality"]
        checks["fully_defined_editable_sketches"] = quality.get("status") == "pass" and len(quality.get("sketches", [])) == 2
        checks["material_readback"] = snapshot["material"]["name"] == spec.get("material_library_entry", "6061-T6 (SS)") and bool(snapshot["material"]["database"])
        checks["material_density"] = close_enough(snapshot["mass"].get("density_kg_m3"), 2700, 1)
        checks["thickness_parameter"] = close_enough(snapshot.get("thickness_mm"), 10, tol)
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
            "failed_checks": [k for k, v in checks.items() if not v]}


def workflow_checks(report, spec):
    """@brief 从实际测量重新判定执行事实，不把缓存 PASS 或 BLOCKED 字样当作通过。"""
    connection, cleanup = report.get("connection", {}), report.get("cleanup", {})
    pid = connection.get("process_id")
    checks = {"no_execution_error": not report.get("error"),
              "runtime_diagnostics": report.get("runtime_diagnostics", {}).get("status") == "pass"
              and report.get("runtime_diagnostics", {}).get("blocked_reasons") == []
              and all(report.get("runtime_diagnostics", {}).get("checks", {}).get(k) is True
                      for k in ("windows", "python_64_bit", "pythoncom", "win32com", "comtypes")),
              "real_2026_owned_instance": report.get("backend") == "real-solidworks-2026" and report.get("mock") is False
              and report.get("version", {}).get("year") == 2026 and connection.get("actual_version") == 2026
              and connection.get("requested_version") == 2026 and connection.get("started_by_cad_studio") is True
              and valid_process_identity(pid, report.get("process_created_at")) and report.get("processes_before") == {},
              "safe_cleanup": cleanup.get("status") == "pass" and cleanup.get("owned_pid") == pid
              and cleanup.get("remaining_documents") == 0 and cleanup.get("exit_requested") is True
              and cleanup.get("processes_after") == {} and cleanup.get("errors") == []}
    for stage in ("built", "reopened", "step_reopened"):
        try:
            snapshot = report[stage]
            validation = validate_snapshot(snapshot, spec, native=stage != "step_reopened")
            checks[stage] = validation["status"] == "pass" and snapshot.get("validation") == validation
        except (KeyError, TypeError, ValueError, ArithmeticError):
            checks[stage] = False
    for name in ("base_constraints", "hole_constraints"):
        quality = report.get(name, {})
        checks[name] = (quality.get("status") == "pass" and quality.get("constrained_status") == 3
                        and quality.get("fix_count") == 0 and (quality.get("dimension_count") or 0) > 0 and quality.get("errors") == [])
    review = report.get("review", {})
    evaluation = review.get("evaluation", {})
    checks["review_rules"] = (evaluation.get("status") == "pass" and evaluation.get("issues") == []
                              and all(review.get("checks", {}).get(k) is True for k in REVIEW_CHECKS))
    previews = review.get("previews", [])
    expected = {str(Path(report.get("output_dir", "")) / "review" / f"mounting_bracket_{v}.bmp") for v in VIEWS}
    checks["four_previews"] = len(previews) == 4 and {p.get("path") for p in previews} == expected and all(
        p.get("exists") is True and p.get("likely_blank") is False and p.get("width", 0) >= 640
        and p.get("height", 0) >= 480 and p.get("size_bytes", 0) >= 10000 for p in previews)
    checks["known_manual_requirement"] = type(evaluation.get("manual_review_required")) is bool
    return checks


def adapt_terminal(report, output, spec):
    """@brief 仅适配已完成的 CAD 流程终态；Core 没有调度实际建模步骤。

    @details 保留原始 Review；只把规则状态与人工标记翻译为 Verification 的正式输入。
    """
    checks = workflow_checks(report, spec)
    evaluation = report.get("review", {}).get("evaluation", {})
    succeeded = all(value for name, value in checks.items() if name != "review_rules")
    raw = {"success": succeeded, "status": "ok" if succeeded else "blocked" if "BLOCKED:" in report.get("error", "") else "failed",
           "manual_review_required": evaluation.get("manual_review_required", True),
           "message": "真实 CAD 流程结束后的终态适配"}
    if raw["status"] == "blocked":
        # Core 会将 success=False 归为明确工具失败；前置未执行只传 BLOCKED，不伪称成功或失败。
        raw.pop("success")
    # evaluation.issues 是通用审查说明，而非 Verification 的带 status 检查；原文留在 report。
    reviewer = {"status": evaluation.get("status"), "manual_review_required": evaluation.get("manual_review_required", True),
                "reason": evaluation.get("manual_review_reason"),
                "evidence": [{"path": report.get("review_path"), "scope": "original_review"}]}
    assessment = execute_with_core(handler=lambda _: raw, run_id=report.get("trace_run_id", output.name), tool_name="golden_terminal_adapter",
                                   capability_id="part_and_features", requires_review=True, reviewer_result=reviewer,
                                   trace_dir=output / "trace")
    core = assessment.to_dict()
    report.update(execution_core=core, core_scope="terminal_adaptation_only", workflow_checks=checks,
                  task_status=core["status"], status=core["status"], manual_review_required=evaluation.get("manual_review_required"))
    if core["status"] == "blocked" and all(checks.values()) and evaluation.get("manual_review_required") is True:
        report["blocking_reasons"] = [MANUAL_REVIEW_BLOCK]
    else:
        report["blocking_reasons"] = [name for name, value in checks.items() if not value]
        if core["status"] == "blocked" and not report["blocking_reasons"]:
            report["blocking_reasons"] = ["UNEXPECTED_CORE_BLOCK"]


def acceptance_result(report, spec, expected_terminal, integrity):
    """@brief 测试验收与业务终态独立；只有明确、唯一的预期人工阻塞可以通过。"""
    checks = workflow_checks(report, spec)
    core = report.get("execution_core", {})
    verification = core.get("verification") or {}
    task = report.get("task_status")
    checks.update(evidence_integrity=integrity.get("status") == "pass" and integrity.get("errors") == [],
                  terminal_matches=task == expected_terminal and report.get("status") == task and core.get("status") == task,
                  core_execution_succeeded=core.get("execution", {}).get("success") is True and core.get("exception") is None,
                  core_scope=report.get("core_scope") == "terminal_adaptation_only",
                  core_verified=core.get("requires_review") is True and verification.get("status") == "PASS"
                  and verification.get("error_code") is None)
    if expected_terminal == "blocked":
        checks["only_expected_manual_block"] = (report.get("manual_review_required") is True
            and report.get("review", {}).get("evaluation", {}).get("manual_review_required") is True
            and verification.get("manual_review_required") is True and report.get("blocking_reasons") == [MANUAL_REVIEW_BLOCK]
            and (core.get("recovery") or {}).get("decision") == "user_action_required"
            and core.get("step", {}).get("status") == "blocked")
    else:
        checks["no_manual_review_needed"] = (report.get("manual_review_required") is False
            and verification.get("manual_review_required") is False and report.get("blocking_reasons") == []
            and core.get("recovery") is None)
    return {"acceptance_status": "passed" if all(checks.values()) else "failed", "expected_terminal": expected_terminal,
            "checks": checks, "failed_checks": [name for name, value in checks.items() if not value]}


def required_evidence(run_id):
    """@brief 固定必需交付物集合，不能按当前碰巧存在的文件减少验收要求。"""
    return evidence_paths("mounting_bracket", run_id)


def inspect_evidence(output, report):
    """@brief 回读文件、哈希和 Ledger，校验覆盖集合、来源及报告关联；未知即失败。"""
    errors = []
    try:
        safe_output_path(output, output)
        output = output.resolve()
        load = lambda p: json.loads(safe_output_path(output, p).read_text(encoding="utf-8"))
        manifest = load(output / "sha256.json")
        entries = {}
        for entry in manifest:
            path = output / entry["path"]
            if Path(entry["path"]).is_absolute() or not path.resolve().is_relative_to(output):
                raise ValueError("HASH_PATH_OUTSIDE_RUN")
            safe_output_path(output, path)
            key = path.relative_to(output).as_posix()
            if key in entries or not path.is_file() or path.stat().st_size <= 0:
                raise ValueError(f"MISSING_DUPLICATE_OR_EMPTY_ARTIFACT: {key}")
            if entry["size_bytes"] != path.stat().st_size or entry["sha256"] != sha256_file(path):
                raise ValueError(f"ARTIFACT_HASH_MISMATCH: {key}")
            entries[key] = entry
        actual = set()
        for path in output.rglob("*"):
            safe_output_path(output, path)
            if path.is_file() and path != output / "sha256.json":
                actual.add(path.relative_to(output).as_posix())
        ledger_key = f"ledgers/{output.name}.ledger.json"
        trace_run_id = report.get("trace_run_id", output.name)
        if set(entries) != actual or not (required_evidence(trace_run_id) | {ledger_key}).issubset(entries):
            raise ValueError("EVIDENCE_COVERAGE_INCOMPLETE")
        if load(output / "report.json") != report:
            raise ValueError("REPORT_CONTENT_MISMATCH")
        for name in ("runtime_config", "runtime_diagnostics"):
            if load(output / f"{name}.json") != report.get(name):
                raise ValueError("RUNTIME_DIAGNOSTIC_MISMATCH")
        for stage in ("built", "reopened", "step_reopened"):
            if load(output / f"{stage}.json") != report.get(stage):
                raise ValueError(f"SNAPSHOT_CONTENT_MISMATCH: {stage}")
        disk_review = load(output / "review/mounting_bracket_review_report.json")
        if disk_review != report.get("review"):
            raise ValueError("REVIEW_CONTENT_MISMATCH")
        ledger = load(output / ledger_key)
        if (ledger["executor"] != "solidworks-com-pywin32" or ledger["status"] != report["task_status"]
                or ledger["runId"] != trace_run_id or ledger["jobId"] != output.name
                or ledger["verification"] != [report["execution_core"]]):
            raise ValueError("LEDGER_PROVENANCE_MISMATCH")
        ledger_paths = set()
        for entry in ledger["artifacts"]:
            path = Path(entry["path"])
            key = path.resolve().relative_to(output).as_posix()
            if key in ledger_paths or key not in entries or not entry["exists"] or entry["isDirectory"] or entry.get("producedThisRun") is not True:
                raise ValueError("LEDGER_ARTIFACT_INVALID")
            if entry["sha256"] != entries[key]["sha256"] or entry["sizeBytes"] != entries[key]["size_bytes"]:
                raise ValueError("LEDGER_HASH_MISMATCH")
            ledger_paths.add(key)
        if ledger_paths != set(entries) - {ledger_key}:
            raise ValueError("LEDGER_COVERAGE_INCOMPLETE")
        # 追踪文件来自真实 Core 适配，须有验证及准确终态，不能把工具失败冒充人工阻塞。
        events = [json.loads(line) for line in (output / "trace" / "events" / f"{trace_run_id}.jsonl").read_text(encoding="utf-8").splitlines()]
        validate_core_trace(events, report, trace_run_id)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        errors.append(f"{type(error).__name__}: {error}")
    return {"status": "pass" if not errors else "fail", "errors": errors}


def write_evidence_bundle(output, report):
    """@brief 封存本轮报告、Ledger 与清单；排除 Ledger/清单自引用。"""
    for path in output.rglob("*"):
        safe_output_path(output, path)
    safe_output_path(output, output / "report.json")
    safe_output_path(output, output / "sha256.json")
    ledger_path = output / "ledgers" / f"{output.name}.ledger.json"
    safe_output_path(output, ledger_path)
    write_json(output / "report.json", report)
    files = [p for p in output.rglob("*") if p.is_file() and p not in {output / "sha256.json", ledger_path}]
    write_artifact_ledger(output, {"id": output.name, "runId": report.get("trace_run_id", output.name), "executor": "solidworks-com-pywin32",
                                  "status": report["task_status"], "cwd": str(output)},
                          {"artifacts": [{"kind": p.suffix.lstrip("."), "path": str(p)} for p in files],
                           "artifactBaseline": {}, "verification": [report["execution_core"]]})
    files.append(ledger_path)
    write_json(output / "sha256.json", [{"path": p.relative_to(output).as_posix(), "size_bytes": p.stat().st_size,
                                        "sha256": sha256_file(p)} for p in sorted(files)])
    return inspect_evidence(output, report)


def snapshot_model(model, boss_name=None):
    """@brief 调用既有测量/草图/特征接口，补采边界拓扑与材料库回读。"""
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import get_com_member as member
    from scripts.sw_measure import collect_mass_properties
    from scripts.sw_review import collect_geometry_measurements, collect_model_summary
    from scripts.sw_sketch_quality import inspect_model_sketches
    bodies = list(member(model, "GetBodies2", 0, False) or [])
    planes, edges = [], []
    for body in bodies:
        for face in member(body, "GetFaces"):
            surface = member(face, "GetSurface")
            if member(surface, "IsPlane"):
                p = list(member(surface, "PlaneParams"))
                axis = max(range(3), key=lambda a: abs(p[a]))
                if close_enough(abs(p[axis]), 1, 1e-6):
                    planes.append({"axis": axis, "coordinate_mm": p[axis + 3] * 1000})
        for edge in member(body, "GetEdges"):
            curve = member(edge, "GetCurve")
            if not member(curve, "IsCircle"):
                continue
            p = list(member(curve, "CircleParams"))
            adjacent = list(member(edge, "GetTwoAdjacentFaces2") or [])
            at_plate = False
            for face in adjacent:
                surface = member(face, "GetSurface")
                if member(surface, "IsPlane"):
                    plane = list(member(surface, "PlaneParams"))
                    at_plate |= close_enough(abs(plane[2]), 1, 1e-6) and close_enough(plane[5] * 1000, p[2] * 1000, .01)
            trim = member(edge, "GetCurveParams3")
            length = float(member(curve, "GetLength3", member(trim, "UMinValue"), member(trim, "UMaxValue"))) * 1000
            edges.append([p[0] * 1000, p[1] * 1000, p[2] * 1000, p[6] * 1000, at_plate, length])
    result = {"body_count": len(bodies), "planes": planes, "circular_edges": edges,
              "geometry": collect_geometry_measurements(model), "mass": collect_mass_properties(model)}
    if boss_name is not None:
        database = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        name = member(model, "GetMaterialPropertyName2", "", database)
        result.update(features=collect_model_summary(model), sketch_quality=inspect_model_sketches(model),
                      material={"name": name, "database": database.value},
                      thickness_mm=float(member(member(model, "Parameter", "D1@" + boss_name), "SystemValue")) * 1000)
        # 官方规定 Instant3D 的 ICE 必须通过 GetTypeName 回读底层特征类型。
        feature = member(model, "FirstFeature")
        by_name = {item["name"]: item for item in result["features"]["features"]}
        while feature is not None:
            name = str(member(feature, "Name"))
            if by_name[name]["type"] == "ICE":
                by_name[name]["underlying_type"] = str(member(feature, "GetTypeName"))
            feature = member(feature, "GetNextFeature")
    return result


def run_cad(output, report, spec):
    """@brief 仅在进程状态可证明为空时启动真机；清理只依据实际文档所有权。"""
    import pythoncom
    from scripts.sw_connect import (connect_solidworks, get_com_member as member, get_sw_version, find_template,
                                    new_document, save_document, open_document, close_owned_solidworks)
    from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, extrude_boss, extrude_cut, clear_sketch_selection_cache
    from scripts.sw_sketch_quality import fully_define_sketch
    from scripts.sw_export import export_to_step
    from scripts.sw_review import run_review
    from scripts.sw_process import solidworks_processes
    prior = solidworks_processes()
    report["processes_before"] = prior
    if prior is None or prior:
        raise RuntimeError("BLOCKED: SolidWorks 进程状态不为空或不可知；保留已有进程及文档")
    sw, model, pid, owned = None, None, None, False
    owned_titles = set()
    runtime = report["runtime_config"]
    pythoncom.CoInitialize()
    try:
        sw, _, connection = connect_solidworks(version=CASE_REGISTRY["mounting_bracket"]["year"], visible=True,
                                               wait_seconds=runtime["connect_timeout_seconds"], return_metadata=True)
        report.update(connection=connection, version=get_sw_version(sw))
        pid = int(member(sw, "GetProcessID"))
        owned = connection["started_by_cad_studio"] is True and pid not in prior
        report["process_created_at"] = process_created_at(pid)
        if not owned or report["version"]["year"] != 2026 or list(member(sw, "GetDocuments") or []):
            raise RuntimeError("BLOCKED: 无法证明新建空白 SolidWorks 2026 实例的所有权")
        template = runtime["part_template"] or find_template(sw, "part")
        if not template or not Path(template).is_file():
            raise RuntimeError("BLOCKED: 未找到可用零件模板")
        report["resolved_part_template"] = {"path": str(template), "sha256": sha256_file(Path(template))}
        model = new_document(sw, "part", template_path=str(template))
        owned_titles.add(str(member(model, "GetTitle")))
        with sketch(model, "Front Plane") as ref:
            sketch_rectangle(model, 0, 0, spec["size_mm"][0] / 1000, spec["size_mm"][1] / 1000)
            report["base_constraints"] = fully_define_sketch(model)
        boss = extrude_boss(model, ref, .010, direction=False)
        if boss is None:
            raise RuntimeError("母体拉伸失败")
        boss_name = str(member(boss, "Name"))
        with sketch(model, "Front Plane") as ref:
            for x, y in spec["hole_centers_mm"]:
                if sketch_circle(model, x / 1000, y / 1000, spec["hole_diameter_mm"] / 2000) is None:
                    raise RuntimeError("孔草图创建失败")
            report["hole_constraints"] = fully_define_sketch(model)
        if extrude_cut(model, ref, 0, direction=True) is None:
            raise RuntimeError("贯穿孔切除失败")
        # 使用已安装的原厂材料库，禁止把自定义字符串当作实际材料分配。
        database = resolve_material_database(runtime, report["doctor"]["installations"]["solidworks"]["executable"])
        # 原厂库使用带 (SS) 后缀的精确条目名；不创建或篡改材料库。
        import xml.etree.ElementTree as ET
        entry_name = spec.get("material_library_entry", "6061-T6 (SS)")
        material = next((item for item in ET.parse(database).iter("material") if item.get("name") == entry_name), None)
        if material is None:
            raise RuntimeError("BLOCKED: 原厂库未提供 6061-T6 (SS)")
        report["material_library_entry"] = {"requested": spec["material"], "name": material.get("name"), "matid": material.get("matid")}
        member(model, "SetMaterialPropertyName2", "", str(database), material.get("name"))
        report["material_database_sha256"] = sha256_file(database)
        report["resolved_material_database"] = str(database)
        for stage in ("built", "reopened"):
            if not member(model, "ForceRebuild3", False):
                raise RuntimeError(f"{stage} 重建失败")
            evidence = snapshot_model(model, boss_name)
            evidence["validation"] = validate_snapshot(evidence, spec)
            report[stage] = evidence
            print(f"{stage}: {evidence['validation']['status']}; volume={evidence['mass']['volume_mm3']}", flush=True)
            write_json(output / f"{stage}.json", evidence)
            if evidence["validation"]["status"] != "pass":
                raise RuntimeError(f"{stage} 几何验收失败: {evidence['validation']['failed_checks']}")
            if stage == "built":
                native = output / "mounting_bracket.SLDPRT"
                if native.exists() or not save_document(model, str(native)) or native.stat().st_size < 1024:
                    raise RuntimeError("原生保存失败或路径已经存在")
                clear_sketch_selection_cache(model)
                sw.CloseDoc(str(member(model, "GetTitle")))
                if list(member(sw, "GetDocuments") or []):
                    raise RuntimeError("关闭后仍有文档，未执行重开")
                model = open_document(sw, str(native), silent=True, raise_on_error=True)
                owned_titles.add(str(member(model, "GetTitle")))
        step = output / "mounting_bracket.step"
        if step.exists() or not export_to_step(model, str(step)) or step.stat().st_size < 1024:
            raise RuntimeError("STEP 导出失败")
        if not step.read_text(encoding="ascii", errors="replace").lstrip().startswith("ISO-10303-21;"):
            raise RuntimeError("STEP 文件头无效")
        report["review"], report["review_path"] = run_review(model, output / "review", basename="mounting_bracket",
                                                            views=VIEWS, expected_outputs=[str(native), str(step)])
        # 在同一个真实 SolidWorks 内重新导入 STEP，检查实际交付几何。
        clear_sketch_selection_cache(model)
        sw.CloseDoc(str(member(model, "GetTitle")))
        model = open_document(sw, str(step), silent=True, raise_on_error=True)
        owned_titles.add(str(member(model, "GetTitle")))
        evidence = snapshot_model(model)
        evidence["validation"] = validate_snapshot(evidence, spec, native=False)
        report["step_reopened"] = evidence
        write_json(output / "step_reopened.json", evidence)
        if evidence["validation"]["status"] != "pass":
            raise RuntimeError(f"STEP 重开几何不符: {evidence['validation']['failed_checks']}")
    finally:
        cleanup = {"status": "failed", "owned_pid": pid, "errors": []}
        report["cleanup"] = cleanup
        try:
            if sw is not None and owned:
                for doc in list(member(sw, "GetDocuments") or []):
                    path = str(member(doc, "GetPathName") or "")
                    title = str(member(doc, "GetTitle"))
                    if (path and Path(path).resolve().is_relative_to(output)) or (not path and title in owned_titles):
                        clear_sketch_selection_cache(doc)
                        sw.CloseDoc(title)
                remaining = list(member(sw, "GetDocuments") or [])
                cleanup["remaining_documents"] = len(remaining)
                if not remaining:
                    cleanup["exit_requested"] = close_owned_solidworks(sw, True, expected_pid=pid)
        except Exception:
            cleanup["errors"].append(traceback.format_exc())
        model = sw = None
        clear_sketch_selection_cache()
        gc.collect()
        pythoncom.CoUninitialize()
        deadline = time.monotonic() + runtime["cleanup_timeout_seconds"]
        while pid and time.monotonic() < deadline:
            current = solidworks_processes()
            if current is None or pid not in current:
                break
            time.sleep(.25)
        cleanup["processes_after"] = solidworks_processes()
        if cleanup.get("remaining_documents") == 0 and cleanup.get("exit_requested") and cleanup["processes_after"] == prior and not cleanup["errors"]:
            cleanup["status"] = "pass"


def finalize_report(output, report, spec, expected_terminal):
    """@brief 核验后封存双状态报告；证据写入异常只允许验收失败。"""
    report["ledger_path"] = str(output / "ledgers" / f"{output.name}.ledger.json")
    try:
        integrity = write_evidence_bundle(output, report)
        result = acceptance_result(report, spec, expected_terminal, integrity)
        report.update(evidence_integrity=integrity, acceptance=result, acceptance_status=result["acceptance_status"])
        final_integrity = write_evidence_bundle(output, report)
        if final_integrity["status"] != "pass":
            raise RuntimeError(str(final_integrity))
    except Exception:
        report.update(acceptance_status="failed", evidence_integrity={"status": "fail", "errors": [traceback.format_exc()]})
        if "acceptance" in report:
            report["acceptance"]["acceptance_status"] = "failed"
        # report.json 若被链接替换，错误处理也不能覆盖外部文件。
        try:
            write_json(safe_output_path(output, output / "report.json"), report)
        except ValueError:
            write_json(safe_output_path(output, output / "finalization_error.json"), report)
    return report


def run_once(output, expected_terminal="completed", runtime_config=None):
    """@brief 保存所有失败、日志、Execution Core、Artifact Ledger 与文件 SHA-256。"""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workflow, spec = load_case()
    report = {"schema_version": "1.2", "backend": "real-solidworks-2026", "mock": False,
              "status": "failed", "task_status": "failed", "acceptance_status": "failed",
              "expected_terminal": expected_terminal, "workflow": workflow, "expected_volume_mm3": expected_volume(spec),
              "trace_run_id": "golden_" + uuid.uuid4().hex,
              "generated_at": datetime.now(timezone.utc).isoformat(), "output_dir": str(output)}
    with (output / "run.log").open("w", encoding="utf-8", buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        try:
            report["source_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            try:
                report["runtime_config"] = load_runtime_config(runtime_config)
            except (OSError, ValueError, TypeError) as error:
                raise RuntimeError(f"BLOCKED: 运行配置不可用: {error}") from error
            report["runtime_diagnostics"] = diagnose_runtime(report["runtime_config"])
            if report["runtime_diagnostics"]["status"] != "pass":
                raise RuntimeError("BLOCKED: 运行时诊断不通过")
            for command, name in ((["scripts/sw_preflight.py"], "preflight"), (["scripts/cad_studio.py", "doctor"], "doctor")):
                result = subprocess.run([sys.executable, "-X", "utf8", *command], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError(f"BLOCKED: {name} 失败: {result.returncode}")
                if name == "doctor":
                    report["doctor"] = json.loads(result.stdout)
            run_cad(output, report, spec)
        except Exception:
            report["error"] = traceback.format_exc()
            print(report["error"], flush=True)
        report.setdefault("runtime_config", {})
        report.setdefault("runtime_diagnostics", {"status": "blocked", "blocked_reasons": [report.get("error", "unknown")]})
        write_json(output / "runtime_config.json", report["runtime_config"])
        write_json(output / "runtime_diagnostics.json", report["runtime_diagnostics"])
        adapt_terminal(report, output, spec)
        print(json.dumps({"task_status": report["task_status"], "core_scope": report["core_scope"],
                          "blocking_reasons": report["blocking_reasons"], "cleanup": report.get("cleanup")}, ensure_ascii=False), flush=True)
    finalize_report(output, report, spec, expected_terminal)
    print(f"{output.name}: acceptance_status={report['acceptance_status']}, task_status={report['task_status']} — {output / 'report.json'}", flush=True)
    return report


def summarize_runs(reports, spec, expected_terminal):
    """@brief 套件结束时再次读取全部证据；预期 BLOCKED 模式强制五个独立真机实例。"""
    rows, workflow = [], []
    for report in reports:
        integrity = inspect_evidence(Path(report["output_dir"]), report)
        result = acceptance_result(report, spec, expected_terminal, integrity)
        if report.get("acceptance_status") != result["acceptance_status"]:
            result["acceptance_status"] = "failed"
            result["failed_checks"].append("stored_acceptance_mismatch")
        checks = workflow_checks(report, spec)
        workflow.append(checks)
        rows.append({"task_status": report.get("task_status"), "acceptance_status": result["acceptance_status"],
                     "failed_checks": result["failed_checks"], "evidence_integrity": integrity,
                     "report": str(Path(report["output_dir"]) / "report.json")})
    pids = [report.get("connection", {}).get("process_id") for report in reports]
    identities = [(pid, report.get("process_created_at")) for pid, report in zip(pids, reports)]
    trace_ids = [report.get("execution_core", {}).get("run_id") for report in reports]
    suite_checks = {"runs_present": bool(reports), "all_runs_accepted": all(row["acceptance_status"] == "passed" for row in rows),
                    "independent_trace_runs": len(set(trace_ids)) == len(trace_ids),
                    "independent_processes": len(set(identities)) == len(identities) and all(type(pid) is int and pid > 0 for pid in pids),
                    "five_runs_for_expected_block": expected_terminal != "blocked" or len(reports) == 5}
    tasks = [row["task_status"] for row in rows]
    task = "failed" if any(t not in {"completed", "blocked"} for t in tasks) or not tasks else "blocked" if "blocked" in tasks else "completed"
    geometry_keys = ("real_2026_owned_instance", "built", "reopened", "step_reopened", "base_constraints", "hole_constraints")
    false_completions = sum((r.get("task_status") == "completed" or r.get("execution_core", {}).get("status") == "completed")
                            and (r.get("manual_review_required") is not False or not all(c.values())
                                 or row["evidence_integrity"]["status"] != "pass"
                                 or r.get("execution_core", {}).get("status") != r.get("task_status"))
                            for r, c, row in zip(reports, workflow, rows))
    return {"schema_version": "1.2", "backend": "real-solidworks-2026", "mock": False, "status": task, "task_status": task,
            "acceptance_status": "passed" if all(suite_checks.values()) else "failed", "expected_terminal": expected_terminal,
            "suite_checks": suite_checks, "runs": rows,
            "metrics": {"run_count": len(reports), "geometry_success_count": sum(all(c[k] for k in geometry_keys) for c in workflow),
                        "expected_gate_correct_count": sum(row["acceptance_status"] == "passed" for row in rows),
                        "task_completion_count": tasks.count("completed"),
                        "test_acceptance_count": sum(row["acceptance_status"] == "passed" for row in rows),
                        "false_completion_count": false_completions,
                        "cleanup_success_count": sum(c["safe_cleanup"] for c in workflow)}}


def main(argv=None):
    """@brief 默认严格完成；显式 blocked 模式仅验收五轮正确人工阻塞，不放宽业务门禁。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--expected-terminal", choices=("completed", "blocked"), default="completed")
    parser.add_argument("--runtime-config", type=Path, help="仅配置模板/材料库和有界超时的 JSON 文件")
    args = parser.parse_args(argv)
    if args.expected_terminal == "blocked" and args.runs != 5:
        parser.error("--expected-terminal blocked 必须结合 --runs 5")
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [run_once(args.output / f"run-{i:02d}", args.expected_terminal, args.runtime_config) for i in range(1, args.runs + 1)]
    summary = summarize_runs(reports, load_case()[1], args.expected_terminal)
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["acceptance_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
