"""@brief NeutralCadDocument 的轻量 DFM 规则复核。

本模块只做可追溯的制造风险检查，不输出制造认证结论。即使所有机器规则通过，
顶层状态仍保持 review_required，由工程师对材料、工艺、公差和供应商能力做
最终确认。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _bounds(document: dict[str, Any]) -> dict[str, Any]:
    """@brief 从基础特征估算包络尺寸，用于 DFM 风险检查。"""
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
        return {"available": False, "size": []}
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


def _common_checks(document: dict[str, Any], manufacturing: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 所有工艺共用的材料、包络和孔径证据检查。"""
    material = _material(document, manufacturing)
    bounds = _bounds(document)
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


def _machining_checks(document: dict[str, Any], manufacturing: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief CNC/机加工基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing)
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


def _sheet_metal_checks(document: dict[str, Any], manufacturing: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 钣金基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing)
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


def _laser_checks(document: dict[str, Any], manufacturing: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 激光切割基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing)
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


def _printing_checks(document: dict[str, Any], manufacturing: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 3D 打印基础 DFM 检查。"""
    checks = _common_checks(document, manufacturing)
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
    bounds = _bounds(document)
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


def build_dfm_report(document_path: str | Path, *, process: str | None = None) -> dict[str, Any]:
    """@brief 生成不依赖 CAD 软件的 DFM 复核报告。"""
    source = Path(document_path).expanduser().resolve()
    try:
        document = _load_document(source)
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
        "generatedAt": _now_iso(),
        "sourceDocument": str(source),
        "sourceSha256": _sha256_file(source) if source.is_file() else "",
        "documentId": document.get("documentId"),
        "units": document.get("units", "mm"),
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

    if normalized_process == "machining":
        report["checks"] = _machining_checks(document, manufacturing)
    elif normalized_process == "sheet_metal":
        report["checks"] = _sheet_metal_checks(document, manufacturing)
    elif normalized_process == "laser_cutting":
        report["checks"] = _laser_checks(document, manufacturing)
    elif normalized_process == "3d_printing":
        report["checks"] = _printing_checks(document, manufacturing)
    report["reviewFindings"] = [
        item for item in report["checks"] if item.get("status") in {"warning", "fail"}
    ]
    return report


def write_dfm_report(document_path: str | Path, output_path: str | Path, *, process: str | None = None) -> dict[str, Any]:
    """@brief 写出版本化 DFM 报告，并在返回值中附带 SHA-256 产物证据。"""
    report = build_dfm_report(document_path, process=process)
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
    args = parser.parse_args(argv)
    result = write_dfm_report(args.input, args.output, process=args.process)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
