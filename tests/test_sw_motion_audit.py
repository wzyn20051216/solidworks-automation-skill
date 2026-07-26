"""@brief Motion Study 机器可读审计回归测试。"""

from scripts import sw_motion


class FakeResults:
    """@brief 模拟需要重新计算的运动结果。"""

    IsOutOfDate = True


class FakeMotionFeature:
    """@brief 模拟真实旋转马达 Motion Feature。"""

    Name = "旋转马达"
    GetType = 102
    GetTypeName2 = "AEMRotationalMotor"


class FakeStudy:
    """@brief 模拟包含一个马达的 Motion Study。"""

    Name = "轴系运动"
    StudyType = 1
    IsActive = True
    IsPlaying = False

    def GetDuration(self):
        return 4.0

    def GetNumOfExternalMotors(self):
        return 1

    def GetNumOfExternalForces(self):
        return 0

    def GetMotionFeaturesCount(self):
        return 1

    def GetMotionFeatures(self):
        return (FakeMotionFeature(),)

    def GetResults(self, study_type):
        assert study_type == 1
        return FakeResults()


class FakeManager:
    """@brief 模拟 MotionStudyManager。"""

    def GetMotionStudyCount(self):
        return 1

    def GetMotionStudyNames(self):
        return ("轴系运动",)

    def GetMotionStudy(self, name):
        assert name == "轴系运动"
        return FakeStudy()


def test_motion_summary_reports_stale_results(monkeypatch) -> None:
    monkeypatch.setattr(sw_motion, "get_motion_study_manager", lambda model: FakeManager())
    monkeypatch.setattr(sw_motion, "ensure_motion_type_library", lambda raise_on_error=False: "swmotionstudy.tlb")

    summary = sw_motion.collect_motion_study_summary(object())

    assert summary["study_count"] == 1
    assert summary["studies"][0]["motor_count"] == 1
    assert summary["studies"][0]["motor_feature_count"] == 1
    assert summary["studies"][0]["results_available"] is True
    assert summary["studies"][0]["results_out_of_date"] is True


def test_motion_validation_rejects_stale_results() -> None:
    result = sw_motion.validate_motion_study_summary(
        {
            "motion_type_library": "swmotionstudy.tlb",
            "study_count": 1,
            "studies": [{
                "name": "轴系运动",
                "available": True,
                "study_type": 1,
                "duration_seconds": 4.0,
                "motor_count": 1,
                "results_available": True,
                "results_out_of_date": True,
            }],
        },
        expected_study_type=1,
    )

    assert result["status"] == "fail"
    assert any(item["id"] == "results-fresh" and not item["passed"] for item in result["checks"])


def test_motion_validation_passes_complete_fresh_study() -> None:
    result = sw_motion.validate_motion_study_summary(
        {
            "motion_type_library": "swmotionstudy.tlb",
            "study_count": 1,
            "studies": [{
                "name": "叶轮运动",
                "available": True,
                "study_type": 1,
                "duration_seconds": 6.0,
                "motor_count": 1,
                "results_available": True,
                "results_out_of_date": False,
            }],
        },
        study_name="叶轮运动",
        expected_study_type=1,
        minimum_duration_seconds=4.0,
    )

    assert result["status"] == "pass"
    assert all(item["passed"] for item in result["checks"])


def test_motion_validation_rejects_missing_study_and_type_library() -> None:
    result = sw_motion.validate_motion_study_summary(
        {"motion_type_library": None, "study_count": 0, "studies": []},
        study_name="不存在",
    )

    assert result["status"] == "fail"
    assert {item["id"] for item in result["checks"]} == {"study-present", "type-library"}
