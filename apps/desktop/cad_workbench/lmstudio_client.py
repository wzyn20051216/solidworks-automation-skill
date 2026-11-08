"""@brief LM Studio OpenAI uyumlu API uç noktası için yerel köprü CLI.

LM Studio yerel sunucusu (varsayılan: http://127.0.0.1:1234/v1) OpenAI uyumlu
bir REST API sunar. Bu modül, birleşik Agent Provider protokolünü bu uç
noktaya çevirir: istem (prompt) /chat/completions'a gönderilir ve model
yanıtı stdout'a yazılır; böylece parse_provider_result tarafından
normalleştirilebilir.

Ortam değişkenleri:
* ``LMSTUDIO_BASE_URL`` — API uç noktası (varsayılan ``http://127.0.0.1:1234/v1``)
* ``LMSTUDIO_API_KEY``  — isteğe bağlı Bearer anahtarı (LM Studio genelde istemez)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_TIMEOUT_SECONDS = 600

SYSTEM_PROMPT = (
    "Sen CAD Studio icin calisan bir muhendislik otomasyon ajanisin. "
    "Yanitini YALNIZCA verilen JSON semasina uyan tek bir JSON nesnesi olarak dondur: "
    '{"summary": str, "changedFiles": [str], '
    '"verification": [{"command": str, "status": "passed|failed|skipped", "note": str}], '
    '"risks": [str], "nextSteps": [str]}. '
    "JSON disinda hicbir metin, aciklama veya Markdown kullanma."
)


def resolve_base_url(value: str | None = None) -> str:
    """@brief CLI argümanı > ortam değişkeni > varsayılan sırasıyla uç noktayı çözer."""
    base = (value or os.environ.get("LMSTUDIO_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base.lower().startswith(("http://", "https://")):
        base = f"http://{base}"
    if not base.lower().endswith("/v1"):
        base = f"{base}/v1"
    return base


def _request(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    """@brief LM Studio uç noktasına JSON isteği gönderir ve JSON yanıtı döndürür."""
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LMSTUDIO_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
        except OSError:
            pass
        raise RuntimeError(f"LM Studio API hatası {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"LM Studio uç noktasına ulaşılamadı: {url}. LM Studio'da yerel sunucunun açık olduğundan emin olun. ({exc})"
        ) from exc


def list_models(base_url: str, timeout: float = 10) -> list[str]:
    """@brief /models uç noktasından yüklü model kimliklerini okur."""
    payload = _request(f"{base_url}/models", None, timeout)
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [str(item.get("id")) for item in models if isinstance(item, dict) and item.get("id")]


def probe(base_url: str) -> int:
    """@brief Model isteği göndermeden uç noktanın erişilebilirliğini doğrular."""
    try:
        models = list_models(base_url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    summary = ", ".join(models[:5]) if models else "yüklü model yok"
    print(f"LM Studio API hazır ({base_url}); modeller: {summary}")
    return 0


def run_task(base_url: str, prompt: str, model: str | None, schema_path: Path | None, timeout: float) -> int:
    """@brief İstemi /chat/completions'a gönderir ve birleşik sonucu stdout'a yazar."""
    chosen_model = (model or "").strip()
    if not chosen_model:
        models = list_models(base_url)
        if not models:
            print("LM Studio'da yüklü model bulunamadı; önce bir model yükleyin.", file=sys.stderr)
            return 1
        chosen_model = models[0]
    payload: dict[str, Any] = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "stream": False,
    }
    if schema_path and schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "unified_agent_result", "strict": True, "schema": schema},
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    response = _request(f"{base_url}/chat/completions", payload, timeout)
    choices = response.get("choices") if isinstance(response, dict) else None
    content = ""
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = str(message.get("content") or "")
    if not content.strip():
        print("LM Studio boş yanıt döndürdü; model yüklü ve çalışır durumda mı?", file=sys.stderr)
        return 1
    print(content)
    return 0


def main(argv: list[str] | None = None) -> int:
    """@brief Komut satırı girişi: --version sağlık kontrolü, aksi halde görev çalıştırma."""
    parser = argparse.ArgumentParser(description="LM Studio OpenAI uyumlu API köprüsü")
    parser.add_argument("--version", action="store_true", help="Uç nokta sağlık kontrolü yap ve çık")
    parser.add_argument("--base-url", default=None, help="LM Studio API uç noktası (varsayılan: LMSTUDIO_BASE_URL veya http://127.0.0.1:1234/v1)")
    parser.add_argument("--model", default=None, help="Kullanılacak model kimliği; boşsa ilk yüklü model seçilir")
    parser.add_argument("--schema", default=None, help="Birleşik sonuç JSON şema dosyası")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="İstek zaman aşımı (saniye)")
    parser.add_argument("prompt", nargs="?", default="", help="Modele gönderilecek görev istemi")
    args = parser.parse_args(argv)

    base_url = resolve_base_url(args.base_url)
    if args.version:
        return probe(base_url)
    if not args.prompt.strip():
        parser.error("görev istemi (prompt) gerekli")
    try:
        return run_task(base_url, args.prompt, args.model, Path(args.schema) if args.schema else None, args.timeout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
