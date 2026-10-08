"""@brief 实际 HTTP MCP 握手、身份与资源取回；不调用 CAD 写工具。"""
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))
from artifact_access import ArtifactAccess


def test_http_host_auth_image_and_binary_resource_roundtrip(tmp_path):
    """@brief 明确允许的远端 Host 可以访问，未授权/错误 Origin 无法访问。"""
    output = tmp_path / "output"
    output.mkdir()
    source = output / "preview.bmp"
    Image.new("RGB", (16, 16), color=(0, 80, 160)).save(source)
    step = output / "fixture.step"
    step.write_bytes(b"ISO-10303-21;fixture;END-ISO-10303-21;")
    queue = tmp_path / "queue"
    refs = ArtifactAccess(output, queue).publish({"outputs": [str(source), str(step)]})
    token = uuid4().hex
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "SW_MCP_TOKEN": token, "SW_MCP_OUTPUT_ROOT": str(output), "SW_MCP_QUEUE_DIR": str(queue)}
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(ROOT / "mcp-server/server.py"), "--transport", "streamable-http",
            "--host", "127.0.0.1", "--port", str(port), "--allow-host", "cad.example:*"], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            url = f"http://127.0.0.1:{port}/mcp"
            headers = {"Accept": "application/json, text/event-stream", "Host": f"cad.example:{port}", "Authorization": "Bearer " + token}
            message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25",
                "capabilities": {}, "clientInfo": {"name": "contract-test", "version": "1"}}}
            for _ in range(100):
                try:
                    response = httpx.post(url, json=message, headers=headers, trust_env=False, timeout=2)
                    break
                except httpx.ConnectError:
                    if process.poll() is not None:
                        raise AssertionError((tmp_path / "server.log").read_text())
                    time.sleep(.1)
            else:
                raise AssertionError("HTTP MCP 启动超时")
            assert response.status_code == 200
            denied = {**headers, "Authorization": "Bearer wrong"}
            assert httpx.post(url, json=message, headers=denied, trust_env=False).status_code == 401
            invalid_host = {**headers, "Host": "untrusted.example"}
            assert httpx.post(url, json=message, headers=invalid_host, trust_env=False).status_code in {403, 421}
            invalid_origin = {**headers, "Origin": "http://untrusted.example"}
            assert httpx.post(url, json=message, headers=invalid_origin, trust_env=False).status_code == 403

            async def roundtrip():
                async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True, trust_env=False) as client:
                    async with streamable_http_client(url, http_client=client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            assert "solidworks_create_basic_part" in {item.name for item in tools.tools}
                            preview = await session.call_tool("cadstudio_read_artifact", {"params": {"artifact_id": refs[0]["artifact_id"]}})
                            picture = next(item for item in preview.content if item.type == "image")
                            assert picture.mimeType == "image/png"
                            assert Image.open(io.BytesIO(base64.b64decode(picture.data))).size == (16, 16)
                            resource = await session.read_resource(refs[1]["uri"])
                            restored = base64.b64decode(resource.contents[0].blob)
                            assert hashlib.sha256(restored).hexdigest() == refs[1]["sha256"]
            asyncio.run(roundtrip())
        finally:
            process.terminate()
            process.wait(timeout=10)
