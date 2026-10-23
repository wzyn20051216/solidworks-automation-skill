"""@brief P0-1.2 可复用入口、配置、隔离及 trace 的离线故障注入。"""
import json
import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_workflow_support as support
import solidworks_golden_workflow as entry
import solidworks_golden_mounting_bracket_2026 as golden
from test_solidworks_golden_mounting_bracket_2026 import make_evidence, load_case, verdict


@pytest.mark.parametrize("value", [{"version": 2025}, {"manual_review_required": False}, {"length_tolerance_mm": 100},
                                   {"connect_timeout_seconds": 999}, {"cleanup_timeout_seconds": True},
                                   {"material_database": "missing.sldmat"}, []])
def test_runtime_config_cannot_change_acceptance_or_hide_missing_files(tmp_path, value):
    """@brief 运行配置不允许改变用例、版本、容差或审批要求。"""
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        support.load_runtime_config(path)


def test_relative_config_paths_are_relative_to_config_file(tmp_path):
    """@brief 相对模板路径不依赖当前目录，缺省库路径从安装诊断推导。"""
    (tmp_path / "part.prtdot").write_bytes(b"offline fixture")
    config = tmp_path / "config.json"
    config.write_text('{"part_template":"part.prtdot","connect_timeout_seconds":15}', encoding="utf-8")
    assert support.load_runtime_config(config)["part_template"] == str(tmp_path / "part.prtdot")
    with pytest.raises(ValueError, match="BLOCKED"):
        support.resolve_material_database(support.load_runtime_config(), tmp_path / "SLDWORKS.exe")


def test_missing_dependency_is_explicitly_blocked(monkeypatch):
    """@brief 缺失 COM 依赖不会自动安装或替代 CAD。"""
    monkeypatch.setattr(support.importlib.util, "find_spec", lambda _: None)
    result = support.diagnose_runtime(support.load_runtime_config())
    assert result["status"] == "blocked" and "pythoncom" in result["blocked_reasons"]


def test_invalid_runtime_config_preserves_report_without_calling_cad(tmp_path, monkeypatch):
    """@brief 配置失败仍保留双状态报告和日志，且不得启动 CAD。"""
    monkeypatch.setattr(golden, "run_cad", lambda *args: pytest.fail("不应调用 CAD"))
    report = golden.run_once(tmp_path / "run-01", "blocked", tmp_path / "missing.json")
    assert report["task_status"] == "blocked" and report["acceptance_status"] == "failed"
    assert (tmp_path / "run-01" / "run.log").is_file()
    assert report["runtime_diagnostics"]["status"] == "blocked"


def test_registered_entry_rejects_unknown_code_and_preserves_default(monkeypatch):
    """@brief 不允许指定任意模块；选择用例不能放宽其默认完成模式。"""
    with pytest.raises(SystemExit) as error:
        entry.main(["--case", "../../untrusted.py"])
    assert error.value.code == 2
    observed = []
    monkeypatch.setattr(golden, "main", lambda argv: observed.extend(argv) or 1)
    assert entry.main(["--case", "mounting_bracket", "--output", "new-output"]) == 1
    assert observed == ["--output", "new-output"]


def test_rerun_never_overwrites_existing_output(tmp_path):
    """@brief 重复运行拒绝已有目录，保留原始文件且不会启动 CAD。"""
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "user-file.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        entry.main(["--case", "mounting_bracket", "--output", str(output)])
    assert sentinel.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("fault", ["reorder", "wrong_run", "wrong_step", "extra_terminal", "different_verification"])
def test_trace_faults_remain_failures_even_after_rehash(tmp_path, fault):
    """@brief 重算哈希不能把乱序、串轮、错误步骤或多重终态变成有效 trace。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    trace = output / "trace" / "events" / "run-01.jsonl"
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    if fault == "reorder":
        events[3], events[5] = events[5], events[3]
    elif fault == "wrong_run":
        events[3]["run_id"] = "other-run"
    elif fault == "wrong_step":
        events[3]["step_id"] = "other-step"
    elif fault == "extra_terminal":
        events.insert(3, {**events[-1], "type": "run.failed"})
    else:
        report["execution_core"]["step"]["verification"]["status"] = "BLOCKED"
    trace.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert golden.write_evidence_bundle(output, report)["status"] == "fail"
    assert verdict(report)["acceptance_status"] == "failed"


def test_hardlink_report_cannot_overwrite_external_file(tmp_path):
    """@brief 真正建立测试硬链接，证明正常封存和异常处理都保护外部文件。"""
    output = tmp_path / "run-01"
    report = make_evidence(output)
    external = tmp_path / "protected.txt"
    external.write_text("preserve", encoding="utf-8")
    (output / "report.json").unlink()
    os.link(external, output / "report.json")
    golden.finalize_report(output, report, load_case()[1], "blocked")
    assert external.read_text(encoding="utf-8") == "preserve"
    assert report["acceptance_status"] == "failed" and (output / "finalization_error.json").is_file()


def test_link_and_escape_paths_are_rejected_before_io(tmp_path, monkeypatch):
    """@brief 无需管理员创建符号链接权限，也可覆盖链接拒绝路径。"""
    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(ValueError):
        support.safe_output_path(root, tmp_path / "outside")
    candidate = root / "linked.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == candidate or original(p))
    with pytest.raises(ValueError, match="LINK_FORBIDDEN"):
        support.safe_output_path(root, candidate)


def test_pid_reuse_with_distinct_creation_times_is_independent(tmp_path):
    """@brief Windows 重用 PID 不能造成假失败，同一实例仍不允许冒充五轮。"""
    reports = [make_evidence(tmp_path / f"run-{i:02d}", pid=1000) for i in range(1, 6)]
    for i, report in enumerate(reports):
        report["process_created_at"] = f"2026-10-23T00:00:{i:02d}+00:00"
        golden.write_evidence_bundle(Path(report["output_dir"]), report)
    assert golden.summarize_runs(reports, load_case()[1], "blocked")["acceptance_status"] == "passed"
    assert not support.valid_process_identity(1000, "unknown")


def test_trace_from_another_suite_with_same_folder_name_is_rejected(tmp_path):
    """@brief 不同套件都叫 run-01 也不能互换 trace；实际入口使用随机唯一 ID。"""
    for name in ("suite_a", "suite_b"):
        (tmp_path / name).mkdir()
    first = make_evidence(tmp_path / "suite_a" / "run-01", mutation=lambda r: r.update(trace_run_id="unique_a"))
    second = make_evidence(tmp_path / "suite_b" / "run-01", mutation=lambda r: r.update(trace_run_id="unique_b"))
    source = Path(first["output_dir"]) / "trace" / "events" / "unique_a.jsonl"
    destination = Path(second["output_dir"]) / "trace" / "events" / "unique_b.jsonl"
    destination.write_bytes(source.read_bytes())
    assert golden.write_evidence_bundle(Path(second["output_dir"]), second)["status"] == "fail"
