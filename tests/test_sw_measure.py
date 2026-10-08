"""测量工具回归测试。

重点锁定真机实测发现的单位缺陷：``GetPartBox(True)`` 返回**米**，
``IFeatureManager`` 各接口也一律用米；只有把单位搞对，包围盒读数才有意义。
"""
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

sys.modules.setdefault(
    "sw_preflight",
    types.SimpleNamespace(
        import_com_dependencies=lambda: (
            types.SimpleNamespace(VT_DISPATCH=9, VT_BYREF=16384, VT_I4=3),
            types.SimpleNamespace(),
            lambda *args: None,
        )
    ),
)


def fake_get_com_member(obj, attr_name, *args):
    """测试用 COM 成员读取器，兼容属性/方法两种形态。"""
    member = getattr(obj, attr_name)
    if args:
        return member(*args)
    if callable(member):
        try:
            return member()
        except TypeError:
            return member
    return member


sys.modules.setdefault(
    "sw_connect",
    types.SimpleNamespace(
        get_com_member=fake_get_com_member,
        create_empty_dispatch_variant=lambda: None,
        mm=lambda value: value / 1000.0,
        deg=lambda value: value * 3.141592653589793 / 180.0,
    ),
)

import sw_measure  # noqa: E402


class FakeMassProperty:
    """质量属性替身。SW2024 SP5 实测没有 Status 成员。"""

    def __init__(self, mass_kg=0.036, volume_m3=3.6e-05, area_m2=0.0139,
                 center_m=(0.05, 0.03, -0.003), has_status=False):
        self._mass = mass_kg
        self._volume = volume_m3
        self._area = area_m2
        self._center = center_m
        if has_status:
            self.Status = 1
        self.override_calls = []

    def Mass(self):
        return self._mass

    def Volume(self):
        return self._volume

    def SurfaceArea(self):
        return self._area

    def CenterOfMass(self):
        return list(self._center)

    def GetMomentOfInertia(self, _frame):
        return [1e-05] * 9

    def SetOverrideMass(self, enabled):
        self.override_calls.append(enabled)


class FakeModel:
    """文档替身。"""

    def __init__(self, box_m=None, material=None, mass_property=None, box_raises=False,
                 density_kg_m3=1000.0):
        self._box_m = box_m
        self.MaterialIdName = material
        self._mass_property = mass_property or FakeMassProperty()
        self._box_raises = box_raises
        self._density = density_kg_m3
        self.preference_writes = []
        self.Extension = types.SimpleNamespace(CreateMassProperty=lambda: self._mass_property)

    def GetPartBox(self, use_system_units=True):
        if self._box_raises:
            raise RuntimeError("no geometry")
        return list(self._box_m or [])

    def GetUserPreferenceDoubleValue(self, preference):
        """读取双精度偏好项（swMaterialPropertyDensity=7）。"""
        assert preference == 7, f"只支持密度偏好项，收到 {preference}"
        return self._density

    def SetUserPreferenceDoubleValue(self, preference, value):
        """写入双精度偏好项。"""
        self.preference_writes.append((preference, float(value)))
        self._density = float(value)
        return True


# ------------------------------------------------------------ 包围盒单位

def test_bounding_box_meters_are_converted_to_mm():
    """@brief GetPartBox(True) 返回米，必须换算为毫米。

    真机实测：100x60x6 mm 的板返回 [0,0,-0.006, 0.1,0.06,0]。
    若漏掉换算，这里的断言会得到 0.1 / 0.06 / 0.006。
    """
    model = FakeModel(box_m=[0.0, 0.0, -0.006, 0.1, 0.06, 0.0])

    result = sw_measure.collect_bounding_box(model)

    assert result["size_mm"] == pytest.approx([100.0, 60.0, 6.0])
    assert result["min_corner_mm"] == pytest.approx([0.0, 0.0, -6.0])
    assert result["max_corner_mm"] == pytest.approx([100.0, 60.0, 0.0])
    assert result["errors"] == []


def test_bounding_box_diagonal_uses_mm():
    """@brief 对角线长度按毫米计算。"""
    model = FakeModel(box_m=[0.0, 0.0, 0.0, 0.003, 0.004, 0.0])

    result = sw_measure.collect_bounding_box(model)

    assert result["diagonal_mm"] == pytest.approx(5.0)


def test_bounding_box_missing_geometry_reports_error():
    """@brief 无几何时报告错误而不是返回零点。"""
    result = sw_measure.collect_bounding_box(FakeModel(box_raises=True))

    assert result["size_mm"] is None
    assert result["errors"]


def test_bounding_box_short_array_reports_error():
    """@brief 坐标不足 6 个时报告错误。"""
    result = sw_measure.collect_bounding_box(FakeModel(box_m=[0.0, 0.0, 0.0]))

    assert result["size_mm"] is None
    assert any("6 个坐标" in item for item in result["errors"])


# ------------------------------------------------------------ 质量属性

def test_mass_properties_converted_to_engineering_units():
    """@brief 质量转克、体积转 mm³、表面积转 mm²、质心转 mm。"""
    model = FakeModel(mass_property=FakeMassProperty(), material="Alloy Steel")

    result = sw_measure.collect_mass_properties(model)

    assert result["mass_g"] == pytest.approx(36.0)
    assert result["volume_mm3"] == pytest.approx(36000.0)
    assert result["surface_area_mm2"] == pytest.approx(13900.0)
    assert result["center_of_mass_mm"] == pytest.approx([50.0, 30.0, -3.0])
    assert result["material"] == "Alloy Steel"
    assert result["material_assigned"] is True
    assert result["errors"] == []


def test_mass_properties_warns_when_material_missing():
    """@brief 未分配材料时给出提醒，但不当作执行错误。"""
    model = FakeModel(material=None)

    result = sw_measure.collect_mass_properties(model)

    assert result["material_assigned"] is False
    assert result["errors"] == []
    assert any("未分配材料" in item for item in result["warnings"])


def test_missing_status_member_is_not_an_error():
    """@brief SW2024 SP5 没有 IMassProperty.Status，缺失不应记为错误。

    旧实现用通用 read() 读取 Status，每次测量都会带一条无意义告警。
    """
    model = FakeModel(mass_property=FakeMassProperty(has_status=False))

    result = sw_measure.collect_mass_properties(model)

    assert not any("Status" in item for item in result["errors"])
    assert result["status"] is None


def test_status_reported_when_present():
    """@brief 有 Status 成员时正常读取。"""
    model = FakeModel(mass_property=FakeMassProperty(has_status=True))

    result = sw_measure.collect_mass_properties(model)

    assert result["status"] == "calculated"


def test_density_derived_from_mass_over_volume():
    """@brief 未传密度时，由质量/体积反算，用于核对材料是否选对。"""
    model = FakeModel(mass_property=FakeMassProperty(mass_kg=7.85, volume_m3=0.001))

    result = sw_measure.collect_mass_properties(model)

    assert result["density_kg_m3"] == pytest.approx(7850.0)
    assert result["implied_density_kg_m3"] == pytest.approx(7850.0)


def test_density_set_through_user_preference():
    """@brief 密度通过 swMaterialPropertyDensity(7) 偏好项设置。

    IMassProperty.Density 是只读属性、SetOverrideMass 不存在——真机实测都不可用。
    """
    model = FakeModel(mass_property=FakeMassProperty(mass_kg=0.2826, volume_m3=3.6e-05))

    result = sw_measure.collect_mass_properties(model, density_kg_m3=7850.0)

    assert result["density_overridden"] is True
    assert model.preference_writes == [(7, 7850.0)]
    assert result["density_kg_m3"] == pytest.approx(7850.0)
    assert result["previous_density_kg_m3"] == pytest.approx(1000.0)
    # 反算密度与请求值一致，不应报错
    assert result["errors"] == []


def test_density_mismatch_is_flagged():
    """@brief 密度设置未生效时（反算值不符）必须报错，不能静默给出错误质量。"""
    # 请求 7850，但模型仍按 1000 计算
    model = FakeModel(mass_property=FakeMassProperty(mass_kg=0.036, volume_m3=3.6e-05))

    result = sw_measure.collect_mass_properties(model, density_kg_m3=7850.0)

    assert any("密度设置可能未生效" in item for item in result["errors"])


def test_mass_property_creation_failure_is_reported():
    """@brief CreateMassProperty 失败时结构化报告，不抛裸异常。"""

    class BrokenModel:
        MaterialIdName = None

        class Extension:
            @staticmethod
            def CreateMassProperty():
                raise RuntimeError("no body")

    result = sw_measure.collect_mass_properties(BrokenModel())

    assert result["mass_g"] is None
    assert any("质量属性对象失败" in item for item in result["errors"])


# ------------------------------------------------------------ 干涉检查

class FakeInterference:
    """干涉检查对象替身。"""

    def __init__(self, count=0, fail_on=None):
        self.count = count
        self.fail_on = fail_on
        self.TreatSubAssembliesAsComponents = None
        self.TreatCoincidenceAsInterference = None
        self.done_called = False

    def Done(self):
        self.done_called = True
        if self.fail_on == "done":
            raise RuntimeError("assembly busy")

    def GetInterferenceCount(self):
        if self.fail_on == "count":
            raise RuntimeError("count unavailable")
        return self.count

    def GetInterferences(self):
        assert not self.done_called
        if self.fail_on == "calculate":
            raise RuntimeError("calculation failed")
        return [types.SimpleNamespace(Volume=1e-07, Components=[])
                for _ in range(self.count)]


class FakeAssembly:
    """装配体替身。"""

    def __init__(self, count=0, fail_on=None):
        self.InterferenceDetectionManager = FakeInterference(count, fail_on)

    def ClearSelection2(self, all_selections):
        assert all_selections


def test_interference_clean_assembly():
    """@brief 零干涉时通过，但仍要求人工复核。"""
    result = sw_measure.inspect_interference(FakeAssembly(count=0))

    assert result["status"] == "pass"
    assert result["interference_count"] == 0
    assert result["severity"] == "none"
    assert result["manual_review_required"] is True


def test_interference_reports_volumes_in_mm3():
    """@brief 干涉体积换算为 mm³ 并据此分级。"""
    result = sw_measure.inspect_interference(FakeAssembly(count=2))

    assert result["status"] == "warn"
    assert result["interference_count"] == 2
    assert result["items"][0]["volume_mm3"] == pytest.approx(100.0)
    assert result["severity"] == "major"


def test_interference_options_are_forwarded():
    """@brief 选项必须真正传给 SolidWorks。"""
    assembly = FakeAssembly(count=0)

    sw_measure.inspect_interference(
        assembly,
        treat_subassemblies_as_components=True,
        treat_coincidence_as_interference=True,
    )

    assert assembly.InterferenceDetectionManager.TreatSubAssembliesAsComponents is True
    assert assembly.InterferenceDetectionManager.TreatCoincidenceAsInterference is True
    assert assembly.InterferenceDetectionManager.IgnoreHiddenBodies is False
    assert assembly.InterferenceDetectionManager.done_called


@pytest.mark.parametrize("failure", ["count", "calculate", "done"])
def test_interference_api_failures_never_report_zero(failure):
    """计算、数量或结束失败均不得伪造零干涉通过。"""
    assembly = FakeAssembly(count=2, fail_on=failure)
    result = sw_measure.inspect_interference(assembly)
    assert result["status"] == "blocked"
    assert result["interference_count"] is None
    assert assembly.InterferenceDetectionManager.done_called


def test_interference_array_count_mismatch_is_blocked():
    """空数组与非零计数不一致时拒绝放行。"""
    assembly = FakeAssembly(count=2)
    assembly.InterferenceDetectionManager.GetInterferences = lambda: []
    assert sw_measure.inspect_interference(assembly)["status"] == "blocked"


def test_interference_failure_is_structured():
    """@brief 干涉检查自身报错时返回 blocked 而非崩溃。"""
    result = sw_measure.inspect_interference(FakeAssembly(fail_on="done"))

    assert result["status"] == "blocked"
    assert result["manual_review_required"] is True
    assert result["errors"]


# ------------------------------------------------------------ 配合校核

def test_clearance_fit_detected():
    """@brief 孔大于轴判为间隙配合。"""
    result = sw_measure.check_tolerance_fit(shaft_mm=9.98, hole_mm=10.02, fit="clearance")

    assert result["fit_satisfied"] is True
    assert result["clearance_mm"] == pytest.approx(0.04)


def test_interference_fit_detected():
    """@brief 孔小于轴判为过盈配合。"""
    result = sw_measure.check_tolerance_fit(shaft_mm=10.05, hole_mm=10.0, fit="interference")

    assert result["fit_satisfied"] is True
    assert result["clearance_mm"] == pytest.approx(-0.05)


def test_fit_check_warns_about_nominal_sizes():
    """@brief 结果必须附带"名义尺寸不含公差"的边界说明。"""
    result = sw_measure.check_tolerance_fit(shaft_mm=9.98, hole_mm=10.02)

    assert "GB/T 1800" in result["caveat"] or "ISO 286" in result["caveat"]


def test_fit_requested_but_not_satisfied():
    """@brief 要求间隙配合但实际过盈时明确判定失败。"""
    result = sw_measure.check_tolerance_fit(shaft_mm=10.05, hole_mm=10.0, fit="clearance")

    assert result["fit_satisfied"] is False
