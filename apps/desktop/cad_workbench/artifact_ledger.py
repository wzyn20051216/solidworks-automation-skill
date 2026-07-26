"""@brief CAD Studio 任务交付物账本。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .core import now_iso


def ledger_dir(queue_dir: Path) -> Path:
    """@brief 返回交付物账本目录。"""
    directory = Path(queue_dir) / "ledgers"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ledger_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief 返回指定任务的交付物账本路径。"""
    return ledger_dir(queue_dir) / f"{safe_job_id(job_id)}.ledger.json"


def sha256_file(path: Path) -> str:
    """@brief 计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_paths(value: Any) -> list[tuple[str, Path]]:
    """@brief 从 result/artifacts 字段提取可能的交付物路径。"""
    paths: list[tuple[str, Path]] = []
    if isinstance(value, str):
        paths.append(("artifact", Path(value)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                paths.append((f"artifact_{index}", Path(item)))
            elif isinstance(item, dict):
                raw_path = item.get("path") or item.get("outputPath")
                if raw_path:
                    paths.append((str(item.get("kind") or item.get("type") or f"artifact_{index}"), Path(str(raw_path))))
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                paths.append((str(key), Path(item)))
            elif isinstance(item, dict):
                raw_path = item.get("path") or item.get("outputPath")
                if raw_path:
                    paths.append((str(key), Path(str(raw_path))))
    return paths


def _artifact_base_dir(job: dict[str, Any]) -> Path:
    """@brief 返回相对交付物路径的解析基准目录。"""
    if job.get("cwd"):
        return Path(str(job["cwd"]))
    if job.get("projectPath"):
        project_path = Path(str(job["projectPath"]))
        if project_path.suffix:
            return project_path.parent
        return project_path
    return Path.cwd()


def collect_artifact_paths(job: dict[str, Any], result: dict[str, Any]) -> list[tuple[str, Path]]:
    """@brief 从任务和执行结果中收集交付物路径。"""
    collected: list[tuple[str, Path]] = []
    if result.get("outputPath"):
        collected.append(("codex_output", Path(str(result["outputPath"]))))
    collected.extend(_candidate_paths(result.get("outputs")))
    collected.extend(_candidate_paths(result.get("artifacts")))
    collected.extend(_candidate_paths(job.get("artifacts")))

    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    base_dir = _artifact_base_dir(job)
    for kind, path in collected:
        if not path.is_absolute():
            path = base_dir / path
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append((kind, path))
    return unique


def describe_artifact(kind: str, path: Path, artifact_baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """@brief 返回单个交付物的存在性、大小和 hash。"""
    resolved = Path(path).expanduser()
    exists = resolved.exists()
    item: dict[str, Any] = {
        "kind": kind,
        "path": str(resolved),
        "exists": exists,
        "isDirectory": resolved.is_dir() if exists else False,
    }
    if exists and resolved.is_file():
        stat = resolved.stat()
        item["sizeBytes"] = stat.st_size
        item["sha256"] = sha256_file(resolved)
        if artifact_baseline is not None:
            before = artifact_baseline.get(str(resolved.resolve()))
            if isinstance(before, dict) and before.get("sha256"):
                item["producedThisRun"] = before.get("sha256") != item["sha256"]
            else:
                item["producedThisRun"] = before is None
    return item


def build_artifact_ledger(queue_dir: Path, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """@brief 构建任务交付物账本对象。"""
    baseline = result.get("artifactBaseline") if isinstance(result.get("artifactBaseline"), dict) else None
    artifacts = [describe_artifact(kind, path, baseline) for kind, path in collect_artifact_paths(job, result)]
    return {
        "schemaVersion": "1.0",
        "jobId": job.get("id"),
        "runId": job.get("runId"),
        "kind": job.get("kind"),
        "executor": job.get("executor", "mock"),
        "target": job.get("target"),
        "objective": job.get("objective"),
        "detail": job.get("detail"),
        "strictRules": job.get("strictRules") if isinstance(job.get("strictRules"), list) else [],
        "expectedOutput": job.get("expectedOutput"),
        "localCadAutomation": bool(
            job.get("uiConfig", {}).get("cadRuntime", {}).get("localCadAutomation")
            if isinstance(job.get("uiConfig"), dict)
            and isinstance(job.get("uiConfig", {}).get("cadRuntime"), dict)
            else False
        ),
        "status": job.get("status"),
        "generatedAt": now_iso(),
        "queueDir": str(Path(queue_dir)),
        "artifacts": artifacts,
        "verification": result.get("verification", []),
        "risks": result.get("risks", []),
        "resultMessage": result.get("message"),
    }


def write_artifact_ledger(queue_dir: Path, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """@brief 写入任务交付物账本并返回账本对象。"""
    ledger = build_artifact_ledger(queue_dir, job, result)
    path = ledger_path_for(queue_dir, job.get("id"))
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger["ledgerPath"] = str(path)
    return ledger
