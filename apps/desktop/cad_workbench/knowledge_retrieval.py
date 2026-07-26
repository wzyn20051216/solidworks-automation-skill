"""@brief CAD Studio 本地优先 RAG 检索与可选云知识库连接器。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_+.#/-]*|[\u4e00-\u9fff]")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """@brief 禁止云 RAG 请求携带授权头自动跳转到其他地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


@dataclass(frozen=True)
class KnowledgeChunk:
    """@brief 一段可追溯的知识库检索结果。"""

    source: str
    title: str
    text: str
    score: float
    sha256: str
    provider: str = "local"


def default_knowledge_roots() -> list[Path]:
    """@brief 返回内置机械知识根目录。"""
    return [
        REPO_ROOT / "SKILL.md",
        REPO_ROOT / "references",
        REPO_ROOT / "subskills",
    ]


def _iter_documents(roots: Iterable[Path]) -> Iterable[Path]:
    """@brief 枚举知识根目录中的受支持文本文件。"""
    seen: set[Path] = set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        candidates = [root] if root.is_file() else root.rglob("*") if root.is_dir() else []
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved


def _document_text(path: Path, max_bytes: int = 2 * 1024 * 1024) -> str:
    """@brief 安全读取知识文档，拒绝异常大的输入。"""
    if path.stat().st_size > max_bytes:
        return ""
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if path.suffix.lower() == ".json":
        try:
            value = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return ""
    return value.strip()


def _chunks(text: str, max_chars: int = 1400, overlap: int = 180) -> Iterable[str]:
    """@brief 按段落切分知识文档，并保留少量上下文重叠。"""
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            yield current
            current = f"{current[-overlap:]}\n\n{paragraph}".strip()
        else:
            for start in range(0, len(paragraph), max_chars - overlap):
                yield paragraph[start : start + max_chars]
            current = ""
    if current:
        yield current


def _tokens(text: str) -> list[str]:
    """@brief 提取中英文机械检索词；中文按单字并补充相邻二元组。"""
    raw = [item.lower() for item in TOKEN_PATTERN.findall(text)]
    chinese = [item for item in raw if "\u4e00" <= item <= "\u9fff"]
    bigrams = ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]
    return [*raw, *bigrams]


def _title(path: Path, text: str) -> str:
    """@brief 从 Markdown 标题或文件名生成结果标题。"""
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("# ").strip()[:120]
    return path.stem.replace("_", " ")[:120]


def retrieve_local_knowledge(query: str, roots: Iterable[Path] | None = None, top_k: int = 6) -> list[KnowledgeChunk]:
    """@brief 对本地 Skill 知识进行轻量 BM25 风格检索。"""
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []

    documents: list[tuple[Path, str, str, list[str]]] = []
    document_frequency: dict[str, int] = {}
    for path in _iter_documents(roots or default_knowledge_roots()):
        text = _document_text(path)
        if not text:
            continue
        for chunk in _chunks(text):
            tokens = _tokens(chunk)
            documents.append((path, _title(path, chunk), chunk, tokens))
            for token in query_tokens.intersection(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1

    count = max(1, len(documents))
    ranked: list[KnowledgeChunk] = []
    for path, title, text, tokens in documents:
        token_counts = {token: tokens.count(token) for token in query_tokens if token in tokens}
        if not token_counts:
            continue
        score = 0.0
        for token, frequency in token_counts.items():
            inverse_frequency = math.log(1 + count / (1 + document_frequency.get(token, 0)))
            score += (1 + math.log(frequency)) * inverse_frequency
        normalized = score / math.sqrt(max(1, len(tokens)))
        ranked.append(
            KnowledgeChunk(
                source=str(path),
                title=title,
                text=text,
                score=round(normalized, 6),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.source, item.sha256))
    return ranked[: max(1, min(int(top_k), 12))]


def retrieve_cloud_knowledge(query: str, config: dict[str, Any], timeout_seconds: float = 8.0) -> list[KnowledgeChunk]:
    """@brief 调用显式配置的 HTTPS RAG 服务；令牌只从环境变量读取。"""
    endpoint = str(config.get("endpoint") or "").strip()
    parsed_endpoint = urllib.parse.urlsplit(endpoint)
    if (
        parsed_endpoint.scheme.lower() != "https"
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ValueError("云知识库 endpoint 必须使用 HTTPS")
    token_env = str(config.get("tokenEnv") or "CAD_STUDIO_RAG_TOKEN")
    if token_env != "CAD_STUDIO_RAG_TOKEN":
        raise ValueError("云知识库只允许从 CAD_STUDIO_RAG_TOKEN 读取令牌")
    token = os.environ.get(token_env, "")
    if not token:
        raise RuntimeError(f"云知识库缺少环境变量 {token_env}")
    payload = json.dumps(
        {
            "query": query,
            "namespace": str(config.get("namespace") or "cad-studio"),
            "topK": max(1, min(int(config.get("topK") or 6), 12)),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"云知识库检索失败: {exc}") from exc
    items = raw.get("chunks") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("云知识库响应缺少 chunks 数组")
    chunks: list[KnowledgeChunk] = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        text = str(item["text"]).strip()[:4000]
        chunks.append(
            KnowledgeChunk(
                source=str(item.get("source") or endpoint),
                title=str(item.get("title") or "云知识")[:120],
                text=text,
                score=float(item.get("score") or 0.0),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                provider="cloud",
            )
        )
    return chunks


def build_job_knowledge_context(job: dict[str, Any]) -> dict[str, Any]:
    """@brief 根据任务目标构建可注入 Codex Prompt 的可审计 RAG 上下文。"""
    query = "\n".join(
        str(value)
        for value in (job.get("objective"), job.get("detail"), job.get("expectedOutput"), job.get("prompt"))
        if value
    )
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    knowledge_config = ui_config.get("knowledgeBase") if isinstance(ui_config.get("knowledgeBase"), dict) else {}
    roots = default_knowledge_roots()
    for raw_path in knowledge_config.get("localRoots", []) if isinstance(knowledge_config.get("localRoots"), list) else []:
        path = Path(str(raw_path)).expanduser()
        if path.exists():
            roots.append(path)
    chunks = retrieve_local_knowledge(query, roots=roots, top_k=int(knowledge_config.get("topK") or 6))
    warnings: list[str] = []
    if knowledge_config.get("cloudEnabled") is True:
        capabilities = job.get("capabilities") if isinstance(job.get("capabilities"), list) else []
        if "external_network" not in capabilities:
            warnings.append("云知识库未执行：任务未声明 external_network 能力。")
        elif not job.get("approvedAt"):
            warnings.append("云知识库未执行：外部网络能力尚未人工审批。")
        else:
            try:
                chunks.extend(retrieve_cloud_knowledge(query, knowledge_config))
            except (ValueError, RuntimeError) as exc:
                warnings.append(str(exc))
    chunks.sort(key=lambda item: (-item.score, item.provider, item.source))
    limited: list[KnowledgeChunk] = []
    seen: set[tuple[str, str]] = set()
    remaining_chars = 12_000
    for item in chunks:
        key = (item.source, item.sha256)
        if key in seen or remaining_chars <= 0 or len(limited) >= 12:
            continue
        seen.add(key)
        text = item.text[:remaining_chars]
        if not text:
            continue
        limited.append(
            KnowledgeChunk(
                source=item.source,
                title=item.title,
                text=text,
                score=item.score,
                sha256=item.sha256,
                provider=item.provider,
            )
        )
        remaining_chars -= len(text)
    return {
        "querySha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "providers": sorted(set(item.provider for item in limited)),
        "chunks": [asdict(item) for item in limited],
        "warnings": warnings,
    }
