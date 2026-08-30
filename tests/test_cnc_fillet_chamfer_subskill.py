"""@brief solidworks-fillet-chamfer-cnc 子技能的离线工程逻辑回归测试。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "subskills" / "solidworks-fillet-chamfer-cnc" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import cnc_strategy as strategy  # noqa: E402


def test_default_parameters_pass_and_keep_dowels_clear_of_center_slot() -> None:
    """@brief 默认定位孔不得再与中心长圆槽相交。"""
    params, report = strategy.build_parameters()

    assert report["errors"] == []
    assert report["status"] == "pass_with_warnings"
    assert strategy.parameter_positions(params)["dowel"] == [(-0.0, -24.0), (0.0, 24.0)]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"dowel_hole_x": 32.0, "dowel_hole_y": 0.0}, "中心槽"),
        ({"counterbore_diameter": 6.0}, "counterbore_diameter"),
        ({"counterbore_depth": 16.0}, "minimum_bottom_wall"),
        ({"pocket_center_x": 55.0}, "减重口袋"),
        ({"chamfer_angle_deg": 90.0}, "chamfer_angle_deg"),
        ({"base_corner_radius": float("nan")}, "有限数值"),
    ],
)
def test_invalid_engineering_parameters_block_before_com(overrides, message) -> None:
    """@brief 孔槽碰撞和不可制造尺寸必须在 COM 调用前阻断。"""
    with pytest.raises(ValueError, match=message):
        strategy.build_parameters(overrides)


def test_rectangle_pocket_is_allowed_but_requires_dfm_warning() -> None:
    """@brief 尖角矩形口袋不能被误报为 CNC 友好结构。"""
    _params, report = strategy.build_parameters({"pocket_shape": "rectangle"})

    assert any("尖锐内角" in warning for warning in report["warnings"])


def test_operation_plan_has_exact_edge_counts_and_bounded_fallbacks() -> None:
    """@brief 操作计划必须声明边数，并限制降级次数和下限。"""
    params, _report = strategy.build_parameters()
    progressive = strategy.build_operation_plan(params, "progressive")
    strict = strategy.build_operation_plan(params, "strict")

    by_name = {item["name"]: item for item in progressive}
    assert by_name["Fillet_Base_Corners"]["expected_edge_count"] == 4
    assert by_name["Chamfer_Top_Outer"]["expected_edge_count"] == 8
    assert by_name["Chamfer_Hole_Mouths"]["expected_edge_count"] == 6
    assert by_name["Fillet_Base_Corners"]["attempt_values_mm"] == [8.0, 6.0, 4.0]
    assert all(len(item["attempt_values_mm"]) == 1 for item in strict)


def test_zero_treatment_disables_operation_and_updates_expected_topology() -> None:
    """@brief 禁用立角圆角后，顶边闭环应从八边恢复为四边。"""
    params, _report = strategy.build_parameters(
        {"base_corner_radius": 0.0, "boss_corner_radius": 0.0}
    )
    plan = strategy.build_operation_plan(params)
    by_name = {item["name"]: item for item in plan}

    assert "Fillet_Base_Corners" not in by_name
    assert "Fillet_Boss_Corners" not in by_name
    assert by_name["Chamfer_Top_Outer"]["expected_edge_count"] == 4
    assert by_name["Chamfer_Boss_Top"]["expected_edge_count"] == 4


def test_set_parser_rejects_unknown_or_malformed_values() -> None:
    """@brief 通用参数覆盖不能静默接受拼写错误。"""
    assert strategy.parse_set_values(["base_corner_radius=6"]) == {
        "base_corner_radius": 6.0
    }
    with pytest.raises(ValueError, match="未知参数"):
        strategy.parse_set_values(["base_corner_raduis=6"])
    with pytest.raises(ValueError, match="name=value"):
        strategy.parse_set_values(["base_corner_radius"])


@pytest.mark.parametrize("basename", ["../escape", "folder/name", "bad:name", ".."])
def test_basename_cannot_escape_output_directory(basename) -> None:
    """@brief 输出基名不能携带路径或 Windows 非法字符。"""
    with pytest.raises(ValueError):
        strategy.validate_basename(basename)


def test_json_parameter_file_supports_wrapped_payload(tmp_path: Path) -> None:
    """@brief VibeCAD/桌面端可复用 parameters 包装格式。"""
    path = tmp_path / "params.json"
    path.write_text(
        json.dumps({"schema_version": 2, "parameters": {"top_chamfer": 1.25}}),
        encoding="utf-8",
    )

    assert strategy.load_parameter_file(path) == {"top_chamfer": 1.25}


def test_dry_run_cli_writes_plan_without_solidworks(tmp_path: Path) -> None:
    """@brief --dry-run 必须在无 COM 建模副作用时生成完整计划。"""
    script = SCRIPT_DIR / "create_cnc_mount_template.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dry-run",
            "--failure-policy",
            "strict",
            "--set",
            "top_chamfer=1.25",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads((tmp_path / "CNC_Mount_Template_plan.json").read_text(encoding="utf-8"))

    assert "planned" in completed.stdout
    assert payload["schema_version"] == 2
    assert payload["failure_policy"] == "strict"
    assert payload["parameters"]["top_chamfer"] == pytest.approx(1.25)


def test_exact_edge_selection_refuses_ambiguous_topology(monkeypatch) -> None:
    """@brief 匹配数量异常时不得继续创建圆角或倒角。"""
    spec = importlib.util.spec_from_file_location(
        "cnc_mount_template_for_test",
        SCRIPT_DIR / "create_cnc_mount_template.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FakeModel:
        """@brief 提供精确选边函数所需的最小模型接口。"""

        def ClearSelection2(self, _clear_all):
            return True

    fake_edges = [object(), object()]
    monkeypatch.setattr(module, "matching_edges", lambda *_args: fake_edges)
    monkeypatch.setattr(module, "edge_signature", lambda _edge: {"curve": "line"})

    with pytest.raises(RuntimeError, match="expected=4, actual=2"):
        module.select_exact_edges(FakeModel(), lambda _edge: True, "base vertical", 4)


def test_reference_planes_are_hidden_before_review(monkeypatch) -> None:
    """@brief 构造平面可见时必须切换显示状态，避免污染交付预览。"""
    spec = importlib.util.spec_from_file_location(
        "cnc_mount_template_hide_planes_test",
        SCRIPT_DIR / "create_cnc_mount_template.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    calls = []

    class FakeModel:
        """@brief 提供隐藏参考平面所需的最小模型接口。"""

        def ClearSelection2(self, clear_all):
            calls.append(("clear", clear_all))

    def fake_member(_model, name, *_args):
        calls.append(("member", name))
        return True

    monkeypatch.setattr(module, "get_com_member", fake_member)
    module.hide_reference_planes(FakeModel())

    assert ("member", "GetVisibilityOfConstructPlanes") in calls
    assert ("member", "ViewDispRefplanes") in calls


def test_progressive_treatment_records_actual_degraded_size(monkeypatch) -> None:
    """@brief 求解返回 None 时可按计划降级，但必须记录实际尺寸。"""
    spec = importlib.util.spec_from_file_location(
        "cnc_mount_template_fallback_test",
        SCRIPT_DIR / "create_cnc_mount_template.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FakeFeature:
        """@brief 模拟第二次尝试创建成功的特征。"""

        Name = ""

    class FakeFeatureManager:
        """@brief 第一次返回 None，第二次返回特征。"""

        def __init__(self):
            self.calls = 0
            self.feature = FakeFeature()

        def FeatureFillet(self, *_args):
            self.calls += 1
            return None if self.calls == 1 else self.feature

    class FakeModel:
        """@brief 提供圆角降级所需的最小模型接口。"""

        def __init__(self):
            self.FeatureManager = FakeFeatureManager()

        def ClearSelection2(self, _clear_all):
            return True

        def ForceRebuild3(self, _top_only):
            return True

        def FeatureByName(self, name):
            return self.FeatureManager.feature if self.FeatureManager.feature.Name == name else None

    params, _report = strategy.build_parameters()
    operation = strategy.build_operation_plan(params, "progressive")[0]
    monkeypatch.setattr(module, "operation_predicate", lambda *_args: lambda _edge: True)
    monkeypatch.setattr(
        module,
        "select_exact_edges",
        lambda *_args: ([object()] * 4, [{"curve": "line"}] * 4),
    )

    evidence = module.apply_treatment(FakeModel(), operation, params)

    assert evidence["status"] == "degraded"
    assert evidence["requested_value_mm"] == 8.0
    assert evidence["actual_value_mm"] == 6.0
    assert [item["result"] for item in evidence["attempts"]] == [
        "feature_returned_none",
        "created_and_persisted",
    ]


def test_nonpersistent_feature_aborts_without_trying_smaller_size(monkeypatch) -> None:
    """@brief 返回非空但未持久化时不得继续叠加另一档圆角。"""
    spec = importlib.util.spec_from_file_location(
        "cnc_mount_template_persistence_test",
        SCRIPT_DIR / "create_cnc_mount_template.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FakeFeature:
        """@brief 模拟可命名但无法从树中回读的特征。"""

        Name = ""

    class FakeFeatureManager:
        """@brief 记录 API 调用次数。"""

        def __init__(self):
            self.calls = 0

        def FeatureFillet(self, *_args):
            self.calls += 1
            return FakeFeature()

    class FakeModel:
        """@brief 模拟重建后特征消失。"""

        def __init__(self):
            self.FeatureManager = FakeFeatureManager()

        def ClearSelection2(self, _clear_all):
            return True

        def ForceRebuild3(self, _top_only):
            return True

        def FeatureByName(self, _name):
            return None

    params, _report = strategy.build_parameters()
    operation = strategy.build_operation_plan(params, "progressive")[0]
    model = FakeModel()
    monkeypatch.setattr(module, "operation_predicate", lambda *_args: lambda _edge: True)
    monkeypatch.setattr(
        module,
        "select_exact_edges",
        lambda *_args: ([object()] * 4, [{"curve": "line"}] * 4),
    )

    with pytest.raises(RuntimeError, match="禁止继续尝试"):
        module.apply_treatment(model, operation, params)

    assert model.FeatureManager.calls == 1
