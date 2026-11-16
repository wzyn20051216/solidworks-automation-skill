"""验证既有实例的可选ROT回退；默认只读，可显式创建并关闭专用未保存测试文档。"""
import argparse
import asyncio
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import sw_connect as connection
from scripts.sw_process import solidworks_processes

KEY = "SW_ATTACH_EXISTING_DISPATCH"


def snapshot(app):
    """读取文档清单、活动文档身份和可见性的内存快照。

    参数:
        app: 已核对身份的 SolidWorks 实例。
    返回:
        文档路径、标题、未保存标志及窗口状态组成的元组；不直接写入报告。
    """
    get = connection.get_com_member
    documents = tuple(sorted((str(get(doc, "GetPathName")), str(get(doc, "GetTitle")),
                              bool(get(doc, "GetSaveFlag")))
                             for doc in (get(app, "GetDocuments") or [])))
    active = get(app, "ActiveDoc")
    identity = None if active is None else (str(get(active, "GetPathName")),
                                            str(get(active, "GetTitle")))
    return documents, identity, bool(get(app, "Visible"))


def direct_case(app, version, enabled, force_rot_failure):
    """验证一次直接 API 连接及其进程归属。

    参数:
        app: 用于核对目标 PID 的既有实例。
        version: 目标 SolidWorks 年份。
        enabled: 是否临时启用附着回退。
        force_rot_failure: 是否仅对 ROT 查询注入受控失败。
    返回:
        连接结果和真实 Dispatch 次数的脱敏证据字典。
    """
    original = connection.win32com_client
    dispatches = []
    pid = int(connection.get_com_member(app, "GetProcessID"))

    def get_active(prog_id):
        if force_rot_failure:
            raise RuntimeError("controlled ROT lookup failure")
        return original.GetActiveObject(prog_id)

    def dispatch(prog_id):
        dispatches.append(prog_id)
        return original.Dispatch(prog_id)

    with patch.dict(os.environ):
        os.environ.pop(KEY, None)
        if enabled:
            os.environ[KEY] = "1"
        with patch.object(connection, "win32com_client", SimpleNamespace(
                GetActiveObject=get_active, Dispatch=dispatch)), redirect_stdout(io.StringIO()):
            try:
                actual, _, metadata = connection.connect_solidworks(
                    version=version, wait_seconds=0, visible=bool(app.Visible),
                    return_metadata=True)
            except connection.SolidWorksConnectionError as error:
                assert not enabled and error.code == "SW_INSTANCE_NOT_READY"
                assert not dispatches
                return {"enabled": enabled, "controlled_rot_failure": force_rot_failure,
                        "status": "blocked", "code": error.code, "real_dispatch_count": 0}
    assert int(connection.get_com_member(actual, "GetProcessID")) == pid
    assert metadata["started_by_cad_studio"] is False
    assert metadata["actual_version"] == version
    if force_rot_failure:
        assert enabled and len(dispatches) == 1
    return {"enabled": enabled, "controlled_rot_failure": force_rot_failure,
            "status": "connected", "same_process": True,
            "claims_exit_ownership": False, "real_dispatch_count": len(dispatches)}


async def mcp_case(version, enabled, expected_pid, visible):
    """启动独立 MCP stdio 服务并验证真实连接。

    参数:
        version: 目标 SolidWorks 年份。
        enabled: 是否在服务进程环境中启用回退。
        expected_pid: 预期连接的既有实例 PID，仅用于内存核对。
        visible: 预期保留的窗口可见状态。
    返回:
        连接结果的脱敏证据字典；退出客户端后仍需由调用者核对文档状态。
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "SW_MCP_DISCOVERY": "full"}
    env.pop(KEY, None)
    if enabled:
        env[KEY] = "1"
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "mcp-server/server.py")], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            schema = next(t.inputSchema for t in tools.tools if t.name == "solidworks_connect")
            assert "params" in schema["properties"]
            result = await session.call_tool("solidworks_connect", {"params": {
                "version": version, "wait_seconds": 0, "visible": visible}})
            payload = json.loads(next(c.text for c in result.content if c.type == "text"))
    if payload.get("status") == "ok":
        assert payload["process_id"] == expected_pid and payload["year"] == version
        return {"enabled": enabled, "status": "connected", "same_process": True}
    assert not enabled and "SW_INSTANCE_NOT_READY" in json.dumps(payload)
    return {"enabled": enabled, "status": "blocked", "code": "SW_INSTANCE_NOT_READY"}


def run(version, output, create_test_document=False):
    """执行可选 ROT 回退的原生 API 和 MCP 对照验证。

    参数:
        version: 唯一既有目标实例的年份。
        output: 尚不存在的报告输出目录。
        create_test_document: 是否在空会话创建专用未保存文档，成功后关闭且不保存。
    返回:
        脱敏原生报告；失败时不自动关闭未知或未保存文档。
    """
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = solidworks_processes()
    assert before is not None and len(before) == 1, "需唯一的既有SolidWorks实例"
    pid, year = next(iter(before.items()))
    assert year == version
    report = {"status": "failed", "source_sha256": hashlib.sha256(
        (ROOT / "scripts/sw_connect.py").read_bytes()).hexdigest(), "cases": []}
    # 构造器可能启动进程；确认返回身份后才读取文档，且不取得退出所有权。
    app = connection.win32com_client.Dispatch(connection._prog_id_for_version(version))
    assert int(connection.get_com_member(app, "GetProcessID")) == pid
    assert connection.get_sw_version(app)["year"] == version
    assert solidworks_processes() == before
    original = snapshot(app)
    scratch = None
    if create_test_document:
        assert not original[0], "创建专用未保存文档需要空白会话"
        scratch = connection.new_document(app, "part")
        scratch.SetSaveFlag()
        assert bool(connection.get_com_member(scratch, "GetSaveFlag"))
    initial = snapshot(app)
    report["environment"] = connection.get_sw_version(app)

    def unchanged():
        assert solidworks_processes() == before
        assert snapshot(app) == initial

    try:
        try:
            found = connection.win32com_client.GetActiveObject(
                connection._prog_id_for_version(version))
        except Exception:
            report["natural_rot_available"] = False
        else:
            assert int(connection.get_com_member(found, "GetProcessID")) == pid
            report["natural_rot_available"] = True
        for enabled in [False, True]:
            print("直接连接，回退开关=" + str(enabled), flush=True)
            row = direct_case(app, version, enabled, False)
            unchanged()
            report["cases"].append({"entry": "direct", **row})
        # 自然ROT可用时另行注入查询失败；Dispatch和CAD对象仍为真实调用。
        if all(r["status"] == "connected" for r in report["cases"]):
            for enabled in [False, True]:
                row = direct_case(app, version, enabled, True)
                unchanged()
                report["cases"].append({"entry": "direct", **row})
        for enabled in [False, True]:
            print("真实MCP连接，回退开关=" + str(enabled), flush=True)
            row = asyncio.run(mcp_case(version, enabled, pid, initial[2]))
            unchanged()
            report["cases"].append({"entry": "mcp_stdio", **row})
        assert any(r["enabled"] and r["status"] == "connected" for r in report["cases"])
        report["tested_document_count"] = len(initial[0])
        if scratch is not None:
            assert bool(connection.get_com_member(scratch, "GetSaveFlag"))
            report["unsaved_test_document_preserved"] = True
            app.CloseDoc(connection.get_com_member(scratch, "GetTitle"))
            assert snapshot(app) == original
            report["test_document_closed_without_saving"] = True
        report.update(status="passed", processes_unchanged=True, documents_unchanged=True,
                      active_document_unchanged=True, visibility_unchanged=True,
                      original_state_restored=snapshot(app) == original,
                      document_count=len(original[0]))
    finally:
        (output / "native-report.json").write_text(json.dumps(report, ensure_ascii=False,
            indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--create-test-document", action="store_true",
                        help="仅在空白会话创建专用未保存文档；验证后关闭，不保存")
    args = parser.parse_args()
    print(json.dumps(run(args.version, args.output, args.create_test_document),
                     ensure_ascii=False, indent=2))
