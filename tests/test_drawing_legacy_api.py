"""@brief 旧版接口独立替身验证，不能代替 SW2020 真机兼容矩阵。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sw_drawing


def test_old_position_setter_requires_typed_safearray(monkeypatch):
    """@brief 普通 tuple 会被旧接口忽略，必须传 VT_ARRAY|VT_R8。"""
    class Array:
        def __init__(self, code, values):
            self.code, self.values = code, values
    class View:
        def __init__(self):
            self.position = (0.0, 0.0)
        @property
        def Position(self):
            return self.position
        @Position.setter
        def Position(self, value):
            assert isinstance(value, Array)
            assert value.code == 8197
            self.position = tuple(value.values)
    monkeypatch.setattr(sw_drawing._MODULE, "VARIANT", Array)
    view = View()
    assert sw_drawing._MODULE._set_view_center(view, (.16, .13)) == [.16, .13]


def test_old_center_mark_member_fallback():
    class View:
        def GetFirstCenterMark(self):
            return "old-mark"
    assert sw_drawing.first_center_mark(View()) == "old-mark"


def test_present_member_failure_is_not_suppressed():
    class View:
        def GetFirstCenterMark2(self):
            raise RuntimeError("read failed")
    with pytest.raises(RuntimeError, match="read failed"):
        sw_drawing.first_center_mark(View())
