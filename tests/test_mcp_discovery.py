"""发现模式、统一策略与人工审批的回归；不调用真实 SolidWorks。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp-server" / "server.py"
sys.path.insert(0, str(ROOT / "mcp-server"))

import policy  # noqa: E402
from approval import ApprovalError, ApprovalLedger  # noqa: E402
from gate import DISCOVERY_TOOLS, ToolGate  # noqa: E402


def _fake_manager():
    server = FastMCP("gate-fixture")

    @server.tool(name="solidworks_save_document")
    def save(params: dict) -> str:
        """保存文档。"""
        return '{"status":"ok","tool":"save"}'

    server.add_tool(save, name="solidworks_create_basic_part")
    server.add_tool(save, name="solidworks_close_documents")

    @server.tool(name="solidworks_mass_properties")
    def mass() -> str:
        """读取质量属性。"""
        return '{"mass":1.0}'

    @server.tool(name="solidworks_review_active", structured_output=False)
    def review():
        """返回图文混合结果。"""
        return [
            TextContent(type="text", text="review report"),
            ImageContent(type="image", data=base64.b64encode(b"png").decode(), mimeType="image/png"),
        ]

    return server._tool_manager


def _gate(tmp_path: Path, mode: str = "search", approval: str = "server") -> ToolGate:
    return ToolGate(_fake_manager(), mode=mode, approval_mode=approval,
                    ledger=ApprovalLedger(tmp_path / "approvals"))


def _save(gate: ToolGate, path: str = "D:/work/part.SLDPRT", **extra):
    arguments = {"params": {"path": path, **extra}}
    return asyncio.run(gate.call_tool("solidworks_create_basic_part", arguments))


def test_policy_covers_every_registered_tool():
    """新增工具若没登记副作用，必须在这里失败，而不是发布后默认放行。"""
    import server

    registered = set(server._gate._tools) - set(DISCOVERY_TOOLS)
    assert registered == set(policy.registered_names())


def test_read_tool_runs_without_approval(tmp_path):
    gate = _gate(tmp_path)
    result = asyncio.run(gate.call_tool("solidworks_mass_properties", {}))
    assert json.loads(result)["mass"] == 1.0


def test_health_check_start_request_is_not_classified_as_read_only():
    assert policy.classify("solidworks_health_check", {"params": {}})[0] is policy.Effect.READ
    assert policy.classify("solidworks_health_check", {"params": {"start_solidworks": True}})[0] is policy.Effect.WRITE
    assert policy.classify("solidworks_connect")[0] is policy.Effect.WRITE


def test_api_lookup_accurately_classifies_optional_installation():
    assert policy.classify("solidworks_lookup_api")[0] is policy.Effect.WRITE
    assert policy.classify("solidworks_lookup_api", {"params": {"offline": True}})[0] is policy.Effect.READ
    assert policy.classify("solidworks_lookup_api", {"params": {"auto_install": False}})[0] is policy.Effect.READ
    assert policy.classify("solidworks_lookup_api", {"params": {"auto_install": "false"}})[0] is policy.Effect.WRITE


def test_api_lookup_input_requires_exactly_one_request_form():
    import server
    from pydantic import ValidationError
    assert server.SolidWorksApiLookupInput(task="画圆").task == "画圆"
    assert server.SolidWorksApiLookupInput(interface="ISketchManager", member="CreateCircleByRadius").member
    for value in ({}, {"interface": "ISketchManager"}, {"task": "画圆", "interface": "ITest", "member": "Method"}):
        with pytest.raises(ValidationError):
            server.SolidWorksApiLookupInput(**value)


def test_connect_forwards_optional_target_version(monkeypatch):
    import server
    calls = []
    class Sw:
        GetProcessID = 123
        RevisionNumber = "34.1.1"
    monkeypatch.setattr(server, "connect_solidworks", lambda **kwargs: (calls.append(kwargs) or Sw(), None), raising=False)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.setattr(server, "_run_locked", lambda op, fmt: json.dumps(op()))
    result = json.loads(server.solidworks_connect(server.SolidWorksConnectInput(version=2026)))
    assert calls[0]["version"] == 2026 and result["year"] == 2026 and result["process_id"] == 123
    server.solidworks_connect(server.SolidWorksConnectInput())
    assert "version" not in calls[1]


def test_api_lookup_propagates_cancellation_to_worker(monkeypatch):
    import server
    import scripts.sw_api_lookup as api
    started, stopped = threading.Event(), threading.Event()
    def lookup(*args, cancelled, **kwargs):
        started.set()
        while not cancelled():
            time.sleep(0.01)
        stopped.set()
        raise api.LookupCancelled("cancelled")
    monkeypatch.setattr(api, "lookup_api", lookup)
    async def run():
        task = asyncio.create_task(server.solidworks_lookup_api(
            server.SolidWorksApiLookupInput(interface="ISketchManager", member="CreateCircleByRadius")))
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(stopped.wait, 2)
    asyncio.run(run())


def test_health_check_with_start_requires_approval(tmp_path):
    called = []
    server = FastMCP("health-fixture")

    def health(params: dict) -> str:
        called.append(params)
        return "ok"

    server.add_tool(health, name="solidworks_health_check")
    gate = ToolGate(server._tool_manager, approval_mode="server", ledger=ApprovalLedger(tmp_path / "ledger"))
    with pytest.raises(ToolError, match="需要人工批准"):
        asyncio.run(gate.call_tool("solidworks_health_check", {"params": {"start_solidworks": True}}))
    assert called == []


@pytest.mark.parametrize("name", [
    "cadstudio_check_dfm", "cadstudio_check_drc", "cadstudio_check_routing",
    "cadstudio_review_advanced_geometry", "solidworks_inspect_drawing",
])
def test_report_writing_tools_require_approval(tmp_path, name):
    invoked = []
    server = FastMCP("report-fixture")

    def write_report() -> str:
        invoked.append(True)
        return "unexpected"

    server.add_tool(write_report, name=name)
    gate = ToolGate(server._tool_manager, approval_mode="server", ledger=ApprovalLedger(tmp_path / "ledger"))
    assert policy.classify(name)[0] is policy.Effect.WRITE
    with pytest.raises(ToolError):
        asyncio.run(gate.call_tool(name, {}))
    assert not invoked


def test_write_tool_is_blocked_until_human_approves(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ToolError) as blocked:
        _save(gate)
    message = str(blocked.value)
    assert "需要人工批准" in message
    pending = gate.ledger.pending()
    assert len(pending) == 1 and pending[0]["tool"] == "solidworks_create_basic_part"

    gate.ledger.approve(pending[0]["id"])
    assert json.loads(_save(gate))["tool"] == "save"

    # 一次性批准用完即失效，第二次调用重新进入待批准。
    with pytest.raises(ToolError):
        _save(gate)
    assert len(gate.ledger.pending()) == 1


def test_changed_arguments_do_not_reuse_approval(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ToolError):
        _save(gate, "D:/work/a.SLDPRT")
    gate.ledger.approve(gate.ledger.pending()[0]["id"])

    with pytest.raises(ToolError) as blocked:
        _save(gate, "D:/work/b.SLDPRT")
    assert "需要人工批准" in str(blocked.value)
    grants = [json.loads(path.read_text(encoding="utf-8"))
              for path in (tmp_path / "approvals" / "grants").glob("*.json")]
    assert grants and all(grant["used"] == 0 for grant in grants)  # 原批准没有被这次调用消耗


def test_model_supplied_approved_flag_is_ignored(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ToolError):
        _save(gate, "D:/work/a.SLDPRT", approved=True)
    assert len(gate.ledger.pending()) == 1


def test_approval_rejects_malformed_request_id(tmp_path):
    """请求 ID 只能来自账本；带路径分隔符的输入不能读到账本外的文件。"""
    gate = _gate(tmp_path)
    with pytest.raises(ToolError):
        _save(gate)
    with pytest.raises(ApprovalError):
        gate.ledger.approve("../../secret")
    with pytest.raises(ApprovalError):
        gate.ledger.request_record("not-a-request")


def test_scope_grants_are_disabled_until_targets_can_be_verified(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ApprovalError, match="范围授权已停用"):
        gate.ledger.grant_scope(["solidworks_save_document"], ["D:/work"], ttl_seconds=600)
    with pytest.raises(ToolError):
        _save(gate, "D:/work/sub/part.SLDPRT")


def test_client_approval_mode_keeps_legacy_behaviour(tmp_path):
    """完整模式默认沿用客户端逐工具审批，服务端不额外拦截。"""
    gate = _gate(tmp_path, mode="full", approval="client")
    assert json.loads(_save(gate))["tool"] == "save"


def test_full_mode_can_enforce_server_approval(tmp_path):
    """选择 server 审批时，完整模式的直调同样先走策略与账本。"""
    gate = _gate(tmp_path, mode="full", approval="server")
    with pytest.raises(ToolError):
        _save(gate)
    gate.ledger.approve(gate.ledger.pending()[0]["id"])
    assert json.loads(_save(gate))["tool"] == "save"


def test_active_document_write_fails_closed_without_document_binding(tmp_path):
    gate = _gate(tmp_path, approval="server")
    with pytest.raises(ToolError, match="需要 document_target"):
        asyncio.run(gate.call_tool("solidworks_save_document", {"params": {"path": "D:/work/a.SLDPRT"}}))
    assert gate.ledger.pending() == []


def test_discovery_reports_active_document_binding_requirement(tmp_path):
    gate = _gate(tmp_path, approval="server")
    detail = gate.describe("solidworks_save_document")
    assert detail["available"] is True
    assert detail["document_target_required"] is True
    result = gate.search("solidworks_save_document", limit=1)
    assert result[0]["name"] == "solidworks_save_document"
    assert result[0]["available"] is True


def test_discovery_reports_unsupported_document_operation(tmp_path):
    gate = _gate(tmp_path, approval="server")
    detail = gate.describe("solidworks_close_documents")
    assert detail["available"] is False
    assert "无法绑定并复核文档身份" in detail["blocked_reason"]
    with pytest.raises(ToolError, match="无法绑定并复核文档身份"):
        asyncio.run(gate.call_tool("solidworks_close_documents", {"params": {}}))


def test_off_mode_is_the_explicit_opt_out(tmp_path):
    assert json.loads(_save(_gate(tmp_path, approval="off")))["tool"] == "save"


def test_auto_mode_matches_documented_defaults(tmp_path):
    """search 默认依赖客户端的任务授权；full 沿用客户端审批。"""
    ledger = ApprovalLedger(tmp_path / "approvals")
    assert ToolGate(_fake_manager(), ledger=ledger).approval_mode == "task"
    assert ToolGate(_fake_manager(), mode="full", ledger=ledger).approval_mode == "client"


def test_task_approval_mode_does_not_require_per_tool_confirmation(tmp_path):
    gate = _gate(tmp_path, approval="task")
    arguments = {"params": {"path": "D:/work/a.SLDPRT"}}
    result = asyncio.run(gate.call_tool("solidworks_save_document", arguments))
    assert json.loads(result)["tool"] == "save"
    assert gate.ledger.pending() == []
    detail = gate.describe("solidworks_save_document")
    assert detail["available"] is True
    assert detail["approval_required"] is False
    assert detail["approval_mode"] == "task"


class _ElicitContext:
    """模拟支持/不支持 elicitation 的客户端。"""

    def __init__(self, supported: bool = True, action: str = "accept", approve: bool = True):
        self.session = self
        self.supported = supported
        self.action = action
        self.approve = approve
        self.prompts: list[str] = []

    def check_client_capability(self, capabilities):
        return self.supported

    async def elicit(self, message, schema):
        from types import SimpleNamespace

        self.prompts.append(message)
        data = SimpleNamespace(approve=self.approve) if self.action == "accept" else None
        return SimpleNamespace(action=self.action, data=data)


def test_approval_is_not_shared_between_mcp_sessions(tmp_path):
    gate = _gate(tmp_path, approval="server")
    first, second = _ElicitContext(), _ElicitContext()
    arguments = {"params": {"path": "D:/work/a.SLDPRT"}}
    with pytest.raises(ToolError):
        asyncio.run(gate.call_tool("solidworks_create_basic_part", arguments, context=first))
    request = gate.ledger.pending()[0]
    gate.ledger.approve(request["id"])
    with pytest.raises(ToolError):
        asyncio.run(gate.call_tool("solidworks_create_basic_part", arguments, context=second))
    result = asyncio.run(gate.call_tool("solidworks_create_basic_part", arguments, context=first))
    assert json.loads(result)["tool"] == "save"


def test_elicit_mode_denies_when_client_unsupported_or_declines(tmp_path):
    unsupported = _ElicitContext(supported=False)
    with pytest.raises(ToolError):
        asyncio.run(_gate(tmp_path, approval="elicit").call_tool(
            "solidworks_create_basic_part", {"params": {"path": "D:/work/a.SLDPRT"}}, context=unsupported))
    assert unsupported.prompts == []

    declining = _ElicitContext(action="decline")
    with pytest.raises(ToolError):
        asyncio.run(_gate(tmp_path, approval="elicit").call_tool(
            "solidworks_create_basic_part", {"params": {"path": "D:/work/a.SLDPRT"}}, context=declining))
    assert declining.prompts


def test_elicit_mode_allows_only_on_explicit_approval(tmp_path):
    accepted = _ElicitContext()
    result = asyncio.run(_gate(tmp_path, approval="elicit").call_tool(
        "solidworks_create_basic_part", {"params": {"path": "D:/work/a.SLDPRT"}}, context=accepted))
    assert json.loads(result)["tool"] == "save"
    assert 'D:/work/a.SLDPRT' in accepted.prompts[0]


def test_elicit_refuses_to_approve_truncated_parameters(tmp_path):
    client = _ElicitContext()
    gate = _gate(tmp_path, approval="elicit")
    arguments = {"params": {"path": "D:/work/a.SLDPRT", "details": "x" * 5000}}
    with pytest.raises(ToolError):
        asyncio.run(gate.call_tool("solidworks_create_basic_part", arguments, context=client))
    assert client.prompts == []
    assert len(gate.ledger.pending()) == 1


def test_result_passthrough_keeps_images(tmp_path):
    gate = _gate(tmp_path, mode="full", approval="client")
    blocks = asyncio.run(gate.call_tool("solidworks_review_active", {}, convert_result=True))
    assert isinstance(blocks[0], TextContent)
    assert isinstance(blocks[1], ImageContent)


def test_unknown_tool_is_denied(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ToolError) as blocked:
        asyncio.run(gate.call_tool("not_a_real_tool", {}))
    assert "未登记" in str(blocked.value)


def test_search_mode_rejects_inapplicable_client_approval(tmp_path):
    with pytest.raises(ValueError, match="发现模式不能使用 client"):
        _gate(tmp_path, mode="search", approval="client")


def test_discovery_entries_cannot_recurse():
    import server

    with pytest.raises(ToolError) as blocked:
        asyncio.run(server.sw_call_tool("sw_call_tool", {}))
    assert "不能调用发现入口自身" in str(blocked.value)


def test_full_mode_hides_discovery_entries_and_search_mode_hides_tools(tmp_path):
    import server

    search_gate = ToolGate(server._gate._manager, mode="search", approval_mode="server",
                           ledger=ApprovalLedger(tmp_path / "a"))
    assert {tool.name for tool in search_gate.list_tools()} == set(DISCOVERY_TOOLS)

    full_gate = ToolGate(server._gate._manager, mode="full", approval_mode="client",
                         ledger=ApprovalLedger(tmp_path / "b"))
    names = {tool.name for tool in full_gate.list_tools()}
    assert names.isdisjoint(DISCOVERY_TOOLS)
    assert len(names) == 69


def test_describe_preserves_original_input_and_output_schema(tmp_path):
    import server

    gate = ToolGate(server._gate._manager, mode="search", approval_mode="server",
                    ledger=ApprovalLedger(tmp_path / "ledger"))
    original = gate.get_tool("solidworks_health_check")
    described = gate.describe(original.name)
    assert described["inputSchema"] == original.parameters
    assert original.output_schema is not None
    assert described["outputSchema"] == original.output_schema


def _stdio_env(tmp_path: Path, mode: str) -> dict[str, str]:
    return {
        **os.environ,
        "SW_MCP_DISCOVERY": mode,
        "SW_MCP_APPROVAL": "server",
        "SW_MCP_APPROVAL_DIR": str(tmp_path / "approvals"),
    }


async def _with_session(env: dict[str, str], handler):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await handler(session)


def test_stdio_search_mode_exposes_three_entries_and_blocks_writes(tmp_path):
    async def handler(session):
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == set(DISCOVERY_TOOLS)

        found = await session.call_tool("sw_search_tools", {"query": "检查装配体有没有干涉"})
        payload = json.loads(found.content[0].text)
        assert payload["results"][0]["name"] == "solidworks_interference_check"

        await session.call_tool("sw_describe_tool", {"name": "solidworks_save_document"})

        blocked = await session.call_tool(
            "sw_call_tool",
            {"name": "solidworks_create_basic_part", "arguments": {"params": {"path": "D:/work/a.SLDPRT"}}},
        )
        assert blocked.isError is True
        assert "需要人工批准" in blocked.content[0].text

    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_design_audit_is_discoverable_and_respects_approval(tmp_path):
    """通过真实网关发现 DRC；严格模式禁止未经批准的报告写入。"""
    source = tmp_path / "part.json"
    source.write_text(json.dumps({"documentId": "demo", "units": "mm", "features": []}), encoding="utf-8")
    output = tmp_path / "report.json"

    async def handler(session):
        found = await session.call_tool("sw_search_tools", {"query": "设计规则审计 DRC"})
        names = [item["name"] for item in json.loads(found.content[0].text)["results"]]
        assert "cadstudio_check_drc" in names
        listed = await session.call_tool("sw_call_tool", {"name": "cadstudio_list_drc_rules", "arguments": {}})
        assert not listed.isError
        assert json.loads(listed.content[0].text)["rulePacks"]
        result = await session.call_tool("sw_call_tool", {"name": "cadstudio_check_drc", "arguments": {"params": {
            "input_path": str(source), "output_path": str(output)
        }}})
        assert result.isError and "需要人工批准" in result.content[0].text
        assert not output.exists()

    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_design_audit_creates_versioned_reports_in_task_mode(tmp_path):
    source = tmp_path / "part.json"
    source.write_text(json.dumps({"documentId": "demo", "units": "mm", "features": []}), encoding="utf-8")
    output = tmp_path / "report.json"
    output.write_text("existing", encoding="utf-8")

    async def handler(session):
        result = await session.call_tool("sw_call_tool", {"name": "cadstudio_check_drc", "arguments": {"params": {
            "input_path": str(source), "output_path": str(output), "rule_packs": ["machined_bracket"]
        }}})
        assert not result.isError
        report = json.loads(result.content[0].text)
        assert report["status"] == "review_required"
        assert output.read_text(encoding="utf-8") == "existing"
        assert Path(report["reportPath"]).is_file()

    asyncio.run(_with_session({**_stdio_env(tmp_path, "search"), "SW_MCP_APPROVAL": "task"}, handler))


def test_stdio_versioned_api_lookup_is_discoverable_and_offline(tmp_path):
    """从真实 stdio 网关检索、描述并调用版本化 API 查证，不依赖 CAD 安装。"""
    async def handler(session):
        result = await session.call_tool("sw_search_tools", {"query": "查证 SolidWorks API 接口签名"})
        assert not result.isError
        assert "solidworks_lookup_api" in [item["name"] for item in json.loads(result.content[0].text)["results"]]
        detail = await session.call_tool("sw_describe_tool", {"name": "solidworks_lookup_api"})
        assert not detail.isError and json.loads(detail.content[0].text)["inputSchema"]
        called = await session.call_tool("sw_call_tool", {
            "name": "solidworks_lookup_api",
            "arguments": {"params": {"interface": "ISketchManager", "member": "CreateCircleByRadius",
                                      "version": 2024, "offline": True}},
        })
        assert not called.isError
        value = json.loads(called.content[0].text)
        assert value["interface"] == "ISketchManager" and value["official"] is None
        assert value["runtime_verified"] is False
    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_natural_language_api_lookup_offline(tmp_path):
    async def handler(session):
        called = await session.call_tool("sw_call_tool", {
            "name": "solidworks_lookup_api", "arguments": {"params": {
                "task": "SolidWorks 2026 画圆并拉伸", "offline": True}},
        })
        assert not called.isError
        result = json.loads(called.content[0].text)
        assert result["status"] == "candidates"
        assert [(item["interface"], item["member"]) for item in result["results"]] == [
            ("ISketchManager", "CreateCircleByRadius"), ("IFeatureManager", "FeatureExtrusion3")]
    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_auto_install_respects_explicit_server_approval_mode(tmp_path):
    async def handler(session):
        called = await session.call_tool("sw_call_tool", {
            "name": "solidworks_lookup_api", "arguments": {"params": {
                "task": "SolidWorks 2026 画圆", "auto_install": True}},
        })
        assert called.isError
        assert "需要人工批准" in called.content[0].text
    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_auto_install_uses_default_task_authorization(tmp_path):
    async def handler(session):
        called = await session.call_tool("sw_call_tool", {
            "name": "solidworks_lookup_api", "arguments": {"params": {
                "task": "没有可识别的建模操作", "auto_install": True}},
        })
        assert not called.isError
        assert json.loads(called.content[0].text)["status"] == "no_candidate"
    config = _stdio_env(tmp_path, "search")
    config["SW_MCP_APPROVAL"] = "auto"
    asyncio.run(_with_session(config, handler))


def test_stdio_hidden_tools_are_still_checked_when_called_by_name(tmp_path):
    """隐藏只影响列表；客户端点名调用被隐藏的工具也必须经过策略与审批。"""
    async def handler(session):
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == set(DISCOVERY_TOOLS)

        read = await session.call_tool("solidworks_health_check", {})
        assert read.isError is not True
        health = json.loads(read.content[0].text)
        # CI 没有安装 SolidWorks 时健康检查应返回 warning，而不是协议错误。
        assert isinstance(health["checks"]["solidworks_detected"], bool)
        assert isinstance(health["issues"], list)
        assert health["status"] == ("warning" if health["issues"] else "ok")

        blocked = await session.call_tool(
            "solidworks_create_basic_part",
            {"params": {"path": "D:/work/bypass-attempt.SLDPRT"}},
        )
        assert blocked.isError is True
        assert "需要人工批准" in blocked.content[0].text

    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_approval_can_be_consumed_only_in_the_same_session(tmp_path):
    async def handler(session):
        args = {"name": "cadstudio_check_dfm", "arguments": {"params": {}}}
        blocked = await session.call_tool("sw_call_tool", args)
        assert blocked.isError and "需要人工批准" in blocked.content[0].text
        ledger = ApprovalLedger(tmp_path / "approvals")
        request = ledger.pending()[0]
        ledger.approve(request["id"], expected_record=request)
        # 缺少必填参数，授权后仍会由原工具校验拒绝，不执行任何文件或 CAD 写操作。
        result = await session.call_tool("sw_call_tool", args)
        assert result.isError and "需要人工批准" not in result.content[0].text

    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_active_document_writes_are_blocked_in_both_call_paths(tmp_path):
    async def handler(session):
        direct = await session.call_tool("solidworks_save_document", {"params": {}})
        wrapped = await session.call_tool("sw_call_tool", {
            "name": "solidworks_save_document", "arguments": {"params": {}}
        })
        for result in (direct, wrapped):
            assert result.isError
            assert "需要 document_target" in result.content[0].text

    asyncio.run(_with_session(_stdio_env(tmp_path, "search"), handler))


def test_stdio_full_mode_keeps_legacy_surface(tmp_path):
    async def handler(session):
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert len(names) == 69
        assert names.isdisjoint(DISCOVERY_TOOLS)
        assert "solidworks_save_document" in names

    asyncio.run(_with_session(_stdio_env(tmp_path, "full"), handler))


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sw_mcp_approve.py"), "--dir", str(tmp_path / "approvals"), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), stdin=subprocess.DEVNULL,
    )


def test_cli_lists_pending_and_refuses_non_interactive_approval(tmp_path):
    gate = _gate(tmp_path)
    with pytest.raises(ToolError):
        _save(gate)
    request_id = gate.ledger.pending()[0]["id"]

    listed = _cli(tmp_path, "list")
    assert listed.returncode == 0, listed.stderr
    assert request_id in listed.stdout

    refused = _cli(tmp_path, "approve", request_id)
    assert refused.returncode == 1
    assert "拒绝" in refused.stderr
    assert len(gate.ledger.pending()) == 1  # 没有产生任何批准记录
    assert not list((tmp_path / "approvals" / "grants").glob("*.json"))
