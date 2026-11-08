"""Yerel yardım, kalıcı önbellek, yedek ayrıştırma ve anonim Parallel kanıt sınırlarını doğrular."""
import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import local_api_evidence as local
from scripts import parallel_api_lookup as parallel
from scripts import sw_api_lookup as api


INTERFACE, MEMBER, YEAR = "ISketchManager", "CreateCircleByRadius", 2024
URL = api.official_api_url(YEAR, INTERFACE, MEMBER)


def document():
    text = "CreateCircleByRadius Radius in meters"
    return {"status": "found", "source": URL, "version": YEAR, "title": f"{MEMBER} ({INTERFACE})",
            "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "retrieved_at": "2026-01-01T00:00:00+00:00", "provider": "solidworks-direct"}


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api._OFFICIAL_CACHE.clear()
    yield
    api._OFFICIAL_CACHE.clear()


def test_persistent_cache_offline_failure_and_tampering(monkeypatch):
    monkeypatch.setattr(api, "_running_target", lambda *a: None)
    monkeypatch.setattr(api, "_installed_target", lambda *a: None)
    monkeypatch.setattr(api, "retrieve_official_document", lambda *a, **k: document())
    assert api.lookup_api(INTERFACE, MEMBER, YEAR)["official"]["text"] == document()["text"]
    api._OFFICIAL_CACHE.clear()
    monkeypatch.setattr(api, "retrieve_official_document", lambda *a, **k: pytest.fail("offline called network"))
    offline = api.lookup_api(INTERFACE, MEMBER, YEAR, online=False)
    assert offline["official"]["cache_status"] == "previously_retrieved"
    assert any("son alınan yerel önbellek" in warning for warning in offline["warnings"])
    assert local.load_document(2026, INTERFACE, MEMBER) is None
    path = local._cache_path(YEAR, INTERFACE, MEMBER)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["text"] = "tampered CreateCircleByRadius"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert local.load_document(YEAR, INTERFACE, MEMBER) is None


def test_fallback_does_not_send_task_or_call_when_disabled(monkeypatch):
    monkeypatch.setattr(api, "_running_target", lambda *a: None)
    monkeypatch.setattr(api, "_installed_target", lambda *a: None)
    def fail(*a, **kw): raise RuntimeError("network unavailable")
    monkeypatch.setattr(api, "retrieve_official_document", fail)
    calls = []
    def fallback(*args, **kwargs):
        calls.append(args)
        return {**document(), "provider": "parallel-anonymous", "version_evidence": "official_url_and_title"}
    monkeypatch.setattr(api, "retrieve_parallel_document", fallback)
    assert api.lookup_api(INTERFACE, MEMBER, YEAR, parallel_fallback=False)["official"] is None
    assert not calls
    result = api.lookup_api(INTERFACE, MEMBER, YEAR)
    assert calls == [(YEAR, INTERFACE, MEMBER, URL)]
    assert result["official"]["provider"] == "parallel-anonymous"
    assert any("bağlantı ve başlığa dayanıyor" in warning for warning in result["warnings"])
    monkeypatch.setattr(api, "retrieve_parallel_document", lambda *a, **k: pytest.fail("unexpected network"))
    assert api.lookup_api(INTERFACE, MEMBER, YEAR, online=False)["official"]["cache_status"]


def test_semantic_page_parser_requires_version_and_product(monkeypatch):
    class Response:
        def __init__(self, request): self.url = request.full_url
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return self.url
        def read(self, size):
            data = getattr(self, "data", b'<meta name="solidworks-version" content="2024"><meta name="solidworks-product" content="api"><title>CreateCircleByRadius (ISketchManager)</title><main><h1>CreateCircleByRadius</h1><p>Radius in meters</p><script>malicious</script></main>')
            self.data = b""
            return data
    class Opener:
        def open(self, request, timeout): return Response(request)
    monkeypatch.setattr(api.urllib.request, "build_opener", lambda *a: Opener())
    result = api.retrieve_official_document(YEAR, INTERFACE, MEMBER)
    assert "Radius in meters" in result["text"] and "malicious" not in result["text"]


def test_local_help_reads_single_matching_topic_without_installing_tools(monkeypatch, tmp_path):
    exe = tmp_path / "SLDWORKS.exe"
    archive = tmp_path / "api" / "apihelp.chm"
    archive.parent.mkdir()
    archive.write_bytes(b"fixture")
    monkeypatch.setattr(local.shutil, "which", lambda name: "7z.exe")
    basename = Path(URL.split("?", 1)[0]).name
    def run(args, stdout, **kwargs):
        if args[1] == "l": stdout.write(f"Path = sldworksapi/{basename}\n".encode())
        else: stdout.write(b"<title>CreateCircleByRadius (ISketchManager)</title><h1>CreateCircleByRadius</h1><p>Radius in meters</p>")
    monkeypatch.setattr(local.subprocess, "run", run)
    result = local.read_local_help(exe, YEAR, INTERFACE, MEMBER, URL)
    assert result["version_evidence"] == "installation_directory_only"
    assert "meters" in result["text"] and result["runtime_verified"] is False
    monkeypatch.setattr(local, "_find_sevenzip", lambda: None)
    assert local.read_local_help(exe, YEAR, INTERFACE, MEMBER, URL) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows 7-Zip registry discovery")
def test_find_sevenzip_in_registered_install_without_path(monkeypatch, tmp_path):
    executable = tmp_path / "7z.exe"
    executable.write_bytes(b"fixture")
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_64KEY=4,
        KEY_WOW64_32KEY=8, KEY_READ=16, OpenKey=lambda *args: Key(),
        QueryValueEx=lambda key, name: (str(tmp_path), 1))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(local.shutil, "which", lambda name: None)
    assert local._find_sevenzip() == str(executable)


@pytest.mark.skipif(os.name != "nt", reason="Windows 7-Zip registry discovery")
def test_standalone_7za_is_not_treated_as_chm_reader(monkeypatch):
    registry = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_64KEY=4,
        KEY_WOW64_32KEY=8, KEY_READ=16)
    def missing(*args): raise OSError("not installed")
    registry.OpenKey = missing
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(local.shutil, "which", lambda name: "7za.exe" if name == "7za" else None)
    assert local._find_sevenzip() is None


def test_local_help_accepts_legacy_topic_name(monkeypatch, tmp_path):
    exe = tmp_path / "SLDWORKS.exe"
    archive = tmp_path / "api" / "apihelp.chm"
    archive.parent.mkdir()
    archive.write_bytes(b"fixture")
    monkeypatch.setattr(local, "_find_sevenzip", lambda: "7z.exe")
    def run(args, stdout, **kwargs):
        if args[1] == "l": stdout.write(b"Path = ISketchManager/ISketchManager__CreateCircleByRadius.htm\n")
        else: stdout.write(b"<title>ISketchManager::CreateCircleByRadius</title><p>CreateCircleByRadius Radius in meters</p>")
    monkeypatch.setattr(local.subprocess, "run", run)
    result = local.read_local_help(exe, YEAR, INTERFACE, MEMBER, URL)
    assert result and "Radius in meters" in result["text"]

    def wrong_title(args, stdout, **kwargs):
        if args[1] == "l": stdout.write(b"Path = ISketchManager/ISketchManager__CreateCircleByRadius.htm\n")
        else: stdout.write(b"<title>ISketchManager::OtherMethod</title><p>CreateCircleByRadius mentioned here</p>")
    monkeypatch.setattr(local.subprocess, "run", wrong_title)
    assert local.read_local_help(exe, YEAR, INTERFACE, MEMBER, URL) is None


def test_local_help_preserves_table_cell_boundaries(monkeypatch, tmp_path):
    archive = tmp_path / "api" / "swconst.chm"
    archive.parent.mkdir()
    archive.write_bytes(b"fixture")
    monkeypatch.setattr(local, "_find_sevenzip", lambda: "7z.exe")
    url = api.official_api_url(2026, "swMateType_e", "swMateCOINCIDENT")
    basename = Path(url.split("?", 1)[0]).name
    def run(args, stdout, **kwargs):
        if args[1] == "l": stdout.write(f"Path = {basename}\n".encode())
        else: stdout.write(b"\xef\xbb\xbf\r\n    \r\n<title>swMateType_e Enumeration</title><table><tr><td>swMateCOINCIDENT</td><td>0</td></tr></table>")
    monkeypatch.setattr(local.subprocess, "run", run)
    result = local.read_local_help(tmp_path / "SLDWORKS.exe", 2026, "swMateType_e", "swMateCOINCIDENT", url)
    assert result and "swMateCOINCIDENT\t0" in result["text"]
    assert not result["text"].startswith("\ufeff") and "\r" not in result["text"]


@pytest.mark.parametrize("url", ["https://evil.test/2024/api/ISketchManager~CreateCircleByRadius.html",
    "https://help.solidworks.com/2024/api/../2026/ISketchManager~CreateCircleByRadius.html",
    "https://help.solidworks.com/2024/api/%252e%252e/ISketchManager~CreateCircleByRadius.html",
    "https://user@help.solidworks.com/2024/api/ISketchManager~CreateCircleByRadius.html"])
def test_parallel_rejects_invalid_source_url(url):
    assert not parallel._official_url(url, YEAR, INTERFACE, MEMBER)


def test_parallel_session_reuses_anonymous_session_and_filters_sources(monkeypatch):
    import httpx
    import mcp
    import mcp.client.streamable_http as stream
    seen = []
    class Client:
        def __init__(self, **kwargs):
            assert type(kwargs["auth"]) is httpx.Auth and kwargs["follow_redirects"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
    @asynccontextmanager
    async def transport(url, http_client):
        assert url == parallel._ENDPOINT
        yield None, None, None
    class Session:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def initialize(self): pass
        async def call_tool(self, name, arguments):
            seen.append((name, arguments))
            payload = ({"results": [], "session_id": "session-one"} if len(seen) == 1 else
                       {"results": [{"url": "https://evil.test"}, {"url": URL}], "session_id": "session-one"} if len(seen) == 2 else
                       {"results": [{"url": URL, "title": f"{MEMBER} ({INTERFACE}) - 2024", "excerpts": ["CreateCircleByRadius Radius in meters"]}]})
            return SimpleNamespace(isError=False, content=[SimpleNamespace(text=json.dumps(payload))])
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(stream, "streamable_http_client", transport)
    monkeypatch.setattr(mcp, "ClientSession", Session)
    result = asyncio.run(parallel._query(YEAR, INTERFACE, MEMBER, URL))
    assert result["version_evidence"] == "official_url_and_title"
    assert [item[0] for item in seen] == ["web_fetch", "web_search", "web_fetch"]
    assert seen[1][1]["session_id"] == seen[2][1]["session_id"] == "session-one"
    assert seen[2][1]["urls"] == [URL]


def test_parallel_cancellation_cleans_up(monkeypatch):
    cancelled = []
    async def slow(*args):
        try: await asyncio.sleep(10)
        finally: cancelled.append(True)
    monkeypatch.setattr(parallel, "_query", slow)
    async def run():
        checks = iter([False, True])
        with pytest.raises(parallel.ParallelLookupCancelled):
            await parallel._guard(YEAR, INTERFACE, MEMBER, URL, lambda: next(checks), 3)
    asyncio.run(run())
    assert cancelled == [True]
