"""@brief 基于 Artifact Ledger 的交付物复核门禁。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .core import now_iso

KNOWN_FORMAT_EXTENSIONS = {".step", ".stp", ".stl", ".dxf", ".pdf", ".dwg", ".sldprt", ".sldasm"}
DIMENSION_TRIPLE_PATTERN = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",
    re.IGNORECASE,
)
DIAMETER_PATTERN = re.compile(r"(?:直径|孔径|[Ø⌀Φφ])\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?", re.IGNORECASE)


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

    if extension in {".sldprt", ".sldasm"}:
        label = "SLDASM" if extension == ".sldasm" else "SLDPRT"
        return {
            "id": check_id,
            "severity": "P1",
            "status": "warning",
            "message": f"{label} 为专有格式，当前仅完成文件级记录，后续需由 SolidWorks 打开复核: {path}",
        }

    return None


def _close_measurement(left: float, right: float, tolerance: float = 1e-6) -> bool:
    """@brief 比较机械规格数值，当前任务统一按 mm 记录。"""
    return abs(left - right) <= tolerance


def _same_envelope(left: tuple[float, float, float], right: tuple[float, float, float]) -> bool:
    """@brief 忽略模型坐标轴方向比较外形包围盒尺寸。"""
    return all(
        _close_measurement(left_value, right_value)
        for left_value, right_value in zip(sorted(left), sorted(right))
    )


def _unique_triplets(values: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """@brief 去除任务描述中重复出现的三元尺寸。"""
    unique: list[tuple[float, float, float]] = []
    for value in values:
        if not any(_same_envelope(value, existing) for existing in unique):
            unique.append(value)
    return unique


def _dimension_triplets(text: str) -> list[tuple[float, float, float]]:
    """@brief 从自然语言中提取 L x W x H/厚度三元尺寸。"""
    return [tuple(float(value) for value in match) for match in DIMENSION_TRIPLE_PATTERN.findall(text)]


def _diameters(text: str) -> list[float]:
    """@brief 从自然语言中提取明确标注的孔径。"""
    return [float(value) for value in DIAMETER_PATTERN.findall(text)]


def _json_measurements(value: Any) -> tuple[list[tuple[float, float, float]], list[float]]:
    """@brief 递归读取验收 JSON 中的外形三元尺寸和孔径证据。"""
    triplets: list[tuple[float, float, float]] = []
    diameters: list[float] = []

    def visit(item: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(item, dict):
            normalized = {str(key).lower().replace("-", "_").replace(" ", "_"): child for key, child in item.items()}
            length = normalized.get("length", normalized.get("length_mm"))
            width = normalized.get("width", normalized.get("width_mm"))
            thickness = normalized.get(
                "thickness",
                normalized.get("thickness_mm", normalized.get("height", normalized.get("height_mm"))),
            )
            if not all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in (length, width, thickness)):
                length = normalized.get("size_x", normalized.get("size_x_mm", length))
                width = normalized.get("size_y", normalized.get("size_y_mm", width))
                thickness = normalized.get("size_z", normalized.get("size_z_mm", thickness))
            if all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in (length, width, thickness)):
                triplets.append((float(length), float(width), float(thickness)))
            for key, child in normalized.items():
                is_hole_evidence = (
                    key.startswith("hole_")
                    or any(segment in {"hole", "holes", "孔", "孔洞"} for segment in path)
                    or normalized.get("internal") is True
                )
                if (
                    key in {"diameter", "diameter_mm", "hole_diameter", "hole_diameter_mm"}
                    and is_hole_evidence
                    and isinstance(child, (int, float))
                    and not isinstance(child, bool)
                ):
                    diameters.append(float(child))
                visit(child, (*path, key))
        elif isinstance(item, list):
            for child in item:
                visit(child, path)

    visit(value)
    return triplets, diameters


def _trusted_measurement_payload(value: Any) -> dict[str, Any] | None:
    """@brief 只接受声明为 CAD/B-Rep API 回读的结构化规格报告。"""
    if not isinstance(value, dict):
        return None
    cad_spec = value.get("cad_spec")
    if not isinstance(cad_spec, dict):
        return None
    source = str(cad_spec.get("measurement_source") or value.get("measurement_source") or "")
    trusted_prefixes = ("SolidWorks API ", "AutoCAD ActiveX ", "OpenCascade B-Rep ")
    return cad_spec if source.startswith(trusted_prefixes) else None


def _artifact_measurements(artifacts: list[dict[str, Any]]) -> tuple[list[tuple[float, float, float]], list[float]]:
    """@brief 从本轮 JSON 交付物读取独立于 Codex 摘要的规格证据。"""
    triplets: list[tuple[float, float, float]] = []
    diameters: list[float] = []
    for artifact in artifacts:
        path = Path(str(artifact.get("path") or ""))
        if (
            artifact.get("exists") is not True
            or artifact.get("isDirectory") is True
            or artifact.get("producedThisRun") is not True
            or path.suffix.lower() != ".json"
            or int(artifact.get("sizeBytes") or 0) > 1024 * 1024
        ):
            continue
        try:
            raw = path.read_bytes()
            expected_sha256 = str(artifact.get("sha256") or "")
            if not expected_sha256 or hashlib.sha256(raw).hexdigest() != expected_sha256:
                continue
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        payload = _trusted_measurement_payload(value)
        if payload is None:
            continue
        found_triplets, found_diameters = _json_measurements(payload)
        triplets.extend(found_triplets)
        diameters.extend(found_diameters)
    return triplets, diameters


def _spec_conformance_checks(ledger: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """@brief 对比任务明确尺寸与验收 JSON 的实际规格，阻止错模型进入人工放行。"""
    strict_rules = ledger.get("strictRules") if isinstance(ledger.get("strictRules"), list) else []
    requirement_text = "\n".join(
        [
            str(ledger.get("objective") or ""),
            str(ledger.get("detail") or ""),
            *(str(item) for item in strict_rules),
        ]
    )
    expected_triplets = _dimension_triplets(requirement_text)
    expected_diameters = _diameters(requirement_text)
    evidence_triplets, evidence_diameters = _artifact_measurements(artifacts)
    expected_triplets = _unique_triplets(expected_triplets)
    checks: list[dict[str, Any]] = []

    if expected_triplets:
        missing_envelopes = [
            expected
            for expected in expected_triplets
            if not any(_same_envelope(expected, actual) for actual in evidence_triplets)
        ]
        checks.append(
            {
                "id": "spec-envelope-dimensions",
                "severity": "P0",
                "status": "pass" if evidence_triplets and not missing_envelopes else "fail",
                "message": (
                    f"外形尺寸证据与任务一致: {expected_triplets} mm。"
                    if evidence_triplets and not missing_envelopes
                    else "缺少独立的机器可读外形尺寸证据。"
                    if not evidence_triplets
                    else f"外形尺寸与任务不一致；缺少 {missing_envelopes} mm，验收证据报告 {evidence_triplets} mm。"
                ),
            }
        )

    if expected_diameters:
        unique_expected = sorted(set(expected_diameters))
        unique_actual = sorted(set(evidence_diameters))
        missing = [
            expected
            for expected in unique_expected
            if not any(_close_measurement(expected, actual) for actual in unique_actual)
        ]
        checks.append(
            {
                "id": "spec-hole-diameters",
                "severity": "P0",
                "status": "pass" if evidence_diameters and not missing else "fail",
                "message": (
                    f"孔径证据与任务一致: {unique_expected} mm。"
                    if evidence_diameters and not missing
                    else "任务包含明确孔径，但交付物缺少独立的机器可读孔径证据。"
                    if not evidence_diameters
                    else f"孔径与任务不一致；缺少要求孔径 {missing} mm，验收证据报告 {unique_actual} mm。"
                ),
            }
        )
    return checks


def evaluate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """@brief 根据账本内容生成交付物复核结论。"""
    artifacts = ledger.get("artifacts") if isinstance(ledger.get("artifacts"), list) else []
    checks: list[dict[str, Any]] = []
    delivery_artifacts = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and str(artifact.get("kind") or "") != "codex_output"
    ]
    checks.extend(_spec_conformance_checks(ledger, delivery_artifacts))

    verification = ledger.get("verification") if isinstance(ledger.get("verification"), list) else []
    if ledger.get("executor") == "codex" and not verification:
        checks.append(
            {
                "id": "executor-verification-present",
                "severity": "P1",
                "status": "warning",
                "message": "执行器未返回验证记录，不能确认生成步骤已经完成针对性检查。",
            }
        )
    for index, item in enumerate(verification):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "skipped")
        review_status = "pass" if status == "passed" else "warning" if status == "skipped" else "fail"
        checks.append(
            {
                "id": f"executor-verification-{index}",
                "severity": "P0" if review_status == "fail" else "P1",
                "status": review_status,
                "message": f"执行验证 {status}: {item.get('command') or '未命名检查'}；{item.get('note') or ''}",
            }
        )

    risks = ledger.get("risks") if isinstance(ledger.get("risks"), list) else []
    if risks:
        checks.append(
            {
                "id": "executor-residual-risks",
                "severity": "P1",
                "status": "warning",
                "message": "执行器报告残余风险: " + "；".join(str(item) for item in risks),
            }
        )

    expected_output = str(ledger.get("expectedOutput") or "")
    expected_groups: list[tuple[str, set[str]]] = []
    format_groups = [
        ("SLDPRT", {".sldprt"}),
        ("SLDASM", {".sldasm"}),
        ("STEP", {".step", ".stp"}),
        ("STL", {".stl"}),
        ("DWG", {".dwg"}),
        ("DXF", {".dxf"}),
        ("PDF", {".pdf"}),
    ]
    for label, extensions in format_groups:
        if label in expected_output:
            expected_groups.append((label, extensions))

    for label, expected_extensions in expected_groups:
        matching = []
        for artifact in delivery_artifacts:
            if Path(str(artifact.get("path") or "")).suffix.lower() not in expected_extensions:
                continue
            if artifact.get("exists") is not True:
                continue
            if ledger.get("executor") == "codex" and artifact.get("producedThisRun") is not True:
                continue
            matching.append(artifact)
        checks.append(
            {
                "id": f"expected-cad-deliverable-{label.lower()}",
                "severity": "P0",
                "status": "pass" if matching else "fail",
                "message": (
                    f"已找到本轮生成的 {label} 交付物，共 {len(matching)} 个。"
                    if matching
                    else f"期望输出包含 {label}，但没有找到本轮生成的对应文件；AI JSON 回执或旧文件不能代替交付物。"
                ),
            }
        )
    cad_extensions = {extensions for _, group in format_groups for extensions in group}
    current_run_cad = [
        artifact
        for artifact in delivery_artifacts
        if Path(str(artifact.get("path") or "")).suffix.lower() in cad_extensions
        and artifact.get("exists") is True
        and (ledger.get("executor") != "codex" or artifact.get("producedThisRun") is True)
    ]
    target = str(ledger.get("target") or "")
    expects_non_cad = "调研报告" in expected_output or "Skills" in target or "规范" in target
    if not expected_groups and ledger.get("localCadAutomation") is True and not expects_non_cad and not current_run_cad:
        checks.append(
            {
                "id": "cad-deliverable-not-declared",
                "severity": "P1",
                "status": "warning",
                "message": "本轮允许本机 CAD 自动化，但没有本轮生成的 CAD/图纸文件；TXT、Markdown 和 AI 回执不能作为 CAD 交付物。",
            }
        )

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
