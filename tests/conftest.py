"""
Shared pytest fixtures for get_com_member tests (issue #16).

No SolidWorks and no pywin32 required. The get_com_member fixture stubs
sw_preflight temporarily during import, restoring sys.modules and sys.path
after the module. Placed in conftest.py so all test modules in tests/ share it
via pytest fixture discovery (no imports needed).
"""
import os
import sys
import types
import importlib.util
from contextlib import contextmanager
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")


@contextmanager
def _imported_sw_connect():
    """
    Context manager that imports sw_connect with stubbed sw_preflight.
    Yields the imported module. Restores sys.modules/sys.path on exit.
    """
    # Track EXACTLY what we modify - surgical isolation
    sw_preflight_existed = "sw_preflight" in sys.modules
    orig_sw_preflight = sys.modules.get("sw_preflight")
    path_inserted = SCRIPTS_DIR not in sys.path
    sw_connect_existed = "sw_connect_under_test" in sys.modules
    orig_sw_connect = sys.modules.get("sw_connect_under_test")

    # Stub sw_preflight: harmless placeholders, no-op ensure
    stub = types.ModuleType("sw_preflight")
    stub.import_com_dependencies = lambda: (object(), object(), object())
    stub.ensure_solidworks_installed = lambda: None
    sys.modules["sw_preflight"] = stub

    if path_inserted:
        sys.path.insert(0, SCRIPTS_DIR)

    try:
        spec = importlib.util.spec_from_file_location(
            "sw_connect_under_test", os.path.join(SCRIPTS_DIR, "sw_connect.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        # Surgical teardown
        if sw_connect_existed and orig_sw_connect is not None:
            sys.modules["sw_connect_under_test"] = orig_sw_connect
        elif not sw_connect_existed and "sw_connect_under_test" in sys.modules:
            del sys.modules["sw_connect_under_test"]

        if path_inserted and SCRIPTS_DIR in sys.path:
            sys.path.remove(SCRIPTS_DIR)

        if sw_preflight_existed and orig_sw_preflight is not None:
            sys.modules["sw_preflight"] = orig_sw_preflight
        elif not sw_preflight_existed and "sw_preflight" in sys.modules:
            del sys.modules["sw_preflight"]


@pytest.fixture(scope="module")
def get_com_member():
    """Import get_com_member function without needing Windows/pywin32."""
    with _imported_sw_connect() as module:
        yield module.get_com_member


@pytest.fixture
def fake_com_obj():
    """Fake COM object with attributes and callables for testing."""
    class _Obj:
        color = "red"

        def GetTitle(self):
            return "part1"

        def Add(self, a, b):
            return a + b

        def RaiseError(self):
            raise RuntimeError("COM error")

    return _Obj


@pytest.fixture(scope="module")
def sw_connect():
    """Import sw_connect module without needing Windows/pywin32."""
    with _imported_sw_connect() as module:
        yield module
