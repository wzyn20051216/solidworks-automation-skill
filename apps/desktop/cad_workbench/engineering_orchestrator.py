"""@brief 将复杂机械需求拆解为可审计的 SolidWorks 工程 DAG。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class CapabilityLevel(str, Enum):
    """@brief 描述技能实现和真实回归的成熟度。"""

    VERIFIED = "verified"
    PILOT = "pilot"
    REFERENCE_ONLY = "reference_only"
    NOT_IMPLEMENTED = "not_implemented"


class PhaseStatus(str, Enum):
    """@brief 描述单个工程阶段的执行状态。"""

    PLANNED = "planned"
    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(frozen=True)
class RetryPolicy:
    """@brief 描述阶段失败后的局部重试和降级策略。"""

    max_attempts: int
    strategy: str
    retryable_failures: Tuple[str, ...]
    fallback: str


@dataclass(frozen=True)
class CapabilityRoute:
    """@brief 描述某阶段选择的能力、技能和 MCP 工具。"""

    capability_id: str
    level: CapabilityLevel
    skills: Tuple[str, ...]
    mcp_tools: Tuple[str, ...]
    execution_mode: str
    reason: str


@dataclass(frozen=True)
class EngineeringPhase:
    """@brief 描述工程 DAG 中可独立执行、验收和重试的阶段。"""

    id: str
    name: str
    depends_on: Tuple[str, ...]
    routes: Tuple[CapabilityRoute, ...]
    artifacts: Tuple[str, ...]
    acceptance: Tuple[str, ...]
    risks: Tuple[str, ...]
    retry_policy: RetryPolicy
    status: PhaseStatus = PhaseStatus.PLANNED
    serial_required: bool = True
    execution_lane: str = "solidworks-com"
    human_gate: bool = False

    @property
    def skills(self) -> Tuple[str, ...]:
        """@brief 返回去重后的阶段技能列表。"""
        return _unique(item for route in self.routes for item in route.skills)

    @property
    def mcp_tools(self) -> Tuple[str, ...]:
        """@brief 返回去重后的阶段 MCP 工具列表。"""
        return _unique(item for route in self.routes for item in route.mcp_tools)


@dataclass(frozen=True)
class EngineeringPlan:
    """@brief 描述复杂机械项目的完整阶段计划。"""

    objective: str
    project_type: str
    phases: Tuple[EngineeringPhase, ...]
    assumptions: Tuple[str, ...]
    warnings: Tuple[str, ...]
    revision: int = 1
    change_request: Optional[str] = None
    critical_cad_serial: bool = True
    schema_version: str = "1.0"

    def phase(self, phase_id: str) -> EngineeringPhase:
        """@brief 按 ID 返回阶段，不存在时抛出明确错误。"""
        for item in self.phases:
            if item.id == phase_id:
                return item
        raise KeyError("未知工程阶段: {}".format(phase_id))

    def validate(self) -> None:
        """@brief 校验唯一 ID、依赖引用、无环性和 CAD 串行策略。"""
        phase_ids = [phase.id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("工程计划包含重复阶段 ID")

        known = set(phase_ids)
        for phase in self.phases:
            missing = set(phase.depends_on) - known
            if missing:
                raise ValueError("阶段 {} 引用了未知依赖: {}".format(phase.id, sorted(missing)))
            if phase.id in phase.depends_on:
                raise ValueError("阶段 {} 不能依赖自身".format(phase.id))
            if phase.status == PhaseStatus.COMPLETED and any(
                route.level == CapabilityLevel.NOT_IMPLEMENTED for route in phase.routes
            ):
                raise ValueError("未实现能力所在阶段不能标记为完成: {}".format(phase.id))
            if self.critical_cad_serial and phase.serial_required and phase.execution_lane != "solidworks-com":
                raise ValueError("关键 CAD 阶段必须进入 solidworks-com 串行通道: {}".format(phase.id))

        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(phase_id: str) -> None:
            if phase_id in visiting:
                raise ValueError("工程计划存在循环依赖: {}".format(phase_id))
            if phase_id in visited:
                return
            visiting.add(phase_id)
            for dependency in self.phase(phase_id).depends_on:
                visit(dependency)
            visiting.remove(phase_id)
            visited.add(phase_id)

        for phase_id in phase_ids:
            visit(phase_id)

    def to_dict(self) -> Dict[str, Any]:
        """@brief 返回适合任务协议和审计日志持久化的字典。"""
        payload = asdict(self)
        return _enum_values(payload)


def engineering_plan_from_dict(payload: Mapping[str, Any]) -> EngineeringPlan:
    """@brief 从队列持久化 JSON 恢复工程计划，用于对话式局部重规划。"""
    phases: List[EngineeringPhase] = []
    for raw_phase in payload.get("phases", []):
        if not isinstance(raw_phase, Mapping):
            continue
        routes = tuple(
            CapabilityRoute(
                capability_id=str(route.get("capability_id") or ""),
                level=CapabilityLevel(str(route.get("level") or CapabilityLevel.NOT_IMPLEMENTED.value)),
                skills=tuple(str(item) for item in route.get("skills", [])),
                mcp_tools=tuple(str(item) for item in route.get("mcp_tools", [])),
                execution_mode=str(route.get("execution_mode") or "blocked"),
                reason=str(route.get("reason") or ""),
            )
            for route in raw_phase.get("routes", [])
            if isinstance(route, Mapping)
        )
        raw_retry = raw_phase.get("retry_policy") if isinstance(raw_phase.get("retry_policy"), Mapping) else {}
        phases.append(
            EngineeringPhase(
                id=str(raw_phase.get("id") or ""),
                name=str(raw_phase.get("name") or ""),
                depends_on=tuple(str(item) for item in raw_phase.get("depends_on", [])),
                routes=routes,
                artifacts=tuple(str(item) for item in raw_phase.get("artifacts", [])),
                acceptance=tuple(str(item) for item in raw_phase.get("acceptance", [])),
                risks=tuple(str(item) for item in raw_phase.get("risks", [])),
                retry_policy=RetryPolicy(
                    max_attempts=int(raw_retry.get("max_attempts") or 1),
                    strategy=str(raw_retry.get("strategy") or "局部重试"),
                    retryable_failures=tuple(str(item) for item in raw_retry.get("retryable_failures", [])),
                    fallback=str(raw_retry.get("fallback") or "转人工复核"),
                ),
                status=PhaseStatus(str(raw_phase.get("status") or PhaseStatus.PLANNED.value)),
                serial_required=bool(raw_phase.get("serial_required", True)),
                execution_lane=str(raw_phase.get("execution_lane") or "solidworks-com"),
                human_gate=bool(raw_phase.get("human_gate", False)),
            )
        )
    plan = EngineeringPlan(
        objective=str(payload.get("objective") or ""),
        project_type=str(payload.get("project_type") or "complex_mechanical_system"),
        phases=tuple(phases),
        assumptions=tuple(str(item) for item in payload.get("assumptions", [])),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        revision=int(payload.get("revision") or 1),
        change_request=str(payload.get("change_request")) if payload.get("change_request") else None,
        critical_cad_serial=bool(payload.get("critical_cad_serial", True)),
        schema_version=str(payload.get("schema_version") or "1.0"),
    )
    plan.validate()
    return plan


@dataclass(frozen=True)
class _CapabilityDefinition:
    """@brief 保存编排器内置的保守能力清单。"""

    level: CapabilityLevel
    skills: Tuple[str, ...]
    mcp_tools: Tuple[str, ...]
    reason: str


MAIN_SKILL = "solidworks-automation"
VIBECAD_SKILL = "solidworks-vibecad"
FILLET_SKILL = "solidworks-fillet-chamfer-cnc"


CAPABILITIES: Mapping[str, _CapabilityDefinition] = {
    "requirements_planning": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (VIBECAD_SKILL, MAIN_SKILL),
        (),
        "VibeCAD 可把自然语言转换为参数化设计计划；正式执行前仍需确认关键尺寸、载荷和制造约束。",
    ),
    "part_and_features": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL, VIBECAD_SKILL),
        ("solidworks_health_check", "solidworks_new_document", "solidworks_create_basic_part", "solidworks_save_document"),
        "参数化零件和基础特征已有真实 COM 封装；复杂轮廓需由技能脚本执行并复核。",
    ),
    "holes_and_finishing": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL, FILLET_SKILL),
        ("solidworks_create_hole_feature", "solidworks_inspect_hole_features", "solidworks_save_document"),
        "盲孔、沉孔、沉头孔、半圆槽及孔位验收已验证；圆角和倒角由专项技能稳定路由。",
    ),
    "assembly_and_mates": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        (
            "solidworks_new_document",
            "solidworks_add_component",
            "solidworks_set_component_fixed",
            "solidworks_add_coincident_mate",
            "solidworks_add_distance_mate",
            "solidworks_add_concentric_mate",
            "solidworks_save_document",
        ),
        "组件插入以及重合、距离、同心 Mate 已验证；必须另外核对自由度和 Mate 特征树。",
    ),
    "motion_study": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        ("solidworks_add_rotary_motor", "solidworks_inspect_motion_studies", "solidworks_validate_motion_study"),
        "当前仅将旋转马达创建、计算和结果审计视为已验证能力。",
    ),
    "drawings_and_bom": _CapabilityDefinition(
        CapabilityLevel.PILOT,
        (MAIN_SKILL,),
        (),
        "工程图处于 Pilot，BOM 和 GB/T 图框、尺寸链必须人工复核，禁止无人值守宣称完成。",
    ),
    "export_delivery": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        ("solidworks_export_active",),
        "STEP、PDF 等已通过窄接口导出，但每个目标文件仍需检查存在性、格式和哈希。",
    ),
    "geometry_and_delivery_review": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        (
            "solidworks_review_active",
            "solidworks_inspect_hole_features",
            "solidworks_inspect_motion_studies",
            "solidworks_validate_motion_study",
        ),
        "多视图、孔槽和 Motion 证据可自动收集；GB/T 图纸仍保留人工终审。",
    ),
}

# 编排器能力比探测器粒度更细；这些别名把本机类型库结果传递到相关阶段。
CAPABILITY_REPORT_ALIASES: Mapping[str, str] = {
    "holes_and_finishing": "part_and_features",
    "drawings_and_bom": "drawings",
    "export_delivery": "part_and_features",
    "geometry_and_delivery_review": "part_and_features",
}

_COMPLEX_PROJECT_SIGNALS: Tuple[Tuple[str, ...], ...] = (
    ("多零件", "多个零件", "装配", "装配体", "整机", "机构", "总成"),
    ("mate", "配合", "同心", "自由度", "干涉"),
    ("motion", "运动仿真", "运动算例", "马达", "转速", "动力学"),
    ("工程图", "图纸", "bom", "明细表", "gb/t", "国标"),
    ("step", "pdf", "交付包", "完整交付"),
    ("沉孔", "盲孔", "槽", "圆角", "倒角", "孔位公差"),
)


def requires_engineering_orchestration(brief: str) -> bool:
    """@brief 判断需求是否需要跨阶段工程 DAG，而不是单步零件任务。

    @param brief 用户自然语言需求。
    @return 命中至少两个独立工程域，或明确要求整机/综合工程时返回 ``True``。
    """
    normalized = brief.strip().lower()
    if not normalized:
        return False
    if any(keyword in normalized for keyword in ("综合工程", "完整工程", "全流程", "整机设计")):
        return True
    matched_domains = sum(any(keyword in normalized for keyword in domain) for domain in _COMPLEX_PROJECT_SIGNALS)
    return matched_domains >= 2


def _unique(values: Iterable[str]) -> Tuple[str, ...]:
    """@brief 保持原顺序并移除重复字符串。"""
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _enum_values(value: Any) -> Any:
    """@brief 递归将枚举转换为 JSON 兼容值。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_enum_values(item) for item in value]
    return value


def _normalise_level(raw_status: str, fallback: CapabilityLevel) -> CapabilityLevel:
    """@brief 将能力探测器状态归一化为编排器成熟度。"""
    status = raw_status.strip().lower()
    if status.startswith("verified"):
        return CapabilityLevel.VERIFIED
    if status == "pilot":
        return CapabilityLevel.PILOT
    if status == "reference_only":
        return CapabilityLevel.REFERENCE_ONLY
    if status == "not_implemented":
        return CapabilityLevel.NOT_IMPLEMENTED
    return fallback


def _route(capability_id: str, capability_report: Optional[Mapping[str, Any]]) -> CapabilityRoute:
    """@brief 根据内置清单和可选本机探测报告选择执行路线。"""
    definition = CAPABILITIES[capability_id]
    level = definition.level
    if capability_report:
        report_capabilities = capability_report.get("capabilities", {})
        report_key = capability_id
        if isinstance(report_capabilities, Mapping) and report_key not in report_capabilities:
            report_key = CAPABILITY_REPORT_ALIASES.get(capability_id, capability_id)
        report_item = report_capabilities.get(report_key, {}) if isinstance(report_capabilities, Mapping) else {}
        if isinstance(report_item, Mapping):
            level = _normalise_level(str(report_item.get("implementation_status", "")), level)
            if report_item.get("ready_for_unattended_use") is False and level == CapabilityLevel.VERIFIED:
                level = CapabilityLevel.PILOT

    if level == CapabilityLevel.VERIFIED:
        mode = "mcp_and_skill" if definition.mcp_tools else "skill"
    elif level == CapabilityLevel.PILOT:
        mode = "assisted_human_gate"
    else:
        mode = "blocked"
    return CapabilityRoute(capability_id, level, definition.skills, definition.mcp_tools, mode, definition.reason)


def _phase_status(routes: Sequence[CapabilityRoute]) -> PhaseStatus:
    """@brief 未实现或仅参考能力默认阻塞，其余阶段默认待执行。"""
    blocked_levels = {CapabilityLevel.REFERENCE_ONLY, CapabilityLevel.NOT_IMPLEMENTED}
    return PhaseStatus.BLOCKED if any(route.level in blocked_levels for route in routes) else PhaseStatus.PLANNED


def _phase(
    phase_id: str,
    name: str,
    depends_on: Sequence[str],
    capability_ids: Sequence[str],
    artifacts: Sequence[str],
    acceptance: Sequence[str],
    risks: Sequence[str],
    retry_policy: RetryPolicy,
    capability_report: Optional[Mapping[str, Any]],
    human_gate: bool = False,
    serial_required: bool = True,
) -> EngineeringPhase:
    """@brief 创建状态保守、能力可追溯的工程阶段。"""
    routes = tuple(_route(item, capability_report) for item in capability_ids)
    return EngineeringPhase(
        id=phase_id,
        name=name,
        depends_on=tuple(depends_on),
        routes=routes,
        artifacts=tuple(artifacts),
        acceptance=tuple(acceptance),
        risks=tuple(risks),
        retry_policy=retry_policy,
        status=_phase_status(routes),
        serial_required=serial_required,
        execution_lane="solidworks-com" if serial_required else "planning",
        human_gate=human_gate or any(route.level != CapabilityLevel.VERIFIED for route in routes),
    )


def build_engineering_plan(
    brief: str,
    capability_report: Optional[Mapping[str, Any]] = None,
) -> EngineeringPlan:
    """@brief 将自然语言复杂机械任务拆成八阶段 SolidWorks DAG。

    @param brief 用户的自然语言工程需求。
    @param capability_report 可选的 ``sw_capability_probe.py`` 报告。
    @return 默认均为待执行或阻塞状态的工程计划，不代表任何 CAD 工作已完成。
    """
    objective = brief.strip()
    if not objective:
        raise ValueError("复杂机械任务描述不能为空")

    planning_retry = RetryPolicy(2, "补齐缺失约束后重新规划", ("missing_requirement", "ambiguous_constraint"), "转人工确认关键工程参数")
    cad_retry = RetryPolicy(2, "仅回滚并重试当前阶段", ("com_error", "rebuild_error", "selection_error"), "缩小特征批次并保留失败证据")
    review_retry = RetryPolicy(1, "返回首个失败阶段局部返工", ("acceptance_failed", "artifact_missing"), "停止交付并请求人工复核")

    phase_catalog = (
        _phase(
            "requirements",
            "需求澄清与工程约束",
            (),
            ("requirements_planning",),
            ("requirements.json", "design_plan.json", "assumptions.json"),
            ("零件数量、功能、接口和运动目标明确", "关键尺寸、材料、载荷、公差和制造方式有来源或显式假设", "交付格式和验收门禁完整"),
            ("自然语言缺少尺寸或载荷时可能产生不可制造方案", "GB/T 版本和企业模板未指定时不能猜测"),
            planning_retry,
            capability_report,
            human_gate=True,
            serial_required=False,
        ),
        _phase(
            "part-modeling",
            "参数化零件建模",
            ("requirements",),
            ("part_and_features",),
            ("四个或需求指定数量的 SLDPRT 文件", "part_parameters.json", "part_rebuild_report.json"),
            ("零件数量与需求一致且文件可原生打开", "草图与关键特征可重建", "质量属性和包围盒符合设计参数"),
            ("欠约束草图导致后续特征漂移", "零件接口尺寸不一致导致装配失败"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "holes-fillet-chamfer",
            "孔槽、圆角与倒角",
            ("part-modeling",),
            ("holes_and_finishing",),
            ("feature_parameters.json", "hole_geometry_evidence.json", "updated SLDPRT files"),
            ("沉孔、盲孔或槽的规格、深度和位置满足参数", "孔轴线位置和孔径公差通过几何验收", "圆角倒角存在且模型无重建错误"),
            ("特征顺序不稳可能导致圆角求解失败", "B-Rep 不能单独证明盲孔或通孔，需交叉检查创建参数"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "assembly-mates",
            "装配体与 Mate",
            ("holes-fillet-chamfer",),
            ("assembly_and_mates",),
            ("assembly.SLDASM", "mate_inventory.json", "degree_of_freedom_report.json"),
            ("组件数量和引用文件完整", "同心、重合、距离等 Mate 与设计自由度预算一致", "旋转件未被错误锁定且无明显干涉"),
            ("过定义 Mate 会锁死机构", "组件名称、配置或基准面语言差异可能导致选择失败"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "motion-study",
            "Motion 运动算例",
            ("assembly-mates",),
            ("motion_study",),
            ("motion_study.json", "motion_validation.json", "calculated Motion Study in SLDASM"),
            ("旋转马达对象真实存在", "算例时长和马达数量符合计划", "计算结果存在且 results_out_of_date=False"),
            ("当前已验证范围不包含接触、摩擦、弹簧或完整动力学", "Motion Analysis 许可证缺失时只能明确降级，不能伪造结果"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "drawing-bom",
            "GB/T 工程图与 BOM",
            ("motion-study",),
            ("drawings_and_bom",),
            ("part_and_assembly_drawings.SLDDRW", "bom.csv", "drawing_review_checklist.json"),
            ("图幅、图框、标题栏、字体和线型符合指定 GB/T/企业模板", "尺寸链、孔槽规格和定位尺寸完整", "BOM 数量、代号、材料和装配引用一致", "人工目视复核无重叠、压线和标题栏侵入"),
            ("该能力仍为 Pilot，不能无人值守交付", "自动尺寸和 BOM 字段可能缺项或布局拥挤"),
            RetryPolicy(2, "按视图或表格局部重排后复核", ("layout_overlap", "dimension_missing", "bom_mismatch"), "保留 SLDDRW 并转人工工程师终审"),
            capability_report,
            human_gate=True,
        ),
        _phase(
            "export-delivery",
            "STEP/PDF 与交付导出",
            ("drawing-bom",),
            ("export_delivery",),
            ("assembly.step", "drawing.pdf", "artifact_ledger.json"),
            ("STEP 可重新打开且实体/组件数量合理", "PDF 页数、图幅和内容非空", "全部交付物存在、非空并记录 SHA-256"),
            ("导出成功返回值不能替代文件格式校验", "引用丢失或字体替换会造成交付偏差"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "final-review",
            "综合复核与交付门禁",
            ("export-delivery",),
            ("geometry_and_delivery_review",),
            ("isometric/front/top/right previews", "review_report.json", "review_gate.json"),
            ("多视图目视检查通过", "零件、孔槽、Mate、Motion、图纸、BOM 和导出证据逐项通过", "任何 Pilot 项均有人类签署，失败项未被标记完成"),
            ("仅检查文件存在会漏掉几何和装配错误", "局部修改可能使下游图纸或 Motion 结果过期"),
            review_retry,
            capability_report,
            human_gate=True,
        ),
    )

    normalized = objective.lower()
    requested_features = any(keyword in normalized for keyword in ("孔", "槽", "圆角", "倒角", "公差", "螺纹"))
    requested_assembly = any(keyword in normalized for keyword in ("装配", "装配体", "整机", "机构", "总成", "mate", "配合", "干涉", "自由度"))
    requested_motion = any(keyword in normalized for keyword in ("motion", "运动仿真", "运动算例", "马达", "转速", "动力学"))
    requested_drawing = any(keyword in normalized for keyword in ("工程图", "图纸", "bom", "明细表", "gb/t", "国标"))
    requested_export = any(keyword in normalized for keyword in ("step", "stp", "stl", "pdf", "导出", "交付"))
    requested_ids = {"requirements", "part-modeling", "final-review"}
    if requested_features:
        requested_ids.add("holes-fillet-chamfer")
    if requested_assembly or requested_motion:
        requested_ids.add("assembly-mates")
    if requested_motion:
        requested_ids.add("motion-study")
    if requested_drawing:
        requested_ids.add("drawing-bom")
    if requested_export:
        requested_ids.add("export-delivery")

    selected_phases: List[EngineeringPhase] = []
    previous_phase_id: Optional[str] = None
    for phase in phase_catalog:
        if phase.id not in requested_ids:
            continue
        dependencies = () if previous_phase_id is None else (previous_phase_id,)
        selected_phases.append(replace(phase, depends_on=dependencies))
        previous_phase_id = phase.id
    phases = tuple(selected_phases)

    warnings = tuple(
        "{} 使用 {}，必须经过人工门禁。".format(phase.name, route.level.value)
        for phase in phases
        for route in phase.routes
        if route.level != CapabilityLevel.VERIFIED
    )
    plan = EngineeringPlan(
        objective=objective,
        project_type="complex_mechanical_system",
        phases=phases,
        assumptions=(
            "未提供的尺寸、材料、载荷、公差和标准版本只记录为待确认项，不自动写成事实。",
            "所有 SolidWorks COM 写操作进入 solidworks-com 单并发通道。",
            "本计划描述待执行工作；阶段路由成功不等于模型或交付物已经完成。",
        ),
        warnings=warnings,
    )
    plan.validate()
    return plan


_CHANGE_PHASE_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("requirements", ("需求", "材料", "载荷", "标准", "数量")),
    ("part-modeling", ("零件", "外形", "尺寸", "草图", "拉伸")),
    ("holes-fillet-chamfer", ("孔", "沉孔", "盲孔", "槽", "圆角", "倒角", "公差")),
    ("assembly-mates", ("装配", "mate", "配合", "同心", "干涉", "自由度")),
    ("motion-study", ("motion", "运动", "马达", "转速", "动画")),
    ("drawing-bom", ("工程图", "图纸", "bom", "明细表", "gb/t", "标注")),
    ("export-delivery", ("step", "pdf", "导出", "交付")),
    ("final-review", ("复核", "验收", "预览")),
)


def infer_affected_phases(change_request: str) -> Tuple[str, ...]:
    """@brief 根据局部修改描述推断最靠前的受影响阶段。"""
    normalized = change_request.strip().lower()
    if not normalized:
        raise ValueError("局部修改描述不能为空")
    matched = [phase_id for phase_id, keywords in _CHANGE_PHASE_KEYWORDS if any(keyword in normalized for keyword in keywords)]
    return (matched[0],) if matched else ("requirements",)


def replan_for_local_change(
    plan: EngineeringPlan,
    change_request: str,
    affected_phase_ids: Optional[Sequence[str]] = None,
) -> EngineeringPlan:
    """@brief 对局部修改阶段及其所有 DAG 后继重新规划。

    未受影响且已经有外部验收证据的阶段可保留原状态；受影响阶段和后继统一回到
    ``planned``（原能力为阻塞时仍保持 ``blocked``），从而避免沿用过期结果。
    """
    plan.validate()
    roots = tuple(affected_phase_ids or infer_affected_phases(change_request))
    known = {phase.id for phase in plan.phases}
    unknown = set(roots) - known
    if unknown:
        raise ValueError("局部修改引用了未知阶段: {}".format(sorted(unknown)))

    invalidated: Set[str] = set(roots)
    changed = True
    while changed:
        changed = False
        for phase in plan.phases:
            if phase.id not in invalidated and any(parent in invalidated for parent in phase.depends_on):
                invalidated.add(phase.id)
                changed = True

    phases: List[EngineeringPhase] = []
    for phase in plan.phases:
        if phase.id not in invalidated:
            phases.append(phase)
            continue
        next_status = _phase_status(phase.routes)
        phases.append(replace(phase, status=next_status))

    replanned = replace(
        plan,
        phases=tuple(phases),
        revision=plan.revision + 1,
        change_request=change_request.strip(),
        warnings=plan.warnings
        + ("局部修改已使以下阶段及其后继失效: {}".format(", ".join(sorted(invalidated))),),
    )
    replanned.validate()
    return replanned
