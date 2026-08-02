"""@brief NeutralCadDocument 的轻量 DFM 规则复核。

本模块只做可追溯的制造风险检查，不输出制造认证结论。即使所有机器规则通过，
顶层状态仍保持 review_required，由工程师对材料、工艺、公差和供应商能力做
最终确认。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .dfm_profiles import DfmProfileError, load_profiles, merge_profiles
except ImportError:  # pragma: no cover - 兼容直接执行 scripts/dfm_review.py
    from dfm_profiles import DfmProfileError, load_profiles, merge_profiles


DFM_PROCESSES = {"machining", "sheet_metal", "laser_cutting", "3d_printing"}
PROCESS_ALIASES = {
    "auto": "auto",
    "cnc": "machining",
    "machining": "machining",
    "machine": "machining",
    "milling": "machining",
    "sheet": "sheet_metal",
    "sheetmetal": "sheet_metal",
    "sheet_metal": "sheet_metal",
    "laser": "laser_cutting",
    "laser_cutting": "laser_cutting",
    "laser-cutting": "laser_cutting",
    "fdm": "3d_printing",
    "sla": "3d_printing",
    "sls": "3d_printing",
    "3dp": "3d_printing",
    "3d_printing": "3d_printing",
    "3d-printing": "3d_printing",
}
UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4, "in": 25.4}
FEATURE_LENGTH_FIELDS = {"length", "width", "height", "x", "y", "z", "radius", "diameter", "depth"}
MANUFACTURING_LENGTH_FIELDS = {
    "wallThickness",
    "minimumWallThickness",
    "minimumDrillDiameter",
    "internalCornerRadius",
    "bendRadius",
    "kerf",
}


def _now_iso() -> str:
    """@brief 返回 UTC 秒级时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    """@brief 计算文件 SHA-256。"""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versioned_target(path: Path) -> Path:
    """@brief 返回不会覆盖既有文件的版本化输出路径。"""
    target = Path(path)
    if not target.exists():
        return target
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem}_v{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _load_document(path: Path) -> dict[str, Any]:
    """@brief 读取并做 NeutralCadDocument 最小结构校验。"""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("NeutralCadDocument 必须是 JSON object。")
    if not str(document.get("documentId") or "").strip():
        raise ValueError("NeutralCadDocument 缺少 documentId。")
    features = document.get("features", [])
    if not isinstance(features, list):
        raise ValueError("NeutralCadDocument.features 必须是数组。")
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("NeutralCadDocument.features 只能包含 object。")
        if not str(feature.get("id") or "").strip() or not str(feature.get("type") or "").strip():
            raise ValueError("每个 feature 必须包含非空 id 和 type。")
    return document


def _document_to_mm(document: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """@brief 将 DFM 涉及的 NeutralCadDocument 长度字段规范化为毫米。"""
    source_units = str(document.get("units") or "mm").strip().lower()
    if source_units not in UNIT_TO_MM:
        raise ValueError(f"DFM 不支持单位 {source_units}。")
    normalized = copy.deepcopy(document)
    geometry_factor = UNIT_TO_MM[source_units]
    for feature in normalized.get("features", []):
        params = feature.get("parameters") if isinstance(feature, dict) else None
        if not isinstance(params, dict):
            continue
        for key in FEATURE_LENGTH_FIELDS:
            if key in params and isinstance(params[key], (int, float)) and not isinstance(params[key], bool):
                params[key] = float(params[key]) * geometry_factor

    metadata = normalized.get("metadata") if isinstance(normalized.get("metadata"), dict) else {}
    manufacturing = metadata.get("manufacturing") if isinstance(metadata.get("manufacturing"), dict) else {}
    manufacturing_units = str(manufacturing.get("unit") or source_units).strip().lower()
    if manufacturing_units not in UNIT_TO_MM:
        raise ValueError(f"DFM 不支持制造元数据单位 {manufacturing_units}。")
    manufacturing_factor = UNIT_TO_MM[manufacturing_units]
    for key in MANUFACTURING_LENGTH_FIELDS:
        if key in manufacturing and isinstance(manufacturing[key], (int, float)) and not isinstance(manufacturing[key], bool):
            manufacturing[key] = float(manufacturing[key]) * manufacturing_factor
    if isinstance(manufacturing.get("buildVolume"), (list, tuple)):
        manufacturing["buildVolume"] = [
            float(item) * manufacturing_factor if isinstance(item, (int, float)) and not isinstance(item, bool) else item
            for item in manufacturing["buildVolume"]
        ]
    manufacturing["unit"] = "mm"
    normalized["units"] = "mm"
    return normalized, source_units


def _manufacturing(document: dict[str, Any]) -> dict[str, Any]:
    """@brief 提取制造元数据。"""
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    value = metadata.get("manufacturing") if isinstance(metadata.get("manufacturing"), dict) else {}
    return dict(value)


def _normalize_process(value: Any) -> str:
    """@brief 将 UI、Skill 和 CLI 的工艺名称归一到 DFM 白名单。"""
    token = str(value or "auto").strip().lower().replace(" ", "_")
    return PROCESS_ALIASES.get(token, token)


def _number(value: Any) -> float | None:
    """@brief 安全读取浮点数。"""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _sequence_numbers(value: Any) -> list[float] | None:
    """@brief 安全读取数字数组。"""
    if not isinstance(value, (list, tuple)):
        return None
    numbers = [_number(item) for item in value]
    if any(item is None for item in numbers):
        return None
    return [float(item) for item in numbers if item is not None]


def _material(document: dict[str, Any], manufacturing: dict[str, Any]) -> str:
    """@brief 从制造元数据或材料表中提取材料名称。"""
    direct = str(manufacturing.get("material") or "").strip()
    if direct and direct.lower() != "auto":
        return direct
    materials = document.get("materials")
    if isinstance(materials, list) and materials:
        first = materials[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("material") or "").strip()
        return str(first).strip()
    return ""


def _feature_params(feature: dict[str, Any]) -> dict[str, Any]:
    """@brief 返回特征参数 object。"""
    return feature.get("parameters") if isinstance(feature.get("parameters"), dict) else {}


def _box_bounds(params: dict[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    """@brief 根据 box 参数估算包围盒。"""
    length = _number(params.get("length"))
    width = _number(params.get("width"))
    height = _number(params.get("height"))
    if length is None or width is None or height is None:
        return None
    x = float(params.get("x", 0) or 0)
    y = float(params.get("y", 0) or 0)
    z = float(params.get("z", 0) or 0)
    return (x - length / 2, y - width / 2, z - height / 2, x + length / 2, y + width / 2, z + height / 2)


def _cylinder_bounds(params: dict[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    """@brief 根据 cylinder/hole 参数估算包围盒。"""
    radius = _number(params.get("radius"))
    diameter = _number(params.get("diameter"))
    radius = radius or (diameter / 2 if diameter else None)
    height = _number(params.get("height")) or _number(params.get("depth")) or 1.0
    if radius is None:
        return None
    x = float(params.get("x", 0) or 0)
    y = float(params.get("y", 0) or 0)
    z = float(params.get("z", 0) or 0)
    return (x - radius, y - radius, z - height / 2, x + radius, y + radius, z + height / 2)


def _bounds(document: dict[str, Any], brep_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """@brief 优先使用已验证 B-Rep 证据，否则从基础特征估算包络尺寸。"""
    if brep_evidence and brep_evidence.get("available") and brep_evidence.get("size"):
        return {
            "available": True,
            "size": list(brep_evidence["size"]),
            "source": "brep_evidence",
            "backend": brep_evidence.get("backend"),
            "evidenceSha256": brep_evidence.get("sha256"),
        }
    boxes: list[tuple[float, float, float, float, float, float]] = []
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        kind = str(feature.get("type") or "").lower()
        params = _feature_params(feature)
        box = _box_bounds(params) if kind == "box" else _cylinder_bounds(params) if kind in {"cylinder", "hole"} else None
        if box:
            boxes.append(box)
    if not boxes:
        return {"available": False, "size": [], "source": "neutral_parameters"}
    min_x = min(item[0] for item in boxes)
    min_y = min(item[1] for item in boxes)
    min_z = min(item[2] for item in boxes)
    max_x = max(item[3] for item in boxes)
    max_y = max(item[4] for item in boxes)
    max_z = max(item[5] for item in boxes)
    return {
        "available": True,
        "min": [min_x, min_y, min_z],
        "max": [max_x, max_y, max_z],
        "size": [max_x - min_x, max_y - min_y, max_z - min_z],
        "source": "neutral_parameters",
    }


def _canonical_sha256(payload: dict[str, Any]) -> str:
    """@brief 对内存证据计算稳定 SHA-256。"""
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _brep_size(payload: dict[str, Any]) -> list[float] | None:
    """@brief 从 SolidWorks 或 OCCT B-Rep 证据提取毫米包络。"""
    envelope = payload.get("envelope_mm")
    if isinstance(envelope, dict):
        values = [_number(envelope.get(key)) for key in ("length", "width", "height")]
        if all(value is not None for value in values):
            return [float(value) for value in values if value is not None]
    bounds = payload.get("bounds")
    if isinstance(bounds, dict):
        size = _sequence_numbers(bounds.get("size"))
        if size and len(size) == 3:
            return size
        minimum = bounds.get("min")
        maximum = bounds.get("max")
        if isinstance(minimum, list) and isinstance(maximum, list) and len(minimum) == len(maximum) == 3:
            try:
                result = [float(maximum[index]) - float(minimum[index]) for index in range(3)]
            except (TypeError, ValueError):
                return None
            if all(value > 0 for value in result):
                return result
    return None


def _load_brep_evidence(
    value: str | Path | dict[str, Any] | None,
    *,
    allowed_root: Path,
) -> dict[str, Any]:
    """@brief 装载并验证 B-Rep 证据来源，不把普通参数声明冒充几何测量。"""
    if value is None:
        return {"available": False, "verifiedSource": False, "reason": "未提供 B-Rep 证据。"}
    evidence_path: Path | None = None
    if isinstance(value, dict):
        payload = dict(value)
    else:
        raw = Path(value).expanduser()
        if not raw.is_absolute():
            evidence_path = (allowed_root / raw).resolve()
            try:
                evidence_path.relative_to(allowed_root.resolve())
            except ValueError as exc:
                raise ValueError("相对 B-Rep 证据路径逃逸模型目录，已拒绝。") from exc
        else:
            evidence_path = raw.resolve()
        if evidence_path.suffix.lower() != ".json" or not evidence_path.is_file():
            raise ValueError("B-Rep 证据必须是存在的 JSON 文件。")
        if evidence_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("B-Rep 证据超过 4 MiB 安全上限。")
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("B-Rep 证据必须是 JSON object。")

    backend = str(payload.get("backend") or "")
    evidence = payload.get("measurements") if isinstance(payload.get("measurements"), dict) else None
    if backend == "solidworks_brep":
        if not evidence:
            raise ValueError("SolidWorks B-Rep 证据必须包含 measurements。")
        if str(evidence.get("units") or "").lower() != "mm":
            raise ValueError("SolidWorks B-Rep measurements 必须明确声明 units=mm。")
        measurement_source = str(evidence.get("measurement_source") or "")
        if "solidworks api" not in measurement_source.lower() or "b-rep" not in measurement_source.lower():
            raise ValueError("SolidWorks B-Rep measurements 缺少受认可的 API 测量来源。")
        allowed_extensions = {".sldprt"}
    elif backend == "headless_occt":
        evidence = payload.get("geometryEvidence") if isinstance(payload.get("geometryEvidence"), dict) else None
        if not evidence:
            raise ValueError("OCCT B-Rep 证据必须包含 geometryEvidence。")
        if str(payload.get("units") or evidence.get("units") or "").lower() != "mm":
            raise ValueError("OCCT B-Rep 证据必须明确声明 units=mm。")
        measurement_source = "OCCT B-Rep topology"
        allowed_extensions = {".brep", ".step", ".stp"}
    else:
        raise ValueError("B-Rep 证据后端未经认可；不得把普通参数或手工 JSON 标记为 SolidWorks B-Rep。")
    if payload.get("producedThisRun") is not True:
        raise ValueError("B-Rep 证据未标记 producedThisRun=true，不能用于本轮制造判断。")
    artifact_raw = payload.get("sourceArtifact")
    if not str(artifact_raw or "").strip():
        raise ValueError("B-Rep 证据缺少 sourceArtifact。")
    artifact_path = Path(str(artifact_raw)).expanduser()
    if not artifact_path.is_absolute():
        artifact_path = (allowed_root / artifact_path).resolve()
        try:
            artifact_path.relative_to(allowed_root.resolve())
        except ValueError as exc:
            raise ValueError("B-Rep sourceArtifact 路径逃逸模型目录，已拒绝。") from exc
    else:
        artifact_path = artifact_path.resolve()
    if artifact_path.suffix.lower() not in allowed_extensions or not artifact_path.is_file():
        raise ValueError("B-Rep sourceArtifact 不存在或格式与后端不匹配。")
    expected_artifact_hash = str(payload.get("sourceSha256") or "").lower()
    actual_artifact_hash = _sha256_file(artifact_path)
    if len(expected_artifact_hash) != 64 or expected_artifact_hash != actual_artifact_hash:
        raise ValueError("B-Rep sourceArtifact SHA-256 不匹配，证据已失去绑定。")
    size = _brep_size(evidence)
    topology = evidence.get("topology") if isinstance(evidence.get("topology"), dict) else {}
    if size is None:
        raise ValueError("B-Rep 证据缺少有效的三轴包络。")
    if backend == "headless_occt" and int(topology.get("solids") or 0) < 1:
        raise ValueError("OCCT B-Rep 证据未证明存在实体。")
    sha256 = _sha256_file(evidence_path) if evidence_path else _canonical_sha256(payload)
    return {
        "available": True,
        "verifiedSource": True,
        "backend": backend,
        "measurementSource": measurement_source or "OCCT B-Rep topology",
        "size": size,
        "sha256": sha256,
        "sourceArtifact": str(artifact_path),
        "sourceSha256": actual_artifact_hash,
        "producedThisRun": True,
        "path": str(evidence_path) if evidence_path else None,
        "topology": topology,
        "errors": evidence.get("errors") if isinstance(evidence.get("errors"), list) else [],
    }


def _hole_diameters(document: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 提取孔类特征直径证据。"""
    holes: list[dict[str, Any]] = []
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        if str(feature.get("type") or "").lower() != "hole":
            continue
        params = _feature_params(feature)
        diameter = _number(params.get("diameter"))
        if diameter is None and _number(params.get("radius")) is not None:
            diameter = float(_number(params.get("radius")) or 0) * 2
        if diameter is not None:
            holes.append({"id": str(feature.get("id")), "diameter": diameter, "x": params.get("x"), "y": params.get("y")})
    return holes


def _check(check_id: str, status: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    """@brief 构造稳定检查项。"""
    payload: dict[str, Any] = {"id": check_id, "status": status, "severity": severity, "message": message}
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def _critical_missing(document: dict[str, Any], manufacturing: dict[str, Any], process: str) -> list[str]:
    """@brief 返回特定工艺缺失的关键输入。"""
    missing: list[str] = []
    if not _material(document, manufacturing):
        missing.append("metadata.manufacturing.material")
    if process in {"machining", "sheet_metal", "laser_cutting", "3d_printing"} and _number(manufacturing.get("wallThickness")) is None:
        missing.append("metadata.manufacturing.wallThickness")
    if process == "sheet_metal":
        if _number(manufacturing.get("bendRadius")) is None:
            missing.append("metadata.manufacturing.bendRadius")
        if _number(manufacturing.get("kFactor")) is None:
            missing.append("metadata.manufacturing.kFactor")
    if process == "laser_cutting" and _number(manufacturing.get("kerf")) is None:
        missing.append("metadata.manufacturing.kerf")
    if process == "3d_printing" and _sequence_numbers(manufacturing.get("buildVolume")) is None:
        missing.append("metadata.manufacturing.buildVolume")
    return missing


def _common_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    brep_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """@brief 所有工艺共用的材料、包络和孔径证据检查。"""
    material = _material(document, manufacturing)
    bounds = _bounds(document, brep_evidence)
    checks = [
        _check(
            "material_declared",
            "pass" if material else "fail",
            "critical",
            f"材料已声明: {material}" if material else "缺少材料，不能进行制造风险判断。",
            material=material or None,
        ),
        _check(
            "bounds_available",
            "pass" if bounds.get("available") else "warning",
            "medium",
            "已提取基础包络尺寸。" if bounds.get("available") else "未能从基础特征估算包络尺寸。",
            bounds=bounds,
        ),
    ]
    holes = _hole_diameters(document)
    if holes:
        min_hole = min(item["diameter"] for item in holes)
        checks.append(
            _check(
                "hole_diameter_inventory",
                "pass",
                "medium",
                f"已识别 {len(holes)} 个孔类特征，最小孔径 {min_hole:g} mm。",
                holes=holes,
            )
        )
    else:
        checks.append(_check("hole_diameter_inventory", "warning", "low", "未识别孔类特征；如零件含孔槽，应补齐规格和定位证据。"))
    return checks


def _machining_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    brep_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """@brief CNC/机加工基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing, brep_evidence)
    wall = _number(manufacturing.get("wallThickness"))
    min_wall = _number(manufacturing.get("minimumWallThickness")) or 1.5
    checks.append(
        _check(
            "machining_min_wall",
            "pass" if wall is not None and wall >= min_wall else "fail",
            "high",
            f"最小壁厚/筋厚 {wall:g} mm，大于建议阈值 {min_wall:g} mm。" if wall is not None and wall >= min_wall else f"机加工壁厚低于建议阈值 {min_wall:g} mm 或缺失。",
            wallThickness=wall,
            minimumWallThickness=min_wall,
        )
    )
    min_drill = _number(manufacturing.get("minimumDrillDiameter")) or 2.0
    small_holes = [item for item in _hole_diameters(document) if item["diameter"] < min_drill]
    checks.append(
        _check(
            "machining_min_drill",
            "warning" if small_holes else "pass",
            "medium",
            f"{len(small_holes)} 个孔径低于建议最小钻孔 {min_drill:g} mm。" if small_holes else f"孔径未低于建议最小钻孔 {min_drill:g} mm。",
            minimumDrillDiameter=min_drill,
            smallHoles=small_holes or None,
        )
    )
    if _number(manufacturing.get("internalCornerRadius")) is None:
        checks.append(_check("machining_internal_corner_radius", "warning", "medium", "未声明内角半径/刀具半径，方形内角可能无法按模型直接加工。"))
    else:
        checks.append(_check("machining_internal_corner_radius", "pass", "medium", "已声明内角半径/刀具半径。", internalCornerRadius=_number(manufacturing.get("internalCornerRadius"))))
    return checks


def _sheet_metal_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    brep_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """@brief 钣金基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing, brep_evidence)
    thickness = _number(manufacturing.get("wallThickness"))
    bend = _number(manufacturing.get("bendRadius"))
    k_factor = _number(manufacturing.get("kFactor"))
    checks.append(
        _check(
            "sheet_bend_radius",
            "pass" if thickness is not None and bend is not None and bend >= thickness * 0.8 else "warning",
            "high",
            "折弯内半径与板厚比例在常见可制造范围内。" if thickness is not None and bend is not None and bend >= thickness * 0.8 else "折弯内半径小于 0.8 倍板厚或缺失，需要确认材料和折弯模具。",
            wallThickness=thickness,
            bendRadius=bend,
        )
    )
    checks.append(
        _check(
            "sheet_k_factor",
            "pass" if k_factor is not None and 0.2 <= k_factor <= 0.55 else "fail",
            "critical",
            "K 因子处于常见展开计算范围。" if k_factor is not None and 0.2 <= k_factor <= 0.55 else "K 因子缺失或超出常见范围，展开长度不可复核。",
            kFactor=k_factor,
        )
    )
    min_hole = max(float(thickness or 0), 1.0)
    small_holes = [item for item in _hole_diameters(document) if item["diameter"] < min_hole]
    checks.append(
        _check(
            "sheet_hole_vs_thickness",
            "warning" if small_holes else "pass",
            "medium",
            f"{len(small_holes)} 个孔径小于板厚/1mm 建议值。" if small_holes else "孔径未小于板厚/1mm 建议值。",
            smallHoles=small_holes or None,
        )
    )
    return checks


def _laser_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    brep_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """@brief 激光切割基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing, brep_evidence)
    thickness = _number(manufacturing.get("wallThickness"))
    kerf = _number(manufacturing.get("kerf"))
    checks.append(
        _check(
            "laser_kerf_declared",
            "pass" if kerf is not None and kerf > 0 else "fail",
            "critical",
            f"已声明割缝 {kerf:g} mm。" if kerf else "缺少割缝 kerf，无法复核孔槽补偿。",
            kerf=kerf,
        )
    )
    if thickness is not None and kerf is not None:
        checks.append(
            _check(
                "laser_kerf_ratio",
                "warning" if kerf > thickness * 0.35 else "pass",
                "medium",
                "割缝相对板厚偏大，需要确认机台参数。" if kerf > thickness * 0.35 else "割缝相对板厚处于可复核范围。",
                wallThickness=thickness,
                kerf=kerf,
            )
        )
    min_slot = max(float(thickness or 0), float(kerf or 0) * 3, 1.0)
    small_holes = [item for item in _hole_diameters(document) if item["diameter"] < min_slot]
    checks.append(
        _check(
            "laser_min_hole_slot",
            "warning" if small_holes else "pass",
            "medium",
            f"{len(small_holes)} 个孔/槽特征低于建议最小值 {min_slot:g} mm。" if small_holes else f"孔/槽特征未低于建议最小值 {min_slot:g} mm。",
            minimumHoleOrSlot=min_slot,
            smallHoles=small_holes or None,
        )
    )
    return checks


def _printing_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    brep_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """@brief 3D 打印基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing, brep_evidence)
    wall = _number(manufacturing.get("wallThickness"))
    sub_process = str(manufacturing.get("subProcess") or manufacturing.get("process") or "").strip().lower()
    recommended_wall = _number(manufacturing.get("minimumWallThickness")) or (0.8 if sub_process == "sla" else 1.2)
    checks.append(
        _check(
            "printing_min_wall",
            "pass" if wall is not None and wall >= recommended_wall else "warning",
            "high",
            f"壁厚 {wall:g} mm 满足当前默认建议 {recommended_wall:g} mm。" if wall is not None and wall >= recommended_wall else f"壁厚低于当前默认建议 {recommended_wall:g} mm 或缺失。",
            wallThickness=wall,
            minimumWallThickness=recommended_wall,
        )
    )
    build = _sequence_numbers(manufacturing.get("buildVolume"))
    bounds = _bounds(document, brep_evidence)
    if build and bounds.get("available"):
        size = [float(item) for item in bounds.get("size", [])]
        fits = len(size) == 3 and all(size[index] <= build[index] for index in range(3))
        checks.append(
            _check(
                "printing_build_volume",
                "pass" if fits else "fail",
                "critical",
                "模型包络位于打印机成型空间内。" if fits else "模型包络超出打印机成型空间。",
                modelSize=size,
                buildVolume=build,
            )
        )
    else:
        checks.append(_check("printing_build_volume", "fail", "critical", "缺少成型空间或模型包络，无法判断是否可打印。", buildVolume=build, bounds=bounds))
    overhang = _number(manufacturing.get("maxUnsupportedOverhangDeg"))
    if overhang is None:
        checks.append(_check("printing_overhang", "warning", "medium", "未声明悬垂角/支撑策略，需要人工检查打印方向和支撑。"))
    else:
        checks.append(_check("printing_overhang", "warning" if overhang > 45 else "pass", "medium", "悬垂角超过 45°，通常需要支撑。" if overhang > 45 else "悬垂角处于常见免支撑范围。", maxUnsupportedOverhangDeg=overhang))
    return checks


def _fits_envelope(size: list[float], capacity: list[float]) -> bool:
    """@brief 判断三轴尺寸在允许旋转工件方向后是否能装入能力空间。"""
    return all(model <= machine for model, machine in zip(sorted(size), sorted(capacity)))


def _profile_checks(
    document: dict[str, Any],
    manufacturing: dict[str, Any],
    process: str,
    limits: dict[str, Any],
    brep_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """@brief 根据安全合并后的供应商、材料和设备能力生成违反项。"""
    checks: list[dict[str, Any]] = []
    material = _material(document, manufacturing)
    allowed = limits.get("allowedMaterials")
    if isinstance(allowed, list):
        compatible = material.casefold() in {str(item).casefold() for item in allowed}
        checks.append(
            _check(
                "profile_material_capability",
                "pass" if compatible else "fail",
                "critical",
                "材料在 Profile 能力范围内。" if compatible else f"供应商/设备 Profile 不支持材料 {material}。",
                material=material,
                allowedMaterials=allowed,
            )
        )

    bounds = _bounds(document, brep_evidence)
    envelope_key = {
        "machining": "workEnvelope",
        "sheet_metal": "formingEnvelope",
        "laser_cutting": "workEnvelope",
        "3d_printing": "buildVolume",
    }[process]
    capacity = limits.get(envelope_key) or limits.get("maximumEnvelope")
    if isinstance(capacity, list):
        size = bounds.get("size") if bounds.get("available") else []
        fits = len(size) == 3 and _fits_envelope([float(item) for item in size], capacity)
        checks.append(
            _check(
                "profile_equipment_envelope",
                "pass" if fits else "fail",
                "critical",
                "模型包络位于设备能力空间内。" if fits else "模型包络超出供应商/设备能力空间，或缺少可核验包络。",
                modelSize=size,
                equipmentEnvelope=capacity,
                evidenceSource=bounds.get("source"),
            )
        )

    wall = _number(manufacturing.get("wallThickness"))
    minimum_wall = limits.get("minimumWallThickness")
    if minimum_wall is not None:
        passed = wall is not None and wall >= minimum_wall
        checks.append(
            _check(
                "profile_minimum_wall",
                "pass" if passed else "fail",
                "high",
                "壁厚满足 Profile 最小值。" if passed else "壁厚低于供应商/工艺 Profile 最小值。",
                wallThickness=wall,
                minimumWallThickness=minimum_wall,
            )
        )

    thickness = wall
    minimum_thickness = limits.get("minimumThickness")
    maximum_thickness = limits.get("maximumThickness")
    if minimum_thickness is not None or maximum_thickness is not None:
        passed = thickness is not None
        if minimum_thickness is not None:
            passed = passed and thickness >= minimum_thickness
        if maximum_thickness is not None:
            passed = passed and thickness <= maximum_thickness
        checks.append(
            _check(
                "profile_material_thickness",
                "pass" if passed else "fail",
                "critical",
                "材料厚度位于 Profile 范围内。" if passed else "材料厚度超出供应商/设备 Profile 范围。",
                wallThickness=thickness,
                minimumThickness=minimum_thickness,
                maximumThickness=maximum_thickness,
            )
        )

    if process == "machining":
        holes = _hole_diameters(document)
        minimum_drill = limits.get("minimumDrillDiameter")
        if minimum_drill is not None:
            violations = [hole for hole in holes if hole["diameter"] < minimum_drill]
            checks.append(
                _check(
                    "profile_minimum_drill",
                    "fail" if violations else "pass",
                    "high",
                    f"{len(violations)} 个孔小于 Profile 最小钻孔直径。" if violations else "孔径满足 Profile 最小钻孔直径。",
                    minimumDrillDiameter=minimum_drill,
                    violations=violations or None,
                )
            )
        tools = limits.get("availableToolDiameters")
        if isinstance(tools, list) and holes:
            unavailable = [hole for hole in holes if not any(abs(hole["diameter"] - tool) <= 0.05 for tool in tools)]
            checks.append(
                _check(
                    "profile_tool_inventory",
                    "fail" if unavailable else "pass",
                    "high",
                    f"{len(unavailable)} 个孔没有匹配的钻具（直径容差 0.05 mm）。" if unavailable else "孔径均有匹配钻具。",
                    availableToolDiameters=tools,
                    violations=unavailable or None,
                )
            )
        minimum_corner = limits.get("minimumInternalCornerRadius")
        if minimum_corner is not None:
            actual_corner = _number(manufacturing.get("internalCornerRadius"))
            passed = actual_corner is not None and actual_corner >= minimum_corner
            checks.append(
                _check(
                    "profile_internal_corner_tooling",
                    "pass" if passed else "fail",
                    "high",
                    "内角半径适配可用刀具。" if passed else "内角半径小于 Profile 刀具能力或未声明。",
                    internalCornerRadius=actual_corner,
                    minimumInternalCornerRadius=minimum_corner,
                )
            )
        max_ratio = limits.get("maximumHoleDepthDiameterRatio")
        if max_ratio is not None:
            deep_holes: list[dict[str, Any]] = []
            for feature in document.get("features", []):
                if not isinstance(feature, dict) or str(feature.get("type") or "").lower() != "hole":
                    continue
                params = _feature_params(feature)
                diameter = _number(params.get("diameter")) or ((_number(params.get("radius")) or 0) * 2)
                depth = _number(params.get("depth")) or _number(params.get("height"))
                if diameter and depth and depth / diameter > max_ratio:
                    deep_holes.append({"id": feature.get("id"), "ratio": depth / diameter})
            checks.append(
                _check(
                    "profile_hole_depth_ratio",
                    "fail" if deep_holes else "pass",
                    "high",
                    "深径比满足刀具能力。" if not deep_holes else f"{len(deep_holes)} 个孔超出最大深径比。",
                    maximumHoleDepthDiameterRatio=max_ratio,
                    violations=deep_holes or None,
                )
            )

    if process == "sheet_metal":
        bend = _number(manufacturing.get("bendRadius"))
        minimum_bend = limits.get("minimumBendRadius")
        minimum_ratio = limits.get("minimumBendRadiusRatio")
        passed = True
        if minimum_bend is not None:
            passed = bend is not None and bend >= minimum_bend
        if minimum_ratio is not None:
            passed = passed and bend is not None and thickness is not None and bend >= thickness * minimum_ratio
        if minimum_bend is not None or minimum_ratio is not None:
            checks.append(
                _check(
                    "profile_bending_capability",
                    "pass" if passed else "fail",
                    "critical",
                    "折弯半径满足模具 Profile。" if passed else "折弯半径不满足供应商模具能力。",
                    bendRadius=bend,
                    minimumBendRadius=minimum_bend,
                    minimumBendRadiusRatio=minimum_ratio,
                )
            )

    if process == "laser_cutting":
        kerf = _number(manufacturing.get("kerf"))
        lower = limits.get("minimumKerf")
        upper = limits.get("maximumKerf")
        minimum_feature = limits.get("minimumHoleOrSlot")
        if lower is not None or upper is not None:
            passed = kerf is not None and (lower is None or kerf >= lower) and (upper is None or kerf <= upper)
            checks.append(
                _check(
                    "profile_laser_kerf",
                    "pass" if passed else "fail",
                    "high",
                    "割缝位于机台 Profile 范围内。" if passed else "割缝超出机台 Profile 范围。",
                    kerf=kerf,
                    minimumKerf=lower,
                    maximumKerf=upper,
                )
            )
        if minimum_feature is not None:
            violations = [hole for hole in _hole_diameters(document) if hole["diameter"] < minimum_feature]
            checks.append(
                _check(
                    "profile_laser_minimum_feature",
                    "fail" if violations else "pass",
                    "high",
                    "孔槽尺寸满足激光工艺 Profile。" if not violations else f"{len(violations)} 个孔槽小于供应商能力。",
                    minimumHoleOrSlot=minimum_feature,
                    violations=violations or None,
                )
            )

    if process == "3d_printing" and limits.get("maximumUnsupportedOverhangDeg") is not None:
        overhang = _number(manufacturing.get("maxUnsupportedOverhangDeg"))
        maximum = limits["maximumUnsupportedOverhangDeg"]
        passed = overhang is not None and overhang <= maximum
        checks.append(
            _check(
                "profile_printing_overhang",
                "pass" if passed else "fail",
                "high",
                "悬垂角满足打印机/材料 Profile。" if passed else "悬垂角超出打印机/材料 Profile 或未声明。",
                maxUnsupportedOverhangDeg=overhang,
                profileMaximumOverhangDeg=maximum,
            )
        )
    return checks


def build_dfm_report(
    document_path: str | Path,
    *,
    process: str | None = None,
    profiles: list[str | Path | dict[str, Any]] | None = None,
    brep_evidence: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """@brief 生成不依赖 CAD 软件的 DFM 复核报告。

    @param profiles 可选材料、设备或供应商能力 Profile；按能力交集合并。
    @param brep_evidence 可选 SolidWorks/OCCT B-Rep 测量证据或其 JSON 路径。
    """
    source = Path(document_path).expanduser().resolve()
    try:
        document, source_units = _document_to_mm(_load_document(source))
    except Exception as exc:
        return {
            "schemaVersion": "1.0",
            "status": "failed",
            "stage": "dfm_review",
            "process": _normalize_process(process),
            "checks": [],
            "missingInputs": [],
            "artifacts": [],
            "manualReviewRequired": True,
            "manual_review_required": True,
            "retryable": False,
            "error_code": "invalid_neutral_document",
            "message": str(exc),
            "generatedAt": _now_iso(),
            "sourceDocument": str(source),
            "producedThisRun": True,
        }

    manufacturing = _manufacturing(document)
    raw_process = process if process and _normalize_process(process) != "auto" else manufacturing.get("process")
    normalized_process = _normalize_process(raw_process)
    if normalized_process == "auto":
        normalized_process = ""
    report: dict[str, Any] = {
        "schemaVersion": "1.0",
        "status": "review_required",
        "stage": "dfm_review",
        "process": normalized_process,
        "checks": [],
        "missingInputs": [],
        "artifacts": [],
        "manualReviewRequired": True,
        "manual_review_required": True,
        "retryable": False,
        "error_code": None,
        "limitations": [
            "DFM 规则检查不等于制造认证，必须由工程师结合供应商能力、材料批次、公差和载荷复核。",
        ],
        "profiles": [],
        "effectiveProfileLimits": {},
        "profileViolations": [],
        "brepEvidence": {"available": False, "verifiedSource": False},
        "generatedAt": _now_iso(),
        "sourceDocument": str(source),
        "sourceSha256": _sha256_file(source) if source.is_file() else "",
        "documentId": document.get("documentId"),
        "units": "mm",
        "sourceUnits": source_units,
        "producedThisRun": True,
    }
    if normalized_process not in DFM_PROCESSES:
        report.update(
            {
                "status": "blocked",
                "process": normalized_process or "unknown",
                "missingInputs": ["metadata.manufacturing.process"],
                "error_code": "dfm_unknown_process",
                "checks": [
                    _check(
                        "dfm_process_selected",
                        "fail",
                        "critical",
                        "未指定受支持的制造工艺；可选 machining、sheet_metal、laser_cutting、3d_printing。",
                    )
                ],
            }
        )
        return report

    try:
        loaded_profiles = load_profiles(profiles, allowed_root=source.parent)
        effective_limits, profile_records = merge_profiles(loaded_profiles, normalized_process)
    except DfmProfileError as exc:
        report.update(
            {
                "status": "blocked",
                "error_code": "dfm_invalid_profile",
                "checks": [_check("dfm_profile_validation", "fail", "critical", str(exc))],
                "limitations": report["limitations"] + ["无效 Profile 未参与 DFM 判断。"],
            }
        )
        return report
    report["profiles"] = profile_records
    report["effectiveProfileLimits"] = effective_limits

    try:
        brep = _load_brep_evidence(brep_evidence, allowed_root=source.parent)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report.update(
            {
                "status": "blocked",
                "error_code": "dfm_invalid_brep_evidence",
                "checks": [_check("dfm_brep_evidence", "fail", "critical", str(exc))],
                "limitations": report["limitations"] + ["未经验证的 B-Rep 证据未参与 DFM 判断。"],
            }
        )
        return report
    report["brepEvidence"] = brep
    if effective_limits.get("requiresBrepEvidence") and not brep.get("available"):
        report.update(
            {
                "status": "blocked",
                "error_code": "dfm_brep_evidence_required",
                "missingInputs": ["brepEvidence"],
                "checks": [
                    _check(
                        "dfm_brep_evidence",
                        "fail",
                        "critical",
                        "当前 Profile 要求真实 B-Rep 证据；未提供时不能进行该能力判断。",
                    )
                ],
                "limitations": report["limitations"] + ["缺少真实 B-Rep，未把 NeutralCadDocument 参数估算冒充实体测量。"],
            }
        )
        return report
    if brep.get("available"):
        report["limitations"].append("B-Rep 证据仅覆盖报告中记录的包络/拓扑范围，不等于完整制造认证。")
    else:
        report["limitations"].append("未提供 B-Rep 证据；包络来自 NeutralCadDocument 参数估算，不能证明 SolidWorks 实体拓扑。")

    missing = _critical_missing(document, manufacturing, normalized_process)
    if missing:
        report.update(
            {
                "status": "blocked",
                "missingInputs": missing,
                "error_code": "dfm_missing_inputs",
                "checks": [
                    _check(
                        "dfm_required_inputs",
                        "fail",
                        "critical",
                        "缺少关键制造输入，不能进行无人值守 DFM 判断。",
                        missingInputs=missing,
                    )
                ],
            }
        )
        return report

    manufacturing_for_checks = dict(manufacturing)
    if effective_limits.get("minimumWallThickness") is not None:
        current = _number(manufacturing_for_checks.get("minimumWallThickness")) or 0
        manufacturing_for_checks["minimumWallThickness"] = max(current, effective_limits["minimumWallThickness"])
    if effective_limits.get("minimumDrillDiameter") is not None:
        current = _number(manufacturing_for_checks.get("minimumDrillDiameter")) or 0
        manufacturing_for_checks["minimumDrillDiameter"] = max(current, effective_limits["minimumDrillDiameter"])
    if normalized_process == "machining":
        report["checks"] = _machining_checks(document, manufacturing_for_checks, brep)
    elif normalized_process == "sheet_metal":
        report["checks"] = _sheet_metal_checks(document, manufacturing_for_checks, brep)
    elif normalized_process == "laser_cutting":
        report["checks"] = _laser_checks(document, manufacturing_for_checks, brep)
    elif normalized_process == "3d_printing":
        report["checks"] = _printing_checks(document, manufacturing_for_checks, brep)
    report["checks"].extend(_profile_checks(document, manufacturing, normalized_process, effective_limits, brep))
    report["reviewFindings"] = [
        item for item in report["checks"] if item.get("status") in {"warning", "fail"}
    ]
    report["profileViolations"] = [
        item for item in report["checks"] if item.get("id", "").startswith("profile_") and item.get("status") == "fail"
    ]
    return report


def write_dfm_report(
    document_path: str | Path,
    output_path: str | Path,
    *,
    process: str | None = None,
    profiles: list[str | Path | dict[str, Any]] | None = None,
    brep_evidence: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """@brief 写出版本化 DFM 报告，并在返回值中附带 SHA-256 产物证据。"""
    report = build_dfm_report(document_path, process=process, profiles=profiles, brep_evidence=brep_evidence)
    target = _versioned_target(Path(output_path).expanduser().resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "kind": "dfm_report",
        "type": "artifact",
        "format": "json",
        "path": str(target),
        "exists": True,
        "producedThisRun": True,
    }
    report["reportPath"] = str(target)
    report["artifacts"] = [artifact]
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact["sha256"] = _sha256_file(target)
    artifact["sizeBytes"] = target.stat().st_size
    return report


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio NeutralCadDocument DFM 复核")
    parser.add_argument("--input", type=Path, required=True, help="NeutralCadDocument .cadstudio.json")
    parser.add_argument("--output", type=Path, required=True, help="版本化 DFM report JSON 输出路径")
    parser.add_argument("--process", choices=sorted(DFM_PROCESSES | {"auto", "CNC", "FDM", "SLA"}), default="auto")
    parser.add_argument("--profile", action="append", default=[], help="可重复指定 DFM Profile JSON，按能力交集合并")
    parser.add_argument("--brep-evidence", type=Path, help="可选 SolidWorks/OCCT B-Rep 证据 JSON")
    args = parser.parse_args(argv)
    result = write_dfm_report(
        args.input,
        args.output,
        process=args.process,
        profiles=args.profile,
        brep_evidence=args.brep_evidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
