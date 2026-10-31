"""@brief CAD Studio 任务交付物账本。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .core import now_iso


DELIVERY_FILE_EXTENSIONS = frozenset({
    ".sldprt", ".sldasm", ".slddrw",
    ".step", ".stp", ".iges", ".igs", ".brep",
    ".stl", ".obj", ".glb", ".gltf",
    ".dxf", ".dwg", ".pdf", ".png", ".svg",
})
_CURRENT_RUN_PROOF_EXEMPT_KINDS = frozenset({
    "agent_output", "codex_output", "engineering_plan", "preview_manifest",
})


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


def _artifact_key(path: Path) -> str:
    """@brief 返回跨 Windows 大小写和相对路径一致的文件键。"""
    return os.path.normcase(os.path.normpath(str(Path(path).expanduser().resolve())))


def normalize_artifact_baseline(value: Any) -> dict[str, Any]:
    """@brief 兼容旧纯字典基线，并返回可判断完整性的统一结构。"""
    if isinstance(value, dict) and isinstance(value.get("entries"), dict):
        entries = {
            _artifact_key(Path(str(path))): metadata
            for path, metadata in value["entries"].items()
            if isinstance(metadata, dict)
        }
        errors = value.get("errors")
        return {
            "schemaVersion": str(value.get("schemaVersion") or "2.0"),
            "entries": entries,
            "complete": value.get("complete") is True,
            "truncated": value.get("truncated") is True,
            "scannedCount": int(value.get("scannedCount") or len(entries)),
            "errors": [str(item) for item in errors] if isinstance(errors, list) else [],
            "legacy": False,
        }
    if isinstance(value, dict):
        # 旧版本只保存 path -> metadata，没有完整性字段。旧条目仍可做 hash
        # 比较，但“基线中不存在”不能证明文件是执行后新建的。
        return {
            "schemaVersion": "1.0",
            "entries": {
                _artifact_key(Path(str(path))): metadata
                for path, metadata in value.items()
                if isinstance(metadata, dict)
            },
            "complete": False,
            "truncated": False,
            "scannedCount": len(value),
            "errors": ["legacy_baseline_without_completeness"],
            "legacy": True,
        }
    return {
        "schemaVersion": "2.0",
        "entries": {},
        "complete": False,
        "truncated": False,
        "scannedCount": 0,
        "errors": ["artifact_baseline_missing"],
        "legacy": False,
    }


def artifact_requires_current_run_proof(artifact: dict[str, Any]) -> bool:
    """@brief 判断交付物是否必须证明由本轮生成。"""
    kind = str(artifact.get("kind") or "").lower()
    if kind in _CURRENT_RUN_PROOF_EXEMPT_KINDS:
        return False
    return Path(str(artifact.get("path") or "")).suffix.lower() in DELIVERY_FILE_EXTENSIONS


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


def _describe_artifact(kind: str, path: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    """@brief 使用已规范化的基线描述单个产物。"""
    resolved = Path(path).expanduser()
    exists = resolved.exists()
    item: dict[str, Any] = {
        "kind": kind,
        "path": str(resolved),
        "exists": exists,
        "isDirectory": resolved.is_dir() if exists else False,
        "producedThisRun": None,
    }
    if exists and resolved.is_file():
        stat = resolved.stat()
        item["sizeBytes"] = stat.st_size
        item["sha256"] = sha256_file(resolved)
        before = baseline["entries"].get(_artifact_key(resolved))
        if isinstance(before, dict) and before.get("sha256"):
            item["producedThisRun"] = before.get("sha256") != item["sha256"]
        elif baseline["complete"]:
            item["producedThisRun"] = True
    return item


def describe_artifact(kind: str, path: Path, artifact_baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """@brief 返回交付物事实，并以 true/false/null 表示本轮新鲜度。"""
    return _describe_artifact(kind, path, normalize_artifact_baseline(artifact_baseline))


def build_artifact_ledger(queue_dir: Path, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """@brief 构建任务交付物账本对象。"""
    baseline = normalize_artifact_baseline(result.get("artifactBaseline"))
    artifacts = [_describe_artifact(kind, path, baseline) for kind, path in collect_artifact_paths(job, result)]
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
        "freshnessBaseline": {
            key: baseline[key]
            for key in ("schemaVersion", "complete", "truncated", "scannedCount", "errors", "legacy")
        },
        "artifacts": artifacts,
        "verification": result.get("verification", []),
        "risks": result.get("risks", []),
        "drawingEvidence": result.get("drawingEvidence"),
        "bomEvidence": result.get("bomEvidence"),
        "dfmEvidence": result.get("dfmEvidence"),
        "reviewFindings": result.get("reviewFindings", []),
        "artifactRelations": result.get("artifactRelations", []),
        "resultMessage": result.get("message"),
    }


def write_artifact_ledger(queue_dir: Path, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """@brief 写入任务交付物账本并返回账本对象。"""
    ledger = build_artifact_ledger(queue_dir, job, result)
    path = ledger_path_for(queue_dir, job.get("id"))
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger["ledgerPath"] = str(path)
    return ledger
