"""SolidWorks 参数与属性封装的无 COM 回归测试。"""
from __future__ import annotations

from scripts import sw_document_data as document_data


class FakeVariant:
    def __init__(self, _variant_type, value):
        self.value = value


class FakeDimension:
    def __init__(self):
        self.values = {"默认": 0.01, "加工": 0.02}
        self.current = "默认"

    @property
    def SystemValue(self):
        return self.values[self.current]

    def GetSystemValue2(self, name):
        return self.values[name]

    def SetSystemValue3(self, value, mode, names):
        if mode == 1:
            self.values[self.current] = value
        elif mode == 2:
            self.values = {name: value for name in self.values}
        elif mode == 3:
            for name in names.value:
                self.values[name] = value
        return 0


class FakePropertyManager:
    def __init__(self):
        self.values = {}

    def Add3(self, name, _kind, value, _option):
        self.values[name] = value
        return 0

    def Get6(self, name, _cached, raw, resolved, was_resolved, linked):
        if name not in self.values:
            return 1
        raw.value = self.values[name]
        resolved.value = self.values[name]
        was_resolved.value = True
        linked.value = False
        return 2


class FakeExtension:
    def __init__(self):
        self.managers = {}

    def CustomPropertyManager(self, configuration):
        return self.managers.setdefault(configuration, FakePropertyManager())


class FakeModel:
    def __init__(self):
        self.dimension = FakeDimension()
        self.Extension = FakeExtension()

    def Parameter(self, name):
        return self.dimension if name == "D1@Boss-Extrude1" else None

    def GetConfigurationNames(self):
        return ["默认", "加工"]

    def EditRebuild3(self):
        return True


def setup_module():
    document_data.VARIANT = FakeVariant
    document_data.pythoncom.VT_ARRAY = 0x2000
    document_data.pythoncom.VT_BSTR = 8
    document_data.pythoncom.VT_BYREF = 0x4000
    document_data.pythoncom.VT_BOOL = 11


def test_updates_specific_configuration_with_mm_conversion():
    model = FakeModel()
    result = document_data.update_dimension_mm(
        model,
        "D1@Boss-Extrude1",
        35.0,
        configuration_mode="specific",
        configuration_names=["加工"],
    )
    assert result["success"] is True
    assert result["before_mm"] == {"加工": 20.0}
    assert result["after_mm"] == {"加工": 35.0}
    assert model.dimension.values["默认"] == 0.01


def test_rejects_missing_dimension_and_invalid_value():
    model = FakeModel()
    try:
        document_data.update_dimension_mm(model, "missing", 10)
    except LookupError as error:
        assert "找不到尺寸" in str(error)
    else:
        raise AssertionError("missing dimension should fail")

    try:
        document_data.update_dimension_mm(model, "D1@Boss-Extrude1", 0)
    except ValueError as error:
        assert "大于 0" in str(error)
    else:
        raise AssertionError("non-positive dimension should fail")


def test_sets_and_reads_back_configuration_properties():
    model = FakeModel()
    result = document_data.set_custom_properties(
        model,
        {"PartNumber": "PN-001", "Material": "45#"},
        configuration_name="加工",
    )
    assert result["success"] is True
    assert [item["verified"] for item in result["properties"]] == [True, True]
    assert result["properties"][0]["readback"]["raw"] == "PN-001"
