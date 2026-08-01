"""AutoCAD 会话薄封装的无 COM 回归测试。"""
from __future__ import annotations

import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subskills" / "autocad-automation" / "scripts"))

import acad_session  # noqa: E402


class FakeEntity:
    """@brief 记录尺寸实体的图层和颜色。"""

    def __init__(self, kind, args):
        self.kind = kind
        self.args = args
        self.Layer = "0"
        self.Color = 256


class FakeModelSpace:
    """@brief 模拟只支持 Count/Item 的 AutoCAD ModelSpace。"""

    def __init__(self):
        self.entities = []

    @property
    def Count(self):
        return len(self.entities)

    def Item(self, index):
        return self.entities[index]

    def AddDimAligned(self, *args):
        entity = FakeEntity("aligned", args)
        self.entities.append(entity)
        return entity

    def AddDimRotated(self, *args):
        entity = FakeEntity("rotated", args)
        self.entities.append(entity)
        return entity

    def AddDimDiametric(self, *args):
        entity = FakeEntity("diametric", args)
        self.entities.append(entity)
        return entity


class FakeLayers:
    def __init__(self):
        self.values = {}

    def Item(self, name):
        if name not in self.values:
            raise KeyError(name)
        return self.values[name]

    def Add(self, name):
        layer = type("Layer", (), {"Color": 256, "Linetype": "Continuous"})()
        self.values[name] = layer
        return layer


class FakeDocument:
    def __init__(self):
        self.ModelSpace = FakeModelSpace()
        self.Layers = FakeLayers()


def _session(monkeypatch):
    monkeypatch.setattr(acad_session, "acad_point", lambda value: tuple(value))
    session = acad_session.AutoCADSession()
    session.doc = FakeDocument()
    return session


def test_creates_real_dimension_entities_with_expected_arguments(monkeypatch):
    session = _session(monkeypatch)

    aligned = session.add_dim_aligned((0, 0, 0), (120, 0, 0), (60, -12, 0))
    rotated = session.add_dim_rotated((0, 0, 0), (0, 80, 0), (-12, 40, 0), 90)
    diameter = session.add_dim_diametric((15, 15, 0), 4.5, leader_length=8)

    assert [aligned.kind, rotated.kind, diameter.kind] == ["aligned", "rotated", "diametric"]
    assert all(entity.Layer == "DIM" for entity in (aligned, rotated, diameter))
    assert math.isclose(rotated.args[3], math.pi / 2)
    assert diameter.args[0] == (19.5, 15.0, 0.0)
    assert diameter.args[1] == (10.5, 15.0, 0.0)


def test_iter_model_entities_uses_count_item_proxy(monkeypatch):
    session = _session(monkeypatch)
    session.doc.ModelSpace.entities.extend(["line", "circle"])

    assert list(session.iter_model_entities()) == ["line", "circle"]
