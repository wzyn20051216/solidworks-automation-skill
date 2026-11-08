# CAD Studio Yerel Otomasyon Kuyruğu Protokolü

## Amaç

CAD Studio masaüstü tarafı, görevleri Tauri üzerinden yerel JSON dosyaları olarak kaydeder; Python worker kuyruğu okur ve yerel Codex'i çağırır. Resmi masaüstü başlatma yalnızca Codex handler'ı etkinleştirir; mock handler yalnızca açık geliştirme testleri içindir.

## Kuyruk dizini

Rust tarafı `app.path().app_data_dir()/queue` değerini esas alır. Geçerli Tauri tanımlayıcısı:

```text
com.wzyn.cadstudio
```

Windows'ta yaygın yol:

```text
%APPDATA%\com.wzyn.cadstudio\queue
```

worker varsayılan olarak bu dizini de okur. Hata ayıklarken açıkça belirtilebilir:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --queue-dir "<kuyruk-dizini>"
```

Masaüstü entegrasyon testleri başlatmadan önce `CAD_STUDIO_QUEUE_DIR` ayarlayarak Tauri kuyruk dizinini geçersiz kılabilir; resmi çalıştırmada ayarlanmadığında yine uygulama veri dizini kullanılır.

Sürekli dinleme:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<kuyruk-dizini>"
```

Masaüstü tarafı ayrıca Worker Control sunar; kuyruk panelinin sağ üst köşesinden yazılımın yönettiği Python worker başlatılıp/durdurulabilir. Tarayıcı önizleme modu worker'ı başlatmaz.

## Görev JSON

Her görev için bir dosya; dosya adı güvenli hale getirilmiş `id` değerinden gelir:

```text
{id}.json
```

Alanlar:

```json
{
  "schemaVersion": "1.0",
  "id": "job-1721900000000-a1b2c3",
  "runId": "run-1721900000000-a1b2c3",
  "kind": "create_shell",
  "title": "Yeni CAD görevi",
  "detail": "Parça, montaj, muhafaza, delik/kanal ve temel kontrol görevleri oluştur",
  "status": "queued",
  "progress": 0,
  "createdAt": "2026-07-25T12:00:00.000Z",
  "updatedAt": "2026-07-25T12:00:00.000Z",
  "requestedBy": "local-user",
  "createdByAppVersion": "0.1.0",
  "policy": {
    "sandbox": "workspace-write",
    "approval": "never",
    "requireSkillRead": true,
    "requireTests": true,
    "requireCommit": true,
    "requirePush": false,
    "requireReviewerPass": true
  },
  "capabilities": [],
  "projectPath": "D:/demo/demo_shell.step"
}
```

Makine tarafından okunabilir Schema:

```text
apps/desktop/cad_workbench/schemas/automation_job.schema.json
```

Görev türleri:

- `create_shell`: Eski adlandırmayla uyumlu yeni CAD görevi; parça, montaj, muhafaza, delik/kanal ve temel kontrolleri kapsar.
- `import_model`: Yerel CAD modelini içe aktarır ve proje bağlamını oluşturur.
- `delivery_package`: STEP, STL, PDF, DWG vb. teslim paketleri üretir.
- `codex_task`: Grafiksel yapılandırma ile oluşturulan Codex etkileşimsiz yürütme görevi.

Codex Bridge uzantı alanları:

```json
{
  "executor": "codex",
  "objective": "Kullanıcı girdisine göre en iyi CAD görev türünü, üretim yöntemini, malzemeyi ve teslim biçimini otomatik belirle",
  "target": "AI otomatik belirler",
  "expectedOutput": "AI otomatik çıktı seçer",
  "strictRules": ["Belirtilmeyen alanlar için AI en iyi mühendislik çözümünü otomatik seçer", "Delik/kanallar gerçek geometri kesimi olmalıdır", "CAD teknik resimleri Çin'de yaygın mekanik teknik resim biçimine göre incelenmelidir"],
  "prompt": "Sen Codex'sin; CAD Studio grafik arayüzü tarafından oluşturulan görevi yürüt...",
  "cwd": "C:/path/to/solidworks-automation-skill",
  "skillPath": "C:/path/to/solidworks-automation-skill/SKILL.md",
  "uiConfig": {
    "selection": {
      "mode": "auto_best",
      "autoTarget": true,
      "autoOutput": true,
      "autoProcess": true,
      "autoMaterial": true,
      "instruction": "Belirtilmeyen alanlar için AI en iyi mühendislik çözümünü otomatik seçer ve gerekçesini açıklar."
    }
  }
}
```

Varsayılan seçim anlamları:

- Kullanıcı görev türünü, süreci, malzemeyi, çıktı biçimini veya ölçü ayrıntılarını belirtmediğinde UI `selection.mode = "auto_best"` yazar.
- Codex, mühendislik hedefine, giriş dosyalarına, üretim yöntemine, maliyete, mukavemete, işlenebilirliğe ve teslim gereksinimlerine göre en iyi çözümü otomatik seçmelidir.
- Otomatik seçimden sonra nihai sonuçta seçim gerekçesi ve kalan riskler açıklanmalıdır.
- Kullanıcı belirli bir şablona veya belirli bir seçeneğe tıkladığında o alan kullanıcı tarafından belirtilmiş sayılır ve Codex buna öncelikli olarak uymalıdır.

Durum akışı:

```text
queued -> running -> passed | review_required | failed | cancelled
queued -> running -> failed
queued -> cancelled
queued -> approval_required -> queued | cancelled
review_required -> passed | failed
```

Kurallar:

- UI yeni görevleri yalnızca oluşturma arayüzü üzerinden yazar; iptal, yürütme öncesi onay ve yürütme sonrası manuel inceleme ayrı özel komutlardan geçer; genel kaydetme ile görev durumu üzerine yazılamaz.
- worker yalnızca `status == "queued"` olan görevleri işler.
- `passed`, `failed`, `cancelled` terminal durumlardır; `review_required` için kullanıcının açıkça "incelemeyi onayla" veya "reddet" demesi gerekir.
- worker `workerLog`, `lastMessage`, `result` veya `error` alanlarını geri yazar; ön uç bu alanları doğrudan gösterebilir.
- Başarılı görevler `artifactLedgerPath` ve `artifacts` alanlarını geri yazar; teslimatların varlığını, boyutunu ve hash'ini göstermek için kullanılır.
- Başarılı görevler `reviewGatePath` ve `reviewGate` alanlarını geri yazar; teslimat inceleme durumunu göstermek için kullanılır.
- Reviewer Gate `warning` olduğunda `review_required` yazılır ve "tamamlandı" gösterilemez; yalnızca kapı `pass` olduğunda `passed` yazılır.
- Gerçek CAD handler'ı `passed` yazmadan önce dosya varlığı kontrolünü tamamlamalıdır; yer tutucu dosyaları, AI JSON makbuzlarını veya eski dosyaları üretilebilir teslimat olarak işaretleyemez.
- `save_queue_job` yalnızca var olmayan yeni `queued` görevleri kabul eder; var olan görevlerin üzerine yazılması her zaman reddedilir.

Manuel inceleme onaylanmadan önce somut açıklama doldurulmalı ve geçerli görevin gerektirdiği inceleme kontrol listesi tamamlanmalıdır. Onaydan sonra `reviewedBy`, `reviewedAt`, `reviewDecision = "approved"` yazılır ve manuel kontrol maddeleri, uyarı listesi ile teslimat yolu/boyut/SHA-256 anlık görüntüsü `reviewGate.manualReview` ve `review.manual_approved` denetim olayına yazılır; reddetme durumunda sorun açıklaması doldurulmalı ve `reviewDecision = "rejected"`, belirgin hata ile `review.manual_rejected` yazılmalıdır.

## Policy Gate

Policy Gate, worker/control-plane katmanının zorunlu kapısıdır; yalnızca ön uç uyarısına bağlı olamaz. Codex görevleri yürütülmeden önce ilke ve yetenek bildirimleri kontrol edilir; risk eşleşirse geri yazılır:

```json
{
  "status": "approval_required",
  "approvalReasons": ["Görev Git push talep ediyor, manuel onay gerekiyor."],
  "lastMessage": "Görev manuel onay gerektiriyor: ..."
}
```

Şu anda manuel onay gerektiren durumlar:

- `policy.approval == "manual-required"`.
- `policy.requirePush == true` veya `uiConfig.gates.commitAndPush == true`.
- `policy.sandbox == "danger-full-access"`.
- `capabilities` şunlardan birini içeriyor: `git_push`, `full_access`, `cad_macro`, `external_network`, `cross_workspace`, `delete_files`.

Masaüstünde "Onayla"ya tıklandıktan sonra şunlar yazılır:

```json
{
  "approvedAt": "unix:1784970000",
  "approvedBy": "local-user",
  "approvedPolicyReasons": ["Görev Git push talep ediyor, manuel onay gerekiyor."],
  "status": "queued"
}
```

worker geçerli görevin onay nedenlerini yeniden hesaplar ve bunların `approvedPolicyReasons` ile tam olarak eşleşmesini ister; onaydan sonra görev tam yetkiye, CAD makrosuna veya başka tehlikeli yeteneklere değiştirilirse onay geçersiz olur ve görev yeniden `approval_required` durumuna girer. Bu nihai kurcalamaya karşı koruma çözümü değildir; ileride Artifact Ledger HMAC imzası ve değiştirilemez denetim kayıtları ekleyecektir.

## Güvenilir kuyruk durum makinesi

Hâlâ yerel JSON dosya kuyruğu kullanılır, ancak worker artık asgari güvenilirlik semantiğine sahiptir:

- Görevi almadan önce `{job}.json.lock` açılır; Windows `msvcrt.locking`, Unix `fcntl.flock` ile işletim sistemi özel kilidi alınır ve birden çok worker'ın aynı görevi tekrar alması önlenir.
- Alma sonrası `runnerId`, `workerPid`, `attempt`, `heartbeatAt`, `leaseUntil` yazılır.
- Çalışan worker `heartbeatAt` ve `leaseUntil` değerlerini düzenli olarak yeniler; uzun görevlerin yanlışlıkla stale sayılmasını önler.
- worker bittiğinde işletim sistemi kilidini serbest bırakır; `.lock` dosyası tanılama kaydı olarak kalır, süreç anormal çıkış yaptığında işletim sistemi kilidi otomatik serbest bırakır.
- UI görevi `status: "cancelled"` veya `cancelRequested: true` olarak yazabilir; worker yönettiği Codex alt sürecini sonlandırır.
- Başlatma veya yoklamada `leaseUntil` süresi dolmuş `running` görevler kurtarılır ve yeniden `queued` yapılır.
- Yazılımın Worker'ı aktif olarak durdurması, Alt+F4, sistem kapanması veya yerel çıkış durumunda önce Worker süreç ağacı sonlandırılır, ardından `workerPid` ile o Worker'ın tamamlanmamış `running` görevleri hemen `queued` durumuna geri alınır; iptal talebi olan görevler `cancelled` kalır.
- Bozuk JSON `queue/quarantine` dizinine taşınır ve aynı adlı bir `.error.txt` oluşturulur; watch döngüsü kesilmez.
- Her görev için `queue/events/{job_id}.jsonl` olay akışı yazılır.
- Yönetilen alt sürecin stdout/stderr çıktısı `queue/logs/{job_id}.stdout.log` ve `queue/logs/{job_id}.stderr.log` dosyalarına yazılır.
- Başarılı görevler `queue/ledgers/{job_id}.ledger.json` teslimat defterini yazar.
- Başarılı görevler `queue/reviews/{job_id}.review.json` Reviewer Gate raporunu yazar.
- worker `queue/worker_health.json` sağlık sinyalini yazar.

Bu alanlar worker yönetim alanlarıdır; UI gösterebilir ancak elle değiştirmemelidir.

## Worker Health

worker her kuyruk taramasından sonra şunu yazar:

```text
queue/worker_health.json
```

Alanlar şunları içerir:

- `status`: `healthy`, `attention`, `warning` veya `error`.
- `heartbeatAt`: En son sinyal zamanı.
- `processedCount`: Bu turda işlenen görev sayısı.
- `recoveredCount`: Bu turda kurtarılan stale running görev sayısı.
- `queue`: Görev durumuna göre sayılan kuyruk sayısı.

Masaüstü tarafındaki `worker_status` aynı anda yönetilen süreç PID'sini ve en son sağlık sinyalini döndürür. Tarayıcı önizleme modu worker'ı başlatmaz.

## Artifact Ledger

Artifact Ledger, Agent teslim sonuçlarını denetlenebilir makine kayıtlarına dönüştürmek için kullanılır. worker görev başarılı olduktan sonra `result.outputPath`, `result.outputs`, `result.artifacts` ve görevin kendi `artifacts` alanlarını toplayıp şunu üretir:

```json
{
  "schemaVersion": "1.0",
  "jobId": "job-1721900000000-a1b2c3",
  "runId": "run-1721900000000-a1b2c3",
  "status": "passed",
  "artifacts": [
    {
      "kind": "step",
      "path": "D:/demo/outputs/model/demo.step",
      "exists": true,
      "isDirectory": false,
      "sizeBytes": 12345,
      "sha256": "..."
    }
  ],
  "verification": [],
  "resultMessage": "Görev tamamlandı"
}
```

Yazma yolu:

```text
queue/ledgers/{job_id}.ledger.json
```

Göreli çıktı yolları önce görevin `cwd` değerine göre çözümlenir; `cwd` yoksa `projectPath` dizinine veya proje dizinine göre çözümlenir. Aynı bilgi özet olarak görev JSON'unun `artifactLedgerPath` ve `artifacts` alanlarına geri yazılır ve `artifact.ledger_written` olayı eklenir. Gerçek CAD handler'ı yine de P0 teslimatlarının eksiksiz olup olmadığına kendisi karar vermelidir; Ledger gerçekleri kaydetmekle sorumludur ve üretim seviyesi kabulün yerini almaz.

## Reviewer Gate

Reviewer Gate, Artifact Ledger'a dayalı olarak asgari teslimat inceleme raporu üretir:

```text
queue/reviews/{job_id}.review.json
```

Geçerli kurallar:

- Bildirilen teslimat yok: `warning`; yalnızca sürecin tamamlandığı doğrulanabilir, üretim dosyalarının eksiksiz olduğu doğrulanamaz.
- Bildirilen teslimat mevcut değil: `fail`.
- Teslimat boş dosya: `fail`.
- Teslimat bir dizin: `warning`; şu anda dizin içeriği özyinelemeli doğrulanmaz.
- Normal dosya mevcut ve SHA-256 var: `pass`.
- Codex kendi doğrulamasını `failed` olarak bildirirse Reviewer Gate `fail` olmalıdır; doğrulama kaydı yoksa veya kalan risk varsa en az `warning` olmalıdır.
- `SLDPRT / STEP / STL`, `DWG / DXF / PDF` gibi belirgin biçim listeleri madde madde kapı kontrolünden geçer; bunlardan bir dosya tüm teslim paketinin yerini tutamaz.
- Codex teslimatları görev çalışma alanı, kullanıcı çıktı dizini veya giriş dosyası dizini içinde olmalıdır. Yürütmeden önce CAD dosyalarının boyutu, nanosaniye düzeyinde değişiklik zamanı ve SHA-256'sı kaydedilir; yürütmeden sonra yalnızca yeni dosyalar veya içerik hash'i değişen dosyalar `producedThisRun = true` olarak işaretlenir; yalnızca zaman damgasını değiştirmek bu turun ürünü gibi gösterilemez; AI makbuzları ve değişmemiş eski dosyalar bu turun CAD ürünü sayılmaz.
- STEP/STP `ISO-10303-21` ve `END-ISO-10303-21` işaretlerini içermelidir.
- STL tanınabilir ASCII `solid/endsolid` veya Binary STL temel yapısına sahip olmalıdır.
- DXF `SECTION` içermeli ve `EOF` ile bitmelidir.
- PDF `%PDF-` dosya başlığını içermelidir.
- DWG AutoCAD `AC10` sürüm başlığını içermelidir.
- SLDPRT, SLDASM tescilli biçimlerdir; şu anda yalnızca `warning` verilebilir, ileride SolidWorks ile açılarak incelenecektir.

Rapor özeti görev JSON'unun `reviewGate` ve `reviewGatePath` alanlarına geri yazılır ve `review.gate_completed` olayı eklenir. Bu, ilerideki üretim seviyesi Reviewer Gate'in temelidir; gerçek CAD aşamasında ayrıca STEP/STL/DWG/PDF'nin açılıp açılamadığı, ölçü zincirinin eksiksiz olup olmadığı ve 3B baskıda gerçek deliklerin oluşup oluşmadığı kontrol edilmelidir.

## Codex Bridge

Yazılımın konumu "AI destekli CAD otomasyon konsolu"dur:

```text
grafiksel yapılandırma -> yapılandırılmış görev JSON -> Python worker -> codex exec -> kuyruk sonucunu geri yazma
```

Worker, Prompt'u derlemeden önce yerel öncelikli RAG çalıştırır: varsayılan olarak ana Skill'i, `references/` ve alt beceri bilgi dosyalarını arar ve kaynak, SHA-256 ve parçacıkları Prompt'a enjekte eder. `uiConfig.knowledgeBase.cloudEnabled=true` olduğunda Tauri sunucu tarafında `external_network` yeteneğini türetir; HTTPS bulut arama uç noktası yalnızca manuel onay tamamlandıktan sonra çağrılabilir.

Görevde açıkça `arayüz.yöntem` / `arayüz::yöntem` geçtiğinde veya bu projede doğrulanmış doğal dil işlem adayları eşleştiğinde Worker, paylaşılan API doğrulama çekirdeğini kullanır (açık referanslar öncelikli, en fazla iki aday). Varsayılan olarak resmi belgelere erişilir; doğrudan okuma başarısız olur ve geçmiş önbellek yoksa anonim Parallel kullanılır. İstek yalnızca genel yıl, arayüz, üye ve resmi bağlantıları içerir. `uiConfig.knowledgeBase.officialApiDocsEnabled=false` bu aracın ağa bağlanmasını ve bağımlılık indirmesini yasaklar ve denetlenen alt sürece `SW_API_LOOKUP_NETWORK=off` aktarır; `parallelApiFallbackEnabled=false` yalnızca Parallel'i kapatır ve `SW_API_LOOKUP_PARALLEL=off` aktarır. Her ikisi de Agent istemcisinin kendi ağ izinlerini değiştirmez. Geçmiş önbellek alma zamanını belirtir; Parallel ve yerel yardımın sürüm kanıtları kendi sınırlamalarına sahiptir ve gerçek makine doğrulamasıyla eşdeğer değildir. Mevcut bulut RAG yapılandırması ve onay kuralları bağımsız kalır.

Codex yürütmeyi etkinleştirme:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<kuyruk-dizini>"
```

Yazılım içinde "Başlat"a tıklamak şunu başlatmakla eşdeğerdir:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<Tauri kuyruk dizini>"
```

Bu giriş varsayılan olarak `--codex-full-access` eklemez; tam yetki yine manuel onay ve açık komut anahtarı gerektirir.

worker şunu çağırır:

```powershell
node.exe "<npm>/node_modules/@openai/codex/bin/codex.js" exec -C "<cwd>" -s workspace-write -c "approval_policy=\"never\"" -o "<çıktı dosyası>" --output-schema "<schema>" "<prompt>"
```

Notlar:

- `--enable-codex` açık bir anahtardır; sıradan mock hata ayıklamasının gerçek Codex yürütmeyi yanlışlıkla tetiklemesini önler.
- Varsayılan olarak yalnızca `workspace-write` izin verilir. Gerçekten tam yetki gerekiyorsa görev önce Policy Gate onayından geçmeli ve worker başlatılırken ek olarak `--codex-full-access` verilmelidir.
- Windows npm kurulumunda öncelikli olarak `node.exe + codex.js` kullanılır; kullanıcı prompt'u `cmd.exe` ile ayrıştırılmaz.
- Codex sürümü, oturum açma durumu ve SolidWorks preflight sağlık kontrolleri için 5～10 saniyelik zaman aşımı vardır; zaman aşımında süreç ağacı sonlandırılır ve belirgin bir hata döndürülür, masaüstü arayüzü bloke edilmez.
- worker `cwd` değerinin depo beyaz listesi içinde olmasını doğrular ve çıktıyı `<cwd>/ai_team/{job_id}_codex_result.json` olarak zorlar; yürütmeden önce aynı adlı eski makbuz silinir; eksik veya geçersiz JSON doğrudan başarısız olur.
- UI prompt'u ve yürütme kısıtlarını üretmekten sorumludur; Codex gerçek dosya okuma/yazma, skill çağırma, doğrulama çalıştırma, commit ve push işlemlerinden sorumludur.
- Worker yürütmeden önce yerel mekanik bilgi aramasını çalıştırır ve kaynak yolu, SHA-256 ve puanlama içeren parçacıkları kurumsal Prompt'a enjekte eder.
- Ayarlar sayfasından yerel standart kitaplıkları eklenebilir; bulut RAG varsayılan olarak kapalıdır, etkinleştirildiğinde Tauri sunucu tarafı `external_network` tehlikeli yeteneğini türetir ve onay gerektirir.
- Codex çıktısı `ai_team/{job_id}_codex_result.json` dosyasına yazılır ve aynı anda görev JSON'unun `result.outputPath` alanına yol geri yazılır.

### CAD yazılımı yönlendirmesi

UI hedef yazılımı `targetSoftware` ve `uiConfig.cadRuntime` alanlarına yazar:

```json
{
  "targetSoftware": "AI otomatik yazılım seçer",
  "capabilities": ["cad_macro"],
  "policy": {
    "sandbox": "danger-full-access",
    "approval": "never"
  },
  "uiConfig": {
    "cadRuntime": {
      "application": "auto",
      "applicationLabel": "AI otomatik yazılım seçer",
      "localCadAutomation": true,
      "solidworksSkillPath": "C:/path/to/solidworks-automation-skill/SKILL.md",
      "autocadSkillPath": "C:/path/to/solidworks-automation-skill/subskills/autocad-automation/SKILL.md"
    }
  }
}
```

Yönlendirme kuralları:

- Üç boyutlu katı, montaj, gerçek delikler, sac metal, STEP/STL/SLDPRT dışa aktarımı için öncelikli olarak SolidWorks çağrılır.
- DWG/DXF/PDF, ulusal standart teknik resim, katmanlar, ölçü zinciri, delik tablosu, başlık bloğu ve AutoCAD yerel önizlemesi için öncelikli olarak AutoCAD çağrılır.
- Teslim paketi, montaj resmi ve üretim incelemesi için önce SolidWorks ile üç boyutlu ve ara dosyalar üretilebilir, ardından AutoCAD ile iki boyutlu teknik resim ve dışa aktarım tamamlanabilir.
- `application == "auto"` olduğunda Codex, görev hedefine göre SolidWorks, AutoCAD veya her ikisinin birlikte kullanımını otomatik seçmeli ve sonuçta seçim gerekçesini açıklamalıdır.
- `localCadAutomation == true` olduğunda görev `cad_macro` yeteneğini ve `danger-full-access` sandbox'ını bildirir; bu nedenle Policy Gate manuel onay ister; worker da `--codex-full-access` ile başlatılmalıdır ki onaylanan görev gerçekten masaüstü yazılımı çağırma yeteneğine sahip olsun.

## Gerçek yürütücüye bağlanma

Python worker'ın uzantı noktası:

```text
apps/desktop/cad_workbench/queue_worker.py
```

handler'ı değiştirme veya enjekte etme:

- `create_shell` -> SolidWorks modelleme, katı delik açma, STL/STEP dışa aktarma.
- `import_model` -> dosya ayrıştırma, küçük resim, proje dizini başlatma.
- `delivery_package` -> AutoCAD teknik resim dışa aktarma, PDF/DWG/DXF, teslim listesi ve standart incelemesi.

Yürütücü P0 kapılarına uymalıdır:

- 3B baskı delikleri gerçek geometri kesimi olmalıdır; yalnızca çizgi çizmek veya yalnızca yorum yazmak kabul edilmez.
- Teknik resimler eksiksiz ölçü zincirini, delik tablosunu, teknik gereksinimleri, çerçeve başlık bloğunu ve GB/T tarzı anotasyonu korumalıdır.
- Başarısızlık durumunda `failed` ve belirgin `error` geri yazılmalıdır; sessizce atlanmamalıdır.
