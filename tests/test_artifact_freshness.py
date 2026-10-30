"""@brief 本轮交付文件新鲜度门禁回归；不启动 CAD。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from apps.desktop.cad_workbench.artifact_ledger import build_artifact_ledger
from apps.desktop.cad_workbench.queue_worker import (
    _snapshot_cad_artifacts,
    process_job,
    write_job,
)
from apps.desktop.cad_workbench.reviewer_gate import evaluate_ledger


def _step(path: Path, content: str = "ISO-10303-21;\nEND-ISO-10303-21;\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _ledger(tmp_path: Path, path: Path, baseline, *, executor: str = "agent") -> dict:
    job = {
        "id": f"freshness-{executor}",
        "executor": executor,
        "expectedOutput": path.suffix.lstrip(".").upper(),
        "uiConfig": {"cadRuntime": {"localCadAutomation": True}},
    }
    result = {
        "artifacts": [{"kind": path.suffix.lstrip("."), "path": str(path)}],
        "artifactBaseline": baseline,
    }
    return build_artifact_ledger(tmp_path / "queue", job, result)


@pytest.mark.parametrize("executor", ["agent", "codex", "solidworks-com-pywin32"])
def test_production_executors_reject_unchanged_delivery(tmp_path: Path, executor: str) -> None:
    """@brief 所有生产执行器都必须拒绝执行前已存在且内容未变化的文件。"""
    target = _step(tmp_path / "old.step")
    baseline = _snapshot_cad_artifacts([tmp_path])

    ledger = _ledger(tmp_path, target, baseline, executor=executor)
    review = evaluate_ledger(ledger)

    assert ledger["artifacts"][0]["producedThisRun"] is False
    assert review["status"] == "fail"
    assert any(
        check["id"] == "artifact-current-run" and check["status"] == "fail"
        for check in review["checks"]
    )


def test_unknown_baseline_requires_review_instead_of_passing(tmp_path: Path) -> None:
    """@brief 缺少基线时不得猜测为新一轮生成，应进入人工复核。"""
    target = _step(tmp_path / "unknown.step")

    ledger = _ledger(tmp_path, target, None)
    review = evaluate_ledger(ledger)

    assert ledger["artifacts"][0]["producedThisRun"] is None
    assert review["status"] == "warning"
    assert any(
        check["id"] == "artifact-current-run" and check["status"] == "warning"
        for check in review["checks"]
    )
    assert not any(check["status"] == "fail" for check in review["checks"])


def test_truncated_baseline_is_unknown(tmp_path: Path) -> None:
    """@brief 基线扫描截断后，未出现在条目中的文件不能证明为本轮生成。"""
    target = _step(tmp_path / "truncated.step")
    baseline = {
        "schemaVersion": "2.0",
        "entries": {},
        "complete": False,
        "truncated": True,
        "scannedCount": 10000,
        "errors": ["baseline_limit_reached"],
    }

    ledger = _ledger(tmp_path, target, baseline)
    review = evaluate_ledger(ledger)

    assert ledger["artifacts"][0]["producedThisRun"] is None
    assert review["status"] == "warning"


def test_legacy_baseline_is_compatible_but_cannot_prove_new_file(tmp_path: Path) -> None:
    """@brief 旧纯字典仍可比较已有条目，但不能把未记录文件自动判为新文件。"""
    target = _step(tmp_path / "legacy.step")

    ledger = _ledger(tmp_path, target, {})
    review = evaluate_ledger(ledger)

    assert ledger["artifacts"][0]["producedThisRun"] is None
    assert review["status"] == "warning"


def test_new_and_modified_files_pass_current_run_proof(tmp_path: Path) -> None:
    """@brief 执行前不存在或 hash 改变的文件可以满足本轮交付。"""
    baseline = _snapshot_cad_artifacts([tmp_path])
    target = _step(tmp_path / "new.step")

    new_review = evaluate_ledger(_ledger(tmp_path, target, baseline))
    assert new_review["status"] == "pass"

    after_new = _snapshot_cad_artifacts([tmp_path])
    _step(target, "ISO-10303-21;\nUPDATED\nEND-ISO-10303-21;\n")
    modified_review = evaluate_ledger(_ledger(tmp_path, target, after_new))
    assert modified_review["status"] == "pass"


def test_touch_only_does_not_satisfy_current_run_proof(tmp_path: Path) -> None:
    """@brief 只修改时间戳、不改变内容仍视为旧文件。"""
    target = _step(tmp_path / "touched.step")
    baseline = _snapshot_cad_artifacts([tmp_path])
    os.utime(target, None)

    review = evaluate_ledger(_ledger(tmp_path, target, baseline))

    assert review["status"] == "fail"


def test_mixed_fresh_and_stale_files_fail(tmp_path: Path) -> None:
    """@brief 新文件不能让混合在同一交付中的旧文件蒙混过关。"""
    stale = _step(tmp_path / "old.step")
    baseline = _snapshot_cad_artifacts([tmp_path])
    fresh = _step(tmp_path / "new.step")
    job = {
        "id": "freshness-mixed",
        "executor": "agent",
        "expectedOutput": "STEP",
        "uiConfig": {"cadRuntime": {"localCadAutomation": True}},
    }
    result = {
        "artifacts": [
            {"kind": "step", "path": str(stale)},
            {"kind": "step", "path": str(fresh)},
        ],
        "artifactBaseline": baseline,
    }

    review = evaluate_ledger(build_artifact_ledger(tmp_path / "queue", job, result))

    assert review["status"] == "fail"
    assert any(
        check["id"] == "artifact-current-run"
        and check["status"] == "fail"
        and str(stale) in check["message"]
        for check in review["checks"]
    )


def test_snapshot_covers_slddrw_and_skips_outside_symlink(tmp_path: Path) -> None:
    """@brief 工程图必须进入基线，指向根目录外的链接不得被读取。"""
    drawing = tmp_path / "drawing.slddrw"
    drawing.write_bytes(b"SolidWorks drawing fixture")
    outside = tmp_path.parent / "outside-drawing.slddrw"
    outside.write_bytes(b"outside")
    link = tmp_path / "linked.slddrw"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("环境不允许创建文件符号链接")

    baseline = _snapshot_cad_artifacts([tmp_path])
    keys = {os.path.normcase(os.path.normpath(path)) for path in baseline["entries"]}

    assert os.path.normcase(os.path.normpath(str(drawing.resolve()))) in keys
    assert os.path.normcase(os.path.normpath(str(outside.resolve()))) not in keys
    assert baseline["complete"] is True


@pytest.mark.parametrize(("baseline", "expected_status"), [
    ("stale", "failed"),
    (None, "review_required"),
])
def test_worker_maps_freshness_failures_to_safe_terminal_states(
    tmp_path: Path,
    baseline,
    expected_status: str,
) -> None:
    """@brief Worker 将旧文件映射 failed，将未知新鲜度映射 review_required。"""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    target = _step(tmp_path / "worker.step")
    snapshot = _snapshot_cad_artifacts([tmp_path]) if baseline == "stale" else None
    job_path = queue_dir / "job.json"
    write_job(job_path, {
        "schemaVersion": "2.0",
        "id": "freshness-worker",
        "kind": "agent_task",
        "executor": "agent",
        "status": "queued",
        "capabilities": ["part_and_features"],
        "expectedOutput": "STEP",
        "uiConfig": {
            "outputDir": str(tmp_path),
            "cadRuntime": {"localCadAutomation": True},
        },
    })

    result = process_job(job_path, handlers={
        "agent_task": lambda _job: {
            "message": "Agent 返回交付文件",
            "artifacts": [{"kind": "step", "path": str(target)}],
            "artifactBaseline": snapshot,
        },
    })

    assert result is not None
    assert result["status"] == expected_status
