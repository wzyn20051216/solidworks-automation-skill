"""
Core behavior tests for get_com_member's `default` fallback (issue #16).

The get_com_member fixture is provided by tests/conftest.py.
Run:  pytest -q tests/test_get_com_member_core.py
"""
import pytest


# _Obj is now provided by the fake_com_obj fixture in conftest.py


def test_missing_member_with_default_returns_default(get_com_member, fake_com_obj):
    """This FAILS on the old code (raises AttributeError), PASSES on the fixed code."""
    _Obj = fake_com_obj
    assert get_com_member(_Obj(), "GetFirstCenterMark2", default=None) is None
    assert get_com_member(_Obj(), "Nope", default=42) == 42


def test_missing_member_without_default_still_raises(get_com_member, fake_com_obj):
    """Backward compatibility: no default -> same behavior as before (raise)."""
    _Obj = fake_com_obj
    with pytest.raises(AttributeError):
        get_com_member(_Obj(), "GetFirstCenterMark2")


def test_present_attribute_returned_as_is(get_com_member, fake_com_obj):
    _Obj = fake_com_obj
    assert get_com_member(_Obj(), "color") == "red"


def test_present_callable_no_args_is_called(get_com_member, fake_com_obj):
    _Obj = fake_com_obj
    assert get_com_member(_Obj(), "GetTitle") == "part1"


def test_present_callable_with_args_is_called(get_com_member, fake_com_obj):
    _Obj = fake_com_obj
    assert get_com_member(_Obj(), "Add", 2, 3) == 5


def test_callable_error_propagates(get_com_member, fake_com_obj):
    """
    The fix only catches AttributeError on member lookup.
    Exceptions raised by CALLING the member must propagate unchanged.
    """
    _Obj = fake_com_obj
    with pytest.raises(RuntimeError, match="COM error"):
        get_com_member(_Obj(), "RaiseError")
