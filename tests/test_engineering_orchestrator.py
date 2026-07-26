"""@brief 复杂机械工程 DAG 编排器回归测试。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from apps.desktop.cad_workbench.engineering_orchestrator import (
    CapabilityLevel,
    EngineeringPlan,
    PhaseStatus,
    build_engineering_plan,
    engineering_plan_from_dict,
    infer_affected_phases,
    requires_engineering_orchestration,
    replan_for_local_change,
)


BRIEF = "带倒角、沉孔、四零件装配、旋转马达、GB/T工程图和STEP/PDF交付的减速机构"


def test_complex_reducer_is_split_into_complete_engineering_dag() -> None:
    """@brief 给定综合减速机构需求必须拆成八个可验收阶段。"""
    plan = build_engineering_plan(BRIEF)

    assert [phase.id for phase in plan.phases] == [
        "requirements",
        "part-modeling",
        "holes-fillet-chamfer",
        "assembly-mates",
        "motion-study",
        "drawing-bom",
        "export-delivery",
        "final-review",
    ]
    assert plan.phase("part-modeling").depends_on == ("requirements",)
    assert plan.phase("assembly-mates").depends_on == ("holes-fillet-chamfer",)
    assert plan.phase("motion-study").depends_on == ("assembly-mates",)
    assert plan.phase("drawing-bom").depends_on == ("motion-study",)
    assert plan.phase("final-review").depends_on == ("export-delivery",)
    plan.validate()


def test_complex_classifier_does_not_force_simple_part_into_full_dag() -> None:
    """@brief 简单拉伸零件不应被强行加入装配、Motion 和图纸阶段。"""
    assert requires_engineering_orchestration(BRIEF) is True
    assert requires_engineering_orchestration("拉伸一个 50x30x10 mm 的矩形块") is False
    assert requires_engineering_orchestration("设计一个四零件装配体并输出 STEP") is True


def test_dynamic_dag_omits_unrequested_motion_and_drawing() -> None:
    """@brief 装配加 STEP 不能自动扩张为 Motion 和工程图项目。"""
    plan = build_engineering_plan("设计一个四零件装配体并输出 STEP")
    phase_ids = [phase.id for phase in plan.phases]

    assert phase_ids == ["requirements", "part-modeling", "assembly-mates", "export-delivery", "final-review"]
    assert plan.phase("assembly-mates").depends_on == ("part-modeling",)
    assert plan.phase("export-delivery").depends_on == ("assembly-mates",)
    with pytest.raises(KeyError):
        plan.phase("motion-study")


def test_routes_select_existing_skills_and_mcp_tools() -> None:
    """@brief 倒角、沉孔、装配和 Motion 必须路由到现有真实能力。"""
    plan = build_engineering_plan(BRIEF)

    feature_phase = plan.phase("holes-fillet-chamfer")
    assert "solidworks-fillet-chamfer-cnc" in feature_phase.skills
    assert "solidworks_create_hole_feature" in feature_phase.mcp_tools
    assert "solidworks_inspect_hole_features" in feature_phase.mcp_tools

    assembly_phase = plan.phase("assembly-mates")
    assert "solidworks_add_component" in assembly_phase.mcp_tools
    assert "solidworks_add_concentric_mate" in assembly_phase.mcp_tools

    motion_phase = plan.phase("motion-study")
    assert "solidworks_add_rotary_motor" in motion_phase.mcp_tools
    assert "solidworks_validate_motion_study" in motion_phase.mcp_tools
    assert "solidworks_export_active" in plan.phase("export-delivery").mcp_tools


def test_every_phase_has_artifacts_acceptance_risks_and_retry_policy() -> None:
    """@brief 每阶段必须能独立交付证据、验收和局部重试。"""
    plan = build_engineering_plan(BRIEF)

    for phase in plan.phases:
        assert phase.artifacts
        assert phase.acceptance
        assert phase.risks
        assert phase.retry_policy.max_attempts >= 1
        assert phase.retry_policy.fallback


def test_plan_never_claims_unexecuted_or_pilot_work_is_complete() -> None:
    """@brief 规划成功不能被误解为 CAD、BOM 或图纸已经完成。"""
    plan = build_engineering_plan(BRIEF)
    drawing = plan.phase("drawing-bom")

    assert all(phase.status != PhaseStatus.COMPLETED for phase in plan.phases)
    assert drawing.routes[0].level == CapabilityLevel.PILOT
    assert drawing.routes[0].execution_mode == "assisted_human_gate"
    assert drawing.human_gate is True
    assert not drawing.mcp_tools
    assert any("不能无人值守" in risk for risk in drawing.risks)


def test_capability_report_can_block_unimplemented_motion() -> None:
    """@brief 本机报告声明未实现时不得继续把 Motion 当作可自动执行。"""
    plan = build_engineering_plan(
        BRIEF,
        capability_report={
            "capabilities": {
                "motion_study": {
                    "implementation_status": "not_implemented",
                    "ready_for_unattended_use": False,
                }
            }
        },
    )

    motion = plan.phase("motion-study")
    assert motion.status == PhaseStatus.BLOCKED
    assert motion.routes[0].execution_mode == "blocked"
    assert motion.routes[0].level == CapabilityLevel.NOT_IMPLEMENTED

    invalid = replace(motion, status=PhaseStatus.COMPLETED)
    invalid_plan = replace(plan, phases=tuple(invalid if item.id == motion.id else item for item in plan.phases))
    with pytest.raises(ValueError, match="未实现能力"):
        invalid_plan.validate()


def test_probe_capability_alias_downgrades_pilot_drawing_route() -> None:
    """@brief 编排器必须识别真实能力探测器的 drawings 键。"""
    plan = build_engineering_plan(
        BRIEF,
        capability_report={
            "capabilities": {
                "drawings": {
                    "implementation_status": "not_implemented",
                    "ready_for_unattended_use": False,
                }
            }
        },
    )

    drawing = plan.phase("drawing-bom")
    assert drawing.status == PhaseStatus.BLOCKED
    assert drawing.routes[0].level == CapabilityLevel.NOT_IMPLEMENTED


def test_critical_cad_phases_share_single_serial_lane() -> None:
    """@brief 关键 SolidWorks COM 阶段不得被调度为并发写操作。"""
    plan = build_engineering_plan(BRIEF)
    critical = [phase for phase in plan.phases if phase.serial_required]

    assert plan.critical_cad_serial is True
    assert critical
    assert {phase.execution_lane for phase in critical} == {"solidworks-com"}
    assert plan.phase("requirements").serial_required is False


def test_local_hole_change_replans_only_affected_phase_and_descendants() -> None:
    """@brief 修改沉孔后保留已确认需求和零件，失效孔特征及所有下游结果。"""
    plan = build_engineering_plan(BRIEF)
    completed_phases = tuple(
        replace(phase, status=PhaseStatus.COMPLETED) if phase.id in {"requirements", "part-modeling"} else phase
        for phase in plan.phases
    )
    progressed = replace(plan, phases=completed_phases)

    replanned = replan_for_local_change(progressed, "把沉孔直径改为 12 mm")

    assert infer_affected_phases("把沉孔直径改为 12 mm") == ("holes-fillet-chamfer",)
    assert replanned.revision == 2
    assert replanned.phase("requirements").status == PhaseStatus.COMPLETED
    assert replanned.phase("part-modeling").status == PhaseStatus.COMPLETED
    assert replanned.phase("holes-fillet-chamfer").status == PhaseStatus.PLANNED
    assert replanned.phase("assembly-mates").status == PhaseStatus.PLANNED
    assert replanned.phase("drawing-bom").status == PhaseStatus.PLANNED
    assert replanned.phase("final-review").status == PhaseStatus.PLANNED
    assert "沉孔直径" in (replanned.change_request or "")


def test_plan_serializes_to_provider_friendly_values() -> None:
    """@brief 计划应可直接写入统一 Agent 任务 JSON。"""
    payload = build_engineering_plan(BRIEF).to_dict()

    assert payload["schema_version"] == "1.0"
    assert payload["phases"][0]["status"] == "planned"
    assert payload["phases"][5]["routes"][0]["level"] == "pilot"
    assert payload["phases"][5]["human_gate"] is True


def test_persisted_plan_round_trip_supports_follow_up_replanning() -> None:
    """@brief 队列中的上一轮 DAG 必须可恢复并继续做局部修改。"""
    original = build_engineering_plan(BRIEF)

    restored = engineering_plan_from_dict(original.to_dict())
    replanned = replan_for_local_change(restored, "把沉孔直径改为 12 mm")

    assert restored.to_dict() == original.to_dict()
    assert replanned.revision == original.revision + 1
    assert replanned.phase("holes-fillet-chamfer").status == PhaseStatus.PLANNED
