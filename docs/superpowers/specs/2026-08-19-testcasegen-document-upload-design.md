# TestCaseGen — Analiz Dökümanından Test Case Üretimi Tasarımı

**Tarih:** 2026-08-19
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

TestCaseGen şu an tek giriş yolu üzerinden çalışıyor: kullanıcı ekran görüntüleri yükler (Adım 1), Ollama vision modeliyle her ekrandan aday başlıklar çıkarılır (Adım 2), başlıklar kural motoruyla önceliklendirilir (Adım 3), son olarak seçilen başlıklar için ekran görüntüleri modele tekrar gönderilerek adım adım test case üretilir (Adım 4).

Bazı akışlar için ekran görüntüsü yerine (veya yanında) bir **analiz/gereksinim dökümanı** (BA'nın yazdığı Word/Excel doküman) mevcut oluyor. Bu tasarım, kullanıcının bu dökümanı yükleyip doğrudan ondan aday test case başlıkları ve adımları üretebilmesini; Adım 3 (önceliklendirme) ve export'un ise değişmeden aynı kalmasını sağlar.

**Kapsam dışı (bilinçli YAGNI kararları):**
- PDF desteği — kullanıcı sadece Word (.docx) ve Excel (.xlsx) istedi.
- Çok uzun dökümanlar için parça parça (map-reduce/chunking) işleme — metin 15.000 karakterle sınırlanır, aşımda kullanıcıya uyarı gösterilir. Gerçek ihtiyaç ortaya çıkarsa ayrı bir iterasyon.
- Ekran ve döküman girişini birbirine "karıştırıp" tek bir test case'in hem ekran hem döküman bağlamı kullanması — bir title ya `screens` ya da `document` kaynaklıdır, karışık kaynak yok.
- Aday başlıkların otomatik/onaysız listeye eklenmesi — mevcut ekran akışındaki gibi kullanıcı her adayı elle "+ Başlık Ekle" ile onaylar.

## Yeni Bağımlılık

`backend/requirements.txt`'e `python-docx` eklenir (Word metni okumak için). Excel için mevcut `openpyxl` kullanılır — yeni bağımlılık gerekmez.

## Veri Modeli Değişiklikleri

### Session'a yeni `document` alanı

```json
"document": {
  "filename": "analiz.docx",
  "ext": ".docx",
  "extracted_text": "...",
  "truncated": false,
  "candidate_titles": [{"text": "...", "excerpt": "..."}]
}
```

- Yoksa `null`. `create_session`'da varsayılan `null`.
- Bir session'da hem `screens` hem `document` aynı anda dolu olabilir — birbirini dışlamaz. Adım 1-2 UI'ı hangisi varsa onun için ilgili aksiyonu gösterir.
- `truncated: true` ise çıkarılan metin 15.000 karakterde kesilmiştir.

### `title` nesnesine yeni alanlar

```json
{
  "id": "uuid",
  "text": "...",
  "source": "screens" | "document",
  "screen_indices": [0, 1],
  "doc_excerpt": "..." | null,
  "score": ..., "level": ..., "level_source": ..., "rationale": "..."
}
```

- `source`: `screen_indices` doluysa `"screens"`, `doc_excerpt` doluysa `"document"`.
- Eski session'larda (`source` alanı olmayan) `load_session` yüklerken `source` yoksa `"screens"` varsayılır (geriye dönük uyumluluk, mevcut `screen_index` → `screen_indices` yükseltmesiyle aynı yerde yapılır).

## Backend Değişiklikleri

### `services/testcasegen_service.py` — yeni fonksiyonlar

- `extract_text_from_docx(file_bytes: bytes) -> str` — `python-docx` ile paragrafları ve tablo hücrelerini sırayla birleştirir.
- `extract_text_from_xlsx(file_bytes: bytes) -> str` — `openpyxl` ile her sayfayı `Sayfa: <ad>` başlığı altında, satırları `|` ile ayırarak metne çevirir.
- İkisi de sonucu 15.000 karakterde keser, kesilirse `(text, truncated: bool)` döner.
- `build_document_title_extraction_prompt(doc_text: str) -> str` — LLM'den dökümanı okuyup 5-15 aday test case başlığı + her biri için dökümandan alınmış kısa bir `excerpt` istemesini sağlar. Şema: `{"titles": [{"text": "...", "excerpt": "..."}]}`.
- `build_testcase_prompt_from_document(title_text: str, doc_excerpt: str) -> str` — mevcut `build_testcase_prompt`'taki 5 KESİN KURAL (pasif çatı, tek aksiyon/step, `@değişken` notasyonu, boş expected yasağı, context-echo yasağı) aynen korunur; "Ekran N" çerçevesi yerine döküman alıntısı çerçevesi kullanılır. Ekran görüntüsü olmadığından, modele dökümanda açıkça belirtilmeyen somut UI adları için makul bir varsayımda bulunabileceği ama bunun tahmini olduğunu unutmaması gerektiği belirtilir.

### `routers/testcasegen_router.py` — yeni endpoint'ler

- `POST /sessions/{id}/document/upload` — multipart dosya (`.docx`/`.xlsx`), uzantıya göre ilgili extract fonksiyonunu çağırır, `session["document"]` doldurur.
  - Desteklenmeyen uzantı → 400.
  - Parse hatası (bozuk dosya) → 400.
  - Çıkarılan metin boş/çok kısaysa (ör. taranmış görüntü içeren docx) → 400.
- `DELETE /sessions/{id}/document` — `session["document"] = null`.
- `POST /sessions/{id}/document/extract-titles` — `build_document_title_extraction_prompt` ile tek seferlik `ai_service.ollama_generate_text` çağrısı yapar (ekran akışındaki SSE'nin aksine döküman tek parça olduğundan streaming gerekmiyor), sonucu `session["document"]["candidate_titles"]`'a yazar ve döner. Ollama hatası → 503.

### `routers/testcasegen_router.py` — değişen endpoint'ler

- `POST /sessions/{id}/titles` (`TitleIn`): `screen_indices: list[int] = []` ve `doc_excerpt: Optional[str] = None` alanları eklenir; en az biri dolu olmalı (ikisi de boşsa 400). `source` otomatik hesaplanır.
- `POST /sessions/{id}/generate-testcases`: title'ın `source`'una göre dallanır:
  - `"screens"` → mevcut davranış aynen (ilgili ekran görüntüleri varsa `ollama_generate_vision`, yoksa `ollama_generate_text` — bu dallanma zaten mevcut, bir önceki oturumda eklendi).
  - `"document"` → `build_testcase_prompt_from_document(title.text, title.doc_excerpt)` + her zaman `ollama_generate_text` (görsel yok).

## Frontend Değişiklikleri (`WebArayuz/testcasegen.html`)

- **Adım 1 paneli:** Mevcut ekran dropzone'unun yanına ikinci bir yükleme alanı: "Analiz Dökümanı Yükle (.docx / .xlsx)". Yüklendikten sonra dosya adı + "Kaldır" butonu gösterilir. `truncated: true` ise küçük bir uyarı rozeti gösterilir ("Döküman çok uzun, ilk 15.000 karakter kullanıldı").
- **Adım 2 paneli:** `session.document` doluysa "Dökümandan Başlıkları Çıkar" butonu görünür (ekran varsa mevcut "Başlıkları Çıkar" butonuyla birlikte, ayrı kart olarak). Sonuç kartları ekran akışındaki "aday başlık + özet" kartlarıyla aynı görsel dilde: başlık metni + `excerpt` + "+ Başlık Ekle" butonu.
- **Adım 3-4 ve export:** Title kartlarında `source === "document"` ise ekran rozeti yerine "📄 Döküman" rozeti gösterilir (mevcut ekran-sayısı rozeti mantığının yanına eklenir, `testcasegen.html:879` civarı). Önceliklendirme (Adım 3) ve export akışı zaten jenerik olduğundan değişmez.

## Hata Yönetimi

| Durum | Davranış |
|---|---|
| Desteklenmeyen dosya uzantısı | 400 "Sadece .docx veya .xlsx desteklenir" |
| Bozuk/okunamayan dosya | 400 "Döküman okunamadı" |
| Çıkarılan metin boş/çok kısa | 400 "Dökümandan metin çıkarılamadı, dosya boş görünüyor" |
| `titles` endpoint'inde `screen_indices` ve `doc_excerpt` ikisi de boş | 400 "Ekran veya döküman alıntısı belirtilmeli" |
| LLM çağrısı başarısız (herhangi bir yeni endpoint) | 503 "Ollama servisine ulaşılamadı" (mevcut desenle tutarlı) |

## Test Kapsamı

- `test_testcasegen_document_extraction.py` — `extract_text_from_docx`/`extract_text_from_xlsx` gerçek küçük dosyalarla (mock'suz), 15.000 karakter kesme davranışı.
- `test_testcasegen_router_document.py` — upload/delete/extract-titles endpoint'leri (başarı + hata yolları), `add_title`'ın `doc_excerpt` ile çalışması, `generate-testcases`'ın döküman kaynaklı title için `ollama_generate_text` çağırdığını ve prompt'ta ekran çerçevesi ("Ekran N") kullanmadığını doğrulayan testler.
- Mevcut ekran-akışı testleri (116 test, bkz. önceki oturum) değişmeden geçmeli — `source` alanı eski davranışı bozmayacak şekilde geriye dönük uyumlu olmalı.
