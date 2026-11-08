"""Kayıtlı MCP araçlarını gerçek yan etkilerine göre sınıflandırır; keşif modu ile yerel doğrudan çağrı bu tek ölçütü paylaşır.

Sınıflandırma yalnızca annotations'a bakılarak değil, her araç için elle doğrulanmalıdır; örneğin
``solidworks_document_units`` annotasyonu salt okunurdur, ancak aynı çağrıda belge birimlerini değiştirebilir;
``solidworks_review_active`` "inceleme" gibi görünür, oysa önizleme ve raporları diske yazar.
Kayıtlı olmayan araçlar her zaman UNKNOWN olur ve reddedilir; bu da yeni araçların önce sınıflandırma eklemesini zorlar.
"""
from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Iterable


class Effect(str, Enum):
    """Araç çağrısının model, dosya veya harici süreç üzerindeki gerçek etkisi."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


_READ: frozenset[str] = frozenset({
    "cadstudio_resolve_backend",
    "cadstudio_list_drc_rules",
    "cadstudio_routing_preflight",
    "cadstudio_fea_preflight",
    "cadstudio_read_artifact",
    "solidworks_addin_host_status",
    "solidworks_health_check",
    "solidworks_lookup_api",
    "solidworks_list_edges",
    "solidworks_mass_properties",
    "solidworks_bounding_box",
    "solidworks_interference_check",
    "solidworks_inspect_configurations",
    "solidworks_inspect_hole_features",
    "solidworks_inspect_motion_studies",
    "solidworks_validate_motion_study",
    "solidworks_inspect_native_geometry",
    "design_spec_validate",
})

_WRITE: frozenset[str] = frozenset({
    "solidworks_connect",
    "cadstudio_check_dfm",
    "cadstudio_check_drc",
    "cadstudio_check_routing",
    "cadstudio_review_advanced_geometry",
    "solidworks_inspect_drawing",
    "cadstudio_write_open_format",
    "cadstudio_build_dxf_preview_scene",
    "cadstudio_prepare_fea",
    "cadstudio_run_fea",
    "cadstudio_run_fea_convergence",
    "cadstudio_create_ocp_loft",
    "cadstudio_create_ocp_surface",
    "solidworks_recover",
    "solidworks_new_document",
    "solidworks_create_basic_part",
    "solidworks_sketch_and_extrude",
    "solidworks_revolve",
    "solidworks_fillet",
    "solidworks_chamfer",
    "solidworks_shell",
    "solidworks_pattern",
    "solidworks_mirror_feature",
    "solidworks_document_units",
    "design_spec_build",
    "solidworks_open_document",
    "solidworks_add_component",
    "solidworks_set_component_fixed",
    "solidworks_save_document",
    "solidworks_add_coincident_mate",
    "solidworks_add_distance_mate",
    "solidworks_add_concentric_mate",
    "solidworks_set_appearance",
    "solidworks_export_active",
    "solidworks_create_configuration",
    "solidworks_activate_configuration",
    "solidworks_update_dimension",
    "solidworks_set_custom_properties",
    "solidworks_export_assembly_bom",
    "solidworks_review_active",
    "solidworks_generate_drawing",
    "solidworks_review_drawing",
    "solidworks_create_hole_feature",
    "solidworks_add_rotary_motor",
    "solidworks_build_round_sweeps",
    "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform",
    "solidworks_exclude_reviewed_bodies",
})

# Üzerine yazma veya toplu yazma: parametre yanlış yazılırsa kayıp "bir fazla özellik" değil, "üzerine yazılmış dosyalar" olur.
_DESTRUCTIVE: frozenset[str] = frozenset({
    "solidworks_close_documents",
    "solidworks_pack_and_go",
    "solidworks_batch_export_files",
})

_NOTES: dict[str, str] = {
    "solidworks_health_check": "start_solidworks=true olduğunda SolidWorks'ü başlatır veya bağlanır; onay gerektirir.",
    "solidworks_lookup_api": "Varsayılan olarak resmi belgeleri sorgular ve gerektiğinde bağımlılıkları yapılandırır; doğrudan okuma başarısız olup önbellek yoksa yalnızca genel API tanımlayıcısını ve sürümünü gönderen anonim Parallel kullanılır; offline=true veya auto_install=false kurulumu engeller.",
    "cadstudio_check_dfm": "İnceleme raporunu çıktı yoluna yazar.",
    "cadstudio_check_drc": "Tasarım kuralı inceleme raporunu çıktı yoluna yazar.",
    "cadstudio_check_routing": "İnceleme raporunu çıktı yoluna yazar.",
    "cadstudio_review_advanced_geometry": "Ön kontrol raporunu çıktı yoluna yazar.",
    "solidworks_inspect_drawing": "Teknik resim önizlemesi ve raporu üretir.",
    "solidworks_document_units": "Annotasyon salt okunur olarak işaretlidir, ancak aynı çağrı belge birimlerini değiştirebilir.",
    "solidworks_review_active": "Önizleme görüntüsünü ve inceleme raporunu diske yazar.",
    "solidworks_recover": "Engelleyici iletişim kutularını kapatır ve oturum durumunu sıfırlar.",
    "solidworks_connect": "Yeni bir SolidWorks süreci başlatabilir.",
    "solidworks_close_documents": "Tüm belgeleri kapatabilir; kaydedilmemiş değişiklikler kaybolur.",
    "solidworks_pack_and_go": "Hedef dizine toplu kopyalar; mevcut dosyaların üzerine yazabilir.",
    "solidworks_batch_export_files": "Toplu olarak diske yazar; mevcut çıktıların üzerine yazabilir.",
    "solidworks_run_fea": "Yerel bir çözücü süreci başlatır ve sonuç dosyalarını yazar.",
    "solidworks_run_fea_convergence": "Çözücüyü arka arkaya birçok kez başlatır.",
}

_EFFECTS: dict[str, Effect] = {
    **{name: Effect.READ for name in _READ},
    **{name: Effect.WRITE for name in _WRITE},
    **{name: Effect.DESTRUCTIVE for name in _DESTRUCTIVE},
}

# Bu araçlar yürütme sırasında etkin belgeyi okur; mevcut onay kaydı bu belge kimliğine bağlanamaz.
# Sunucu tarafı onay modunda, güvenilir bir belge kimliği anlık görüntüsü ve kilit altında yeniden doğrulama
# uygulanana kadar yürütme reddedilmelidir.
_ACTIVE_DOCUMENT_WRITES: frozenset[str] = frozenset({
    "solidworks_sketch_and_extrude", "solidworks_revolve", "solidworks_fillet",
    "solidworks_chamfer", "solidworks_shell", "solidworks_pattern", "solidworks_mirror_feature",
    "solidworks_document_units", "solidworks_add_component", "solidworks_set_component_fixed",
    "solidworks_save_document", "solidworks_close_documents", "solidworks_add_coincident_mate",
    "solidworks_add_distance_mate", "solidworks_add_concentric_mate", "solidworks_set_appearance",
    "solidworks_export_active", "solidworks_create_configuration", "solidworks_activate_configuration",
    "solidworks_update_dimension", "solidworks_set_custom_properties", "solidworks_export_assembly_bom",
    "solidworks_pack_and_go", "solidworks_review_active", "solidworks_create_hole_feature",
    "solidworks_add_rotary_motor", "solidworks_build_round_sweeps", "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform", "solidworks_exclude_reviewed_bodies",
})


def needs_active_document_identity(tool_name: str) -> bool:
    return tool_name in _ACTIVE_DOCUMENT_WRITES


_UNSUPPORTED_DOCUMENT_WRITES: frozenset[str] = frozenset({
    # Tüm belgeleri kapatmak, tam belge kümesinin bağlanmasını gerektirir. Yerel alt süreçler ayrıca PID ve giriş dosyası durumunun ayrı bağlanmasını gerektirir.
    "solidworks_close_documents", "solidworks_build_round_sweeps", "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform", "solidworks_exclude_reviewed_bodies",
    "solidworks_document_units", "solidworks_add_component", "solidworks_review_active",
    "solidworks_pack_and_go",
})


def supports_document_identity(tool_name: str) -> bool:
    return needs_active_document_identity(tool_name) and tool_name not in _UNSUPPORTED_DOCUMENT_WRITES

# Parametre adında bu parçaları içeren dize değerleri "diske yazma hedefi" sayılır; onay kapsamı buna göre bağlanır.
_PATH_HINT = re.compile(r"path|file|dir|output|target|destination", re.IGNORECASE)


def classify(tool_name: str, arguments: Any = None) -> tuple[Effect, str]:
    """Araç yan etkisi düzeyini ve gösterilebilir gerekçeyi döndürür."""
    # Sağlık kontrolü varsayılan olarak SolidWorks'ü başlatmaz, ancak parametreyle başlatma istenebilir; yalnızca araç adına bakarak izin verilemez.
    if tool_name == "solidworks_health_check" and isinstance(arguments, dict):
        params = arguments.get("params", {})
        if isinstance(params, dict) and params.get("start_solidworks") not in (None, False, 0):
            return Effect.WRITE, "Kontrol için SolidWorks'ü başlatma veya bağlanma isteği."
    if tool_name == "solidworks_lookup_api":
        params = arguments.get("params", {}) if isinstance(arguments, dict) else {}
        if not isinstance(params, dict):
            return Effect.UNKNOWN, "API doğrulama parametreleri geçersiz."
        if params.get("offline") is True or params.get("auto_install") is False:
            return Effect.READ, "Bu kez otomatik kurulum kapalı; doğrulama yerel kaynakları ve geçmiş önbelleği okuyabilir."
        return Effect.WRITE, _NOTES[tool_name]
    effect = _EFFECTS.get(tool_name, Effect.UNKNOWN)
    if effect is Effect.UNKNOWN:
        return effect, "Yan etkisi kayıtlı olmayan araç: varsayılan olarak reddedilir; lütfen önce policy.py içinde sınıflandırmayı ekleyin."
    return effect, _NOTES.get(tool_name, "")


def registered_names() -> frozenset[str]:
    """Policy tablosunun kapsadığı tüm araç adları; kayıt defterinde eksik kayıt olmadığını doğrulamak için kullanılır."""
    return frozenset(_EFFECTS)


def requires_approval(effect: Effect) -> bool:
    """Yalnızca yazma ve yıkıcı işlemler insan onayı gerektirir; salt okunur izin verilir, bilinmeyen reddedilir."""
    return effect in (Effect.WRITE, Effect.DESTRUCTIVE)


def targets(arguments: Any) -> list[str]:
    """Parametrelerdeki diske yazma hedeflerini çıkarır; onay gösterimi ve kapsam eşleştirmesi için kullanılır."""
    found: list[str] = []
    for key, value in _walk(arguments):
        if not _PATH_HINT.search(key):
            continue
        for item in _strings(value):
            if item not in found:
                found.append(item)
    return found


def canonical_digest(tool_name: str, arguments: Any) -> str:
    """Belirli bir çağrıyı bir özete indirger; herhangi bir parametre değişikliği farklı bir özet üretir."""
    payload = json.dumps(
        {"tool": tool_name, "arguments": arguments},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize(tool_name: str, arguments: Any, limit: int = 1200) -> str:
    """Onay arayüzü için parametre özeti; aşırı uzun dizilerin tamamının terminale dökülmesini önler."""
    text = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _walk(value: Any, key: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for name, item in value.items():
            yield from _walk(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item, key)
    else:
        yield key, value


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str) and value.strip():
        yield value.strip()
