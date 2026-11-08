"""目标文档身份核验，不接触 SolidWorks 或已有用户文件。"""
from __future__ import annotations

import contextvars
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
from document_identity import DocumentIdentity, DocumentIdentityError, bind_document, verify_bound_document


def test_matches_pid_and_normalized_document_path(tmp_path):
    path = tmp_path / "folder" / "part.SLDPRT"
    path.parent.mkdir()
    identity = DocumentIdentity.create(123, str(path))
    with bind_document(identity):
        verify_bound_document(123, str(path.parent / "." / "part.SLDPRT"))
        with pytest.raises(DocumentIdentityError, match="süreci"):
            verify_bound_document(456, str(path))
        with pytest.raises(DocumentIdentityError, match="Etkin belge"):
            verify_bound_document(123, str(path.parent / "other.SLDPRT"))


@pytest.mark.parametrize("pid", [None, 0, -1, True, "123"])
def test_rejects_invalid_process_id(tmp_path, pid):
    with pytest.raises(DocumentIdentityError, match="süreç ID"):
        DocumentIdentity.create(pid, str(tmp_path / "part.SLDPRT"))


@pytest.mark.parametrize("path", ["", "relative.sldprt", " ", "a\x00b.sldprt", "bad*.sldprt"])
def test_rejects_unsaved_relative_or_invalid_path(path):
    with pytest.raises(DocumentIdentityError):
        DocumentIdentity.create(123, path)


def test_requires_approved_binding_and_restores_context(tmp_path):
    first = DocumentIdentity.create(1, str(tmp_path / "a.SLDPRT"))
    second = DocumentIdentity.create(2, str(tmp_path / "b.SLDASM"))
    with pytest.raises(DocumentIdentityError, match="bağlı değil"):
        verify_bound_document(1, first.path)
    with bind_document(first):
        with bind_document(second):
            verify_bound_document(2, second.path)
        verify_bound_document(1, first.path)
    with pytest.raises(DocumentIdentityError, match="bağlı değil"):
        verify_bound_document(1, first.path)


def test_document_identity_does_not_leak_into_fresh_context(tmp_path):
    identity = DocumentIdentity.create(1, str(tmp_path / "a.SLDPRT"))
    with bind_document(identity):
        with pytest.raises(DocumentIdentityError, match="bağlı değil"):
            contextvars.Context().run(verify_bound_document, 1, identity.path)


def test_direct_constructor_also_validates(tmp_path):
    with pytest.raises(DocumentIdentityError):
        DocumentIdentity(-1, str(tmp_path / "a.SLDPRT"))


def test_global_document_or_subprocess_operations_remain_blocked():
    import policy

    for name in ("solidworks_close_documents", "solidworks_document_units",
                 "solidworks_add_component", "solidworks_review_active", "solidworks_pack_and_go",
                 "solidworks_build_round_sweeps", "solidworks_import_step_part",
                 "solidworks_replace_component_preserving_transform", "solidworks_exclude_reviewed_bodies"):
        assert policy.needs_active_document_identity(name)
        assert not policy.supports_document_identity(name)


def test_binding_reaches_fastmcp_sync_tool_thread(tmp_path):
    from mcp.server.fastmcp import FastMCP

    identity = DocumentIdentity.create(42, str(tmp_path / "threaded.SLDPRT"))
    server = FastMCP("document-identity-test")

    @server.tool(name="guard_probe")
    def probe() -> str:
        verify_bound_document(42, identity.path)
        return "ok"

    async def run():
        with bind_document(identity):
            return await server._tool_manager.call_tool("guard_probe", {}, convert_result=False)

    assert asyncio.run(run()) == "ok"
