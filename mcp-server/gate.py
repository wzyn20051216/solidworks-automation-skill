"""Keşif modu ile yerel doğrudan çağrının paylaştığı tek ağ geçidi.

FastMCP'nin ``list_tools`` / ``call_tool`` metotları çağrı anında ``self._tool_manager``
okur; bu nedenle kayıt defterini bu vekille değiştirmek hem stdio hem streamable-http
üzerinde geçerli olur ve "istemcinin gizlenen yerel aracı doğrudan adıyla çağırması"
biçimindeki atlama yolunu da kapatır.
"""
from __future__ import annotations

import logging
import json
import secrets
import threading
import weakref
from contextlib import nullcontext
from typing import Any, Sequence

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ClientCapabilities, ElicitationCapability, Tool as MCPTool
from pydantic import BaseModel

import policy
from approval import ApprovalError, ApprovalLedger
from discovery import ToolCatalog
from document_identity import DocumentIdentity, DocumentIdentityError, bind_document

logger = logging.getLogger("solidworks_mcp.gate")

DISCOVERY_TOOLS = ("sw_search_tools", "sw_describe_tool", "sw_call_tool")

MODES = ("full", "search")
APPROVAL_MODES = ("auto", "task", "server", "client", "elicit", "off")
_EXTERNAL_APPROVAL_MODES = ("task", "client", "off")


class _Confirm(BaseModel):
    approve: bool


class ToolGate:
    """Kayıt defteri vekili: görünürlüğü denetler ve yürütmeden önce Policy ile onayı tek yerden uygular."""

    def __init__(self, manager: Any, *, mode: str = "search", approval_mode: str = "auto",
                 ledger: ApprovalLedger | None = None):
        if mode not in MODES:
            raise ValueError(f"SW_MCP_DISCOVERY yalnızca {'/'.join(MODES)} olabilir; alınan değer {mode!r}")
        if approval_mode not in APPROVAL_MODES:
            raise ValueError(f"SW_MCP_APPROVAL yalnızca {'/'.join(APPROVAL_MODES)} olabilir; alınan değer {approval_mode!r}")
        if mode == "search" and approval_mode == "client":
            raise ValueError("Keşif modu client onayını kullanamaz: istemci yalnızca genel girişleri görür ve özgün araç başına onay veremez.")
        self._manager = manager
        self.mode = mode
        self.approval_mode = "task" if (approval_mode == "auto" and mode == "search") else (
            "client" if approval_mode == "auto" else approval_mode)
        # Araç kaydı, paketleme ve salt okunur çağrılar kullanıcı dizininde onay defteri oluşturmamalıdır.
        self._ledger = ledger
        self._catalog: ToolCatalog | None = None
        self._catalog_size = -1
        self._internal_subject = secrets.token_hex(16)
        self._subjects: weakref.WeakKeyDictionary[Any, str] = weakref.WeakKeyDictionary()
        self._subjects_lock = threading.Lock()

    @property
    def ledger(self) -> ApprovalLedger:
        if self._ledger is None:
            self._ledger = ApprovalLedger()
        return self._ledger

    def _subject(self, context: Any) -> str:
        """Modelin ilettiği istemci kimliğine güvenmek yerine sunucu tarafı oturuma bağlar."""
        if context is None:
            return self._internal_subject
        try:
            session = context.session
            with self._subjects_lock:
                subject = self._subjects.get(session)
                if subject is None:
                    subject = secrets.token_hex(16)
                    self._subjects[session] = subject
                return subject
        except (AttributeError, TypeError, ValueError) as exc:
            raise ToolError("Onay, geçerli istemci oturumuna bağlanamadı; yürütme reddedildi.") from exc

    # ------------------------------------------------------------ Kayıt defteri vekili
    @property
    def _tools(self) -> dict[str, Any]:
        """Paketleme betiği tam kayıt defterini okumalıdır; keşif modu yayın ürününü etkilememelidir."""
        return self._manager._tools

    def add_tool(self, *args: Any, **kwargs: Any) -> Any:
        tool = self._manager.add_tool(*args, **kwargs)
        self._catalog = None
        return tool

    def remove_tool(self, name: str) -> Any:
        self._catalog = None
        return self._manager.remove_tool(name)

    def get_tool(self, name: str) -> Any:
        return self._manager.get_tool(name)

    def list_tools(self) -> list[Any]:
        tools = self._manager.list_tools()
        if self.mode == "full":
            return [tool for tool in tools if tool.name not in DISCOVERY_TOOLS]
        return [tool for tool in tools if tool.name in DISCOVERY_TOOLS]

    # ------------------------------------------------------------ Arama
    def catalog(self) -> ToolCatalog:
        tools = [tool for tool in self._manager.list_tools() if tool.name not in DISCOVERY_TOOLS]
        if self._catalog is None or len(tools) != self._catalog_size:
            self._catalog = ToolCatalog(
                [MCPTool(name=tool.name, title=tool.title, description=tool.description,
                         inputSchema=tool.parameters, outputSchema=tool.output_schema,
                         annotations=tool.annotations, icons=tool.icons,
                         _meta=tool.meta).model_dump(by_alias=True, exclude_none=True)
                 for tool in tools],
                read_names={tool.name for tool in tools
                            if policy.classify(tool.name)[0] is policy.Effect.READ},
            )
            self._catalog_size = len(tools)
        return self._catalog

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        results = self.catalog().search(query, limit)
        for item in results:
            effect, _ = policy.classify(item["name"])
            item["effect"] = effect.value
            blocked = self._blocked_reason(item["name"])
            item["available"] = blocked is None
            if (self.approval_mode not in _EXTERNAL_APPROVAL_MODES
                    and policy.supports_document_identity(item["name"])):
                item["document_target_required"] = True
            if blocked:
                item["blocked_reason"] = blocked
        return results

    def describe(self, name: str) -> dict[str, Any] | None:
        tool = self.catalog().describe(name)
        if tool is None:
            return None
        view = {key: tool[key] for key in ("name", "title", "description", "inputSchema", "outputSchema", "annotations", "icons", "_meta") if key in tool}
        effect, note = policy.classify(name)
        view["effect"] = effect.value
        view["approval_required"] = (policy.requires_approval(effect)
                                     and self.approval_mode not in _EXTERNAL_APPROVAL_MODES)
        view["approval_mode"] = self.approval_mode
        if (self.approval_mode not in _EXTERNAL_APPROVAL_MODES
                and policy.supports_document_identity(name)):
            view["document_target_required"] = True
            view["document_target_note"] = "sw_call_tool üzerinden kayıtlı belgenin mutlak yolunu ve SolidWorks süreç ID'sini sağlayın."
        if note:
            view["policy_note"] = note
        blocked = self._blocked_reason(name)
        view["available"] = blocked is None
        if blocked:
            view["blocked_reason"] = blocked
        return view

    def _blocked_reason(self, name: str) -> str | None:
        if (self.approval_mode not in _EXTERNAL_APPROVAL_MODES
                and policy.needs_active_document_identity(name)
                and not policy.supports_document_identity(name)):
            return (
                f"Engellendi: {name} SolidWorks etkin belgesine bağlıdır; mevcut sunucu tarafı onayı belge kimliğini bağlayıp doğrulayamaz. "
                "Güvenilir araç başına onaya sahip yerel modu kullanın veya belge kimliği bağlama özelliğini bekleyin."
            )
        return None

    # ------------------------------------------------------------ Yürütme
    async def call_tool(self, name: str, arguments: dict[str, Any] | None,
                        context: Any = None, convert_result: bool = False,
                        document_target: dict[str, Any] | None = None) -> Any:
        arguments = arguments or {}
        if name in DISCOVERY_TOOLS:
            return await self._manager.call_tool(name, arguments, context=context, convert_result=convert_result)

        effect, note = policy.classify(name, arguments)
        if effect is policy.Effect.UNKNOWN:
            raise ToolError(
                f"Araç {name} için yan etki düzeyi kayıtlı değil; sunucu yürütmeyi reddetti. "
                "Yayınlamadan önce mcp-server/policy.py içinde sınıflandırmayı ekleyin."
            )

        blocked = self._blocked_reason(name)
        if blocked:
            raise ToolError(blocked)

        identity = None
        approval_arguments: dict[str, Any] = arguments
        if document_target is not None and policy.needs_active_document_identity(name) and not policy.supports_document_identity(name):
            raise ToolError(f"{name} henüz document_target doğrulamasını desteklemiyor; bu hedef parametresi kullanılamaz.")
        if (policy.supports_document_identity(name)
                and (self.approval_mode not in _EXTERNAL_APPROVAL_MODES or document_target is not None)):
            if not isinstance(document_target, dict) or set(document_target) != {"process_id", "path"}:
                raise ToolError("Bu işlem document_target gerektirir: kayıtlı belgenin mutlak yolu path ve SolidWorks süreç ID'si process_id.")
            try:
                identity = DocumentIdentity.create(document_target["process_id"], document_target["path"])
            except DocumentIdentityError as exc:
                raise ToolError(str(exc)) from exc
            approval_arguments = {"arguments": arguments, "document_target": {
                "process_id": identity.process_id, "path": identity.path,
            }}

        if policy.requires_approval(effect) and self.approval_mode not in _EXTERNAL_APPROVAL_MODES:
            subject = self._subject(context)
            allowed = await self._authorize(name, approval_arguments, effect, note, context, subject)
            if not allowed:
                raise ToolError(allowed_reason(self.ledger, name, approval_arguments, effect, subject))

        with bind_document(identity) if identity else nullcontext():
            return await self._manager.call_tool(name, arguments, context=context, convert_result=convert_result)

    async def _authorize(self, name: str, arguments: dict[str, Any], effect: policy.Effect,
                         note: str, context: Any, subject: str) -> bool:
        if self.ledger.consume(name, arguments, subject=subject) is not None:
            return True
        if self.approval_mode == "elicit":
            return await self._confirm_via_client(name, arguments, effect, note, context)
        return False

    async def _confirm_via_client(self, name: str, arguments: dict[str, Any], effect: policy.Effect,
                                  note: str, context: Any) -> bool:
        """MCP kullanıcı etkileşimiyle onay alır; istemci desteklemiyorsa onaylanmamış sayılır."""
        if context is None:
            return False
        try:
            capabilities = context.session.check_client_capability(
                ClientCapabilities(elicitation=ElicitationCapability(form=None)))
        except Exception:
            return False
        if not capabilities:
            return False
        # Kullanıcının tam parametreleri görmeden bir işlemi onaylamasına izin verilmemelidir.
        # Etkileşim mesajının güvenli sınırı aşılırsa sessizce kırpmak yerine bant dışı onaya geçilir
        # ve tam parametreler onay tarafında gösterilir.
        parameters = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        if len(parameters) > 4000:
            logger.warning("Onay parametreleri çok uzun; elicitation ile tam olarak gösterilemez")
            return False
        targets = policy.targets(arguments)
        message = (
            f"SolidWorks MCP bir yazma işlemi yürütmek istiyor.\nAraç: {name}\nDüzey: {effect.value}\n"
            f"Parametreler: {parameters}"
            + (f"\nHedefler: {', '.join(targets)}" if targets else "")
            + (f"\nNot: {note}" if note else "")
        )
        try:
            result = await context.elicit(message=message, schema=_Confirm)
        except Exception as exc:  # İstemci çalışma sırasında etkileşimi reddedebilir
            logger.warning("elicitation başarısız: %s", exc)
            return False
        return result.action == "accept" and bool(result.data.approve)


def allowed_reason(ledger: ApprovalLedger, name: str, arguments: dict[str, Any],
                   effect: policy.Effect, subject: str | None = None) -> str:
    """Onaylanmadığında modele döndürülen engelleme açıklaması; yürütülebilir insan onayı adımlarını içerir."""
    try:
        request = ledger.request(name, arguments, effect.value, subject=subject)
        request_id = request["id"]
        detail = f"Onay isteği {request_id} ({int(request['expires_at'] - request['created_at'])} saniye geçerli)"
    except ApprovalError as exc:  # Defter yazılamıyorsa yalnızca "onay bekliyor" gibi davranılamaz
        return f"Araç {name} insan onayı gerektiriyor, ancak onay defteri kullanılamıyor: {exc}"
    return (
        f"Engellendi: {name} bir {effect.value} işlemidir; yalnızca insan onayından sonra yürütülür.\n"
        f"{detail}\n"
        f"MCP sunucusunun bulunduğu makinede kurulum dizininde bir terminal açıp şunu çalıştırın: python scripts/sw_mcp_approve.py approve {request_id}\n"
        f"Ardından tamamen aynı parametrelerle yeniden deneyin; parametreler değişirse önceki onay geçersiz olur."
    )
