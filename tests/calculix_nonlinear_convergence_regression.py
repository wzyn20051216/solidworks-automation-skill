"""@brief CalculiX 2.23 非线性静力网格收敛真机回归。

该脚本只改变结构化 C3D8 网格的厚度方向细化等级，保持材料、载荷、约束和
NLGEOM 增量控制一致；它不会把收敛结果当作安全认证。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fea_convergence import run_convergence_study


def _analysis(analysis_id: str, divisions: int) -> dict:
    """@brief 构造 10x10x40 mm 受压块的厚度方向结构化非线性网格。"""
    nodes = []
    node_id = 1
    for layer in range(divisions + 1):
        z = 40.0 * layer / divisions
        for y in (0.0, 10.0):
            for x in (0.0, 10.0):
                nodes.append({"id": node_id, "x": x, "y": y, "z": z})
                node_id += 1
    elements = []
    for layer in range(divisions):
        bottom = 1 + 4 * layer
        top = bottom + 4
        elements.append({
            "id": layer + 1,
            "type": "C3D8",
            "nodeIds": [bottom, bottom + 1, bottom + 3, bottom + 2, top, top + 1, top + 3, top + 2],
        })
    bottom_nodes = [1, 2, 3, 4]
    top_start = 1 + 4 * divisions
    top_nodes = list(range(top_start, top_start + 4))
    return {
        "schemaVersion": "1.1",
        "analysisId": analysis_id,
        "analysisType": "static_nonlinear",
        "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {
            "name": "Steel",
            "elasticModulusMPa": 210000,
            "poissonRatio": 0.3,
            "densityKgM3": 7850,
        },
        "mesh": {
            "nodes": nodes,
            "elements": elements,
            "nodeSets": {"Bottom": bottom_nodes, "Top": top_nodes},
            "elementSets": {"Body": [item["id"] for item in elements]},
        },
        "constraints": [{"id": "fixed_bottom", "type": "fixed", "nodeSet": "Bottom"}],
        "loads": [{"id": "compress_top", "type": "force", "nodeSet": "Top", "dof": 3, "value": -25}],
        "nonlinearControls": {
            "initialIncrement": 0.1,
            "timePeriod": 1.0,
            "minimumIncrement": 1e-6,
            "maximumIncrement": 0.2,
            "maximumIncrements": 100,
        },
    }


def build_request() -> dict:
    """@brief 返回四档、物理条件一致的非线性收敛请求。"""
    cases = []
    for divisions in (1, 2, 4, 8):
        cases.append({
            "id": f"z{divisions}",
            "characteristicSizeMm": 40.0 / divisions,
            "analysis": _analysis(f"nonlinear_convergence_z{divisions}", divisions),
        })
    return {"schemaVersion": "1.0", "studyId": "nonlinear_block_convergence", "tolerancePercent": 8.0, "cases": cases}


def main() -> int:
    """@brief 执行真机回归并输出报告。"""
    parser = argparse.ArgumentParser(description="CalculiX 非线性网格收敛回归")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run_convergence_study(build_request(), args.output_dir, timeout_seconds_per_case=180)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "review_required" and report.get("converged") else 1


if __name__ == "__main__":
    raise SystemExit(main())
