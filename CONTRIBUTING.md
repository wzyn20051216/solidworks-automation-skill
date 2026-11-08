# Katkı Rehberi / Contributing Guide

SolidWorks Automation Skill projesine gösterdiğiniz ilgi için teşekkürler!

## Yönetişim ve Bakım Modeli

Bu depo **tek kişilik çekirdek bakım + açık topluluk katkısı** modelini benimser. Herhangi bir dış geliştirici Fork + Pull Request yoluyla kod gönderebilir; depo owner'ı kod kalitesini, test kanıtını ve gerçek değeri değerlendirdikten sonra birleştirip birleştirmeyeceğine karar verir.

- **Bakımcı**: [@wzyn20051216](https://github.com/wzyn20051216) (şu anda yazma yetkisine sahip tek hesap)
- **Sabit bir bağımsız gözden geçiren atanmaz** ve PR'ların başkası tarafından approve edilmesi zorunlu değildir
- **Tüm birleştirme kararları tek başına owner tarafından verilir**. Bu proje bağımsız bir yeniden inceleme yeteneği sunmaz ve bu yeteneğe sahip olduğunu iddia etmez
- Dış katkıcılar yazma yetkisine sahip değildir ve herhangi bir korumalı dala doğrudan push yapamaz; tüm dış değişiklikler yalnızca PR yoluyla owner tarafından birleştirilebilir

**Bu modelin bilinen sınırları**: Birleştirme kalitesi owner'ın kişisel yargısına bağlıdır, ikinci bir kişinin çapraz doğrulaması yoktur. Bu, araç tipi açık kaynak projelerin topluluk işbirliği için uygundur; uyumluluk denetimi veya üçüncü taraf onayı gerektiren senaryolar için uygun değildir.

### Mevcut yönetişim kısıtları (2026-10-27 itibarıyla olduğu gibi kaydedilmiştir)

- `main`'in ruleset'i şu anda `required_approving_review_count = 0` (tek kişilik bakım modelinin yerleşik değeri, bu nedenle yönetişim başarısızlığı sayılmaz)
- owner hâlâ ruleset `bypass_actors` içinde ve `bypass_mode = always`. **Bu, şu anda kaldırılmamış bir engelleyici maddedir**: politika bypass listesinin boş olmasını gerektirir;
  kod, dokümanlar ve testler "herhangi bir bypass uygun bulunmaz" şeklinde yürütülür
- Uzak CAD kabulünün `bypass_actors` kanıtı **CI tarafından gerçek zamanlı okunmaz** — GitHub bu alanı yalnızca o ruleset üzerinde yazma yetkisi olduğunda döndürür,
  salt okunur denetim kimlik bilgileri bunu okuyamaz. Bu nedenle bu, **çevrimdışı toplama + imzalı kanıt** ile üstlenilir; CI yalnızca salt okunur doğrulama yapar, ayrıntılar için bkz.
  [`docs/architecture/governance-attestation.md`](docs/architecture/governance-attestation.md)
- **Bu kanıt bakımcı tarafından bizzat düzenlenir, açık anahtar güven kökü bu depoda saklanır**, yalnızca kurcalamaya karşı iz sağlar, **bağımsız denetim, bağımsız onay veya iki kişilik inceleme oluşturmaz**
- Depo değişkeni `GOVERNANCE_TRUST_ROOT_ANCHOR`, depo dosyalarının dışında ikinci bir bağlantı noktası sağlar ve "açık anahtar + günlük + kanıt"ın bir bütün olarak değiştirilmesini engelleyebilir;
  ancak depo yöneticisi yetkisine sahip olanlar bu değişkeni de birlikte değiştirebilir, dolayısıyla yalnızca maliyeti artırır, bağımsız bir güven kökü değildir
- `.github/CODEOWNERS`, yönetişime duyarlı yolların sorumlularını bildirmiştir, ancak `require_code_owner_review = false` olduğundan
  **dosyanın kendisi zorunlu bir kapı oluşturmaz** (tek kişilik bir depoda açmak "yazar kendi PR'ını onaylayamaz" nedeniyle kilitlenmeye yol açar)
- `test-and-build` artık `node --test tests/test_cad_ci_guard.cjs` ve
  `node scripts/ci/check_governance_drift.cjs` içeriyor; ikincisi yalnızca yönetişim kodu değişikliklerini belirgin bir fark haline getirebilir, **birleştirme yetkisi olanların birlikte değiştirmesini engelleyemez**
- **Yukarıdaki düzenlemeler tamamlanıp gerçekten doğrulanana kadar, bu deponun bağımsız onay yeteneğine veya zorunlu CI kapısına sahip olduğu dışarıya karşı iddia edilemez**

Bu kısıtların takip kayıtları yayın engelleyici listesi B-02'de yer alır; owner'ın da zorunlu denetimleri atlayamamasını sağlayan asgari değişiklik planı (tek alanı boşaltma
`bypass_actors`, kabul ölçütleri ve geri alma dahil) için bkz.
[`docs/architecture/governance-bypass-remediation.md`](docs/architecture/governance-bypass-remediation.md).
Yönetişim kodu, iş akışı ve güven kökü değişiklikleri yine bakımcı tarafından elle onaylanmalıdır.

### Bakımcı: ruleset değişikliğinden sonra kanıt yeniden toplanmalıdır

Herhangi bir ruleset değişikliği (`bypass_actors` boşaltma dahil) `updated_at` ile iki özeti (`policy_digest` / `snapshot_digest`)
aynı anda değiştirir, **eski kanıt derhal geçersiz olur** ve uzak CAD kabulü bununla birlikte bloke olur. Değişiklikten sonra yerel makinede bir kez toplama yapılmalı ve yeni kanıt PR ile birlikte gönderilmelidir:

```bash
GH_TOKEN="$(gh auth token)" node scripts/ci/capture_governance_attestation.cjs --verify
```

Toplama aracı uzak durum uygun değilse **varsayılan olarak imzalamayı reddeder** (dosya yazmaz, sıfır olmayan çıkış kodu verir). Uygun olmayan durumu tanı amacıyla kaydetmeniz gerçekten gerekiyorsa
`--allow-noncompliant` kullanın; ürün `compliant: false` olarak işaretlenir ve asla kabulden geçemez.

Güven kökünü veya kanıtı değiştirdikten sonra ayrıca `node scripts/ci/check_governance_drift.cjs --update` çalıştırmalı ve listeyi birlikte göndermelisiniz,
aksi halde `test-and-build` sapma nedeniyle başarısız olur.

Özel anahtar yalnızca yerel makinede `%USERPROFILE%\.cad-governance\` altında saklanır; depoya girmemeli ve CI'ye yazılmamalıdır. Tam akış, ikili özet semantiği ve anahtar rotasyon adımları için yukarıdaki belgelere bakın.

## Nasıl Katkıda Bulunulur

### Bug Bildirme

Bir Bug bulduysanız, lütfen bir Issue oluşturun ve aşağıdaki bilgileri ekleyin:

- SolidWorks sürümü
- Python sürümü
- İşletim sistemi sürümü
- Ayrıntılı hata mesajı ve yığın izi
- Yeniden üretme adımları

### Özellik İsteği Gönderme

Yeni bir özellik fikriniz varsa:

1. Önce Issues içinde benzer bir istek olup olmadığını denetleyin
2. Fikrinizi açıklayan yeni bir Issue oluşturun
3. Kullanım senaryosunu ve beklenen etkiyi belirtin

### Kod Gönderme

1. **Depoyu Fork edin**
   ```bash
   git clone https://github.com/yourusername/solidworks-automation-skill.git
   cd solidworks-automation-skill
   ```

2. **Dal oluşturun**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Kod yazın**
   - Mevcut kod stiline uyun
   - Gerekli yorumları ekleyin (Türkçe)
   - Kodun SolidWorks 2020 ve üzeri sürümlerde çalıştığından emin olun; mevcut gerçek donanım kabul temeli **2026**'dır, CAD ile ilgili değişiklikler için aşağıdaki "CAD ile ilgili değişikliklerin ek gereksinimleri" bölümüne bakın

4. **Test**
   - Kodunuzu SolidWorks içinde test edin
   - Mevcut işlevselliği bozmadığınızdan emin olun

5. **Commit**
   ```bash
   git add .
   git commit -m "Ekle: özellik açıklamanız"
   ```

6. **Push yapın ve PR oluşturun**
   ```bash
   git push origin feature/your-feature-name
   ```
   Ardından GitHub üzerinde Pull Request oluşturun

## PR İnceleme ve Birleştirme Ölçütleri

Dış PR'lar owner tarafından incelendikten sonra birleştirilir veya kapatılır. Aşağıdaki ölçütler iç ve dış PR'lar için aynı şekilde geçerlidir.

### 1. Göndermeden önceki gereksinimler

- Dal **en güncel `main`** üzerinden oluşturulmalı, "eski dal CI'dan geçti" tarzı sahte geçişlerden kaçınılmalıdır
- **Bir PR yalnızca bir sorunu çözer**. Özellik, düzeltme, yeniden düzenleme ve biçimlendirme aynı PR içinde karıştırılmamalıdır
- PR hedefiyle ilgisiz biçimlendirme veya yeniden sıralama değişiklikleri eklemeyin, bu tür değişiklikler inceleme maliyetini artırır
- Yıkıcı değişiklikler (genel fonksiyon imzalarının değiştirilmesi, varsayılan davranışın değiştirilmesi, yeteneklerin kaldırılması) başlıkta ve açıklamada açıkça `BREAKING` olarak işaretlenmelidir

### 2. PR açıklamasının içermesi gereken altı öğe

| Öğe | Gereksinim |
| --- | --- |
| Sorun / gerekçe | Hangi sorunun çözüleceği, yeniden üretme koşulları; ilgili Issue numarası |
| Çözüm özeti | Neyin değiştirildiği, neden bu şekilde değiştirildiği, alternatiflerin neden seçilmediği |
| Etki kapsamı | Üretim kapılarına (Review / Verification / Execution Core), bağımlılıklara, dışa aktarma formatlarına, yapılandırma dosyalarına dokunup dokunmadığı |
| Geriye dönük uyumluluk | Mevcut çağrıların etkilenip etkilenmediği; varsayılan parametrelerde davranışın değişip değişmediği |
| Geri alma yöntemi | Sorun çıktığında nasıl geri alınacağı, veri taşıma gerekip gerekmediği |
| Test kanıtı konumu | Çevrimdışı testlerin ve gerçek donanım kanıtlarının gerçek yolları |

Yukarıdaki öğelerden herhangi biri eksik olan bir PR için owner, kod incelemesine geçmeden doğrudan tamamlanmasını isteyebilir.

### 3. Test kanıtı gereksinimleri

**Çevrimdışı testler (zorunlu)**

- Göndermeden önce yerel olarak `python -m pytest -q` çalıştırılmalı ve tümü geçmelidir
- Yeni veya değiştirilmiş işlevsellik testle birlikte gelmelidir; yalnızca doküman veya yorum değişiklikleri muaf tutulabilir, ancak açıklamada belirtilmelidir
- Hata enjeksiyonu tipi testler silinemez ve geçmek için iddialar gevşetilemez

**Gerçek donanım testleri (CAD davranışını ilgilendirdiğinde zorunlu)**

- SolidWorks sürümü açıkça belirtilmelidir; bu deponun mevcut gerçek donanım kabul temeli **SolidWorks 2026**'dır
- "Gerçek yürütme" ile "sentetik / mock" açıkça ayrılmalıdır. mock sonuçları gerçek donanım istatistiklerine **dahil edilmez** ve yeteneğin doğrulandığını iddia etmek için kullanılamaz
- Kanıt **yeni ve bağımsız bir dizine** yazılmalı, mevcut çıktı dizinleri ve geçmiş kanıtlar üzerine yazılmamalı veya değiştirilmemelidir

### 4. CI denetimleri

- PR, `test-and-build` durum denetiminden geçmelidir (ruleset `protect-main`'in gerçek zorunlu denetim adı)
- Bu denetim 2026-10-28'den itibaren bir **toplayıcı kapıdır**: beş paralel işi `needs` ile bekler, herhangi biri başarısız olursa başarısız olur,
  ve başarısız olduğunda `skipped` yerine `failure` verir ("çalışmadı"nın "geçti" olarak yanlış okunmasını önlemek için):

  | İş | Kapsam |
  | --- | --- |
  | `governance-gate` | `node --test tests/test_cad_ci_guard.cjs` (şu anda 93 öğe) ve `check_governance_drift.cjs` (10 hassas dosyanın sapma denetimi) |
  | `python-tests` | `pytest` tamamı, skill / MCP / release sözleşme doğrulaması |
  | `frontend-tests` | workbench bağımlılık yüklemesi, başlangıç tanılaması, ön uç testleri ve derlemesi |
  | `rust-tests` | `cargo fmt -- --check`, `cargo test`, `cargo clippy -- -D warnings` |
  | `package-build` | Paketleme, updater sözleşme doğrulaması, taşınabilir sürüm ve kurulum paketi uçtan uca |

- Yukarıdaki yapı `tests/test_release_workflow_contract.py` tarafından kilitlenmiştir: `merge_group` tetikleyicisini silmek,
  zorunlu denetim adını değiştirmek, `needs` içinde iş atlamak, `timeout-minutes` eksik bırakmak, ilk E2E tanılamasını atmak bu testi başarısız kılar,
  sessizce etkisiz hale gelmez
- Zorunlu denetim **dalın main ile eşitlenmesini** gerektirir (`strict_required_status_checks_policy = true`):
  main ilerledikten sonra dal güncellenmeli ve yeniden çalıştırılmalıdır, aksi halde birleştirilemez. Amaç "birleştirme sonrası ağacın" CI'nin doğruladığı ağaç olmasını sağlamaktır
- **`scripts/ci/`, `.github/workflows/`, `tests/test_cad_ci_guard.cjs`,
  `docs/architecture/evidence/` veya güven kökünü değiştirdiğinizde**, `check_governance_drift.cjs --update` çalıştırmalı
  ve `.github/governance-sensitive-manifest.json` dosyasını birlikte göndermelisiniz, aksi halde bu denetim engelleyici olur
- **Yerel geçiş, CI geçişinin yerini alamaz**. İkisinin sonucu tutarsız olduğunda CI esas alınır ve fark araştırılır
- Uçtan uca adımlarda WebView2/CDP başlangıç yarışını absorbe etmek için **1 kez yeniden denemeye** izin verilir: ilk tanılama
  `release-output/e2e-diagnostics.attempt1.*` olarak kaydedilir ve yapı ile birlikte yüklenir (yükleme adımı `if: always()`);
  yeniden denemeden sonra hâlâ başarısızsa başarısız sayılır — **yeniden denemeyle kararlı kusurların gizlenmesine izin verilmez**
- **Gerçek CAD donanım testleri birleştirme ön koşulu değildir**: depoda kendi barındırılan Runner yoktur, `Windows CAD Regression` elle tetiklenir,
  zorunlu denetim değildir ve zamanlanamaz. Birleştirme kararı yalnızca barındırılan CI'ya (`test-and-build`) bakar; gerçek donanım kanıtı bakımcı tarafından yerel makinede kabul edildikten sonra PR açıklamasına yazılır

### 4.1 Birleştirme akışı ve bağımsız incelemenin sınırları

**Dış katkıcıların PR'ları**:

1. Katkıcı Fork eder ve PR açar (bu depoda dış hesapların yazma yetkisi yoktur, korumalı dallara doğrudan push yapamaz)
2. owner kodu, test kanıtını ve etki alanını **elle** satır satır inceler (boyutlar için sonraki bölüme bakın)
3. `test-and-build` **gerçekten geçmelidir**; başarısızsa birleştirilmez, "yerelde geçti" ifadesi ikame olarak kabul edilmez
4. owner tarafından birleştirilir; birleştirmeden sonra sonraki regresyonları takip etmek owner'ın sorumluluğundadır

**owner'ın kendi gönderdiği PR'lar (kısıtların olduğu gibi açıklanması)**:

- Tek kişilik bakım modelinde owner'ın PR'ı **bağımsız üçüncü taraf incelemesi alamaz** — onay yetkisine sahip ikinci bir kişi yoktur.
  Bu proje bu tür PR'ların bağımsız incelemeden geçtiğini **iddia etmez**.
- Bu nedenle owner'ın PR'ı şunları yapmalıdır: PR açıklamasına "tek kişilik bakım nedeniyle bağımsız inceleme yoktur" yazmalı; öz denetim listesini ve test çıktısını eklemeli;
  öz denetimi "incelendi ve geçti" olarak yazmamalı veya sahte approve kaydı oluşturmamalıdır.
- PR'ı geçirmek için `bypass_actors`, yönetici zorla push'u, ruleset'i kapatma veya başarısız denetimi skipped olarak işaretleme **yasaktır**.
  İzin verilen tek istisna "denetimin altyapı arızası nedeniyle (örn. Actions kotasının tükenmesi) çalışamaması"dır; bu durumda arıza kanıtı kaydedilmeli ve doğrulanmadığı belirtilmelidir.

**Birleştirme kuyruğu (merge queue) şu anda kullanılamıyor — olduğu gibi kaydedilmiştir**:

- Bu depo bir **kişisel hesaba (`User`)** aittir, GitHub'ın `merge_queue` kuralı yalnızca organizasyon (`Organization`) depolarına açıktır.
  2026-10-28 testi: `protect-main`'e bu kuralı eklemek `422 Invalid rule 'merge_queue'` döndürür;
  yalnızca bu kuralı içeren **bağımsız bir deneme ruleset'i** ile gönderim de reddedildi, bunun bir parametre hatası değil yetenek eksikliği olduğu doğrulandı.
- İş akışı `merge_group` tetikleyicisini bildirmiştir; depo ileride bir organizasyona taşındığında kuyruk **doğrudan etkinleştirilebilir**, iş akışının yeniden değiştirilmesi gerekmez.
- **Eşdeğer ikame**: `strict_required_status_checks_policy = true`. `pull_request` çalışması
  `refs/pull/N/merge` (main ile PR'ın birleşim sonucu) üzerinde denetim yapar; "main ile eşit olmalı" koşuluyla birlikte
  **birleştirme sonrası ağacın CI'nin doğruladığı ağaç olmasını** garanti eder. Bedeli, main ilerledikten sonra dalın güncellenmesi ve bir kez yeniden çalıştırılmasıdır.
- "Alt işlerin hepsi yeşil" ifadesini "merge queue'dan geçti" olarak **söylemeyin** — şu anda kuyruk yoktur, bu yalnızca güçlü eşitleme + gerçek PR denetimidir.

**stacked PR'ların bilinen açığı (geçmiş kaydı ve sonraki disiplin)**:

- 2026-10-28'den önce `main ← #39 ← #42 ← #43` şeklinde bir yığın vardı, ara katmanın hedef dalı başka bir özellik dalıydı ve
  **zorunlu denetimle bağlı değildi**. Bu yığın 2026-10-28'de sırayla birleştirildi (`4e4df52` → `d9878f6` → `3237eca`).
- Bu süreçte **iki kez ara durum main kırmızısı** görüldü (`4e4df52`, `d9878f6` push çalışmaları),
  kök neden taşınabilir sürüm E2E'nin page yarışıydı ve `6b9bee0` ile onarıldı; başarısız çalışmalar ve günlüklerin tümü incelenebilir şekilde korundu.
- İleride yeniden yığın açılırsa, katman katman birleştirdikten sonra bir sonraki katman için `test-and-build`'in geçtiği **yeniden tetiklenip doğrulanmalıdır**;
  "alt katman PR'ı geçti" ifadesi "üst katman kapı koruması altında" olarak varsayılamaz, bu gerçek gizlenmemelidir.

### 5. Kod inceleme boyutları

owner aşağıdaki boyutlara göre birleştirip birleştirmeyeceğine karar verir:

1. **Doğruluk**: Mantık geçerli mi, sınır koşulları (boş değer, sınır aşımı, eşzamanlılık, COM kopması) ele alınmış mı
2. **Uyumluluk**: Geriye dönük uyumlu mu; varsayılan parametrelerde mevcut davranış bit düzeyinde aynı mı
3. **Güvenlik sınırları**: Doğrulama gevşetilmiş mi, bir başarısızlık başarı olarak gizlenebilir mi, otomatik onay veya incelemeyi atlama yolu eklenmiş mi
4. **Bakım kolaylığı**: Mevcut kod stiline uyuyor mu, gerekli docstring'ler var mı
5. **Kanıt kalitesi**: Testler değişiklik noktalarını kapsıyor mu, gerçek donanım kanıtı yeniden incelenebilir mi, sayısal değerler orijinal ürünlere kadar izlenebilir mi
6. **Gerçek değer**: Gerçek bir sorunu çözüyor mu, proje yönüyle tutarlı mı

### 6. Reddetme veya değişiklik isteme koşulları

Herhangi birinin sağlanması **birleştirilmemesi** anlamına gelir:

- `test-and-build`'den geçmemiş veya CI'yi bozacak bir değişiklik göndermiş
- Araç çağrısı başarısını görev tamamlanması saymış veya doğrulanmadığı halde yeteneğin geçtiğini iddia etmiş
- "Testleri yeşile çevirmek" için mevcut testleri ve hata enjeksiyonunu silmiş, yorum satırına almış veya gevşetmiş
- Üretim kapılarını gevşetmiş (`scripts/sw_review.py`, `scripts/core/verification.py`, `scripts/core/execution.py`)
- Elle incelemeyi, otomatik onayı veya yapılandırılabilir denetim atlamayı devre dışı bırakan bir yol eklemiş
- Geçmiş kanıt dizinlerinin üzerine yazmış, değiştirmiş veya silmiş
- Bir PR birden fazla ilgisiz hedefi karıştırmış ve ayırmayı reddetmiş
- Açıklama kilit bilgilerden yoksun ve hatırlatmadan sonra hâlâ tamamlanmamış

Birleştirilebilir ancak **değişiklik istenmesi** gereken durumlar: adlandırma veya yorumların standart olmaması, sınır işlemenin eksikliği, test kapsamının yetersizliği, dokümanların eşzamanlı güncellenmemesi.

### 7. CAD ile ilgili değişikliklerin ek gereksinimleri

Modelleme, montaj, eşleştirme, dışa aktarma, girişim algılama ve hareket doğrulamayı ilgilendiren değişiklikler ayrıca şunları sağlamalıdır:

- **Sürüm ve backend**: Gerçek SolidWorks sürümü, backend kimliği (örn. `SldWorks.Application.34`) ve kendi kurduğu özel (exclusive) örnek olup olmadığı
- **Yerel geometri kanıtı**: Yerel B-Rep / özellik ağacı / eşleştirme geri okuması esas alınır, **geometri sonucu yerine sınırlayıcı kutu kabul edilmez**
- **Girişim ve temas**: Girişim algılama API'si gerçekten çağrılmalı; kasıtlı sıfır hacimli ortak kenar teması ile hacim penetrasyonu ayrı değerlendirilmeli, "sıfır olmayan temas girdileri"nin tümü penetrasyon olarak ele alınmamalıdır
- **Nihai durum ve temizleme**: Belgenin kaydedilmesi, kapatılması, yeniden açılması sonrası geri okuma sonucu ve kalıntı CAD süreci veya belgesi olup olmadığı açıklanmalıdır
- **Doğrulanmamış kapsam bildirimi**: Bu sefer **doğrulanmayan** içerik açıkça yazılmalıdır (örn. serbest sürükleme, sürekli süpürme, temas dinamiği, yük, Motion Study, üretim onayı)
- **Dışa çıkarım yapılamaz**: Statik durumun geçmesi "hareket yeteneği doğrulandı" olarak ifade edilemez; yerel kabul uzak CI kabulü olarak ifade edilemez

### 8. Masaüstü uçtan uca testler (`ai_team/`)

`ai_team/` altında CAD Studio'nun (Tauri + React) gerçek tarayıcı uçtan uca testleri bulunur.
Bunlar **`pytest` tarafından toplanmaz** ve normal `npm test` içinde çalışmaz, ayrıca yürütülmeleri gerekir.

**Ortak ön koşullar (herhangi biri eksikse başarısız olur; bu bir ortam sorunudur, kod kusuru değildir):**

1. Bağımlılıklar yüklenmiş ve **ön uç ürünü derlenmiş olmalıdır**: `cd apps/workbench-ui && npm ci && npm run build`
   (betik Playwright'ı `apps/workbench-ui/node_modules/playwright` üzerinden içe aktarır, sayfayı `apps/workbench-ui/dist` üzerinden yükler)
2. Chromium yüklenmiş olmalıdır: `cd apps/workbench-ui && npx playwright install chromium`
3. **Depo kök dizininde** yürütülmelidir (betik depo kökünü bulmak için `path.resolve(__dirname, "..")` kullanır)

| Betik | Doğrulanan içerik | Ek ön koşul | Tahmini süre |
| --- | --- | --- | --- |
| `release-portable-e2e.cjs` | Taşınabilir paket başlangıcı, tanılama ürünleri | Önce `scripts/build_windows_release.ps1` çalıştırıp `release-output/` oluşturun | 3–8 min |
| `nsis-install-e2e.ps1` | NSIS kurulum/kaldırma, yükseltme yolu | Yukarıdakiyle aynı, ayrıca yönetici yetkisi gerekir | 5–15 min |
| `delivery-gate-e2e.cjs` | Teslim kapısı, sürüm kaydı, duyarlı düzen | Ön uç derlenmiş olmalı | 1–3 min |
| `preview-viewport-e2e.cjs` | JS önizleme listesi, DXF Worker, katman paneli, canvas boş değil | Ön uç derlenmiş olmalı | 1–3 min |
| `workbench-e2e-final.cjs` | Workbench tam akışı | Ön uç derlenmiş + Tauri yürütülebilir dosyası | 3–8 min |
| `provider-ui-e2e.cjs` | Agent Provider yapılandırma arayüzü | Ön uç derlenmiş olmalı | 2–5 min |
| `ui-layout-check.cjs` | Düzen ekran görüntüsü karşılaştırması, çıktı `ai_team/ui_review/` altına | Ön uç derlenmiş olmalı | 1–2 min |

```powershell
# Tipik sıra
cd apps/workbench-ui; npm ci; npm run build; npx playwright install chromium; cd ../..
node ai_team/delivery-gate-e2e.cjs
node ai_team/preview-viewport-e2e.cjs
```

`ai_team/*` varsayılan olarak `.gitignore` tarafından hariç tutulur ve yalnızca yukarıdaki 7 betiğe izin verilir (bkz. `.gitignore` beyaz listesi).
Yeni bir betik eklerken aynı anda beyaz listeye eklenmelidir, aksi halde depoya girmez.

## Kod Kuralları

### Python kod stili

- 4 boşluk girinti kullanın
- Fonksiyon ve değişkenlerde snake_case kullanın
- Sınıf adlarında PascalCase kullanın
- Sabitlerde UPPER_CASE kullanın
- Türkçe yorumlar ve docstring'ler

### Doküman kuralları

- Tüm genel fonksiyonların docstring'i olmalıdır
- Docstring'ler Türkçe kullanır
- Parametre açıklamaları ve dönüş değeri açıklamaları içerir

Örnek:
```python
def extrude_boss(model, sketch_name, depth, direction=True, merge=True):
    """
    Çıkıntı ekstrüzyonu

    Parametreler:
        model: IModelDoc2
        sketch_name: Kroki adı (örn. "Sketch1")
        depth: Ekstrüzyon derinliği (metre)
        direction: True=pozitif yön
        merge: True=sonucu birleştir

    Döndürür:
        IFeature nesnesi
    """
    # Uygulama kodu...
```

### Commit mesajı kuralları

Türkçe kullanın, biçim aşağıdaki gibidir:

- `Ekle: yeni özellik açıklaması`
- `Düzelt: Bug açıklaması`
- `Güncelle: güncelleme içeriği açıklaması`
- `Doküman: doküman güncelleme açıklaması`
- `Yeniden düzenle: yeniden düzenleme içeriği açıklaması`

## Proje Yapısı

```
solidworks-automation-skill/
├── scripts/              # Çekirdek Python modülleri
│   ├── sw_connect.py    # Bağlantı ve belge yönetimi
│   ├── sw_part.py       # Parça modelleme API
│   ├── sw_assembly.py   # Montaj API
│   ├── sw_drawing.py    # Teknik resim API
│   └── sw_export.py     # Dosya dışa aktarma API
├── references/          # API referans dokümanları
├── examples/            # Örnek kod
├── README.md            # Proje açıklaması
└── CONTRIBUTING.md      # Bu dosya
```

## Yeni Özellik Ekleme

Yeni bir API sarmalayıcısı eklemek isterseniz:

1. İlgili `scripts/sw_*.py` dosyasına fonksiyon ekleyin
2. `references/` içindeki ilgili dokümanı güncelleyin
3. `examples/` içine kullanım örneği ekleyin
4. README.md dosyasını güncelleyin

## Yardıma mı ihtiyacınız var?

- [references/](./references/) dizinindeki dokümanlara bakın
- [examples/](./examples/) dizinindeki örneklere bakın
- Issues içinde soru sorun
- [SolidWorks API resmî dokümantasyonuna](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks_namespace.html) başvurun

## Davranış Kuralları

- Tüm katkıcılara saygı gösterin
- Dostane ve profesyonel olun
- Yapıcı eleştiriyi kabul edin
- Proje için en faydalı olana odaklanın

Katkınız için teşekkürler! 🎉
