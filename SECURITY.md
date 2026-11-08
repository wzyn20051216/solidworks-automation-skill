# Güvenlik Politikası

## Desteklenen Sürümler

Güvenlik düzeltmeleri öncelikli olarak GitHub Releases'teki en yeni CAD Studio sürümünü ve `main` dalını kapsar.

## Güvenlik Açığı Bildirimi

Kimlik bilgisi sızıntısına, keyfi dosya yazımına, komut enjeksiyonuna, onay atlatmaya veya kontrolsüz CAD otomasyonuna yol açabilecek sorunları lütfen GitHub Security Advisory üzerinden özel olarak bildirin. Genel Issue'lara API Key, şirket çizimleri, görev kuyruğu veya tam günlük eklemeyin.

## Güven Sınırları

- CAD Studio AI API Key saklamaz; kimlik doğrulama Agent CLI veya CC Switch tarafından yönetilir.
- CAD, dizinler arası, ağ, silme ve Git push işlemleri tehlikeli yeteneklerdir ve mutlaka politika kapılarından geçmelidir.
- AI çıktısı, makine mühendisinin ölçü, malzeme, yük, güvenlik ve üretim incelemesinin yerini alamaz.
- Resmî açık kaynak derlemeleri şu anda ticari kod imzalama sunmuyor; indirdikten sonra GitHub Release SHA-256 değerini doğrulamalısınız.
