"""
Edge-case tests for get_com_member's `default` fallback (issue #16).

The get_com_member fixture is provided by tests/conftest.py.
Run:  pytest -q tests/test_get_com_member_edge_cases.py
"""
import pytest


# _Obj is now provided by the fake_com_obj fixture in conftest.py


class _RuntimeAttrRaiser:
    """A present, callable member that raises AttributeError when invoked."""

    def RaiseAttrError(self):
        raise AttributeError("member not found at runtime")


def test_attribute_error_during_invocation_with_default_propagates(get_com_member):
    """
    `default` must only cover the getattr LOOKUP miss.
    An AttributeError raised while CALLING a present member must propagate,
    even when a default is supplied.
    """
    with pytest.raises(AttributeError, match="member not found at runtime"):
        get_com_member(_RuntimeAttrRaiser(), "RaiseAttrError", default=None)


def test_callable_returns_none_is_not_treated_as_default_missing(get_com_member):
    """
    A callable that returns None must return None, NOT the default value.
    The default is only used when the attribute is missing entirely.
    """
    class _ReturnsNone:
        def GetValue(self):
            return None

    result = get_com_member(_ReturnsNone(), "GetValue", default="fallback")
    assert result is None


def test_missing_member_with_falsy_default_returns_falsy(get_com_member, fake_com_obj):
    """
    Falsy defaults (0, "", False, []) must be returned as-is when member is missing.
    The default logic must not treat falsy values as "no default provided".
    """
    obj = fake_com_obj()
    assert get_com_member(obj, "NonExistent", default=0) == 0
    assert get_com_member(obj, "NonExistent", default="") == ""
    assert get_com_member(obj, "NonExistent", default=False) is False
    assert get_com_member(obj, "NonExistent", default=[]) == []


def test_present_member_with_falsy_default_ignores_default(get_com_member, fake_com_obj):
    """
    When the member exists, the default must be ignored entirely.
    Falsy defaults must not affect the return value of present members.
    """
    obj = fake_com_obj()
    # Present attribute with falsy default
    assert get_com_member(obj, "color", default="blue") == "red"
    # Present callable with falsy default
    assert get_com_member(obj, "GetTitle", default=None) == "part1"
    assert get_com_member(obj, "Add", 2, 3, default=999) == 5
