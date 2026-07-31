"""@brief CAD Studio/SolidWorks Skill 的能力真源读取与门禁工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "capabilities.yaml"
VALID_LEVELS = {"verified", "pilot", "reference_only", "not_implemented"}


def manifest_path(path: str | Path | None = None) -> Path:
    """@brief 返回能力清单路径。"""
    return Path(path).expanduser().resolve() if path else MANIFEST_PATH


def load_capabilities(path: str | Path | None = None) -> dict[str, Any]:
    """@brief 读取 JSON-compatible YAML 能力清单并做最小结构校验。"""
    source = manifest_path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
        raise ValueError(f"能力清单格式无效: {source}")
    for item in payload["capabilities"]:
        if not isinstance(item, dict) or not item.get("id") or item.get("level") not in VALID_LEVELS:
            raise ValueError(f"能力清单条目无效: {item!r}")
    return payload


def capability_index(payload: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """@brief 返回能力 ID 到条目的索引。"""
    source = payload or load_capabilities()
    return {str(item["id"]): dict(item) for item in source.get("capabilities", [])}


def capability_level(capability_id: str, payload: Mapping[str, Any] | None = None) -> str:
    """@brief 返回能力等级，未知能力按未实现处理。"""
    return capability_index(payload).get(capability_id, {}).get("level", "not_implemented")


def unattended_allowed(capability_ids: Iterable[str], payload: Mapping[str, Any] | None = None) -> bool:
    """@brief 判断一组能力是否允许无人值守执行。"""
    return all(capability_level(capability_id, payload) == "verified" for capability_id in capability_ids)


def capability_snapshot(capability_ids: Iterable[str] | None = None, payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """@brief 生成可写入任务证据的能力快照。"""
    index = capability_index(payload)
    selected = list(capability_ids) if capability_ids is not None else list(index)
    return [dict(index.get(capability_id, {"id": capability_id, "level": "not_implemented"})) for capability_id in selected]
