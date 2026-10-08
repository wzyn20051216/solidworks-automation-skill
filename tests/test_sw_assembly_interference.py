"""装配干涉报告无 COM 门禁测试。"""
from __future__ import annotations

from scripts.sw_assembly import get_interference_detection


def test_interference_report_pass_and_warn():
    class Item:
        Volume = 1.25
        Components = []

    class Detection:
        TreatSubAssembliesAsComponents = True
        TreatCoincidenceAsInterference = True

        def Done(self):
            return None

        def GetInterferenceCount(self):
            return 1

        def GetInterferences(self):
            return [Item()]

    class Model:
        InterferenceDetectionManager = Detection()

        def ClearSelection2(self, all_selections):
            assert all_selections

    report = get_interference_detection(Model())
    assert report["status"] == "warn"
    assert report["interference_count"] == 1
    assert report["manual_review_required"] is True
    assert report["items"][0]["name"] is None
    assert report["items"][0]["volume"] == 1.25


def test_interference_report_blocks_when_api_is_unavailable():
    report = get_interference_detection(object())
    assert report["status"] == "blocked"
    assert report["interference_count"] is None
    assert report["manual_review_required"] is True
