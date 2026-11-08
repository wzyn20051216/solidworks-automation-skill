"""@brief CAD Studio çoklu Agent Provider protokolü regresyon testi."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from apps.desktop.cad_workbench.agent_providers import AgentProvider, build_provider_command, parse_provider_result, resolve_provider
from apps.desktop.cad_workbench.engineering_orchestrator import build_engineering_plan
from apps.desktop.cad_workbench.queue_worker import record_provider_verification, run_agent_job


def test_codex_prefers_npm_node_entry_over_windowsapps_alias(tmp_path: Path, monkeypatch) -> None:
    """@brief Worker'ın bulunabilen ama çalıştırılamayan WindowsApps Codex takma adına çarpmasını önler."""
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
    """@brief Dört Provider türü de etkileşimsiz komut kullanmalı ve birleşik çalışma alanını korumalıdır."""
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
    """@brief Provider sarmalayıcı JSON/JSONL birleşik sonuç nesnesine normalleştirilmelidir."""
    provider = AgentProvider(provider_id, provider_id, f"{provider_id}-v1", False, True, (provider_id,))
    output = tmp_path / "result.json"

    parsed = parse_provider_result(provider, stdout, output)

    assert parsed == RESULT
    assert json.loads(output.read_text(encoding="utf-8")) == RESULT


def test_claude_verification_aliases_normalize_to_reviewer_contract(tmp_path: Path) -> None:
    """@brief Claude'un yaygın type/detail çıktısı Reviewer Gate'e girmeden önce normalleştirilmelidir."""
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
    """@brief executor=agent iken Codex komutuna geri dönülmemelidir."""
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
    """@brief Gerçek başarı kaydı yalnızca protokol ve zamanı saklar; kimlik bilgisi veya ham çıktı saklamaz."""
    provider = AgentProvider("claude", "Claude Code", "claude-print-v1", True, True, ("claude",))

    path = record_provider_verification(tmp_path, provider)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["providers"]["claude"]["verified"] is True
    assert payload["providers"]["claude"]["protocol"] == "claude-print-v1"
    assert "token" not in json.dumps(payload).lower()


def test_complex_agent_job_injects_auditable_engineering_dag(tmp_path: Path, monkeypatch) -> None:
    """@brief Kapsamlı görev DAG kanıtı üretmelidir; basit Provider protokolü değişmeden kalır."""
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
    """@brief Konuşma düzeltmesi önceki DAG'ı geri yüklemeli; yerel isteği yepyeni basit görev saymamalıdır."""
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


def test_lmstudio_provider_resolves_to_python_bridge() -> None:
    """@brief LM Studio, harici CLI gerektirmeden Python API köprüsüyle çözülmelidir."""
    provider = resolve_provider("lmstudio")

    assert provider.id == "lmstudio"
    assert provider.name == "LM Studio"
    assert provider.protocol == "lmstudio-openai-v1"
    assert provider.command[1].endswith("lmstudio_client.py")


def test_lmstudio_command_targets_api_endpoint(tmp_path: Path, monkeypatch) -> None:
    """@brief LM Studio komutu şemayı, modeli ve yapılandırılan uç noktayı taşımalıdır."""
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:9999/v1")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    provider = resolve_provider("lmstudio")

    command = build_provider_command(provider, "görevi çalıştır", tmp_path, tmp_path / "result.json", schema, "workspace-write", model="qwen2.5-coder")

    assert command[:2] == list(provider.command)
    assert "--schema" in command and str(schema) in command
    assert "--base-url" in command and "http://127.0.0.1:9999/v1" in command
    assert "--model" in command and "qwen2.5-coder" in command
    assert command[-1] == "görevi çalıştır"


def test_lmstudio_output_normalizes_to_unified_result(tmp_path: Path) -> None:
    """@brief LM Studio stdout JSON'u birleşik sonuç nesnesine normalleştirilmelidir."""
    provider = AgentProvider("lmstudio", "LM Studio", "lmstudio-openai-v1", True, False, ("lmstudio",))
    output = tmp_path / "lmstudio-result.json"

    parsed = parse_provider_result(provider, json.dumps(RESULT, ensure_ascii=False), output)

    assert parsed == RESULT
    assert json.loads(output.read_text(encoding="utf-8")) == RESULT


def test_lmstudio_client_round_trip_against_local_endpoint(tmp_path: Path, monkeypatch, capsys) -> None:
    """@brief Köprü CLI, gerçek bir OpenAI uyumlu HTTP uç noktasıyla uçtan uca çalışmalıdır."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from apps.desktop.cad_workbench import lmstudio_client

    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            assert self.path == "/v1/models"
            self._send({"data": [{"id": "qwen2.5-coder"}]})

        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/v1/chat/completions"
            length = int(self.headers.get("Content-Length") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            self._send({"choices": [{"message": {"content": json.dumps(RESULT, ensure_ascii=False)}}]})

        def log_message(self, *args) -> None:  # noqa: ANN002
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        schema = tmp_path / "schema.json"
        schema.write_text(json.dumps({"type": "object"}), encoding="utf-8")
        monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)

        assert lmstudio_client.main(["--version", "--base-url", base_url]) == 0
        assert lmstudio_client.main(["--base-url", base_url, "--schema", str(schema), "görev istemi"]) == 0
    finally:
        server.shutdown()
        thread.join(timeout=5)

    stdout = capsys.readouterr().out
    assert "LM Studio API hazır" in stdout
    request = captured["request"]
    assert request["model"] == "qwen2.5-coder"
    assert request["messages"][-1] == {"role": "user", "content": "görev istemi"}
    assert request["response_format"]["type"] == "json_schema"
    assert json.loads(stdout.strip().splitlines()[-1]) == RESULT


def test_lmstudio_agent_job_uses_api_bridge(tmp_path: Path, monkeypatch) -> None:
    """@brief executor=agent + provider=lmstudio görevi birleşik protokolde tamamlanmalıdır."""
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path / "lmstudio-agent-result.json"
    monkeypatch.setattr("apps.desktop.cad_workbench.queue_worker.agent_output_path", lambda job, cwd: output)
    job = {
        "id": "agent-lmstudio-test",
        "kind": "agent_task",
        "executor": "agent",
        "cwd": str(repo),
        "prompt": "birleşik protokol testi",
        "objective": "LM Studio Provider doğrulaması",
        "uiConfig": {
            "agentRuntime": {
                "provider": "lmstudio",
                "providerName": "LM Studio",
                "protocol": "lmstudio-openai-v1",
            }
        },
    }
    calls: list[list[str]] = []

    def fake_runner(command, cwd, timeout_seconds):  # noqa: ANN001, ANN201
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(RESULT, ensure_ascii=False), stderr="")

    result = run_agent_job(job, runner=fake_runner, timeout_seconds=3)

    assert calls[0][0] == "lmstudio"
    assert result["mode"] == "agent"
    assert result["provider"]["id"] == "lmstudio"
    assert result["provider"]["protocol"] == "lmstudio-openai-v1"
    assert output.is_file()
