"""@brief 探测本机 SolidWorks 类型库与高级机械能力，不修改任何 CAD 文档。"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

try:
    from .sw_preflight import import_com_dependencies, missing_com_dependencies, solidworks_installed
except ImportError:
    from sw_preflight import import_com_dependencies, missing_com_dependencies, solidworks_installed


TYPELIB_PATTERNS = {
    "solidworks_core": [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\sldworks.tlb",
        r"E:\Solidworks\SOLIDWORKS\sldworks.tlb",
    ],
    "motion_study": [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\swmotionstudy.tlb",
        r"E:\Solidworks\SOLIDWORKS\swmotionstudy.tlb",
    ],
    "routing": [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\SWRoutingLib.tlb",
        r"E:\Solidworks\SOLIDWORKS\SWRoutingLib.tlb",
    ],
    "simulation_motion": [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS*\cmotionswapi.tlb",
        r"E:\Solidworks\SOLIDWORKS\cmotionswapi.tlb",
    ],
}

CAPABILITY_KEYWORDS = {
    "part_and_features": ("IPartDoc", "IFeatureManager", "ISketchManager"),
    "assembly_and_mates": ("IAssemblyDoc", "IMateFeatureData"),
    "configurations": ("IConfigurationManager", "IConfiguration"),
    "drawings": ("IDrawingDoc", "IView", "ITableAnnotation"),
    "sheet_metal": ("ISheetMetalFeatureData", "IFlatPatternFeatureData"),
    "weldments": ("IStructuralMemberFeatureData", "IWeldmentCutListFeature"),
    "surface_modeling": ("ISurface", "IKnitSurfaceFeatureData"),
    "mold_tools": ("IMold", "ICavityFeatureData"),
    "motion_study": ("IMotionStudyManager", "IMotionStudy", "IMotionStudyResults"),
    "routing": ("IRoute", "IRoutingComponent"),
}

IMPLEMENTATION_STATUS = {
    "part_and_features": "verified",
    "assembly_and_mates": "verified",
    "configurations": "reference_only",
    "drawings": "pilot",
    "sheet_metal": "reference_only",
    "weldments": "reference_only",
    "surface_modeling": "reference_only",
    "mold_tools": "not_implemented",
    "motion_study": "verified_rotary_motor_and_audit",
    "routing": "not_implemented",
}


def _find_typelib(patterns: list[str]) -> Path | None:
    """@brief 返回第一个实际存在的类型库。"""
    for pattern in patterns:
        for raw_path in glob.glob(os.path.expandvars(pattern)):
            path = Path(raw_path).resolve()
            if path.is_file():
                return path
    return None


def _type_names(pythoncom, path: Path) -> list[str]:
    """@brief 从类型库读取接口/枚举名称。"""
    library = pythoncom.LoadTypeLib(str(path))
    return sorted(
        {
            str(library.GetDocumentation(index)[0])
            for index in range(library.GetTypeInfoCount())
            if library.GetDocumentation(index)[0]
        }
    )


def probe_capabilities() -> dict:
    """@brief 生成不夸大实现状态的机器可读能力报告。"""
    missing = missing_com_dependencies()
    report = {
        "schema_version": "1.0",
        "solidworks_detected": solidworks_installed(),
        "missing_com_dependencies": missing,
        "type_libraries": {},
        "capabilities": {},
        "notes": [
            "type_library_present 只证明本机安装包含接口定义，不证明许可证、当前文档或自动化实现已验证。",
            "implementation_status=reference_only/not_implemented 的能力禁止自动宣称完成。",
        ],
    }
    if missing:
        return report
    pythoncom, _client, _variant = import_com_dependencies(allow_install=False)
    all_types: set[str] = set()
    for name, patterns in TYPELIB_PATTERNS.items():
        path = _find_typelib(patterns)
        item = {"present": path is not None, "path": str(path) if path else None, "type_count": 0}
        if path:
            try:
                names = _type_names(pythoncom, path)
                item["type_count"] = len(names)
                all_types.update(names)
            except Exception as exc:
                item["error"] = str(exc)
        report["type_libraries"][name] = item

    lowered_types = {name.lower() for name in all_types}
    for capability, interface_names in CAPABILITY_KEYWORDS.items():
        matches = [name for name in interface_names if name.lower() in lowered_types]
        report["capabilities"][capability] = {
            "interfaces_found": matches,
            "interface_coverage": len(matches) / len(interface_names),
            "implementation_status": IMPLEMENTATION_STATUS[capability],
            "ready_for_unattended_use": IMPLEMENTATION_STATUS[capability].startswith("verified") and len(matches) == len(interface_names),
        }
    return report


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="探测 SolidWorks 高级机械能力和本机类型库。")
    parser.add_argument("--output", type=Path, help="可选 JSON 输出路径。")
    args = parser.parse_args()
    report = probe_capabilities()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["solidworks_detected"] and not report["missing_com_dependencies"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
