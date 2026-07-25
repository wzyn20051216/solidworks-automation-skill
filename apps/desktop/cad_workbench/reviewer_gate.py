"""@brief 基于 Artifact Ledger 的交付物复核门禁。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .core import now_iso


def review_dir(queue_dir: Path) -> Path:
    """@brief 返回 Reviewer Gate 报告目录。"""
    directory = Path(queue_dir) / "reviews"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def review_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief 返回指定任务 Reviewer Gate 报告路径。"""
    return review_dir(queue_dir) / f"{safe_job_id(job_id)}.review.json"


def evaluate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """@brief 根据账本内容生成交付物复核结论。"""
    artifacts = ledger.get("artifacts") if isinstance(ledger.get("artifacts"), list) else []
    checks: list[dict[str, Any]] = []

    if not artifacts:
        checks.append(
            {
                "id": "artifact-present",
                "severity": "P1",
                "status": "warning",
                "message": "任务未声明任何交付物，当前只能确认流程完成，不能确认制造文件齐全。",
            }
        )

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        kind = str(artifact.get("kind") or f"artifact_{index}")
        if artifact.get("exists") is not True:
            checks.append(
                {
                    "id": f"artifact-exists-{kind}",
                    "severity": "P0",
                    "status": "fail",
                    "message": f"交付物不存在: {artifact.get('path')}",
                }
            )
            continue
        if artifact.get("isDirectory") is True:
            checks.append(
                {
                    "id": f"artifact-directory-{kind}",
                    "severity": "P2",
                    "status": "warning",
                    "message": f"交付物是目录，当前只记录路径，未递归校验目录内容: {artifact.get('path')}",
                }
            )
            continue
        size_bytes = int(artifact.get("sizeBytes") or 0)
        if size_bytes <= 0:
            checks.append(
                {
                    "id": f"artifact-nonempty-{kind}",
                    "severity": "P0",
                    "status": "fail",
                    "message": f"交付物为空文件: {artifact.get('path')}",
                }
            )
        elif not artifact.get("sha256"):
            checks.append(
                {
                    "id": f"artifact-hash-{kind}",
                    "severity": "P1",
                    "status": "warning",
                    "message": f"交付物缺少 SHA-256: {artifact.get('path')}",
                }
            )
        else:
            checks.append(
                {
                    "id": f"artifact-file-{kind}",
                    "severity": "P2",
                    "status": "pass",
                    "message": f"交付物存在且已记录 hash: {artifact.get('path')}",
                }
            )

    statuses = {check["status"] for check in checks}
    overall = "fail" if "fail" in statuses else "warning" if "warning" in statuses else "pass"
    return {
        "schemaVersion": "1.0",
        "jobId": ledger.get("jobId"),
        "runId": ledger.get("runId"),
        "status": overall,
        "reviewedAt": now_iso(),
        "artifactCount": len(artifacts),
        "checks": checks,
    }


def write_reviewer_gate(queue_dir: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    """@brief 写入 Reviewer Gate 报告并返回报告对象。"""
    review = evaluate_ledger(ledger)
    path = review_path_for(queue_dir, ledger.get("jobId"))
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    review["reviewPath"] = str(path)
    return review
