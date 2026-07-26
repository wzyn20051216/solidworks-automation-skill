"""@brief SolidWorks 装配体中英文基准面别名测试。"""

from scripts import sw_assembly


class FakeModel:
    """@brief 仅包含中文版前视基准面。"""

    def FeatureByName(self, name):
        return object() if name == "前视基准面" else None


class FakeComponent:
    """@brief 提供组件名称用于错误信息。"""

    Name2 = "base-1"


def test_component_feature_expands_english_plane_to_chinese_alias(monkeypatch) -> None:
    monkeypatch.setattr(sw_assembly, "get_component_model", lambda component, resolve=True: FakeModel())

    feature = sw_assembly.get_component_feature(FakeComponent(), "Front Plane")

    assert feature is not None
