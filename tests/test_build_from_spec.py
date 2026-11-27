"""规格执行器回归测试。

重点锁定真机实测发现的两个缺陷：

1. 单位换算：规格用毫米，而 ``sw_hole_features`` 的 center/diameter/depth 与
   ``sw_part.fillet`` 一律期望**米**。把毫米直接传进去会得到 1000 倍大的草图，
   SolidWorks 静默拒绝切除（"特征创建成功但不存在"），实测把 100mm 的板撑到 13300mm。
2. 变量遮蔽：圆角循环用 ``fillet`` 作循环变量，遮蔽了同名的 fillet 函数，
   使 ``fillet(model, radius)`` 变成调用 dict。

本模块用 unittest.mock 在用例内替换依赖，避免污染其它测试文件的模块缓存。
"""
from pathlib import Path
import sys
import types
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.build_from_spec as build_from_spec  # noqa: E402


class FakeModel:
    """文档替身。"""

    def __init__(self):
        self.rebuilds = 0
        self.cleared = 0

    def ForceRebuild3(self, _silent):
        self.rebuilds += 1
        return True

    def ClearSelection2(self, _all):
        self.cleared += 1
        return True


@pytest.fixture
def harness(monkeypatch):
    """
    替换 build_from_spec 的全部外部依赖，返回记录调用参数的容器。

    只 patch 该模块自己的绑定，不影响其它测试文件。
    """
    record = {"holes": [], "part": []}

    def make_creator(kind):
        def creator(model, hole):
            record["holes"].append({"kind": kind, "hole": hole})
            return {"feature_kind": kind, "feature_names": (hole.get("id"),)}
        return creator

    def through(model, center=None, diameter=None, name="孔", **kwargs):
        record["holes"].append({"kind": "through", "center": center, "diameter": diameter, "name": name})

        return {"feature_kind": "through", "feature_names": (name,), "center_m": center, "diameter_m": diameter}

    def blind(model, center=None, diameter=None, depth=None, name="孔", **kwargs):
        record["holes"].append({"kind": "blind", "center": center, "diameter": diameter, "depth": depth, "name": name})
        return {"feature_kind": "blind", "feature_names": (name,)}

    def counterbore(model, center=None, hole_diameter=None, counterbore_diameter=None,
                    counterbore_depth=None, name="孔", **kwargs):
        record["holes"].append({
            "kind": "counterbore", "center": center, "diameter": hole_diameter,
            "counterbore_diameter": counterbore_diameter,
            "counterbore_depth": counterbore_depth, "name": name,
        })
        return {"feature_kind": "counterbore", "feature_names": (name,)}

    def countersink(model, center=None, hole_diameter=None, countersink_diameter=None,
                    included_angle_deg=None, name="孔", **kwargs):
        record["holes"].append({
            "kind": "countersink", "center": center, "diameter": hole_diameter,
            "countersink_diameter": countersink_diameter,
            "included_angle_deg": included_angle_deg, "name": name,
        })
        return {"feature_kind": "countersink", "feature_names": (name,)}

    monkeypatch.setattr(build_from_spec, "create_through_hole", through)
    monkeypatch.setattr(build_from_spec, "create_blind_hole", blind)
    monkeypatch.setattr(build_from_spec, "create_counterbore_hole", counterbore)
    monkeypatch.setattr(build_from_spec, "create_countersink_hole", countersink)

    def corner_rectangle(model, x1, y1, x2, y2):
        record["part"].append(("corner_rectangle", x1, y1, x2, y2))

    def circle(model, cx, cy, radius):
        record["part"].append(("circle", cx, cy, radius))

    def extrude_boss(model, sketch_name, depth, **kwargs):
        record["part"].append(("extrude_boss", sketch_name, depth))
        return types.SimpleNamespace(Name="Boss-Extrude1")

    def fillet(model, radius, edges=None):
        record["part"].append(("fillet", radius))
        return types.SimpleNamespace(Name="Fillet1")

    class FakeSketchManager:
        """草图上下文管理器替身。"""

        def __init__(self, outer):
            self._outer = outer

        def __enter__(self):
            return "Sketch1"

        def __exit__(self, *_):
            return False

    def sketch(model, plane_name="Front Plane"):
        record["part"].append(("sketch", plane_name))
        return FakeSketchManager(record)

    monkeypatch.setattr(build_from_spec, "sketch_corner_rectangle", corner_rectangle)
    monkeypatch.setattr(build_from_spec, "sketch_circle", circle)
    monkeypatch.setattr(build_from_spec, "extrude_boss", extrude_boss)
    monkeypatch.setattr(build_from_spec, "fillet", fillet)
    monkeypatch.setattr(build_from_spec, "sketch", sketch)

    monkeypatch.setattr(
        build_from_spec, "select_edges",
        lambda model, spec: {"status": "ok", "selected_count": 4, "selected": []},
    )
    monkeypatch.setattr(
        build_from_spec.sw_measure, "collect_bounding_box",
        lambda model: {"size_mm": [100.0, 60.0, 6.0], "errors": []},
    )
    monkeypatch.setattr(
        build_from_spec.sw_measure, "collect_mass_properties",
        lambda model: {"mass_g": 500.0, "errors": []},
    )
    return record


def base_spec(**overrides):
    """构造归一化后的规格。"""
    spec = {
        "schema_version": "1.0",
        "part_name": "bracket",
        "source_units": "mm",
        "base": {"type": "rect_plate", "width_mm": 100.0, "height_mm": 60.0, "thickness_mm": 6.0},
        "holes": [],
        "fillets": [],
        "verify": {},
    }
    spec.update(overrides)
    return spec


def run(spec, harness, **kwargs):
    """执行构建并返回 (结果, 调用记录)。"""
    kwargs.setdefault("apply_fillets", False)
    kwargs.setdefault("verify_geometry", False)
    return build_from_spec.build_from_spec(FakeModel(), spec, **kwargs), harness


# ------------------------------------------------------------ 单位换算

def test_hole_arguments_converted_to_metres(harness):
    """@brief 核心缺陷：孔的中心与直径必须从毫米换算为米。

    未换算时圆心 x=10(mm) 会被当成 10 米，实测把 100x60 的板撑到 13300mm。
    """
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0]}
    ])

    result, record = run(spec, harness)

    assert len(record["holes"]) == 1
    hole = record["holes"][0]
    assert hole["kind"] == "through"
    # 关键断言：传进 sw_hole_features 的必须是米
    assert hole["center"] == pytest.approx((0.010, 0.010))
    assert hole["diameter"] == pytest.approx(0.0066)
    assert result["hole_count_created"] == 1


def test_hole_center_helper_converts_mm_to_m():
    """@brief _hole_center_m 是毫米到米的唯一转换点，必须正确。"""
    center = build_from_spec._hole_center_m({"position_mm": [10.0, 20.0, 0.0]})

    assert center == pytest.approx((0.010, 0.020))


def test_blind_hole_depth_converted_to_metres(harness):
    """@brief 盲孔深度换算为米。"""
    spec = base_spec(holes=[
        {"id": "H1", "type": "blind", "diameter_mm": 5.0, "depth_mm": 6.0, "position_mm": [10.0, 10.0, 0.0]}
    ])

    result, record = run(spec, harness)

    assert record["holes"][0]["depth"] == pytest.approx(0.006)
    assert result["hole_count_created"] == 1


def test_counterbore_dimensions_converted_to_metres(harness):
    """@brief 沉头孔的三组尺寸都要换算。"""
    spec = base_spec(holes=[{
        "id": "H1", "type": "counterbore", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0],
        "counterbore_diameter_mm": 11.0, "counterbore_depth_mm": 6.0,
    }])

    result, record = run(spec, harness)

    hole = record["holes"][0]
    assert hole["kind"] == "counterbore"
    assert hole["diameter"] == pytest.approx(0.0066)
    assert hole["counterbore_diameter"] == pytest.approx(0.011)
    assert hole["counterbore_depth"] == pytest.approx(0.006)
    assert result["hole_count_created"] == 1


def test_countersink_angle_passed_through_unconverted(harness):
    """@brief 锥沉孔角度是度，不做单位换算。"""
    spec = base_spec(holes=[{
        "id": "H1", "type": "countersink", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0],
        "countersink_diameter_mm": 12.0, "angle_deg": 82.0,
    }])

    result, record = run(spec, harness)

    hole = record["holes"][0]
    assert hole["kind"] == "countersink"
    assert hole["countersink_diameter"] == pytest.approx(0.012)
    assert hole["included_angle_deg"] == 82.0
    assert result["hole_count_created"] == 1


def test_base_plate_origin_at_lower_left_corner(harness):
    """@brief 板料原点在左下角，规格孔位可直接按图纸标注。

    旧实现把板居中于原点（-50..50），导致按图纸标的 90mm 孔位落到板外。
    """
    result, record = run(base_spec(), harness)

    rectangle = next(call for call in record["part"] if call[0] == "corner_rectangle")
    assert rectangle[1:3] == pytest.approx((0.0, 0.0))
    assert rectangle[3:5] == pytest.approx((0.1, 0.06))


def test_base_plate_thickness_converted(harness):
    """@brief 厚度换算为米。"""
    result, record = run(base_spec(), harness)

    extrude = next(call for call in record["part"] if call[0] == "extrude_boss")
    assert extrude[2] == pytest.approx(0.006)


def test_cylinder_base_diameter_converted(harness):
    """@brief 圆柱基体直径换算为米（半径 = 直径/2）。"""
    spec = base_spec(base={"type": "cylinder", "diameter_mm": 50.0, "height_mm": 80.0})

    result, record = run(spec, harness)

    circle = next(call for call in record["part"] if call[0] == "circle")
    assert circle[3] == pytest.approx(0.025)


# ------------------------------------------------------------ 越界校验

def test_hole_outside_plate_is_rejected_before_building(harness):
    """@brief 孔位越界必须在建孔前报错，否则得到的是一串误导性的"特征未创建"。"""
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [200.0, 10.0, 0.0]}
    ])

    result, record = run(spec, harness)

    assert result["status"] == "error"
    assert any("超出了板料范围" in item for item in result["errors"])
    assert record["holes"] == []


def test_hole_touching_edge_is_rejected(harness):
    """@brief 孔壁超出边界（而非仅圆心）也算越界。"""
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 20.0, "position_mm": [3.0, 30.0, 0.0]}
    ])

    result, _ = run(spec, harness)

    assert result["status"] == "error"
    assert any("超出了板料范围" in item for item in result["errors"])


def test_valid_corner_holes_pass_bounds_check(harness):
    """@brief 板内四角孔应通过校验并全部创建。"""
    spec = base_spec(holes=[
        {"id": f"H{index}", "type": "through", "diameter_mm": 6.6, "position_mm": position + [0.0]}
        for index, position in enumerate([[10.0, 10.0], [90.0, 10.0], [10.0, 50.0], [90.0, 50.0]], start=1)
    ])

    result, _ = run(spec, harness)

    assert result["hole_count_created"] == 4
    assert result["errors"] == []


def test_cylinder_hole_outside_radius_rejected(harness):
    """@brief 圆柱基体上的孔超出半径要报错。"""
    spec = base_spec(
        base={"type": "cylinder", "diameter_mm": 50.0, "height_mm": 10.0},
        holes=[{"id": "H1", "type": "through", "diameter_mm": 5.0, "position_mm": [40.0, 0.0, 0.0]}],
    )

    result, _ = run(spec, harness)

    assert any("超出圆柱半径" in item for item in result["errors"])


# ------------------------------------------------------------ 结果判定

def test_hole_feature_names_key_is_read_correctly(harness):
    """@brief HoleFeatureEvidence 的键是 feature_names，不是 status/feature_name。

    旧实现读不存在的 "status" 键，把成功的孔判成失败。
    """
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0]}
    ])

    result, _ = run(spec, harness)

    assert result["hole_count_created"] == 1
    assert not any("未成功创建" in item for item in result["errors"])
    step = next(item for item in result["steps"] if item["step"] == "hole")
    assert step["ok"] is True
    assert step["feature"] == "H1"


def test_missing_feature_names_marks_hole_failed(harness, monkeypatch):
    """@brief 特征名为空视为失败，不能算成功。"""
    monkeypatch.setattr(
        build_from_spec, "create_through_hole",
        lambda model, hole: {"feature_kind": "through", "feature_names": ()},
    )
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0]}
    ])

    result, _ = run(spec, harness)

    assert result["status"] == "error"
    assert result["hole_count_created"] == 0


def test_creator_exception_is_recorded_not_raised(harness, monkeypatch):
    """@brief 单个孔创建抛异常时记录并继续，不中断整个构建。"""

    def raising(model, center=None, diameter=None, name="H", **kwargs):
        if name == "H2":
            raise RuntimeError("boom")
        return {"feature_kind": "through", "feature_names": (name,)}

    monkeypatch.setattr(build_from_spec, "create_through_hole", raising)
    spec = base_spec(holes=[
        {"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0]},
        {"id": "H2", "type": "through", "diameter_mm": 6.6, "position_mm": [90.0, 10.0, 0.0]},
    ])

    result, _ = run(spec, harness)

    assert any("H2" in item for item in result["errors"])
    assert result["hole_count_created"] == 1


# ------------------------------------------------------------ 孔阵列展开

def test_circular_pattern_expands_evenly():
    """@brief 圆周阵列按等分角展开并重新编号。"""
    holes = [{
        "id": "B", "type": "through", "diameter_mm": 5.0, "position_mm": [0.0, 0.0, 0.0],
        "pattern": {"type": "circular", "count": 6, "radius": 30.0, "start_angle": 0.0},
    }]

    expanded = build_from_spec.expand_hole_patterns(holes)

    assert len(expanded) == 6
    assert expanded[0]["id"] == "B_1"
    assert expanded[0]["position_mm"][:2] == pytest.approx([30.0, 0.0])
    assert expanded[3]["position_mm"][:2] == pytest.approx([-30.0, 0.0], abs=1e-6)


def test_linear_pattern_expands_along_direction():
    """@brief 线性阵列沿 dx/dy 展开。"""
    holes = [{
        "id": "L", "type": "through", "diameter_mm": 5.0, "position_mm": [10.0, 10.0, 0.0],
        "pattern": {"type": "linear", "count": 4, "dx": 20.0, "dy": 0.0},
    }]

    expanded = build_from_spec.expand_hole_patterns(holes)

    assert len(expanded) == 4
    assert [hole["position_mm"][0] for hole in expanded] == pytest.approx([10.0, 30.0, 50.0, 70.0])


def test_hole_without_pattern_is_copied_not_aliased():
    """@brief 无阵列的孔原样保留，但复制而非引用。"""
    holes = [{"id": "H1", "type": "through", "diameter_mm": 5.0, "position_mm": [1.0, 2.0, 0.0]}]

    expanded = build_from_spec.expand_hole_patterns(holes)

    assert expanded[0] is not holes[0]
    assert expanded[0]["position_mm"] == [1.0, 2.0, 0.0]


def test_pattern_count_is_clamped():
    """@brief 异常的阵列数量被夹到合理范围，避免生成海量几何。"""
    holes = [{
        "id": "B", "type": "through", "diameter_mm": 5.0, "position_mm": [0.0, 0.0, 0.0],
        "pattern": {"type": "circular", "count": 10**6, "radius": 30.0},
    }]

    expanded = build_from_spec.expand_hole_patterns(holes)

    assert len(expanded) <= 200


def test_unknown_pattern_type_preserves_original_hole():
    """@brief 未知阵列类型时保留原孔而不是丢弃。"""
    holes = [{
        "id": "B", "type": "through", "diameter_mm": 5.0, "position_mm": [1.0, 2.0, 0.0],
        "pattern": {"type": "spiral", "count": 4},
    }]

    expanded = build_from_spec.expand_hole_patterns(holes)

    assert len(expanded) == 1
    assert expanded[0]["position_mm"] == [1.0, 2.0, 0.0]


# ------------------------------------------------------------ 圆角

def test_fillet_radius_converted_to_metres(harness):
    """@brief 圆角半径换算为米。"""
    spec = base_spec(fillets=[{"radius_mm": 4.0, "axis": "z"}])

    result, record = run(spec, harness, apply_fillets=True)

    fillet_call = next(call for call in record["part"] if call[0] == "fillet")
    assert fillet_call[1] == pytest.approx(0.004)


def test_fillet_loop_variable_does_not_shadow_function(harness):
    """@brief 核心缺陷：循环变量曾命名为 fillet，遮蔽同名函数导致 'dict' not callable。

    只要圆角能真正被调用（record 里有 fillet 记录）就说明没有被遮蔽。
    """
    spec = base_spec(fillets=[{"radius_mm": 2.0, "axis": "z"}, {"radius_mm": 3.0, "axis": "z"}])

    result, record = run(spec, harness, apply_fillets=True)

    fillet_calls = [call for call in record["part"] if call[0] == "fillet"]
    assert len(fillet_calls) == 2
    assert [call[1] for call in fillet_calls] == pytest.approx([0.002, 0.003])


def test_fillet_skipped_when_no_edges_match(harness, monkeypatch):
    """@brief 选不到边时跳过圆角并给出提示，不静默对当前选择集操作。"""
    monkeypatch.setattr(
        build_from_spec, "select_edges",
        lambda model, spec: {"status": "error", "selected_count": 0, "errors": ["none"]},
    )
    spec = base_spec(fillets=[{"radius_mm": 4.0, "axis": "z"}])

    result, record = run(spec, harness, apply_fillets=True)

    assert any("未选中任何边线" in item for item in result["warnings"])
    assert not any(call[0] == "fillet" for call in record["part"])


def test_fillet_failure_is_warning_not_error(harness, monkeypatch):
    """@brief 圆角失败只记警告，已建成的实体不回滚。"""
    def failing_fillet(model, radius, edges=None):
        raise RuntimeError("半径过大")

    monkeypatch.setattr(build_from_spec, "fillet", failing_fillet)
    spec = base_spec(fillets=[{"radius_mm": 50.0, "axis": "z"}])

    result, _ = run(spec, harness, apply_fillets=True)

    assert any("圆角 0 失败" in item for item in result["warnings"])
    assert result["status"] in ("ok", "warn")


# ------------------------------------------------------------ 验证

def test_verification_runs_and_reports(harness, monkeypatch):
    """@brief 开启验证时比对实测与期望。"""
    monkeypatch.setattr(
        build_from_spec.sw_measure, "collect_exact_part_bounding_box",
        lambda model: {"size_mm": [100.0, 60.0, 6.0], "errors": []},
    )
    spec = base_spec(
        holes=[{"id": "H1", "type": "through", "diameter_mm": 6.6, "position_mm": [10.0, 10.0, 0.0]}],
        verify={"envelope_mm": [100.0, 60.0, 6.0], "hole_count": 1, "tolerance_mm": 0.1},
    )

    result, _ = run(spec, harness, verify_geometry=True)

    assert result["verification"]["status"] == "pass"
    assert result["measurements"]["bounding_box"]["size_mm"] == [100.0, 60.0, 6.0]


def test_verification_flags_dimension_mismatch(harness, monkeypatch):
    """@brief 实测尺寸与规格不符时报告警告并要求复核。"""
    monkeypatch.setattr(
        build_from_spec.sw_measure, "collect_exact_part_bounding_box",
        lambda model: {"size_mm": [999.0, 60.0, 6.0], "errors": []},
    )
    spec = base_spec(verify={"envelope_mm": [100.0, 60.0, 6.0], "tolerance_mm": 0.1})

    result, _ = run(spec, harness, verify_geometry=True)

    assert result["verification"]["status"] == "warn"
    assert "envelope_mm" in result["verification"]["failed"]


@pytest.mark.parametrize("extreme_available", [True, False])
def test_envelope_verification_does_not_use_approximate_box(harness, monkeypatch, extreme_available):
    """精确外形由实体极值决定，极值失败时近似包围盒不能充当验收证据。"""
    expected_mm = [100.0, 60.0, 6.0]
    approximate_mm = [100.0, 60.0, 6.4] if extreme_available else expected_mm
    monkeypatch.setattr(
        build_from_spec.sw_measure, "collect_bounding_box",
        lambda model: {"size_mm": approximate_mm, "errors": []},
    )
    model = FakeModel()
    model.GetType = lambda: 1

    def extreme(dx, dy, dz, *_outputs):
        direction = (dx, dy, dz)
        point = tuple(size / 1000 if component > 0 else 0.0
                      for size, component in zip(expected_mm, direction))
        return extreme_available, *point

    model.GetBodies2 = lambda _kind, _visible_only: [types.SimpleNamespace(GetExtremePoint=extreme)]
    result = build_from_spec.build_from_spec(
        model, base_spec(verify={"envelope_mm": expected_mm, "tolerance_mm": 0.1}),
    )

    check = result["verification"]["checks"][0]
    assert check["name"] == "envelope_mm"
    assert check["passed"] is extreme_available
    assert check["actual"] == (expected_mm if extreme_available else None)
    assert bool(result["measurements"]["errors"]) is not extreme_available


def test_base_none_skips_solid_creation(harness):
    """@brief base.type="none" 时只建后续特征。"""
    spec = base_spec(base={"type": "none"})

    result, record = run(spec, harness)

    assert not any(call[0] == "extrude_boss" for call in record["part"])
    assert result["steps"][0]["ok"] is True


def test_mass_properties_included_in_measurements(harness):
    """@brief 测量结果里应同时包含包围盒与质量属性。"""
    result, _ = run(base_spec(), harness, verify_geometry=True)

    assert result["measurements"]["mass_properties"]["mass_g"] == 500.0
