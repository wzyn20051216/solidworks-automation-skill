"""Shared pytest fixtures for SolidWorks automation tests."""

import pytest
from scripts import sw_part


class FakeFeature:
    """Mock SolidWorks Feature."""
    Name = ""


class FakeFeatureManager:
    """Record FeatureCut4 arguments."""
    def __init__(self):
        self.cut_calls = []

    def FeatureCut4(self, *args):
        self.cut_calls.append(args)
        return FakeFeature()


class FakeModel:
    """Minimal model interface for extrude_cut."""
    def __init__(self):
        self.FeatureManager = FakeFeatureManager()

    def ClearSelection2(self, clear_all):
        return True


@pytest.fixture
def cut_model(monkeypatch):
    """Fake model with FeatureCut4 call recording and sketch selection bypassed."""
    model = FakeModel()
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda *args: None)
    return model
