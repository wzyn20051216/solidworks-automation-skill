"""@brief CAD Studio 开放求解器 FEA 输入校验、前置探测与受控执行。

本模块只接受结构化有限元数据并生成白名单 CalculiX 输入文件。它不接受任意
求解器参数、命令行或脚本；求解器缺失、计算失败或结果文件缺失时绝不伪造结果。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ELEMENT_NODES = {"C3D4": 4, "C3D8": 8}
_SOLVER_ENV = {"calculix": "CADSTUDIO_CALCULIX_EXE", "elmer": "CADSTUDIO_ELMER_EXE"}
_SOLVER_NAMES = {"calculix": ("ccx", "ccx.exe"), "elmer": ("ElmerSolver", "ElmerSolver.exe")}
_MAX_INPUT_BYTES = 64 * 1024 * 1024


def _now_iso() -> str:
    """@brief 返回 UTC 秒级时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _versioned_target(path: Path) -> Path:
    """@brief 生成不覆盖既有文件的目标路径。"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_v{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _sha256(path: Path) -> str:
    """@brief 计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_request(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 从字典或受限 JSON 文件读取 FEA 请求。"""
    if isinstance(value, dict):
        return dict(value)
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError("FEA 请求必须是存在的 JSON 文件。")
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("FEA 请求超过 64 MiB 安全上限。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("FEA 请求必须是 JSON object。")
    return payload


def _finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    """@brief 读取有限浮点数并按需要求大于零。"""
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是有限数值。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限数值。") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{field} 必须是{'大于零的' if positive else ''}有限数值。")
    return number


def _identifier(value: Any, field: str) -> str:
    """@brief 验证不会注入 CalculiX 关键字的标识符。"""
    token = str(value or "")
    if not _ID.fullmatch(token):
        raise ValueError(f"{field} 只能使用字母开头的 1-64 位字母、数字或下划线。")
    return token


def validate_analysis(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 严格校验 FEA Schema、拓扑引用、材料、载荷和约束。"""
    request = _load_request(value)
    allowed_top = {"schemaVersion", "analysisId", "analysisType", "solver", "units", "material", "mesh", "constraints", "loads"}
    unknown = set(request) - allowed_top
    if unknown:
        raise ValueError(f"FEA 请求含未允许字段: {', '.join(sorted(unknown))}")
    if request.get("schemaVersion") != "1.0":
        raise ValueError("schemaVersion 必须为 1.0。")
    _identifier(request.get("analysisId"), "analysisId")
    analysis_type = request.get("analysisType")
    if analysis_type not in {"static_linear", "modal", "thermal_steady"}:
        raise ValueError("analysisType 仅支持 static_linear、modal、thermal_steady。")
    solver = request.get("solver")
    if solver not in {"auto", "calculix", "elmer"}:
        raise ValueError("solver 仅支持 auto、calculix、elmer。")
    if request.get("units") != {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"}:
        raise ValueError("FEA 1.0 当前固定使用 mm/N/MPa/C 一致单位制。")

    material = request.get("material")
    if not isinstance(material, dict) or set(material) - {"name", "elasticModulusMPa", "poissonRatio", "densityKgM3", "conductivityWmK"}:
        raise ValueError("material 结构无效或含未允许字段。")
    if not str(material.get("name") or "").strip() or len(str(material["name"])) > 80:
        raise ValueError("material.name 必须是 1-80 字符。")
    _finite_number(material.get("elasticModulusMPa"), "material.elasticModulusMPa", positive=True)
    poisson = _finite_number(material.get("poissonRatio"), "material.poissonRatio")
    if not -1 < poisson < 0.5:
        raise ValueError("material.poissonRatio 必须位于 (-1, 0.5)。")
    _finite_number(material.get("densityKgM3"), "material.densityKgM3", positive=True)
    if analysis_type == "thermal_steady":
        _finite_number(material.get("conductivityWmK"), "material.conductivityWmK", positive=True)

    mesh = request.get("mesh")
    if not isinstance(mesh, dict) or set(mesh) != {"nodes", "elements", "nodeSets", "elementSets"}:
        raise ValueError("mesh 必须且只能包含 nodes、elements、nodeSets、elementSets。")
    nodes = mesh.get("nodes")
    elements = mesh.get("elements")
    if not isinstance(nodes, list) or not 4 <= len(nodes) <= 1_000_000:
        raise ValueError("mesh.nodes 数量必须为 4-1000000。")
    if not isinstance(elements, list) or not 1 <= len(elements) <= 500_000:
        raise ValueError("mesh.elements 数量必须为 1-500000。")
    node_ids: set[int] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or set(node) != {"id", "x", "y", "z"}:
            raise ValueError(f"mesh.nodes[{index}] 结构无效。")
        node_id = node["id"]
        if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id < 1 or node_id in node_ids:
            raise ValueError(f"mesh.nodes[{index}].id 必须是唯一正整数。")
        node_ids.add(node_id)
        for axis in ("x", "y", "z"):
            _finite_number(node[axis], f"mesh.nodes[{index}].{axis}")

    element_ids: set[int] = set()
    element_types: dict[int, str] = {}
    for index, element in enumerate(elements):
        if not isinstance(element, dict) or set(element) != {"id", "type", "nodeIds"}:
            raise ValueError(f"mesh.elements[{index}] 结构无效。")
        element_id = element["id"]
        kind = element["type"]
        refs = element["nodeIds"]
        if isinstance(element_id, bool) or not isinstance(element_id, int) or element_id < 1 or element_id in element_ids:
            raise ValueError(f"mesh.elements[{index}].id 必须是唯一正整数。")
        element_ids.add(element_id)
        element_types[element_id] = kind
        if kind not in _ELEMENT_NODES or not isinstance(refs, list) or len(refs) != _ELEMENT_NODES[kind]:
            raise ValueError(f"mesh.elements[{index}] 的类型或节点数无效。")
        if len(set(refs)) != len(refs) or any(ref not in node_ids for ref in refs):
            raise ValueError(f"mesh.elements[{index}] 引用了缺失或重复节点。")

    node_sets = _validate_sets(mesh["nodeSets"], node_ids, "nodeSets")
    element_sets = _validate_sets(mesh["elementSets"], element_ids, "elementSets")
    constraints = request.get("constraints")
    loads = request.get("loads")
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("constraints 至少需要一项。")
    if not isinstance(loads, list) or not loads:
        raise ValueError("loads 至少需要一项。")
    seen: set[str] = set()
    for index, item in enumerate(constraints):
        if not isinstance(item, dict) or set(item) - {"id", "type", "nodeSet", "dof", "value"}:
            raise ValueError(f"constraints[{index}] 结构无效。")
        item_id = _identifier(item.get("id"), f"constraints[{index}].id")
        if item_id in seen:
            raise ValueError("载荷和约束 ID 必须全局唯一。")
        seen.add(item_id)
        if item.get("type") not in {"fixed", "displacement"} or item.get("nodeSet") not in node_sets:
            raise ValueError(f"constraints[{index}] 类型或 nodeSet 无效。")
        if item["type"] == "displacement":
            if item.get("dof") not in {1, 2, 3}:
                raise ValueError("位移约束 dof 必须为 1、2 或 3。")
            _finite_number(item.get("value"), f"constraints[{index}].value")
    for index, item in enumerate(loads):
        _validate_load(item, index, node_sets, element_sets, element_types, seen)
    return request


def _validate_sets(value: Any, valid_ids: set[int], field: str) -> dict[str, list[int]]:
    """@brief 校验节点集或单元集。"""
    if not isinstance(value, dict):
        raise ValueError(f"mesh.{field} 必须是 object。")
    result: dict[str, list[int]] = {}
    for raw_name, members in value.items():
        name = _identifier(raw_name, f"mesh.{field} 名称")
        if not isinstance(members, list) or not members or any(member not in valid_ids for member in members):
            raise ValueError(f"mesh.{field}.{name} 必须只引用已有 ID。")
        result[name] = members
    return result


def _validate_load(
    item: Any,
    index: int,
    node_sets: dict[str, list[int]],
    element_sets: dict[str, list[int]],
    element_types: dict[int, str],
    seen: set[str],
) -> None:
    """@brief 校验一个白名单载荷。"""
    if not isinstance(item, dict) or set(item) - {"id", "type", "nodeSet", "elementSet", "face", "dof", "value", "magnitude", "direction"}:
        raise ValueError(f"loads[{index}] 结构无效。")
    item_id = _identifier(item.get("id"), f"loads[{index}].id")
    if item_id in seen:
        raise ValueError("载荷和约束 ID 必须全局唯一。")
    seen.add(item_id)
    kind = item.get("type")
    if kind == "force":
        if item.get("nodeSet") not in node_sets or item.get("dof") not in {1, 2, 3}:
            raise ValueError("force 必须引用有效 nodeSet 且 dof 为 1-3。")
        _finite_number(item.get("value"), f"loads[{index}].value")
    elif kind == "pressure":
        if item.get("elementSet") not in element_sets or item.get("face") not in {"P1", "P2", "P3", "P4", "P5", "P6"}:
            raise ValueError("pressure 必须引用有效 elementSet 并明确实体单元面 P1-P6。")
        face_number = int(str(item["face"])[1:])
        referenced_types = {element_types[element_id] for element_id in element_sets[item["elementSet"]]}
        maximum_face = min(4 if element_type == "C3D4" else 6 for element_type in referenced_types)
        if face_number > maximum_face:
            raise ValueError(f"pressure 面 {item['face']} 不适用于单元集中的 {', '.join(sorted(referenced_types))} 单元。")
        _finite_number(item.get("magnitude"), f"loads[{index}].magnitude", positive=True)
    elif kind == "gravity":
        direction = item.get("direction")
        if not isinstance(direction, list) or len(direction) != 3:
            raise ValueError("gravity.direction 必须是三维向量。")
        vector = [_finite_number(value, f"loads[{index}].direction") for value in direction]
        if math.sqrt(sum(value * value for value in vector)) <= 1e-12:
            raise ValueError("gravity.direction 不能是零向量。")
        _finite_number(item.get("magnitude"), f"loads[{index}].magnitude", positive=True)
    else:
        raise ValueError("载荷类型仅支持 force、pressure、gravity。")


def discover_solver(solver: str = "auto") -> dict[str, Any]:
    """@brief 从显式环境变量和 PATH 发现开放求解器。"""
    if solver not in {"auto", "calculix", "elmer"}:
        raise ValueError("求解器仅支持 auto、calculix、elmer。")
    order = ("calculix", "elmer") if solver == "auto" else (solver,)
    checked: list[dict[str, Any]] = []
    for name in order:
        env_name = _SOLVER_ENV[name]
        env_value = os.environ.get(env_name)
        candidate = Path(env_value).expanduser().resolve() if env_value else None
        if candidate and candidate.is_file():
            return {"status": "pass", "solver": name, "executable": str(candidate), "source": env_name, "checked": checked}
        path_value = next((shutil.which(item) for item in _SOLVER_NAMES[name] if shutil.which(item)), None)
        checked.append({"solver": name, "environmentVariable": env_name, "environmentPath": str(candidate) if candidate else None, "pathFound": path_value})
        if path_value:
            return {"status": "pass", "solver": name, "executable": str(Path(path_value).resolve()), "source": "PATH", "checked": checked}
    return {
        "status": "blocked", "solver": solver, "executable": None, "checked": checked,
        "error_code": "fea_solver_missing", "retryable": False,
        "missingDependencies": ["CalculiX ccx" if solver in {"auto", "calculix"} else "ElmerSolver"] + (["ElmerSolver"] if solver == "auto" else []),
        "message": "未发现开放 FEA 求解器。请安装 CalculiX 或 Elmer，并加入 PATH；也可设置 CADSTUDIO_CALCULIX_EXE / CADSTUDIO_ELMER_EXE。",
    }


def build_calculix_input(value: str | Path | dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    """@brief 生成不可注入任意关键字、且不覆盖旧文件的 CalculiX 输入文件。"""
    request = validate_analysis(value)
    if request["analysisType"] != "static_linear":
        return _blocked("generate_input", "fea_calculix_analysis_unsupported", "CalculiX 输入生成当前仅开放 static_linear。")
    target = _versioned_target(Path(output_path).expanduser().resolve())
    if target.suffix.lower() != ".inp":
        raise ValueError("CalculiX 输入文件扩展名必须是 .inp。")
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["** CAD Studio generated; structured whitelist only", "*HEADING", request["analysisId"], "*NODE"]
    for node in request["mesh"]["nodes"]:
        lines.append(f"{node['id']},{float(node['x']):.12g},{float(node['y']):.12g},{float(node['z']):.12g}")
    for kind in _ELEMENT_NODES:
        selected = [item for item in request["mesh"]["elements"] if item["type"] == kind]
        if selected:
            lines.append(f"*ELEMENT,TYPE={kind},ELSET=CADSTUDIO_{kind}")
            lines.extend(f"{item['id']}," + ",".join(str(node_id) for node_id in item["nodeIds"]) for item in selected)
    for name, members in request["mesh"]["nodeSets"].items():
        lines.extend([f"*NSET,NSET={name}", ",".join(str(item) for item in members)])
    for name, members in request["mesh"]["elementSets"].items():
        lines.extend([f"*ELSET,ELSET={name}", ",".join(str(item) for item in members)])
    lines.extend(["*ELSET,ELSET=CADSTUDIO_ALL_ELEMENTS", ",".join(str(item["id"]) for item in request["mesh"]["elements"])])
    material = request["material"]
    lines.extend(["*MATERIAL,NAME=CADSTUDIO_MATERIAL", "*ELASTIC", f"{float(material['elasticModulusMPa']):.12g},{float(material['poissonRatio']):.12g}"])
    lines.extend(["*DENSITY", f"{float(material['densityKgM3']) * 1e-12:.12g}"])
    for kind in _ELEMENT_NODES:
        if any(item["type"] == kind for item in request["mesh"]["elements"]):
            lines.extend([f"*SOLID SECTION,ELSET=CADSTUDIO_{kind},MATERIAL=CADSTUDIO_MATERIAL", ""])
    lines.extend(["*STEP", "*STATIC"])
    lines.append("*BOUNDARY")
    for item in request["constraints"]:
        if item["type"] == "fixed":
            lines.append(f"{item['nodeSet']},1,3,0")
        else:
            lines.append(f"{item['nodeSet']},{item['dof']},{item['dof']},{float(item['value']):.12g}")
    for item in request["loads"]:
        if item["type"] == "force":
            lines.extend(["*CLOAD", f"{item['nodeSet']},{item['dof']},{float(item['value']):.12g}"])
        elif item["type"] == "pressure":
            lines.extend(["*DLOAD", f"{item['elementSet']},{item['face']},{float(item['magnitude']):.12g}"])
        else:
            direction = item["direction"]
            norm = math.sqrt(sum(float(value) ** 2 for value in direction))
            unit = [float(value) / norm for value in direction]
            lines.extend(["*DLOAD", f"CADSTUDIO_ALL_ELEMENTS,GRAV,{float(item['magnitude']):.12g},{unit[0]:.12g},{unit[1]:.12g},{unit[2]:.12g}"])
    lines.extend(["*NODE FILE", "U", "*EL FILE", "S,E", "*END STEP", ""])
    target.write_text("\n".join(lines), encoding="ascii")
    artifact = {"kind": "calculix_input", "path": str(target), "sha256": _sha256(target), "sizeBytes": target.stat().st_size, "producedThisRun": True}
    return {"schemaVersion": "1.0", "status": "pass", "stage": "generate_input", "solver": "calculix", "artifacts": [artifact], "manual_review_required": True, "retryable": False, "error_code": None, "generatedAt": _now_iso()}


def _blocked(stage: str, error_code: str, message: str, **extra: Any) -> dict[str, Any]:
    """@brief 构造稳定 blocked 结果。"""
    result = {"schemaVersion": "1.0", "status": "blocked", "stage": stage, "checks": [], "artifacts": [], "manual_review_required": True, "retryable": False, "error_code": error_code, "message": message, "generatedAt": _now_iso()}
    result.update(extra)
    return result


def run_analysis(value: str | Path | dict[str, Any], output_dir: str | Path, *, timeout_seconds: int = 600) -> dict[str, Any]:
    """@brief 以前置门禁和参数数组受控运行求解器，结果仍要求人工复核。"""
    try:
        request = validate_analysis(value)
    except (ValueError, json.JSONDecodeError) as exc:
        return _blocked("validate", "fea_invalid_request", str(exc))
    preflight = discover_solver(request["solver"])
    if preflight["status"] != "pass":
        return _blocked("preflight", "fea_solver_missing", preflight["message"], preflight=preflight)
    if preflight["solver"] != "calculix":
        return _blocked("generate_input", "fea_elmer_adapter_not_implemented", "已发现 ElmerSolver，但安全输入适配器尚未实现。", preflight=preflight)
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    job_dir = _versioned_target(out_dir / request["analysisId"])
    job_dir.mkdir(parents=False, exist_ok=False)
    deck = build_calculix_input(request, job_dir / f"{request['analysisId']}.inp")
    if deck["status"] != "pass":
        return deck
    stem = Path(deck["artifacts"][0]["path"]).stem
    try:
        completed = subprocess.run([preflight["executable"], "-i", stem], cwd=job_dir, capture_output=True, text=True, timeout=max(1, min(int(timeout_seconds), 86_400)), shell=False, check=False)
    except subprocess.TimeoutExpired:
        return _blocked("solve", "fea_solver_timeout", "CalculiX 求解超时，未生成成功结论。", retryable=True, preflight=preflight)
    evidence = [job_dir / f"{stem}.dat", job_dir / f"{stem}.frd"]
    artifacts = [deck["artifacts"][0]]
    artifacts.extend({"kind": path.suffix.lstrip("."), "path": str(path), "sha256": _sha256(path), "sizeBytes": path.stat().st_size, "producedThisRun": True} for path in evidence if path.is_file() and path.stat().st_size > 0)
    if completed.returncode != 0 or len(artifacts) == 1:
        return {"schemaVersion": "1.0", "status": "failed", "stage": "solve", "solver": "calculix", "artifacts": artifacts, "manual_review_required": True, "retryable": True, "error_code": "fea_solver_failed", "exitCode": completed.returncode, "stdoutTail": completed.stdout[-4000:], "stderrTail": completed.stderr[-4000:], "generatedAt": _now_iso()}
    return {"schemaVersion": "1.0", "status": "review_required", "stage": "review", "solver": "calculix", "artifacts": artifacts, "manual_review_required": True, "retryable": False, "error_code": None, "limitations": ["结果尚未执行网格收敛、载荷合理性和工程安全复核，不能作为安全认证。"], "generatedAt": _now_iso()}


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio 开放求解器 FEA")
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--solver", choices=("auto", "calculix", "elmer"), default="auto")
    generate = sub.add_parser("generate-calculix")
    generate.add_argument("--input", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = discover_solver(args.solver)
    elif args.command == "generate-calculix":
        result = build_calculix_input(args.input, args.output)
    else:
        result = run_analysis(args.input, args.output_dir, timeout_seconds=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
