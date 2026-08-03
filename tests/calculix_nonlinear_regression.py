"""@brief CalculiX 2.23 几何非线性、塑性和面接触真机回归。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fea_analysis import run_analysis


def _block_nodes(z0: float, z1: float, first_id: int) -> list[dict]:
    """@brief 返回 10x10 mm 方柱的八个 C3D8 节点。"""
    points = [
        (0, 0, z0), (10, 0, z0), (10, 10, z0), (0, 10, z0),
        (0, 0, z1), (10, 0, z1), (10, 10, z1), (0, 10, z1),
    ]
    return [
        {"id": first_id + index, "x": x, "y": y, "z": z}
        for index, (x, y, z) in enumerate(points)
    ]


def _single_block(analysis_id: str, *, plastic: bool) -> dict:
    """@brief 构造受轴向压力的单块 NLGEOM/塑性样件。"""
    material = {"name": "Steel", "elasticModulusMPa": 210000, "poissonRatio": 0.3, "densityKgM3": 7850}
    if plastic:
        material["plasticCurve"] = [
            {"yieldStressMPa": 0.5, "plasticStrain": 0.0},
            {"yieldStressMPa": 1.0, "plasticStrain": 0.05},
        ]
    return {
        "schemaVersion": "1.1", "analysisId": analysis_id,
        "analysisType": "static_nonlinear", "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": material,
        "mesh": {
            "nodes": _block_nodes(0, 10, 1),
            "elements": [{"id": 1, "type": "C3D8", "nodeIds": list(range(1, 9))}],
            "nodeSets": {"Bottom": [1, 2, 3, 4], "Top": [5, 6, 7, 8]},
            "elementSets": {"Body": [1]},
        },
        "constraints": [{"id": "fixed_bottom", "type": "fixed", "nodeSet": "Bottom"}],
        "loads": [{"id": "compress_top", "type": "force", "nodeSet": "Top", "dof": 3, "value": -25}],
        "nonlinearControls": {
            "initialIncrement": 0.05, "timePeriod": 1.0, "minimumIncrement": 1e-6,
            "maximumIncrement": 0.1, "maximumIncrements": 200,
        },
    }


def _contact_blocks() -> dict:
    """@brief 构造共面接触的上下两块 C3D8 实体。"""
    nodes = _block_nodes(0, 10, 1) + _block_nodes(10, 20, 9)
    return {
        "schemaVersion": "1.1", "analysisId": "two_block_contact",
        "analysisType": "static_nonlinear", "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {"name": "Steel", "elasticModulusMPa": 210000, "poissonRatio": 0.3, "densityKgM3": 7850},
        "mesh": {
            "nodes": nodes,
            "elements": [
                {"id": 1, "type": "C3D8", "nodeIds": list(range(1, 9))},
                {"id": 2, "type": "C3D8", "nodeIds": list(range(9, 17))},
            ],
            "nodeSets": {
                "LowerBottom": [1, 2, 3, 4], "UpperNodes": list(range(9, 17)), "UpperTop": [13, 14, 15, 16],
            },
            "elementSets": {"LowerElements": [1], "UpperElements": [2]},
        },
        "constraints": [
            {"id": "fixed_lower", "type": "fixed", "nodeSet": "LowerBottom"},
            {"id": "upper_x", "type": "displacement", "nodeSet": "UpperNodes", "dof": 1, "value": 0},
            {"id": "upper_y", "type": "displacement", "nodeSet": "UpperNodes", "dof": 2, "value": 0},
        ],
        "loads": [{"id": "compress", "type": "force", "nodeSet": "UpperTop", "dof": 3, "value": -25}],
        "nonlinearControls": {
            "initialIncrement": 0.05, "timePeriod": 1.0, "minimumIncrement": 1e-6,
            "maximumIncrement": 0.1, "maximumIncrements": 200,
        },
        "surfaces": {
            "LowerTop": {"elementSet": "LowerElements", "face": "S2"},
            "UpperBottom": {"elementSet": "UpperElements", "face": "S1"},
        },
        "contacts": [{
            "id": "block_interface", "masterSurface": "LowerTop", "slaveSurface": "UpperBottom",
            "frictionCoefficient": 0.1, "normalStiffnessMPaPerMm": 21000,
            "tangentialStickSlopeMPaPerMm": 10500,
        }],
    }


def run_regression(output_dir: Path) -> dict:
    """@brief 顺序执行三项真实求解并强制检查证据。"""
    cases = [
        ("geometric_nonlinear", _single_block("geometric_nonlinear", plastic=False)),
        ("material_plasticity", _single_block("material_plasticity", plastic=True)),
        ("surface_contact", _contact_blocks()),
    ]
    results = []
    for capability, request in cases:
        result = run_analysis(request, output_dir, timeout_seconds=180)
        if result.get("status") != "review_required":
            raise RuntimeError(f"{capability} 回归失败: {result}")
        evidence = result.get("resultEvidence", {}).get("summary", {})
        if not evidence.get("resultTerminated") or evidence.get("maximumDisplacementMm") is None:
            raise RuntimeError(f"{capability} 缺少完整结果证据。")
        results.append({
            "capability": capability,
            "analysisId": request["analysisId"],
            "status": result["status"],
            "requestEvidence": result.get("requestEvidence", {}),
            "resultSummary": evidence,
            "artifacts": result.get("artifacts", []),
        })
    report = {"status": "review_required", "solver": "CalculiX 2.23", "cases": results, "manual_review_required": True}
    target = output_dir.resolve() / "nonlinear_regression_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"拒绝覆盖已有回归报告: {target}")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["reportPath"] = str(target)
    return report


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="CalculiX 非线性与接触真机回归")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_regression(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
