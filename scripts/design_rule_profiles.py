"""
@file design_rule_profiles.py
@brief 设计规则检查（DRC）Profile 的校验与合并。

Profile 是**声明式**的：只描述阈值、要停用的规则和数据驱动的自定义规则，绝不包含或执行
任何代码、路径或 URL。这样代理可以把用户的自然语言（例如“螺纹孔到边缘至少 2 倍孔径、
壁厚不低于 1.5mm、弹簧指数控制在 5 到 10”）翻译成一个安全的 Profile JSON 传给检查器，
既能**配置**内置规则，又能**补充**新规则，而不需要写 Python。

安全约束（与 dfm_profiles 一致的思路）：
- 只允许白名单字段、算子、类别和严重度；未知字段一律拒绝。
- Profile 体积上限，标识符受正则约束。
- 不加载、不执行 Profile 中的任何字符串为代码或文件路径。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

PROFILE_SCHEMA = "cadstudio.drc-profile"
PROFILE_VERSION = "1.0"
MAX_PROFILE_BYTES = 512 * 1024
MAX_CUSTOM_RULES = 64

TOP_LEVEL_FIELDS = {"schema", "version", "id", "description", "thresholds", "disabledRules", "customRules"}

# 阈值白名单及其“方向”：minimum=越大越严，maximum=越小越严，plain=直接覆盖。
THRESHOLD_FIELDS: dict[str, str] = {
    "minWallThicknessMm": "minimum",
    "minFeatureSizeMm": "minimum",
    "holeEdgeDistanceRatio": "minimum",
    "holeEdgeDistanceMinMm": "minimum",
    "holeSpacingRatio": "minimum",
    "ligamentMinMm": "minimum",
    "threadEngagementRatio": "minimum",
    "gearMinTeeth": "minimum",
    "sprocketMinTeeth": "minimum",
    "driveTorqueSafetyFactor": "minimum",
    "driveRmsUtilizationMax": "maximum",
    "driveInertiaRatioWarn": "maximum",
    "driveInertiaRatioMax": "maximum",
    "springIndexMin": "plain",
    "springIndexMax": "plain",
    "springIndexHardMin": "plain",
    "springIndexHardMax": "plain",
}

CUSTOM_RULE_FIELDS = {"id", "category", "severity", "appliesTo", "field", "operator", "value", "message"}
RULE_CATEGORIES = {"geometry", "holes", "standard_parts", "assembly", "drawing", "relations", "fastener", "drive", "custom"}
RULE_SEVERITIES = {"info", "minor", "warning", "major", "critical"}
RULE_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "ne"}
APPLIES_TO = {"hole", "feature", "standard_part", "document"}

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class DrcProfileError(ValueError):
    """@brief DRC Profile 校验错误。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DrcProfileError(message)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DrcProfileError(f"{field} 必须是数值")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise DrcProfileError(f"{field} 必须是有限数值")
    return number


def _validate_custom_rule(rule: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验单条声明式自定义规则。"""
    _require(isinstance(rule, Mapping), "customRules 每项必须是对象")
    unknown = set(rule) - CUSTOM_RULE_FIELDS
    _require(not unknown, f"自定义规则含未知字段: {', '.join(sorted(unknown))}")
    rule_id = str(rule.get("id") or "").strip()
    _require(bool(_IDENTIFIER.match(rule_id)), f"自定义规则 id 非法: {rule_id!r}")
    category = str(rule.get("category") or "custom")
    _require(category in RULE_CATEGORIES, f"未知规则类别: {category}")
    severity = str(rule.get("severity") or "warning")
    _require(severity in RULE_SEVERITIES, f"未知严重度: {severity}")
    applies_to = str(rule.get("appliesTo") or "document")
    _require(applies_to in APPLIES_TO, f"未知 appliesTo: {applies_to}")
    field = str(rule.get("field") or "").strip()
    _require(bool(field) and len(field) <= 64, "自定义规则 field 必须为非空短字符串")
    operator = str(rule.get("operator") or "").strip()
    _require(operator in RULE_OPERATORS, f"未知算子: {operator}")
    value = rule.get("value")
    _require(isinstance(value, (int, float, str)) and not isinstance(value, bool), "自定义规则 value 必须是数值或字符串")
    message = str(rule.get("message") or "").strip()
    _require(bool(message) and len(message) <= 300, "自定义规则 message 必须为非空短文本")
    return {
        "id": rule_id,
        "category": category,
        "severity": severity,
        "appliesTo": applies_to,
        "field": field,
        "operator": operator,
        "value": value,
        "message": message,
    }


def validate_profile(payload: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验一个 DRC Profile 并返回规范化副本。"""
    _require(isinstance(payload, Mapping), "Profile 必须是 JSON 对象")
    unknown = set(payload) - TOP_LEVEL_FIELDS
    _require(not unknown, f"Profile 含未知顶层字段: {', '.join(sorted(unknown))}")
    schema = str(payload.get("schema") or PROFILE_SCHEMA)
    _require(schema == PROFILE_SCHEMA, f"schema 必须为 {PROFILE_SCHEMA}")

    thresholds_in = payload.get("thresholds") or {}
    _require(isinstance(thresholds_in, Mapping), "thresholds 必须是对象")
    unknown_t = set(thresholds_in) - set(THRESHOLD_FIELDS)
    _require(not unknown_t, f"thresholds 含未知项: {', '.join(sorted(unknown_t))}")
    thresholds = {key: _number(value, key) for key, value in thresholds_in.items()}
    _require(all(value > 0 for value in thresholds.values()), "阈值必须大于零；要停用规则请显式设置 disabledRules")
    _require(thresholds.get("driveRmsUtilizationMax", 1.0) <= 1.0, "driveRmsUtilizationMax 不能大于 1")
    _require(thresholds.get("driveTorqueSafetyFactor", 1.0) >= 1.0, "driveTorqueSafetyFactor 不能小于 1")

    disabled_in = payload.get("disabledRules") or []
    _require(isinstance(disabled_in, (list, tuple)), "disabledRules 必须是数组")
    disabled = []
    for item in disabled_in:
        text = str(item).strip()
        _require(bool(_IDENTIFIER.match(text)), f"disabledRules 含非法规则 id: {text!r}")
        disabled.append(text)

    custom_in = payload.get("customRules") or []
    _require(isinstance(custom_in, (list, tuple)), "customRules 必须是数组")
    _require(len(custom_in) <= MAX_CUSTOM_RULES, f"自定义规则数量超过上限 {MAX_CUSTOM_RULES}")
    custom = [_validate_custom_rule(rule) for rule in custom_in]
    ids = [rule["id"] for rule in custom]
    _require(len(ids) == len(set(ids)), "自定义规则 id 不能重复")
    _require(not any(value.upper().startswith("DRC-") for value in ids), "自定义规则不能使用保留的 DRC- 前缀")

    return {
        "schema": PROFILE_SCHEMA,
        "version": str(payload.get("version") or PROFILE_VERSION),
        "id": str(payload.get("id") or "inline"),
        "description": str(payload.get("description") or ""),
        "thresholds": thresholds,
        "disabledRules": disabled,
        "customRules": custom,
    }


def load_profile(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """@brief 从路径或内联对象装载并校验一个 Profile。"""
    if isinstance(source, Mapping):
        return validate_profile(source)
    path = Path(source)
    _require(path.is_file(), f"Profile 文件不存在: {path}")
    _require(path.stat().st_size <= MAX_PROFILE_BYTES, "Profile 文件过大")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_profile(payload)


RULE_PACKS_DIR = Path(__file__).resolve().parents[1] / "profiles" / "drc"
_PACK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def list_rule_packs() -> list[dict[str, Any]]:
    """@brief 列出内置行业规则包（profiles/drc/*.json）。"""
    packs: list[dict[str, Any]] = []
    if not RULE_PACKS_DIR.is_dir():
        return packs
    for path in sorted(RULE_PACKS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        packs.append(
            {
                "name": path.stem,
                "id": str(payload.get("id") or path.stem),
                "description": str(payload.get("description") or ""),
                "thresholdKeys": sorted((payload.get("thresholds") or {}).keys()),
                "customRuleCount": len(payload.get("customRules") or []),
            }
        )
    return packs


def load_rule_pack(name: str) -> dict[str, Any]:
    """@brief 按名装载并校验一个行业规则包；名称受正则约束，防止路径穿越。"""
    safe = str(name).strip()
    _require(bool(_PACK_NAME.match(safe)), f"非法规则包名: {name!r}")
    path = RULE_PACKS_DIR / f"{safe}.json"
    _require(path.is_file(), f"规则包不存在: {safe}")
    return load_profile(path)


def merge_profiles(profiles: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """@brief 合并多个已校验 Profile。

    阈值按方向合并：minimum 取更大（更严），maximum 取更小（更严），plain 后者覆盖前者；
    disabledRules 取并集；customRules 按 id 去重后合并（后者覆盖同 id）。
    """
    thresholds: dict[str, float] = {}
    disabled: list[str] = []
    custom: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        validated = validate_profile(profile)
        for key, value in validated["thresholds"].items():
            direction = THRESHOLD_FIELDS.get(key, "plain")
            if key not in thresholds:
                thresholds[key] = value
            elif direction == "minimum":
                thresholds[key] = max(thresholds[key], value)
            elif direction == "maximum":
                thresholds[key] = min(thresholds[key], value)
            else:
                thresholds[key] = value
        for item in validated["disabledRules"]:
            if item not in disabled:
                disabled.append(item)
        for rule in validated["customRules"]:
            custom[rule["id"]] = rule
    return {
        "schema": PROFILE_SCHEMA,
        "version": PROFILE_VERSION,
        "id": "merged",
        "description": "",
        "thresholds": thresholds,
        "disabledRules": disabled,
        "customRules": list(custom.values()),
    }
