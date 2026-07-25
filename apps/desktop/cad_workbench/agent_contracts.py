"""@brief 企业级 Agent 控制平面的任务契约与 prompt 编译器。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


AgentStage = Literal["intake", "plan", "execute", "review", "deliver"]
SandboxLevel = Literal["read-only", "workspace-write", "danger-full-access"]

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILL_PATH = REPO_ROOT / "SKILL.md"
DEFAULT_OUTPUT_SCHEMA = Path(__file__).resolve().parent / "schemas" / "codex_final_response.schema.json"


@dataclass(frozen=True)
class AgentRole:
    """@brief 描述企业 Agent 流水线中的一个角色。"""

    name: str
    stage: AgentStage
    responsibility: str
    can_write: bool = False


@dataclass(frozen=True)
class AgentRunPolicy:
    """@brief 描述 Codex 执行权限、审计和交付策略。"""

    sandbox: SandboxLevel = "workspace-write"
    approval: str = "never"
    timeout_seconds: int = 1800
    require_skill_read: bool = True
    require_tests: bool = True
    require_commit: bool = True
    require_push: bool = True
    require_reviewer_pass: bool = True
    output_schema_path: Path = DEFAULT_OUTPUT_SCHEMA


@dataclass(frozen=True)
class EnterpriseAgentProfile:
    """@brief 描述 CAD Studio 的企业 Agent 能力边界。"""

    name: str = "CAD Studio Enterprise Agent"
    skill_path: Path = DEFAULT_SKILL_PATH
    roles: tuple[AgentRole, ...] = (
        AgentRole("Intake", "intake", "读取 UI 配置、项目路径、制造约束和用户目标。"),
        AgentRole("Planner", "plan", "把需求拆为 CAD 建模、图纸、验证、交付和 Git 任务。"),
        AgentRole("Executor", "execute", "使用 solidworks-automation skill 执行建模、图纸和文件操作。", can_write=True),
        AgentRole("Reviewer", "review", "按 3D 打印真实开孔、GB/T 图纸、测试和交付清单复核。"),
        AgentRole("Delivery", "deliver", "整理输出位置、验证结果、commit/push 状态和失败原因。", can_write=True),
    )
    policy: AgentRunPolicy = field(default_factory=AgentRunPolicy)


DEFAULT_PROFILE = EnterpriseAgentProfile()


def profile_to_json(profile: EnterpriseAgentProfile = DEFAULT_PROFILE) -> dict[str, Any]:
    """@brief 把 Agent Profile 转成可写入任务 JSON 的结构。"""
    payload = asdict(profile)
    payload["skill_path"] = str(profile.skill_path)
    payload["policy"]["output_schema_path"] = str(profile.policy.output_schema_path)
    return payload


def load_profile(path: Path | None = None) -> EnterpriseAgentProfile:
    """@brief 读取企业 Agent Profile，当前默认返回内置配置。"""
    if path is None:
        return DEFAULT_PROFILE
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    policy_raw = raw.get("policy", {})
    policy = AgentRunPolicy(
        sandbox=policy_raw.get("sandbox", "danger-full-access"),
        approval=str(policy_raw.get("approval", "never")),
        timeout_seconds=int(policy_raw.get("timeout_seconds", 1800)),
        require_skill_read=bool(policy_raw.get("require_skill_read", True)),
        require_tests=bool(policy_raw.get("require_tests", True)),
        require_commit=bool(policy_raw.get("require_commit", True)),
        require_push=bool(policy_raw.get("require_push", True)),
        require_reviewer_pass=bool(policy_raw.get("require_reviewer_pass", True)),
        output_schema_path=Path(str(policy_raw.get("output_schema_path", DEFAULT_OUTPUT_SCHEMA))),
    )
    roles = tuple(
        AgentRole(
            name=str(item.get("name", "Agent")),
            stage=item.get("stage", "execute"),
            responsibility=str(item.get("responsibility", "")),
            can_write=bool(item.get("can_write", False)),
        )
        for item in raw.get("roles", [])
    )
    return EnterpriseAgentProfile(
        name=str(raw.get("name", DEFAULT_PROFILE.name)),
        skill_path=Path(str(raw.get("skill_path", DEFAULT_SKILL_PATH))),
        roles=roles or DEFAULT_PROFILE.roles,
        policy=policy,
    )


def compile_codex_prompt(job: dict[str, Any], profile: EnterpriseAgentProfile = DEFAULT_PROFILE) -> str:
    """@brief 将 UI 结构化任务编译为 Codex 企业执行 prompt。"""
    objective = str(job.get("objective") or job.get("detail") or "执行 CAD 自动化任务")
    target = str(job.get("target") or "solidworks-automation skill")
    output = str(job.get("expectedOutput") or "完成实现、验证并总结结果")
    project_path = str(job.get("projectPath") or "未指定")
    user_prompt = str(job.get("prompt") or "").strip()
    strict_rules = job.get("strictRules") if isinstance(job.get("strictRules"), list) else []
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}

    role_lines = "\n".join(
        f"- {role.stage.upper()} / {role.name}: {role.responsibility} 写权限={'是' if role.can_write else '否'}"
        for role in profile.roles
    )
    rule_lines = "\n".join(f"- {rule}" for rule in strict_rules) or "\n".join(
        [
            "- 必须遵守 3D 打印真实开孔要求，不能只画外观线。",
            "- 必须遵守 GB/T 风格图纸规范，尺寸链、孔位和技术要求要完整。",
            "- 修改后必须运行可用验证，并提交中文 commit。",
        ]
    )
    ui_config_text = json.dumps(ui_config, ensure_ascii=False, indent=2) if ui_config else "{}"

    return "\n".join(
        [
            "你是 Codex，正在作为 CAD Studio Enterprise Agent 的执行核心运行。",
            "本次任务来自图形化界面，必须按企业级 Agent 流程执行，而不是自由聊天。",
            "",
            "【必须读取的 Skill】",
            str(profile.skill_path),
            "执行前必须完整阅读并遵守该 SKILL.md 及相关子技能；若任务暴露出可沉淀规范，需更新 skill 或文档。",
            "",
            "【Agent 流水线】",
            role_lines,
            "",
            "【任务目标】",
            objective,
            "",
            "【目标对象】",
            target,
            "",
            "【项目/模型路径】",
            project_path,
            "",
            "【期望输出】",
            output,
            "",
            "【UI 结构化配置】",
            ui_config_text,
            "",
            "【强制规则】",
            rule_lines,
            "",
            "【质量门禁】",
            "- Planner 必须先给出可执行步骤和风险点。",
            "- Executor 修改文件后必须运行针对性验证。",
            "- Reviewer 必须检查真实开孔、图纸规范、文件输出、测试结果和 Git 状态。",
            "- Delivery 必须说明输出路径、验证命令、commit/push 状态和残余风险。",
            "- 如果无法完成，必须写明阻塞原因，不允许假装完成。",
            "",
            "【用户补充 prompt】",
            user_prompt or "无",
            "",
            "【最终响应格式】",
            "请输出符合 JSON schema 的最终结果，字段包含 summary、changedFiles、verification、risks、nextSteps。",
        ]
    )


def safe_job_id(value: Any) -> str:
    """@brief 返回适合文件名和审计日志的任务 ID。"""
    text = str(value or "")
    safe = "".join(ch for ch in text if ch.isascii() and (ch.isalnum() or ch in "-_"))
    if not safe:
        raise ValueError("任务缺少有效 id")
    return safe[:96]


def resolve_workspace(job: dict[str, Any], allowed_roots: list[Path] | None = None) -> Path:
    """@brief 校验并返回任务可用工作区。"""
    roots = [root.expanduser().resolve() for root in (allowed_roots or [REPO_ROOT])]
    raw_cwd = Path(str(job.get("cwd") or REPO_ROOT)).expanduser().resolve()
    if raw_cwd.anchor == raw_cwd.as_posix():
        raise ValueError("拒绝使用文件系统根目录作为 cwd")
    if not any(root == raw_cwd or root in raw_cwd.parents for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise ValueError(f"cwd 不在允许工作区内: {raw_cwd}; allowed={allowed}")
    return raw_cwd


def codex_output_path(job: dict[str, Any], cwd: Path) -> Path:
    """@brief 返回固定的 Codex 输出路径，不接受任务自定义越界路径。"""
    job_id = safe_job_id(job.get("id"))
    output = cwd / "ai_team" / f"{job_id}_codex_result.md"
    resolved = output.resolve()
    if cwd.resolve() not in [resolved, *resolved.parents]:
        raise ValueError(f"输出路径越界: {resolved}")
    return resolved


def validate_codex_job(job: dict[str, Any], allowed_roots: list[Path] | None = None) -> Path:
    """@brief 对 Codex 任务执行最小企业级校验。"""
    if job.get("executor") != "codex":
        raise ValueError("非 Codex 任务不能进入 Codex Runtime")
    if job.get("kind") not in {"codex_task", "create_shell", "import_model", "delivery_package"}:
        raise ValueError(f"未知 Codex 任务类型: {job.get('kind')}")
    prompt = str(job.get("prompt") or "")
    objective = str(job.get("objective") or "")
    if len(prompt) > 24000:
        raise ValueError("prompt 过长，请拆分任务")
    if not prompt and not objective:
        raise ValueError("Codex 任务缺少 prompt 或 objective")
    return resolve_workspace(job, allowed_roots=allowed_roots)
