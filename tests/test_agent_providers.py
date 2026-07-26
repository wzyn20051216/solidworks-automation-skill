"""@brief CAD Studio 多 Agent Provider 协议回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from apps.desktop.cad_workbench.agent_providers import AgentProvider, build_provider_command, parse_provider_result, resolve_provider
from apps.desktop.cad_workbench.engineering_orchestrator import build_engineering_plan
from apps.desktop.cad_workbench.queue_worker import record_provider_verification, run_agent_job


def test_codex_prefers_npm_node_entry_over_windowsapps_alias(tmp_path: Path, monkeypatch) -> None:
    """@brief 防止 Worker 命中可发现但不可执行的 WindowsApps Codex 别名。"""
    appdata = tmp_path / "AppData" / "Roaming"
    script = appdata / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    node = appdata / "npm" / "node.exe"
    node.write_bytes(b"node")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("CODEX_BIN", raising=False)

    provider = resolve_provider("codex")

    assert provider.command == (str(node), str(script))


RESULT = {
    "summary": "完成",
    "changedFiles": [],
    "verification": [],
    "risks": [],
    "nextSteps": [],
}


@pytest.mark.parametrize(
    ("provider_id", "expected_tokens"),
    [
        ("codex", ["exec", "--output-schema"]),
        ("claude", ["-p", "--json-schema", "--permission-mode"]),
        ("gemini", ["-p", "--output-format", "auto_edit"]),
        ("opencode", ["run", "--format", "--dir"]),
    ],
)
def test_provider_commands_compile_unified_protocol(tmp_path: Path, provider_id: str, expected_tokens: list[str]) -> None:
    """@brief 四类 Provider 都必须使用非交互命令并保留统一工作区。"""
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    provider = AgentProvider(provider_id, provider_id, f"{provider_id}-v1", provider_id in {"codex", "claude"}, True, (provider_id,))

    command = build_provider_command(provider, "执行任务", tmp_path, tmp_path / "result.json", schema, "workspace-write")

    assert command[0] == provider_id
    assert all(token in command for token in expected_tokens)
    assert "执行任务" in command


@pytest.mark.parametrize(
    ("provider_id", "stdout"),
    [
        ("claude", json.dumps({"structured_output": RESULT}, ensure_ascii=False)),
        ("gemini", json.dumps({"response": json.dumps(RESULT, ensure_ascii=False)}, ensure_ascii=False)),
        (
            "opencode",
            "\n".join(
                [
                    json.dumps({"type": "step_start"}),
                    json.dumps({"type": "text", "part": {"text": json.dumps(RESULT, ensure_ascii=False)}}, ensure_ascii=False),
                ]
            ),
        ),
    ],
)
def test_provider_outputs_normalize_to_unified_result(tmp_path: Path, provider_id: str, stdout: str) -> None:
    """@brief Provider 包装 JSON/JSONL 必须归一化成统一结果对象。"""
    provider = AgentProvider(provider_id, provider_id, f"{provider_id}-v1", False, True, (provider_id,))
    output = tmp_path / "result.json"

    parsed = parse_provider_result(provider, stdout, output)

    assert parsed == RESULT
    assert json.loads(output.read_text(encoding="utf-8")) == RESULT


def test_claude_verification_aliases_normalize_to_reviewer_contract(tmp_path: Path) -> None:
    """@brief Claude 常见 type/detail 输出必须归一化后再进入 Reviewer Gate。"""
    provider = AgentProvider("claude", "Claude Code", "claude-print-v1", True, True, ("claude",))
    output = tmp_path / "claude-normalised.json"
    provider_result = {
        **RESULT,
        "verification": [{"type": "schema-check", "status": "success", "detail": "结构正确"}],
    }
    stdout = json.dumps({"result": json.dumps(provider_result, ensure_ascii=False)}, ensure_ascii=False)

    parsed = parse_provider_result(provider, stdout, output)

    assert parsed["verification"] == [{"command": "schema-check", "status": "passed", "note": "结构正确"}]


def test_claude_agent_job_uses_selected_provider(tmp_path: Path, monkeypatch) -> None:
    """@brief executor=agent 时不得回退到 Codex 命令。"""
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path / "agent-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.agent_output_path", lambda job, cwd: output)
    job = {
        "id": "agent-claude-test",
        "kind": "agent_task",
        "executor": "agent",
        "cwd": str(repo),
        "prompt": "执行统一协议测试",
        "objective": "验证 Claude Provider",
        "uiConfig": {
            "agentRuntime": {
                "provider": "claude",
                "providerName": "Claude Code",
                "protocol": "claude-print-v1",
            }
        },
    }
    calls: list[list[str]] = []

    def fake_runner(command, cwd, timeout_seconds):  # noqa: ANN001, ANN201
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"structured_output": RESULT}, ensure_ascii=False),
            stderr="",
        )

    result = run_agent_job(job, runner=fake_runner, timeout_seconds=3)

    assert calls[0][0] == "claude"
    assert result["mode"] == "agent"
    assert result["provider"]["id"] == "claude"
    assert output.is_file()


def test_live_provider_verification_is_persisted_without_secrets(tmp_path: Path) -> None:
    """@brief 真实成功记录只保存协议与时间，不保存凭证或原始输出。"""
    provider = AgentProvider("claude", "Claude Code", "claude-print-v1", True, True, ("claude",))

    path = record_provider_verification(tmp_path, provider)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["providers"]["claude"]["verified"] is True
    assert payload["providers"]["claude"]["protocol"] == "claude-print-v1"
    assert "token" not in json.dumps(payload).lower()


def test_complex_agent_job_injects_auditable_engineering_dag(tmp_path: Path, monkeypatch) -> None:
    """@brief 综合任务必须生成 DAG 证据，简单 Provider 协议仍保持不变。"""
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path / "complex-agent-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.agent_output_path", lambda job, cwd: output)
    job = {
        "id": "complex-agent-test",
        "kind": "agent_task",
        "executor": "agent",
        "cwd": str(repo),
        "objective": "设计四零件装配机构，含沉孔、倒角、旋转马达、GB/T 工程图并导出 STEP/PDF",
        "uiConfig": {
            "agentRuntime": {"provider": "claude", "providerName": "Claude Code", "protocol": "claude-print-v1"},
            "engineeringOrchestration": {"mode": "auto_dag"},
        },
    }

    def fake_runner(command, cwd, timeout_seconds):  # noqa: ANN001, ANN201
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"structured_output": RESULT}, ensure_ascii=False), stderr="")

    result = run_agent_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["engineeringPlan"]["project_type"] == "complex_mechanical_system"
    assert [phase["id"] for phase in result["engineeringPlan"]["phases"]][-2:] == ["export-delivery", "final-review"]
    assert Path(result["engineeringPlanPath"]).is_file()
    assert any(item["kind"] == "engineering_plan" for item in result["artifacts"])


def test_follow_up_agent_job_replans_previous_dag_locally(tmp_path: Path, monkeypatch) -> None:
    """@brief 对话追改必须恢复上一轮 DAG，而不是把局部要求当成全新简单任务。"""
    repo = Path(__file__).resolve().parents[1]
    queue = tmp_path / "queue"
    queue.mkdir()
    source_id = "job-source-plan"
    source_plan = build_engineering_plan("四零件装配体，含沉孔、旋转马达、GB/T 工程图并导出 STEP/PDF").to_dict()
    source_plan["phases"][0]["status"] = "completed"
    source_plan["phases"][1]["status"] = "completed"
    source_job = {
        "id": source_id,
        "result": {"engineeringPlan": source_plan},
    }
    (queue / f"{source_id}.json").write_text(json.dumps(source_job, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "follow-up-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.agent_output_path", lambda job, cwd: output)
    current_path = queue / "job-follow-up.json"
    job = {
        "id": "job-follow-up",
        "kind": "agent_task",
        "executor": "agent",
        "cwd": str(repo),
        "objective": "把沉孔直径改为 12 mm",
        "_runtime": {"jobPath": str(current_path)},
        "uiConfig": {
            "sourceJobId": source_id,
            "agentRuntime": {"provider": "claude", "providerName": "Claude Code", "protocol": "claude-print-v1"},
            "engineeringOrchestration": {"mode": "plan_guided_dag"},
        },
    }

    def fake_runner(command, cwd, timeout_seconds):  # noqa: ANN001, ANN201
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"structured_output": RESULT}, ensure_ascii=False), stderr="")

    result = run_agent_job(job, runner=fake_runner, timeout_seconds=3)

    assert result["engineeringPlan"]["revision"] == 2
    assert result["engineeringPlan"]["change_request"] == "把沉孔直径改为 12 mm"
    assert result["engineeringPlan"]["phases"][0]["status"] == "completed"
    assert result["engineeringPlan"]["phases"][1]["status"] == "completed"
    assert result["engineeringPlan"]["phases"][2]["status"] == "planned"
