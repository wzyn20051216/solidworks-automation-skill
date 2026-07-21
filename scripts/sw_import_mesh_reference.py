"""
@file sw_import_mesh_reference.py
@brief 将 OBJ/STL 网格参考模型稳定导入 SolidWorks，并保存审查结果。

这个脚本面向“高还原外观参考模型”场景：例如用户要求汽车、消费电子、
雕塑外观等公开网格模型在 SolidWorks 中作为视觉参考。它优先保留外观参考，
不把三角网格伪装成可参数编辑的 Class-A 曲面。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from .sw_connect import (
        connect_solidworks,
        create_empty_dispatch_variant,
        get_com_member,
        save_document,
    )
    from .sw_preflight import import_com_dependencies
    from .sw_review import run_review
except ImportError:
    from sw_connect import (
        connect_solidworks,
        create_empty_dispatch_variant,
        get_com_member,
        save_document,
    )
    from sw_preflight import import_com_dependencies
    from sw_review import run_review


pythoncom, _win32com_client, VARIANT = import_com_dependencies()


# 本机 SolidWorks 2024 swconst.dll 验证值。使用整数常量可以避免脚本依赖
# SolidWorks.Interop.swconst.dll 的 .NET 加载路径。
SW_IMPORT_STL_VRML_MODEL_TYPE = 208
SW_IMPORT_STL_VRML_UNITS = 210
SW_IMPORT_UNIT_PREFERENCE = 205
SW_IMPORT_STL_VRML_TEXTURE_INFORMATION = 303
SW_VRML_STL_IMPORT_AS_PS_MESH = 679
SW_VRML_STL_IMPORT_SEGMENTED = 682

SW_IMPORT_GRAPHICS_BODY = 0
SW_IMPORT_SURFACE_BODY = 1
SW_IMPORT_SOLID_BODY = 2

SW_LENGTH_UNITS = {
    "mm": 0,
    "cm": 1,
    "m": 2,
    "meter": 2,
    "meters": 2,
    "inch": 3,
    "in": 3,
    "ft": 4,
}

SW_MESH_MODEL_TYPES = {
    "graphics": SW_IMPORT_GRAPHICS_BODY,
    "surface": SW_IMPORT_SURFACE_BODY,
    "solid": SW_IMPORT_SOLID_BODY,
}


def configure_mesh_import_preferences(
    sw: Any,
    *,
    units: str = "m",
    model_type: str = "graphics",
    import_textures: bool = True,
    as_ps_mesh: bool = True,
    segmented: bool = False,
) -> dict[str, Any]:
    """
    @brief 设置 SolidWorks OBJ/STL/VRML 导入偏好。

    @param sw SolidWorks 应用 COM 对象。
    @param units 网格文件单位，默认 m。
    @param model_type graphics/surface/solid，默认 graphics，最适合高面数外观参考。
    @param import_textures 是否尝试导入纹理信息。
    @param as_ps_mesh 是否按细分/图形网格路径导入。
    @param segmented 是否分段导入网格。
    @return 偏好设置审计信息。
    """
    unit_key = units.strip().lower()
    type_key = model_type.strip().lower()
    if unit_key not in SW_LENGTH_UNITS:
        raise ValueError(f"不支持的单位: {units}")
    if type_key not in SW_MESH_MODEL_TYPES:
        raise ValueError(f"不支持的导入类型: {model_type}")

    report: dict[str, Any] = {
        "units": unit_key,
        "model_type": type_key,
        "operations": [],
    }

    int_preferences = [
        (SW_IMPORT_STL_VRML_MODEL_TYPE, SW_MESH_MODEL_TYPES[type_key]),
        (SW_IMPORT_STL_VRML_UNITS, SW_LENGTH_UNITS[unit_key]),
        (SW_IMPORT_UNIT_PREFERENCE, 0),
    ]
    for preference, value in int_preferences:
        ok = sw.SetUserPreferenceIntegerValue(preference, value)
        report["operations"].append(
            {"kind": "integer", "preference": preference, "value": value, "ok": bool(ok)}
        )

    toggle_preferences = [
        (SW_IMPORT_STL_VRML_TEXTURE_INFORMATION, bool(import_textures)),
        (SW_VRML_STL_IMPORT_AS_PS_MESH, bool(as_ps_mesh)),
        (SW_VRML_STL_IMPORT_SEGMENTED, bool(segmented)),
    ]
    for preference, value in toggle_preferences:
        # SetUserPreferenceToggle 在部分版本返回 void；没有 COM 异常即可继续，最终以导入和预览为准。
        returned = sw.SetUserPreferenceToggle(preference, value)
        report["operations"].append(
            {
                "kind": "toggle",
                "preference": preference,
                "value": value,
                "returned": returned,
            }
        )

    return report


def import_mesh_reference(
    mesh_path: str | os.PathLike[str],
    output_sldprt: str | os.PathLike[str],
    *,
    review_dir: str | os.PathLike[str] | None = None,
    units: str = "m",
    model_type: str = "graphics",
    visible: bool = True,
) -> dict[str, Any]:
    """
    @brief 导入 OBJ/STL 网格参考模型并保存为 SLDPRT。

    @param mesh_path 输入 OBJ/STL 文件路径。
    @param output_sldprt 输出 SLDPRT 文件路径。
    @param review_dir 可选审查目录，提供时会导出四视图 BMP 和 JSON 报告。
    @param units 输入网格单位。
    @param model_type graphics/surface/solid；高面数参考模型默认 graphics。
    @param visible 是否显示 SolidWorks。
    @return 导入、保存、审查结果。
    """
    mesh = Path(mesh_path).expanduser().resolve()
    output = Path(output_sldprt).expanduser().resolve()
    if mesh.suffix.lower() not in {".obj", ".stl"}:
        raise ValueError("当前脚本只处理 OBJ/STL。GLB/FBX/BLEND 请先用 Blender/trimesh 转换。")
    if not mesh.exists():
        raise FileNotFoundError(str(mesh))

    output.parent.mkdir(parents=True, exist_ok=True)
    sw, _active = connect_solidworks(visible=visible)

    result: dict[str, Any] = {
        "source": str(mesh),
        "source_size_bytes": mesh.stat().st_size,
        "output_sldprt": str(output),
        "solidworks_revision": get_com_member(sw, "RevisionNumber"),
    }
    result["import_preferences"] = configure_mesh_import_preferences(
        sw,
        units=units,
        model_type=model_type,
        import_textures=True,
        as_ps_mesh=True,
        segmented=False,
    )

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    # 关键坑位：OBJ/STL 走 LoadFile4 时不要传 None，也不要先 GetImportFileData()。
    # None 会触发“类型不匹配”；OpenDoc6 在部分 SW2024 环境中会报 2097152。
    model = sw.LoadFile4(str(mesh), "r", create_empty_dispatch_variant(), errors)
    result["loadfile4_errors"] = int(errors.value)
    result["opened"] = model is not None
    if model is None:
        raise RuntimeError(f"OBJ/STL 导入失败，LoadFile4 errors={errors.value}")

    result["title"] = get_com_member(model, "GetTitle")
    result["doc_type"] = get_com_member(model, "GetType")

    model.ClearSelection2(True)
    model.ForceRebuild3(False)
    model.ViewZoomtofit2()
    model.GraphicsRedraw2()

    saved = save_document(model, str(output))
    result["saved"] = bool(saved)
    result["output_size_bytes"] = output.stat().st_size if output.exists() else 0
    if not saved:
        raise RuntimeError(f"保存失败: {output}")

    if review_dir:
        review_base = Path(review_dir).expanduser().resolve()
        review_base.mkdir(parents=True, exist_ok=True)
        report, report_path = run_review(
            model,
            str(review_base),
            basename=output.stem,
            expected_outputs=[str(output), str(mesh)],
        )
        result["review_report"] = report_path
        result["review_evaluation"] = report.get("evaluation")
        result["review_previews"] = report.get("previews")

    return result


def _build_parser() -> argparse.ArgumentParser:
    """@brief 构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="将 OBJ/STL 网格参考模型导入 SolidWorks 并保存为 SLDPRT。"
    )
    parser.add_argument("mesh_path", help="输入 OBJ/STL 路径")
    parser.add_argument("output_sldprt", help="输出 SLDPRT 路径")
    parser.add_argument("--review-dir", help="审查输出目录")
    parser.add_argument("--units", default="m", choices=sorted(SW_LENGTH_UNITS.keys()))
    parser.add_argument(
        "--model-type",
        default="graphics",
        choices=sorted(SW_MESH_MODEL_TYPES.keys()),
        help="导入为图形体/曲面体/实体。高面数外观参考建议 graphics。",
    )
    parser.add_argument("--hidden", action="store_true", help="隐藏 SolidWorks 窗口")
    return parser


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行入口。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    result = import_mesh_reference(
        args.mesh_path,
        args.output_sldprt,
        review_dir=args.review_dir,
        units=args.units,
        model_type=args.model_type,
        visible=not args.hidden,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
