"""@brief DFM 工艺 Profile 的校验、安全装载和约束合并。

Profile 只描述可追溯的制造能力边界。模块不会执行 Profile 中的路径、URL 或
代码，也不会允许后加载的 Profile 放宽已经生效的制造约束。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


PROFILE_SCHEMA = "cadstudio.dfm-profile"
PROFILE_VERSION = "1.0"
MAX_PROFILE_BYTES = 1024 * 1024
SUPPORTED_PROCESSES = {"machining", "sheet_metal", "laser_cutting", "3d_printing"}
TOP_LEVEL_FIELDS = {"schema", "version", "id", "source", "limits", "processes", "description"}
SOURCE_FIELDS = {"type", "name", "revision", "reference"}
LIMIT_FIELDS = {
    "allowedMaterials",
    "minimumWallThickness",
    "maximumEnvelope",
    "workEnvelope",
    "formingEnvelope",
    "buildVolume",
    "minimumDrillDiameter",
    "minimumInternalCornerRadius",
    "availableToolDiameters",
    "maximumHoleDepthDiameterRatio",
    "minimumThickness",
    "maximumThickness",
    "minimumBendRadius",
    "minimumBendRadiusRatio",
    "minimumKerf",
    "maximumKerf",
    "minimumHoleOrSlot",
    "maximumUnsupportedOverhangDeg",
    "requiresBrepEvidence",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MINIMUM_LIMITS = {
    "minimumWallThickness",
    "minimumDrillDiameter",
    "minimumInternalCornerRadius",
    "minimumThickness",
    "minimumBendRadius",
    "minimumBendRadiusRatio",
    "minimumKerf",
    "minimumHoleOrSlot",
}
_MAXIMUM_LIMITS = {
    "maximumHoleDepthDiameterRatio",
    "maximumThickness",
    "maximumKerf",
    "maximumUnsupportedOverhangDeg",
}
_ENVELOPE_LIMITS = {"maximumEnvelope", "workEnvelope", "formingEnvelope", "buildVolume"}


class DfmProfileError(ValueError):
    """@brief 表示 Profile 不可信、格式无效或合并后矛盾。"""


def _canonical_hash(payload: dict[str, Any]) -> str:
    """@brief 对规范化 JSON 计算稳定 SHA-256。"""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _positive_number(value: Any, field: str) -> float:
    """@brief 校验正有限数。"""
    if isinstance(value, bool):
        raise DfmProfileError(f"Profile limits.{field} 必须是正数，不能是 boolean。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DfmProfileError(f"Profile limits.{field} 必须是正数。") from exc
    if not 0 < number < float("inf"):
        raise DfmProfileError(f"Profile limits.{field} 必须是正有限数。")
    return number


def _positive_vector(value: Any, field: str) -> list[float]:
    """@brief 校验三轴能力空间。"""
    if not isinstance(value, list) or len(value) != 3:
        raise DfmProfileError(f"Profile limits.{field} 必须是三个正数的数组。")
    return [_positive_number(item, field) for item in value]


def validate_profile(payload: Any) -> dict[str, Any]:
    """@brief 严格校验并规范化单个 DFM Profile。

    @param payload 待校验 JSON object。
    @return 可安全合并的规范化 Profile。
    @raises DfmProfileError 出现未知字段、危险值或不支持版本时抛出。
    """
    if not isinstance(payload, dict):
        raise DfmProfileError("DFM Profile 必须是 JSON object。")
    unknown = sorted(set(payload) - TOP_LEVEL_FIELDS)
    if unknown:
        raise DfmProfileError("DFM Profile 含未知顶层字段: " + ", ".join(unknown))
    for field in ("schema", "version", "id", "source", "limits"):
        if field not in payload:
            raise DfmProfileError(f"DFM Profile 缺少必填字段 {field}。")
    if payload.get("schema") != PROFILE_SCHEMA or str(payload.get("version")) != PROFILE_VERSION:
        raise DfmProfileError(f"仅支持 {PROFILE_SCHEMA} {PROFILE_VERSION}。")
    profile_id = str(payload.get("id") or "")
    if not _IDENTIFIER.fullmatch(profile_id):
        raise DfmProfileError("DFM Profile id 只能包含字母、数字、点、下划线和连字符。")

    source = payload.get("source")
    if not isinstance(source, dict):
        raise DfmProfileError("DFM Profile source 必须是 object。")
    unknown_source = sorted(set(source) - SOURCE_FIELDS)
    if unknown_source:
        raise DfmProfileError("DFM Profile source 含未知字段: " + ", ".join(unknown_source))
    if not str(source.get("type") or "").strip() or not str(source.get("name") or "").strip():
        raise DfmProfileError("DFM Profile source 必须包含非空 type 和 name。")

    processes = payload.get("processes", [])
    if processes is None:
        processes = []
    if not isinstance(processes, list) or any(item not in SUPPORTED_PROCESSES for item in processes):
        raise DfmProfileError("DFM Profile processes 包含不支持的工艺。")
    if len(set(processes)) != len(processes):
        raise DfmProfileError("DFM Profile processes 不得重复。")

    limits = payload.get("limits")
    if not isinstance(limits, dict) or not limits:
        raise DfmProfileError("DFM Profile limits 必须是非空 object。")
    unknown_limits = sorted(set(limits) - LIMIT_FIELDS)
    if unknown_limits:
        raise DfmProfileError("DFM Profile limits 含未知或不允许覆盖的字段: " + ", ".join(unknown_limits))
    normalized_limits: dict[str, Any] = {}
    for key, value in limits.items():
        if key in _MINIMUM_LIMITS | _MAXIMUM_LIMITS:
            normalized_limits[key] = _positive_number(value, key)
        elif key in _ENVELOPE_LIMITS:
            normalized_limits[key] = _positive_vector(value, key)
        elif key == "requiresBrepEvidence":
            if not isinstance(value, bool):
                raise DfmProfileError("Profile limits.requiresBrepEvidence 必须是 boolean。")
            normalized_limits[key] = value
        elif key in {"allowedMaterials"}:
            if not isinstance(value, list) or not value or any(not str(item).strip() for item in value):
                raise DfmProfileError(f"Profile limits.{key} 必须是非空材料名称数组。")
            normalized_limits[key] = sorted({str(item).strip() for item in value}, key=str.casefold)
        elif key == "availableToolDiameters":
            if not isinstance(value, list) or not value:
                raise DfmProfileError("Profile limits.availableToolDiameters 必须是非空正数数组。")
            normalized_limits[key] = sorted({_positive_number(item, key) for item in value})

    normalized = {
        "schema": PROFILE_SCHEMA,
        "version": PROFILE_VERSION,
        "id": profile_id,
        "source": {key: source[key] for key in sorted(source) if source[key] not in (None, "")},
        "limits": normalized_limits,
        "processes": list(processes),
    }
    if str(payload.get("description") or "").strip():
        normalized["description"] = str(payload["description"]).strip()
    normalized["sha256"] = _canonical_hash(normalized)
    return normalized


def _resolve_profile_path(path: Path, allowed_root: Path | None) -> Path:
    """@brief 解析 Profile 路径并阻止相对路径逃逸。"""
    raw = Path(path).expanduser()
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        if allowed_root is None:
            raise DfmProfileError("相对 Profile 路径必须提供 allowed_root。")
        root = allowed_root.expanduser().resolve()
        resolved = (root / raw).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise DfmProfileError("相对 Profile 路径逃逸 allowed_root，已拒绝。") from exc
    if resolved.suffix.lower() != ".json" or not resolved.is_file():
        raise DfmProfileError("DFM Profile 必须是存在的 .json 文件。")
    if resolved.stat().st_size > MAX_PROFILE_BYTES:
        raise DfmProfileError("DFM Profile 超过 1 MiB 安全上限。")
    return resolved


def load_profile(value: str | Path | dict[str, Any], *, allowed_root: Path | None = None) -> dict[str, Any]:
    """@brief 从内存对象或受限 JSON 文件装载 Profile。"""
    if isinstance(value, dict):
        return validate_profile(value)
    path = _resolve_profile_path(Path(value), allowed_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DfmProfileError(f"无法读取 DFM Profile: {exc}") from exc
    profile = validate_profile(payload)
    profile["profilePath"] = str(path)
    profile["fileSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return profile


def load_profiles(
    values: Iterable[str | Path | dict[str, Any]] | None,
    *,
    allowed_root: Path | None = None,
) -> list[dict[str, Any]]:
    """@brief 装载 Profile 列表并拒绝重复 ID。"""
    profiles = [load_profile(value, allowed_root=allowed_root) for value in (values or [])]
    ids = [profile["id"] for profile in profiles]
    if len(ids) != len(set(ids)):
        raise DfmProfileError("DFM Profile id 不得重复。")
    return profiles


def _intersect_casefold(left: list[str], right: list[str]) -> list[str]:
    """@brief 按不区分大小写语义求材料集合交集。"""
    right_tokens = {item.casefold() for item in right}
    return [item for item in left if item.casefold() in right_tokens]


def merge_profiles(profiles: list[dict[str, Any]], process: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """@brief 按能力交集合并适用于指定工艺的 Profile。

    最小制造要求取最大值，最大能力取最小值，设备空间逐轴取最小值，材料与刀具
    取集合交集。该策略确保后加载的配置不能静默放宽先前约束。
    """
    effective: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for profile in profiles:
        applicable = not profile["processes"] or process in profile["processes"]
        record = {
            "id": profile["id"],
            "schema": profile["schema"],
            "version": profile["version"],
            "source": profile["source"],
            "sha256": profile["sha256"],
            "fileSha256": profile.get("fileSha256"),
            "applicable": applicable,
            "processes": profile["processes"],
            "appliedLimits": [],
        }
        if not applicable:
            record["reason"] = f"Profile 不适用于 {process}。"
            records.append(record)
            continue
        for key, value in profile["limits"].items():
            if key in _MINIMUM_LIMITS:
                effective[key] = max(float(effective.get(key, 0)), float(value))
            elif key in _MAXIMUM_LIMITS:
                effective[key] = min(float(effective.get(key, value)), float(value))
            elif key in _ENVELOPE_LIMITS:
                current = effective.get(key)
                effective[key] = list(value) if current is None else [min(current[index], value[index]) for index in range(3)]
            elif key == "allowedMaterials":
                effective[key] = list(value) if key not in effective else _intersect_casefold(effective[key], value)
            elif key == "availableToolDiameters":
                current = effective.get(key)
                effective[key] = list(value) if current is None else sorted(set(current) & set(value))
            elif key == "requiresBrepEvidence":
                effective[key] = bool(effective.get(key, False) or value)
            record["appliedLimits"].append(key)
        records.append(record)

    if "minimumThickness" in effective and "maximumThickness" in effective:
        if effective["minimumThickness"] > effective["maximumThickness"]:
            raise DfmProfileError("合并后的最小厚度大于最大厚度，Profile 能力交集为空。")
    if "minimumKerf" in effective and "maximumKerf" in effective:
        if effective["minimumKerf"] > effective["maximumKerf"]:
            raise DfmProfileError("合并后的最小 kerf 大于最大 kerf，Profile 能力交集为空。")
    if "allowedMaterials" in effective and not effective["allowedMaterials"]:
        raise DfmProfileError("Profile 的材料能力交集为空。")
    if "availableToolDiameters" in effective and not effective["availableToolDiameters"]:
        raise DfmProfileError("Profile 的刀具直径交集为空。")
    return effective, records


__all__ = [
    "DfmProfileError",
    "PROFILE_SCHEMA",
    "PROFILE_VERSION",
    "load_profile",
    "load_profiles",
    "merge_profiles",
    "validate_profile",
]
