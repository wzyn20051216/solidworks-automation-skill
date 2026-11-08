"""@brief Karmaşık mekanik gereksinimleri denetlenebilir bir SolidWorks mühendislik DAG'ına ayrıştırır."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class CapabilityLevel(str, Enum):
    """@brief Yetenek uygulamasının ve gerçek regresyonun olgunluğunu tanımlar."""

    VERIFIED = "verified"
    PILOT = "pilot"
    REFERENCE_ONLY = "reference_only"
    NOT_IMPLEMENTED = "not_implemented"


class PhaseStatus(str, Enum):
    """@brief Tek bir mühendislik aşamasının yürütme durumunu tanımlar."""

    PLANNED = "planned"
    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(frozen=True)
class RetryPolicy:
    """@brief Aşama başarısız olduğunda yerel yeniden deneme ve geri düşme stratejisini tanımlar."""

    max_attempts: int
    strategy: str
    retryable_failures: Tuple[str, ...]
    fallback: str


@dataclass(frozen=True)
class CapabilityRoute:
    """@brief Belirli bir aşama için seçilen yeteneği, becerileri ve MCP araçlarını tanımlar."""

    capability_id: str
    level: CapabilityLevel
    skills: Tuple[str, ...]
    mcp_tools: Tuple[str, ...]
    execution_mode: str
    reason: str


@dataclass(frozen=True)
class EngineeringPhase:
    """@brief Mühendislik DAG'ında bağımsız olarak yürütülebilen, kabul edilebilen ve yeniden denenebilen aşamayı tanımlar."""

    id: str
    name: str
    depends_on: Tuple[str, ...]
    routes: Tuple[CapabilityRoute, ...]
    artifacts: Tuple[str, ...]
    acceptance: Tuple[str, ...]
    risks: Tuple[str, ...]
    retry_policy: RetryPolicy
    status: PhaseStatus = PhaseStatus.PLANNED
    serial_required: bool = True
    execution_lane: str = "solidworks-com"
    human_gate: bool = False

    @property
    def skills(self) -> Tuple[str, ...]:
        """@brief Aşamanın tekilleştirilmiş beceri listesini döndürür."""
        return _unique(item for route in self.routes for item in route.skills)

    @property
    def mcp_tools(self) -> Tuple[str, ...]:
        """@brief Aşamanın tekilleştirilmiş MCP araç listesini döndürür."""
        return _unique(item for route in self.routes for item in route.mcp_tools)


@dataclass(frozen=True)
class EngineeringPlan:
    """@brief Karmaşık mekanik proje için eksiksiz aşama planını tanımlar."""

    objective: str
    project_type: str
    phases: Tuple[EngineeringPhase, ...]
    assumptions: Tuple[str, ...]
    warnings: Tuple[str, ...]
    revision: int = 1
    change_request: Optional[str] = None
    critical_cad_serial: bool = True
    schema_version: str = "1.0"

    def phase(self, phase_id: str) -> EngineeringPhase:
        """@brief Aşamayı ID ile döndürür; yoksa açık bir hata fırlatır."""
        for item in self.phases:
            if item.id == phase_id:
                return item
        raise KeyError("Bilinmeyen mühendislik aşaması: {}".format(phase_id))

    def validate(self) -> None:
        """@brief Benzersiz ID'leri, bağımlılık referanslarını, döngüsüzlüğü ve CAD seri politikasını doğrular."""
        phase_ids = [phase.id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("Mühendislik planı yinelenen aşama ID'leri içeriyor")

        known = set(phase_ids)
        for phase in self.phases:
            missing = set(phase.depends_on) - known
            if missing:
                raise ValueError("Aşama {} bilinmeyen bağımlılıklara başvuruyor: {}".format(phase.id, sorted(missing)))
            if phase.id in phase.depends_on:
                raise ValueError("Aşama {} kendisine bağımlı olamaz".format(phase.id))
            if phase.status == PhaseStatus.COMPLETED and any(
                route.level == CapabilityLevel.NOT_IMPLEMENTED for route in phase.routes
            ):
                raise ValueError("Uygulanmamış yetenek içeren aşama tamamlandı olarak işaretlenemez: {}".format(phase.id))
            if self.critical_cad_serial and phase.serial_required and phase.execution_lane != "solidworks-com":
                raise ValueError("Kritik CAD aşaması solidworks-com seri kanalına girmek zorundadır: {}".format(phase.id))

        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(phase_id: str) -> None:
            if phase_id in visiting:
                raise ValueError("Mühendislik planında döngüsel bağımlılık var: {}".format(phase_id))
            if phase_id in visited:
                return
            visiting.add(phase_id)
            for dependency in self.phase(phase_id).depends_on:
                visit(dependency)
            visiting.remove(phase_id)
            visited.add(phase_id)

        for phase_id in phase_ids:
            visit(phase_id)

    def to_dict(self) -> Dict[str, Any]:
        """@brief Görev protokolü ve denetim günlüğü kalıcılığı için uygun sözlük döndürür."""
        payload = asdict(self)
        return _enum_values(payload)


def engineering_plan_from_dict(payload: Mapping[str, Any]) -> EngineeringPlan:
    """@brief Kuyrukta kalıcı JSON'dan mühendislik planını geri yükler; diyalog tabanlı yerel yeniden planlama için kullanılır."""
    phases: List[EngineeringPhase] = []
    for raw_phase in payload.get("phases", []):
        if not isinstance(raw_phase, Mapping):
            continue
        routes = tuple(
            CapabilityRoute(
                capability_id=str(route.get("capability_id") or ""),
                level=CapabilityLevel(str(route.get("level") or CapabilityLevel.NOT_IMPLEMENTED.value)),
                skills=tuple(str(item) for item in route.get("skills", [])),
                mcp_tools=tuple(str(item) for item in route.get("mcp_tools", [])),
                execution_mode=str(route.get("execution_mode") or "blocked"),
                reason=str(route.get("reason") or ""),
            )
            for route in raw_phase.get("routes", [])
            if isinstance(route, Mapping)
        )
        raw_retry = raw_phase.get("retry_policy") if isinstance(raw_phase.get("retry_policy"), Mapping) else {}
        phases.append(
            EngineeringPhase(
                id=str(raw_phase.get("id") or ""),
                name=str(raw_phase.get("name") or ""),
                depends_on=tuple(str(item) for item in raw_phase.get("depends_on", [])),
                routes=routes,
                artifacts=tuple(str(item) for item in raw_phase.get("artifacts", [])),
                acceptance=tuple(str(item) for item in raw_phase.get("acceptance", [])),
                risks=tuple(str(item) for item in raw_phase.get("risks", [])),
                retry_policy=RetryPolicy(
                    max_attempts=int(raw_retry.get("max_attempts") or 1),
                    strategy=str(raw_retry.get("strategy") or "yerel yeniden deneme"),
                    retryable_failures=tuple(str(item) for item in raw_retry.get("retryable_failures", [])),
                    fallback=str(raw_retry.get("fallback") or "insan incelemesine devret"),
                ),
                status=PhaseStatus(str(raw_phase.get("status") or PhaseStatus.PLANNED.value)),
                serial_required=bool(raw_phase.get("serial_required", True)),
                execution_lane=str(raw_phase.get("execution_lane") or "solidworks-com"),
                human_gate=bool(raw_phase.get("human_gate", False)),
            )
        )
    plan = EngineeringPlan(
        objective=str(payload.get("objective") or ""),
        project_type=str(payload.get("project_type") or "complex_mechanical_system"),
        phases=tuple(phases),
        assumptions=tuple(str(item) for item in payload.get("assumptions", [])),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        revision=int(payload.get("revision") or 1),
        change_request=str(payload.get("change_request")) if payload.get("change_request") else None,
        critical_cad_serial=bool(payload.get("critical_cad_serial", True)),
        schema_version=str(payload.get("schema_version") or "1.0"),
    )
    plan.validate()
    return plan


@dataclass(frozen=True)
class _CapabilityDefinition:
    """@brief Orkestratörün yerleşik, temkinli yetenek envanterini saklar."""

    level: CapabilityLevel
    skills: Tuple[str, ...]
    mcp_tools: Tuple[str, ...]
    reason: str


MAIN_SKILL = "solidworks-automation"
VIBECAD_SKILL = "solidworks-vibecad"
FILLET_SKILL = "solidworks-fillet-chamfer-cnc"


CAPABILITIES: Mapping[str, _CapabilityDefinition] = {
    "requirements_planning": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (VIBECAD_SKILL, MAIN_SKILL),
        (),
        "VibeCAD doğal dili parametrik tasarım planına dönüştürebilir; resmi yürütmeden önce kritik ölçüler, yükler ve imalat kısıtları yine de doğrulanmalıdır.",
    ),
    "part_and_features": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL, VIBECAD_SKILL),
        ("solidworks_health_check", "solidworks_new_document", "solidworks_create_basic_part", "solidworks_save_document"),
        "Parametrik parçalar ve temel unsurlar için gerçek COM sarmalayıcıları mevcut; karmaşık profiller beceri betikleriyle yürütülüp incelenmelidir.",
    ),
    "holes_and_finishing": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL, FILLET_SKILL),
        ("solidworks_create_hole_feature", "solidworks_inspect_hole_features", "solidworks_save_document"),
        "Kör delik, havşa, havşa başı, yarım daire kanal ve delik konumu kabulü doğrulandı; radyus ve pah özel beceri üzerinden kararlı şekilde yönlendirilir.",
    ),
    "assembly_and_mates": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        (
            "solidworks_new_document",
            "solidworks_add_component",
            "solidworks_set_component_fixed",
            "solidworks_add_coincident_mate",
            "solidworks_add_distance_mate",
            "solidworks_add_concentric_mate",
            "solidworks_save_document",
        ),
        "Bileşen ekleme ile çakışık, mesafe ve eş merkezli Mate'ler doğrulandı; serbestlik dereceleri ve Mate unsur ağacı ayrıca kontrol edilmelidir.",
    ),
    "motion_study": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        ("solidworks_add_rotary_motor", "solidworks_inspect_motion_studies", "solidworks_validate_motion_study"),
        "Şu anda yalnızca döner motor oluşturma, hesaplama ve sonuç denetimi doğrulanmış yetenek sayılır.",
    ),
    "drawings_and_bom": _CapabilityDefinition(
        CapabilityLevel.PILOT,
        (MAIN_SKILL, "solidworks-engineering-drawing"),
        ("solidworks_generate_drawing", "solidworks_review_drawing", "solidworks_inspect_drawing"),
        "Teknik resim Pilot aşamasındadır; GB/T birinci açı çerçevesi, BOM, ölçü zinciri ve sac levha açınım kanıtları insan tarafından incelenmelidir, gözetimsiz tamamlandı iddiası yasaktır.",
    ),
    "export_delivery": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        ("solidworks_export_active",),
        "STEP, PDF vb. dar arayüz üzerinden dışa aktarıldı; ancak her hedef dosyanın varlığı, biçimi ve karması yine de kontrol edilmelidir.",
    ),
    "geometry_and_delivery_review": _CapabilityDefinition(
        CapabilityLevel.VERIFIED,
        (MAIN_SKILL,),
        (
            "solidworks_review_active",
            "solidworks_inspect_hole_features",
            "solidworks_inspect_motion_studies",
            "solidworks_validate_motion_study",
        ),
        "Çoklu görünüm, delik/kanal ve Motion kanıtları otomatik toplanabilir; GB/T çizimleri için insan nihai incelemesi korunur.",
    ),
}

# Orkestratör yetenekleri, sondaj aracından daha ince tanelidir; bu takma adlar yerel tip
# kitaplığı sonuçlarını ilgili aşamalara aktarır.
CAPABILITY_REPORT_ALIASES: Mapping[str, str] = {
    "holes_and_finishing": "part_and_features",
    "drawings_and_bom": "drawings",
    "export_delivery": "part_and_features",
    "geometry_and_delivery_review": "part_and_features",
}

_COMPLEX_PROJECT_SIGNALS: Tuple[Tuple[str, ...], ...] = (
    ("多零件", "多个零件", "装配", "装配体", "整机", "机构", "总成", "çok parçalı", "birden fazla parça", "montaj", "komple makine", "mekanizma", "alt montaj"),
    ("mate", "配合", "同心", "自由度", "干涉", "eşleme", "eş merkezli", "serbestlik derecesi", "çakışma", "girişim"),
    ("motion", "运动仿真", "运动算例", "马达", "转速", "动力学", "hareket simülasyonu", "hareket etüdü", "motor", "devir", "dinamik"),
    ("工程图", "图纸", "bom", "明细表", "gb/t", "国标", "teknik resim", "çizim", "malzeme listesi", "ulusal standart"),
    ("step", "pdf", "交付包", "完整交付", "teslimat paketi", "eksiksiz teslimat"),
    ("沉孔", "盲孔", "槽", "圆角", "倒角", "孔位公差", "havşa", "kör delik", "kanal", "radyus", "pah", "delik konum toleransı"),
)


def requires_engineering_orchestration(brief: str) -> bool:
    """@brief Gereksinimin tek adımlı parça görevi yerine aşamalar arası mühendislik DAG'ı gerektirip gerektirmediğine karar verir.

    @param brief Kullanıcının doğal dildeki gereksinimi.
    @return En az iki bağımsız mühendislik alanı eşleşirse veya açıkça komple makine/kapsamlı
        mühendislik istenirse ``True`` döndürür.
    """
    normalized = brief.strip().lower()
    if not normalized:
        return False
    if any(keyword in normalized for keyword in ("综合工程", "完整工程", "全流程", "整机设计", "kapsamlı mühendislik", "eksiksiz mühendislik", "uçtan uca süreç", "komple makine tasarımı")):
        return True
    matched_domains = sum(any(keyword in normalized for keyword in domain) for domain in _COMPLEX_PROJECT_SIGNALS)
    return matched_domains >= 2


def _unique(values: Iterable[str]) -> Tuple[str, ...]:
    """@brief Özgün sırayı koruyarak yinelenen dizeleri kaldırır."""
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _enum_values(value: Any) -> Any:
    """@brief Enum'ları özyinelemeli olarak JSON uyumlu değerlere dönüştürür."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_enum_values(item) for item in value]
    return value


def _normalise_level(raw_status: str, fallback: CapabilityLevel) -> CapabilityLevel:
    """@brief Yetenek sondaj durumunu orkestratör olgunluk düzeyine normalleştirir."""
    status = raw_status.strip().lower()
    if status.startswith("verified"):
        return CapabilityLevel.VERIFIED
    if status == "pilot":
        return CapabilityLevel.PILOT
    if status == "reference_only":
        return CapabilityLevel.REFERENCE_ONLY
    if status == "not_implemented":
        return CapabilityLevel.NOT_IMPLEMENTED
    return fallback


def _route(capability_id: str, capability_report: Optional[Mapping[str, Any]]) -> CapabilityRoute:
    """@brief Yerleşik envanter ve isteğe bağlı yerel sondaj raporuna göre yürütme rotası seçer."""
    definition = CAPABILITIES[capability_id]
    level = definition.level
    if capability_report:
        report_capabilities = capability_report.get("capabilities", {})
        report_key = capability_id
        if isinstance(report_capabilities, Mapping) and report_key not in report_capabilities:
            report_key = CAPABILITY_REPORT_ALIASES.get(capability_id, capability_id)
        report_item = report_capabilities.get(report_key, {}) if isinstance(report_capabilities, Mapping) else {}
        if isinstance(report_item, Mapping):
            level = _normalise_level(str(report_item.get("implementation_status", "")), level)
            if report_item.get("ready_for_unattended_use") is False and level == CapabilityLevel.VERIFIED:
                level = CapabilityLevel.PILOT

    if level == CapabilityLevel.VERIFIED:
        mode = "mcp_and_skill" if definition.mcp_tools else "skill"
    elif level == CapabilityLevel.PILOT:
        mode = "assisted_human_gate"
    else:
        mode = "blocked"
    return CapabilityRoute(capability_id, level, definition.skills, definition.mcp_tools, mode, definition.reason)


def _phase_status(routes: Sequence[CapabilityRoute]) -> PhaseStatus:
    """@brief Uygulanmamış veya yalnızca referans yetenekler varsayılan olarak engellenir; diğer aşamalar bekleyen kabul edilir."""
    blocked_levels = {CapabilityLevel.REFERENCE_ONLY, CapabilityLevel.NOT_IMPLEMENTED}
    return PhaseStatus.BLOCKED if any(route.level in blocked_levels for route in routes) else PhaseStatus.PLANNED


def _phase(
    phase_id: str,
    name: str,
    depends_on: Sequence[str],
    capability_ids: Sequence[str],
    artifacts: Sequence[str],
    acceptance: Sequence[str],
    risks: Sequence[str],
    retry_policy: RetryPolicy,
    capability_report: Optional[Mapping[str, Any]],
    human_gate: bool = False,
    serial_required: bool = True,
) -> EngineeringPhase:
    """@brief Durumu temkinli ve yetenekleri izlenebilir bir mühendislik aşaması oluşturur."""
    routes = tuple(_route(item, capability_report) for item in capability_ids)
    return EngineeringPhase(
        id=phase_id,
        name=name,
        depends_on=tuple(depends_on),
        routes=routes,
        artifacts=tuple(artifacts),
        acceptance=tuple(acceptance),
        risks=tuple(risks),
        retry_policy=retry_policy,
        status=_phase_status(routes),
        serial_required=serial_required,
        execution_lane="solidworks-com" if serial_required else "planning",
        human_gate=human_gate or any(route.level != CapabilityLevel.VERIFIED for route in routes),
    )


def build_engineering_plan(
    brief: str,
    capability_report: Optional[Mapping[str, Any]] = None,
) -> EngineeringPlan:
    """@brief Doğal dildeki karmaşık mekanik görevi sekiz aşamalı SolidWorks DAG'ına ayrıştırır.

    @param brief Kullanıcının doğal dildeki mühendislik gereksinimi.
    @param capability_report İsteğe bağlı ``sw_capability_probe.py`` raporu.
    @return Varsayılan olarak tüm aşamaları bekleyen veya engellenmiş plan; hiçbir CAD işinin
        tamamlandığı anlamına gelmez.
    """
    objective = brief.strip()
    if not objective:
        raise ValueError("Karmaşık mekanik görev açıklaması boş olamaz")

    planning_retry = RetryPolicy(2, "Eksik kısıtları tamamladıktan sonra yeniden planla", ("missing_requirement", "ambiguous_constraint"), "Kritik mühendislik parametrelerinin insan tarafından doğrulanmasına devret")
    cad_retry = RetryPolicy(2, "Yalnızca geçerli aşamayı geri al ve yeniden dene", ("com_error", "rebuild_error", "selection_error"), "Unsur partisini küçült ve hata kanıtını koru")
    review_retry = RetryPolicy(1, "İlk başarısız aşamaya dönerek yerel yeniden işle", ("acceptance_failed", "artifact_missing"), "Teslimatı durdur ve insan incelemesi iste")

    phase_catalog = (
        _phase(
            "requirements",
            "Gereksinim netleştirme ve mühendislik kısıtları",
            (),
            ("requirements_planning",),
            ("requirements.json", "design_plan.json", "assumptions.json"),
            ("Parça sayısı, işlev, arayüz ve hareket hedefleri net", "Kritik ölçüler, malzeme, yük, tolerans ve imalat yönteminin kaynağı veya açık varsayımı var", "Teslimat biçimleri ve kabul kapıları eksiksiz"),
            ("Doğal dilde ölçü veya yük eksikse üretilemez tasarım ortaya çıkabilir", "GB/T sürümü ve kurumsal şablon belirtilmediğinde tahmin yürütülemez"),
            planning_retry,
            capability_report,
            human_gate=True,
            serial_required=False,
        ),
        _phase(
            "part-modeling",
            "Parametrik parça modelleme",
            ("requirements",),
            ("part_and_features",),
            ("Dört adet veya gereksinimde belirtilen sayıda SLDPRT dosyası", "part_parameters.json", "part_rebuild_report.json"),
            ("Parça sayısı gereksinimle uyumlu ve dosyalar yerel olarak açılabilir", "Eskizler ve kritik unsurlar yeniden oluşturulabilir", "Kütle özellikleri ve sınırlayıcı kutu tasarım parametrelerine uygun"),
            ("Eksik kısıtlı eskizler sonraki unsurlarda kaymaya yol açar", "Parça arayüz ölçülerinin tutarsızlığı montaj hatasına neden olur"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "holes-fillet-chamfer",
            "Delik/kanal, radyus ve pah",
            ("part-modeling",),
            ("holes_and_finishing",),
            ("feature_parameters.json", "hole_geometry_evidence.json", "updated SLDPRT files"),
            ("Havşa, kör delik veya kanalın özellikleri, derinliği ve konumu parametreleri karşılıyor", "Delik ekseni konumu ve delik çapı toleransı geometrik kabulden geçiyor", "Radyus ve pahlar mevcut ve modelde yeniden oluşturma hatası yok"),
            ("Kararsız unsur sırası radyus çözümünün başarısız olmasına yol açabilir", "B-Rep tek başına kör veya boydan boya deliği kanıtlayamaz; oluşturma parametreleri çapraz kontrol edilmelidir"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "assembly-mates",
            "Montaj ve Mate",
            ("holes-fillet-chamfer",),
            ("assembly_and_mates",),
            ("assembly.SLDASM", "mate_inventory.json", "degree_of_freedom_report.json"),
            ("Bileşen sayısı ve başvurulan dosyalar eksiksiz", "Eş merkezli, çakışık, mesafe vb. Mate'ler tasarım serbestlik derecesi bütçesiyle uyumlu", "Dönen parçalar hatalı kilitlenmemiş ve belirgin çakışma yok"),
            ("Aşırı tanımlı Mate'ler mekanizmayı kilitler", "Bileşen adı, konfigürasyon veya referans düzlem dil farklılıkları seçim hatasına yol açabilir"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "motion-study",
            "Motion hareket etüdü",
            ("assembly-mates",),
            ("motion_study",),
            ("motion_study.json", "motion_validation.json", "calculated Motion Study in SLDASM"),
            ("Döner motor nesnesi gerçekten mevcut", "Etüt süresi ve motor sayısı planla uyumlu", "Hesaplama sonuçları mevcut ve results_out_of_date=False"),
            ("Mevcut doğrulanmış kapsam temas, sürtünme, yay veya tam dinamiği içermez", "Motion Analysis lisansı eksikse yalnızca açıkça düşürülmüş mod bildirilebilir, sonuç uydurulamaz"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "drawing-bom",
            "GB/T teknik resim ve BOM",
            ("motion-study",),
            ("drawings_and_bom",),
            ("part_and_assembly_drawings.SLDDRW", "bom.csv", "drawing_review_checklist.json"),
            ("Kağıt boyutu, çerçeve, antet, yazı tipi ve çizgi tipleri belirtilen GB/T/kurumsal şablona uygun", "Ölçü zinciri, delik/kanal özellikleri ve konumlandırma ölçüleri eksiksiz", "BOM adetleri, kodlar, malzemeler ve montaj referansları tutarlı", "İnsan görsel incelemesinde örtüşme, çizgiye basma veya antede taşma yok"),
            ("Bu yetenek hâlâ Pilot; gözetimsiz teslim edilemez", "Otomatik ölçüler ve BOM alanları eksik kalabilir veya yerleşim sıkışabilir"),
            RetryPolicy(2, "Görünüm veya tabloyu yerel olarak yeniden düzenledikten sonra incele", ("layout_overlap", "dimension_missing", "bom_mismatch"), "SLDDRW dosyasını koru ve insan mühendisin nihai incelemesine devret"),
            capability_report,
            human_gate=True,
        ),
        _phase(
            "export-delivery",
            "STEP/PDF ve teslimat dışa aktarımı",
            ("drawing-bom",),
            ("export_delivery",),
            ("assembly.step", "drawing.pdf", "artifact_ledger.json"),
            ("STEP yeniden açılabilir ve katı/bileşen sayısı makul", "PDF sayfa sayısı, kağıt boyutu ve içeriği boş değil", "Tüm teslimatlar mevcut, boş değil ve SHA-256 kaydedilmiş"),
            ("Başarılı dışa aktarma dönüş değeri dosya biçimi doğrulamasının yerini tutamaz", "Kayıp referanslar veya yazı tipi değişimi teslimat sapmasına yol açar"),
            cad_retry,
            capability_report,
        ),
        _phase(
            "final-review",
            "Kapsamlı inceleme ve teslimat kapısı",
            ("export-delivery",),
            ("geometry_and_delivery_review",),
            ("isometric/front/top/right previews", "review_report.json", "review_gate.json"),
            ("Çoklu görünüm görsel kontrolü geçti", "Parça, delik/kanal, Mate, Motion, çizim, BOM ve dışa aktarma kanıtları tek tek geçti", "Her Pilot kalemi insan imzalı; başarısız kalemler tamamlandı olarak işaretlenmemiş"),
            ("Yalnızca dosya varlığını kontrol etmek geometri ve montaj hatalarını kaçırır", "Yerel değişiklikler alt akıştaki çizim veya Motion sonuçlarını eskitebilir"),
            review_retry,
            capability_report,
            human_gate=True,
        ),
    )

    normalized = objective.lower()
    requested_features = any(keyword in normalized for keyword in ("孔", "槽", "圆角", "倒角", "公差", "螺纹", "delik", "kanal", "radyus", "pah", "tolerans", "diş"))
    requested_assembly = any(keyword in normalized for keyword in ("装配", "装配体", "整机", "机构", "总成", "mate", "配合", "干涉", "自由度", "montaj", "komple makine", "mekanizma", "eşleme", "çakışma", "girişim", "serbestlik derecesi"))
    requested_motion = any(keyword in normalized for keyword in ("motion", "运动仿真", "运动算例", "马达", "转速", "动力学", "hareket simülasyonu", "hareket etüdü", "motor", "devir", "dinamik"))
    requested_drawing = any(keyword in normalized for keyword in ("工程图", "图纸", "bom", "明细表", "gb/t", "国标", "teknik resim", "çizim", "malzeme listesi", "ulusal standart"))
    requested_export = any(keyword in normalized for keyword in ("step", "stp", "stl", "pdf", "导出", "交付", "dışa aktar", "teslimat"))
    requested_ids = {"requirements", "part-modeling", "final-review"}
    if requested_features:
        requested_ids.add("holes-fillet-chamfer")
    if requested_assembly or requested_motion:
        requested_ids.add("assembly-mates")
    if requested_motion:
        requested_ids.add("motion-study")
    if requested_drawing:
        requested_ids.add("drawing-bom")
    if requested_export:
        requested_ids.add("export-delivery")

    selected_phases: List[EngineeringPhase] = []
    previous_phase_id: Optional[str] = None
    for phase in phase_catalog:
        if phase.id not in requested_ids:
            continue
        dependencies = () if previous_phase_id is None else (previous_phase_id,)
        selected_phases.append(replace(phase, depends_on=dependencies))
        previous_phase_id = phase.id
    phases = tuple(selected_phases)

    warnings = tuple(
        "{} aşaması {} düzeyini kullanıyor; insan onay kapısından geçmek zorundadır.".format(phase.name, route.level.value)
        for phase in phases
        for route in phase.routes
        if route.level != CapabilityLevel.VERIFIED
    )
    plan = EngineeringPlan(
        objective=objective,
        project_type="complex_mechanical_system",
        phases=phases,
        assumptions=(
            "Sağlanmayan ölçüler, malzemeler, yükler, toleranslar ve standart sürümleri yalnızca doğrulanacak kalem olarak kaydedilir; otomatik olarak gerçek yazılmaz.",
            "Tüm SolidWorks COM yazma işlemleri solidworks-com tek eşzamanlılık kanalına girer.",
            "Bu plan yapılacak işi tanımlar; aşama yönlendirmesinin başarılı olması modelin veya teslimatın tamamlandığı anlamına gelmez.",
        ),
        warnings=warnings,
    )
    plan.validate()
    return plan


_CHANGE_PHASE_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("requirements", ("需求", "材料", "载荷", "标准", "数量", "gereksinim", "malzeme", "yük", "standart", "adet")),
    ("part-modeling", ("零件", "外形", "尺寸", "草图", "拉伸", "parça", "dış form", "ölçü", "eskiz", "ekstrüzyon")),
    ("holes-fillet-chamfer", ("孔", "沉孔", "盲孔", "槽", "圆角", "倒角", "公差", "delik", "havşa", "kör delik", "kanal", "radyus", "pah", "tolerans")),
    ("assembly-mates", ("装配", "mate", "配合", "同心", "干涉", "自由度", "montaj", "eşleme", "eş merkezli", "çakışma", "girişim", "serbestlik derecesi")),
    ("motion-study", ("motion", "运动", "马达", "转速", "动画", "hareket", "motor", "devir", "animasyon")),
    ("drawing-bom", ("工程图", "图纸", "bom", "明细表", "gb/t", "标注", "teknik resim", "çizim", "malzeme listesi", "ölçülendirme")),
    ("export-delivery", ("step", "pdf", "导出", "交付", "dışa aktar", "teslimat")),
    ("final-review", ("复核", "验收", "预览", "inceleme", "kabul", "önizleme")),
)


def infer_affected_phases(change_request: str) -> Tuple[str, ...]:
    """@brief Yerel değişiklik açıklamasından en öndeki etkilenen aşamayı çıkarır."""
    normalized = change_request.strip().lower()
    if not normalized:
        raise ValueError("Yerel değişiklik açıklaması boş olamaz")
    matched = [phase_id for phase_id, keywords in _CHANGE_PHASE_KEYWORDS if any(keyword in normalized for keyword in keywords)]
    return (matched[0],) if matched else ("requirements",)


def replan_for_local_change(
    plan: EngineeringPlan,
    change_request: str,
    affected_phase_ids: Optional[Sequence[str]] = None,
) -> EngineeringPlan:
    """@brief Yerel olarak değiştirilen aşamayı ve tüm DAG ardıllarını yeniden planlar.

    Etkilenmeyen ve harici kabul kanıtı olan aşamalar mevcut durumlarını koruyabilir;
    etkilenen aşamalar ve ardılları ``planned`` durumuna döner (önceki yetenek
    engellenmişse ``blocked`` kalır), böylece eski sonuçların kullanılması önlenir.
    """
    plan.validate()
    roots = tuple(affected_phase_ids or infer_affected_phases(change_request))
    known = {phase.id for phase in plan.phases}
    unknown = set(roots) - known
    if unknown:
        raise ValueError("Yerel değişiklik bilinmeyen aşamalara başvuruyor: {}".format(sorted(unknown)))

    invalidated: Set[str] = set(roots)
    changed = True
    while changed:
        changed = False
        for phase in plan.phases:
            if phase.id not in invalidated and any(parent in invalidated for parent in phase.depends_on):
                invalidated.add(phase.id)
                changed = True

    phases: List[EngineeringPhase] = []
    for phase in plan.phases:
        if phase.id not in invalidated:
            phases.append(phase)
            continue
        next_status = _phase_status(phase.routes)
        phases.append(replace(phase, status=next_status))

    replanned = replace(
        plan,
        phases=tuple(phases),
        revision=plan.revision + 1,
        change_request=change_request.strip(),
        warnings=plan.warnings
        + ("Yerel değişiklik şu aşamaları ve ardıllarını geçersiz kıldı: {}".format(", ".join(sorted(invalidated))),),
    )
    replanned.validate()
    return replanned
