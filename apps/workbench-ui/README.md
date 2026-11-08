# CAD Studio Masaüstü Workbench

Bu, CAD Studio'nun resmi React + Tauri masaüstü istemcisidir.

Tasarım yönü:

```text
Apple tarzı yerel mühendislik yazılımı; açık renkli yüzen pencereler, görünüm merkezi, yerel duvar kağıdı içe aktarma, sağ tarafta Inspector, net P0 kapıları ve uygulanabilir iş akışları.
```

Mevcut çalıştırma biçimleri iki tanedir:

- Hızlı UI ayarı için Vite tarayıcı önizlemesi.
- Windows `.exe` üretmek için Tauri masaüstü uygulaması.

Mevcut arayüz şunları içerir:

- Sağ üst köşede görünüm katmanı; yerel resim, GIF ve video duvar kağıdı içe aktarmayı destekler, parlaklık, bulanıklık ve vinyet ayarlanabilir.
- Yerel yapılandırma kalıcılığı; geçerli duvar kağıdını, son duvar kağıtlarını, parlaklığı, bulanıklığı, vinyeti ve son içe aktarılan model yollarını otomatik hatırlar.
- Yerel otomasyon kuyruğu; masaüstü tarafı yeni CAD görevi oluşturma, model içe aktarma ve teslim paketi üretme görevlerini JSON olarak kaydeder.
- Agent Bridge paneli; grafiksel yapılandırmayı Codex, Claude Code, Gemini CLI veya OpenCode tarafından çalıştırılabilir görevlere dönüştürür.
- CC Switch, geçerli kullanıcının SQLite/eski sürüm JSON yapılandırmasını eşzamanlı okur, seçilen Agent'a göre model yönlendirmesini gösterir; anahtarları okumaz veya göstermez.
- Varsayılan olarak `AI otomatik olarak en iyi çözümü seçer`; kullanıcı belirtmediğinde görev türünü, süreci, malzemeyi, çıktı biçimini ve kontrol maddelerini otomatik belirler.
- Policy Gate onay kapısı; tehlikeli görevler önce onay bekleyen duruma girer.
- Artifact Ledger teslimat defteri; çıktı dosyalarının varlığını, boyutunu, SHA-256'sını ve bu turdaki güncelliğini kaydeder; eski dosyalar teslim edilebilir duruma giremez, doğrulanamadığında manuel incelemeye girer.
- Kuyruk paneli, masaüstü tarafında yerel Python worker'ı başlatıp/durdurur ve çalışma durumu ile PID'yi gösterir.
- Worker Health sağlık sinyali ve Reviewer Gate teslimat/biçim özelliği incelemesi.
- İncelenecek görevler manuel "incelemeyi onayla/reddet" işlemini destekler; inceleyeni, zamanı, sonucu ve denetim olaylarını kaydeder.
- Varsayılan kiraz çiçeği hareketli duvar kağıdı (ses kanalı ve konum meta verileri kaldırılmıştır); ayrıca Aurora, Blueprint, Studio, Mist. Herhangi bir yerel resim/GIF/video içe aktarma ve geçiş desteklenir.
- Yerel öncelikli profesyonel bilgi bankası: SolidWorks, üretim ve teknik resim standartlarını otomatik arar; kurumsal standart dizinleri eklenebilir.
- İsteğe bağlı HTTPS bulut RAG: yalnızca açıkça etkinleştirildiğinde ve harici ağ onayı geçildiğinde çağrılır; token yalnızca ortam değişkeninden okunur.
- macOS tarzı pencere çubuğu, açık renkli Dock navigasyonu, proje workbench'i ve sağ tarafta Inspector parametre paneli.
- Proje girişi arama, arşivleme/geri yükleme, kopyalama ve silmeyi destekler; görev geçmişi son durum kayıtlarının toplu temizliğini destekler; tüm işlemler yalnızca uygulama meta verilerini temizler, CAD teslim dosyalarını silmez.
- SQLite taşıma işlemi eski anlık görüntüleri korur ve proje, konuşma, mesaj ve görev dizinleri oluşturur; ayarlar sayfası dizin sayısı tutarlılığını gösterir.
- Düğme hover, basma geri bildirimi ve ana düğme parıltı geçiş efekti.
- Masaüstü ve mobil uyumlu önizleme ekran görüntüleri.

Yayın sürümü yükleyicisi skill, Python worker ve mekanik bilgi belgelerini içerir. Kullanıcının yine de Python, en az bir Agent CLI ve gerçek işlem için SolidWorks/AutoCAD kurması gerekir.

Tam kullanıcı belgesi: [CAD Studio Kullanıcı Kılavuzu](../../docs/CAD_STUDIO_USER_MANUAL.md).

Notlar:

- Tarayıcı önizleme modu, kullanıcının içe aktardığı yerel resmi yalnızca geçici olarak önizleyebilir; çünkü tarayıcı yenilendikten sonra özgün dosya yoluna yeniden erişemez.
- Tauri masaüstü modu yerel dosya seçiciyi kullanır; yerel dosya yolunu kaydedebilir ve sonraki başlatmada duvar kağıdını geri yükleyebilir.

## Kurulum

```powershell
cd apps\workbench-ui
npm install
```

## Geliştirme önizlemesi

```powershell
npm run dev
```

## Masaüstü geliştirme

```powershell
npm run desktop:dev
```

## Derleme

```powershell
npm run build
```

## Masaüstü uygulaması oluşturma

```powershell
npm run desktop:build
```

Bu komut çalıştırılabilir bir `.exe` üretir, ancak henüz yükleyici paketlemez.

Yükleyici üretmek isterseniz:

```powershell
npm run desktop:bundle
```

Çıktı programı:

```text
apps\workbench-ui\src-tauri\target\release\cad-studio.exe
```

## Yerel otomasyon kuyruğu

Protokol belgesi:

```text
apps\workbench-ui\docs\automation-queue-protocol.md
```

Masaüstü görevleri Tauri uygulama veri dizinindeki `queue` klasörüne kaydedilir. Python worker prototipi:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --queue-dir "<kuyruk-dizini>"
```

Sürekli dinleme:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<kuyruk-dizini>"
```

Resmi masaüstü başlatma, birleşik Agent handler'ı etkinleştirir ve mock yüklemez. `create_shell`, `import_model`, `delivery_package` için mock yalnızca `--enable-mock` ile açıkça etkinleştirilebilir; kuyruk protokolü geliştirme testleri için kullanılır ve ürün teslim sonucu olarak kullanılamaz.

Birleşik Agent yürütücüsünü etkinleştirme:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<kuyruk-dizini>"
```

Masaüstü tarafı doğrudan "Ayarlar -> Yerel yürütme" üzerinden başlatabilir. Geliştirme sürümü öncelikli olarak mevcut depoyu kullanır, kurulu sürüm gömülü skill kaynaklarını kullanır. Durdur'a tıklandığında yazılımın yönettiği worker süreç ağacı sonlandırılır ve tamamlanmamış görevler yeniden kuyruğa alınır; Alt+F4 ve sistem çıkışı da aynı temizliği yapar.

Agent Bridge'in sorumluluk sınırları:

- UI, tıklama yapılandırmasını, mühendislik kurallarını, hedef çıktıyı ve prompt önizlemesini toplamaktan sorumludur.
- Kuyruk, görevleri JSON olarak kalıcı hale getirmekten ve `.lock`, lease, stale kurtarma, quarantine, Worker Health, Artifact Ledger ve Reviewer Gate aracılığıyla yerel güvenilir yürütmeyi garanti etmekten sorumludur.
- worker, görevleri doğrulamak, Policy Gate'i çalıştırmak, çalışma alanını sınırlamak, çıktı yolunu sabitlemek ve `codex exec` çağırmaktan sorumludur.
- Seçilen Agent, skill'i yürütmek, yerel CAD'i çağırmak, doğrulamayı çalıştırmak ve birleşik yapılandırılmış sonucu döndürmekten sorumludur.

Tehlikeli yetenekler `approval_required` durumuna girer: Git push, `danger-full-access`, CAD makroları, harici ağ, çalışma alanları arası yazma ve dosya silme. Masaüstünde "Onayla"ya tıklandıktan sonra görev `queued` durumuna döner.

Varsayılan Codex sandbox'ı `workspace-write`'dır. Gerçekten tam yetki gerekiyorsa, görev önce onaydan geçmeli ve worker başlatılırken açıkça eklenmelidir:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --codex-full-access --queue-dir "<kuyruk-dizini>"
```

Kurumsal kontrol düzlemi belgesi:

```text
docs\agent-framework\enterprise-agent-control-plane.md
```
