"""Doğal dilden az sayıda izlenebilir SolidWorks API doğrulama adayı tanır."""
from __future__ import annotations

import re

API_REFERENCE_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(I[A-Za-z][A-Za-z0-9_]{1,126}|sw[A-Za-z0-9_]{1,124}_e)\s*(?:::|\.)\s*([A-Za-z][A-Za-z0-9_]{0,127})(?![A-Za-z0-9_])")
SW_YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:solidworks|sw)\s*(20\d{2})(?![0-9])", re.IGNORECASE)
VERSION_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*(?:版|版本|sürüm|sürümü|yıl|yılı)(?!\d)")

# Adaylar bu projede sarılmış API'lerden gelir; aday olmak Agent'ın o yöntemi kullanması gerektiği anlamına gelmez.
_INTENTS = (
    (r"(?:圆孔|圆形孔|(?:绘制|画|创建|生成|建立)[^，。；;\n]{0,8}圆(?:形|圈|草图)?|yuvarlak delik|daire|(?:çiz|oluştur|ekle)[^,.;\n]{0,12}daire|\b(?:draw|create|sketch)\s+(?:a\s+)?circle\b)",
     "ISketchManager", "CreateCircleByRadius"),
    (r"(?:(?:绘制|画|创建|生成|建立)[^，。；;\n]{0,8}(?:矩形|长方形)|矩形草图|dikdörtgen|(?:çiz|oluştur|ekle)[^,.;\n]{0,12}dikdörtgen|\b(?:draw|create|sketch)\s+(?:a\s+)?rectangle\b)",
     "ISketchManager", "CreateCenterRectangle"),
    (r"(?:拉伸|凸台拉伸|ekstrüzyon|ekstrude|\bextrud(?:e|ed|ing|sion)\b)", "IFeatureManager", "FeatureExtrusion3"),
    (r"(?:切除|挖孔|钻孔|kesme|kes|delme|delik aç|\b(?:cut|drill)\b)", "IFeatureManager", "FeatureCut4"),
    (r"(?:圆角|倒圆|radyus|yuvarlat|\bfillet\b)", "IFeatureManager", "FeatureFillet"),
    (r"(?:装配配合|添加配合|创建配合|同心配合|重合配合|montaj eşlemesi|eşleme ekle|eş merkezli eşleme|çakışan eşleme|\b(?:assembly mate|add mate)\b)", "IAssemblyDoc", "AddMate5"),
    (r"(?:质量属性|计算质量|测量质量|计算重量|kütle özellikleri|kütle hesapla|ağırlık hesapla|\bmass properties\b)", "IModelDocExtension", "CreateMassProperty"),
    (r"(?:创建工程图视图|插入工程图视图|生成工程图视图|teknik resim görünümü|çizim görünümü oluştur|resim görünümü ekle|\bdrawing view\b)", "IDrawingDoc", "CreateDrawViewFromModelView3"),
    (r"(?:打开零件|打开装配|打开模型|打开文档|parça aç|montaj aç|model aç|belge aç|\bopen (?:the )?(?:model|document|part|assembly)\b)", "ISldWorks", "OpenDoc6"),
    (r"(?:保存模型|保存零件|保存装配|保存文档|modeli kaydet|parçayı kaydet|montajı kaydet|belgeyi kaydet|\bsave (?:the )?(?:model|document|part)\b)", "IModelDoc2", "Save3"),
)
_NEGATION = re.compile(r"(?:不要|无需|不需要|不必|禁止|避免|不进行|yapma|gerekmez|olmadan|kullanma|do not|don't|without)\s*$", re.IGNORECASE)


def natural_language_candidates(query: str) -> list[tuple[str, str]]:
    """İlk görünme konumuna göre sıralanmış adayları döndürür; belirgin olumsuz ifadeler tetiklemez."""
    found: list[tuple[int, str, str]] = []
    for pattern, interface, member in _INTENTS:
        for match in re.finditer(pattern, query[:10000], re.IGNORECASE):
            prefix = query[max(0, match.start() - 12):match.start()]
            if _NEGATION.search(prefix):
                continue
            found.append((match.start(), interface, member))
            break
    found.sort(key=lambda item: item[0])
    return [(interface, member) for _, interface, member in found]


def task_candidates(query: str, limit: int = 2) -> tuple[list[tuple[str, str]], set[tuple[str, str]]]:
    """Açık referanslar önceliklidir; büyük/küçük harf tekrarları elendikten sonra doğal dil adayları eklenir."""
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for interface, member in API_REFERENCE_PATTERN.findall(query[:10000]):
        key = (interface.casefold(), member.casefold())
        if key not in seen:
            references.append((interface, member))
            seen.add(key)
    explicit_keys = set(seen)
    for interface, member in natural_language_candidates(query):
        key = (interface.casefold(), member.casefold())
        if key not in seen:
            references.append((interface, member))
            seen.add(key)
    return references[:limit], explicit_keys


def task_years(query: str) -> set[int]:
    values = (*SW_YEAR_PATTERN.findall(query[:10000]), *VERSION_YEAR_PATTERN.findall(query[:10000]))
    return {int(year) for year in values if 2010 <= int(year) <= 2035}
