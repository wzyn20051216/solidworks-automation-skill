"""@brief CAD Studio 专业知识检索回归测试。"""

from pathlib import Path
import urllib.error

import pytest

from apps.desktop.cad_workbench.agent_contracts import compile_codex_prompt, policy_reasons
from apps.desktop.cad_workbench.knowledge_retrieval import (
    build_job_knowledge_context,
    retrieve_cloud_knowledge,
    retrieve_local_knowledge,
)


def test_local_knowledge_retrieval_returns_traceable_sources(tmp_path: Path) -> None:
    document = tmp_path / "holes.md"
    document.write_text("# 螺纹孔\n\nM6 粗牙攻丝底孔通常取 5.0 mm，孔口需要倒角。", encoding="utf-8")

    chunks = retrieve_local_knowledge("M6 螺纹孔攻丝底孔", roots=[tmp_path], top_k=3)

    assert chunks
    assert chunks[0].source == str(document.resolve())
    assert chunks[0].sha256
    assert "5.0 mm" in chunks[0].text


def test_job_knowledge_context_defaults_to_local_skill_sources() -> None:
    context = build_job_knowledge_context(
        {
            "objective": "创建带 M6 螺纹孔的 CNC 安装座",
            "detail": "需要攻丝底孔和孔口倒角",
            "uiConfig": {"knowledgeBase": {"topK": 4}},
        }
    )

    assert context["providers"] == ["local"]
    assert context["chunks"]
    assert all(item["source"] and item["sha256"] for item in context["chunks"])


def test_cloud_knowledge_requires_declared_network_capability() -> None:
    context = build_job_knowledge_context(
        {
            "objective": "检索轴承座公差知识",
            "uiConfig": {
                "knowledgeBase": {
                    "cloudEnabled": True,
                    "endpoint": "https://knowledge.example.test/retrieve",
                }
            },
        }
    )

    assert any("external_network" in warning for warning in context["warnings"])
    assert "cloud" not in context["providers"]


def test_prompt_includes_rag_source_and_hash() -> None:
    job = {
        "objective": "创建轴承座",
        "_knowledgeContext": {
            "chunks": [
                {
                    "title": "轴承配合",
                    "source": "C:/kb/bearing.md",
                    "sha256": "abc123",
                    "text": "轴承座孔公差必须按载荷和配合目标复核。",
                }
            ]
        },
    }

    prompt = compile_codex_prompt(job)

    assert "【RAG 专业知识上下文】" in prompt
    assert "C:/kb/bearing.md" in prompt
    assert "abc123" in prompt
    assert "不可信参考数据" in prompt


def test_cloud_rag_rejects_arbitrary_environment_variable_name(monkeypatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-be-read")

    with pytest.raises(ValueError, match="CAD_STUDIO_RAG_TOKEN"):
        retrieve_cloud_knowledge(
            "机械知识",
            {
                "endpoint": "https://rag.example.test/retrieve",
                "tokenEnv": "AWS_SECRET_ACCESS_KEY",
            },
        )


def test_cloud_rag_disables_authorized_redirects(monkeypatch) -> None:
    """@brief 防止 Authorization 头被 urllib 自动转发到重定向目标。"""
    monkeypatch.setenv("CAD_STUDIO_RAG_TOKEN", "secret-token")

    class FakeOpener:
        def open(self, request, timeout):  # noqa: ANN001, ANN201
            assert request.get_header("Authorization") == "Bearer secret-token"
            raise urllib.error.HTTPError(request.full_url, 302, "redirect blocked", {}, None)

    monkeypatch.setattr(
        "apps.desktop.cad_workbench.knowledge_retrieval.urllib.request.build_opener",
        lambda handler: FakeOpener(),
    )

    with pytest.raises(RuntimeError, match="云知识库检索失败"):
        retrieve_cloud_knowledge(
            "机械知识",
            {"endpoint": "https://rag.example.test/retrieve"},
        )


def test_policy_derives_network_and_cross_workspace_from_knowledge_config() -> None:
    reasons = policy_reasons(
        {
            "uiConfig": {
                "knowledgeBase": {
                    "cloudEnabled": True,
                    "localRoots": ["D:/company-standards"],
                }
            }
        }
    )

    assert any("外部网络" in reason for reason in reasons)
    assert any("跨工作区访问" in reason for reason in reasons)
