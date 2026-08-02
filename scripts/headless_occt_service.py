"""OCCT/OCP 无头几何隔离服务。

该脚本在独立 Python 进程中构造基础 B-Rep、执行布尔运算并写出
STEP/IGES/BREP/STL/OBJ/GLB。调用方通过 result JSON 读取结构化结果，
避免 OCCT 原生输出污染 stdio 协议。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "apps" / "desktop"
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))


class UnsupportedFeatureError(ValueError):
    """@brief 当前 OCCT 路由无法表达输入特征。"""


def _params(feature: dict[str, Any]) -> dict[str, Any]:
    return feature.get("parameters") if isinstance(feature.get("parameters"), dict) else {}


def _positive(params: dict[str, Any], key: str, default: float) -> float:
    value = float(params.get(key, default))
    if value <= 0:
        raise ValueError(f"{key} 必须大于 0。")
    return value


def _versioned_target(out_dir: Path, name: str, extension: str, overwrite: bool) -> Path:
    """@brief 默认生成新版本文件，避免覆盖旧交付物。"""
    target = out_dir / f"{name}.{extension}"
    if overwrite or not target.exists():
        return target
    version = 2
    while True:
        candidate = out_dir / f"{name}_v{version}.{extension}"
        if not candidate.exists():
            return candidate
        version += 1


def _document_height(document: dict[str, Any]) -> float:
    heights = [
        float(_params(feature).get("height", 10.0))
        for feature in document.get("features", [])
        if isinstance(feature, dict) and str(feature.get("type") or "").lower() in {"box", "cylinder"}
    ]
    return max([height for height in heights if height > 0] or [10.0])


def build_shape(document: dict[str, Any]):
    """@brief 从 NeutralCadDocument 构造 OCCT TopoDS_Shape。"""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    shape = None
    through_height = _document_height(document) + 20.0
    for feature in document.get("features", []):
        if not isinstance(feature, dict):
            continue
        feature_id = str(feature.get("id") or feature.get("type") or "unknown")
        kind = str(feature.get("type") or "").lower()
        operation = str(feature.get("operation") or "add").lower()
        params = _params(feature)
        x = float(params.get("x", 0.0))
        y = float(params.get("y", 0.0))
        z = float(params.get("z", 0.0))

        if kind == "box":
            length = _positive(params, "length", 10.0)
            width = _positive(params, "width", 10.0)
            height = _positive(params, "height", 10.0)
            primitive = BRepPrimAPI_MakeBox(
                gp_Pnt(x - length / 2, y - width / 2, z - height / 2),
                length,
                width,
                height,
            ).Shape()
        elif kind in {"cylinder", "hole"}:
            radius = _positive(params, "radius", float(params.get("diameter", 10.0)) / 2)
            height = _positive(params, "height", through_height if kind == "hole" else 10.0)
            base_z = z - height / 2
            primitive = BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(x, y, base_z), gp_Dir(0, 0, 1)),
                radius,
                height,
            ).Shape()
        else:
            raise UnsupportedFeatureError(f"OCCT 后端暂不支持特征: {feature_id} ({kind})")

        is_subtractive = kind == "hole" or operation in {"subtract", "cut", "remove"}
        if is_subtractive:
            if shape is None:
                raise UnsupportedFeatureError(f"减材特征 {feature_id} 之前没有基础实体。")
            algorithm = BRepAlgoAPI_Cut(shape, primitive)
            algorithm.Build()
            if not algorithm.IsDone():
                raise RuntimeError(f"OCCT 布尔切除失败: {feature_id}")
            shape = algorithm.Shape()
        elif shape is None:
            shape = primitive
        elif operation in {"add", "new", "union", "fuse"}:
            algorithm = BRepAlgoAPI_Fuse(shape, primitive)
            algorithm.Build()
            if not algorithm.IsDone():
                raise RuntimeError(f"OCCT 布尔合并失败: {feature_id}")
            shape = algorithm.Shape()
        else:
            raise UnsupportedFeatureError(f"OCCT 后端暂不支持操作: {feature_id} ({operation})")

    if shape is None:
        raise UnsupportedFeatureError("NeutralCadDocument 没有可构造的实体特征。")
    return shape


def collect_evidence(shape) -> dict[str, Any]:
    """@brief 回读有效性、体积、包围盒和拓扑数量。"""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer

    def count(kind) -> int:
        explorer = TopExp_Explorer(shape, kind)
        total = 0
        while explorer.More():
            total += 1
            explorer.Next()
        return total

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    xmin, ymin, zmin, xmax, ymax, zmax = bounds.Get()
    return {
        "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "volume": float(props.Mass()),
        "bounds": {
            "min": [float(xmin), float(ymin), float(zmin)],
            "max": [float(xmax), float(ymax), float(zmax)],
        },
        "topology": {
            "solids": count(TopAbs_SOLID),
            "faces": count(TopAbs_FACE),
            "edges": count(TopAbs_EDGE),
            "vertices": count(TopAbs_VERTEX),
        },
    }


def _mesh_shape(shape, linear_deflection: float = 0.2, angular_deflection: float = 0.35) -> None:
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    mesher = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)
    mesher.Perform()
    if not mesher.IsDone():
        raise RuntimeError("OCCT 网格化失败。")


def export_occt(
    document_path: Path,
    out_dir: Path,
    formats: list[str],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """@brief 执行真实 OCCT 写入并返回结构化证据。"""
    from OCP.BRepTools import BRepTools
    from OCP.IGESControl import IGESControl_Writer
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.StlAPI import StlAPI_Writer

    from cad_workbench.cad_core_contracts import sha256_file

    document = json.loads(document_path.read_text(encoding="utf-8"))
    name = str(document.get("documentId") or document_path.stem).replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    shape = build_shape(document)
    evidence = collect_evidence(shape)
    if not evidence["valid"] or evidence["topology"]["solids"] < 1 or evidence["volume"] <= 0:
        raise RuntimeError("OCCT 结果未通过实体有效性、拓扑或体积门禁。")

    normalized_formats = [item.lower().lstrip(".") for item in formats]
    artifacts: list[dict[str, Any]] = []
    mesh_formats = {"stl", "obj", "glb"}.intersection(normalized_formats)
    stl_path: Path | None = None
    temp_context = tempfile.TemporaryDirectory(prefix="cadstudio-occt-")
    try:
        for fmt in normalized_formats:
            normalized = {"stp": "step", "igs": "iges"}.get(fmt, fmt)
            if normalized == "step":
                target = _versioned_target(out_dir, name, "step", overwrite)
                writer = STEPControl_Writer()
                if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(target)) != IFSelect_RetDone:
                    raise RuntimeError("STEP 写入失败。")
            elif normalized == "iges":
                target = _versioned_target(out_dir, name, "iges", overwrite)
                writer = IGESControl_Writer()
                if not writer.AddShape(shape) or not writer.Write(str(target)):
                    raise RuntimeError("IGES 写入失败。")
            elif normalized == "brep":
                target = _versioned_target(out_dir, name, "brep", overwrite)
                if not BRepTools.Write_s(shape, str(target)):
                    raise RuntimeError("BREP 写入失败。")
            elif normalized in {"stl", "obj", "glb"}:
                continue
            else:
                raise UnsupportedFeatureError(f"OCCT 后端不支持输出格式: {normalized}")
            artifacts.append(
                {
                    "kind": normalized,
                    "path": str(target),
                    "exists": target.is_file(),
                    "producedThisRun": True,
                    "sha256": sha256_file(target),
                    "sourceBackend": "headless_occt",
                }
            )

        if mesh_formats:
            _mesh_shape(shape)
            if "stl" in mesh_formats:
                stl_path = _versioned_target(out_dir, name, "stl", overwrite)
            else:
                stl_path = Path(temp_context.name) / f"{name}.stl"
            if not StlAPI_Writer().Write(shape, str(stl_path)) or not stl_path.is_file():
                raise RuntimeError("STL 写入失败。")
            if "stl" in mesh_formats:
                artifacts.append(
                    {
                        "kind": "stl",
                        "path": str(stl_path),
                        "exists": True,
                        "producedThisRun": True,
                        "sha256": sha256_file(stl_path),
                        "sourceBackend": "headless_occt",
                    }
                )

            if {"obj", "glb"}.intersection(mesh_formats):
                import trimesh

                mesh = trimesh.load_mesh(str(stl_path), force="mesh")
                if mesh.is_empty or len(mesh.vertices) < 3 or len(mesh.faces) < 1:
                    raise RuntimeError("OCCT 网格为空，拒绝写出 OBJ/GLB。")
                if "obj" in mesh_formats:
                    target = _versioned_target(out_dir, name, "obj", overwrite)
                    mesh.export(str(target), file_type="obj")
                    artifacts.append(
                        {
                            "kind": "obj",
                            "path": str(target),
                            "exists": target.is_file(),
                            "producedThisRun": True,
                            "sha256": sha256_file(target),
                            "sourceBackend": "headless_occt",
                        }
                    )
                if "glb" in mesh_formats:
                    target = _versioned_target(out_dir, name, "glb", overwrite)
                    target.write_bytes(mesh.export(file_type="glb"))
                    artifacts.append(
                        {
                            "kind": "glb",
                            "path": str(target),
                            "exists": target.is_file(),
                            "producedThisRun": True,
                            "sha256": sha256_file(target),
                            "sourceBackend": "headless_occt",
                        }
                    )
    finally:
        temp_context.cleanup()

    return {
        "backend": "headless_occt",
        "status": "pass",
        "stage": "save",
        "artifacts": artifacts,
        "geometryEvidence": evidence,
        "limitations": ["FEA、安全认证和制造性结论不由几何写入器提供。"],
        "retryable": False,
    }


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """@brief 独立子进程 CLI 入口。"""
    parser = argparse.ArgumentParser(description="CAD Studio OCCT/OCP 隔离几何服务")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--formats", nargs="+", required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = export_occt(args.input, args.out_dir, args.formats, overwrite=args.overwrite)
        _write_result(args.result_json, payload)
        return 0
    except Exception as exc:
        _write_result(
            args.result_json,
            {
                "backend": "headless_occt",
                "status": "blocked" if isinstance(exc, (ImportError, ModuleNotFoundError, UnsupportedFeatureError)) else "failed",
                "stage": "create",
                "artifacts": [],
                "geometryEvidence": {},
                "limitations": [str(exc)],
                "retryable": False,
                "error_code": "occt_dependency_or_capability_missing" if isinstance(exc, (ImportError, ModuleNotFoundError, UnsupportedFeatureError)) else "occt_geometry_failed",
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
