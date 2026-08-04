# TestCaseGen Modülü — Tasarım

**Tarih:** 2026-08-04
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

OtomasyoTool platformuna, mobil uygulama ekran görüntülerinden test case başlıkları çıkarıp, önceliklendirip, seçilen başlıklar için Azure DevOps (ADO) formatında detaylı test case üreten yeni bir sayfa/modül eklenecek: **TestCaseGen**.

Bu görev kapsamı **yalnızca sayfa (UI + iş mantığı + LLM entegrasyonu)** ile sınırlı. Veritabanı bağlantısı/şeması kapsam dışı — state dosya tabanlı (JSON + görsel dosyaları) tutulur, kalıcı DB entegrasyonu ayrı bir iş olarak ele alınacak.

## Mevcut Altyapı (keşif sonucu)

- **Canlı ekran / ADB kontrolü:** `backend/routers/emulator.py` + `backend/services/emulator_service.py` + `backend/WebArayuz/emulator.html`. `GET /api/emulator/devices`, `POST /api/emulator/{device_id}/connect`, `WS /api/emulator/{device_id}/stream` (screencap tabanlı periyodik "canlı" akış + tap/swipe/text ile kontrol). Gerçek scrcpy (video mirroring) **kullanılmıyor** — bu akış "scrcpy benzeri" görsel deneyim sağlıyor, TestCaseGen bunu aynen embed edecek.
- **Ollama entegrasyonu:** `backend/services/ai_service.py::get_ollama_config()` (`ai_config.json` > env, varsayılan `gemma3:4b`, `http://localhost:11434/api/generate`). Şu an gerçek Ollama HTTP çağrısı `ai_test_generator_router.py` içinde 3 ayrı yerde `httpx`/`requests` ile tekrarlanıyor (`model`, `prompt`, `images`, `stream:false`). Bu tekrar TestCaseGen için `ai_service.py`'a taşınacak, mevcut 3 çağrı yerine dokunulmayacak (kapsam dışı refactor yapılmıyor).
- **SSE progress deseni:** `ai_test_generator_router.py::/execute` — uzun süren işlemler için `event:` tabanlı stream. TestCaseGen'in Adım 2 (başlık çıkarma) aynı deseni kullanacak.
- **Sidebar:** `backend/WebArayuz/js/sidebar.js` — "AI Araçlar" bölümüne yeni `item("testcasegen", ..., "Test Case Gen")` eklenecek.
- **Router mount deseni:** `main.py` içinde `app.include_router(...)` ile; `emulator_router` kendi prefix'ini (`/api/emulator`) kendi tanımlıyor, aynı desen TestCaseGen router'ında (`/api/testcasegen`) izlenecek.
- **Auth:** Diğer router'ların çoğu `Depends(get_current_user)` kullanıyor (emulator.py istisna — auth yok); TestCaseGen router'ı **auth zorunlu** olacak, çünkü state kullanıcı bazlı izole ediliyor.

## Mimari

```
backend/routers/testcasegen_router.py   → /api/testcasegen, REST + SSE (extract-titles)
backend/services/testcasegen_service.py → state CRUD, scoring motoru, validator, xlsx export
backend/services/ai_service.py          → + ollama_generate_text(), ollama_generate_vision() (yeni, paylaşılan)
backend/WebArayuz/testcasegen.html      → tek dosya SPA, 4 adımlı wizard, ai-generator.html ile aynı stil
backend/WebArayuz/js/sidebar.js         → "AI Araçlar" bölümüne link eklenir
backend/main.py                         → include_router(testcasegen_router)
```

### Veri Modeli & Depolama

DB yok. Her oturum bir klasör:

```
backend/testcasegen_data/{user_id}/{session_id}/
  session.json
  screenshots/{screen_index}.png
```

`session.json` şeması:

```json
{
  "id": "uuid",
  "user_id": 1,
  "created_at": "iso8601",
  "updated_at": "iso8601",
  "current_step": 1,
  "screens": [
    {
      "index": 0,
      "image_path": "screenshots/0.png",
      "user_note": "Diğer İşlemler sayfası",
      "candidate_titles": ["...", "..."],
      "screen_summary": "...",
      "parse_error": false
    }
  ],
  "titles": [
    {
      "id": "uuid",
      "screen_index": 0,
      "text": "Diğer işlemler menüsü açılır",
      "score": 4.5,
      "level": "high",
      "level_source": "rule",
      "rationale": "Bu ekran işlem akışına doğrudan giriş sağladığı için..."
    }
  ],
  "testcases": [
    {
      "id": "uuid",
      "title_id": "uuid",
      "steps": [
        {
          "step_action": "\"Devam\" butonuna tıklanır",
          "step_expected": "Onay ekranı açılır",
          "violations": []
        }
      ]
    }
  ]
}
```

Kullanıcı sayfadan ayrılıp geri dönerse `GET /api/testcasegen/sessions` ile eski oturumlarını listeleyip devam edebilir veya silebilir.

## Adım Akışı

### Adım 1 — Ekran Görüntüsü Toplama

İki girdi yöntemi, kullanıcı ikisini birlikte de kullanabilir (aynı sıralı listeye eklenir):

1. **Manuel upload:** Sürükle-bırak / dosya seçici, çoklu dosya. Drag-to-reorder liste ile sıra elle düzenlenebilir.
2. **ADB canlı ekran ile yakalama:** `emulator.html`'deki cihaz listesi + `WS /api/emulator/{device_id}/stream` canlı görünümü + tap/swipe/text kontrolleri bu sayfaya gömülür. Kullanıcı cihazda gezinirken "Yakala" butonuna basar; buton, WS üzerinden client'ta zaten mevcut olan **son frame'i** (base64) alıp backend'e POST eder — ADB'ye ayrıca gidilmez, mevcut akış tekrar kullanılır.

Her iki yöntemin çıktısı aynı veri yapısı: `screens[]` listesi, her biri `image_path` + opsiyonel `user_note`.

**Endpoint'ler:**
- `POST /api/testcasegen/sessions` — yeni oturum
- `GET /api/testcasegen/sessions` / `GET /{id}` / `DELETE /{id}`
- `POST /sessions/{id}/screens/upload` (multipart, çoklu dosya, sırayla eklenir)
- `POST /sessions/{id}/screens/capture` (body: `{image_b64, note?}`)
- `PUT /sessions/{id}/screens/reorder` (body: yeni index sırası)
- `PUT /sessions/{id}/screens/{idx}` (not düzenleme)
- `DELETE /sessions/{id}/screens/{idx}`

### Adım 2 — Başlık Çıkarma (LLM ile)

- `POST /sessions/{id}/extract-titles` — SSE stream döner (`ai_test_generator`'daki `/execute` deseniyle aynı yaklaşım).
- Her ekran sırayla işlenir; her istekte **bir önceki ekranın** `user_note` + `screen_summary`'si de prompt'a eklenir (akış bütünlüğü).
- Model çağrısı: `ai_service.ollama_generate_vision(prompt, [image_b64])`. Prompt, çıktının **yalnızca JSON** olmasını zorlar:
  ```json
  {"screen_titles": [{"screen_index": 0, "candidate_titles": ["...", "..."], "screen_summary": "..."}]}
  ```
- Parse: markdown fence / JSON dışı metin temizlenir (`{`...`}` sınırları bulunur). Parse başarısız olursa o ekran `parse_error:true` + ham metin `screen_summary` alanına yazılır; frontend bunu **düzenlenebilir textarea** olarak gösterir (sessizce yutulmaz).
- SSE olayları: `event: screen_done` (`{screen_index, candidate_titles, screen_summary, parse_error}`), sonda `event: complete`.
- Sonuç ekranda düzenlenebilir liste: kullanıcı başlık silebilir/düzenleyebilir/elle yenisini ekleyebilir (`PUT`/`POST`/`DELETE` ile `titles[]` üzerinde CRUD — bu adımda henüz skor/level yok, sonraki adımda hesaplanır).

### Adım 3 — Önceliklendirme (High / Medium / Low)

**LLM karar verici değil — sadece gerekçe metni üretir.** Önceliklendirme kural tabanlı bir scoring fonksiyonuyla yapılır.

`testcasegen_service.py` içinde modül seviyesinde yapılandırılabilir sabitler:

```python
WEIGHTS = {
    "transaction": 3.0,       # form/tutar girişi/onay butonu içeren ekran
    "info_only": -1.0,        # salt bilgi gösterimi
    "negative_potential": 1.5,# validasyon gerektiren input alanı → hata senaryosu riski
    "depth_penalty": 0.3,     # ana akıştan her adım uzaklaştıkça düşen ağırlık
}
THRESHOLD_HIGH = 3.0
THRESHOLD_MEDIUM = 1.0
```

Türkçe anahtar kelime listeleri (`screen_summary` + `user_note` metninde aranır):
- `TRANSACTION_KEYWORDS` = onayla, öde, gönder, kaydet, tutar, miktar, transfer, ...
- `INFO_KEYWORDS` = hakkımızda, bilgi, sss, liste görüntüle, ...
- `NEGATIVE_KEYWORDS` = doğrulama, zorunlu alan, hatalı, geçersiz, input, gir, ...

Skor = ağırlıklı anahtar kelime eşleşmeleri − `depth_penalty × screen_index`. Eşiklere göre `level` atanır.

- `POST /sessions/{id}/prioritize` — tüm `titles[]` için skor+level hesaplar, sonra her başlık için ayrı bir Ollama metin çağrısı ile ("bu skoru şu kriterlere göre 1-2 cümlelik gerekçeye çevir") `rationale` doldurur. `level_source: "rule"`.
- UI: üç sütun (High/Medium/Low), kanban tarzı. Kullanıcı sürükleyerek `level`'ı manuel değiştirebilir → `PUT /sessions/{id}/titles/{title_id}/priority` (`level_source: "manual"` olarak işaretlenir, bir daha otomatik hesaplama onu ezmez).

### Adım 4 — Test Case Üretimi

- Kullanıcı önceliklendirilmiş listeden checkbox ile başlık seçer, "Test Case Oluştur" der.
- `POST /sessions/{id}/generate-testcases` (body: seçilen `title_id[]`). Her başlık için ilgili ekran görüntüsü + başlık + akış sırası verilerek Ollama'dan JSON adım listesi istenir. Prompt **kesin kurallara** zorlar:
  1. Pasif fiil çatısı zorunlu ("tıklanır", "açılır" — emir kipi yasak)
  2. Step Action'da tek aksiyon
  3. Dinamik değerler `@ParamAdı` notasyonu (`@güncel_kur`, `@hesaplanan_tutar`)
  4. Her step'te boş olmayan Step Expected

- **Validator** (`testcasegen_service.validate_steps(steps) -> list[dict]`), LLM çıktısını körü körüne kabul etmez:
  - **Emir kipi tespiti:** bilinen emir kipi fiil listesi (`tıkla`, `aç`, `yaz`, `gir`, `seç`, `onayla`, `bas`, ...) `step_action` sonunda geçiyorsa işaretlenir.
  - **`@` notasyonu eksik değişken:** değişken-görünümlü anahtar kelimeler (`kur`, `tutar`, `hesaplanan`, `bakiye`, ...) metinde `@` öneki olmadan geçiyorsa işaretlenir.
  - **Çoklu aksiyon:** `" ve "` bağlacı + iki ayrı fiil kalıbı tespit edilirse işaretlenir.
  - **Boş Step Expected:** doğrudan kontrol.
  - Her ihlal `{rule, message}` olarak `violations[]`'a yazılır; frontend o satırı kırmızı + tooltip ile gösterir, kullanıcı manuel düzeltir.
- `PUT /sessions/{id}/testcases/{tc_id}/steps/{i}` — satır düzenlenince validator yeniden çalışır (tekrar kaydedilir).
- Sonuç, düzenlenebilir tablo: `ID, Work Item Type, Title, Test Step, Step Action, Step Expected, Area Path, Assigned To, State`.

## Export

`POST /sessions/{id}/export` (body: onaylanan `testcase_id[]`) → `openpyxl` ile `.xlsx` stream:
- Her test case: 1 başlık satırı (`ID` boş — ADO import'ta otomatik atanır, `Work Item Type`="Test Case", `Title` dolu, step alanları boş) + altında sıralı step satırları (`Test Step`=sıra no, `Step Action`/`Step Expected` dolu, `ID`/`Work Item Type`/`Title` boş).
- `Area Path`, `Assigned To`, `State` kolonları boş bırakılır (kullanıcı export sonrası Excel'de doldurur) — bu görevde varsayılan değer atanmıyor.
- Font Arial, header satırı bold, kolon genişlikleri okunabilir (auto-fit yaklaşık genişlik).

## UI/UX

- `testcasegen.html`, `ai-generator.html` ile aynı CSS değişkenleri/renk paleti/komponent stiliyle.
- 4 adımlı stepper/wizard komponenti — geri dönüp önceki adımı düzenleyebilir (adım geçişleri client-side, state backend'de zaten kalıcı olduğu için veri kaybı olmaz).
- Ollama çağrıları sırasında loading state (Adım 2 SSE progress bar, Adım 3/4 spinner).
- Ollama servisi kapalıyken net hata mesajı + "Tekrar Dene" butonu (Adım 2/3/4'ün her birinde).

## Hata Yönetimi

- Her Ollama çağrısı `try/except` ile sarılır (`httpx.ConnectError` / timeout) → `HTTPException(503, "Ollama servisine ulaşılamadı, ...")`. Frontend toast + retry butonu gösterir.
- JSON parse hataları sessizce yutulmaz — Adım 2'de yukarıda açıklandığı gibi ham metin editöre düşer.
- Screenshot capture sırasında cihaz bağlantısı koparsa (`emulator_service` WS hata verirse) frontend bağlantı durumunu gösterir, "Yakala" butonu devre dışı kalır.

## Test Planı

- `testcasegen_service.py` içindeki saf fonksiyonlar (scoring, validator, JSON temizleme/parse) için birim testleri (`pytest`) — LLM çağrısı gerektirmeyen kısımlar mock'suz test edilebilir.
- Ollama çağrıları mock'lanarak (`ollama_generate_vision`/`ollama_generate_text` patch) router endpoint'lerinin uçtan uca akışı test edilir.
- Manuel test: emülatör/gerçek cihazla Adım 1 canlı yakalama akışı, Ollama kapalıyken hata mesajı akışı, export edilen `.xlsx`'in ADO import formatına uyumu.

## Kapsam Dışı

- Veritabanı bağlantısı/şeması/migration
- Kullanıcı auth/yetkilendirme (mevcut JWT auth'u kullanır, yeni bir şey eklenmez)
- ADO API'sine doğrudan otomatik push (yalnızca dosya export)
- Gerçek scrcpy (video mirroring) entegrasyonu
