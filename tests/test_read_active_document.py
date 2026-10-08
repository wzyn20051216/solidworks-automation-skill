"""
Caller-level regression tests for _read_active_document (issue #16).

Tests verify the error-handling contract: return None on ANY failure,
not just AttributeError lookup misses. This ensures backward compatibility
with the original implementation that swallowed all exceptions.

The sw_connect fixture is provided by tests/conftest.py.
Run: pytest -q tests/test_read_active_document.py
"""
import pytest


def test_returns_doc_when_active_doc_present(sw_connect):
    """
    Case (a): ActiveDoc is present and accessible.
    Should return the document object.
    """
    class MockSW:
        ActiveDoc = "mock_document"
    
    result = sw_connect._read_active_document(MockSW())
    assert result == "mock_document"


def test_returns_none_when_active_doc_missing(sw_connect):
    """
    Case (b): ActiveDoc attribute does not exist (lookup miss).
    Should return None, not raise AttributeError.
    """
    class MockSW:
        pass  # No ActiveDoc attribute
    
    result = sw_connect._read_active_document(MockSW())
    assert result is None


def test_returns_none_on_non_attribute_error(sw_connect):
    """
    Case (c): Accessing ActiveDoc raises a non-AttributeError exception.
    Should return None, not propagate the exception.
    
    This is the critical regression test: the original contract swallowed
    ALL exceptions, not just AttributeError. The fix must preserve this.
    """
    class MockSW:
        @property
        def ActiveDoc(self):
            raise RuntimeError("COM server not ready")
    
    result = sw_connect._read_active_document(MockSW())
    assert result is None


def test_returns_none_when_active_doc_raises_com_error(sw_connect):
    """
    Case (d): ActiveDoc raises a COM-specific error (pywin32 com_error).
    Should return None, not propagate the exception.
    """
    class MockCOMError(Exception):
        """Simulates pywin32 com_error without requiring pywin32."""
        pass
    
    class MockSW:
        @property
        def ActiveDoc(self):
            raise MockCOMError("COM object disconnected")
    
    result = sw_connect._read_active_document(MockSW())
    assert result is None
