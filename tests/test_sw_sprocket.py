"""链轮实体入口的输入、状态和失败路径。真机验证另见手动回归脚本。"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import sw_part, sw_sprocket


class Model:
    def __init__(self, existing=False):
        self.SketchManager = SimpleNamespace(AddToDB=False, DisplayWhenAdded=True)
        self.bodies = [object()] if existing else []

    def GetType(self):
        return 1

    def GetBodies2(self, *_):
        return self.bodies

    def ForceRebuild3(self, _):
        return True


SPEC = sw_sprocket.SprocketSpec(12.7, 7.92, 17, 6, 10)


def test_rejects_existing_solid_before_modifying_document():
    model = Model(existing=True)
    with pytest.raises(ValueError, match="无实体"):
        sw_sprocket.create_approximate_sprocket(model, SPEC)
    assert model.SketchManager.AddToDB is False


def test_builds_one_solid_and_restores_sketch_settings(monkeypatch):
    model = Model()
    lines = []
    @contextmanager
    def sketch(*_):
        yield "profile"
    def line(_model, *args):
        lines.append(args)
        return object()
    def extrude(_model, _sketch, depth):
        assert depth == pytest.approx(.006)
        model.bodies = [object()]
        return SimpleNamespace(Name="")
    monkeypatch.setattr(sw_part, "sketch", sketch)
    monkeypatch.setattr(sw_part, "sketch_line", line)
    monkeypatch.setattr(sw_part, "sketch_circle", lambda *_: object())
    monkeypatch.setattr(sw_part, "extrude_boss", extrude)
    _, evidence = sw_sprocket.create_approximate_sprocket(model, SPEC)
    assert evidence["status"] == "review_required"
    assert len(lines) == evidence["profile_segments"] == 170
    assert lines[-1][2:] == lines[0][:2]
    assert model.SketchManager.AddToDB is False and model.SketchManager.DisplayWhenAdded is True


def test_failed_line_restores_sketch_settings(monkeypatch):
    model = Model()
    @contextmanager
    def sketch(*_):
        yield "profile"
    monkeypatch.setattr(sw_part, "sketch", sketch)
    monkeypatch.setattr(sw_part, "sketch_line", lambda *_: None)
    with pytest.raises(RuntimeError, match="轮廓线段"):
        sw_sprocket.create_approximate_sprocket(model, SPEC)
    assert model.SketchManager.AddToDB is False and model.SketchManager.DisplayWhenAdded is True
