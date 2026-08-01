"""交付物版本比较与可审计重新生成计划。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Iterable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_files(paths: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    """@brief 生成文件版本快照；目录和不存在路径不会伪装成交付物。"""
    snapshot: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        key = str(path)
        if not path.is_file():
            snapshot[key] = {"path": key, "exists": False}
            continue
        stat = path.stat()
        snapshot[key] = {
            "path": key,
            "exists": True,
            "name": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
        }
    return snapshot


def compare_snapshots(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """@brief 比较两轮交付文件并返回 added/removed/changed/unchanged。"""
    rows = []
    for path in sorted(set(previous) | set(current)):
        before = previous.get(path, {"path": path, "exists": False})
        after = current.get(path, {"path": path, "exists": False})
        if not before.get("exists") and after.get("exists"):
            status = "added"
        elif before.get("exists") and not after.get("exists"):
            status = "removed"
        elif before.get("sha256") != after.get("sha256"):
            status = "changed"
        else:
            status = "unchanged"
        rows.append({"path": path, "status": status, "before": before, "after": after})
    counts = {status: sum(row["status"] == status for row in rows) for status in ("added", "removed", "changed", "unchanged")}
    return {"schemaVersion": "1.0", "counts": counts, "items": rows}


def build_regeneration_request(
    *,
    project_id: str,
    source_job_id: str,
    failed_stage: str,
    capabilities: list[str],
    assumptions: list[str] | None = None,
    changed_inputs: list[str] | None = None,
) -> dict[str, Any]:
    """@brief 创建不覆盖旧产物的局部重新生成请求。"""
    if not project_id.strip() or not source_job_id.strip() or not failed_stage.strip():
        raise ValueError("project_id、source_job_id、failed_stage 不能为空")
    return {
        "schemaVersion": "1.0",
        "type": "regeneration_request",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "projectId": project_id,
        "sourceJobId": source_job_id,
        "failedStage": failed_stage,
        "capabilitySnapshot": sorted(set(str(item) for item in capabilities if str(item).strip())),
        "assumptions": list(assumptions or []),
        "changedInputs": list(changed_inputs or []),
        "policy": {
            "preservePreviousArtifacts": True,
            "overwrite": False,
            "requireReview": True,
            "scope": "failed_stage_and_downstream",
        },
    }
