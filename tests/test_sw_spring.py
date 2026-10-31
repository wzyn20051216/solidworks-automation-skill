"""弹簧中心线参数、限制和单位的离线验证。"""
import math
import sys
from types import SimpleNamespace

import pytest

from scripts.sw_spring import (OpenHelicalSpringSpec, create_open_helical_spring, expected_body_bounds_mm,
                               exact_body_bounds_mm, validate_spring_spec, verify_helix_definition)


def test_centerline_height_pitch_and_ideal_volume():
    spec = OpenHelicalSpringSpec(3, 24, 48, 6)
    result = validate_spring_spec(spec)
    assert result["pitch_mm"] == 8
    length = math.sqrt((math.pi * 24 * 6) ** 2 + 48 ** 2)
    assert result["centerline_length_mm"] == pytest.approx(length)
    assert result["ideal_volume_mm3"] == pytest.approx(math.pi * 1.5 ** 2 * length)
    expected_axial = 48 + 3 * (math.pi * 24) / math.hypot(math.pi * 24, 8)
    assert expected_body_bounds_mm(spec, 8) == pytest.approx([27, 27, expected_axial])


@pytest.mark.parametrize("spec", [
    OpenHelicalSpringSpec(0, 24, 48, 6), OpenHelicalSpringSpec(True, 24, 48, 6),
    OpenHelicalSpringSpec(3, 11, 48, 6), OpenHelicalSpringSpec(3, 24, 3, 6),
    OpenHelicalSpringSpec(3, 24, 100, 6), OpenHelicalSpringSpec(3, 24, 48, 21),
    OpenHelicalSpringSpec(3, 24, float("nan"), 6), OpenHelicalSpringSpec(3, 24, 48, 6, "false"),
])
def test_invalid_or_out_of_scope_input_is_rejected(spec):
    with pytest.raises(ValueError):
        validate_spring_spec(spec)


def test_existing_body_is_rejected_before_creating_sketch():
    model = SimpleNamespace(GetType=lambda: 1, GetBodies2=lambda *_: [object()])
    with pytest.raises(ValueError, match="无实体"):
        create_open_helical_spring(model, OpenHelicalSpringSpec(3, 24, 48, 6))


def test_incorrect_helix_rotation_is_rejected():
    definition = SimpleNamespace(Clockwise=True, DefinedBy=1, Height=.048, Pitch=.008, Revolution=6.)
    helix = SimpleNamespace(GetDefinition=lambda: definition)
    with pytest.raises(RuntimeError, match="旋向"):
        verify_helix_definition(helix, OpenHelicalSpringSpec(3, 24, 48, 6, False), 8.)


@pytest.mark.skipif(sys.platform != "win32", reason="pywin32 VARIANT 仅在 Windows 可用")
def test_extreme_bounds_use_out_parameters_and_reject_missing_point():
    class Body:
        def GetExtremePoint(self, x, y, z, outx, outy, outz):
            for value, direction, radius in zip((outx, outy, outz), (x, y, z), (.01, .02, .03)):
                value.value = direction * radius
            return True
    assert exact_body_bounds_mm(Body()) == pytest.approx([20, 40, 60])
    class Missing:
        def GetExtremePoint(self, *_):
            return False
    with pytest.raises(RuntimeError, match="极值点"):
        exact_body_bounds_mm(Missing())
