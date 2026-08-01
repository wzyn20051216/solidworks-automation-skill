"""装配干涉报告无 COM 门禁测试。"""
from __future__ import annotations

from scripts.sw_assembly import get_interference_detection


def test_interference_report_pass_and_warn():
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
    assert report["interference_count"] == 1
    assert report["manual_review_required"] is True
    assert report["items"][0]["name"] == "干涉-1"


def test_interference_report_blocks_when_api_is_unavailable():
    report = get_interference_detection(object())
    assert report["status"] == "blocked"
    assert report["interference_count"] is None
    assert report["manual_review_required"] is True
