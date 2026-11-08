"""Gerçek MCP araç meta verisine dayalı çevrimdışı arama; yetkilendirme ve yürütme üstlenmez."""
from __future__ import annotations

import copy
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any


# Her grup bir kavramı temsil eder; aynı grupta birden fazla kelimenin eşleşmesi yalnızca bir kez puan ekler, böylece biçim/eş anlamlı yığılması önlenir.
# Not: Anahtar sözcük listeleri bilinçli olarak Çince terimleri korur; eşleştirme geriye dönük uyumluluk için onları da kapsamalıdır.
_CONCEPTS: tuple[tuple[str, ...], ...] = (
    # Modelleme özellikleri
    ("干涉检查", "检查干涉", "干涉检测", "干涉", "interference", "girişim", "girişim denetimi", "çakışma"),
    ("拉伸凸台", "凸台拉伸", "草图拉伸", "草图", "拉伸", "extrude", "extrusion", "sketch", "ekstrüzyon", "eskiz", "çizim"),
    ("切除", "挖孔", "cut", "kesme", "kes"),
    ("圆角", "倒圆", "fillet", "radyus", "yuvarlat"),
    ("倒角", "chamfer", "pah", "pah kırma"),
    ("旋转特征", "旋转体", "旋转", "revolve", "döndürme", "döndür"),
    ("抽壳", "空心", "shell", "hollow", "kabuk", "içi boş"),
    ("阵列", "pattern", "dizi", "desen"),
    ("镜像", "mirror", "ayna", "aynalama"),
    ("孔特征", "打孔", "开孔", "钻孔", "异型孔", "hole feature", "hole", "counterbore", "countersink", "delik", "havşa"),
    ("孔检查", "检查孔", "孔位", "hole inspection", "inspect hole", "delik denetimi", "delik konumu"),
    ("审视模型", "审视当前模型", "模型审视", "review active", "review the active", "modeli incele", "etkin modeli incele", "model incelemesi"),
    # Sorgulama ve ölçüm
    ("质量属性", "质量特性", "质心", "质量", "mass properties", "centre of mass", "center of mass", "kütle özellikleri", "ağırlık merkezi", "kütle"),
    ("包围盒", "边界框", "外廓尺寸", "bounding box", "sınır kutusu", "çevreleyen kutu"),
    ("边线", "边缘", "edges", "list edges", "kenar", "kenarlar"),
    ("文档单位", "单位设置", "单位", "units", "unit system", "belge birimleri", "birim", "birim sistemi"),
    ("自定义属性", "文件属性", "custom properties", "özel özellikler", "dosya özellikleri"),
    ("配置族", "配置", "configuration", "konfigürasyon", "yapılandırma"),
    ("更改尺寸", "修改尺寸", "更新尺寸", "改尺寸", "命名尺寸", "尺寸", "update dimension", "dimension", "ölçü güncelle", "ölçü değiştir", "ölçü"),
    ("外观颜色", "外观", "颜色", "着色", "appearance", "color", "görünüm", "renk", "renklendirme"),
    ("预览", "preview", "önizleme"),
    # Belge ve dosya
    ("新建文档", "新建零件", "新建装配", "新建工程图", "新建", "new document", "new part", "new assembly", "new drawing", "yeni belge", "yeni parça", "yeni montaj", "yeni teknik resim", "yeni"),
    ("基础零件", "圆柱", "立方体", "方块", "basic part", "cylinder", "temel parça", "silindir", "küp"),
    ("打开文件", "打开文档", "打开", "open document", "open file", "dosya aç", "belge aç", "aç"),
    ("保存文件", "保存文档", "保存", "另存为", "save document", "save as", "save", "dosya kaydet", "belge kaydet", "kaydet", "farklı kaydet"),
    ("关闭文档", "关闭", "close document", "close", "belgeyi kapat", "kapat"),
    ("打包", "pack and go", "pack", "paketle", "paket"),
    ("导出", "输出文件", "export", "dışa aktar", "çıktı dosyası"),
    ("批量导出", "批量输出", "batch export", "toplu dışa aktar", "toplu çıktı"),
    ("材料清单", "物料清单", "明细表", "bom", "malzeme listesi", "parça listesi"),
    ("设计规格", "规格文件", "规格", "design spec", "spec file", "build from spec", "spec", "tasarım spesifikasyonu", "şartname", "spesifikasyon"),
    # Montaj
    ("装配体", "装配", "assembly", "montaj"),
    ("添加零件", "添加组件", "插入零件", "装配零件", "add component", "insert component", "bileşen ekle", "parça ekle", "bileşen yerleştir"),
    ("固定组件", "浮动组件", "固定住", "固定", "浮动", "component fixed", "fixed component",
     "set component fixed", "fix component", "float component", "sabit bileşen", "yüzen bileşen", "bileşeni sabitle", "bileşeni serbest bırak"),
    ("同心配合", "同轴配合", "concentric mate", "concentric", "eş merkezli eşleme", "eş merkezli"),
    ("重合配合", "重合", "coincident mate", "coincident", "çakışan eşleme", "çakışan"),
    ("距离配合", "间距配合", "distance mate", "distance", "uzaklık eşlemesi", "mesafe"),
    ("替换组件", "替换零件", "replace component", "bileşeni değiştir", "parçayı değiştir"),
    ("排除实体", "删除实体", "排除", "exclude bodies", "exclude body", "gövdeleri hariç tut", "gövde hariç tut"),
    # Teknik resim
    ("工程图", "图纸", "drawing", "teknik resim", "çizim"),
    ("生成工程图", "创建工程图", "出工程图", "create drawing", "generate drawing", "teknik resim oluştur", "çizim oluştur"),
    ("审视工程图", "审查工程图", "检查工程图", "review drawing", "teknik resmi incele", "çizimi incele"),
    ("读取工程图", "工程图结构", "视图结构", "inspect drawing", "teknik resim yapısı", "görünüm yapısı"),
    # Hareket
    ("运动算例", "运动研究", "motion study", "hareket etüdü", "hareket çalışması"),
    ("旋转马达", "旋转电机", "马达", "motor", "rotary motor", "döner motor"),
    ("运动检查", "检查运动算例", "inspect motion", "motion audit", "hareketi incele", "hareket denetimi"),
    ("验证运动", "运动验证", "validate motion", "hareketi doğrula"),
    # Analiz
    ("有限元", "有限元分析", "fea", "finite element", "sonlu elemanlar", "sonlu eleman analizi"),
    ("有限元预检", "求解器检查", "求解器", "fea preflight", "solver", "sonlu eleman ön kontrolü", "çözücü"),
    ("准备有限元", "准备分析", "生成inp", "fea prepare", "prepare fea", "calculix", "sonlu eleman hazırla", "analiz hazırla"),
    ("运行有限元", "跑有限元", "求解", "fea run", "run fea", "sonlu eleman çalıştır", "çöz"),
    ("收敛", "convergence", "yakınsama"),
    ("制造性检查", "可制造性", "制造性", "制造检查", "加工", "machining", "dfm", "üretilebilirlik", "imalat", "işleme"),
    ("设计规则", "设计审计", "设计检查", "电机选型", "扭矩核验", "design audit", "design rules", "motor sizing", "drc", "tasarım denetimi", "tasarım kuralları", "motor seçimi", "tork doğrulama"),
    ("高级几何", "曲面审查", "advanced geometry", "ileri geometri"),
    ("放样", "loft"),
    ("曲面", "加厚", "knit", "thicken", "surface", "yüzey", "kalınlaştır"),
    # Kablolama ve güzergâh
    ("线缆", "布线", "管路", "routing", "cable", "kablolama", "güzergâh", "kablo"),
    ("布线检查", "管路检查", "routing review", "güzergâh incelemesi", "kablolama denetimi"),
    ("布线预检", "routing preflight", "güzergâh ön kontrolü"),
    # Ortam ve servisler
    ("连接软件", "连接solidworks", "连接", "connect solidworks", "connect", "solidworks bağlan", "bağlan"),
    ("接口查证", "查询api", "api文档", "接口签名", "接口参数", "api lookup", "api signature", "lookup api", "api doğrula", "api dokümantasyonu", "arayüz imzası", "arayüz parametreleri"),
    ("版本信息", "版本号", "版本", "revision", "version", "solidworks version", "sürüm bilgisi", "sürüm numarası", "sürüm"),
    ("当前文档", "活动文档", "打开的文档", "已打开的文档", "文档列表", "文档状态",
     "open documents", "active document status", "document status", "current document", "geçerli belge", "etkin belge", "açık belgeler", "belge listesi", "belge durumu"),
    ("健康检查", "环境诊断", "依赖检查", "health check", "sağlık kontrolü", "ortam tanılaması", "bağımlılık kontrolü"),
    ("恢复", "卡住", "卡死", "recover", "blocked", "kurtar", "takıldı", "bloke"),
    ("后端选择", "后端", "语言后端", "语言", "backend", "language backend", "arka uç seçimi", "arka uç", "dil arka ucu", "dil"),
    ("插件状态", "插件", "加载项", "addin", "add-in", "eklenti durumu", "eklenti"),
    ("原生几何", "实体名称", "native geometry", "yerel geometri", "gövde adı"),
    ("圆截面扫描", "扫描", "圆截面", "sweep", "sweeps", "round sweep", "round sweeps", "süpürme", "yuvarlak süpürme", "dairesel süpürme"),
    ("导入step", "导入零件", "import step", "import part", "step içe aktar", "parça içe aktar"),
    ("开放格式", "写出step", "写出", "写一个", "write out", "write open format", "open format", "açık biçim", "step yaz", "yaz"),
    ("dxf预览", "预览场景", "preview scene", "dxf preview", "dxf önizleme", "önizleme sahnesi"),
    ("读取产物", "取回产物", "取回", "产物", "artifact", "ürünü oku", "ürünü al", "ürün"),
    # Dosya biçimleri
    ("step", "stp"),
    ("iges", "igs"),
    ("stl",),
    ("pdf",),
    ("dxf",),
)

_WORDS = re.compile(r"[a-z0-9çğıöşü]+|[\u3400-\u9fff]+", re.IGNORECASE)

# Kullanıcı "görüntüle/kontrol et" dediğinde okuma araçları, "oluştur/dışa aktar" dediğinde yazma araçları istenir;
# bu yalnızca küçük bir artı/eksi uygular ve niyet ile kavram kanıtı çatıştığında kullanıcının gerçekte yapmak istediği eyleme yönelir.
_READ_INTENT = (
    "查看", "检查", "读取", "审视", "审查", "列出", "获取", "查询", "哪些", "有没有",
    "是否", "多少", "list", "inspect", "check", "read", "review", "show", "query", "get",
    "görüntüle", "kontrol", "oku", "incele", "listele", "al", "sorgula", "hangi", "var mı",
)
_WRITE_INTENT = (
    "创建", "新建", "添加", "生成", "导出", "保存", "修改", "更新", "设置", "删除", "关闭",
    "替换", "导入", "画", "写入", "运行", "打包", "切换", "加上", "加重", "改成", "建模",
    "write", "create", "add", "generate", "export", "save", "update", "set", "delete",
    "close", "replace", "import", "run", "build", "pack", "activate", "fix",
    "oluştur", "ekle", "üret", "dışa aktar", "kaydet", "güncelle", "ayarla", "sil", "kapat",
    "değiştir", "çalıştır", "paketle",
)
_READ_VERBS = frozenset({
    "inspect", "list", "check", "validate", "review", "preflight", "status", "read",
    "resolve", "health", "audit", "describe", "search",
})


def _is_read_like(tool_name: str) -> bool:
    # Fiil ismin ilk sözcüğü olmayabilir (ör. interference_check); sözcük sözcük kontrol etmek daha güvenlidir.
    return any(part in _READ_VERBS for part in tool_name.split("_")[1:])


# Yalnızca genel eylem içeren ve CAD nesnesi olmayan sorgular (ör. "WeChat'i aç") hiçbir aracı eşleştirmemelidir;
# bu eylem sözcükleri yalnızca nesne sözcüğüyle birlikte göründüğünde kanıt sayılır.
_OBJECTS = (
    "文档", "文件", "零件", "装配", "工程图", "图纸", "模型", "实体", "特征", "草图",
    "配置", "尺寸", "材料", "属性", "视图", "组件", "马达", "算例", "求解器", "线缆",
    "管路", "曲面", "表面", "路径", "bom",
    "belge", "dosya", "parça", "montaj", "resim", "çizim", "model", "gövde", "özellik", "eskiz",
    "yapılandırma", "ölçü", "malzeme", "nitelik", "görünüm", "bileşen", "motor", "çalışma", "çözücü", "kablo",
    "güzergâh", "yüzey", "yol",
)
_GENERIC_ACTION_GROUPS = frozenset({
    "打开文件", "保存文件", "关闭文档", "新建文档", "预览",
})


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _contains(text: str, term: str) -> bool:
    term = _normalize(term)
    if not term:
        return False
    if re.search(r"[\u3400-\u9fff]", term):
        return term in text
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _metadata(tool: Any) -> dict[str, Any]:
    if isinstance(tool, Mapping):
        value = dict(tool)
    elif hasattr(tool, "model_dump"):
        value = tool.model_dump(by_alias=True, exclude_none=True)
    else:
        raise TypeError("Araç meta verisi bir sözlük veya MCP araç nesnesi olmalıdır")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Araç adı boş olmayan bir dize olmalıdır")
    # FastMCP'nin Tool iç alanı parameters, protokol alanı ise inputSchema olarak adlandırılır; ikisi tek bir alanda birleştirilir.
    if "inputSchema" not in value and "parameters" in value:
        value["inputSchema"] = value.pop("parameters")
    return copy.deepcopy(value)


class ToolCatalog:
    """Kayıt defterinden bir kez anlık görüntü oluşturur; araç listesi güncellendiğinde çağıran tarafından yeniden oluşturulur."""

    def __init__(self, tools: Sequence[Any], *, read_names: Collection[str] | None = None):
        self._tools: dict[str, dict[str, Any]] = {}
        self._name: dict[str, str] = {}
        self._text: dict[str, str] = {}
        # Politika katmanı okuma/yazma sınıflandırması sağlıyorsa o esas alınır; aksi halde isimdeki fiillere göre tahmine dönülür.
        self._read_names = None if read_names is None else frozenset(read_names)
        for item in tools:
            tool = _metadata(item)
            name = tool["name"]
            if name in self._tools:
                raise ValueError(f"Yinelenen araç adı: {name}")
            self._tools[name] = tool
            self._name[name] = _normalize(name)
            self._text[name] = _normalize(
                " ".join(str(tool.get(k) or "") for k in ("name", "title", "description"))
            )

    def describe(self, name: str) -> dict[str, Any] | None:
        """Bağımsız bir kopya döndürür, tam Schema ve özgün ek açıklamaları korur; bilinmeyen ad için None döndürür."""
        item = self._tools.get(name)
        return copy.deepcopy(item) if item is not None else None

    def _is_read(self, name: str) -> bool:
        if self._read_names is None:
            return _is_read_like(name)
        return name in self._read_names

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Kompakt adaylar döndürür; adların çalıştırılabilmesi için çağıran tarafından ayrıca doğrulanması ve yetkilendirilmesi gerekir."""
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError("Arama içeriği 1 ile 512 karakter arasında olmalıdır")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("Sonuç sayısı 1 ile 20 arasında bir tam sayı olmalıdır")
        q = _normalize(query)
        groups = [group for group in _CONCEPTS if any(_contains(q, term) for term in group)]
        if not any(_contains(q, term) for term in _OBJECTS):
            groups = [group for group in groups if group[0] not in _GENERIC_ACTION_GROUPS]
        words = {w for w in _WORDS.findall(q) if len(w) >= 2}
        # Ürün adı çoğu araç adında geçtiğinden, tanımlanmış belirli işlem kavramlarını bastırmamalıdır.
        if groups:
            words.discard("solidworks")
        # Yalnızca tek yönlü niyet ağırlıklandırılır; "kontrol et ve düzelt" gibi karışık isteklerde yön tahmin edilmez.
        read_intent = any(_contains(q, term) for term in _READ_INTENT)
        write_intent = any(_contains(q, term) for term in _WRITE_INTENT)
        intent = 0 if read_intent == write_intent else (1 if read_intent else -1)
        matches: list[tuple[int, str]] = []
        for name, text in self._text.items():
            normalized_name = self._name[name]
            score = 1000 if q == normalized_name else 0
            # Araç adı eşleşmesi açıklama eşleşmesinden daha ayırt edicidir: Çince komut adları çoğunlukla yalnızca isimde geçer.
            if len(q) >= 3 and _contains(normalized_name, q):
                score += 30
            elif len(q) >= 3 and _contains(text, q):
                score += 20
            # Her kavram grubu en fazla bir kez puan ekler, böylece eş anlamlı yığılarak puan şişirilmez.
            for group in groups:
                if any(_contains(normalized_name, term) for term in group):
                    score += 18
                elif any(_contains(text, term) for term in group):
                    score += 8
            for word in words:
                if _contains(normalized_name, word):
                    score += 6
                elif _contains(text, word):
                    score += 1
            # Ürün adı yalnızca hâlihazırda eşleşme kanıtı olan adayların sıralamasında kullanılır; tek başına ilgisiz araçları getiremez.
            if groups and score and _contains(q, "solidworks") and _contains(normalized_name, "solidworks"):
                score += 1
            # Yalnızca kanıtı olan adaylar ayarlanır; niyet tek başına ilgisiz araçları sonuca çekmemelidir.
            if score and intent:
                score += 6 if self._is_read(name) == (intent > 0) else -6
            if score:
                matches.append((score, name))
        matches.sort(key=lambda item: (-item[0], item[1]))
        result = []
        for score, name in matches[:limit]:
            description = str(self._tools[name].get("description") or "").strip().split("\n", 1)[0]
            result.append({"name": name, "description": description[:240], "score": score})
        return result
