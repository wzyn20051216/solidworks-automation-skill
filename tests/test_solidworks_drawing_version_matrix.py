"""SolidWorks 工程图跨版本矩阵离线测试。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("solidworks_drawing_version_matrix.py")
SPEC = importlib.util.spec_from_file_location("solidworks_drawing_version_matrix", MODULE_PATH)
assert SPEC and SPEC.loader
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


def test_matrix_runs_only_exact_registered_versions(tmp_path: Path):
    """@brief 未安装版本不得回退到默认 ProgID 并被误记为通过。"""
    calls = []

    def runner(output_root, *, version, run_id):
        calls.append((output_root, version, run_id))
        return {
            "status": "ok",
            "solidworks": {"year": version, "revision": "34.1.1"},
            "output_dir": str(output_root / run_id),
            "report": {"path": str(output_root / run_id / "report.json")},
        }

    result = MATRIX.run_matrix(
        tmp_path,
        registered_versions={2024: False, 2025: False, 2026: True},
        runner=runner,
        run_id="matrix",
    )

    assert result["status"] == "partial"
    assert result["summary"] == {"pass": 1, "failed": 0, "unavailable": 2}
    assert [item[1] for item in calls] == [2026]
    assert [item["status"] for item in result["versions"]] == ["unavailable", "unavailable", "pass"]
    assert Path(result["report_path"]).is_file()
    persisted = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert persisted["report_path"] == result["report_path"]


def test_matrix_rejects_actual_version_mismatch(tmp_path: Path):
    """@brief 指定 SW2025 却连接到 SW2026 时必须失败。"""
    def runner(_output_root, *, version, run_id):
        assert version == 2025 and run_id == "matrix_sw2025"
        return {"status": "ok", "solidworks": {"year": 2026, "revision": "34.1.1"}}

    result = MATRIX.run_matrix(
        tmp_path,
        years=[2025],
        registered_versions={2025: True},
        runner=runner,
        run_id="matrix",
    )

    assert result["status"] == "failed"
    assert result["versions"][0]["reason"] == "regression_failed_or_version_mismatch"


def test_matrix_blocks_when_no_target_version_is_registered(tmp_path: Path):
    """@brief 没有目标版本时生成 blocked 报告且不调用运行器。"""
    def runner(*_args, **_kwargs):
        raise AssertionError("未注册版本不得启动回归")

    result = MATRIX.run_matrix(
        tmp_path,
        years=[2024, 2025],
        registered_versions={2024: False, 2025: False},
        runner=runner,
        run_id="matrix",
    )

    assert result["status"] == "blocked"
    assert result["summary"]["unavailable"] == 2


def test_prog_id_mapping_matches_solidworks_major_versions():
    assert MATRIX.prog_id_for_year(2024) == "SldWorks.Application.32"
    assert MATRIX.prog_id_for_year(2026) == "SldWorks.Application.34"
