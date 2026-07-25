"""@brief 桌面原型的 mock 执行器。"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any, Callable

from .core import now_iso, read_json, write_json


LogCallback = Callable[[str], None]

STAGES = [
    ("preflight", "环境自检"),
    ("build_model", "生成模型"),
    ("export_model", "导出模型"),
    ("build_drawing", "生成图纸"),
    ("export_drawing", "导出图纸"),
    ("review", "规范复核"),
    ("package", "整理交付包"),
]

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _assert_inside(parent: Path, child: Path) -> None:
    """@brief 确保递归操作目标位于项目目录内。"""
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved not in [child_resolved, *child_resolved.parents]:
        raise RuntimeError(f"拒绝操作项目目录外路径: {child_resolved}")


def _log(callback: LogCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_parameters(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief 对 MVP P0 参数完整性做机器检查。"""
    checks: list[dict[str, Any]] = []

    def add(check_id: str, status: str, target: str, message: str, suggestion: str = "") -> None:
        checks.append(
            {
                "id": check_id,
                "severity": "P0",
                "status": status,
                "target": target,
                "message": message,
                "suggestion": suggestion,
            }
        )

    shell = parameters.get("shell", {})
    for key, label in [
        ("outer_length", "外形长度"),
        ("outer_width", "外形宽度"),
        ("outer_height", "外形高度"),
        ("wall_thickness", "壁厚"),
        ("bottom_thickness", "底厚"),
    ]:
        value = shell.get(key)
        if not _is_number(value) or value <= 0:
            add("model-main-dimensions", "fail", "model", f"{label} 缺失或不是正数", "补充外壳基础尺寸")
    if _is_number(shell.get("wall_thickness")) and shell["wall_thickness"] < 0.8:
        add("print-min-wall", "fail", "printing", "壁厚低于 0.8 mm 硬下限", "提高壁厚或确认特殊打印工艺")

    features = parameters.get("features", {})
    for group, label in [("holes", "孔"), ("cutouts", "接口开孔"), ("bosses", "螺丝柱")]:
        for item in features.get(group, []):
            item_id = item.get("id") or "未编号"
            for required in ["id", "face", "quantity", "center_x", "center_y"]:
                if item.get(required) in ("", None):
                    add(
                        f"{group}-position-complete",
                        "fail",
                        "drawing",
                        f"{label} {item_id} 缺少 {required}",
                        "补齐规格、数量和 X/Y 定位，不能只靠引线说明",
                    )
            if group == "holes" and item.get("diameter") in ("", None, 0):
                add("hole-spec-complete", "fail", "drawing", f"孔 {item_id} 缺少直径", "补充孔径")
            if group == "cutouts":
                has_rect = item.get("cutout_width") not in ("", None, 0) and item.get("cutout_height") not in ("", None, 0)
                has_round = item.get("cutout_diameter") not in ("", None, 0)
                if not has_rect and not has_round:
                    add("cutout-spec-complete", "fail", "drawing", f"接口开孔 {item_id} 缺少尺寸", "补充宽高或直径")
            if group == "bosses":
                for required in ["screw_size", "boss_outer_diameter", "hole_diameter", "boss_height"]:
                    if item.get(required) in ("", None, 0):
                        add("boss-spec-complete", "fail", "drawing", f"螺丝柱 {item_id} 缺少 {required}", "补充螺丝柱规格")

    if not any(check["status"] == "fail" for check in checks):
        checks.extend(
            [
                {
                    "id": "model-cut-through",
                    "severity": "P0",
                    "status": "pass",
                    "target": "model",
                    "message": "参数表已包含孔槽真实切除所需规格和定位",
                    "suggestion": "",
                },
                {
                    "id": "drawing-hole-position",
                    "severity": "P0",
                    "status": "pass",
                    "target": "drawing",
                    "message": "孔、接口开孔、螺丝柱均具备规格、数量和定位字段",
                    "suggestion": "",
                },
                {
                    "id": "drawing-frame-title",
                    "severity": "P0",
                    "status": "pass",
                    "target": "drawing",
                    "message": "已选择 GB/T 风格图框、标题栏、单位和比例",
                    "suggestion": "",
                },
            ]
        )
    return checks


def run_mock(project_dir: Path, callback: LogCallback | None = None) -> dict[str, Any]:
    """@brief 生成 mock 交付包和最终复核报告。"""
    project_dir = Path(project_dir)
    project = read_json(project_dir / "project.json")
    parameters = read_json(project_dir / "parameters.json")
    checks = validate_parameters(parameters)
    failed = any(item["status"] == "fail" for item in checks)

    for _, label in STAGES:
        _log(callback, f"{label} ...")

    name = project.get("project_name", "project")
    stem = Path(name).stem or "project"
    model_dir = project_dir / "outputs" / "model"
    drawing_dir = project_dir / "outputs" / "drawing"
    package_dir = project_dir / "outputs" / "package"
    reviews_dir = project_dir / "reviews"
    previews_dir = project_dir / "previews"

    outputs = {
        "sldprt": model_dir / f"{stem}.sldprt",
        "step": model_dir / f"{stem}.step",
        "stl": model_dir / f"{stem}.stl",
        "dwg": drawing_dir / f"{stem}.dwg",
        "dxf": drawing_dir / f"{stem}.dxf",
        "pdf": drawing_dir / f"{stem}.pdf",
        "preview": previews_dir / "drawing_preview.png",
    }

    if not failed:
        outputs["sldprt"].write_text("MOCK SLDPRT PLACEHOLDER - 后续版本由 SolidWorks COM 生成。\n", encoding="utf-8")
        outputs["step"].write_text("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('MOCK STEP'),'1');\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
        outputs["stl"].write_text("solid mock_shell\nendsolid mock_shell\n", encoding="utf-8")
        outputs["dwg"].write_text("MOCK DWG PLACEHOLDER - 后续版本由 AutoCAD COM 生成。\n", encoding="utf-8")
        outputs["dxf"].write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        outputs["pdf"].write_text("MOCK PDF PLACEHOLDER - 后续版本导出真实 PDF。\n", encoding="utf-8")
        outputs["preview"].write_bytes(PNG_1X1)
        (previews_dir / "model_iso.png").write_bytes(PNG_1X1)
        (previews_dir / "package_cover.png").write_bytes(PNG_1X1)

    model_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "当前为 mock 模型复核，真实几何检查将在 SolidWorks 接入后启用。",
    }
    drawing_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "当前为 mock 图纸复核，真实 DWG 尺寸实体和视觉检查将在 AutoCAD 接入后启用。",
    }
    print_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "已执行参数层面的 3D 打印硬规则检查。",
    }
    write_json(reviews_dir / "model_review.json", model_review)
    write_json(reviews_dir / "drawing_review.json", drawing_review)
    write_json(reviews_dir / "printability_review.json", print_review)

    final_review = {
        "schema_version": "0.1",
        "overall_status": "fail" if failed else "warning",
        "project_id": project.get("project_id"),
        "checked_at": now_iso(),
        "checks": checks
        + [
            {
                "id": "mock-runner-not-real-cad",
                "severity": "P1",
                "status": "warning",
                "target": "package",
                "message": "本次为桌面原型 mock 执行，CAD 文件是占位文件，不可用于制造。",
                "suggestion": "后续接入 SolidWorks/AutoCAD 后再转为可交付状态",
            }
        ],
        "outputs": {key: str(path.relative_to(project_dir)) for key, path in outputs.items()},
    }
    write_json(reviews_dir / "final_review.json", final_review)

    manifest = {
        "schema_version": "0.1",
        "generated_at": now_iso(),
        "project_name": project.get("project_name", "CAD 项目"),
        "status": final_review["overall_status"],
        "files": [
            {"kind": key, "path": str(path.relative_to(project_dir)), "exists": path.exists()}
            for key, path in outputs.items()
        ]
        + [
            {"kind": "review", "path": "reviews/final_review.json", "exists": True},
            {"kind": "source", "path": "parameters.json", "exists": True},
            {"kind": "source", "path": "project.json", "exists": True},
        ],
    }
    write_json(project_dir / "outputs" / "manifest.json", manifest)

    readme = project_dir / "README_交付说明.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project.get('project_name', 'CAD 项目')} 交付说明",
                "",
                "- 单位: mm",
                "- 图纸风格: GB/T 风格",
                "- 当前状态: mock 原型输出，不能直接制造",
                "- 复核报告: reviews/final_review.json",
                "- 后续: 接入 SolidWorks/AutoCAD 后输出真实 SLDPRT/STEP/STL/DWG/DXF/PDF",
                "",
            ]
        ),
        encoding="utf-8",
    )

    delivery = package_dir / f"{stem}_delivery"
    if delivery.exists():
        _assert_inside(project_dir, delivery)
        shutil.rmtree(delivery)
    delivery.mkdir(parents=True)
    for rel in ["project.json", "parameters.json", "README_交付说明.md", "outputs/manifest.json"]:
        shutil.copy2(project_dir / rel, delivery / Path(rel).name)
    shutil.copytree(reviews_dir, delivery / "reviews")

    project["updated_at"] = now_iso()
    project["status"] = final_review["overall_status"]
    write_json(project_dir / "project.json", project)
    _log(callback, f"已生成 mock 交付目录: {delivery}")
    return final_review
