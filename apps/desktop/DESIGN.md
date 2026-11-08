# Design System: CAD Otomasyonu Teslimat Çalışma Tezgâhı

## 1. Visual Theme & Atmosphere

Karakter konumlandırması "sessiz mühendislik kontrol odası": yoğunluk 7/10, çeşitlilik 4/10, hareket 2/10.

Arayüz, makine mühendislerine güvenilir, anlaşılır ve tekrar tekrar kullanılabilir hissettirmelidir. Görsel odak gösteriş değil; proje durumunu, parametre bütünlüğünü, P0 incelemesini ve teslimat çıktısını net bir yere koymaktır. Bütün olarak hassas bir alet paneli gibi: sakin, ölçülü, düzenli.

## 2. Color Palette & Roles

- **Drafting Canvas** (#EDEEEA) - Ana arka plan; mühendislik çizim kâğıdına yakın ama sararmadan.
- **Instrument Surface** (#FAFAF7) - Formlar, inceleme alanı ve ana içerik panelleri.
- **Charcoal Console** (#141B1F) - Sol navigasyon ve alt durum çubuğu; saf siyah kullanılamaz.
- **Ink Primary** (#182024) - Başlıklar, etiketler ve ana içerik.
- **Steel Text** (#56636B) - Yardımcı açıklamalar, yollar, durum açıklamaları.
- **Hairline Border** (#D8DDD7) - 1px yapı çizgileri, giriş alanı sınırları.
- **Copper Accent** (#B87333) - Tek vurgu rengi; ana düğmeler, seçili durum, kritik kapı durumları için.

Mor-mavi neon, saf siyah, parlayan gölgeler ve yüksek doygunluklu geçişler yasaktır.

## 3. Typography Rules

- **Display:** Microsoft YaHei UI Semibold - Mühendislik yazılımları için öncelikli; yazı boyutu ölçülü, hiyerarşi yazı kalınlığıyla kurulur.
- **Body:** Microsoft YaHei UI - Satır yüksekliği rahat; form metni 13px'ten küçük olmamalı.
- **Mono:** Cascadia Mono / Consolas - Günlükler, dosya yolları, sayısal listeler.
- **Banned:** Serif yazı tipi kullanılmaz, geniş negatif harf aralığı kullanılmaz, pazarlama tarzı dev başlıklar kullanılmaz.

## 4. Component Stylings

- **Buttons:** Düz, sınırları belirgin; ana düğme Copper Accent kullanır. Basılı durumda daha koyu bakır tonu kullanılır, dış parlama yapılmaz.
- **Panels:** Yalnızca gerçek işlev alanları için. Yarıçap 10px altında, kenarlıklar net; kart içinde kart olmaz.
- **Inputs:** Etiketler sola hizalı, giriş alanı yüksekliği sabit; odak durumunda yalnızca kenarlık rengi değişir.
- **Tables:** Tablo başlığı açık gri zemin; sayı sütunları net, kompakt mühendislik yoğunluğu korunur.
- **Status:** P0/P1 sonuçları metin ve renkle ifade edilir; dekoratif simge yığını kullanılmaz.
- **Empty States:** Kullanıcıya bir sonraki adımı açıkça söyler; örneğin "Parametreleri kaydettikten sonra proje dizini oluşturulur".

## 5. Layout Principles

- Solda navigasyon ve ürün kimliği, ortada çalışma parametreleri, sağda inceleme ve çıktı.
- Üstte komut çubuğu korunur; ana eylemler her zaman sağ üsttedir.
- Özet çubuğu geçerli akışın dört temel gerçeğini gösterir: yerel çalışma, GB/T tarzı, P0 kapısı, Mock durumu.
- Üçe bölünmüş pazarlama kartları kullanılmaz, görsel gürültü süslemeleri yapılmaz.
- Tüm metinler eksiksiz görüntülenmelidir; düğme genişliği metni sıkıştıramaz.

## 6. Motion & Interaction

Masaüstünde şu an karmaşık animasyon yapılmıyor. Etkileşim geri bildirimi hover, pressed, focus ve durum metni değişimlerine dayanır. İleride uzun süreli CAD yürütmesi bağlanırsa aşamalı ilerleme çubuğu ve günlük akışı kullanılır; dönen yükleme halkası kullanılmaz.

## 7. Anti-Patterns

- Saf siyah kullanılmaz.
- Mor/mavi neon geçişler kullanılmaz.
- Dekoratif parlama kullanılmaz.
- Pazarlama söylemi kullanılmaz.
- Emoji kullanılmaz.
- Metin düğmeler tarafından sıkıştırılmaz.
- Form, geniş boşluklu bir demoya dönüştürülmez.
- İnceleme sonuçları JSON içinde gizlenmez; arayüz kritik sorunları doğrudan göstermelidir.
