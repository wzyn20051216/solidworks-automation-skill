"""
@file _common.py
@brief 标准零件 COM 生成器共享的 SolidWorks 辅助函数。

把闭合齿廓/链轮轮廓的“画草图 -> 拉伸 -> 打孔 -> 属性 -> 审查”这条公共链路收拢在一处，
避免三个生成器重复实现。所有长度输入为毫米，进入 SolidWorks 前统一用 mm() 换算成米。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Sequence

THIS_FILE = Path(__file__).resolve()
PARENT_SKILL_DIR = THIS_FILE.parents[3]
PARENT_SCRIPT_DIR = PARENT_SKILL_DIR / "scripts"
if str(PARENT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_SCRIPT_DIR))

from sw_connect import get_com_member, mm  # noqa: E402
from sw_part import current_sketch_name, end_sketch, extrude_boss, extrude_cut, start_sketch  # noqa: E402


def validate_basename(value: str) -> str:
    """@brief 防止输出文件名逃离指定目录。"""
    name = str(value).strip()
    if not name or name in {".", ".."} or Path(name).name != name or any(
        char in name for char in '<>:"/\\|?*'
    ):
        raise ValueError("basename 必须是不含路径或 Windows 非法字符的文件名")
    return name


def clear(model) -> None:
    """@brief 清空选择集。"""
    model.ClearSelection2(True)


def assert_feature(feature, label: str):
    """@brief 检查 SolidWorks 特征对象是否创建成功。"""
    if feature is None:
        raise RuntimeError(f"{label} 创建失败")
    print(f"OK {label}: {getattr(feature, 'Name', '<未命名>')}")
    return feature


def sketch_closed_profile(model, points_mm: Sequence[tuple[float, float]], plane_name: str = "Front Plane") -> str:
    """@brief 用直线段把闭合点列画成草图轮廓（首尾自动连接）。

    @param points_mm 逆时针排列的 (x, y) 点列，单位 mm，首尾不重复。
    @return 草图名称。
    """
    points = [(float(x), float(y)) for x, y in points_mm]
    if len(points) < 3:
        raise ValueError("闭合轮廓至少需要 3 个点")
    start_sketch(model, plane_name)
    sketch_name = current_sketch_name(model, "Sketch_Profile")
    manager = model.SketchManager
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        manager.CreateLine(mm(x1), mm(y1), 0, mm(x2), mm(y2), 0)
    end_sketch(model)
    return sketch_name


def bore_center_hole(model, diameter_mm: float, plane_name: str = "Front Plane", label: str = "中心孔") -> object | None:
    """@brief 在指定基准面上以原点为圆心切一个贯穿中心孔。"""
    if diameter_mm <= 0.0:
        return None
    start_sketch(model, plane_name)
    bore_sketch = current_sketch_name(model, "Sketch_Bore")
    model.SketchManager.CreateCircleByRadius(0.0, 0.0, 0.0, mm(diameter_mm / 2.0))
    end_sketch(model)
    feature = extrude_cut(model, bore_sketch, 0)  # 0 = through all
    return assert_feature(feature, label)


def extrude_profile(model, sketch_name: str, width_mm: float, label: str) -> object:
    """@brief 将闭合轮廓对称拉伸成回转体（沿轴向中面拉伸）。"""
    feature = extrude_boss(model, sketch_name, mm(width_mm))
    return assert_feature(feature, label)


def hide_reference_planes(model) -> None:
    """@brief 导出预览前隐藏参考平面。"""
    clear(model)
    try:
        if bool(get_com_member(model, "GetVisibilityOfConstructPlanes")):
            get_com_member(model, "ViewDispRefplanes")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN 隐藏参考平面失败: {exc}")
    clear(model)


def write_properties(model, properties: Iterable[tuple[str, str]]) -> None:
    """@brief 写入文件级自定义属性。"""
    manager = model.Extension.CustomPropertyManager("")
    for name, value in properties:
        manager.Add3(str(name), 30, str(value), 2)
