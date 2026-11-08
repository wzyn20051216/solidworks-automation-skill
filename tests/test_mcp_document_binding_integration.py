"""模拟审批与持锁执行：不启动或修改真实 SolidWorks。"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))
import server  # noqa: E402
from approval import ApprovalLedger  # noqa: E402
from gate import ToolGate  # noqa: E402
from document_identity import DocumentIdentity, bind_document  # noqa: E402


def _fixture(tmp_path, monkeypatch):
    selected = {"path": str(tmp_path / "approved.SLDPRT"), "pid": 314}
    changed = []

    class Document:
        def GetPathName(self):
            return selected["path"]

    class Application:
        ActiveDoc = Document()

        def GetProcessID(self):
            return selected["pid"]

    sw = Application()
    monkeypatch.setattr(server, "connect_solidworks", lambda **_: (sw, sw.ActiveDoc), raising=False)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name)(), raising=False)
    monkeypatch.setattr(server, "pythoncom", None)
    monkeypatch.setattr(server, "_artifact_access", lambda: type("Artifacts", (), {"publish": lambda self, _: []})())

    mcp = FastMCP("target-binding-fixture")

    @mcp.tool(name="solidworks_save_document")
    def save(params: dict) -> str:
        def op():
            _sw, model = server._active_model_required()
            changed.append(model.GetPathName())
            return {"status": "ok"}
        return server._run_locked(op, server.ResponseFormat.JSON, load_automation=False)

    gate = ToolGate(mcp._tool_manager, approval_mode="server", ledger=ApprovalLedger(tmp_path / "ledger"))
    target = {"process_id": selected["pid"], "path": selected["path"]}
    return gate, target, selected, changed


def _call(gate, target):
    return asyncio.run(gate.call_tool("solidworks_save_document", {"params": {}}, document_target=target))


def test_approval_and_locked_execution_are_bound_to_same_document(tmp_path, monkeypatch):
    gate, target, selected, changed = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ToolError, match="insan onayından"):
        _call(gate, target)
    request = gate.ledger.pending()[0]
    displayed = json.loads(request["summary"])
    assert displayed["document_target"]["process_id"] == 314
    assert Path(displayed["document_target"]["path"]) == Path(target["path"])
    gate.ledger.approve(request["id"], expected_record=request)

    # 用户在批准后切换了活动文档：执行前必须拒绝，不能调用写操作。
    selected["path"] = str(tmp_path / "other.SLDPRT")
    result = json.loads(_call(gate, target))
    assert result["status"] == "error"
    assert "Etkin belge" in result["message"]
    assert changed == []

    # 重新发起并批准后，仅目标文档一致的调用可以执行。
    selected["path"] = target["path"]
    with pytest.raises(ToolError, match="insan onayından"):
        _call(gate, target)
    request = gate.ledger.pending()[0]
    gate.ledger.approve(request["id"], expected_record=request)
    assert json.loads(_call(gate, target))["status"] == "ok"
    assert changed == [target["path"]]


def test_different_document_or_process_does_not_reuse_approval(tmp_path, monkeypatch):
    gate, target, _selected, changed = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ToolError):
        _call(gate, target)
    request = gate.ledger.pending()[0]
    gate.ledger.approve(request["id"], expected_record=request)
    for other in ({**target, "process_id": 315}, {**target, "path": str(tmp_path / "other.SLDPRT")}):
        with pytest.raises(ToolError, match="insan onayından"):
            _call(gate, other)
    assert changed == []


def test_closed_active_document_does_not_fall_back_to_stale_model(tmp_path, monkeypatch):
    stale_model = object()
    sw = type("Application", (), {"ActiveDoc": None})()
    monkeypatch.setattr(server, "connect_solidworks", lambda **_: (sw, stale_model), raising=False)
    identity = DocumentIdentity.create(314, str(tmp_path / "part.SLDPRT"))
    with bind_document(identity), pytest.raises(RuntimeError, match="No active SolidWorks document"):
        server._active_model_required()


def test_task_mode_honors_an_explicit_document_target_without_prompt(tmp_path, monkeypatch):
    strict_gate, target, selected, changed = _fixture(tmp_path, monkeypatch)
    gate = ToolGate(strict_gate._manager, approval_mode="task", ledger=strict_gate.ledger)
    selected["path"] = str(tmp_path / "other.SLDPRT")
    result = json.loads(_call(gate, target))
    assert result["status"] == "error"
    assert changed == []
    selected["path"] = target["path"]
    assert json.loads(_call(gate, target))["status"] == "ok"
    assert changed == [target["path"]]


def _fixture_stdio_server():
    """为协议集成测试替换内存工具，无真实 SolidWorks 或文件写操作。"""
    class Document:
        def GetPathName(self):
            return os.environ["TEST_DOCUMENT_PATH"]

    class Application:
        ActiveDoc = Document()

        def GetProcessID(self):
            return 314

    sw = Application()
    server.connect_solidworks = lambda **_: (sw, sw.ActiveDoc)
    server.get_com_member = lambda obj, name: getattr(obj, name)()
    server.pythoncom = None
    server._artifact_access = lambda: type("Artifacts", (), {"publish": lambda self, _: []})()
    for name in ("solidworks_save_document", "solidworks_create_basic_part", "solidworks_sketch_and_extrude"):
        server._gate.remove_tool(name)

    @server.mcp.tool(name="solidworks_create_basic_part")
    def create(params: dict) -> str:
        return json.dumps({"status": "ok", "step": "create"})

    @server.mcp.tool(name="solidworks_sketch_and_extrude")
    def extrude(params: dict) -> str:
        def op():
            server._active_model_required()
            return {"status": "ok", "step": "extrude"}
        return server._run_locked(op, server.ResponseFormat.JSON, load_automation=False)

    @server.mcp.tool(name="solidworks_save_document")
    def save(params: dict) -> str:
        def op():
            server._active_model_required()
            return {"status": "ok"}
        return server._run_locked(op, server.ResponseFormat.JSON, load_automation=False)

    server.mcp.run(transport="stdio")


def test_stdio_gateway_binds_approval_to_document_and_executes_mock(tmp_path):
    doc = str(tmp_path / "part.SLDPRT")
    ledger_dir = tmp_path / "ledger"
    env = {**os.environ, "SW_MCP_DISCOVERY": "search", "SW_MCP_APPROVAL": "server",
           "SW_MCP_APPROVAL_DIR": str(ledger_dir), "TEST_DOCUMENT_PATH": doc}
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()), "--fixture"],
                                   cwd=str(ROOT), env=env)

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                args = {"name": "solidworks_save_document", "arguments": {"params": {}},
                        "document_target": {"process_id": 314, "path": doc}}
                blocked = await session.call_tool("sw_call_tool", args)
                assert blocked.isError and "insan onayından" in blocked.content[0].text
                ledger = ApprovalLedger(ledger_dir)
                request = ledger.pending()[0]
                ledger.approve(request["id"], expected_record=request)
                result = await session.call_tool("sw_call_tool", args)
                assert not result.isError
                assert json.loads(result.content[0].text)["status"] == "ok"

    asyncio.run(run())


def test_stdio_default_task_mode_executes_without_per_tool_prompt(tmp_path):
    # 模拟未保存文档，验证创建、编辑、保存的多步任务不会要求 PID/路径或重复审批。
    doc = ""
    ledger_dir = tmp_path / "ledger"
    env = {**os.environ, "SW_MCP_DISCOVERY": "search", "SW_MCP_APPROVAL": "auto",
           "SW_MCP_APPROVAL_DIR": str(ledger_dir), "TEST_DOCUMENT_PATH": doc}
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()), "--fixture"],
                                   cwd=str(ROOT), env=env)

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for name in ("solidworks_create_basic_part", "solidworks_sketch_and_extrude", "solidworks_save_document"):
                    result = await session.call_tool("sw_call_tool", {
                        "name": name, "arguments": {"params": {}}
                    })
                    assert not result.isError
                    assert json.loads(result.content[0].text)["status"] == "ok"
                assert not ledger_dir.exists()

    asyncio.run(run())


if __name__ == "__main__" and "--fixture" in sys.argv:
    _fixture_stdio_server()
