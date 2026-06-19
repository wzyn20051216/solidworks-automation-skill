"""
sw_part 草图选择回归测试。

重点覆盖 SolidWorks 2024 中文版反馈过的问题：
选择集为空且 SelectByID2("SKETCH") 失败时，特征函数应使用创建草图时
缓存的对象引用，而不是依赖残留选择集。
"""
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def fake_get_com_member(obj, attr_name, *args):
    """测试用 COM 成员读取器。"""
    member = getattr(obj, attr_name)
    return member(*args) if args or callable(member) else member


class FakeVariant:
    """测试用 VARIANT 占位类型。"""

    def __init__(self, *_args):
        pass


sys.modules["sw_connect"] = types.SimpleNamespace(get_com_member=fake_get_com_member)
sys.modules["sw_preflight"] = types.SimpleNamespace(
    import_com_dependencies=lambda: (
        types.SimpleNamespace(VT_DISPATCH=9),
        types.SimpleNamespace(),
        FakeVariant,
    )
)

import sw_part  # noqa: E402


class FakeFeature:
    """模拟 SolidWorks Feature 对象。"""

    def __init__(self, name):
        self.Name = name
        self.selected = False

    def Select2(self, append, mark):
        """模拟对象级选择成功。"""
        self.selected = True
        return True


class FakeSketch:
    """模拟 SolidWorks Sketch 对象。"""

    def __init__(self, name):
        self.Name = name
        self.feature = FakeFeature(name)

    def GetFeature(self):
        """返回草图对应特征。"""
        return self.feature


class FakeSketchManager:
    """模拟 SketchManager。"""

    def __init__(self, sketch):
        self.ActiveSketch = None
        self.sketch = sketch

    def InsertSketch(self, _update_edit_rebuild):
        """进入或退出草图。"""
        self.ActiveSketch = self.sketch if self.ActiveSketch is None else None


class FakeSelectionManager:
    """模拟空选择集。"""

    def GetSelectedObjectCount2(self, _mark):
        """始终返回空选择集。"""
        return 0


class FakeExtension:
    """模拟 SelectByID2 对 SKETCH 失败、对 PLANE 成功。"""

    def __init__(self):
        self.calls = []

    def SelectByID2(self, name, entity_type, *_args):
        """记录选择调用，并故意让 SKETCH 名称选择失败。"""
        self.calls.append((name, entity_type))
        return entity_type == "PLANE"


class FakeFeatureManager:
    """模拟拉伸特征管理器。"""

    def __init__(self, model):
        self.model = model

    def FeatureExtrusion3(self, *_args):
        """只有对象级选择发生后才创建特征。"""
        if self.model.sketch.feature.selected:
            return FakeFeature("Boss-Extrude1")
        return None


class FakeModel:
    """模拟最小 IModelDoc2。"""

    def __init__(self):
        self.sketch = FakeSketch("草图1")
        self.Extension = FakeExtension()
        self.SketchManager = FakeSketchManager(self.sketch)
        self.SelectionManager = FakeSelectionManager()
        self.FeatureManager = FakeFeatureManager(self)
        self.clear_calls = 0

    def ClearSelection2(self, _clear_all):
        """记录清空选择集。"""
        self.clear_calls += 1

    def FeatureByName(self, _name):
        """模拟中文 SW 中按名称找不到草图。"""
        return None


class SketchSelectionTests(unittest.TestCase):
    """验证草图选择不依赖残留选择集或 SelectByID2("SKETCH")。"""

    def test_extrude_uses_cached_sketch_object_when_select_by_id_fails(self):
        """选择集为空且 SKETCH 名称选择失败时仍应拉伸成功。"""
        model = FakeModel()

        with sw_part.sketch(model, "Front Plane") as sketch_name:
            self.assertEqual(sketch_name, "草图1")

        feature = sw_part.extrude_boss(model, sketch_name, 0.01)

        self.assertIsNotNone(feature)
        self.assertTrue(model.sketch.feature.selected)
        self.assertNotIn(("草图1", "SKETCH"), model.Extension.calls)


if __name__ == "__main__":
    unittest.main()
