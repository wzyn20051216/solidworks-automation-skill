"""Yazma işlemleri için yerel onay kaydı; modelin ilettiği araç parametreleri doğrudan onay oluşturamaz.

Yalnızca çağrı başına onay desteklenir: araç adına, tam parametre özetine ve çağıranın kimliğine bağlanır; tek kullanımlık ve geçerlilik sürelidir.
Kapsam yetkilendirmesi henüz desteklenmez; mevcut kapsam kayıtları da tüketilmez.

Kalıcı biçim yerel dizindeki JSON'dur; imza anahtarı aynı dizinde üretilir. CLI etkileşimli onay sunar,
ancak terminal kontrolü girdinin bir insandan geldiğini kanıtlayamaz; aynı OS kullanıcı izinlerine sahip programlar defteri ve anahtarı okuyup yazabilir,
HMAC bu programları yalıtmaz. Dağıtımcı defter dizinini ve yürütme ortamını korumalıdır; bu mekanizmayla eşit yerel izinlere sahip kötü niyetli süreçlerin onay taklit etmesinin engellendiği iddia edilemez. Araç parametrelerindeki ``approved=true`` etkisizdir.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from policy import Effect, canonical_digest, classify, targets

DEFAULT_CALL_TTL_SECONDS = 15 * 60
MAX_APPROVAL_ARGUMENT_BYTES = 64 * 1024
# Geçmiş kayıtlar otomatik silinmez; kapasite dolduğunda ekleme durur ve kullanıcıdan kendi arşivlemesi istenir.
MAX_APPROVAL_REQUEST_RECORDS = 1000
MAX_APPROVAL_GRANT_RECORDS = 1000

# İstek ID'si token_hex(4) ile üretilir; biçim doğrulaması ../ gibi yol enjeksiyonlarını da engeller.
_REQUEST_ID = re.compile(r"[0-9a-f]{8}")


def default_root() -> Path:
    """Onay kayıtları dizini; kullanıcı veri alanında tutulur, depoya girmez ve kurulum paketiyle dağıtılmaz."""
    override = os.environ.get("SW_MCP_APPROVAL_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "SolidWorksMCP" / "approvals"


class ApprovalError(RuntimeError):
    """Onay kaydı geçersiz, süresi dolmuş veya zaten kullanılmış."""


def _locked(method):
    """Defterin okunmasını, doğrulanmasını ve güncellenmesini süreçler arası korur."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock():
            return method(self, *args, **kwargs)
    return wrapper


class ApprovalLedger:
    """Onay istekleri ve onay kayıtları için yerel defter."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_root()
        self.requests_dir = self.root / "requests"
        self.grants_dir = self.root / "grants"
        for path in (self.root, self.requests_dir, self.grants_dir):
            path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _lock(self):
        # Bağımsız dosya tanıtıcısı, kilidin diğer iş parçacıklarını ve diğer servis süreçlerini kapsamasını sağlar; çökme durumunda OS serbest bırakır.
        with (self.root / '.lock').open('a+b') as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise ApprovalError('Onay defteri kilidi zaman aşımına uğradı, yürütme reddedildi.') from exc
                    time.sleep(0.01)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------------ Anahtar
    def _secret(self) -> bytes:
        path = self.root / "secret.key"
        if not path.exists():
            path.write_bytes(secrets.token_bytes(32))
            try:
                path.chmod(0o600)
            except OSError:  # pragma: no cover - Windows ACL kullanıcı dizininden devralınır
                pass
        return path.read_bytes()

    def _sign(self, body: dict[str, Any]) -> str:
        payload = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret(), payload, hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ İstek
    @_locked
    def request(self, tool: str, arguments: Any, effect: str, *, subject: str | None = None) -> dict[str, Any]:
        """Onay bekleyen bir çağrıyı kaydeder; aynı araç ve aynı parametreyle tekrarlanan istek özgün id'yi yeniden kullanır."""
        summary = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        if len(summary.encode('utf-8')) > MAX_APPROVAL_ARGUMENT_BYTES:
            raise ApprovalError('İşlem parametreleri onay gösterim sınırını aşıyor, yürütme reddedildi.')
        digest = canonical_digest(tool, arguments)
        for existing in self.pending():
            if existing["tool"] == tool and existing["digest"] == digest and existing.get("subject") == subject:
                return existing
        if sum(1 for _ in self.requests_dir.glob("*.json")) >= MAX_APPROVAL_REQUEST_RECORDS:
            raise ApprovalError("Onay isteği kayıtları kapasite sınırına ulaştı; lütfen eski kayıtları güvenli bir konumda arşivledikten sonra yeniden deneyin.")
        # Kısa ID'ler çakışabilir; var olan bir isteğin veya eski bir yetkinin üzerine yazılmamalıdır.
        request_id = None
        for _ in range(32):
            candidate = secrets.token_hex(4)
            if not (self.requests_dir / f"{candidate}.json").exists() and not (self.grants_dir / f"{candidate}.json").exists():
                request_id = candidate
                break
        if request_id is None:
            raise ApprovalError("Benzersiz bir onay isteği ID'si üretilemedi, istek oluşturma reddedildi.")
        now = time.time()
        record = {
            "id": request_id,
            "kind": "call",
            "tool": tool,
            "subject": subject,
            "effect": effect,
            "digest": digest,
            "summary": summary,
            "targets": targets(arguments),
            "created_at": now,
            "expires_at": now + DEFAULT_CALL_TTL_SECONDS,
            "status": "pending",
        }
        self._write(self.requests_dir / f"{record['id']}.json", record)
        return record

    def pending(self) -> list[dict[str, Any]]:
        """Süresi dolmamış ve hâlâ insan kararını bekleyen istekler."""
        now = time.time()
        items = []
        for path in sorted(self.requests_dir.glob("*.json")):
            record = self._read(path)
            if record.get("status") == "pending" and record.get("expires_at", 0) > now:
                items.append(record)
        return items

    def decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        """En son insan kararları; kullanıcının neleri onayladığını doğrulamasını kolaylaştırır."""
        items = [self._read(path) for path in self.requests_dir.glob("*.json")]
        decided = [item for item in items if item.get("status") in {"approved", "denied"}]
        decided.sort(key=lambda item: item.get("decided_at") or 0, reverse=True)
        return decided[:limit]

    # ------------------------------------------------------------------ İnsan kararı
    def _request_path(self, request_id: str) -> Path:
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise ApprovalError(f"Geçersiz istek ID'si: {request_id!r}")
        return self.requests_dir / f"{request_id}.json"

    def request_record(self, request_id: str) -> dict[str, Any]:
        """İstek ayrıntılarını ID ile okur; ID biçimi geçersizse ApprovalError verir."""
        return self._read(self._request_path(request_id))

    @_locked
    def approve(self, request_id: str, ttl_seconds: int | None = None, *,
                expected_record: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bekleyen bir isteği tek kullanımlık bir call onay kaydına dönüştürür."""
        record = self.request_record(request_id)
        if expected_record is not None and record != expected_record:
            raise ApprovalError(f"İstek {request_id} gösterimden sonra değişti, onay reddedildi.")
        try:
            displayed_arguments = json.loads(record["summary"])
            matches_display = (
                record["digest"] == canonical_digest(record["tool"], displayed_arguments)
                and record.get("targets", []) == targets(displayed_arguments)
            )
        except (KeyError, TypeError, ValueError):
            matches_display = False
        if not matches_display:
            raise ApprovalError(f"İstek {request_id} için parametre özeti ile yürütme içeriği uyuşmuyor, onay reddedildi.")
        effect, _ = classify(record["tool"], displayed_arguments)
        if effect not in (Effect.WRITE, Effect.DESTRUCTIVE) or record.get("effect") != effect.value:
            raise ApprovalError(f"İstek {request_id} için yan etki düzeyi geçerli politikayla uyuşmuyor, onay reddedildi.")
        if record.get("status") != "pending":
            raise ApprovalError(f"İstek {request_id} şu anki durumu {record.get('status')}, onaylanamaz.")
        if record.get("expires_at", 0) <= time.time():
            raise ApprovalError(f"İstek {request_id} süresi dolmuş; aracı yeniden çağırarak yeni bir istek oluşturabilirsiniz.")
        # Kapasite kontrolü kilit içinde ve istek durumu değiştirilmeden önce yapılmalıdır; aksi halde onaydan sonra yetki verilemeyebilir.
        if sum(1 for _ in self.grants_dir.glob("*.json")) >= MAX_APPROVAL_GRANT_RECORDS:
            raise ApprovalError("Onay yetki kayıtları kapasite sınırına ulaştı; lütfen eski kayıtları güvenli bir konumda arşivledikten sonra yeniden deneyin.")
        record.update({"status": "approved", "decided_at": time.time()})
        self._write(self.requests_dir / f"{request_id}.json", record)

        body = {
            "kind": "call",
            "id": request_id,
            "tool": record["tool"],
            "subject": record.get("subject"),
            "digest": record["digest"],
            "targets": record.get("targets", []),
            "expires_at": time.time() + (ttl_seconds or DEFAULT_CALL_TTL_SECONDS),
            "max_uses": 1,
            "used": 0,
        }
        return self._issue(body)

    @_locked
    def deny(self, request_id: str) -> dict[str, Any]:
        record = self.request_record(request_id)
        if record.get("status") != "pending":
            raise ApprovalError(f"İstek {request_id} şu anki durumu {record.get('status')}, reddedilemez.")
        record.update({"status": "denied", "decided_at": time.time()})
        return self._write(self.requests_dir / f"{request_id}.json", record)

    @_locked
    def grant_scope(self, tools: list[str], paths: list[str], ttl_seconds: int | None = None,
                    max_uses: int | None = None) -> dict[str, Any]:
        """Bir grup aracın belirli bir süre için yazma kapsamını onaylar."""
        raise ApprovalError("Kapsam yetkilendirmesi devre dışı bırakıldı; lütfen her çağrıyı tek tek inceleyip onaylayın.")

    # ------------------------------------------------------------------ Doğrulama
    @_locked
    def consume(self, tool: str, arguments: Any, *, subject: str | None = None) -> dict[str, Any] | None:
        """Bu çağrıyı kapsayan onay kaydını bulur; tek kullanımlık kayıtlar doğrulama geçince hemen tüketilir."""
        digest = canonical_digest(tool, arguments)
        call_hit = None
        for grant in self._grants():
            if (grant["kind"] != "call" or grant["tool"] != tool
                    or grant["digest"] != digest or grant.get("subject") != subject):
                continue
            call_hit = grant
            break
        if call_hit is not None:
            self._consume(call_hit)
            return call_hit

        # Eski kapsam yetkileri de geçerli olmamalıdır: araç örtük etkin belgeyi değiştirebilir veya harici dosyalara başvurabilir.
        return None

    def _scope_covers(self, grant: dict[str, Any], tool: str, tool_targets: list[str]) -> bool:
        allowed = grant.get("tools") or []
        if "*" not in allowed and tool not in allowed:
            return False
        if tool not in allowed and "*" in allowed:
            # * "tüm yazma araçları" anlamına gelir, ancak yıkıcı işlemler tek tek adlandırılmalıdır; hepsini birden açmaktan kaçının.
            if classify(tool)[0] is Effect.DESTRUCTIVE:
                return False
        try:
            prefixes = [_normalize_path(item) for item in grant.get("paths") or []]
        except (OSError, ValueError):
            return False
        if not prefixes:
            return True
        if not tool_targets:
            return False
        try:
            normalized_targets = [_normalize_path(target) for target in tool_targets]
        except (OSError, ValueError):
            return False
        return all(
            any(_within(target, prefix) for prefix in prefixes)
            for target in normalized_targets
        )

    def _grants(self) -> list[dict[str, Any]]:
        now = time.time()
        valid = []
        for path in sorted(self.grants_dir.glob("*.json")):
            grant = self._read(path)
            if grant.get("expires_at", 0) <= now:
                continue
            if grant.get("max_uses") is not None and grant.get("used", 0) >= grant["max_uses"]:
                continue
            if not hmac.compare_digest(self._sign(_unsigned(grant)), grant.get("signature", "")):
                continue
            valid.append(grant)
        return valid

    def _consume(self, grant: dict[str, Any]) -> None:
        grant["used"] = grant.get("used", 0) + 1
        grant["used_at"] = time.time()
        self._write(self.grants_dir / f"{grant['id']}.json", self._sign_record(grant))

    # ------------------------------------------------------------------ Depolama
    def _issue(self, body: dict[str, Any]) -> dict[str, Any]:
        record = self._sign_record(body)
        self._write(self.grants_dir / f"{body['id']}.json", record)
        return record

    def _sign_record(self, body: dict[str, Any]) -> dict[str, Any]:
        record = dict(body)
        record["signature"] = self._sign(_unsigned(record))
        return record

    @staticmethod
    def _write(path: Path, record: dict[str, Any]) -> dict[str, Any]:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return record

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ApprovalError(f"Onay kaydı bulunamadı: {path.name}") from exc
        except json.JSONDecodeError as exc:
            raise ApprovalError(f"Onay kaydı bozulmuş: {path.name}") from exc


def _unsigned(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "signature"}


def _normalize_path(value: Any) -> str:
    path = Path(str(value))
    if not path.is_absolute():
        raise ValueError('Onay kapsamı ve hedefi mutlak yol olmalıdır')
    return os.path.normcase(str(path.resolve(strict=False)))


def _within(target: str, prefix: str) -> bool:
    """Yol segmentine göre eşleştirir; D:/work'ün yanlışlıkla D:/workshop'u kapsamasını önler."""
    try:
        return os.path.commonpath((target, prefix)) == prefix
    except ValueError:
        return False
