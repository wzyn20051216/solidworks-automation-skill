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


class FakePropertyRebuildModel(FakeModel):
    """@brief 模拟 SW2024 将 EditRebuild3 暴露为布尔伪属性的行为。"""

    EditRebuild3 = True


class FakeConfigurationModel(FakeModel):
    """@brief 模拟 AddConfiguration3、ShowConfiguration2 与活动配置回读。"""

    def __init__(self):
        super().__init__()
        self.names = ["默认"]
        self.active = type("Config", (), {"Name": "默认"})()
        self.ConfigurationManager = type("Manager", (), {})()
        self.ConfigurationManager.ActiveConfiguration = self.active

    def GetConfigurationNames(self):
        return list(self.names)

    def AddConfiguration3(self, name, comment, alternate_name, options):
        config = type(
            "Config",
            (),
            {"Name": name, "Comment": comment, "AlternateName": alternate_name, "Options": options},
        )()
        self.names.append(name)
        return config

    def ShowConfiguration2(self, name):
        if name not in self.names:
            return False
        self.active = type("Config", (), {"Name": name})()
        self.ConfigurationManager.ActiveConfiguration = self.active
        self.dimension.current = name if name in self.dimension.values else "默认"
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


def test_accepts_edit_rebuild_as_boolean_property():
    model = FakePropertyRebuildModel()
    result = document_data.update_dimension_mm(
        model,
        "D1@Boss-Extrude1",
        15.0,
    )
    assert result["success"] is True
    assert result["rebuild_success"] is True
    assert result["after_mm"] == {"current": 15.0}


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


def test_inspects_configurations_and_active_configuration():
    model = FakeModel()
    model.ConfigurationManager = type(
        "Manager",
        (),
        {"ActiveConfiguration": type("Config", (), {"Name": "加工"})()},
    )()

    result = document_data.inspect_configurations(model)

    assert result["status"] == "pilot"
    assert result["configurations"] == ["默认", "加工"]
    assert result["active_configuration"] == "加工"


def test_creates_activates_and_reads_back_configuration():
    """@brief 新配置必须同时出现在清单并成为活动配置。"""
    model = FakeConfigurationModel()

    result = document_data.create_configuration(
        model,
        "加工",
        comment="CNC 工况",
        alternate_name="MACHINED",
    )

    assert result["success"] is True
    assert result["created"] is True
    assert result["configurations_after"] == ["默认", "加工"]
    assert result["activation"]["readback_verified"] is True
    assert result["activation"]["after"] == "加工"


def test_configuration_create_is_idempotent_or_strict_on_request():
    """@brief 默认复用已有配置，严格模式拒绝同名覆盖。"""
    model = FakeConfigurationModel()
    model.AddConfiguration3("加工", "", "", 0)

    reused = document_data.create_configuration(model, "加工")

    assert reused["success"] is True
    assert reused["created"] is False
    assert reused["reused"] is True
    try:
        document_data.create_configuration(model, "加工", if_exists="error")
    except FileExistsError as error:
        assert "配置已存在" in str(error)
    else:
        raise AssertionError("strict duplicate configuration should fail")


def test_activate_configuration_rejects_unknown_name_before_com_call():
    """@brief 未知配置必须在调用 ShowConfiguration2 前失败。"""
    model = FakeConfigurationModel()

    try:
        document_data.activate_configuration(model, "不存在")
    except LookupError as error:
        assert "找不到配置" in str(error)
    else:
        raise AssertionError("unknown configuration should fail")


def test_activate_configuration_accepts_already_active_readback_without_redundant_call():
    """@brief SW2026 创建后已激活时不应被重复 ShowConfiguration2 的 False 误判。"""
    model = FakeConfigurationModel()
    model.AddConfiguration3("薄型", "", "", 0)
    model.ShowConfiguration2("薄型")
    calls = 0

    def unexpected_show(_name):
        nonlocal calls
        calls += 1
        return False

    model.ShowConfiguration2 = unexpected_show
    result = document_data.activate_configuration(model, "薄型")

    assert result["success"] is True
    assert result["api_called"] is False
    assert result["api_return"] is None
    assert calls == 0


def test_configuration_names_are_resolved_case_insensitively() -> None:
    """@brief 英文配置名大小写差异不应创建重复配置。"""
    model = FakeConfigurationModel()
    model.AddConfiguration3("Machined", "", "", 0)

    result = document_data.create_configuration(model, "MACHINED")

    assert result["success"] is True
    assert result["created"] is False
    assert result["configuration"] == "Machined"
    assert result["requested_configuration"] == "MACHINED"
    assert model.names.count("Machined") == 1
