# TestCaseGen — Çok Ekranlı Akış (Flow) Gruplama Tasarımı

**Tarih:** 2026-08-05
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

TestCaseGen şu an her ekran görüntüsünü **bağımsız** bir birim olarak ele alıyor: Adım 2 her ekran için ayrı `candidate_titles` üretiyor, her `title` tek bir `screen_index`'e bağlı, Adım 4'te üretilen her test case tek bir `title`'a (dolayısıyla tek bir ekrana) bağlı. Gerçekte bir test case genelde **çok adımlı bir navigasyon akışı**dır (örn. Login > Diğer İşlemler > Hesaplama Araçları > Kar Payı Hesapla — 4 ekran, TEK test case, adımları 4 ekranın tamamına yayılmalı). Şu anki mimari bunu üretemez; her ekran ayrı bir test case doğurur.

Bu doküman, kullanıcının birden fazla sıralı ekranı **manuel olarak** tek bir "akış" altında gruplayıp, bu akıştan **tek, çok adımlı bir test case** üretebilmesini sağlayan tasarımı tanımlar.

**Kapsam dışı (bu iterasyon için bilinçli YAGNI kararları):**
- AI'ın ekranları otomatik olarak akışlara gruplaması (kullanıcı onayı olmadan) — kapsam dışı.
- Çoklu görsel (multi-image) Ollama vision çağrısı — Adım 2'nin görsel çıkarımı **ekran başına** çalışmaya devam ediyor, sadece görüntüleme/gruplama katmanı değişiyor.
- Bir akıştan tek tek ekran çıkarma / akış yeniden adlandırma UI'ı — akış oluşturma tekrar çalıştırılarak üzerine yazılabilir; bir ekranı akıştan çıkarmak için o ekranın akış rozetindeki "x" ikonuna tıklanır (bkz. aşağıda).
- Veritabanı değişikliği yok — state yine dosya tabanlı JSON.

## Veri Modeli Değişiklikleri

### `screen` nesnesi — iki yeni opsiyonel alan

```json
{
  "index": 0,
  "image_ext": ".png",
  "user_note": "",
  "candidate_titles": [],
  "screen_summary": "",
  "parse_error": false,
  "flow_id": "a1b2c3",
  "flow_name": "Kar Payı Hesaplama"
}
```

- `flow_id` (str | null): akışı paylaşan ekranların ortak kimliği. `null` ise ekran hiçbir akışa dahil değildir ve **kendi başına tek-ekranlı bir akış** gibi davranır (bugünkü davranışla birebir aynı — geriye dönük uyumluluk).
- `flow_name` (str | null): kullanıcının akışa verdiği isim. Yalnızca `flow_id` dolu olan ekranlarda anlamlıdır; aynı `flow_id`'yi paylaşan tüm ekranlarda aynı `flow_name` tutulur.
- İki alan da `create_session`/`add_screen`'de varsayılan `null` ile başlar.

### `title` nesnesi — `screen_index` → `screen_indices`

```json
{
  "id": "uuid",
  "screen_indices": [0, 1, 2, 3],
  "text": "Kar Payı Hesaplama",
  "level": "high",
  "level_source": "rule",
  "rationale": "...",
  "score": 4.2
}
```

- `screen_index: int` alanı **kaldırılıyor**, yerine `screen_indices: list[int]` (sıralı, akıştaki ekranların index'leri) geliyor.
- Tek ekranlı (akışsız) bir title için bu basitçe `[i]` — tek elemanlı liste.

### Geriye dönük uyumluluk — eski `session.json` dosyaları

Bu değişiklikten önce oluşturulmuş oturumlarda `title.screen_index` (tekil int) olabilir. `load_session` içinde, session yüklenirken her title için basit bir yukarı-dönüştürme uygulanır:

```python
for title in session.get("titles", []):
    if "screen_indices" not in title and "screen_index" in title:
        title["screen_indices"] = [title.pop("screen_index")]
```

Bu, `load_session`'ın hemen JSON'ı `json.load` ile okuduğu yerin ardından eklenir. Yeni alan formatındaki (zaten `screen_indices` içeren) oturumlar dokunulmadan geçer.

## Adım 1 — Ekran Toplama: Akış Oluşturma

- Ekran thumbnail'larına bir checkbox eklenir (`renderScreenList`'in ürettiği her `.tcg-screen-thumb` kartına).
- Birden fazla checkbox seçilip yeni bir **"Akış Oluştur"** butonuna tıklandığında: `prompt()` (veya küçük bir input) ile akış adı sorulur; boş bırakılırsa `Akış ${flow_id.slice(0,4)}` gibi varsayılan bir isim kullanılır.
- Frontend, `crypto.randomUUID()` ile bir `flow_id` üretir, seçili her ekran için **sırayla** `PUT /sessions/{id}/screens/{idx}` çağrısı yapar — bu endpoint'in mevcut `NoteIn` şeması `note: str` alanına ek olarak **opsiyonel** `flow_id: str | None` ve `flow_name: str | None` alanları kazanır. `edit_screen_note` servis fonksiyonu bu iki alanı da (verilmişse) `screen` sözlüğüne yazar; `note` alanı verilmemişse mevcut notu değiştirmez (fonksiyon imzasına `flow_id: Optional[str] = None, flow_name: Optional[str] = None` eklenir, `None` geçilirse ilgili alan dokunulmaz).
- Gruplanan thumbnail'lar görsel olarak işaretlenir: aynı `flow_id`'yi paylaşan kartların üstünde ortak renkli bir "parantez" çubuğu + `flow_name` etiketi + küçük bir "x" (o tek ekranı akıştan çıkarır — `flow_id`/`flow_name`'i `null`'a çeken aynı `PUT` endpoint'i çağrılır).
- Yeniden sıralama (drag-to-reorder) davranışı değişmez; akış üyeliği ekranın `index`'ine değil `flow_id`'sine bağlı olduğu için sıralama akışları bozmaz (akış içindeki göreli sıra, ekranların genel sıralamasındaki göreli sırayla otomatik tutarlıdır).

## Adım 2 — Başlık Çıkarma: Akışa Göre Gruplu Görüntüleme

- **Backend/AI tarafında değişiklik yok** — `extract-titles` SSE endpoint'i ekran başına çalışmaya devam eder, her ekran kendi `screen_summary`/`candidate_titles`'ını AI'dan alır.
- **Frontend render değişikliği:** `renderTitlesResult()`, ekranları `flow_id`'ye göre gruplar (aynı `flow_id`'yi paylaşanlar tek kart; `flow_id: null` olan her ekran kendi tek-elemanlı grubu). Bir akış kartı:
  - Akışın adını başlık olarak gösterir (`flow_name`, yoksa "Tekil Ekran").
  - Üye ekranların her birini sırayla küçük bir alt-satır olarak listeler (`Ekran #i: <screen_summary>`).
  - **Birleşik aday başlık listesi**: yeni bir client-only state `_flowCandidates[flow_id] = [...]` — ilk render'da, akışın üye ekranlarının `candidate_titles` listelerinin birleşimi (tekrarlar elenmiş) ile doldurulur; tekil ekranlar için doğrudan o ekranın `candidate_titles`'ı kullanılır (yeni state gerekmez, mevcut `editCandidateTitle` vb. fonksiyonlar tekil ekranlarda değişmeden çalışır). Akış kartındaki ekle/düzenle/sil işlemleri `_flowCandidates[flow_id]` üzerinde çalışan yeni `editFlowCandidateTitle`/`addFlowCandidateTitle`/`removeFlowCandidateTitle` fonksiyonlarıyla yapılır.
  - `parse_error` durumu: bir akıştaki HERHANGİ bir ekran `parse_error: true` ise, o ekranın ham-yanıt uyarı kartı akış kartının İÇİNDE, ayrı bir alt-blok olarak gösterilir (akışın geri kalanı normal render edilir).

## Adım 3 — Önceliklendirme

- **Servis katmanında değişiklik yok**: `score_title(text, screen_note, screen_index)` imzası aynen kalır.
- **Router değişikliği** (`prioritize` endpoint'i): her title için, `title["screen_indices"]`'teki tüm ekranların `user_note`'larını birleştirip (`" ".join(...)`) `screen_note` olarak, listenin **son elemanını** (`screen_indices[-1]`) `screen_index` olarak `score_title`'a geçer. Rasyonel: akışın en derin/son ekranı, mevcut "derinlik cezası" tasarımının temsil ettiği "ana akıştan uzaklık" kavramına en uygun referans noktasıdır.
- **Frontend**: `promoteCandidateTitles()` artık ekran değil **akış** bazında çalışır — `_session.screens`'i `flow_id`'ye göre gruplar (yukarıdaki gibi), her akış için `_flowCandidates[flow_id]` (veya tekil ekran için `screen.candidate_titles`) içindeki her metni `POST /titles` ile `{screen_indices: [...], text}` gövdesiyle gönderir. Zaten-var-mı kontrolü için dedup anahtarı `${screen_indices.join(',')}:${text}` olur (eskiden `${screen_index}:${text}`).
- Kanban kartları (`renderKanban`), `title.screen_indices.length > 1` olduğunda kartın üstüne küçük bir `N ekran` rozeti ekler (`.badge`).

## Adım 4 — Test Case Üretimi

Tek gerçek prompt-mühendisliği değişikliği burada:

- `build_testcase_prompt(title_text: str, screen_summary: str, screen_note: str) -> str` → `build_testcase_prompt(title_text: str, screens: list[dict]) -> str`. `screens` parametresi `[{"index": int, "summary": str, "note": str}, ...]` şeklinde, akıştaki ekranların **sıralı** listesi.
- Yeni prompt, ekranları numaralı bir liste olarak sunar (`Ekran 1 (özet: ..., not: ...) -> Ekran 2 (...) -> ... -> Ekran N (...)`) ve modelden **tüm akışı baştan sona kat eden tek bir test senaryosu** ister — mevcut 4 kesin kural (pasif fiil, tek aksiyon, @Param notasyonu, boş olmayan Step Expected) aynen korunur, JSON şeması (`{"steps": [...]}`) değişmez.
- Router (`generate_testcases` endpoint'i): `screens_by_index.get(title["screen_index"], {})` yerine `[screens_by_index[i] for i in title["screen_indices"] if i in screens_by_index]` ile sıralı ekran listesi oluşturup yeni `build_testcase_prompt`'a geçer.
- **Aşağı akışta (downstream) hiçbir değişiklik yok**: `validate_steps`, `testcases[].steps[]` şeması, tablo render'ı, ihlal vurgulama, xlsx export — hepsi zaten adım sayısından bağımsız çalışıyor (bir test case'in kaç adımı olduğu hiçbir yerde varsayılmıyor).

## Test / Doğrulama

- Backend: `score_title`/`validate_steps`/`build_export_workbook` testleri değişmeden geçmeli (imzaları değişmiyor). `build_testcase_prompt`, `add_title`, `prioritize`, `generate_testcases` için yeni/güncellenmiş testler gerekir (yeni imza, `screen_indices` alanı, eski-format `screen_index`'in `load_session`'da yukarı-dönüştürüldüğünü doğrulayan bir test).
- Frontend: yine test runner yok; doğrulama `node --check` + gerçek backend'e karşı HTTP çağrıları (bir akış oluştur → başlık çıkar → önceliklendir → çok adımlı test case üret → export) + manuel tarayıcı kontrolü.

## Riskler / Notlar

- `edit_screen_note` servis fonksiyonunun imzası genişliyor (`flow_id`, `flow_name` opsiyonel parametreleri) — çağıran router endpoint'inin (`edit_screen_note`) request body modeli (`NoteIn`) de aynı şekilde genişletilmeli; `note` alanı hâlâ zorunlu mu opsiyonel mi olacağına uygulama planında netlik getirilmeli (öneri: üçü de opsiyonel yapılıp en az birinin dolu olması router'da kontrol edilir, tamamen boş istek 400 döner).
- Bir akıştaki ekranlar silinirse (`delete_screen`) ve akışta tek ekran kalırsa, o ekranın `flow_id`/`flow_name`'i otomatik temizlenmez (basitleştirme) — kullanıcı isterse "x" ile manuel temizler. Bu bilinçli bir kapsam kısıtlamasıdır, ekranı olası bir "tek elemanlı ama flow_id'si dolu" garip ara duruma sokabilir; Adım 2/3 render'ı bunu zaten doğru ele alır (tek elemanlı grup normal şekilde gösterilir), tek etki `flow_name`'in gereksiz yere görünmesidir — kozmetik.
- `_flowCandidates` client-only state, sayfa yenilendiğinde (F5) kaybolur ve akışın üye ekranlarının `candidate_titles`'larından yeniden hesaplanır — kullanıcının Adım 2'de yaptığı manuel düzenlemeler (chip ekleme/silme/değiştirme) sayfa yenilenirse kaybolabilir. Bu, mevcut tekil-ekran davranışıyla (candidate_titles zaten sunucuya persist edilmiyor, aynı risk) tutarlıdır — yeni bir risk değil, sadece akış seviyesine taşınıyor.
