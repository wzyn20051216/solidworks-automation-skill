"""
@file design_audit.py
@brief 把 DRC 从一次性 linter 升级为可追溯门禁：finding 指纹、基线 diff、让步单(waiver)、风险评分。

设计规则检查（design_rule_check.py）产出的是一份 checks 报告；本模块提供围绕它的**审计工作流**，
全部纯函数、离线可单测：

- 指纹（fingerprint）：给每条 finding 一个稳定 id（规则+类别+目标），跨多次运行可追踪同一问题。
- 基线 diff：对比上一版报告，分出 new / fixed / persisting，让评审只看增量。
- 让步单（waiver）：带理由/责任人/有效期地豁免某条 finding；过期或不匹配的让步单不生效，
  并单列出来。被让步的 finding 退出门禁判定，但仍留痕。
- 风险评分：按严重度加权汇总未让步的 finding，给出分数与风险等级。

这些让「设计审计」从“报个错”变成“可复核、可签署、可回归”的过程。
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

ACTIONABLE_STATUSES = {"fail", "warning"}

DEFAULT_RISK_WEIGHTS = {"critical": 10.0, "major": 5.0, "warning": 2.0, "minor": 1.0, "info": 0.0}
RISK_BANDS = [(0.0, "none"), (1.0, "low"), (8.0, "medium"), (20.0, "high")]


def finding_fingerprint(check: Mapping[str, Any]) -> str:
    """@brief 由规则 id + 类别 + 目标生成稳定短指纹（不含易变的数值文字）。"""
    rule_id = str(check.get("id") or "")
    category = str(check.get("category") or "")
    target = str(check.get("target") or check.get("appliesTo") or "")
    field = str(check.get("field") or "")
    raw = "|".join([rule_id, category, target, field])
    return "F-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def attach_fingerprints(checks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """@brief 返回带 fingerprint 的 checks 副本。"""
    result = []
    for check in checks:
        item = dict(check)
        item["fingerprint"] = finding_fingerprint(check)
        result.append(item)
    return result


def _actionable(checks: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """@brief 取出 fail/warning 的 finding，按指纹索引（后者覆盖同指纹）。"""
    index: dict[str, dict[str, Any]] = {}
    for check in checks:
        if check.get("status") in ACTIONABLE_STATUSES:
            index[check.get("fingerprint") or finding_fingerprint(check)] = dict(check)
    return index


def diff_findings(
    baseline_checks: Sequence[Mapping[str, Any]],
    current_checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """@brief 对比基线与当前报告的可处理 finding，分出 new / fixed / persisting。"""
    baseline = _actionable(baseline_checks)
    current = _actionable(current_checks)
    new_ids = [fp for fp in current if fp not in baseline]
    fixed_ids = [fp for fp in baseline if fp not in current]
    persisting_ids = [fp for fp in current if fp in baseline]
    return {
        "new": [current[fp] for fp in new_ids],
        "fixed": [baseline[fp] for fp in fixed_ids],
        "persisting": [current[fp] for fp in persisting_ids],
        "counts": {"new": len(new_ids), "fixed": len(fixed_ids), "persisting": len(persisting_ids)},
    }


def _waiver_matches(check: Mapping[str, Any], waiver: Mapping[str, Any]) -> bool:
    """@brief 判断一条 finding 是否匹配某让步单。支持按 fingerprint 或 ruleId+target。"""
    fingerprint = check.get("fingerprint") or finding_fingerprint(check)
    if waiver.get("fingerprint"):
        return str(waiver["fingerprint"]) == fingerprint
    if waiver.get("ruleId"):
        if str(waiver["ruleId"]) != str(check.get("id")):
            return False
        if waiver.get("target") is not None:
            return str(waiver["target"]) == str(check.get("target") or "")
        return True
    return False


def _date_le(a: str | None, b: str | None) -> bool:
    """@brief ISO 日期字符串比较 a <= b；缺失视为不约束。"""
    if not a or not b:
        return True
    return str(a) <= str(b)


def validate_waiver(waiver: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 校验让步单必填项：匹配键、理由、责任人。"""
    if not isinstance(waiver, Mapping):
        raise ValueError("waiver 必须是对象")
    if not (waiver.get("fingerprint") or waiver.get("ruleId")):
        raise ValueError("waiver 必须提供 fingerprint 或 ruleId")
    if not str(waiver.get("reason") or "").strip():
        raise ValueError("waiver 必须提供 reason")
    if not str(waiver.get("owner") or "").strip():
        raise ValueError("waiver 必须提供 owner（责任人）")
    for key in ("createdOn", "expiresOn"):
        if waiver.get(key) is not None:
            try:
                value = waiver[key]
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError as exc:
                raise ValueError(f"waiver.{key} 必须是有效 YYYY-MM-DD 日期") from exc
    if waiver.get("createdOn") and waiver.get("expiresOn") and waiver["createdOn"] > waiver["expiresOn"]:
        raise ValueError("waiver 生效日期不能晚于到期日期")
    return {
        "fingerprint": waiver.get("fingerprint"),
        "ruleId": waiver.get("ruleId"),
        "target": waiver.get("target"),
        "reason": str(waiver["reason"]),
        "owner": str(waiver["owner"]),
        "expiresOn": waiver.get("expiresOn"),
        "createdOn": waiver.get("createdOn"),
    }


def apply_waivers(
    checks: Sequence[Mapping[str, Any]],
    waivers: Sequence[Mapping[str, Any]],
    *,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """@brief 对 checks 应用让步单：命中且未过期的 finding 打上 waived 标记并退出门禁。

    @return {"checks": 带 waived 标记的副本, "applied": [...], "expired": [...], "unused": [...]}。
    """
    if as_of_date is None:
        as_of_date = datetime.now(timezone.utc).date().isoformat()
    try:
        if not isinstance(as_of_date, str) or date.fromisoformat(as_of_date).isoformat() != as_of_date:
            raise ValueError
    except ValueError as exc:
        raise ValueError("as_of_date 必须是有效 YYYY-MM-DD 日期") from exc
    validated = [validate_waiver(w) for w in waivers]
    active, expired, not_yet_valid = [], [], []
    for waiver in validated:
        if waiver.get("createdOn") and not _date_le(waiver["createdOn"], as_of_date):
            not_yet_valid.append(waiver)
        elif waiver.get("expiresOn") and not _date_le(as_of_date, waiver["expiresOn"]):
            expired.append(waiver)
        else:
            active.append(waiver)

    used: set[int] = set()
    annotated: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    for check in checks:
        item = dict(check)
        if "fingerprint" not in item:
            item["fingerprint"] = finding_fingerprint(check)
        if check.get("status") in ACTIONABLE_STATUSES:
            for i, waiver in enumerate(active):
                if _waiver_matches(item, waiver):
                    item["waived"] = True
                    item["waiver"] = {"reason": waiver["reason"], "owner": waiver["owner"], "expiresOn": waiver.get("expiresOn")}
                    used.add(i)
                    applied.append({"fingerprint": item["fingerprint"], "id": item.get("id"), "owner": waiver["owner"], "reason": waiver["reason"]})
                    break
        annotated.append(item)
    unused = [waiver for i, waiver in enumerate(active) if i not in used]
    return {"checks": annotated, "applied": applied, "expired": expired, "notYetValid": not_yet_valid, "unused": unused}


def gated_status(checks: Sequence[Mapping[str, Any]]) -> str:
    """@brief 缺失证据或未执行的规则不能视为完整通过。"""
    statuses = {c.get("status") for c in checks if not c.get("waived")}
    if "fail" in statuses:
        return "fail"
    if "warning" in statuses:
        return "warning"
    if not statuses or "info" in statuses:
        return "review_required"
    return "pass"


def _band(score: float) -> str:
    label = "none"
    for threshold, name in RISK_BANDS:
        if score >= threshold:
            label = name
    return label


def risk_score(checks: Sequence[Mapping[str, Any]], *, weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """@brief 按严重度加权汇总未让步的 finding，给出分数、等级与分项。"""
    w = dict(DEFAULT_RISK_WEIGHTS)
    if weights:
        w.update({k: float(v) for k, v in weights.items()})
    by_severity: dict[str, int] = {}
    score = 0.0
    for check in checks:
        if check.get("waived") or check.get("status") not in ACTIONABLE_STATUSES:
            continue
        severity = str(check.get("severity") or "warning")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        score += w.get(severity, w.get("warning", 2.0))
    return {"score": round(score, 3), "band": _band(score), "weights": w, "bySeverity": by_severity}


def summarize_audit(
    checks: Sequence[Mapping[str, Any]],
    *,
    baseline_checks: Sequence[Mapping[str, Any]] | None = None,
    waivers: Sequence[Mapping[str, Any]] | None = None,
    as_of_date: str | None = None,
    risk_weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """@brief 一站式审计：指纹 -> 让步 -> 门禁状态 -> 风险评分 -> 基线 diff。

    @return {"checks": 处理后的 checks, "gatedStatus", "risk", "waivers", "diff"}。
    """
    fingered = attach_fingerprints(checks)
    waiver_result = apply_waivers(fingered, waivers or [], as_of_date=as_of_date)
    processed = waiver_result["checks"]
    audit: dict[str, Any] = {
        "checks": processed,
        "gatedStatus": gated_status(processed),
        "risk": risk_score(processed, weights=risk_weights),
        "waivers": {
            "applied": waiver_result["applied"],
            "expired": waiver_result["expired"],
            "notYetValid": waiver_result["notYetValid"],
            "unused": waiver_result["unused"],
        },
    }
    if baseline_checks is not None:
        audit["diff"] = diff_findings(baseline_checks, processed)
    return audit


def assert_no_regression(
    baseline_checks: Sequence[Mapping[str, Any]],
    candidate_checks: Sequence[Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
    tolerance: float = 0.0,
    block_new_severities: Sequence[str] = ("critical",),
) -> dict[str, Any]:
    """@brief 回归门禁：候选版本相对基线不得变差，否则拒绝。

    “变差”有两种，任一成立即拒绝：
    1. 未让步 finding 的加权风险分高于基线（超过 tolerance）；
    2. 出现了 block_new_severities（默认 critical）级别的**新增**未让步 finding——
       即使总分因别处改善而下降，也不能用一个新的致命问题去换分数。
    已让步(waived)的 finding 不计入。用于“修改/修复方案是否让设计更差”的把关，
    与 diff_findings / risk_score 共用同一套指纹与权重，所以结论可解释、可追溯。
    """
    baseline = attach_fingerprints(baseline_checks)
    candidate = attach_fingerprints(candidate_checks)
    base_risk = risk_score(baseline, weights=weights)
    cand_risk = risk_score(candidate, weights=weights)
    diff = diff_findings(baseline, candidate)
    delta = round(cand_risk["score"] - base_risk["score"], 6)

    blocked_new = [
        f for f in diff["new"]
        if not f.get("waived") and str(f.get("severity")) in set(block_new_severities)
    ]
    reasons: list[str] = []
    if delta > float(tolerance):
        reasons.append(f"风险分由 {base_risk['score']:g} 升至 {cand_risk['score']:g}（+{delta:g}，容差 {float(tolerance):g}）")
    for finding in blocked_new:
        reasons.append(f"新增 {finding.get('severity')} 级问题 {finding.get('id')}（{finding.get('target') or '-'}）：{finding.get('message', '')}")

    # 问题因缺失证据而消失时，不能把它当作修复。
    info_checks = [item for item in candidate if item.get("status") == "info"]
    uncertain = [finding for finding in diff["fixed"] if any(
        info.get("id") == finding.get("id") or
        (info.get("category") == finding.get("category") and
         str(info.get("id", "")).endswith(("-EVIDENCE", "-000")))
        for info in info_checks
    )]
    if uncertain:
        reasons.append("候选版本对应类别缺少证据，不能确认基线问题已修复")

    return {
        "passed": not reasons,
        "reasons": reasons,
        "baselineScore": base_risk["score"],
        "candidateScore": cand_risk["score"],
        "delta": delta,
        "tolerance": float(tolerance),
        "blockedNewSeverities": list(block_new_severities),
        "newCount": diff["counts"]["new"],
        "fixedCount": diff["counts"]["fixed"],
        "persistingCount": diff["counts"]["persisting"],
        "newBlocking": [{"id": f.get("id"), "target": f.get("target"), "severity": f.get("severity")} for f in blocked_new],
        "unverifiedFixed": [{"id": f.get("id"), "target": f.get("target")} for f in uncertain],
    }
