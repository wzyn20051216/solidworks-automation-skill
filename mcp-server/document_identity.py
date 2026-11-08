"""Etkin belge hedefinin açık bağlanması ve doğrulanması; COM okumaktan veya kullanıcı işlemini onaylamaktan sorumlu değildir.

PID ve normalleştirilmiş kayıtlı belge yolu, yürütme hedefini belirlemek için kullanılır;
belge içeriğinin değişmediğini kanıtlamaz ve aynı sistem kullanıcısının süreçlerine karşı
güvenlik yalıtımı sağlamaz. Çağıran, gerçek PID ile etkin belge yolunu CAD işlem kilidi
içinde almalı ve doğrulamadan sonra aynı model nesnesiyle işlemi yürütmelidir.
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class DocumentIdentityError(ValueError):
    """Hedef geçersiz, bağlanmamış veya gerçek etkin belgeyle uyuşmuyor."""


def _path(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise DocumentIdentityError("Belge yolu geçerli, boş olmayan mutlak bir yol olmalıdır.")
    if any(character in value for character in ("*", "?")):
        raise DocumentIdentityError("Belge yolu joker karakter içeremez.")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise DocumentIdentityError("Belge yolu mutlak olmalıdır; kaydedilmemiş belgeler bu doğrulamayı kullanamaz.")
    if candidate.suffix.lower() not in {".sldprt", ".sldasm", ".slddrw"}:
        raise DocumentIdentityError("Hedef, kayıtlı bir SolidWorks yerel belge yolu olmalıdır.")
    try:
        return os.path.normcase(str(candidate.resolve(strict=False)))
    except (OSError, RuntimeError, ValueError) as exc:
        raise DocumentIdentityError("Belge yolu normalleştirilemedi.") from exc


def _pid(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DocumentIdentityError("SolidWorks süreç ID'si pozitif bir tam sayı olmalıdır.")
    return value


@dataclass(frozen=True)
class DocumentIdentity:
    """Onaya bağlanan SolidWorks süreci ve kayıtlı belge yolu."""

    process_id: int
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "process_id", _pid(self.process_id))
        object.__setattr__(self, "path", _path(self.path))

    @classmethod
    def create(cls, process_id: object, path: object) -> DocumentIdentity:
        return cls(process_id, path)  # type: ignore[arg-type]

    def verify(self, process_id: object, path: object) -> None:
        """Gerçek etkin belgeyi denetler; çağıran, alınan model nesnesini yürütme kilidi içinde hemen kullanmalıdır."""
        if _pid(process_id) != self.process_id:
            raise DocumentIdentityError("SolidWorks süreci, onay sırasındaki hedefle uyuşmuyor.")
        if _path(path) != self.path:
            raise DocumentIdentityError("Etkin belge, onay sırasındaki hedefle uyuşmuyor.")


_target: contextvars.ContextVar[DocumentIdentity | None] = contextvars.ContextVar(
    "solidworks_approved_document_identity", default=None
)


@contextmanager
def bind_document(identity: DocumentIdentity) -> Iterator[None]:
    """Onaylanan hedefi bu çağrı bağlamına bağlar; çıkışta üst bağlamı geri yükler."""
    if not isinstance(identity, DocumentIdentity):
        raise DocumentIdentityError("Geçerli bir onaylı belge kimliği eksik.")
    token = _target.set(identity)
    try:
        yield
    finally:
        _target.reset(token)


def verify_bound_document(process_id: object, path: object) -> None:
    """Geçerli çağrıya bağlanan hedefi doğrular; bağlama yoksa güvenli biçimde başarısız olur."""
    identity = _target.get()
    if identity is None:
        raise DocumentIdentityError("Bu çağrıda onaylı bir belge kimliği bağlı değil.")
    identity.verify(process_id, path)


def has_bound_document() -> bool:
    """Tam modla uyumluluk: hedef doğrulamayı yalnızca sunucu tarafı onay çağrılarında zorunlu kılar."""
    return _target.get() is not None
