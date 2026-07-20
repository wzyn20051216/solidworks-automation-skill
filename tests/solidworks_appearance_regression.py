#!/usr/bin/env python
"""SolidWorks 外观数组 COM 编组回归测试。"""

from __future__ import annotations

import math
import tempfile
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from sw_appearance import apply_component_palette, rgb01, set_document_appearance
from sw_assembly import add_component
from sw_connect import get_com_member, mm
from sw_part import extrude_midplane, sketch, sketch_rectangle
from sw_session import SolidWorksSession


def assert_rgb(actual, expected, label: str, tolerance: float = 1e-6) -> None:
    """@brief 检查材质数组前三位是否为预期 RGB。"""
    if actual is None or len(actual) < 3:
        raise AssertionError(f"{label}: 无法读取材质数组: {actual!r}")
    for channel, actual_value, expected_value in zip("RGB", actual[:3], expected):
        if not math.isclose(float(actual_value), float(expected_value), abs_tol=tolerance):
            raise AssertionError(
                f"{label}: {channel} 通道错误，实际 {actual[:3]!r}，预期 {expected!r}"
            )


def main() -> int:
    """@brief 验证文档级和装配组件级 RGB 均可正确回读。"""
    session = SolidWorksSession(visible=True)
    model = session.new_part()
    temp_dir = Path(tempfile.gettempdir()) / "solidworks_appearance_regression"
    temp_dir.mkdir(parents=True, exist_ok=True)
    part_path = temp_dir / "appearance_block.SLDPRT"
    assembly_title = ""
    cases = {"red": "#E31B35", "blue": "#2AA8FF"}
    try:
        session.sw.CloseDoc(part_path.name)
        for label, color in cases.items():
            if not set_document_appearance(model, color):
                raise AssertionError(f"{label}: 外观写入函数返回失败")
            assert_rgb(model.MaterialPropertyValues, rgb01(color), label)

        active_configuration = get_com_member(
            get_com_member(model, "ConfigurationManager"), "ActiveConfiguration"
        )
        configuration_name = str(get_com_member(active_configuration, "Name"))
        configuration_color = "#4FA6A8"
        if not set_document_appearance(model, configuration_color, configuration_name):
            raise AssertionError("指定配置外观写入函数返回失败")
        assert_rgb(
            model.MaterialPropertyValues,
            rgb01(configuration_color),
            "configured_aqua",
        )

        with sketch(model, "Front Plane") as sketch_ref:
            sketch_rectangle(model, 0, 0, mm(20), mm(20))
        if extrude_midplane(model, sketch_ref, mm(20)) is None:
            raise AssertionError("组件测试块拉伸失败")
        if not session.save(model, str(part_path)):
            raise AssertionError("组件测试块保存失败")
        part_title = str(get_com_member(model, "GetTitle"))
        session.sw.CloseDoc(part_title)

        assembly = session.new_assembly()
        assembly_title = str(get_com_member(assembly, "GetTitle"))
        component = add_component(assembly, str(part_path), sw=session.sw)
        if component is None:
            raise AssertionError("组件测试块添加失败")
        component_color = "#C7CCD1"
        reports = apply_component_palette([(component, component_color)])
        if not reports[0]["ok"]:
            raise AssertionError(f"组件级外观写入失败: {reports[0]}")
        assert_rgb(
            component.MaterialPropertyValues,
            rgb01(component_color),
            "component_silver",
        )
        print("appearance_roundtrip_ok")
        return 0
    finally:
        if assembly_title:
            session.sw.CloseDoc(assembly_title)
        session.sw.CloseDoc(part_path.name)
        try:
            title = str(get_com_member(model, "GetTitle"))
            if title:
                session.sw.CloseDoc(title)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
