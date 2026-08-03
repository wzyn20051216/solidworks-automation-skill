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
_ELEMENT_FACE_LIMITS = {"C3D4": 4, "C3D8": 6}
_SOLVER_ENV = {"calculix": "CADSTUDIO_CALCULIX_EXE", "elmer": "CADSTUDIO_ELMER_EXE"}
_SOLVER_NAMES = {"calculix": ("ccx", "ccx.exe"), "elmer": ("ElmerSolver", "ElmerSolver.exe")}
_MAX_INPUT_BYTES = 64 * 1024 * 1024
_RESULT_NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")


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


def _windows_user_environment(name: str) -> str | None:
    """@brief 读取当前用户环境变量注册表，避免长驻应用必须重启才能发现新安装。"""
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return None


def _standard_solver_candidates(solver: str) -> list[Path]:
    """@brief 返回 CAD Studio 在非系统盘使用的受控求解器候选路径。"""
    if os.name != "nt" or solver != "calculix":
        return []
    return [
        Path(drive) / "CADStudio" / "CalculiX-2.23" / "calculix_2.23_4win" / "ccx.exe"
        for drive in ("D:\\", "E:\\")
    ]


def _identifier(value: Any, field: str) -> str:
    """@brief 验证不会注入 CalculiX 关键字的标识符。"""
    token = str(value or "")
    if not _ID.fullmatch(token):
        raise ValueError(f"{field} 只能使用字母开头的 1-64 位字母、数字或下划线。")
    return token


def _calculix_id_lines(values: list[int], *, width: int = 16) -> list[str]:
    """@brief 按 CalculiX 每行最多 16 个集合成员的限制拆分 ID。"""
    return [",".join(str(item) for item in values[index:index + width]) for index in range(0, len(values), width)]


def validate_analysis(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    """@brief 严格校验 FEA Schema、拓扑引用、材料、载荷和约束。"""
    request = _load_request(value)
    allowed_top = {
        "schemaVersion", "analysisId", "analysisType", "solver", "units", "material", "mesh",
        "constraints", "loads", "nonlinearControls", "surfaces", "contacts",
    }
    unknown = set(request) - allowed_top
    if unknown:
        raise ValueError(f"FEA 请求含未允许字段: {', '.join(sorted(unknown))}")
    if request.get("schemaVersion") not in {"1.0", "1.1"}:
        raise ValueError("schemaVersion 必须为 1.0 或 1.1。")
    _identifier(request.get("analysisId"), "analysisId")
    analysis_type = request.get("analysisType")
    if analysis_type not in {"static_linear", "static_nonlinear", "modal", "thermal_steady"}:
        raise ValueError("analysisType 仅支持 static_linear、static_nonlinear、modal、thermal_steady。")
    if analysis_type == "static_nonlinear" and request.get("schemaVersion") != "1.1":
        raise ValueError("static_nonlinear 必须使用 FEA schemaVersion 1.1。")
    solver = request.get("solver")
    if solver not in {"auto", "calculix", "elmer"}:
        raise ValueError("solver 仅支持 auto、calculix、elmer。")
    if request.get("units") != {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"}:
        raise ValueError("FEA 1.0 当前固定使用 mm/N/MPa/C 一致单位制。")

    material = request.get("material")
    if not isinstance(material, dict) or set(material) - {"name", "elasticModulusMPa", "poissonRatio", "densityKgM3", "conductivityWmK", "plasticCurve"}:
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
    plastic_curve = material.get("plasticCurve")
    if plastic_curve is not None:
        if analysis_type != "static_nonlinear":
            raise ValueError("material.plasticCurve 只允许用于 static_nonlinear。")
        if not isinstance(plastic_curve, list) or not 2 <= len(plastic_curve) <= 64:
            raise ValueError("material.plasticCurve 必须包含 2-64 个应力/塑性应变点。")
        previous_stress = -math.inf
        previous_strain = -math.inf
        for index, point in enumerate(plastic_curve):
            if not isinstance(point, dict) or set(point) != {"yieldStressMPa", "plasticStrain"}:
                raise ValueError(f"material.plasticCurve[{index}] 结构无效。")
            stress = _finite_number(point["yieldStressMPa"], f"material.plasticCurve[{index}].yieldStressMPa", positive=True)
            strain = _finite_number(point["plasticStrain"], f"material.plasticCurve[{index}].plasticStrain")
            if strain < 0 or stress <= previous_stress or strain <= previous_strain:
                raise ValueError("material.plasticCurve 的屈服应力和塑性应变必须严格递增且应变非负。")
            if index == 0 and strain != 0:
                raise ValueError("material.plasticCurve 首点 plasticStrain 必须为 0。")
            previous_stress, previous_strain = stress, strain

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
    _validate_nonlinear_extensions(request, analysis_type, element_sets, element_types)
    return request


def _validate_nonlinear_extensions(
    request: dict[str, Any],
    analysis_type: str,
    element_sets: dict[str, list[int]],
    element_types: dict[int, str],
) -> None:
    """@brief 校验几何非线性增量、单元面和白名单接触对。"""
    controls = request.get("nonlinearControls")
    surfaces = request.get("surfaces")
    contacts = request.get("contacts")
    if analysis_type != "static_nonlinear":
        if any(value is not None for value in (controls, surfaces, contacts)):
            raise ValueError("nonlinearControls、surfaces 和 contacts 只允许用于 static_nonlinear。")
        return
    if not isinstance(controls, dict) or set(controls) != {
        "initialIncrement", "timePeriod", "minimumIncrement", "maximumIncrement", "maximumIncrements",
    }:
        raise ValueError("static_nonlinear 必须提供完整 nonlinearControls。")
    initial = _finite_number(controls["initialIncrement"], "nonlinearControls.initialIncrement", positive=True)
    period = _finite_number(controls["timePeriod"], "nonlinearControls.timePeriod", positive=True)
    minimum = _finite_number(controls["minimumIncrement"], "nonlinearControls.minimumIncrement", positive=True)
    maximum = _finite_number(controls["maximumIncrement"], "nonlinearControls.maximumIncrement", positive=True)
    maximum_increments = controls["maximumIncrements"]
    if isinstance(maximum_increments, bool) or not isinstance(maximum_increments, int) or not 1 <= maximum_increments <= 1000:
        raise ValueError("nonlinearControls.maximumIncrements 必须是 1-1000 的整数。")
    if not minimum <= initial <= maximum <= period:
        raise ValueError("非线性增量必须满足 minimum <= initial <= maximum <= timePeriod。")
    if surfaces is None:
        surfaces = {}
    if not isinstance(surfaces, dict) or len(surfaces) > 64:
        raise ValueError("surfaces 必须是最多 64 项的 object。")
    surface_names: set[str] = set()
    surface_element_members: dict[str, set[int]] = {}
    for raw_name, surface in surfaces.items():
        name = _identifier(raw_name, "surfaces 名称")
        surface_names.add(name)
        if not isinstance(surface, dict) or set(surface) != {"elementSet", "face"}:
            raise ValueError(f"surfaces.{name} 必须且只能包含 elementSet 和 face。")
        element_set = surface.get("elementSet")
        face = str(surface.get("face") or "")
        if element_set not in element_sets or not re.fullmatch(r"S[1-6]", face):
            raise ValueError(f"surfaces.{name} 必须引用有效 elementSet 和 S1-S6。")
        face_number = int(face[1:])
        referenced_types = {element_types[element_id] for element_id in element_sets[element_set]}
        if any(face_number > _ELEMENT_FACE_LIMITS[element_type] for element_type in referenced_types):
            raise ValueError(f"surfaces.{name} 的 {face} 不适用于所引用单元。")
        surface_element_members[name] = set(element_sets[element_set])
    if contacts is None:
        contacts = []
    if not isinstance(contacts, list) or len(contacts) > 32:
        raise ValueError("contacts 必须是最多 32 项的数组。")
    contact_ids: set[str] = set()
    for index, contact in enumerate(contacts):
        allowed = {
            "id", "masterSurface", "slaveSurface", "frictionCoefficient",
            "normalStiffnessMPaPerMm", "tangentialStickSlopeMPaPerMm",
        }
        if not isinstance(contact, dict) or set(contact) != allowed:
            raise ValueError(f"contacts[{index}] 结构无效。")
        contact_id = _identifier(contact.get("id"), f"contacts[{index}].id")
        if contact_id in contact_ids:
            raise ValueError(f"接触 ID 重复: {contact_id}")
        contact_ids.add(contact_id)
        master = contact.get("masterSurface")
        slave = contact.get("slaveSurface")
        if master not in surface_names or slave not in surface_names or master == slave:
            raise ValueError(f"contacts[{index}] 必须引用两个不同的已定义 surface。")
        if surface_element_members[master].intersection(surface_element_members[slave]):
            raise ValueError(f"contacts[{index}] 当前只允许来自不相交单元集的两个 surface；自接触尚未验证。")
        friction = _finite_number(contact.get("frictionCoefficient"), f"contacts[{index}].frictionCoefficient")
        if not 0 <= friction <= 2:
            raise ValueError("frictionCoefficient 必须位于 [0, 2]。")
        _finite_number(contact.get("normalStiffnessMPaPerMm"), f"contacts[{index}].normalStiffnessMPaPerMm", positive=True)
        stick_slope = _finite_number(contact.get("tangentialStickSlopeMPaPerMm"), f"contacts[{index}].tangentialStickSlopeMPaPerMm")
        if stick_slope < 0 or (friction > 0 and stick_slope == 0):
            raise ValueError("有摩擦接触必须提供大于零的 tangentialStickSlopeMPaPerMm。")


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
        environment_candidates: list[tuple[str, str | None]] = [
            (env_name, os.environ.get(env_name)),
            (f"HKCU\\Environment\\{env_name}", _windows_user_environment(env_name)),
        ]
        for source, env_value in environment_candidates:
            candidate = Path(os.path.expandvars(env_value)).expanduser().resolve() if env_value else None
            checked.append({"solver": name, "source": source, "path": str(candidate) if candidate else None, "exists": bool(candidate and candidate.is_file())})
            if candidate and candidate.is_file():
                return {"status": "pass", "solver": name, "executable": str(candidate), "source": source, "checked": checked}
        path_value = next((shutil.which(item) for item in _SOLVER_NAMES[name] if shutil.which(item)), None)
        if path_value:
            return {"status": "pass", "solver": name, "executable": str(Path(path_value).resolve()), "source": "PATH", "checked": checked}
        for candidate in _standard_solver_candidates(name):
            checked.append({"solver": name, "source": "cadstudio-standard-path", "path": str(candidate), "exists": candidate.is_file()})
            if candidate.is_file():
                return {"status": "pass", "solver": name, "executable": str(candidate.resolve()), "source": "cadstudio-standard-path", "checked": checked}
    return {
        "status": "blocked", "solver": solver, "executable": None, "checked": checked,
        "error_code": "fea_solver_missing", "retryable": False,
        "missingDependencies": ["CalculiX ccx" if solver in {"auto", "calculix"} else "ElmerSolver"] + (["ElmerSolver"] if solver == "auto" else []),
        "message": "未发现开放 FEA 求解器。请安装 CalculiX 或 Elmer，并加入 PATH；也可设置 CADSTUDIO_CALCULIX_EXE / CADSTUDIO_ELMER_EXE。",
    }


def parse_calculix_results(job_dir: str | Path, stem: str) -> dict[str, Any]:
    """@brief 解析受限 FRD/STA 结果，验证位移、应力、版本和线性步收敛。"""
    root = Path(job_dir).expanduser().resolve()
    frd = root / f"{stem}.frd"
    sta = root / f"{stem}.sta"
    cvg = root / f"{stem}.cvg"
    if not frd.is_file() or frd.stat().st_size <= 0:
        return {"status": "failed", "error_code": "fea_result_frd_missing", "checks": [], "summary": {}}
    solver_version: str | None = None
    last_nonempty = ""
    current: str | None = None
    current_rows: dict[int, tuple[float, ...]] = {}
    result_blocks: dict[str, list[dict[int, tuple[float, ...]]]] = {"displacement": [], "stress": []}
    duplicate_node = False
    with frd.open("r", encoding="ascii", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                last_nonempty = stripped
            if solver_version is None:
                match = re.search(r"1UVERSION\s+Version\s+([^\s]+)", line)
                if match:
                    solver_version = match.group(1)
            if line.startswith(" -4  DISP"):
                current = "displacement"
                current_rows = {}
                continue
            if line.startswith(" -4  STRESS"):
                current = "stress"
                current_rows = {}
                continue
            if line.startswith(" -3"):
                if current and current_rows:
                    result_blocks[current].append(current_rows)
                current = None
                current_rows = {}
                continue
            if current and line.startswith(" -1"):
                values = [float(item) for item in _RESULT_NUMBER.findall(line)]
                if len(values) < 3:
                    continue
                node_id = int(values[1])
                components = tuple(values[2:])
                if node_id in current_rows:
                    duplicate_node = True
                if current == "displacement" and len(components) >= 3:
                    current_rows[node_id] = components[:3]
                elif current == "stress" and len(components) >= 6:
                    current_rows[node_id] = components[:6]
    displacement_rows = result_blocks["displacement"][-1] if result_blocks["displacement"] else {}
    stress_rows = result_blocks["stress"][-1] if result_blocks["stress"] else {}
    displacements = list(displacement_rows.values())
    stresses = list(stress_rows.values())
    finite = all(math.isfinite(value) for row in [*displacements, *stresses] for value in row)
    max_displacement = max((math.sqrt(sum(value * value for value in row)) for row in displacements), default=None)

    def von_mises(row: tuple[float, float, float, float, float, float]) -> float:
        sxx, syy, szz, sxy, syz, szx = row
        return math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3.0 * (sxy**2 + syz**2 + szx**2))

    max_von_mises = max((von_mises(row) for row in stresses), default=None)
    sta_text = sta.read_text(encoding="ascii", errors="replace") if sta.is_file() else ""
    cvg_text = cvg.read_text(encoding="ascii", errors="replace") if cvg.is_file() else ""
    increment_lines = [line for line in sta_text.splitlines() if re.match(r"^\s+\d+\s+\d+\s+\d+\s+\d+", line)]
    contact_element_counts: list[int] = []
    for line in cvg_text.splitlines():
        fields = line.split()
        if len(fields) >= 5 and all(field.isdigit() for field in fields[:5]):
            contact_element_counts.append(int(fields[4]))
    maximum_contact_elements = max(contact_element_counts, default=0)
    result_terminated = last_nonempty == "9999"
    node_sets_match = bool(displacement_rows) and set(displacement_rows) == set(stress_rows)
    failure_markers = re.findall(r"(?i)\b(?:ERROR|DIVERGED|DIVERGENCE|NOT\s+CONVERGED|FAILED)\b", sta_text + "\n" + cvg_text)
    converged = bool(increment_lines) and result_terminated and node_sets_match and not duplicate_node and not failure_markers and finite
    checks = [
        {"id": "fea-result-version", "status": "pass" if solver_version else "warning", "message": f"CalculiX {solver_version}" if solver_version else "未读取到求解器版本"},
        {"id": "fea-result-displacement", "status": "pass" if displacements and finite else "fail", "count": len(displacements)},
        {"id": "fea-result-stress", "status": "pass" if stresses and finite else "fail", "count": len(stresses)},
        {"id": "fea-result-node-identity", "status": "pass" if node_sets_match and not duplicate_node else "fail", "nodeSetsMatch": node_sets_match, "duplicateNode": duplicate_node},
        {"id": "fea-result-termination", "status": "pass" if result_terminated and not failure_markers else "fail", "terminated": result_terminated, "failureMarkers": failure_markers},
        {"id": "fea-result-contact-elements", "status": "pass" if maximum_contact_elements > 0 else "warning", "maximumContactElementCount": maximum_contact_elements},
        {"id": "fea-result-convergence", "status": "pass" if converged else "fail", "increments": len(increment_lines)},
    ]
    return {
        "status": "pass" if converged else "failed",
        "error_code": None if converged else "fea_result_incomplete_or_nonfinite",
        "checks": checks,
        "summary": {
            "solverVersion": solver_version,
            "displacementNodeCount": len(displacements),
            "stressNodeCount": len(stresses),
            "maximumDisplacementMm": max_displacement,
            "maximumVonMisesStressMPa": max_von_mises,
            "convergedIncrementCount": len(increment_lines),
            "finiteValues": finite,
            "resultTerminated": result_terminated,
            "nodeSetsMatch": node_sets_match,
            "failureMarkers": failure_markers,
            "maximumContactElementCount": maximum_contact_elements,
        },
        "files": [str(path) for path in (frd, sta, cvg) if path.is_file()],
    }


def build_calculix_input(value: str | Path | dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    """@brief 生成不可注入任意关键字、且不覆盖旧文件的 CalculiX 输入文件。"""
    request = validate_analysis(value)
    if request["analysisType"] not in {"static_linear", "static_nonlinear"}:
        return _blocked("generate_input", "fea_calculix_analysis_unsupported", "CalculiX 输入生成当前仅开放 static_linear/static_nonlinear。")
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
        lines.append(f"*NSET,NSET={name}")
        lines.extend(_calculix_id_lines(members))
    for name, members in request["mesh"]["elementSets"].items():
        lines.append(f"*ELSET,ELSET={name}")
        lines.extend(_calculix_id_lines(members))
    lines.append("*ELSET,ELSET=CADSTUDIO_ALL_ELEMENTS")
    lines.extend(_calculix_id_lines([item["id"] for item in request["mesh"]["elements"]]))
    for name, surface in request.get("surfaces", {}).items():
        lines.extend([f"*SURFACE,NAME={name},TYPE=ELEMENT", f"{surface['elementSet']},{surface['face']}"])
    material = request["material"]
    lines.extend(["*MATERIAL,NAME=CADSTUDIO_MATERIAL", "*ELASTIC", f"{float(material['elasticModulusMPa']):.12g},{float(material['poissonRatio']):.12g}"])
    if material.get("plasticCurve"):
        lines.append("*PLASTIC")
        lines.extend(
            f"{float(point['yieldStressMPa']):.12g},{float(point['plasticStrain']):.12g}"
            for point in material["plasticCurve"]
        )
    lines.extend(["*DENSITY", f"{float(material['densityKgM3']) * 1e-12:.12g}"])
    for kind in _ELEMENT_NODES:
        if any(item["type"] == kind for item in request["mesh"]["elements"]):
            lines.extend([f"*SOLID SECTION,ELSET=CADSTUDIO_{kind},MATERIAL=CADSTUDIO_MATERIAL", ""])
    for contact in request.get("contacts", []):
        interaction = f"CADSTUDIO_CONTACT_{contact['id']}"
        lines.extend([
            f"*SURFACE INTERACTION,NAME={interaction}",
            "*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=LINEAR",
            f"{float(contact['normalStiffnessMPaPerMm']):.12g}",
        ])
        friction = float(contact["frictionCoefficient"])
        if friction > 0:
            lines.extend(["*FRICTION", f"{friction:.12g},{float(contact['tangentialStickSlopeMPaPerMm']):.12g}"])
    nonlinear = request["analysisType"] == "static_nonlinear"
    for contact in request.get("contacts", []):
        interaction = f"CADSTUDIO_CONTACT_{contact['id']}"
        lines.extend([
            f"*CONTACT PAIR,INTERACTION={interaction},TYPE=SURFACE TO SURFACE",
            f"{contact['slaveSurface']},{contact['masterSurface']}",
        ])
    step_card = (
        f"*STEP,NLGEOM,INC={int(request['nonlinearControls']['maximumIncrements'])}"
        if nonlinear else "*STEP"
    )
    lines.extend([step_card, "*STATIC"])
    if nonlinear:
        controls = request["nonlinearControls"]
        lines.append(
            f"{float(controls['initialIncrement']):.12g},{float(controls['timePeriod']):.12g},"
            f"{float(controls['minimumIncrement']):.12g},{float(controls['maximumIncrement']):.12g}"
        )
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
    return {
        "schemaVersion": request["schemaVersion"], "status": "pass", "stage": "generate_input",
        "solver": "calculix", "analysisType": request["analysisType"], "artifacts": [artifact],
        "requestEvidence": {
            "geometricNonlinearity": nonlinear,
            "plasticCurvePointCount": len(material.get("plasticCurve", [])),
            "contactPairCount": len(request.get("contacts", [])),
        },
        "manual_review_required": True, "retryable": False, "error_code": None, "generatedAt": _now_iso(),
    }


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
    if request["analysisType"] not in {"static_linear", "static_nonlinear"}:
        return _blocked("generate_input", "fea_calculix_analysis_unsupported", "CalculiX 执行当前仅开放 static_linear/static_nonlinear。")
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
    evidence = [job_dir / f"{stem}.dat", job_dir / f"{stem}.frd", job_dir / f"{stem}.sta", job_dir / f"{stem}.cvg"]
    artifacts = [deck["artifacts"][0]]
    artifacts.extend({"kind": path.suffix.lstrip("."), "path": str(path), "sha256": _sha256(path), "sizeBytes": path.stat().st_size, "producedThisRun": True} for path in evidence if path.is_file() and path.stat().st_size > 0)
    result_evidence = parse_calculix_results(job_dir, stem)
    solver_evidence = {
        "executable": preflight["executable"],
        "executableSha256": _sha256(Path(preflight["executable"])),
        "source": preflight.get("source"),
        "exitCode": completed.returncode,
    }
    contact_elements_missing = bool(request.get("contacts")) and result_evidence.get("summary", {}).get("maximumContactElementCount", 0) <= 0
    if completed.returncode != 0 or result_evidence["status"] != "pass" or contact_elements_missing:
        error_code = "fea_solver_failed" if completed.returncode != 0 else result_evidence.get("error_code") or "fea_result_invalid"
        if contact_elements_missing:
            error_code = "fea_contact_elements_missing"
        return {"schemaVersion": request["schemaVersion"], "status": "failed", "stage": "solve", "solver": "calculix", "artifacts": artifacts, "solverEvidence": solver_evidence, "resultEvidence": result_evidence, "manual_review_required": True, "retryable": True, "error_code": error_code, "exitCode": completed.returncode, "stdoutTail": completed.stdout[-4000:], "stderrTail": completed.stderr[-4000:], "generatedAt": _now_iso()}
    nonlinear = request["analysisType"] == "static_nonlinear"
    limitations = ["单次结果已解析并验证有限值与求解增量，但仍需网格收敛、载荷合理性和工程安全复核，不能作为安全认证。"]
    if nonlinear:
        limitations.append("非线性结果只证明本轮白名单 CalculiX 输入完成求解；接触穿透、塑性路径和增量敏感性仍需专门复核。")
    if request.get("contacts"):
        limitations.append("CONT. EL 只证明 CalculiX 生成了接触单元，不证明接触全程闭合或穿透量合格。")
    return {
        "schemaVersion": request["schemaVersion"], "status": "review_required", "stage": "review",
        "solver": "calculix", "analysisType": request["analysisType"], "artifacts": artifacts,
        "solverEvidence": solver_evidence, "resultEvidence": result_evidence,
        "requestEvidence": deck.get("requestEvidence", {}),
        "manual_review_required": True, "retryable": False, "error_code": None,
        "limitations": limitations, "generatedAt": _now_iso(),
    }


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
