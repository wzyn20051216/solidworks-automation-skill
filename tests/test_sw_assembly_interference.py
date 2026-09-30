"""装配干涉报告无 COM 门禁测试(现代/旧版 API 双路径)。"""
from __future__ import annotations

from scripts.sw_assembly import get_interference_detection


def test_interference_report_pass_and_warn_legacy_api():
    class Item:
        Name = "干涉-1"
        Volume = 1.25

    class Detection:
        TreatSubAssembliesAsComponents = True
        TreatCoincidenceAsInterference = True

        def Done(self):
            return None

        def GetInterferenceCount(self):
            return 1

        def GetInterference(self, index):
            assert index == 0
            return Item()

    class Model:
        InterferenceDetection = Detection()

    report = get_interference_detection(Model())
    assert report["status"] == "warn"
    assert report["api"] == "legacy"
    assert report["interference_count"] == 1
    assert report["manual_review_required"] is True
    assert report["items"][0]["name"] == "干涉-1"
    assert report["interfering_components"] == []


class _ModernComponent:
    def __init__(self, name):
        self.Name2 = name


class _ModernInterference:
    def __init__(self):
        self._components = [_ModernComponent("housing-1"), _ModernComponent("shaft-1")]

    def IGetComponents(self):
        return list(self._components)


class _ModernManager:
    TreatSubAssembliesAsComponents = True
    TreatCoincidenceAsInterference = True

    def __init__(self, count, interferences, components):
        self._count = count
        self._interferences = interferences
        self._components = components

    def Done(self):
        return None

    def GetInterferenceCount(self):
        return self._count

    def GetInterferences(self):
        return list(self._interferences)

    def GetInterferenceComponents(self):
        return list(self._components)


def test_interference_report_uses_modern_manager_when_available():
    manager = _ModernManager(1, [_ModernInterference()], [_ModernComponent("housing-1"), _ModernComponent("shaft-1")])

    class Model:
        InterferenceDetectionManager = manager

    report = get_interference_detection(Model())
    assert report["status"] == "warn"
    assert report["api"] == "modern"
    assert report["interference_count"] == 1
    assert report["interfering_components"] == ["housing-1", "shaft-1"]
    assert report["items"][0]["name"] == "housing-1 & shaft-1"


def test_interference_report_pass_when_no_interference_modern():
    manager = _ModernManager(0, [], [])

    class Model:
        InterferenceDetectionManager = manager

    report = get_interference_detection(Model())
    assert report["status"] == "pass"
    assert report["interference_count"] == 0
    assert report["manual_review_required"] is False


def test_interference_report_blocks_when_api_is_unavailable():
    report = get_interference_detection(object())
    assert report["status"] == "blocked"
    assert report["interference_count"] is None
    assert report["manual_review_required"] is True
    assert report["interfering_components"] == []
