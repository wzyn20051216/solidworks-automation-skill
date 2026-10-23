"""@brief 离线验收器契约测试；合成测量记录不代表真实 CAD 结果。"""
from copy import deepcopy
import math
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import solidworks_golden_mounting_bracket_2026 as golden
from solidworks_golden_mounting_bracket_2026 import expected_volume, load_case, validate_snapshot


def valid_measurements():
    """@brief 构造验收器输入夹具；不启动、模拟或声称已执行 SolidWorks。"""
    _, spec = load_case()
    holes = [{"diameter_mm": 7, "position_mm": [x, y, 0], "axis": [0, 0, 1], "axial_length_mm": 10}
             for x, y in spec["hole_centers_mm"]]
    return {"body_count": 1, "geometry": {"envelope_mm": {"length": 120, "width": 80, "height": 10}, "holes": holes},
            "mass": {"volume_mm3": expected_volume(spec), "density_kg_m3": 2700},
            "planes": [{"axis": a, "coordinate_mm": v} for a, v in ((0, -60), (0, 60), (1, -40), (1, 40), (2, 0), (2, 10))],
            "circular_edges": [[x, y, z, 3.5, True, math.pi * 7] for x, y in spec["hole_centers_mm"] for z in (0, 10)],
            "features": {"features": [{"type": "Boss"}, {"type": "Cut"}]},
            "sketch_quality": {"status": "pass", "sketches": [{}, {}]},
            "material": {"name": "6061-T6 (SS)", "database": "fixture.sldmat"}, "thickness_mm": 10}


def test_analytic_volume_and_definition():
    """@brief 固定 P0 规格及解析体积，防止误改夹具后假成功。"""
    workflow, spec = load_case()
    assert workflow["id"] == "mounting_bracket"
    assert math.isclose(expected_volume(spec), 94460.619599741, abs_tol=1e-6)
    assert validate_snapshot(valid_measurements(), spec)["status"] == "pass"


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(body_count=2),
    lambda s: s["mass"].update(volume_mm3=96000),
    lambda s: s["mass"].update(volume_mm3=float("nan")),
    lambda s: s["geometry"]["holes"][0].update(diameter_mm=6),
    lambda s: s["geometry"]["holes"][0].update(position_mm=[-47, -28, 0]),
    lambda s: s["geometry"]["holes"][0].update(axial_length_mm=9),
    lambda s: s["geometry"]["holes"][0].update(axis=[1, 0, 0]),
    lambda s: s["geometry"]["holes"].pop(),
    lambda s: s["geometry"].update(errors=["unknown"]),
    lambda s: s["geometry"]["envelope_mm"].update(length=119),
    lambda s: s["planes"].pop(),
    lambda s: s["circular_edges"].pop(),
    lambda s: s["circular_edges"][0].__setitem__(4, False),
    lambda s: s["sketch_quality"].update(status="review_required"),
    lambda s: s["features"].update(unknown_feature_health=[{"name": "unknown"}]),
    lambda s: s["features"].update(features=[{"type": "Imported"}]),
    lambda s: s["material"].update(name="6061"),
    lambda s: s["material"].update(database=""),
    lambda s: s["mass"].update(density_kg_m3=1000),
    lambda s: s.update(thickness_mm=9),
])
def test_geometric_or_unknown_evidence_never_passes(mutation):
    """@brief 孔位、孔径、盲孔、约束、未知状态等故障必须被验收拒绝。"""
    snapshot = valid_measurements()
    mutation(snapshot)
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "fail"


def complete_report(output, pid=12345, manual=True):
    """@brief 合成契约输入；这些记录不来自 CAD，绝不计入真机运行统计。"""
    quality = {"status": "pass", "constrained_status": 3, "fix_count": 0, "dimension_count": 2, "errors": []}
    report = {"backend": "real-solidworks-2026", "mock": False, "version": {"year": 2026},
              "runtime_config": {}, "runtime_diagnostics": {"status": "pass", "blocked_reasons": [],
              "checks": dict.fromkeys(("windows", "python_64_bit", "pythoncom", "win32com", "comtypes"), True)},
              "process_created_at": "2026-10-23T00:00:00+00:00",
              "connection": {"requested_version": 2026, "actual_version": 2026, "process_id": pid, "started_by_cad_studio": True},
              "processes_before": {}, "cleanup": {"status": "pass", "owned_pid": pid, "remaining_documents": 0,
                                                    "exit_requested": True, "processes_after": {}, "errors": []},
              "base_constraints": deepcopy(quality), "hole_constraints": deepcopy(quality), "output_dir": str(output),
              "acceptance_status": "failed", "review_path": str(output / "review" / "mounting_bracket_review_report.json"),
              "review": {"evaluation": {"status": "pass", "manual_review_required": manual, "issues": [], "manual_review_reason": "fixture"},
                         "checks": dict.fromkeys(golden.REVIEW_CHECKS, True),
                         "previews": [{"path": str(output / "review" / f"mounting_bracket_{v}.bmp"), "exists": True,
                                       "likely_blank": False, "width": 1600, "height": 1000, "size_bytes": 4800054} for v in golden.VIEWS]}}
    for stage in ("built", "reopened", "step_reopened"):
        snapshot = valid_measurements()
        snapshot["geometry"]["cylindrical_faces"] = [{"diameter_mm": 7, "origin_mm": [x, y, 0], "axis": [0, 0, 1],
                                                     "internal": True, "area_mm2": math.pi * 7 * 10} for x, y in load_case()[1]["hole_centers_mm"]]
        snapshot["validation"] = validate_snapshot(snapshot, load_case()[1], native=stage != "step_reopened")
        report[stage] = snapshot
    return report


@pytest.mark.parametrize("status,manual", [("pass", True), ("warn", False), ("fail", False), ("unknown", False), ("pass", None)])
def test_review_never_becomes_false_completion(tmp_path, status, manual):
    """@brief 即使建模成功，WARN/FAIL/未知/人工标志也必须阻断。"""
    report = complete_report(tmp_path)
    report["review"]["evaluation"].update(status=status, manual_review_required=manual)
    golden.adapt_terminal(report, tmp_path, load_case()[1])
    assert report["task_status"] != "completed"
    assert golden.acceptance_result(report, load_case()[1], "completed", {"status": "pass", "errors": []})["acceptance_status"] == "failed"


def test_cleanup_and_step_reopen_required(tmp_path):
    """@brief 清理失败、缺少交付重开和预览均不能完成。"""
    report = complete_report(tmp_path)
    for field in ("cleanup", "step_reopened"):
        changed = deepcopy(report)
        changed.pop(field)
        assert not all(golden.workflow_checks(changed, load_case()[1]).values())
    report["review"]["previews"].pop()
    assert golden.workflow_checks(report, load_case()[1])["four_previews"] is False


def test_instant3d_underlying_type_must_be_read():
    """@brief 接受已回读的 Cut 底层类型；未知 ICE 不可直接视为切除。"""
    snapshot = valid_measurements()
    snapshot["features"]["features"] = [{"type": "Extrusion"}, {"type": "ICE", "underlying_type": "Cut"}]
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "pass"
    snapshot["features"]["features"][1].pop("underlying_type")
    assert validate_snapshot(snapshot, load_case()[1])["status"] == "fail"


def test_step_split_faces_require_full_area_and_full_circles():
    """@brief STEP 半圆接缝不得被误判为槽；缺面或缺弧仍不能通过。"""
    snapshot = valid_measurements()
    snapshot["geometry"]["holes"] = []
    snapshot["geometry"]["cylindrical_faces"] = [
        {"diameter_mm": 7, "origin_mm": [x, y, 10], "axis": [0, 0, -1],
         "internal": True, "area_mm2": math.pi * 7 * 10 / 2}
        for x, y in load_case()[1]["hole_centers_mm"] for _ in range(2)]
    snapshot["circular_edges"] = [[*edge[:5], edge[5] / 2] for edge in snapshot["circular_edges"] for _ in range(2)]
    assert validate_snapshot(snapshot, load_case()[1], native=False)["status"] == "pass"
    broken = deepcopy(snapshot)
    broken["geometry"]["cylindrical_faces"].pop()
    assert validate_snapshot(broken, load_case()[1], native=False)["status"] == "fail"
    snapshot["circular_edges"].pop()
    assert validate_snapshot(snapshot, load_case()[1], native=False)["status"] == "fail"


def make_evidence(output, pid=12345, mutation=None, manual=True):
    """@brief 仅在 pytest 临时目录生成合成证据，用真实 Core/哈希/Ledger 测验收器。"""
    output.mkdir()
    report = complete_report(output, pid, manual)
    if mutation:
        mutation(report)
    golden.adapt_terminal(report, output, load_case()[1])
    # 占位字节只用于完整性故障注入，不是 CAD/图像，不在真机统计中出现。
    for name in golden.required_evidence(report.get("trace_run_id", output.name)):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"OFFLINE CONTRACT FIXTURE\n" * 100)
    for stage in ("built", "reopened", "step_reopened"):
        golden.write_json(output / f"{stage}.json", report[stage])
    for name in ("runtime_config", "runtime_diagnostics"):
        golden.write_json(output / f"{name}.json", report[name])
    golden.write_json(output / "review" / "mounting_bracket_review_report.json", report["review"])
    return golden.finalize_report(output, report, load_case()[1], "blocked")


def verdict(report, expected="blocked"):
    """@brief 每次读取磁盘证据，不能只相信已存的验收标志。"""
    return golden.acceptance_result(report, load_case()[1], expected,
                                    golden.inspect_evidence(Path(report["output_dir"]), report))


def test_expected_manual_block_is_accepted_but_never_completed(tmp_path):
    """@brief 真正执行 Verification 后得到预期阻塞，测试成功不改变业务状态。"""
    report = make_evidence(tmp_path / "run-01")
    assert report["acceptance_status"] == verdict(report)["acceptance_status"] == "passed"
    assert report["task_status"] == report["execution_core"]["status"] == "blocked"
    assert report["manual_review_required"] is True
    assert report["execution_core"]["execution"]["success"] is True
    assert report["execution_core"]["verification"]["status"] == "PASS"
    assert report["blocking_reasons"] == [golden.MANUAL_REVIEW_BLOCK]
    assert verdict(report, "completed")["acceptance_status"] == "failed"


@pytest.mark.parametrize("mutation", [
    lambda r: r["built"]["geometry"]["holes"][0].update(diameter_mm=6),
    lambda r: r["reopened"]["geometry"]["holes"][0].update(position_mm=[-47, -28, 0]),
    lambda r: r["step_reopened"]["geometry"]["cylindrical_faces"][0].update(diameter_mm=6),
    lambda r: r["reopened"]["material"].update(name="6061"),
    lambda r: r["hole_constraints"].update(constrained_status=2),
    lambda r: r["reopened"]["sketch_quality"].update(status="review_required"),
    lambda r: r["review"]["evaluation"].update(status="fail", issues=[{"code": "injected", "severity": "fail"}]),
    lambda r: r["review"]["evaluation"].update(status="warn"),
    lambda r: r["review"]["evaluation"].update(status="unknown"),
    lambda r: r["review"]["evaluation"].pop("manual_review_required"),
    lambda r: r["cleanup"].update(status="failed"),
    lambda r: r["cleanup"].update(remaining_documents=1),
    lambda r: r["cleanup"].update(processes_after={12345: 2026}),
    lambda r: r["connection"].update(started_by_cad_studio=False),
    lambda r: r.update(error="BLOCKED: 许可证缺失"),
    lambda r: r.update(mock=True),
])
def test_expected_block_does_not_hide_workflow_faults(tmp_path, mutation):
    """@brief 错误孔径/孔位、材料、约束、Review、清理和其它阻塞绝不能通过。"""
    report = make_evidence(tmp_path / "run-01", mutation=mutation)
    assert report["task_status"] != "completed"
    assert report["acceptance_status"] == verdict(report)["acceptance_status"] == "failed"


@pytest.mark.parametrize("artifact", ["mounting_bracket.SLDPRT", "mounting_bracket.step", "reopened.json",
                                      "review/mounting_bracket_front.bmp", "ledgers/run-01.ledger.json", "sha256.json"])
def test_missing_artifact_fails_even_if_task_is_expected_blocked(tmp_path, artifact):
    """@brief 删除任一必要产物后，旧 passed/blocked 标志不能让验收继续通过。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    (output / artifact).unlink()
    assert verdict(report)["acceptance_status"] == "failed"


def test_removed_artifact_cannot_be_hidden_by_rehashing(tmp_path):
    """@brief 即使重新生成清单和 Ledger，固定必需产物集合也不能被缩减。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    (output / "mounting_bracket.step").unlink()
    integrity = golden.write_evidence_bundle(output, report)
    assert integrity["status"] == "fail"
    assert verdict(report)["acceptance_status"] == "failed"


def test_hash_and_ledger_faults_are_rejected(tmp_path):
    """@brief 文件篡改及 Ledger 覆盖缺失都不能被 expected-terminal 放行。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    (output / "mounting_bracket.step").write_bytes(b"corrupted")
    assert verdict(report)["acceptance_status"] == "failed"
    golden.write_evidence_bundle(output, report)
    path = output / "ledgers" / "run-01.ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["artifacts"].pop()
    golden.write_json(path, ledger)
    # 更新清单仍无法掩盖 Ledger 缺失：不是只测清单是否与文件匹配。
    manifest_path = output / "sha256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest:
        if entry["path"] == "ledgers/run-01.ledger.json":
            entry.update(sha256=golden.sha256_file(path), size_bytes=path.stat().st_size)
    golden.write_json(manifest_path, manifest)
    assert verdict(report)["acceptance_status"] == "failed"


@pytest.mark.parametrize("mutation", [
    lambda r: r["blocking_reasons"].append("OTHER_BLOCK"),
    lambda r: r["execution_core"].update(status="completed"),
    lambda r: r["execution_core"]["verification"].update(status="BLOCKED"),
    lambda r: r["execution_core"]["execution"].update(success=False),
    lambda r: r.update(manual_review_required=False),
    lambda r: r.update(task_status="unknown"),
])
def test_terminal_or_manual_flag_mismatch_is_not_accepted(tmp_path, mutation):
    """@brief 注入非人工阻塞、错误 Core 终态或手动清除人工标记必须失败。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    mutation(report)
    golden.write_evidence_bundle(output, report)
    assert verdict(report)["acceptance_status"] == "failed"


@pytest.mark.parametrize("fault", [None, "diameter", "position", "missing", "review", "cleanup", "core"])
def test_cli_expected_block_exit_code_with_fault_injection(tmp_path, monkeypatch, fault):
    """@brief 离线 CLI 契约：五轮合成输入中任一故障必须非零；不会启动 CAD。"""
    mutations = {"diameter": lambda r: r["built"]["geometry"]["holes"][0].update(diameter_mm=6),
                 "position": lambda r: r["reopened"]["geometry"]["holes"][0].update(position_mm=[0, 0, 0]),
                 "review": lambda r: r["review"]["evaluation"].update(status="fail"),
                 "cleanup": lambda r: r["cleanup"].update(status="failed")}
    reports = [make_evidence(tmp_path / f"run-{i:02d}", pid=1000 + i, mutation=mutations.get(fault) if i == 1 else None)
               for i in range(1, 6)]
    if fault == "missing":
        (tmp_path / "run-01" / "mounting_bracket.step").unlink()
    if fault == "core":
        reports[0]["execution_core"]["status"] = "completed"
    iterator = iter(reports)
    monkeypatch.setattr(golden, "run_once", lambda *args: next(iterator))
    assert golden.main(["--output", str(tmp_path / "cli"), "--runs", "5", "--expected-terminal", "blocked"]) == (0 if fault is None else 1)
    if fault is None:
        strict = golden.summarize_runs(reports, load_case()[1], "completed")
        assert strict["task_status"] == "blocked" and strict["acceptance_status"] == "failed"
    if fault == "core":
        summary = json.loads((tmp_path / "cli" / "summary.json").read_text(encoding="utf-8"))
        assert summary["metrics"]["false_completion_count"] == 1


def test_cli_blocked_requires_five_runs_before_creating_output(tmp_path):
    """@brief 禁止用单轮或空运行满足五轮预期终态验收。"""
    with pytest.raises(SystemExit) as error:
        golden.main(["--output", str(tmp_path / "cli"), "--expected-terminal", "blocked"])
    assert error.value.code == 2 and not (tmp_path / "cli").exists()


def test_duplicate_pid_or_incomplete_suite_cannot_pass(tmp_path):
    """@brief 即使每轮单独通过，重复实例或不足五轮也不能整体通过。"""
    reports = [make_evidence(tmp_path / f"run-{i:02d}") for i in range(1, 6)]
    summary = golden.summarize_runs(reports, load_case()[1], "blocked")
    assert summary["acceptance_status"] == "failed" and summary["suite_checks"]["independent_processes"] is False
    assert golden.summarize_runs(reports[:1], load_case()[1], "blocked")["acceptance_status"] == "failed"


def test_cli_default_is_strict_completion(tmp_path, monkeypatch):
    """@brief 不传模式时仍要求 completed；正常人工 BLOCKED 也必须非零。"""
    report = make_evidence(tmp_path / "run-01")
    monkeypatch.setattr(golden, "run_once", lambda *args: report)
    assert golden.main(["--output", str(tmp_path / "cli")]) == 1
    summary = json.loads((tmp_path / "cli" / "summary.json").read_text(encoding="utf-8"))
    assert summary["expected_terminal"] == "completed" and summary["task_status"] == "blocked"


def test_evidence_write_failure_cannot_preserve_passed_acceptance(tmp_path, monkeypatch):
    """@brief 最后封存报告失败，必须撤销验收 passed，并保留错误。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    def fail_write(*args):
        """@brief 注入磁盘写入失败。"""
        raise OSError("injected disk error")
    monkeypatch.setattr(golden, "write_evidence_bundle", fail_write)
    golden.finalize_report(output, report, load_case()[1], "blocked")
    assert report["acceptance_status"] == "failed" and report["task_status"] == "blocked"
    assert "injected disk error" in report["evidence_integrity"]["errors"][0]
