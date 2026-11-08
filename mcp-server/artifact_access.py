"""@brief MCP salt okunur ürün adaptörü: Artifact Ledger'ı yeniden kullanır, opak ID ve dizin sınırı uygular."""
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from uuid import uuid4

from apps.desktop.cad_workbench.artifact_ledger import ledger_path_for, write_artifact_ledger

_ID = re.compile(r"^(mcp-[0-9a-f]{32})-([0-9]{1,5})$")
MAX_INLINE = 8 * 1024 * 1024


class ArtifactAccess:
    """@brief Ürün ID'sini mevcut teslim kaydıyla ilişkilendirir; ikinci bir dosya defteri oluşturmaz."""
    def __init__(self, root, queue_dir):
        self.root = Path(root).expanduser().resolve()
        self.queue_dir = Path(queue_dir).expanduser().resolve()

    def _inside(self, path):
        """@brief Mutlak yollar, bağlantılar veya ledger içeriğinden kaynaklanan sınır dışı okumaları reddeder."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("Ürün izin verilen çıktı dizininde değil veya dosya mevcut değil")
        return resolved

    def publish(self, payload):
        """@brief Mevcut dosyaları yalnızca açık çıktı alanlarından kaydeder; girdi belgelerini veya rastgele dizeleri okumaz."""
        candidates = []
        def walk(value, output=False):
            if isinstance(value, dict):
                for key, item in value.items():
                    is_output = key in {"output_path", "outputPath", "report_path", "reportPath", "pdf_path", "drawing_path"}
                    if is_output or (output and key == "path"):
                        if isinstance(item, str):
                            candidates.append(item)
                    else:
                        walk(item, output or key in {"outputs", "artifacts", "previews", "preview_paths"})
            elif isinstance(value, list):
                for item in value:
                    walk(item, output)
            elif output and isinstance(value, str):
                candidates.append(value)
        walk(payload)
        paths = []
        for candidate in candidates:
            try:
                path = self._inside(candidate)
                if path not in paths:
                    paths.append(path)
            except (OSError, ValueError):
                continue
        if not paths:
            return []
        run = "mcp-" + uuid4().hex
        ledger = write_artifact_ledger(self.queue_dir, {"id": run, "runId": run, "kind": "mcp_tool", "executor": "mcp"},
            {"outputs": [{"path": str(path)} for path in paths]})
        refs = []
        for index, item in enumerate(ledger["artifacts"]):
            artifact_id = f"{run}-{index}"
            refs.append({"artifact_id": artifact_id, "uri": "cad-artifact://delivery/" + artifact_id,
                "name": Path(item["path"]).name, "size_bytes": item["sizeBytes"], "sha256": item["sha256"],
                "mime_type": mimetypes.guess_type(item["path"])[0] or "application/octet-stream"})
        return refs

    def read(self, artifact_id, offset=0, max_bytes=MAX_INLINE):
        """@brief Sınırlı okuma yapar ve içerik hash'ini doğrular; istemci path parametresiyle rastgele dosya okuyamaz."""
        match = _ID.fullmatch(str(artifact_id))
        if not match or offset < 0 or not 1 <= max_bytes <= MAX_INLINE:
            raise ValueError("Ürün ID'si veya okuma aralığı geçersiz")
        ledger = json.loads(ledger_path_for(self.queue_dir, match[1]).read_text(encoding="utf-8"))
        items = ledger["artifacts"]
        index = int(match[2])
        if index >= len(items):
            raise ValueError("Ürün ID'si mevcut değil")
        record = items[index]
        path = self._inside(record["path"])
        # Hash'i hesaplamak ve blokları okumak için aynı salt okunur dosya tanıtıcısını kullan;
        # doğrulamadan sonra ayrı dosya açmanın yol yarışına yol açmasını önler.
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
            if digest.hexdigest() != record["sha256"] or size != record["sizeBytes"]:
                raise ValueError("Ürün içeriği değişti; lütfen teslim incelemesini yeniden çalıştırın")
            if offset > size:
                raise ValueError("Okuma kaydırması dosya boyutunu aşıyor")
            stream.seek(offset)
            data = stream.read(max_bytes)
        return path, data, {"sha256": record["sha256"], "total_bytes": size, "offset": offset,
            "next_offset": offset + len(data) if offset + len(data) < size else None}
