# SolidWorks MCP Server

Bu dizin, hem CAD gerektirmeyen açık format araçlarını hem de SolidWorks COM beyaz liste araçlarını sunan yerel bir MCP Server sağlar. MCP; CAD Studio, Skill ve CLI ile aynı yetenek listesini ve veri protokolünü paylaşır.

SolidWorks, Windows masaüstü COM uygulamasıdır ve uzaktan çok istemcili eşzamanlı kullanıma uygun değildir; bu nedenle bu server varsayılan olarak `stdio` kullanır ve dahili olarak tüm SolidWorks işlemlerini genel bir kilit ile seri yürütür.

`stdio` dışında, aynı araç kümesini `--transport streamable-http` ile HTTP üzerinden de sunabilirsiniz; bu, **aynı makinede olmayan** MCP istemcilerinin bağlanmasını sağlar (örneğin Linux üzerindeki bir agent'ın Windows üzerindeki SolidWorks'ü uzaktan sürmesi). Bu durumda genel seri kilit hâlâ geçerlidir; lütfen yine de yalnızca tek bir istemci bağlayın.

## Ortam gereksinimleri

- Windows 10/11
- Yalnızca `cadstudio_write_open_format` çağrılırken SolidWorks/AutoCAD kurulumu gerekmez
- Yerel SolidWorks işlemleri için destek ve kabul hedefi SolidWorks 2026'dır; kurulumdan sonra en az bir kez başlatıp COM kaydını tamamlayın
- Python 3.10+
- Python bağımlılıkları:

```powershell
pip install -r mcp-server\requirements.txt
```

## Başlatma

Depo kök dizininde çalıştırın:

```powershell
python mcp-server\server.py
```

Bu komut genellikle MCP istemcisi tarafından alt süreç olarak başlatılır; elle uzun süre çalıştırmaya gerek yoktur.

## Araç keşif modu (varsayılan)

Varsayılan `SW_MCP_DISCOVERY=search`: `tools/list` yalnızca üç keşif giriş noktasını gösterir; 69 yerel araç isteğe bağlı olarak aranabilir.
Varsayılan olarak istemcinin geçerli görev yetkisini aldığı kabul edilir; görev içi çağrılar artık her seferinde sunucu onayı istemez; daha sıkı denetim gerektiğinde
`server` modu etkinleştirilebilir. Başlangıç araç listesi boyutu şu komutla
`python -m pytest -q tests/test_mcp_discovery_quality.py` doğrulanabilir.

| Giriş noktası | İşlev |
| --- | --- |
| `sw_search_tools` | Çince ve İngilizce ifadelerle adayları arar; ad, açıklama, alaka düzeyi ve yan etki düzeyini döndürür; işlem yürütmez |
| `sw_describe_tool` | Tek bir aracın tam giriş Schema'sını, yan etki düzeyini ve insan onayı gerekip gerekmediğini okur |
| `sw_call_tool` | Adıyla yürütür; policy denetiminden geçer, onay davranışı seçilen moda ve güven sınırına bağlıdır |

Gizlenen yerel araçları doğrudan adıyla çağırmak da ağ geçidinden geçer; bilinmeyen araçlar her zaman reddedilir.

İstemcinin araç bazında izin istemleri göstermesi gerektiğinde, `SW_MCP_DISCOVERY=full` ile 69 adlandırılmış aracın tamamını görüntüleyin.
Her iki mod da aynı yürütme denetimlerini paylaşır; `stdio` ve `--transport streamable-http` davranışı aynıdır.

### Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `SW_MCP_DISCOVERY` | `search` | `search` keşif modu; `full` yerel adlandırılmış araçlar |
| `SW_MCP_APPROVAL` | `auto` | `auto`: keşif modu `task`, tam mod `client` kullanır; `task`: istemcinin görev yetkisine güvenir, her seferinde onay istemez; `server`: yerel, her seferinde onay defteri; `client`: araç bazında onayı istemciye bırakır, yalnızca tam modda izin verilir; `elicit`: MCP elicitation kullanır (agent tarafından otomatik yanıtlanabilir); `off`: sunucu tarafı onayı kapatır |
| `SW_MCP_APPROVAL_DIR` | `%LOCALAPPDATA%\SolidWorksMCP\approvals` | Onay defteri dizini |
| `SW_API_LOOKUP_NETWORK` | `on` | `off` olarak ayarlandığında bu projenin API doğrulamasının resmi belgelere erişmesini engeller; istemcinin kendi aramasını denetlemez |
| `SW_API_LOOKUP_AUTO_INSTALL` | `on` | `off` olarak ayarlandığında API doğrulamasının bağımlılıkları otomatik kurmasını ve yardım dosyalarını geri yüklemesini engeller |
| `SW_AUTO_INSTALL_DEPENDENCIES` | `on` | `off` olarak ayarlandığında temel COM ön kontrolünün ve masaüstü yürütücünün bağımlılıkları otomatik kurmasını engeller |

`solidworks_lookup_api`, `interface` + `member` veya doğal dil `task` destekler; hedef sürüme göre yerel tür kitaplığını, API Help'i ve resmi belgeleri doğrular; doğrudan okuma başarısız olduğunda ve önbellek yokken anonim Parallel kullanır ve yalnızca genel sürüm, arayüz, üye ve resmi bağlantıları gönderir. Varsayılan olarak bağımlılıkları isteğe bağlı otomatik yapılandırır; bu nedenle MCP notları ortamı değiştirebilir olarak işaretlenir; `auto_install=false` kurulumu devre dışı bırakır, `offline=true` ağ erişimini ve kurulumu devre dışı bırakır. Sunucu yan etkiyi parametrelere göre ayırt eder; kullanıcının yapılandırdığı sunucu onay modu hâlâ geçerlidir. Sonuçlar sürüm kanıtını, kaynağı ve edinme zamanını ayırt eder; gerçek makine doğrulamasının yerini tutamaz. Birden çok hedef belirlenemediğinde tahmin etmez veya SolidWorks'ü başlatmaz. `solidworks_connect`, isteğe bağlı `version` yılını destekler ve gerçek bağlantı sürümünü denetler.

### Görev yetkisi ve isteğe bağlı her seferinde onay

Varsayılan `task` modunda görev yetkisini tanımlamak istemcinin veya kullanıcının sorumluluğundadır; MCP sunucusu istemcinin kullanıcıya gerçekten
sorup sormadığını **doğrulayamaz** ve araç bazında yetki yalıtımı sunmaz. Sunucu yine de kayıtlı olmayan araçları reddeder ve parametre doğrulamasını,
hedef kısıtlarını ve SolidWorks seri yürütmesini uygular; aynı yerel yetkilere sahip süreçler bu hizmeti atlayabilir.

Kayıtlı belgelerin etkin belge işlemleri için isteğe bağlı olarak `document_target` (mutlak `path` ve `process_id`) iletilebilir;
sunucu hedefi doğrular; iletilmezse aracın mevcut etkin belge davranışı kullanılır ve kaydedilmemiş belgeler ile mevcut iş akışları desteklenir.

Aşağıda, açıkça `SW_MCP_APPROVAL=server` seçildiğindeki her seferinde onay mekanizması açıklanmaktadır.

**Güven sınırı:** Onay defteri ve komut satırı aynı işletim sistemi kullanıcı yetkisi altında çalışır. TTY denetimi
girdinin gerçek bir kişiden geldiğini kanıtlayamaz: bu kullanıcı yetkisine sahip bir süreç terminali taklit edebilir veya deftere ve imza anahtarına doğrudan erişebilir. Bu nedenle
defter, güvenilir yerel ortamlardaki işlem onayı için uygundur; aynı kullanıcıdaki Agent'ları veya kötü niyetli süreçleri yalıtmanın güvenlik sınırı değildir.
İşlem başına güvenilir insan denetimi gerektiğinde, doğrulanmış güvenilir bir istemci/bağımsız onay mekanizması kullanılmalıdır; `client`,
`elicit` ve `off` modları da yalnızca yapılandırma adına bakılarak insan onayının varlığını garanti edemez.

Araçlar etkin belgeyi, dolaylı yolları veya girdi dosyalarındaki referansları kullanabilir. Şu anda kapsam yetkilendirmesi devre dışıdır ve eski kapsam yetkileri de
tüketilmez. `server` / `elicit` modlarında, bağlamayı destekleyen etkin belge işlemleri `sw_call_tool` aracılığıyla
`document_target` sağlamalıdır; bu, kayıtlı belgenin mutlak `path`'ini ve SolidWorks `process_id`'sini içerir. Örneğin önce
`solidworks_connect` ile `process_id` ve `document.path` okunur, ardından ikisi `document_target` içine konur;
sunucu hedefi parametrelerle birlikte gösterir ve onaya bağlar, kilit tutulurken etkin belge alınırken PID ve yolu yeniden doğrular.

Kaydedilmemiş belgeler, belge kapatma, belge birim ayarları, bileşen ekleme, model incelemesi, Pack and Go ve yerel alt süreç
işlemleri bu bağlamayı henüz desteklemez ve engellenmeye devam eder. PID ve yol konumlandırma için kullanılır;
belge içeriğinin veya harici referansların değişmediğini kanıtlayamaz ve aynı sistem kullanıcı yetkisine sahip süreçleri yalıtamaz. `full` +
`client` veya `off` mevcut istemci denetimini korur, ancak sunucu onayının geçerliliğini garanti etmez. Bu mekanizma henüz gerçek
SolidWorks hedef değiştirme doğrulamasını tamamlamamıştır ve kabul edilmiş bir güvenlik sınırı olarak görülmemelidir.

Modelin `approved: true` veya benzer bir parametre iletmesi etkili olmaz. Bir yazma işlemi engellendiğinde, döndürülen içerik onay isteği ID'sini verir;
bunu bu makineye erişimi olan bir terminalde çalıştırmanız gerekir:

```powershell
python scripts\sw_mcp_approve.py list
python scripts\sw_mcp_approve.py approve <istek ID>
```

Onay, "araç + tam parametre özeti + sunucu oturumu + geçerlilik süresi" ile bağlanır ve tek kullanımlıktır (varsayılan 15 dakika);
parametreler değişirse, sunucu yeniden başlarsa veya oturum değişirse onay yeniden istenmelidir. Açık yollar parametrelere dahildir, ancak
girdi dosyası içeriğinin, dolaylı referansların veya belge durumunun doğrulandığı anlamına gelmez; bu mekanizma güvenilmez ortamlarda kullanılamaz.
İstek kayıtları ve yetki kayıtlarının her biri 1000 kayıt üst sınırına sahiptir; üst sınıra ulaşıldığında sunucu güvenli biçimde yeni kayıtları reddeder, geçmiş
dosyaları otomatik silmez. Kullanıcının kayıtların aidiyetini doğruladıktan sonra kendisinin yedekleyip arşivlemesi gerekir ki onay kullanılmaya devam edilebilsin.

### Eski davranışa geri dönme

MCP istemci yapılandırmasında server sürecine ortam değişkenleri ekleyin:

```jsonc
{
  "command": "python",
  "args": ["C:\\path\\to\\mcp-server\\server.py"],
  "env": { "SW_MCP_DISCOVERY": "full", "SW_MCP_APPROVAL": "client" }
}
```

Bu, tüm yerel araçların görünürlüğünü geri getirir ve araç bazında onayın verilip verilmeyeceğine istemci karar verir. Ortam değişkenlerini değiştirmeyip yalnızca sürümü yükselten istemciler varsayılan olarak keşif modunu kullanır.

### Protokol doğrulaması

```powershell
python scripts\validate_mcp.py            # hem full hem search doğrular
python scripts\validate_mcp.py --mode search
```

Keşif modu doğrulaması 3 giriş noktasının görünür olduğunu, her gerekli aracın adıyla aranabildiğini ve Schema'sının okunabildiğini onaylar; tam mod doğrulaması
69 aracın tamamının görünür olduğunu doğrular.

## HTTP aktarımı (streamable-http)

MCP istemcisi ile SolidWorks aynı makinede olmadığında (örneğin Linux üzerindeki bir agent Windows üzerindeki SolidWorks'ü sürerken), istemcinin yerel stdio alt sürecini doğrudan başlatması mümkün değildir; bu durumda HTTP aktarımına geçin:

```powershell
python -m pip install uvicorn
$env:SW_MCP_TOKEN = "<rastgele paylaşılan anahtarla değiştirin>"
python mcp-server\server.py --transport streamable-http --host 0.0.0.0 --port 8000 `
  --allow-host "192.168.1.10:*" --output-root "C:\cad-output"
```

- Uç nokta: `http://<yerel IP>:8000/mcp` (Streamable HTTP, FastMCP varsayılan yolu `/mcp`)
- `--host` varsayılanı `127.0.0.1`; yerel ağ erişimi için açıkça `0.0.0.0` iletin ve ilgili bağlantı noktasının güvenlik duvarını açın
- `--port` varsayılanı `8000`
- Varsayılan değerler `SW_MCP_HOST` / `SW_MCP_PORT` ortam değişkenleriyle de sağlanabilir; komut satırı parametreleri önceliklidir
- **`uvicorn` isteğe bağlı bir bağımlılıktır**: yalnızca `--transport streamable-http` için gereklidir; eksikse açık bir uyarı verilir
- Varsayılan hâlâ `stdio`'dur; mevcut MCP istemci yapılandırmalarının değiştirilmesi gerekmez
- Geri döngü dışı dinleme için `SW_MCP_TOKEN` ve açık `--allow-host` ayarlanmalıdır; Host alanına istemcinin eriştiği gerçek IP/alan adı yazılır, birden çok kez belirtilebilir
- İstemci istekleri `Authorization: Bearer <paylaşılan anahtar>` taşır; tarayıcı istemcileri ayrıca açıkça `--allow-origin "https://istemci alan adı"` belirtmelidir
- Host/Origin doğrulaması açık kalır; el sıkışma, 401, hatalı Host ve hatalı Origin reddi yerel özel test uç noktasıyla doğrulanmıştır
- Genel ağ veya güvenilmez ağ üzerinden bağlanırken, aktarımı TLS'li bir ters proxy veya denetimli tünel ile koruyun

İstemci yapılandırma örneği (OpenCode / remote MCP destekleyen diğer istemciler):

```jsonc
{
  "mcp": {
    "servers": {
      "solidworks": {
        "type": "remote",
        "url": "http://192.168.1.10:8000/mcp",
        "headers": { "Authorization": "Bearer <paylaşılan anahtar>" }
      }
    }
  }
}
```

İstemcinin URL/headers yapılandırma alanları için ilgili istemci belgelerine bakın. Bu aktarım mevcut MCP sürecini ve COM seri kilidini kullanır.

### Önizleme ve teslim dosyalarını geri alma

Çıktı dosyaları `--output-root` (veya `SW_MCP_OUTPUT_ROOT`) içinde olduğunda, araç sonucuna `artifact_refs` eklenir; bu, opak `artifact_id`, `uri`, dosya boyutu ve SHA-256 içerir. Yapılandırılmadığında yalnızca sistem geçici dizini altındaki `solidworks-automation-artifacts` dizinine izin verilir; teslim dizinini açıkça belirtmeniz önerilir.

- `cadstudio_read_artifact` çağırın; parametre `{"params":{"artifact_id":"<sonuçtaki ID>"}}` biçimindedir, küçük görseller standart PNG içerik bloğu döndürür.
- Sonuçtaki `cad-artifact://delivery/...` URI'sini `resources/read` ile okuyun ve 8 MiB'ı aşmayan ham ikili dosyayı geri alın.
- Büyük dosyalar için `cadstudio_read_artifact` kullanın; `as_preview:false`, `offset`, `max_bytes` ayarlayın ve base64 bloklarını `next_offset` ile birleştirin; tamamlandığında SHA-256'yı karşılaştırın.
- Okuma uyarlaması mevcut Artifact Ledger'ı yeniden kullanır; dosya değişirse, dizin dışına çıkılırsa veya keyfi yol parametreleri verilirse doğrulanmış ürün olarak okunamaz.

Uzak girdiler yine de önceden CAD ana makinesine yerleştirilmelidir; ürün okuma arayüzü yalnızca mevcut teslim dosyalarına hizmet eder.
Araçlar **şu anda toplam 69 tanedir**. Keşif modunda bu araçlar `tools/list` içinde görünmez, ancak arama, Schema okuma ve yürütme davranışı tam modla aynıdır. `cadstudio_list_drc_rules` tasarım denetimi kurallarını listeler; `cadstudio_check_drc` nötr belgeyi denetler ve rapor yazar, bir yazma işlemidir ve katı modda onay gerektirir. API doğrulaması bağımlılıkları isteğe bağlı yapılandırabilir; izin davranışı yukarıda açıklanmıştır.

## Smithery yayını

Kök dizindeki `manifest.json` MCPB spesifikasyonuna uyar ve `tools_generated: true` kullanır. Önce `mcpb pack` ile standart paketi üretin, ardından FastMCP'nin gerçek `inputSchema`'sını içeren Smithery yayın paketini oluşturmak için aşağıdaki komutları çalıştırın:

```powershell
mcpb pack . .\dist\solidworks-automation-skill-1.3.0.mcpb
python .\scripts\build_smithery_mcpb.py `
  .\dist\solidworks-automation-skill-1.3.0.mcpb `
  .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb
smithery mcp publish .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb `
  -n wzyn20051216/solidworks-automation-skill
```

Smithery'nin mevcut yayın arayüzü, araç kartlarının `inputSchema` içermesini gerektirirken MCPB 0.4'ün statik `tools` öğeleri bu alana izin vermez; bu nedenle yayın paketi, iki ayrı schema'yı elle bakımını önlemek için betik tarafından MCP Server kayıt defterinden otomatik oluşturulur. Araç kartları tam kayıt defterinden gelir (72 öğe: 69 yerel araç + 3 keşif giriş noktası) ve çalışma zamanındaki `SW_MCP_DISCOVERY` seçiminden bağımsızdır.

## Çok istemcili otomatik kayıt

Bu depo, `solidworks` MCP Server'ı aşağıdakilere otomatik olarak kaydetmeyi deneyen çok istemcili bir kayıt aracı sağlar:

- Codex
- Claude Code
- Claude Desktop
- Cursor
- Windsurf

Depo kök dizininde çalıştırın:

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies
```

Yalnızca belirtilen istemciyi kaydedin:

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies -Clients codex,claude-code,cursor
```

Node.js sürümü doğrudan `npx` yükleyicisinde veya CI'da kullanılabilir:

```powershell
node .\mcp-server\register_all_ai_mcp.js --install-dependencies
```

Kayıttan sonra istemciye göre denetleyin:

```powershell
codex mcp list
claude mcp list
```

> Bu depo üzerinden `npx` ile kurulum yapıldığında çok istemcili kayıt aracı otomatik çalışır. Bazı AI istemcilerinin salt skill içe aktarımı kurulum betiğini çalıştırmaz; yukarıdaki kayıt komutunu yerel olarak çalıştırmanız gerekir.

## Codex'e özel kayıt

Yalnızca Codex'i kaydetmek istiyorsanız:

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_codex_mcp.ps1 -InstallDependencies
```

## Elle yapılandırma

Yolu kendi yerel depo yolunuzla değiştirin:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": [
        "C:\\path\\to\\solidworks-automation-skill\\mcp-server\\server.py"
      ]
    }
  }
}
```

İstemciniz komut satırı kaydını destekliyorsa benzer bir komut da kullanabilirsiniz:

```powershell
codex mcp add solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
claude mcp add --scope user solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
```

## Sunulan araçlar

| Araç | Açıklama | SolidWorks'ü değiştirir mi |
|---|---|---|
| `cadstudio_resolve_backend` | Yetenek gerçek kaynağına, arayüz semantiğine, kullanılabilir çalışma zamanına, Revision ve eklenti koşullarına göre Python/C#/C++/SWBasic/OCCT gibi arka uçları seçer | Hayır |
| `cadstudio_write_open_format` | Yerel `.cadstudio.json` beyaz listesinden STEP/IGES/BREP/STL/OBJ/GLB/DXF/SVG/PDF/PNG, Preview Manifest/Scene ve geometri/hash kanıtı yazar | Hayır |
| `cadstudio_build_dxf_preview_scene` | Salt okunur DXF beyaz listesini eski dosyaların üzerine yazmayan `.scene.json` biçimine dönüştürür | Hayır |
| `cadstudio_read_artifact` | Teslim ID'sine göre PNG önizleme veya sınırlı ikili blok döndürür, mevcut Ledger'ın SHA-256'sını doğrular | Hayır |
| `cadstudio_check_dfm` | NeutralCadDocument üzerinde işleme, sac metal, lazer kesim, 3D baskı veya enjeksiyon kalıplama beyanına dayalı DFM denetimi yapar; kritik girdi eksikse blocked döndürür, kural geçse de insan incelemesi gerekir | Hayır |
| `cadstudio_check_routing` | Nötr Routing uç noktalarını, segmentlerini, uzunluğunu, bükülme yarıçapını, çarpışma/açıklığı, destekleri ve Routing BOM'u doğrular | Hayır |
| `cadstudio_routing_preflight` | SOLIDWORKS Routing tür kitaplığını, eklenti kaydını ve lisans kanıtını yoklar; kanıt eksikse blocked döndürür | Hayır |
| `solidworks_addin_host_status` | C# Add-in derlemesini, HKCU/HKLM kayıt katmanını, süreç içi UI/olay tanılamasını ve blok kodunu salt okunur denetler | Hayır |
| `solidworks_lookup_api` | Hedef sürüme göre API'yi doğrular; varsayılan olarak ağa bağlanır ve bağımlılıkları isteğe bağlı otomatik kurar, CAD'i başlatmaz veya değiştirmez | Parametreye göre: varsayılan olarak ortamı değiştirebilir; otomatik kurulum kapatılabilir |
| `cadstudio_fea_preflight` | CalculiX/Elmer çözücülerini yoklar, keyfi komut çalıştırmaz | Hayır |
| `cadstudio_prepare_fea` | FEA 1.0/1.1 isteklerinden sürümlenmiş CalculiX `.inp` üretir, keyfi betik çalıştırmaz | Hayır |
| `cadstudio_run_fea` | Beyaz listedeki CalculiX doğrusal veya sınırlı doğrusal olmayan statik görevini çalıştırır ve yer değiştirme, gerilme ve yakınsama kanıtını ayrıştırır | Hayır |
| `cadstudio_run_fea_convergence` | 3-8 kademeli beyaz liste ağı çalıştırır ve son iki kademenin yer değiştirme/gerilme değişimini karşılaştırır | Hayır |
| `cadstudio_review_advanced_geometry` | Karmaşık yüzey/kalıp nötr planını doğrular ve pilot/blocked geçit kanıtı döndürür | Hayır |
| `cadstudio_create_ocp_loft` | Beyaz listedeki kapalı kesitlerden gerçek düz çizgili Loft STEP/BREP/STL üretir ve B-Rep'i yeniden açarak doğrular | Hayır |
| `cadstudio_create_ocp_surface` | Katı JSON'dan düzgün Loft, düz çizgi/yay Sweep, kapalı kabuk Knit veya açık yüz Thicken üretir ve süreklilik örnekleme kanıtı döndürür | Hayır |
| `solidworks_health_check` | Python bağımlılıklarını, SolidWorks algılamasını, Motion tür kitaplığını ve isteğe bağlı canlı bağlantıyı denetler | Hayır |
| `solidworks_connect` | SolidWorks'e bağlanır/başlatır ve etkin belge özetini döndürür | Hayır |
| `solidworks_new_document` | Yeni parça/montaj/teknik resim oluşturur | Evet |
| `solidworks_create_basic_part` | Temel kutu/silindir parça oluşturur, kaydedebilir ve belge rengini ayarlayabilir | Evet |
| `solidworks_open_document` | Mevcut SolidWorks belgesini açar | Evet |
| `solidworks_add_component` | Etkin montaja parça/alt montaj ekler, isteğe bağlı olarak bileşeni sabitler | Evet |
| `solidworks_set_component_fixed` | Bileşen adı anahtar kelimesine göre montaj bileşenini sabitler veya serbest bırakır | Evet |
| `solidworks_save_document` | Etkin belgeyi kaydeder veya farklı kaydeder | Evet |
| `solidworks_close_documents` | Etkin belgeyi veya tüm belgeleri kapatır | Evet, kaydedilmemiş değişiklikler kaybolabilir |
| `solidworks_add_coincident_mate` | İki bileşenin belirtilen referans düzlemleri/özellikleri arasına çakışık Mate ekler | Evet |
| `solidworks_add_distance_mate` | İki bileşenin belirtilen referans düzlemleri/özellikleri arasına mesafe Mate ekler | Evet |
| `solidworks_add_concentric_mate` | Silindir yüzü yarıçap aralığına göre eş merkezli Mate ekler, dönüşün kilitlenip kilitlenmeyeceği seçilebilir | Evet |
| `solidworks_set_appearance` | Etkin belgenin veya belirtilen bileşenin görünüm rengini ayarlar | Evet |
| `solidworks_export_active` | Etkin belgeyi STEP/STL/IGES/Parasolid/PDF/DXF olarak dışa aktarır | Evet, çıktı dosyası yazar |
| `solidworks_inspect_configurations` | Yapılandırma listesini ve geçerli etkin yapılandırmayı okur | Hayır |
| `solidworks_create_configuration` | AddConfiguration3 ile yapılandırma oluşturur/yeniden kullanır; etkinleştirebilir, yeniden oluşturabilir, kaydedebilir ve geri okuyabilir | Evet |
| `solidworks_activate_configuration` | Yapılandırmayı değiştirir ve etkin yapılandırma adı ile yeniden oluşturma sonucuyla geri okuma doğrulaması yapar | Evet |
| `solidworks_update_dimension` | Kesin boyut adına göre parametreyi değiştirir, değişiklik öncesi/sonrası, yeniden oluşturma ve kayıt kanıtı döndürür | Evet |
| `solidworks_set_custom_properties` | Dosya düzeyinde veya yapılandırma düzeyinde özel özellikleri yazar ve geri okur | Evet |
| `solidworks_batch_export_files` | Çok dosyalı, çok biçimli toplu dışa aktarma yapar ve bu turun ürünlerini doğrular | Evet, çıktı dosyası yazar |
| `solidworks_export_assembly_bom` | Montaj bileşeni/özellik BOM CSV'sini dışa aktarır, insan incelemesini zorunlu kılar | Evet, çıktı dosyası yazar |
| `solidworks_pack_and_go` | Yerel Pack and Go ile belgeleri ve referansları paketler | Evet, çıktı dosyası yazar |
| `solidworks_review_active` | Çok açılı BMP önizlemeleri ve JSON inceleme raporu dışa aktarır | Evet, çıktı dosyası yazar |
| `solidworks_generate_drawing` | DrawingSpec v1'e göre GB/T/ISO teknik resim, SLDDRW, PDF, önizleme ve inceleme raporu üretir; COM boyut konumlarını nihai PDF metin kutularıyla ilişkilendirir | Evet, çıktı dosyası yazar |
| `solidworks_review_drawing` | DrawingSpec'e göre teknik resim yapısını, düzenini, boyut zincirini, delik yuvalarını ve nihai PDF boyut metni sınırlarını inceler | Hayır, inceleme çıktısı yazar |
| `solidworks_inspect_drawing` | Teknik resim sayfalarını, görünümlerini, boyutlarını, notlarını, tablolarını ve BMP önizleme kanıtını salt okunur biçimde okur | Hayır, inceleme çıktısı yazar |
| `solidworks_create_hole_feature` | Kör delik, geçme delik, havşa, havşa başlı delik veya yarım daire uçlu yuva oluşturur ve parametre kanıtı döndürür | Evet |
| `solidworks_inspect_hole_features` | B-Rep delik segmentlerini, bileşik delikleri, yuva ucu yaylarını okur ve delik konumlarını doğrular | Hayır |
| `solidworks_add_rotary_motor` | Etkin montajda yeni Motion Study oluşturur ve sabit hızlı döner motor ekler | Evet |
| `solidworks_inspect_motion_studies` | Çalışmaları, motor/dış kuvvet sayılarını ve sonuç tazeliğini okur | Hayır |
| `solidworks_validate_motion_study` | Süre, tür, motor sayısı, sonuç varlığı ve eskime durumu için teslim geçidi uygular | Hayır |

## Temel montaj aracı örnekleri

Silindir parça oluşturma:

```json
{
  "shape": "cylinder",
  "radius_mm": 25,
  "depth_mm": 50,
  "output_path": "C:\\temp\\cylinder.SLDPRT",
  "color": "#BFC4C8"
}
```

Etkin montaja bileşen ekleyip sabitleme:

```json
{
  "path": "C:\\temp\\base.SLDPRT",
  "x_mm": 0,
  "y_mm": 0,
  "z_mm": 0,
  "fix_component": true
}
```

Dönme serbestliğini koruyan eş merkezli Mate ekleme:

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "radius_a_min_mm": 4.5,
  "radius_a_max_mm": 5.5,
  "radius_b_min_mm": 11,
  "radius_b_max_mm": 13,
  "lock_rotation": false
}
```

Eksenel mesafe Mate ekleme:

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "feature_a_name": "Front Plane",
  "feature_b_name": "Front Plane",
  "distance_mm": 42
}
```

## Motion Study örneği

Ön koşul: Etkin belge bir montajdır ve içinde sabit bir mil/direk bileşeni ile bir çark (impeller) bileşeni vardır; çarkın eş merkezli Mate'i dönüşü kilitlememiştir ve çark bileşeni sabit değildir.

Örnek çağrı parametreleri:

```json
{
  "shaft_component_keyword": "stand",
  "rotor_component_keyword": "impeller",
  "shaft_radius_min_mm": 4.5,
  "shaft_radius_max_mm": 5.5,
  "rotor_radius_min_mm": 10.5,
  "rotor_radius_max_mm": 11.5,
  "rpm": 60,
  "study_name": "çark_60RPM_döngüsel_dönüş",
  "motor_name": "çark_döner_motor_60RPM",
  "duration_seconds": 4,
  "calculate": true,
  "play": false
}
```

Karmaşık havşa oluşturma:

```json
{
  "feature_kind": "counterbore",
  "center_x_mm": 20,
  "center_y_mm": 15,
  "diameter_mm": 6,
  "secondary_diameter_mm": 12,
  "secondary_depth_mm": 4,
  "plane_name": "Front Plane",
  "feature_name": "H1_havşa"
}
```

Motion Study doğrulama:

```json
{
  "study_name": "çark_60RPM_döngüsel_dönüş",
  "expected_study_type": 1,
  "minimum_duration_seconds": 4,
  "minimum_motor_count": 1,
  "require_results": true
}
```

## Tasarım ilkeleri

- Keyfi Python/VBA yürütme aracı açılmaz; MCP istemcisinin denetimsiz betik çalıştırmasını önler.
- CAD Studio başsız/geçit araçları `cadstudio_` ön ekini, yerel SolidWorks araçları `solidworks_` ön ekini kullanır; diğer MCP server'larla çakışmayı önler.
- Tüm COM işlemleri seri yürütülür; SolidWorks masaüstü oturumunun çökme olasılığını azaltır.
- Hata dönüşleri önerilen eylemleri içerir; LLM'in kendi kendini düzeltmesini kolaylaştırır.

## Bilinen sınırlamalar

- MCP; temel kutu/silindir, karmaşık delik yuvaları, bileşen ekleme, yaygın Mate'ler, sabitleme/serbest bırakma, görünüm, dışa aktarma, inceleme, döner motor, Motion sonuç geçidini ve DFM/Routing/FEA/karmaşık geometri için denetimli giriş noktalarını kapsar.
- Sınırlı kapalı düz çizgili Loft gerçek STEP/BREP üretebilir ve yeniden açabilir; düzgün Loft, süpürme, serbest yüzey, G1/G2 ve kalıp hâlâ yalnızca yapılandırılmış plan geçidi olarak sunulur.
- SolidWorks Motion / Simulation lisans farklılıkları hesaplama yeteneğini etkileyebilir; geçerli eklenti veya yetki yoksa `blocked` döndürülür, atlatılmaya çalışılmaz.

## Yerel dairesel kesit yolu araçları

Beş korumalı deneysel araç; yerel süpürmeyi, STEP içe aktarmayı, gövde incelemesini/hariç tutmayı ve konumu koruyan bileşen değiştirmeyi destekler. Spesifikasyon, sınırlama ve inceleme gereksinimleri için bkz. [araç açıklaması](../docs/native-wire-tools.md).
