"""@brief CalculiX 多网格收敛序列执行与证据汇总。"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .fea_analysis import run_analysis, validate_analysis
except ImportError:
    from fea_analysis import run_analysis, validate_analysis


def _now_iso() -> str:
    """@brief 返回 UTC 秒级时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_positive(value: Any, field: str, *, maximum: float | None = None) -> float:
    """@brief 校验有限正数和可选上限。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是有限正数。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限正数。") from exc
    if not math.isfinite(number) or number <= 0 or (maximum is not None and number > maximum):
        raise ValueError(f"{field} 超出允许范围。")
    return number


def _identifier(value: Any, field: str) -> str:
    """@brief 校验不会进入路径或求解器关键字的标识符。"""
    token = str(value or "")
    if not token or len(token) > 64 or not token[0].isalpha() or not all(char.isalnum() or char == "_" for char in token):
        raise ValueError(f"{field} 只能使用字母开头的 1-64 位字母、数字或下划线。")
    return token


def _load_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 从字典或不超过 128 MiB 的 JSON 文件读取收敛请求。"""
    if isinstance(value, dict):
        return dict(value)
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError("网格收敛请求必须是存在的 JSON 文件。")
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("网格收敛请求超过 128 MiB 安全上限。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("网格收敛请求必须是 JSON object。")
    return payload


def _physics_fingerprint(analysis: dict[str, Any]) -> str:
    """@brief 计算不含网格和任务 ID 的物理条件指纹。"""
    payload = {
        key: analysis[key]
        for key in ("analysisType", "solver", "units", "material", "constraints", "loads")
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_convergence_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 校验至少三档、物理条件一致且网格严格细化的收敛请求。"""
    request = _load_request(value)
    allowed = {"schemaVersion", "studyId", "tolerancePercent", "cases"}
    if set(request) - allowed:
        raise ValueError(f"收敛请求含未允许字段: {', '.join(sorted(set(request) - allowed))}")
    if request.get("schemaVersion") != "1.0":
        raise ValueError("schemaVersion 必须为 1.0。")
    _identifier(request.get("studyId"), "studyId")
    _finite_positive(request.get("tolerancePercent"), "tolerancePercent", maximum=25.0)
    cases = request.get("cases")
    if not isinstance(cases, list) or not 3 <= len(cases) <= 8:
        raise ValueError("cases 必须包含 3-8 档网格。")
    case_ids: set[str] = set()
    previous_size = math.inf
    previous_nodes = 0
    previous_elements = 0
    fingerprint = None
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) != {"id", "characteristicSizeMm", "analysis"}:
            raise ValueError(f"cases[{index}] 结构无效。")
        case_id = _identifier(case.get("id"), f"cases[{index}].id")
        if case_id in case_ids:
            raise ValueError(f"收敛 case ID 重复: {case_id}")
        case_ids.add(case_id)
        size = _finite_positive(case.get("characteristicSizeMm"), f"cases[{index}].characteristicSizeMm")
        if size >= previous_size:
            raise ValueError("characteristicSizeMm 必须按粗到细严格递减。")
        previous_size = size
        analysis = validate_analysis(case.get("analysis"))
        if analysis["analysisType"] != "static_linear" or analysis["solver"] not in {"auto", "calculix"}:
            raise ValueError("网格收敛当前只允许 CalculiX static_linear。")
        node_count = len(analysis["mesh"]["nodes"])
        element_count = len(analysis["mesh"]["elements"])
        if node_count <= previous_nodes or element_count <= previous_elements:
            raise ValueError("网格细化时节点数和单元数必须严格增加。")
        previous_nodes = node_count
        previous_elements = element_count
        current_fingerprint = _physics_fingerprint(analysis)
        if fingerprint is None:
            fingerprint = current_fingerprint
        elif current_fingerprint != fingerprint:
            raise ValueError("所有收敛 case 的材料、载荷和约束必须完全一致。")
    return request


def _versioned_directory(path: Path) -> Path:
    """@brief 返回不覆盖既有目录的版本化目录。"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.name}_v{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _relative_change_percent(previous: float, current: float) -> float:
    """@brief 计算相邻网格结果相对变化百分比。"""
    return abs(current - previous) / max(abs(current), abs(previous), 1e-15) * 100.0


def run_convergence_study(
    value: str | Path | dict[str, Any],
    output_dir: str | Path,
    *,
    timeout_seconds_per_case: int = 600,
) -> dict[str, Any]:
    """@brief 依次真实求解各档网格并汇总位移/应力收敛证据。"""
    try:
        request = validate_convergence_request(value)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": "1.0", "status": "blocked", "stage": "validate",
            "studyId": None, "cases": [], "artifacts": [], "manual_review_required": True,
            "retryable": False, "error_code": "fea_convergence_invalid_request",
            "message": str(exc), "generatedAt": _now_iso(),
        }
    root = _versioned_directory(Path(output_dir).expanduser().resolve() / request["studyId"])
    root.mkdir(parents=True, exist_ok=False)
    case_results = []
    artifacts = []
    for case in request["cases"]:
        analysis = dict(case["analysis"])
        analysis["analysisId"] = f"{request['studyId']}_{case['id']}"
        result = run_analysis(analysis, root, timeout_seconds=timeout_seconds_per_case)
        summary = result.get("resultEvidence", {}).get("summary", {})
        record = {
            "id": case["id"],
            "characteristicSizeMm": float(case["characteristicSizeMm"]),
            "nodeCount": len(analysis["mesh"]["nodes"]),
            "elementCount": len(analysis["mesh"]["elements"]),
            "status": result.get("status"),
            "error_code": result.get("error_code"),
            "maximumDisplacementMm": summary.get("maximumDisplacementMm"),
            "maximumVonMisesStressMPa": summary.get("maximumVonMisesStressMPa"),
            "solverVersion": summary.get("solverVersion"),
        }
        case_results.append(record)
        artifacts.extend(result.get("artifacts", []))
        if result.get("status") != "review_required":
            return {
                "schemaVersion": "1.0", "status": "failed", "stage": "solve",
                "studyId": request["studyId"], "cases": case_results, "artifacts": artifacts,
                "manual_review_required": True, "retryable": True,
                "error_code": "fea_convergence_case_failed", "failedCase": case["id"],
                "caseResult": result, "generatedAt": _now_iso(),
            }
    changes = []
    for previous, current in zip(case_results, case_results[1:]):
        displacement_change = _relative_change_percent(
            float(previous["maximumDisplacementMm"]), float(current["maximumDisplacementMm"])
        )
        stress_change = _relative_change_percent(
            float(previous["maximumVonMisesStressMPa"]), float(current["maximumVonMisesStressMPa"])
        )
        changes.append({
            "from": previous["id"], "to": current["id"],
            "displacementChangePercent": displacement_change,
            "stressChangePercent": stress_change,
        })
    tolerance = float(request["tolerancePercent"])
    last_change = changes[-1]
    converged = (
        last_change["displacementChangePercent"] <= tolerance
        and last_change["stressChangePercent"] <= tolerance
    )
    report = {
        "schemaVersion": "1.0", "status": "review_required", "stage": "review",
        "studyId": request["studyId"], "solver": "calculix", "cases": case_results,
        "changes": changes, "tolerancePercent": tolerance, "converged": converged,
        "artifacts": artifacts, "manual_review_required": True,
        "retryable": not converged,
        "error_code": None if converged else "fea_mesh_convergence_not_reached",
        "limitations": [
            "收敛只比较最后两档网格的最大位移和最大 Von Mises 应力；仍需检查应力奇异点、载荷合理性和局部结果。",
        ],
        "generatedAt": _now_iso(),
    }
    report_path = root / "convergence_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["reportPath"] = str(report_path)
    return report

