"""质量属性无 COM 测试：mass_properties 经假 Extension 读 GetMassProperties2。"""
from scripts.sw_mass_properties import mass_properties


class _FakeExt:
    def __init__(self, props):
        self._props = props

    def GetMassProperties2(self, accuracy, status_ref, default_density):
        return self._props


class _FakeModel:
    def __init__(self, props, material="AISI 1045"):
        self.Extension = _FakeExt(props)
        self.Material = material


def test_mass_properties_with_material_pass():
    # 0.01m 立方体钢：vol=1e-6 m3, area=6e-4 m2, mass~7.85e-3 kg, cog=(0,0,0)
    props = [0.0, 0.0, 0.0, 1e-6, 6e-4, 0.00785]
    r = mass_properties(_FakeModel(props, material="AISI 1045"))
    assert r["status"] == "pass"
    assert r["mass_meaningful"] is True
    assert r["material"] == "AISI 1045"
    assert abs(r["volume_mm3"] - 1000.0) < 1e-6      # 1e-6 m3 -> 1000 mm3
    assert abs(r["surface_mm2"] - 600.0) < 1e-6      # 6e-4 m2 -> 600 mm2
    assert abs(r["mass_kg"] - 0.00785) < 1e-9
    assert r["center_of_mass_mm"] == [0.0, 0.0, 0.0]


def test_mass_properties_no_material_review():
    # 几何有效但未赋材料 -> 质量无意义
    props = [0.0, 0.0, 0.0, 1e-6, 6e-4, 0.00785]
    r = mass_properties(_FakeModel(props, material=""))
    assert r["status"] == "review_required"
    assert r["mass_meaningful"] is False
    assert r["error_code"] == "MASS_MATERIAL_UNASSIGNED"
    # 几何值仍应填出
    assert abs(r["volume_mm3"] - 1000.0) < 1e-6


def test_mass_properties_nonpositive_mass_review():
    # 材料已设但质量<=0（密度未配）-> 非正质量
    props = [0.0, 0.0, 0.0, 1e-6, 6e-4, 0.0]
    r = mass_properties(_FakeModel(props, material="AISI 1045"))
    assert r["status"] == "review_required"
    assert r["error_code"] == "MASS_NONPOSITIVE"


def test_mass_properties_extension_none_failed():
    # Extension 属性读出 None -> 结构化失败
    class ExtNone:
        Material = "AISI 1045"
        Extension = None

    r = mass_properties(ExtNone())
    assert r["status"] == "failed"
    assert r["error_code"] == "MASS_NO_EXTENSION"
