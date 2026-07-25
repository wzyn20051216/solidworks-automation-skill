"""@brief 基于 Artifact Ledger 的交付物复核门禁。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .core import now_iso

KNOWN_FORMAT_EXTENSIONS = {".step", ".stp", ".stl", ".dxf", ".pdf", ".dwg", ".sldprt"}


def review_dir(queue_dir: Path) -> Path:
    """@brief 返回 Reviewer Gate 报告目录。"""
    directory = Path(queue_dir) / "reviews"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def review_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief 返回指定任务 Reviewer Gate 报告路径。"""
    return review_dir(queue_dir) / f"{safe_job_id(job_id)}.review.json"


def _read_file_sample(path: Path, limit: int = 1024 * 1024) -> bytes:
    """@brief 读取文件开头样本，避免为了格式检查加载超大 CAD 文件。"""
    with Path(path).open("rb") as handle:
        return handle.read(limit)


def _artifact_extension(kind: str, path: Path) -> str:
    """@brief 根据路径后缀或 kind 推断交付物格式。"""
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    normalized = kind.lower().lstrip(".")
    return f".{normalized}" if f".{normalized}" in KNOWN_FORMAT_EXTENSIONS else ""


def _text_sample(sample: bytes) -> str:
    """@brief 把二进制样本宽松转为文本，供 STEP/DXF/STL 文本特征检查。"""
    return sample.decode("utf-8", errors="ignore").upper()


def validate_known_format(kind: str, path: Path) -> dict[str, Any] | None:
    """@brief 对常见 CAD 交付格式做轻量打开性/格式特征检查。"""
    extension = _artifact_extension(kind, path)
    if extension not in KNOWN_FORMAT_EXTENSIONS:
        return None

    sample = _read_file_sample(path)
    text = _text_sample(sample)
    check_id = f"artifact-format-{kind}"

    if extension in {".step", ".stp"}:
        valid = "ISO-10303-21" in text and "END-ISO-10303-21" in text
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"STEP 文件{'包含' if valid else '缺少'} ISO-10303-21 结构标记: {path}",
        }

    if extension == ".stl":
        ascii_valid = text.lstrip().startswith("SOLID") and "ENDSOLID" in text
        binary_valid = len(sample) >= 84 and not text.lstrip().startswith("SOLID")
        valid = ascii_valid or binary_valid
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"STL 文件{'具备' if valid else '缺少'}可识别的 ASCII/Binary 结构: {path}",
        }

    if extension == ".dxf":
        valid = "SECTION" in text and text.rstrip().endswith("EOF")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"DXF 文件{'包含' if valid else '缺少'} SECTION/EOF 结构标记: {path}",
        }

    if extension == ".pdf":
        valid = sample.startswith(b"%PDF-")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"PDF 文件{'包含' if valid else '缺少'} %PDF 文件头: {path}",
        }

    if extension == ".dwg":
        valid = sample.startswith(b"AC10")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"DWG 文件{'包含' if valid else '缺少'} AutoCAD AC10 版本头: {path}",
        }

    if extension == ".sldprt":
        return {
            "id": check_id,
            "severity": "P1",
            "status": "warning",
            "message": f"SLDPRT 为专有格式，当前仅完成文件级记录，后续需由 SolidWorks 打开复核: {path}",
        }

    return None


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
            format_check = validate_known_format(kind, Path(str(artifact.get("path"))))
            if format_check:
                checks.append(format_check)

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
