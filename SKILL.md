---
name: solidworks-automation
description: "SolidWorks CAD otomasyon yeteneği; öncelikli olarak doğrulanmış parça, delik/kanal, montaj, teknik resim, dışa aktarma ve teslim incelemesini kapsar; tüm yetenek seviyeleri capabilities.yaml esas alınır, doğrulanmamış yetenekler mutlaka elle incelemeden geçmelidir."
metadata: { "openclaw": { "homepage": "https://github.com/wzyn20051216/solidworks-automation-skill", "os": ["win32"], "requires": { "anyBins": ["python", "py"] } } }
---

# SolidWorks Otomasyon Yeteneği

## Hızlı Başlangıç

### Ortam gereksinimleri

- Windows sistemi; yerel SolidWorks işlemleri için destek ve kabul hedefi SolidWorks 2026'dır, açık format başsız yazma CAD yazılımı kurulumunu gerektirmez
- Python 3.10+; yerel Windows CAD otomasyonu ayrıca `pywin32` / `comtypes` gerektirir
- MCP/araçsallaştırılmış çağrılar `mcp` / `pydantic` gerektirir
- Teknik resim nihai teslim incelemesi `PyMuPDF` gerektirir; SolidWorks'ten PDF dışa aktarıp gerçek ölçü metni sınırlarını geri okur, `requirements.txt` içinde yer alır
- GLB/GLTF/OBJ/STL ağ referans modellerini işlerken ayrıca `trimesh` / `pygltflib` / `numpy` / `Pillow` gerekebilir
- OpenClaw üzerinden kullanıyorsanız, yetenek dizininin `~/.openclaw/skills/solidworks-automation/` veya `~/.agents/skills/solidworks-automation/` altında olduğundan emin olun

### Giriş öz denetimi

Tüm Agent'lar SolidWorks otomasyonunu yürütmeden önce yetenek öz denetimini çalıştırır:

```bash
python SKILL_DIR/scripts/sw_preflight.py
```

Masaüstü veya CLI yürütmesinden önce ortam tanılamasının çalıştırılması önerilir:

```powershell
python SKILL_DIR/scripts/cad_studio.py doctor
```

`capabilities.yaml`, Skill, MCP, kuyruk ve UI'nin ortak kullandığı yeteneğin tek doğruluk kaynağıdır. Yetenek seviyeleri `verified`, `pilot`, `reference_only` veya `not_implemented`'tir; son ikisi gözetimsiz teslimat olarak kullanılamaz. Bu liste ayrıca Python, C# PIA/Add-in, yerel C++, SWBasic, OCCT ve harici çözücülerin atomik işlem yönlendirmesini yönetir; yürütmeden önce `python scripts/backend_router.py --list` ile sorgulanabilir, kurallar için bkz. `references/language-backend-routing.md`.

### Çoklu giriş ve çoklu backend

- CAD Studio ile Skill/CLI/MCP eş düzeyli girişlerdir; Automation Job, NeutralCadDocument, Preview Manifest, Evidence Graph ve yetenek listesini ortak kullanır.
- SolidWorks/AutoCAD algılanmadığında yalnızca `SLDPRT/SLDASM/SLDDRW/DWG` gibi yerel formatlar engellenir; açık format görevleri öncelikli olarak `headless_open_format_writing`'e yönlendirilir.
- Tasarım kuralı incelemesi veya vidalı mil/kayış motoru torku ön taraması gerektiğinde `references/design-rule-check.md` ve `references/drive-sizing.md` okunur; kullanıcının sağladığı veya doğrulanmış olarak toplanan nötr belge girdi olarak alınır; eksik kanıt `review_required` olarak işaretlenir ve sonuç mühendis tarafından incelenmelidir.
- Delme paneli delik konumlarını tanımlamak veya teknik resim adaylarını planlamak gerektiğinde `subskills/solidworks-engineering-drawing/references/drilling-panel-gdt.md` okunur; delik tipi, referans ve tolerans geometriden tahmin edilemez, aday spesifikasyonlar doğrulanmış teknik resim olarak sunulamaz.
- Kullanıcı referans, bileşik tolerans çerçevesi veya GD&T otomatik yerleştirmesi istediğinde `subskills/solidworks-engineering-drawing/references/native-gdt.md` okunur. Mevcut teknik resimlerde önce `scripts/sw_gdt_copy.py --source resim.slddrw --inspect` ile hedef belirlenir, ardından yeni bir kopya yazılır; modelden yeni teknik resim çıkarmak için mevcut MCP `solidworks_generate_drawing` veya `scripts/sw_drawing_package.py` kullanılır ve yapılandırılmış ölçüler, temel ölçüler, referanslar ile tek çerçeve/bileşik çerçeve gereksinimleri sağlanır. SW2026 kaydedip yeniden açarak yerel ilişkililiği, tüm katmanları ve referans malzeme süslemelerini doğrular, kaynak dosya korunur ve sonuç görsel olarak incelenmelidir; eski serbest metinlerden yerleştirme tahmin edilmez.
- Ortak referanslar, alt referans grupları, projeksiyon tolerans bölgeleri, profil ofseti, CZ/SZ, yerel kapsamlar ve diğer ileri GD&T için `subskills/solidworks-engineering-drawing/references/gdt-extended-options.md` okunmaya devam edilir ve aynı araç üzerinden yapılandırılmış üyeler ile `options` gönderilir; her üye doğrulanmalı ve yazıldıktan sonra kaydedip yeniden açarak tüm yeni anlamlar doğrulanmalıdır.
- Kaydedilmiş bir modelde görüntülenen ölçü toleranslarını çıkarmak için `scripts/sw_tolerance_extract.py` kullanılır; yalnızca geçerli yapılandırmayı okur, sonuçlar gizli ölçüleri veya diğer yapılandırmaları kapsamaz; açı, montaj ve teknik resim okumaları hâlâ doğrulanmalıdır.
- Özelliğe göre toplu yeniden adlandırma gerektiğinde önce `scripts/sw_file_rename.py` ile salt okunur önizleme oluşturulur; sınırlı bağımsız parçalar için `scripts/sw_rename_copy.py`, tek yapılandırmalı iç içe montajlar için `scripts/sw_assembly_rename.py` yeni dizinde kopya oluşturup yeniden açarak doğrular. Kaynak dosyalar ve harici kullanım konumları değişmez; teknik resimler, Toolbox, çoklu yapılandırma ve diğer doğrulanmamış referanslar hâlâ engellenir, ayrıntılar için bkz. `references/rename-preview.md`.
- Zincir dişlisi görünümü veya geometri gösterimi gerektiğinde `references/sprocket.md` okunur ve yeni boş bir parça içinde yaklaşık katı model oluşturmak için `scripts/sw_sprocket.py` kullanılır; bu model zincir kavraması veya üretim gereksinimleri açısından doğrulanmamıştır ve üretim seviyesinde standart zincir dişlisi olarak kullanılamaz.
- Açık uçlu eşit hatveli dairesel telli yay katı modeli gerektiğinde `references/spring.md` okunur ve `scripts/sw_spring.py` kullanılır; girdi yüksekliği katı serbest yüksekliği değil, helis merkez hattının eksenel hareketidir; malzeme, uçlar ve mühendislik performansı mutlaka incelenmelidir.
- Başsız yazma `scripts/headless_cad_writer.py` kullanır; OCCT/OCP yalıtılmış süreç gerçek olarak STEP, IGES, BREP, STL, OBJ, GLB yazar, iki boyutlu backend DXF, SVG, PDF, PNG yazar ve geometri ile SHA-256 kanıtı üretir.
- DXF teslimatı ayrıca `preview_scene` üretir; mevcut DXF, `python scripts/cad_studio.py preview-dxf --input drawing.dxf --output drawing.scene.json` veya MCP `cadstudio_build_dxf_preview_scene` ile sınırlı bir PreviewScene'e dönüştürülebilir. Bu komut yalnızca beyaz listedeki varlıkları okur ve eski dosyaların üzerine yazmayı reddeder.
- OCCT şu anda kutu, silindir, boolean birleştirme, silindir delik kesme, kurallı/sınırlı düzgün Loft, düz çizgi/tek yay Sweep, kapalı kabuk Knit ve açık yüz Thicken kapsar; karmaşık yollar, kendiyle kesişen ofset veya eksik OCP çalışma zamanında `blocked` kalır. Uzantı değiştirerek veya boş dosyayla destek sahtelemek yasaktır.
- `delivery-preview` yalnızca geçerli görevin gerçek ürünlerini gösterebilir; sabit örnekler `demo-showcase` ve `isDemo: true` olarak işaretlenmelidir ve teslim kararına giremez.

Kurallar:

1. `comtypes` / `win32com` / `pythoncom` eksikliği algılandığında varsayılan olarak `python -m pip install "pywin32>=305" "comtypes>=1.2.0"` çalıştırılarak bağımlılıklar tamamlanır; kurulum başarısız olursa neden ve elle yöntem açıklanır.
2. `SW_AUTO_INSTALL_DEPENDENCIES=off` ortam değişkeni veya `sw_preflight.py --no-install` otomatik kurulumu kapatabilir.
3. SolidWorks kurulumu veya COM kaydı algılanmadığında yerel SolidWorks işlemleri durdurulur; yerel format zorunlu değilse ve `fallbackPolicy=allow_open_formats` ise başsız açık format backend'i yürütülmeye devam edilir, tüm görev başarısız olarak yanlış işaretlenmez.

### Python bağımlılığı hatırlatması

Bağımlılıkları göreve göre asgari düzeyde kurun; normal parça modellemede ağ dönüştürme kitaplıklarını zorla kurmayın; teknik resim teslimatı için standart `requirements.txt` içindeki PyMuPDF gerekir:

```powershell
# Çekirdek SolidWorks COM otomasyon bağımlılıkları
python -m pip install -r SKILL_DIR\requirements.txt

# Yalnızca GLB/GLTF/OBJ/STL ağ denetimi, ölçekleme veya dönüştürme gerektiğinde kurun
python -m pip install -r SKILL_DIR\requirements-mesh.txt
```

GLB/GLTF/FBX/BLEND'i OBJ/STL'ye dönüştüren görevleri yürütmeden önce `importlib.util.find_spec()` ile
`trimesh`, `pygltflib`, `PIL` kullanılabilir mi diye denetleyin; eksik olduğunda önce kullanıcıya hangi kitaplıkların gerekli olduğunu ve amaçlarını bildirin, ardından kurun veya elle komut verin.

### SolidWorks'e bağlanma

```python
import sys; sys.path.insert(0, r"SKILL_DIR/scripts")
from sw_connect import mm
from sw_part import sketch, sketch_circle, extrude_boss
from sw_sketch_quality import fully_define_sketch
from sw_session import SolidWorksSession

with SolidWorksSession(version=2026) as session:
    model = session.new_part()

    with sketch(model, "Front Plane") as sketch_name:
        sketch_circle(model, 0, 0, mm(25))
        fully_define_sketch(model)

    if extrude_boss(model, sketch_name, mm(50)) is None:
        raise RuntimeError("Ekstrüzyon başarısız")
    if not session.save(model, r"C:\temp\cylinder.sldprt"):
        raise RuntimeError("Kaydetme başarısız")
    if not session.export(model, r"C:\temp\cylinder.step"):
        raise RuntimeError("Dışa aktarma başarısız")
```

> `SKILL_DIR` yerine bu yeteneğin gerçek kurulum yolunu yazın.

Model teslimatında krokinin kısıt durumu, ölçüleri ve ilişkileri geri okunmalıdır; toplu Fix'in tasarım parametrelerinin yerini alması yasaktır; kaydedip yeniden açtıktan sonra krokinin hedef özellik tarafından tüketildiği, kritik ölçülerin değiştirilebildiği ve delik konumlarının doğru kaldığı doğrulanmalıdır. Temel daire/dikdörtgen için `fully_define_sketch()` kullanılabilir; karmaşık krokilere tasarım ölçüleri ve ilişkileri açıkça belirtilmeli, ardından `inspect_model_sketches()` ile kabul edilmelidir; kanıt eksik olduğunda elle inceleme korunur.

Oturum bağlamı yalnızca bu turda kaydedilen belgeleri ve aidiyeti doğrulanmış boş örnekleri temizler; belge bütçesine ulaşıldığında önce bu turun dosyaları işlenir. Yürütme başarısız olarak işaretlendiğinde, yeniden oluşturma başarısız olduğunda, denetim sonucu bilinmediğinde veya elle inceleme henüz tamamlanmadığında görev tamamlandı olarak ilan edilemez. Uzak MCP `artifact_refs` üzerinden PNG veya orijinal dosyayı geri alır ve SHA-256'yı doğrular; kurallar için bkz. `mcp-server/README.md`.

## Çekirdek İş Akışları

Kullanıcı gereksinimine göre ilgili modülü seçin:

| Gereksinim | Betik | Referans dokümanı |
|---|---|---|
| Giriş öz denetimi ve bağımlılık tamamlama | `scripts/sw_preflight.py` | `references/troubleshooting.md` |
| CAD'siz açık format yazma | `scripts/headless_cad_writer.py`, `scripts/cad_studio.py write-open-format` | `capabilities.yaml`, ortak CAD Core Schema |
| İleri yetenek/tip kitaplığı algılama | `scripts/sw_capability_probe.py` | `references/complex-mechanical-routing.md` |
| Python/C#/C++/SWBasic/OCCT backend seçimi | `scripts/backend_router.py` | `references/language-backend-routing.md`, `capabilities.yaml` |
| C# süreç içi Add-in ana makinesi, olaylar ve UI | `scripts/sw_addin_host.ps1`, `scripts/sw_addin_host.py` | `references/solidworks-addin-host.md` |
| Çok modelli makro üretim koruması | `scripts/sw_macro_guard.py` | `references/openclaw.md` |
| Kullanışlı oturum API'si | `scripts/sw_session.py` | - |
| Bağlantı ve belge yönetimi | `scripts/sw_connect.py` | - |
| Görünüm ve malzeme | `scripts/sw_appearance.py` | `references/appearance.md` |
| Parça modelleme (kroki+özellik) | `scripts/sw_part.py` | `references/part-modeling.md` |
| Standart dış alın düz dişli katı modeli | `scripts/sw_gear.py` | `references/gears.md` |
| Kör delik/havşa delik/havşalı delik/yarım daire uçlu kanal ve delik konumu kabulü | `scripts/sw_hole_features.py`, `scripts/sw_review.py` | `references/complex-hole-features.md`, `references/review.md` |
| Doğal dilden parametrik tasarım planı / VibeCAD | `subskills/solidworks-vibecad/scripts/plan_from_brief.py` | `subskills/solidworks-vibecad/SKILL.md`, `subskills/solidworks-vibecad/README.md` |
| Çok sayıda yuvarlatma/pah CNC işlenmiş parça | `subskills/solidworks-fillet-chamfer-cnc/scripts/create_cnc_mount_template.py`; ileri yuvarlatmalar için `verify_advanced_fillets.py` | `subskills/solidworks-fillet-chamfer-cnc/SKILL.md`, `subskills/solidworks-fillet-chamfer-cnc/references/cnc-fillet-chamfer-lessons.md` |
| Vida delikleri/dişli delikler, kılavuz çekme ön deliği | `subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py` | `subskills/solidworks-threaded-holes/SKILL.md`, `subskills/solidworks-threaded-holes/references/threaded-hole-lessons.md` |
| AutoCAD DWG/DXF iki boyutlu çizim, çizgiden CAD'e dönüştürme, toplu çizim değiştirme | `subskills/autocad-automation/scripts/acad_draw.py`, `subskills/autocad-automation/scripts/acad_review.py` | `subskills/autocad-automation/SKILL.md`, `subskills/autocad-automation/references/troubleshooting.md` |
| Montaj işlemleri, dişli bağlantı/menteşe/sürüklenebilir hareket eşleştirmesi | `scripts/sw_assembly.py` | `references/assembly.md` |
| Motion Study hareket simülasyonu, döner motor ve sonuç denetimi | `scripts/sw_motion.py` | `references/motion-study.md`, `references/complex-mechanical-routing.md` |
| Teknik resim çıkarma | `scripts/sw_drawing.py` | `references/drawing.md` |
| Dosya dışa aktarma | `scripts/sw_export.py` | `references/export.md` |
| Yapılandırma ailesi oluşturma/etkinleştirme, parametre değiştirme ve özel özellikler | `scripts/sw_document_data.py` | `references/advanced.md` |
| Montaj BOM CSV ve Pack and Go | `scripts/sw_delivery.py` | `references/export.md` |
| OBJ/STL yüksek aslına uygun ağ referansı içe aktarma | `scripts/sw_import_mesh_reference.py` | `references/mesh-reference-import.md` |
| Sonuç öz incelemesi | `scripts/sw_review.py` | `references/review.md` |
| Anlamsal varlık referansı | `scripts/sw_entity_reference.py` | Face1/Edge1 ve ekran koordinatlarının kademeli olarak yerine geçer |
| DFM üretim riski incelemesi | `scripts/dfm_review.py`, `scripts/dfm_profiles.py`, `scripts/cad_studio.py check-dfm` | Tedarikçi profili, B-Rep kanıtı, işleme, sac metal, lazer kesim, 3D baskı ve enjeksiyon bildirim tipi kural denetimi |
| Routing nötr inceleme ve ön kontrol | `scripts/routing_review.py`, `scripts/cad_studio.py check-routing`, `scripts/cad_studio.py routing-preflight` | Uç noktalar, segmentler, uzunluk, bükme yarıçapı, çarpışma/boşluk, destek, Routing BOM; yerel yazma eklenti/lisans kanıtını beklemelidir |
| FEA ön kontrol, girdi ve sınırlı çözüm | `scripts/fea_analysis.py`, `scripts/fea_convergence.py`, `scripts/cad_studio.py fea-preflight/prepare-fea/run-fea/run-fea-convergence` | CalculiX 2.23 doğrulanmış doğrusal/doğrusal olmayan statik, plastik, yüzey teması, son adım COPEN/CPRESS/CSLIP ve doğrusal/doğrusal olmayan ağ yakınsaması; tümü hâlâ mühendislik incelemesi gerektirir |
| Karmaşık yüzeyler ve kalıp | `scripts/advanced_geometry.py`, `scripts/advanced_geometry_ocp.py`, `scripts/advanced_surface_ocp.py`, `scripts/cad_studio.py review-advanced-geometry/create-ocp-loft/create-ocp-surface` | Kurallı/düzgün Loft, sınırlı Sweep/Knit/Thicken yazılabilir ve B-Rep yeniden açılabilir; G1/G2 ve eğrilik yarıçapı yalnızca ayrık örnekleme kanıtı döndürür |
| Yerel MCP Server | `mcp-server/server.py` | `mcp-server/README.md`, `references/mcp-server.md` |
| MCP protokol doğrulaması | `scripts/validate_mcp.py` | `mcp-server/README.md` |
| Sürümlenmiş API doğrulaması | `scripts/sw_api_lookup.py` | `references/api-lookup.md` |
| OpenClaw ile SolidWorks kontrolü | - | `references/openclaw.md` |
| Sac metal/kaynaklı parça/simülasyon/özellikler | - | `references/advanced.md` |
| Kurumsal Agent / yerel öncelikli ve bulut RAG | `apps/desktop/cad_workbench/knowledge_retrieval.py` | `references/enterprise-agent-rag.md` |
| Codex/Claude/Gemini/OpenCode/LM Studio Provider Adapter | `apps/desktop/cad_workbench/agent_providers.py` | `references/agent-provider-architecture.md` |
| Kapsamlı makine mühendisliği DAG otomatik orkestrasyonu | `apps/desktop/cad_workbench/engineering_orchestrator.py` | `references/complex-mechanical-routing.md` |
| Sık karşılaşılan hata giderme | - | `references/troubleshooting.md` |

Pack and Go, SW2026 SP01.1'deki temel iki parçalı montaj üzerinde art arda üç kez yerel regresyondan geçti: `SavePackAndGo()` gerçek olarak montajı ve iki parçayı çıkarır, durum kodlarının tümü 0'dır, geçici geri dönüş kullanılmamıştır. Bazı sürümlerde `GetDocumentNames()` kaydetmeden önce yalnızca üst düzey dosyaları numaralandırabilir; montajın yerel parçalarını tamamlamak için `AddExternalDocuments` kullanılmamalı, önce yerel kaydetme yürütülmeli, ardından gerçek diske yazılan bağımlılıklar denetlenmelidir. Diske yazma hâlâ bağımlılık eksikse, `scripts/sw_delivery.py::pack_and_go()` varsayılan olarak `GetDependencies2` ile manifest ve SHA-256 içeren bir `pilot` geçici paketi üretir; katı yerel anlam gerektiğinde `fallback_policy="blocked"` kullanın. Harici referanslar, Toolbox, yapılandırmalar ve teknik resimler yine elle incelenmelidir, bu nedenle genel yetenek `pilot` kalır.

## OpenClaw işbirliği yöntemi

1. Önce SolidWorks sürümünü, arayüz dilini, girdi dosyası yollarını, çıktı yollarını ve hedef işlemi (modelleme / montaj / teknik resim / dışa aktarma) doğrulayın.
2. `{baseDir}/scripts` altındaki mevcut modülleri öncelikli olarak yeniden kullanın, COM bağlantı mantığını elle yeniden yazmayın.
3. OpenClaw'ın `exec` / `shell` yeteneğinde kısa, tek seferlik Python betikleri çalıştırın; asgari içe aktarma kümesi aşağıdaki gibidir:

```python
import sys
sys.path.insert(0, r"{baseDir}/scripts")
from sw_connect import connect_solidworks, mm, deg, new_document
```

4. Yürütmeden sonra döndürülen nesnenin `None` olup olmadığını, kaydetme/dışa aktarmanın başarılı olup olmadığını ve çıktı dosyasının diske yazılıp yazılmadığını denetleyin.
5. Model oluşturduktan veya değiştirdikten sonra mutlaka sonuç öz incelemesi yapın: en az bir izometrik önizleme görüntüsü dışa aktarın, gerekirse ön/üst/sağ görünümleri dışa aktarın ve ekran görüntüsü veya BMP üzerinden geometrinin kullanıcının amacına uyup uymadığını görsel olarak denetleyin.
6. Daha eksiksiz bir OpenClaw iş akışı, istem örneği ve sorun giderme önerisi gerekiyorsa `references/openclaw.md` dosyasını okuyun.

## Kullanım akışı

1. Önce atomik işleme göre `backend_router.py` çalıştırın, ardından `preferredBackend`, `requiredOutputs`, `nativeFormatRequired` ve `fallbackPolicy` ile backend'i belirleyin; Python, C# veya SolidWorks'ün kesinlikle kullanılabilir olduğunu varsaymayın. Normal görevlerde Automation eşdeğeri arayüz önceliklidir; yalnızca yalnızca yönetilmeyen C++ tarafından desteklenen ham `I*` işaretçi anlamı açıkça gerektiğinde yerel C++'a yükseltin.
   Olay aboneliği, PropertyManagerPage, TaskPane veya uzun süreli UI `solidworks_addin_ui_events` rotasına gider, öncelikli olarak C# Add-in; HKLM kaydı, 64 bit TLB kaydı ve `host-status.json` denetlenmelidir, yalnızca `LoadAddIn=0` ile başarı iddia edilemez. SW2026'nın PMP Handler'ı public, COM görünür olmalı ve `IDispatch` class interface sunmalıdır.
2. Yerel SolidWorks formatı gerektiğinde `sw_preflight.py` çalıştırın; eksik bağımlılıklar varsayılan olarak otomatik kurulur, SolidWorks eksikse yalnızca yerel aşama engellenir.
3. Yerel format gerekmediğinde veya açık format geri dönüşüne izin verildiğinde `python scripts/cad_studio.py write-open-format --input model.cadstudio.json --out-dir output` çalıştırın.
4. Hızlı üretilebilirlik incelemesi gerektiğinde `python scripts/cad_studio.py check-dfm --input model.cadstudio.json --output output/dfm_report.json --process machining` çalıştırın; `--profile supplier.json` ve `--brep-evidence brep.json` desteklenir. Rapor malzeme, duvar kalınlığı, K faktörü, kesim aralığı, şekillendirme alanı veya istenen B-Rep kanıtından yoksunsa `blocked` döndürür; kurallar geçse de elle inceleme gerekir.
5. Yerel SolidWorks rotasında bağlantı, açma, yeni oluşturma, kaydetme ve dışa aktarmayı yönetmek için öncelikli olarak `SolidWorksSession()` kullanın; alt düzey kontrol gerektiğinde `sw_connect.py`, `sw_part.py` gibi fonksiyonları birleştirin.
6. Kullanıcı gereksinimi doğal dile yakın olduğunda, parametreler eksik olduğunda veya "sektör bilgi tabanı + istem şablonu + parametrik tasarım planı" gerektiğinde önce `subskills/solidworks-vibecad/SKILL.md` okuyun ve `design_plan.json` ile yürütme özetini üretin.
7. Çok sayıda yuvarlatma/pah içeren CNC parçaları, montaj yatakları, bağlantı blokları ve braketler için önce `subskills/solidworks-fillet-chamfer-cnc/SKILL.md` okuyun ve "temel gövde -> dış kontur yuvarlatma/pah -> delik/kanal kesme -> delik ağzı pahı -> inceleme" istikrarlı sırasına göre yürütün.
8. Vida delikleri, dişli delikler, kılavuz çekme delikleri, M3/M4/M5/M6/M8 kör veya geçiş delikleri görevleri için önce `subskills/solidworks-threaded-holes/SKILL.md` okuyun; varsayılan olarak "parametre/delik konumu doğrulama -> kılavuz çekme ön deliği -> Metric Tap gerçek Thread -> CosmeticThread/kanıt helisi geri dönüşü -> delik ağzı pahı -> yeniden oluşturma sonrası özellik kanıtı -> özellikler ve inceleme" istikrarlı rotasına göre yürütün. Hole Wizard, dış diş, inç/boru dişleri ve mevcut parçada delik değiştirme hâlâ pilot olarak işlenir.

**Dişli yönlendirme kapısı:** Kullanıcı "dişli çiz/modelle/oluştur" dediğinde önce `references/gears.md` okuyun, katı dişli gereksinimini Gear Mate ile değiştirmeyin. Yalnızca standart dış alın düz dişli ve modül, diş sayısı, basınç açısı, diş genişliği ve mil deliği biliniyorsa `scripts/sw_gear.py` kullanın; üretim görevlerinde parametreler uydurulamaz, yalnızca görsel demo yapılırken varsayılan değerler açıkça bildirilebilir. Helisel, konik, iç dişli, kremayer, sonsuz vida/sonsuz dişli, profil kaydırmalı veya üretim seviyesinde modifikasyon/boşluk mutlaka özel rotaya veya elle incelemeye yönlendirilmelidir, standart düz dişli betiğine zorla uygulanmaz. "Dişli bağlantı/aktarma/eşleştirme" ise `sw_assembly.add_gear_mate_by_cylinders()` rotasına gider.

9. Normal kör delik, geçiş deliği, silindirik havşa delik, konik havşalı delik, yarım daire uçlu kanal veya delik dizisi görevleri için `references/complex-hole-features.md` okuyun ve öncelikli olarak `scripts/sw_hole_features.py` çağırın; oluşturma parametresi kanıtı `collect_geometry_measurements()`, `validate_hole_positions()` ve kesit görünümü ile çapraz doğrulanmalıdır.
10. SolidWorks parça resmi, montaj resmi, GB/T teknik resim, ölçü zinciri, delik tablosu, BOM, başlık bloğu veya teknik resim inceleme görevleri için önce `subskills/solidworks-engineering-drawing/SKILL.md` okuyun; bu alt yetenek kök yeteneğin model, delik/kanal ve özellik kanıtlarını tüketir. AutoCAD'in DWG/DXF, iki boyutlu çizim, çizgiden CAD'e dönüştürme, toplu çizim değiştirme veya AutoCAD yerel önizleme görevleri için `subskills/autocad-automation/SKILL.md` okuyun. Mekanik/3D baskı delikli teslimatı üretilebilir teknik resim olarak ele alınmalıdır: tüm delikler, kanallar, arayüzler, su girişleri, vida delikleri ve vida sütunları için aynı anda spesifikasyon, miktar ve konumlandırma ölçüleri verilmelidir; çizim sıkışık olduğunda delik tablosu/kanal tablosu kullanın, kritik ölçülerin yerine uzun kılavuz çizgisi kullanmayın.
11. Kullanıcı gerçek bir ürün için "orijinal görünüm", "1:1 kopya", "konsept sürüme benzemiyor" dediğinde önce `references/mesh-reference-import.md` okuyun: herkese açık ağ/plan referansları önceliklidir, düşük aslına uygun elle yapılmış taslak üzerinde tekrar tekrar ince ayar yapmayın; OBJ/STL içe aktarmak gerektiğinde öncelikli olarak `scripts/sw_import_mesh_reference.py` kullanın.
12. VBA makrosunun mutlaka büyük bir model tarafından üretilmesi gerekiyorsa önce `sw_macro_guard.py` ile model yönlendirmesi, kod doğrulaması, yeniden deneme ve yerel şablon geri dönüşü yapın.
13. Dosyaları kaydetmek/dışa aktarmak için `session.export()` veya `sw_export.py` kullanın.
14. Önizleme görüntüsü dışa aktarmak ve öz inceleme yapmak için `sw_review.py` kullanın; GUI/masaüstü ekran görüntüsü yeteneği varsa SolidWorks görünümünü açıp ekran görüntüsüyle inceleyin.
15. Sac metal, kaynaklı parça, karmaşık yüzey, kalıp, Routing, Simulation/FEA, karmaşık Motion veya yapılandırma ailesi görevlerinde önce `sw_capability_probe.py` çalıştırın ve `references/complex-mechanical-routing.md` okuyun; Routing için `routing-preflight/check-routing`, FEA için `fea-preflight/prepare-fea/run-fea/run-fea-convergence`, karmaşık yüzeyler için `review-advanced-geometry/create-ocp-loft/create-ocp-surface` kullanın. FEA ve ileri yüzey çözümünün geçmesi hâlâ `review_required`'dır.
16. Kurumsal/proje mekanik bilgisi gerektiğinde `references/enterprise-agent-rag.md` okuyun; varsayılan olarak yalnızca yerel bilgi kullanılır, bulut RAG açıkça etkinleştirilmeli, `external_network` bildirilmeli ve elle onay tamamlanmalıdır.
17. Bir gereksinim aynı anda parça, delik/kanal/yuvarlatma, montaj Mate, Motion, teknik resim/BOM ve çok formatlı teslimat içindeki iki veya daha fazla mühendislik alanını kapsadığında `apps/desktop/cad_workbench/engineering_orchestrator.py` çağırarak aşamalı DAG üretin. Kritik CAD yazma işlemleri bağımlılığa göre sırayla yürütülmeli, her aşama ürünleri ve kabul kanıtlarını bağımsız olarak kaydetmelidir; yerel değişikliklerde yalnızca etkilenen aşamalar ve ardılları yeniden planlanır, tüm mühendislik işinin tek bir aşırı uzun Prompt'a sıkıştırılıp tek seferde tamamlandığının ilan edilmesi yasaktır.

### Mekanik teknik resim varsayılan temel çizgisi

Bundan sonra bu yeteneğin katıldığı tüm CAD/mekanik yapı/3D baskı projelerinde bu temel çizgiler varsayılan olarak uygulanır:

1. "Anlaşılabilir bir şema"yı "üretilebilir bir teknik resim" olarak görmeyin. Delik, kanal, arayüz, montaj deliği veya baskı muhafazası söz konusu olduğunda dış ölçüler, duvar/taban kalınlığı, delik/kanal spesifikasyonu ve konumlandırma ölçüleri mutlaka tamamlanmalıdır.
2. Kullanıcı "Çin'de yaygın format", "GB tarzı", "katı standart" istediğinde yerel makine teknik resim alışkanlıkları benimsenmelidir: standart kağıt boyutu/çerçeve/başlık bloğu, FangSong Çince, katmanlı çizgi tipleri, merkez çizgileri/kesikli çizgiler, gerçek ölçülendirme varlıkları ve teknik gereksinimler.
3. Uzun kılavuz çizgileri yalnızca yerel açıklama için kullanılabilir, ölçü zincirinin yerini alamaz; görünümler arası geçemez, delikleri, merkez çizgilerini, ölçü metinlerini bastıramaz veya başlık bloğuna giremez.
4. Yoğun delik/kanallar öncelikli olarak delik tablosu, kanal tablosu veya delik/kanal ayrıntı tablosuyla verilmelidir; tablo içinde konum, spesifikasyon, miktar ve konumlandırma açıkça yazılmalıdır; tablo konumlandırma ölçülerinden kaçınmanın bahanesi olamaz.
5. Teslimattan önce önizleme görüntüsü görsel olarak incelenmelidir; eksik ölçü, örtüşme, çizgi üzerine binme veya başlık bloğuna girme görüldüğünde önce yeniden çalışılıp sonra raporlanmalıdır.

### Yüksek aslına uygun görünüm/herkese açık ağ referans modeli

Kullanıcı otomobil, tüketici elektroniği, heykel gibi gerçek nesnelerin yüksek aslına uygun görünümünü istediğinde önce "görsel referans modeli" ile "mühendislik açısından üretilebilir parametrik model"i ayırın:

1. Kullanıcı "orijinal gibi" istiyorsa öncelikli olarak herkese açık 3D model/çok görünümlü plan isteyin veya bulun, kaynak, yazar, lisans ve indirme tarihini kaydedin; üretilenin resmî Class-A veya tarama düzeyinde bir model olduğunu iddia etmeyin.
2. `.glb/.gltf/.fbx/.blend` önce `.obj/.stl`'ye dönüştürülür; OBJ malzemeyi korumayı tercih eder, STL malzemesiz geri dönüş olarak kullanılır.
3. İçe aktarmadan önce sınırlayıcı kutu ile koordinat eksenlerini ve ölçeği doğrulayın, ardından gerçek nominal ölçülere göre ölçekleyin.
4. Python dönüştürme/ölçekleme gerekiyorsa önce `requirements-mesh.txt` içindeki isteğe bağlı bağımlılıkların kullanılabilir olduğunu doğrulayın; eksik olduğunda amacı açıklayın ve kurulumu önerin.
5. OBJ/STL'yi SolidWorks'e aktarırken `sw_import_mesh_reference.py` kullanın; kilit yazım `LoadFile4(path, "r", create_empty_dispatch_variant(), errors)`'tir, `OpenDoc6()` kullanmayın veya `LoadFile4()`'e `None` geçirmeyin.
6. Sonuç incelemesi dört görünümü ve kilit tanıma özelliklerini görmelidir; "önizleme boş değil" "kullanıcının belirttiği nesneye benziyor"un yerini alamaz.
7. Kullanıcı sonradan mühendislik açısından düzenlenebilir bir yapı istiyorsa ağ referansına dayalı parça bazlı tersine yeniden oluşturma yapılmalı ve ağdan içe aktarılan parçanın parametrik katı model olmadığı açıkça belirtilmelidir.

### Çok renkli görünüm gereksinimi

Model gövde, cam, lamba grubu, lastik, jant veya başka birden çok renk içerdiğinde:

1. `references/appearance.md` okuyun, tek biçimde `sw_appearance.py` kullanın, normal Python `list`'ini doğrudan COM malzeme özelliğine geçirmek yasaktır.
2. Kaynak parçada önce belge düzeyi renk ayarlanır; montajda geçersiz kılmak gerektiğinde bileşen düzeyi renk kullanılır.
3. Her ayarlamadan sonra `verify_appearance()` veya `apply_component_palette()` çağırıp RGB'yi geri okuyun; yalnızca setter dönüş değerini denetlemek geçmiş sayılmaz.
4. Kaydetme ve ekran görüntüsünden önce `model.ClearSelection2(True)` çağırın; `sw_review.save_preview()` bu temizliği zaten içerir.
5. En az üç beklenen rengin gerçekten görünür olduğunu görsel olarak doğrulayın; "önizleme boş değil" renk denetiminin yerini alamaz.
6. Görünüm anormalliğinde önce `tests/solidworks_appearance_regression.py` çalıştırın, ardından kullanıcı modelini yeniden oluşturun.

### MCP Server kullanımı

Kullanıcı "SolidWorks'ün MCP desteklemesini sağla", "Codex/Claude Desktop araç çağrısına bağla", "her seferinde uzun bir Python betiği üretme" dediğinde:

1. `mcp-server/README.md` okuyun.
2. Kullanıcı MCP'yi otomatik yapılandırmak istiyorsa öncelikli olarak çok istemcili kayıt aracını çalıştırın: `powershell -ExecutionPolicy Bypass -File mcp-server/register_all_ai_mcp.ps1 -InstallDependencies`; Codex, Claude Code, Claude Desktop, Cursor, Windsurf kaydetmeyi dener.
3. Yerel `stdio` MCP server kullanın: `python mcp-server/server.py`; varsayılan keşif modudur (`SW_MCP_DISCOVERY=search`), yalnızca `sw_search_tools` / `sw_describe_tool` / `sw_call_tool` sunar. Tüm adlandırılmış araçlar gerektiğinde `SW_MCP_DISCOVERY=full` ayarlayın.
4. Keşif modu "ara -> Schema oku -> yürüt" olarak kullanılır: önce `sw_search_tools` ile Türkçe/İngilizce ifadelerle aday bulun, ardından `sw_describe_tool` ile parametreleri doğrulayın, son olarak `sw_call_tool`. Araç adlarını tahminle doğrudan çağırmayın.
5. Varsayılan keşif modu, istemcinin geçerli görev için yetkiyi zaten aldığına güvenir; kullanıcı yetkisi kapsamında modelleme yapın, her öğe için
   ek onay istemeyin. Kullanıcının yetkilendirmediği üzerine yazma, kapatma veya diğer yüksek riskli işlemler için yine açık yetki alınmalıdır.
   Kaydedilmiş belgelerin etkin belge yazma işlemleri için `document_target` (mutlak `path` ve SolidWorks
   `process_id`) sağlanabilir; sağlanmadığında aracın mevcut etkin belge davranışı kullanılır.
   Kullanıcı `server`'ı açıkça etkinleştirirse ve araç bir istek ID'si döndürürse, kullanıcıdan sunucu tarafında
   `python scripts/sw_mcp_approve.py approve <istek ID>` çalıştırmasını isteyin; hedef doğrulanamadığında durun ve kısıtı açıklayın.
6. CAD'siz açık format yazma için öncelikli olarak `cadstudio_write_open_format` çağırın; DFM, Routing, FEA ve karmaşık geometri için sırasıyla `cadstudio_check_dfm`, `cadstudio_check_routing`, `cadstudio_routing_preflight`, `cadstudio_fea_preflight`, `cadstudio_prepare_fea`, `cadstudio_run_fea`, `cadstudio_run_fea_convergence`, `cadstudio_review_advanced_geometry`, `cadstudio_create_ocp_loft`, `cadstudio_create_ocp_surface` çağırın; SolidWorks yerel işlemleri için beyaz listedeki `solidworks_*` araçlarını çağırın.
7. Rastgele Python/VBA yürütme araçları sunmayın; yeni MCP araçları eklerken `scripts/sw_*.py` içindeki doğrulanmış sarmalayıcıları yeniden kullanın.
8. SolidWorks COM işlemleri sırayla yürütülmelidir; MCP server içinde masaüstü oturum çakışmasını azaltmak için global kilit zaten kullanılmaktadır.
9. Temel demo `examples/08_mini_fan_motion_assembly.py` kullanır; otomatik modelleme, montaj, Mate ve Motion Study'yi doğrular, yuvarlatma/pah görünümünün kusursuz olduğunu garanti etmez.

### Hareketli montaj gereksinimi

Kullanıcı "hareket etsin", "SolidWorks içinde sürükleyeyim", "menteşe", "dişli bağlantı", "gerçek mekanik eşleştirme" dediğinde:

1. Önce `references/assembly.md` içindeki hareket tipi montaj iş akışını okuyun; kullanıcı açıkça Motion Study / hareket simülasyonu / motor istiyorsa ayrıca `references/motion-study.md` okuyun.
2. Öncelikli olarak `sw_assembly.py` içindeki `resolve_component()`, `get_assembly_entity()`, `find_largest_cylinder_face()`, `add_mate5_checked()`, `add_concentric_mate_by_cylinders()`, `add_gear_mate_by_cylinders()` fonksiyonlarını yeniden kullanın.
3. Dönen parçalar için eş merkezli Mate ve `lock_rotation=False` kullanın, mili, dişliyi ve üst kapağı üç referans düzlemiyle tamamen kilitlemeyin.
4. Dişli aktarımı için gerçek Gear Mate kullanın, betikle sahte animasyonla mekanik eşleştirmeyi taklit etmeyin.
5. Oluşturduktan sonra `collect_mate_feature_summary()` veya özellik ağacı gezinmesiyle MateGroup altında `MateConcentric`, `MateGearDim` gibi gerçek Mate özelliklerinin bulunduğunu doğrulayın.
6. Gerçek hareket simülasyonu gerektiğinde öncelikli olarak `sw_motion.create_motion_study()`, `add_constant_speed_rotary_motor_by_cylinders()`, `calculate_and_play()` ile Motion Study ve motor oluşturun.
7. Hesaplamadan sonra `sw_motion.validate_motion_studies()` veya MCP `solidworks_validate_motion_study` çağırın; tip, süre, motor sayısı, sonuç varlığı ve `results_out_of_date=False` denetlenmelidir; yalnızca zaman çizelgesini, animasyonu veya `Calculate=True` görmek kabul geçişi sayılmaz.
8. Demo animasyonu gerektiğinde ek olarak betikle bileşen konumları veya Mate Controller sürülebilir, ancak animasyon gösteriminin etkileşimli serbestlik derecesine eşdeğer olmadığı belirtilmelidir; nihai ölçüt SolidWorks içinde sürüklenebilmesidir.

## GPT / Kimi / Claude çok modelli strateji

Agent'ın büyük bir modelden VBA makrosu üretmesini gerektiğinde mutlaka `scripts/sw_macro_guard.py` üzerinden yapılmalıdır:

1. **Model yönlendirmesi**: GPT serisi mevcut sade istemi kullanır; Kimi / Claude / bilinmeyen modeller otomatik olarak güçlü biçim kısıtlı Prompt yükler ve yalnızca VBA kaynak kodu çıktısı vermeye zorlanır.
2. **Yerel şablon geri dönüşü**: Model çıktısı başarısız olduğunda veya ayrıştırma başarısız olduğunda doğrudan hata verilmez; kullanıcı anahtar sözcüklerine göre (örn. "küp", "silindir", "ekstrüzyon", "kroki") yerleşik VBA şablonu seçilerek yürütmeye devam edilir.
3. **Çıktı doğrulaması**: Yürütmeden önce `SldWorks`, `ModelDoc2`, `Sub`, `End Sub` denetlenir, geçtikten sonra SolidWorks'e teslim edilmesine izin verilir; geçmezse yeniden denenir.
4. **Zaman aşımı/yeniden deneme**: Tek bir model isteği için `30s` zaman aşımı önerilir; ayrıştırma başarısız olduğunda otomatik olarak `1~2` kez yeniden denenir ve yeniden deneme Prompt'una daha güçlü biçim yönergeleri eklenir.

Örnek:

```python
from sw_macro_guard import build_prompt, fallback_macro_for_request, validate_vba_macro

prompt = build_prompt("50mm'lik bir silindir çiz", model_name="claude")
macro = fallback_macro_for_request("50mm'lik bir silindir çiz")
result = validate_vba_macro(macro)
assert result.ok, result.issues
```

## Sarmalanmamış API kuralları

Görev `scripts/` içinde henüz sarmalanmamış bir SolidWorks API'sini çağırmayı gerektirdiğinde:

1. Önce `references/api-lookup.md` okuyun, hedef sürümün yerel tip kitaplığını ve resmî belgelerini sorgulamak için `python SKILL_DIR/scripts/sw_api_lookup.py arayüz metot` kullanın; hedef yıl biliniyorsa `--version 2024`, çok örnek varsa `--process-id` ekleyin. İmzayı, birimleri, ön koşulları ve sürüm farklarını doğrulayın.
2. Arayüzleri ezberden tahmin etmek yasaktır; özellikle uzun parametreli COM metotları, `VARIANT` / by-ref parametreleri, enum değerleri, seçim işaretleri ve `SaveAs` benzeri arayüzler.
3. Kod yazarken asgari çalıştırılabilir betiği koruyun ve her adımın dönüş değeri için `None` / `False` denetimi yapın.
4. Uyguladıktan sonra gerçekten çalıştırılmalı, hedef dosya kaydedilmeli veya dışa aktarılmalı ve önizleme görüntüsü ile inceleme raporu üretmek için `sw_review.py` kullanılmalıdır.
5. Yeni keşfedilen tuzaklar, hata kodları, uyumlu yazım veya istikrarlı sarmalayıcılar `references/troubleshooting.md` veya ilgili modül referans dokümanına eklenmelidir; yaygın mantık daha sonra `scripts/` içine yerleştirilir.

Doğrulama varsayılan olarak SolidWorks resmî belgelerine erişebilir; resmî site doğrudan okunamazsa ve önbellek yoksa anonim Parallel yedek sorgusu kullanılır; yalnızca herkese açık sürüm, arayüz, üye ve resmî bağlantılar gönderilir. `--offline` veya `SW_API_LOOKUP_NETWORK=off` bu aracın ağa erişimini yasaklar, `--no-parallel` veya `SW_API_LOOKUP_PARALLEL=off` yalnızca Parallel'i kapatır. Çevrimdışıyken yerel yardım ve son alınan önbellek kullanılabilir; sürüm kanıtına ve alma zamanına dikkat edilmelidir. Belgeler yetersiz olduğunda istemcinin izin verdiği ölçüde kendi araması kullanılabilir, yalnızca herkese açık API tanımlayıcıları aranır; istemcinin kendi ağ izni istemci tarafından denetlenir. Arayüz bildirimleri, resmî açıklamalar ve gerçek makine davranışı ayrı ayrı değerlendirilir; hedef sürüm veya çalışma doğrulaması eksik olduğunda doğrulanmış uyumluluk iddia edilemez.

Doğal dil görevi bir API belirtmediğinde önce `python SKILL_DIR/scripts/sw_api_lookup.py --task "görev açıklaması"` çalıştırılarak yaygın adaylar otomatik doğrulanır; adaylar zorunlu çözüm değildir. Aday yoksa veya planda başka bir API belirlenmişse önce mevcut sarmalayıcılardan arayüz ve üyeler belirlenir, ardından ilgili sürüm tek tek sorgulanır, görev metninin tamamı üçüncü taraf hizmete gönderilmez.

## Sonuç öz incelemesi

Her CAD oluşturma, değiştirme, içe aktarma veya dışa aktarmadan sonra, kullanıcı açıkça gerekmediğini söylemediği sürece öz inceleme yapılmalıdır:

1. COM dönüş değerlerini, özellik nesnelerini, kaydetme/dışa aktarma dönüş değerlerini ve çıktı dosyası boyutunu denetleyin.
2. Modeli yenilemek için `model.ForceRebuild3(False)`, `model.ViewZoomtofit2()` çağırın.
3. `scripts/sw_review.py` içindeki `run_review()` ile `isometric/front/top/right` önizleme görüntülerini dışa aktarın ve `*_review_report.json` yazın.
4. Rapordaki `evaluation.status`, `evaluation.issues`, `checks` ve önizleme görüntüsünü okuyun; ekran görüntüsü veya dışa aktarılan BMP üzerinden denetleyin: ana gövde var mı, oran/yönelim makul mü, kritik parçalar eksik mi, belirgin örtüşme veya havada asılı kalma var mı, dosya adı ve çıktı yolu doğru mu.
5. Sorun bulunduğunda önce betiği düzeltip yeniden oluşturun, ardından raporlayın; yalnızca "kaydetme başarılı" diye raporlamayın.

Örnek:

```python
from sw_review import run_review

model.ForceRebuild3(False)
report, report_path = run_review(
    model,
    r"C:\temp\review",
    basename="car",
    expected_outputs=[r"C:\temp\car.sldprt", r"C:\temp\car.step"],
)
print(report_path)
print(report["evaluation"])
```

## Önemli notlar

- **Birimler**: API tek biçimde **metre** kullanır. 50mm'yi 0,05m'ye dönüştürmek için `mm(50)`, açıyı dönüştürmek için `deg(90)` kullanın
- **Sürüm**: SolidWorks yılı belirtilebilir ve hedef örnek doğrulanabilir; farklı işlemlerin uyumluluğu `capabilities.yaml` ve gerçek sürüm kanıtı esas alınır, bağlantı başarısı tüm işlevlerin uyumlu olduğu anlamına gelmez
- **Seçim**: COM nesnesi elde edilebildiğinde nesne düzeyi `Select2()` tercih edilir; referans düzlemi için `SelectByID2("PLANE")` kullanılabilir, kroki yalnızca `SelectByID2("SKETCH")` ile seçilmeye bağımlı olmamalıdır
- **Kroki**: Krokiden otomatik girip/çıkmak için `with sketch(model, "Front Plane") as sketch_name:` kullanımı önerilir; `sw_part.py` kroki nesnesi referansını önbelleğe alır, SW2024 Çince sürümünde krokiyi adla seçme hatasını önler
- **Bileşen ekleme**: Montajda öncelikli olarak `sw_assembly.add_component()` kullanın; SW2024 Çince sürümünde `AddComponent4` `None` döndürebilir, sarmalayıcı `AddComponent5` kullanır, parçayı sessizce açar, montajı yeniden etkinleştirip yeniden dener
- **Görünüm**: Renk gereksinimi yüksek modellerde öncelikli olarak çok parçalı montaja bölün; malzeme dizisi `SAFEARRAY(double)` ile gruplanmalı ve RGB geri okunarak doğrulanmalıdır
- **VARIANT**: by-ref parametreler `VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)` ile sarmalanmalıdır
- **Referans düzlemi adları**: `start_sketch()` İngilizce "Front/Top/Right Plane" ile Çince sürümdeki ön/üst/yan referans düzlemi adlarını otomatik uyumlu hale getirir
- **Kroki koordinatları**: Kroki düzlemine dayalı yerel koordinat sistemi, birim metre
- **Hareketli montaj**: Önce bileşeni çözümleyip ardından Mate varlığını seçin; `GetCorresponding()` parça içi yüz/özellikleri montaj bağlamına eşlemek için kullanılır; eş merkezli Mate varsayılan olarak dönüşü kilitlemez
- **Motion Study**: `swmotionstudy.tlb` yüklenmelidir; pywin32 altında `CreateMotionStudy` / `Activate` / `Calculate` özellik olarak davranabilir, öncelikli olarak `sw_motion.motion_member()` uyumluluğu kullanılır
