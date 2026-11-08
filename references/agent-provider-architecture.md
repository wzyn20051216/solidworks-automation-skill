# Çoklu Agent Provider Mimarisi

## Amaç

CAD Studio farklı kullanıcı ortamlarını hedefler ve tek bir modele veya CLI'ye bağlı değildir. Tüm Provider'lar tek bir CAD görev protokolünü, onay politikasını, bilgi erişimini, ürün kayıt defterini ve inceleme kapısını paylaşır; farklar yalnızca komut derleme ve sonuç ayrıştırma katmanında kalır.

```text
Kullanıcı görevi
  -> UnifiedAutomationJob
  -> Policy Gate
  -> Provider Adapter
  -> Codex / Claude Code / Gemini CLI / OpenCode / LM Studio
  -> UnifiedAgentResult
  -> Artifact Ledger
  -> CAD/B-Rep/Motion Reviewer Gate
  -> yerel teslimat dizini
```

## Provider durumları karıştırılamaz

Arayüz ve günlükler aşağıdaki durumları ayrı ayrı ifade etmelidir:

| Durum | Kanıt | Bağlı olarak ifade edilebilir mi |
|---|---|---|
| Kurulu değil | CLI girişi bulunamıyor veya `--version` başarısız | Hayır |
| Kurulu | `--version` başarılı | Hayır |
| Kimlik doğrulama başarısız | Resmi kimlik doğrulama durum komutu başarısız | Hayır |
| Kimlik doğrulama doğrulanacak | CLI'nin düşük maliyetli kimlik sorgu komutu yok | Hayır, ilk gerçek görevde doğrulanır |
| Kimlik doğrulama doğrulandı | Resmi kimlik komutu başarılı | Kimlik doğrulama doğrulandı olarak ifade edilebilir |
| Yürütme doğrulandı | Gerçek görev birleşik protokolle yapılandırılmış sonuç döndürdü | O görev yürütmesi başarılı olarak ifade edilebilir |

CLI'nin varlığı, ortam değişkeninin varlığı veya CC Switch'te Provider yapılandırması tek başına model isteğinin kullanılabilir olduğunu kanıtlamaz. Provider'ın kendi başarı bildirimi de SolidWorks/AutoCAD ürününün doğru olduğunu kanıtlamaz.

## Birleşik görev protokolü

Görev türü `agent_task`, yürütücü `agent` kullanır:

```json
{
  "kind": "agent_task",
  "executor": "agent",
  "objective": "Havşa ve yarım daire kanal içeren montaj plakası oluştur",
  "skillPath": "C:/Users/user/.codex/skills/solidworks-automation/SKILL.md",
  "uiConfig": {
    "agentRuntime": {
      "provider": "claude",
      "providerName": "Claude Code",
      "protocol": "claude-print-v1",
      "model": ""
    }
  }
}
```

Eski `codex_task` ve `executor=codex` yalnızca uyumluluk girişi olarak kullanılır; Worker'a girdikten sonra yine aynı yürütme akışına normalleştirilir.

## Birleşik sonuç protokolü

Her Provider sonunda aşağıdaki alanları üretmelidir:

```json
{
  "summary": "Bu turda ne yapıldı",
  "changedFiles": [],
  "verification": [],
  "risks": [],
  "nextSteps": []
}
```

Birleşik sonuç yalnızca Agent yürütme kaydıdır, CAD kabul kanıtı değildir. Mekanik teslimat yine bağımsız dosya karması, B-Rep ölçüleri, delik/kanal konumlandırması, önizleme görüntüsü, Motion sonucu ve insan inceleme kaydı gerektirir.

## Mevcut Adapter

| Provider | Protokol ID | Etkileşimsiz giriş | Yapılandırılmış çıktı kaynağı |
|---|---|---|---|
| Codex | `codex-exec-v1` | `codex exec` | `--output-schema` + çıktı dosyası |
| Claude Code | `claude-print-v1` | `claude -p` | `--output-format json` + `--json-schema` |
| Gemini CLI | `gemini-headless-v1` | `gemini -p` | JSON response sarmalayıcısı |
| OpenCode | `opencode-jsonl-v1` | `opencode run` | JSONL metin olayları |
| LM Studio | `lmstudio-openai-v1` | `lmstudio_client.py` | OpenAI uyumlu `/chat/completions` yanıtı |

Uygulama şu dosyalarda bulunur:

- `apps/desktop/cad_workbench/agent_providers.py`
- `apps/desktop/cad_workbench/lmstudio_client.py`
- `apps/desktop/cad_workbench/queue_worker.py`
- `apps/workbench-ui/src-tauri/src/lib.rs`

### LM Studio uç noktası

LM Studio harici bir CLI gerektirmez; yerel OpenAI uyumlu REST API'si üzerinden çalışır. Varsayılan uç nokta `http://127.0.0.1:1234/v1` olup `LMSTUDIO_BASE_URL` ortam değişkeniyle değiştirilebilir. `LMSTUDIO_API_KEY` ayarlanırsa istek `Authorization: Bearer` başlığıyla gönderilir; yerel sunucu genelde bunu istemez. Model açıkça seçilmezse `/models` listesindeki ilk yüklü model kullanılır.

## Yeni Provider ekleme adımları

1. Kararlı ID'yi `SUPPORTED_PROVIDER_IDS` ve ön yüzdeki `AgentProviderId` içinde kaydet.
2. Yalnızca o CLI'nin resmi dokümantasyonunda doğrulanmış etkileşimsiz parametreleri kullan; seçenekleri ezberden tahmin etme.
3. `build_provider_command()` içinde birleşik görevi Provider komutuna derle.
4. `parse_provider_result()` içinde yerel sarmalayıcıyı ayrıştır ve sonunda birleşik sonuç alanlarına zorla yakınsa.
5. Kurulum, kimlik doğrulama, zaman aşımı, JSON olmayan, eksik alan ve iptal görevi testleri ekle.
6. Masaüstü sağlık kontrolünde kurulum, kimlik doğrulama ve yürütme doğrulamasını ayır; belirsiz bir "bağlı" boolean değeri ekleme.
7. Gerçek minimum sonda yürüt; çıkış kodu, stdout/stderr, iptal ve zaman aşımı davranışını doğrula.

## Gözlemlenebilir yürütme süreci

Yazılım planı, genel adımları, araç çağrılarını, onayları, günlükleri, dosya değişikliklerini ve inceleme sonuçlarını gösterebilir. Modelin gizli düşünce zincirini vaat etme veya uydurma; kullanıcının gerçekten ihtiyaç duyduğu şey denetlenebilir yürütme izi ve üzerine soru sorulabilen konuşma bağlamıdır.

## Güvenlik sınırları

- Provider Adapter rastgele Python, PowerShell veya VBA araçlarını doğrudan açığa çıkarmaz.
- CAD COM çağrıları seri hale getirilir; birden fazla Agent'ın aynı masaüstü oturumunu eşzamanlı işletmesi önlenir.
- Dış ağ, bulut RAG ve tehlikeli yerel CAD işlemleri Policy Gate'e girer.
- API Key görev JSON'una, günlüklere veya ön yüz kalıcı depolamasına yazılmaz; yalnızca gizliliği temizlenmiş durum veya ortam değişkeni adı kaydedilir.
- Provider çıktısı schema, Artifact Ledger ve Reviewer Gate'ten geçmelidir; doğrudan teslimat başarısı ilan edilemez.
