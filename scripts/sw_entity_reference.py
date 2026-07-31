"""SolidWorks 语义实体引用。

把特征名、实体类型和几何签名组合成可审计引用，逐步减少对 Face1/Edge1
和屏幕坐标的依赖。模块不猜测 COM API；调用方负责提供候选实体的元数据。
"""
from __future__ import annotations

import hashlib
import json
import numbers
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SemanticEntityReference:
    """@brief 可序列化的语义实体引用。"""

    entity_type: str
    feature_name: str | None = None
    geometry_signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """@brief 转为任务证据 JSON。"""
        return asdict(self)


def geometry_signature(values: Any, precision: int = 6) -> str:
    """@brief 对几何摘要做稳定哈希，避免把屏幕坐标写入任务。"""

    def normalize(value: Any) -> Any:
        if isinstance(value, numbers.Real) and not isinstance(value, bool):
            return round(float(value), precision)
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, Mapping):
            return {str(key): normalize(value[key]) for key in sorted(value, key=str)}
        return value

    canonical = json.dumps(normalize(values), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def reference_from_metadata(entity_type: str, feature_name: str | None = None, geometry: Any = None) -> SemanticEntityReference:
    """@brief 从特征名、类型和几何摘要创建引用。"""
    return SemanticEntityReference(
        entity_type=str(entity_type),
        feature_name=str(feature_name) if feature_name else None,
        geometry_signature=geometry_signature(geometry) if geometry is not None else None,
    )


def resolve_semantic_reference(
    reference: SemanticEntityReference,
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """@brief 按类型、特征名和几何签名解析候选实体。"""
    scored: list[tuple[int, Mapping[str, Any]]] = []
    for candidate in candidates:
        score = 0
        if str(candidate.get("entity_type", candidate.get("type", ""))) == reference.entity_type:
            score += 4
        if reference.feature_name and candidate.get("feature_name", candidate.get("name")) == reference.feature_name:
            score += 3
        if reference.geometry_signature and candidate.get("geometry_signature") == reference.geometry_signature:
            score += 5
        if score:
            scored.append((score, candidate))
    if not scored:
        return {"status": "not_found", "reference": reference.to_dict(), "candidates": []}
    best_score = max(score for score, _ in scored)
    best = [candidate for score, candidate in scored if score == best_score]
    if len(best) != 1:
        return {"status": "ambiguous", "score": best_score, "reference": reference.to_dict(), "candidates": [dict(item) for item in best]}
    return {"status": "resolved", "score": best_score, "reference": reference.to_dict(), "entity": dict(best[0])}
