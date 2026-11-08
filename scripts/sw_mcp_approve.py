"""SolidWorks MCP yazma işlemlerinin insan tarafından onaylanması.

Kullanım::

    python scripts/sw_mcp_approve.py list
    python scripts/sw_mcp_approve.py approve 1a2b3c4d
    python scripts/sw_mcp_approve.py deny 1a2b3c4d

MCP çağrı parametrelerindeki ``approved=true`` bir onay kaydı oluşturmaz. Etkileşimli terminal denetimi yalnızca
sıradan boru hattı yanlış kullanımını önler; girdinin bir insandan geldiğini kanıtlayamaz. Aynı işletim sistemi kullanıcısıyla kod çalıştırabilen süreçler
yerel deftere erişebilir veya terminali taklit edebilir; bu mekanizma bu tür süreçleri yalıtamaz.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))

from approval import ApprovalError, ApprovalLedger, default_root  # noqa: E402


def _format_time(timestamp: float | None) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _show_list(ledger: ApprovalLedger) -> int:
    print(f"Onay kayıt dizini: {ledger.root}")
    pending = ledger.pending()
    if pending:
        print("\nOnay bekleyen:")
        for item in pending:
            remaining = max(0, int(item["expires_at"] - time.time()) // 60)
            print(f"  [{item['id']}] {item['tool']} ({item['effect']}, kalan {remaining} dakika)")
            print(f"        Parametreler: {item['summary'][:300]}")
            if item.get("targets"):
                print(f"        Hedefler: {', '.join(item['targets'])}")
    else:
        print("\nOnay bekleyen: yok")

    decisions = ledger.decisions(5)
    if decisions:
        print("\nSon kararlar:")
        for item in decisions:
            print(f"  [{item['id']}] {item['status']} {item['tool']} @ {_format_time(item.get('decided_at'))}")
    return 0


def _confirm(prompt: str) -> bool:
    """Etkileşimli girdi gerektirir; TTY tek başına girdinin insandan geldiğini kanıtlamaz."""
    if not sys.stdin.isatty():
        print("Reddedildi: onay etkileşimli bir terminalde insan tarafından verilmelidir (geçerli standart girdi terminal değil).", file=sys.stderr)
        return False
    try:
        answer = input(f"{prompt} onaylamak için yes yazın: ")
    except (EOFError, KeyboardInterrupt):
        # Windows'un NUL aygıtı da isatty() için doğru döndürür; girdi okunamayan durum yakalanmalıdır.
        print("\nReddedildi: insan onayı alınamadı.", file=sys.stderr)
        return False
    return answer.strip().lower() == "yes"


def _show_request(ledger: ApprovalLedger, request_id: str) -> dict:
    record = ledger.request_record(request_id)
    print(f"Araç: {record['tool']}  Düzey: {record['effect']}  İstek: {request_id}")
    print(f"Parametreler: {record['summary']}")
    if record.get("targets"):
        print(f"Hedefler: {', '.join(record['targets'])}")
    return record


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="SolidWorks MCP yazma işlemlerini insan tarafından onaylar")
    parser.add_argument("--dir", default=None, help="Onay kayıt dizini (varsayılan: SW_MCP_APPROVAL_DIR)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Onay bekleyen istekleri ve son kararları listeler")

    approve = sub.add_parser("approve", help="Bekleyen bir isteği onaylar")
    approve.add_argument("request_id")
    approve.add_argument("--ttl", type=int, default=None, help="Onay geçerlilik süresi (saniye)")

    deny = sub.add_parser("deny", help="Bekleyen bir isteği reddeder")
    deny.add_argument("request_id")

    scope = sub.add_parser("scope", help="Kapsam yetkilendirmesi devre dışı (yalnızca komut uyumluluğu için korunur)")
    scope.add_argument("--tool", action="append", required=True, help="Araç adı, yinelenebilir; * tüm yazma araçlarını belirtir")
    scope.add_argument("--path", action="append", default=[], help="İzin verilen dizin öneki, yinelenebilir; atlanırsa dizin sınırı yok")
    scope.add_argument("--ttl", type=int, default=None, help="Geçerlilik süresi (saniye)")
    scope.add_argument("--uses", type=int, default=None, help="En fazla kullanım sayısı; atlanırsa sınırsız")

    args = parser.parse_args(argv)
    ledger = ApprovalLedger(args.dir or default_root())
    command = args.command or "list"

    try:
        if command == "list":
            return _show_list(ledger)
        if command == "approve":
            record = _show_request(ledger, args.request_id)
            if not _confirm(f"{record['tool']} aracının bu çağrısı onaylansın mı?"):
                return 1
            grant = ledger.approve(args.request_id, args.ttl, expected_record=record)
            print(f"Onaylandı, geçerlilik {_format_time(grant['expires_at'])} tarihine kadar; yalnızca bu çağrı için geçerli.")
            return 0
        if command == "deny":
            _show_request(ledger, args.request_id)
            if not _confirm("Bu çağrı reddedilsin mi?"):
                return 1
            ledger.deny(args.request_id)
            print("Reddedildi.")
            return 0
        if command == "scope":
            raise ApprovalError("Kapsam yetkilendirmesi devre dışı; lütfen her somut çağrıyı tek tek onaylayın.")
    except ApprovalError as exc:
        print(f"Başarısız: {exc}", file=sys.stderr)
        return 1
    parser.error(f"Bilinmeyen komut: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
