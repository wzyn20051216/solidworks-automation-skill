"""@brief 生成五档真实 C3D8 悬臂梁网格收敛请求。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_hex_cantilever(nx: int, ny: int, nz: int, *, analysis_id: str) -> dict:
    """@brief 构造 60x12x12 mm 结构化六面体悬臂梁。"""
    length, width, height = 60.0, 12.0, 12.0

    def node_id(i: int, j: int, k: int) -> int:
        return 1 + i + (nx + 1) * (j + (ny + 1) * k)

    nodes = []
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                nodes.append({
                    "id": node_id(i, j, k),
                    "x": length * i / nx,
                    "y": width * j / ny,
                    "z": height * k / nz,
                })
    elements = []
    element_id = 1
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                elements.append({
                    "id": element_id,
                    "type": "C3D8",
                    "nodeIds": [
                        node_id(i, j, k), node_id(i + 1, j, k),
                        node_id(i + 1, j + 1, k), node_id(i, j + 1, k),
                        node_id(i, j, k + 1), node_id(i + 1, j, k + 1),
                        node_id(i + 1, j + 1, k + 1), node_id(i, j + 1, k + 1),
                    ],
                })
                element_id += 1
    fixed = [node_id(0, j, k) for k in range(nz + 1) for j in range(ny + 1)]
    return {
        "schemaVersion": "1.0",
        "analysisId": analysis_id,
        "analysisType": "static_linear",
        "solver": "calculix",
        "units": {"length": "mm", "force": "N", "stress": "MPa", "temperature": "C"},
        "material": {
            "name": "StructuralSteel",
            "elasticModulusMPa": 210000,
            "poissonRatio": 0.3,
            "densityKgM3": 7850,
        },
        "mesh": {
            "nodes": nodes,
            "elements": elements,
            "nodeSets": {"FixedNodes": fixed},
            "elementSets": {"AllElements": [item["id"] for item in elements]},
        },
        "constraints": [{"id": "fixed_root", "type": "fixed", "nodeSet": "FixedNodes"}],
        "loads": [{"id": "self_weight", "type": "gravity", "magnitude": 9810, "direction": [0, 0, -1]}],
    }


def build_study() -> dict:
    """@brief 返回粗到最细五档网格收敛请求。"""
    levels = [
        ("coarse", 15.0, 4, 1, 1),
        ("medium", 7.5, 8, 2, 2),
        ("fine", 5.0, 12, 3, 3),
        ("finer", 3.75, 16, 4, 4),
        ("finest", 3.0, 20, 5, 5),
    ]
    return {
        "schemaVersion": "1.0",
        "studyId": "cantilever_gravity_convergence",
        "tolerancePercent": 8.0,
        "cases": [
            {
                "id": name,
                "characteristicSizeMm": size,
                "analysis": build_hex_cantilever(nx, ny, nz, analysis_id=f"cantilever_{name}"),
            }
            for name, size, nx, ny, nz in levels
        ],
    }


def main() -> int:
    """@brief 写出不覆盖旧文件的收敛示例 JSON。"""
    parser = argparse.ArgumentParser(description="生成 CalculiX 悬臂梁网格收敛示例")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.expanduser().resolve()
    if target.exists():
        raise SystemExit(f"拒绝覆盖已有文件: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_study(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "pass", "path": str(target), "sizeBytes": target.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
