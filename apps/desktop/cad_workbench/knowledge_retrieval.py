"""@brief CAD Studio yerel öncelikli RAG araması ve isteğe bağlı bulut bilgi tabanı bağlayıcısı."""

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
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_+.#/-]*|[\u4e00-\u9fff]")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """@brief Bulut RAG isteklerinin yetkilendirme başlığıyla başka adreslere otomatik yönlenmesini engeller."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


@dataclass(frozen=True)
class KnowledgeChunk:
    """@brief İzlenebilir tek bir bilgi tabanı arama sonucu."""

    source: str
    title: str
    text: str
    score: float
    sha256: str
    provider: str = "local"
    version: int | None = None
    retrieved_at: str | None = None
    evidence_level: str | None = None


def default_knowledge_roots() -> list[Path]:
    """@brief Yerleşik mekanik bilgi kök dizinlerini döndürür."""
    return [
        REPO_ROOT / "SKILL.md",
        REPO_ROOT / "references",
        REPO_ROOT / "subskills",
    ]


def _iter_documents(roots: Iterable[Path]) -> Iterable[Path]:
    """@brief Bilgi kök dizinlerindeki desteklenen metin dosyalarını listeler."""
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
    """@brief Bilgi belgesini güvenle okur; anormal büyüklükteki girdileri reddeder."""
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
    """@brief Bilgi belgesini paragraflara böler ve az miktarda bağlam örtüşmesi korur."""
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
    """@brief Çince ve İngilizce mekanik arama terimlerini çıkarır; Çince karakter bazında alınır ve komşu ikililer eklenir."""
    raw = [item.lower() for item in TOKEN_PATTERN.findall(text)]
    chinese = [item for item in raw if "\u4e00" <= item <= "\u9fff"]
    bigrams = ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]
    return [*raw, *bigrams]


def _title(path: Path, text: str) -> str:
    """@brief Markdown başlığından veya dosya adından sonuç başlığı üretir."""
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("# ").strip()[:120]
    return path.stem.replace("_", " ")[:120]


def retrieve_local_knowledge(query: str, roots: Iterable[Path] | None = None, top_k: int = 6) -> list[KnowledgeChunk]:
    """@brief Yerel Skill bilgisi üzerinde hafif BM25 tarzı arama yapar."""
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
    """@brief Açıkça yapılandırılmış HTTPS RAG servisini çağırır; token yalnızca ortam değişkeninden okunur."""
    endpoint = str(config.get("endpoint") or "").strip()
    parsed_endpoint = urllib.parse.urlsplit(endpoint)
    if (
        parsed_endpoint.scheme.lower() != "https"
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ValueError("Bulut bilgi tabanı endpoint'i HTTPS kullanmak zorundadır")
    token_env = str(config.get("tokenEnv") or "CAD_STUDIO_RAG_TOKEN")
    if token_env != "CAD_STUDIO_RAG_TOKEN":
        raise ValueError("Bulut bilgi tabanı token'ı yalnızca CAD_STUDIO_RAG_TOKEN üzerinden okuyabilir")
    token = os.environ.get(token_env, "")
    if not token:
        raise RuntimeError(f"Bulut bilgi tabanı için {token_env} ortam değişkeni eksik")
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
        raise RuntimeError(f"Bulut bilgi tabanı araması başarısız: {exc}") from exc
    items = raw.get("chunks") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("Bulut bilgi tabanı yanıtında chunks dizisi eksik")
    chunks: list[KnowledgeChunk] = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        text = str(item["text"]).strip()[:4000]
        chunks.append(
            KnowledgeChunk(
                source=str(item.get("source") or endpoint),
                title=str(item.get("title") or "Bulut bilgisi")[:120],
                text=text,
                score=float(item.get("score") or 0.0),
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                provider="cloud",
            )
        )
    return chunks


def _api_knowledge(query: str, config: dict[str, Any], cancelled: Callable[[], bool] | None) -> tuple[list[KnowledgeChunk], list[str]]:
    """Önce açık referansları, ardından bu projede doğrulanmış işlemlerden adayları seçer; görev tam metni dışarı gönderilmez."""
    from scripts.api_intent import task_candidates, task_years
    references, explicit_keys = task_candidates(query)
    if not references:
        return [], []
    from scripts.sw_api_lookup import lookup_api

    years = task_years(query)
    if len(years) > 1:
        return [], ["Görev birden fazla SolidWorks yılından bahsediyor; API doğrulamadan önce hedef sürümü açıkça belirtin."]
    year = next(iter(years)) if len(years) == 1 else None
    results: list[KnowledgeChunk] = []
    warnings: list[str] = []
    inferred = [f"{interface}.{member}" for interface, member in references if (interface.casefold(), member.casefold()) not in explicit_keys]
    if inferred:
        warnings.append("Doğal dilden tanınan API doğrulama adayları: " + ", ".join(inferred) + "; gerçek yöntem görev planlaması ve sürüm kanıtıyla doğrulanmalıdır.")
    online_setting = config.get("officialApiDocsEnabled", True)
    if not isinstance(online_setting, bool):
        warnings.append("Resmi API dokümantasyonu çevrim içi ayarı geçersiz; çevrim dışı doğrulama kullanıldı.")
        online_setting = False
    parallel_setting = config.get("parallelApiFallbackEnabled", True)
    if not isinstance(parallel_setting, bool):
        warnings.append("Parallel yedek ayarı geçersiz; bu servis kapatıldı.")
        parallel_setting = False
    for interface, member in references:
        result = lookup_api(interface, member, year, online=online_setting, parallel_fallback=parallel_setting,
                            cancelled=cancelled)
        warnings.extend(result.get("warnings") or [])
        target = result.get("target") or {}
        library = result.get("typelib") or {}
        if library.get("member_found"):
            text = json.dumps({"target": target, "declarations": library.get("declarations"),
                               "runtime_verified": False}, ensure_ascii=False)
            results.append(KnowledgeChunk(
                source=f"{library.get('file')} (SolidWorks {target.get('year')})",
                title=f"{interface}.{member} yerel tip kitaplığı bildirimi", text=text, score=0.0,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), provider="local-api",
                version=target.get("year"), evidence_level="type_library_declaration"))
        local_help = result.get("local_help") or {}
        if local_help.get("status") == "found":
            results.append(KnowledgeChunk(
                source=local_help["source"], title=local_help["title"], text=local_help["text"], score=0.0,
                sha256=local_help["sha256"], provider="local-api-help", version=local_help.get("version"),
                retrieved_at=local_help.get("retrieved_at"), evidence_level=("local_help_signed_installer" if
                    local_help.get("version_evidence") == "signed_installer_product_and_file_hash" else "local_help_version_unverified")))
        official = result.get("official") or {}
        if official.get("status") == "found":
            is_parallel = official.get("provider") == "parallel-anonymous"
            results.append(KnowledgeChunk(
                source=official["source"], title=official["title"], text=official["text"],
                score=0.0, sha256=official["sha256"], provider="parallel-api" if is_parallel else "official-api",
                version=official.get("version"), retrieved_at=official.get("retrieved_at"),
                evidence_level=("cached_parallel_reference" if is_parallel else "cached_official_document")
                    if official.get("cache_status") else ("parallel_extracted_official" if is_parallel else "official_document")))
        if result.get("status") in {"unknown", "not_found", "conflict"}:
            warnings.append(f"{interface}.{member} için hedef sürüm veya arayüz henüz doğrulanmadı: {result.get('status')}.")
    return results, warnings


def build_job_knowledge_context(job: dict[str, Any], *, cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """@brief Görev hedefine göre Codex Prompt'a enjekte edilebilir, denetlenebilir RAG bağlamı oluşturur."""
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
    api_chunks, api_warnings = _api_knowledge(query, knowledge_config, cancelled)
    warnings.extend(api_warnings)
    if knowledge_config.get("cloudEnabled") is True:
        capabilities = job.get("capabilities") if isinstance(job.get("capabilities"), list) else []
        if "external_network" not in capabilities:
            warnings.append("Bulut bilgi tabanı çalıştırılmadı: görev external_network yeteneğini bildirmedi.")
        elif not job.get("approvedAt"):
            warnings.append("Bulut bilgi tabanı çalıştırılmadı: dış ağ yeteneği henüz insan onayından geçmedi.")
        else:
            try:
                chunks.extend(retrieve_cloud_knowledge(query, knowledge_config))
            except (ValueError, RuntimeError) as exc:
                warnings.append(str(exc))
    chunks.sort(key=lambda item: (-item.score, item.provider, item.source))
    limited: list[KnowledgeChunk] = []
    seen: set[tuple[str, str]] = set()
    remaining_chars = 12_000
    for item in [*api_chunks, *chunks]:
        key = (item.source, item.sha256)
        if key in seen or remaining_chars <= 0 or len(limited) >= 12:
            continue
        seen.add(key)
        # Prompt'ta her parça en fazla 4000 karakter gösterilir; karma, Agent'a fiilen gönderilen parçayla eşleşmelidir.
        text = item.text[:min(remaining_chars, 4000)]
        if not text:
            continue
        limited.append(
            KnowledgeChunk(
                source=item.source,
                title=item.title,
                text=text,
                score=item.score,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                provider=item.provider,
                version=item.version,
                retrieved_at=item.retrieved_at,
                evidence_level=item.evidence_level,
            )
        )
        remaining_chars -= len(text)
    return {
        "querySha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "providers": sorted(set(item.provider for item in limited)),
        "chunks": [asdict(item) for item in limited],
        "warnings": warnings,
    }
