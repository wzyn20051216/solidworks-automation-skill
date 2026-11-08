# SolidWorks Automation alt yetenek matrisi

Bu depo "büyük depo + çoklu alt yetenek" organizasyon biçimini benimser. Kök yetenek `solidworks-automation` SolidWorks bağlantısı, doküman yönetimi, modelleme API'si, dışa aktarma, öz-inceleme ve MCP Server sunar; özel yetenekler `subskills/` altında yer alır ve her alt yetenek kendi içinde `SKILL.md`, `README.md`, `manifest.yaml`, betikler, referans belgeleri ve örnekler barındırır.

Bu yapı çoklu yetenek depolarının yönetim biçimini örnek alır: kök README genel giriş, kurulum yöntemi, yetenek haritası ve çağrı yönlendirmesinden sorumludur; her alt yetenek ise belirli bir istikrarlı iş akışından sorumludur.

## Yetenek dizini

| Alt yetenek | Durum | Kullanım | Giriş |
|---|---|---|---|
| `solidworks-vibecad` | experimental | Doğal dil gereksinimi -> parametrik tasarım planı, üretim kuralı denetimi, yürütme özeti, inceleme kapısı | `subskills/solidworks-vibecad/SKILL.md` |
| `solidworks-fillet-chamfer-cnc` | stable | CNC montaj yuvası, parametre/çarpışma ön kontrolü, anlamsal kenar seçimi, sınırlı ölçü düşürme, delik yuvaları ve yuvarlatılmış cepler | `subskills/solidworks-fillet-chamfer-cnc/SKILL.md` |
| `solidworks-threaded-holes` | stable | M3-M12 dişli delikler, kılavuz delikleri, delik ağzı pahı, diş özellikleri ve STEP çıktısı | `subskills/solidworks-threaded-holes/SKILL.md` |
| `solidworks-engineering-drawing` | pilot | GB/T birinci açı parça resmi/montaj resmi, ölçü zinciri, delik tablosu, BOM, PDF/BMP kanıtı ve üretim teslim incelemesi | `subskills/solidworks-engineering-drawing/SKILL.md` |
| `autocad-automation` | stable | AutoCAD DWG/DXF iki boyutlu çizim, çizgi sanatı vektörleştirme, katman/metin/ölçülendirme işleme, dışa aktarma ve çizim öz denetimi | `subskills/autocad-automation/SKILL.md` |

## Önerilen yönlendirme

```text
Doğal dil gereksinimi
  -> solidworks-vibecad
  -> yapılandırılmış design_plan.json
  -> parça türüne göre özel alt yeteneğe yönlendir
  -> teknik resim gereksinimi solidworks-engineering-drawing'e bağlanır
  -> kök yetenek scripts/sw_*.py SolidWorks COM'u yürütür
  -> sw_review.run_review() incelemesi
```

## Hangi durumda hangisi kullanılır

### solidworks-vibecad

Kullanıcı şöyle der:

- "Bu gereksinimi parametrikleştir"
- "Bir text-to-CAD iş akışı yap"
- "Sektör bilgi tabanını ve istem şablonlarını sabitle"
- "Önce doğrudan modelleme yapma, önce tasarım planı çıkar"

Kullanım:

```text
subskills/solidworks-vibecad/SKILL.md
```

### solidworks-fillet-chamfer-cnc

Kullanıcı şöyle der:

- "CNC montaj yuvası"
- "Bağlantı bloğu/destek"
- "Çok sayıda yuvarlatma ve pah"
- "Ağırlık azaltma cebi/uzun yuvarlak yuva/havşalı plaka"

Kullanım:

```text
subskills/solidworks-fillet-chamfer-cnc/SKILL.md
```

### solidworks-threaded-holes

Kullanıcı şöyle der:

- "M6 dişli delik"
- "Diş açma deliği"
- "Kılavuz deliği"
- "Hole Wizard / ThreadFeatureData / CosmeticThread"

Kullanım:

```text
subskills/solidworks-threaded-holes/SKILL.md
```

### autocad-automation

Kullanıcı şöyle der:

- "Bunu AutoCAD ile çiz"
- "DWG veya DXF oluştur/değiştir"
- "Bu görseldeki çizgi sanatını CAD'e dönüştür"
- "Katmanları, metinleri, blokları, harici referansları toplu denetle"
- "AutoCAD yerel önizlemesini dışa aktar ve incele"

Kullanım:

```text
subskills/autocad-automation/SKILL.md
```

### solidworks-engineering-drawing

Kullanıcı şöyle der:

- "Parça resmi/montaj resmi/teknik resim oluştur"
- "GB/T, birinci açı izdüşümüne göre çiz"
- "Ölçü zincirini, delik tablosunu, BOM'u, başlık bloğunu tamamla"
- "Teknik resmin üretime teslim edilip edilemeyeceğini incele"

Kullanım:

```text
subskills/solidworks-engineering-drawing/SKILL.md
```

Bu alt yetenek kök yetenek, VibeCAD, delik yuvası/CNC alt yeteneği veya mühendislik orkestratörü tarafından ihtiyaç halinde bağlanabilir; diğer alt yeteneklerin ona ters bağımlılığı yoktur.

Not: Sıradan "resme bakarak CAD çizme" işleminin son sürümü yalnızca orijinal görselin vektörleştirilmiş çizgilerini korur; elle tahmin edilen dış konturları, yüz elipslerini, Logo üçgen çizgilerini, su dalgası çizgilerini, yer tutucu metinleri veya görsel içi inceleme açıklamalarını korumaz.

## Alt yetenek dizin standardı

Yeni bir alt yetenek eklerken şunları koruyun:

```text
subskills/<skill-name>/
├── SKILL.md             # AI çağrı girişi ve iş akışı
├── README.md            # insan okuma girişi
├── manifest.yaml        # dizin meta verileri
├── scripts/             # yeniden kullanılabilir betikler
├── references/          # ölçülen deneyimler, tuzaklardan kaçınma ve API açıklamaları
├── examples/            # örnek girdi/çıktı
└── agents/              # isteğe bağlı, farklı istemci yapılandırmaları
```

## Kalite kapıları

Her alt yetenek şunları açıklamalıdır:

- Uygun senaryolar ve uygun olmayan senaryolar.
- Kök yeteneğin hangi `scripts/sw_*.py` betiklerinin çağrılması önerilir.
- SolidWorks API'sinin istikrarlı stratejisi ve düşürme stratejisi.
- Çıktı dosyaları ve inceleme gereksinimleri.
- Yeni karşılaşılan tuzaklar `references/` altında biriktirilmelidir.
