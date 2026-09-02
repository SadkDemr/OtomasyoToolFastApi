# Bilgi Tabanı: Dosya Yükleme + Versiyon/Fark Raporu — Tasarım

- **Tarih:** 2026-09-02
- **Durum:** Onaylandı (brainstorming), implementasyon planı bekleniyor
- **Kapsam:** `backend/WebArayuz/admin-knowledge.html`, `backend/routers/testcasegen_router.py`,
  `backend/services/knowledge_service.py`, `backend/services/ai_service.py`,
  `backend/services/testcasegen_service.py`, `backend/models/db_models.py`

## 1. Amaç

Admin şu an Bilgi Tabanı sayfasında (Kurallar / Örnek Senaryolar) sadece elle metin
yazarak kayıt ekleyebiliyor. İstenen geliştirme iki parça:

1. Bu sayfaya **dosya yükleme** eklensin (.docx/.xlsx/.txt/.md) — dosyanın içeriği
   otomatik olarak metin alanına dolsun, admin elle yazmak zorunda kalmasın.
2. Admin **aynı başlıkta** yeni bir dosya/metin yüklediğinde (örn. haftalık güncelleme),
   sistem eski içerikle yeniyi karşılaştırıp **"şunlar değişti"** şeklinde doğal dilde
   bir özet çıkarsın. Bu özet hem kayıt anında gösterilsin hem de kalıcı bir
   **Değişiklik Geçmişi** sayfasında saklansın.

## 2. Kapsam Dışı (Non-goals)

- Otomatik/zamanlanmış (cron) dosya izleme yok — tetikleyici her zaman admin'in
  elle "kaydet" demesi. "Haftalık" ritim admin'in kendi alışkanlığı, sistemin
  otomasyonu değil.
- Eski versiyonu arama havuzunda (RAG) tutmuyoruz — güncelleme sonrası arama
  SADECE en güncel içeriği görür (bkz. §4.3).
- Dosya-bazlı (binary) saklama yok — sadece çıkarılan düz metin saklanır, orijinal
  .docx/.xlsx dosyası diskte tutulmaz (mevcut TestCaseGen doküman yükleme akışıyla
  tutarlı: `backend/routers/testcasegen_router.py:174-213`).
- Diff/versiyon geçmişi sınırsız büyüyebilir; bu spec'te bir temizleme/arşivleme
  politikası tanımlanmıyor (ileride ihtiyaç olursa ayrı bir iş).

## 3. Veri Modeli

Yeni tablo — mevcut `KnowledgeEntry` (`backend/models/db_models.py:399`) modeline
dokunulmaz, sadece yanına eklenir:

```python
class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String, index=True)   # "rule" | "example"
    title = Column(String, index=True)
    full_content = Column(Text)               # chunklanmamış tam metin
    is_current = Column(Boolean, default=True, index=True)
    diff_summary = Column(Text, nullable=True)  # None ise "ilk kayıt"
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Neden ayrı tablo, `KnowledgeEntry` değil:** `KnowledgeEntry` satırları zaten
chunk'lanmış parçalar (`knowledge_service._chunk_text`, `CHUNK_CHAR_LIMIT=1000`) —
chunk sırası/birleştirme garantisi yok, tam orijinal metni geri kurmak güvenilir
değil. Diff için tam, bozulmamış metne ihtiyaç var; bu yüzden versiyon tablosu
tam metni saklar, arama tablosu (`KnowledgeEntry`) chunk+embedding'i saklamaya
devam eder. İkisi `(entry_type, title)` ile eşleşir.

`(entry_type, title)` çifti üzerinde uygulama katmanında "en fazla bir
`is_current=True` satır" invariantı korunur (DB constraint yerine kod ile —
mevcut kod tabanında benzer invariantlar da genelde uygulama katmanında
tutuluyor, ör. `DeviceSession`).

## 4. Backend Akışı

### 4.1 Dosyadan metin çıkarma (yeni, küçük endpoint)

```
POST /api/testcasegen/knowledge/extract-file   (admin, multipart file)
→ { "text": "...", "suggested_title": "..." }
```

- `.docx`/`.xlsx`: `testcasegen_service.extract_text_from_docx` /
  `extract_text_from_xlsx` yeniden kullanılır (zaten TestCaseGen doküman
  yüklemede var — `backend/services/testcasegen_service.py`).
- `.txt`/`.md`: doğrudan UTF-8 decode.
- `suggested_title`: dosya adından uzantısız, alt çizgi/tire boşluğa çevrilmiş
  öneri (örn. `sifre-kurali-v2.docx` → `"sifre kurali v2"`) — admin bunu
  serbestçe değiştirebilir, otomatik kayıt tetiklemez.
- Bu endpoint SADECE metin çıkarır, kaydetmez. Kayıt hâlâ mevcut
  `POST /knowledge/rules` / `POST /knowledge/examples` ile, dosyadan gelen metin
  admin tarafından (gerekirse düzenlenip) gönderilir. Böylece elle yazma ile
  dosya yükleme aynı kayıt yolunu kullanır, iki ayrı kod yolu oluşmaz.

### 4.2 Kayıt/güncelleme — `knowledge_service.save_versioned_entry()`

Mevcut `POST /knowledge/rules` ve `POST /knowledge/examples` endpoint'leri
(`backend/routers/testcasegen_router.py:667-676`, `:724-735`), bugün doğrudan
`knowledge_service.add_entry()` / `add_example()` çağırıyor. Bunun yerine yeni
ortak bir fonksiyon çağıracaklar:

```python
async def save_versioned_entry(
    db: Session, entry_type: str, title: str, content: str, user_id: int,
) -> dict:
    """(entry_type, title) icin mevcut is_current versiyonu bulur, fark uretir,
    eskiyi arsivler, yeni versiyonu ve arama kayitlarini olusturur.
    Doner: {"is_update": bool, "diff_summary": str|None, "chunks": int}"""
```

Başlık eşleştirmesi **tam, büyük/küçük harf duyarlı** string karşılaştırmasıdır
(normalize/trim dışında ekstra fuzzy-match yok) — mevcut `list_knowledge_rules`/
`list_knowledge_examples` de başlıkları hiç normalize etmiyor, bu davranışla
tutarlı. `"Şifre Kuralı"` ile `"şifre kuralı"` farklı başlık sayılır, admin aynı
kaydı güncellemek istiyorsa önceki başlığı birebir kopyalamalı (mevcut kartlardan
kopyala-yapıştır ile).

Adımlar:

1. `KnowledgeDocumentVersion` üzerinde `(entry_type, title, is_current=True)`
   sorgusu → `previous` (None veya satır).
2. **`previous` yoksa:** yeni versiyon satırı (`diff_summary=None`) eklenir →
   git 4.3'e (arama kayıtlarını oluştur).
3. **`previous` varsa:**
   - `previous.full_content == content` ise: hiçbir şey değişmemiş — mevcut
     davranış korunur, kayıt/embedding yeniden oluşturulmaz, `{"is_update":
     False, "diff_summary": None, "chunks": 0}` döner (gereksiz LLM/embedding
     çağrısı yapılmaz).
   - Farklıysa: `difflib.unified_diff(previous.full_content.splitlines(),
     content.splitlines(), lineterm="")` ile satır bazlı diff çıkarılır →
     `build_diff_summary_prompt(title, diff_text)` (yeni, `testcasegen_service.py`)
     ile prompt kurulur → `ai_service.ollama_generate_text(prompt)` çağrılır →
     `diff_summary` (düz metin, 2-5 cümle).
     - LLM çağrısı başarısız olursa (`try/except`): `diff_summary` = ham diff'in
       kısa bir özeti yerine, sabit bir uyarı metni ("İçerik değişti ama otomatik
       özet çıkarılamadı — Ollama'ya ulaşılamadı.") — kayıt işlemi YİNE
       tamamlanır, LLM adımı best-effort'tur, engelleyici değildir.
   - `previous.is_current = False` yapılır, `db.commit()`.
   - Yeni `KnowledgeDocumentVersion` satırı (`diff_summary` ile) eklenir.

### 4.3 Arama havuzunun (RAG) güncellenmesi

`(entry_type, title)` ile eşleşen mevcut `KnowledgeEntry` satırları (chunk +
embedding) silinir, ardından:

- `entry_type == "rule"`: mevcut `knowledge_service.add_entry()` aynen çağrılır
  (chunk'lama + embedding, mevcut davranış).
- `entry_type == "example"`: mevcut `knowledge_service.add_example()` aynen
  çağrılır (chunklanmaz, embedding yok — mevcut davranış).

Bu adım hem ilk-kayıt hem güncelleme durumunda çalışır (fark: güncellemede önce
silme var).

### 4.4 API sözleşmesi değişikliği

`POST /knowledge/rules` ve `POST /knowledge/examples` response'u genişler:

```json
{ "status": "ok", "chunks": 3, "is_update": true,
  "diff_summary": "Şifre alanı için minimum karakter sayısı 8'den 10'a çıkarıldı." }
```

(`is_update`/`diff_summary` yeni alanlar — geriye dönük uyumlu, mevcut alanlar
korunuyor.)

### 4.5 Değişiklik Geçmişi listeleme endpoint'i

```
GET /api/testcasegen/knowledge/history?entry_type=rule|example (opsiyonel filtre)
→ { "versions": [
      { "id", "entry_type", "title", "is_current", "diff_summary",
        "created_by": "<username|null>", "created_at" }, ...
    ] }
```

`full_content` bu listede DÖNMEZ (liste görünümü için gereksiz büyük); ayrı bir
`GET /knowledge/history/{id}` ile tek versiyonun tam içeriği istenirse alınabilir
(sayfada "tam içeriği gör" linki için — bu spec'te opsiyonel, ilk sürümde
atlanabilir, plan aşamasında karar verilir).

## 5. Frontend Değişiklikleri

### 5.1 `admin-knowledge.html` — mevcut modal'a dosya yükleme

Modal'daki `fContent` textarea'sının üstüne (`rule-modal-body` içine) bir
dosya-bırak alanı eklenir (mevcut `java-generator.html`'deki
`.file-drop-zone` deseniyle tutarlı — aynı CSS sınıfı yeniden kullanılabilir
veya kopyalanır). Dosya seçilince:

1. `POST /knowledge/extract-file` (multipart) çağrılır.
2. Dönen `text` → `fContent.value`, `suggested_title` → `fTitle.value`
   (**sadece `fTitle` boşsa** — admin bir şey yazmışsa üzerine yazılmaz).
3. Admin normal "Kaydet" akışına devam eder (mevcut `saveRule()`), sunucudan
   dönen `is_update`/`diff_summary` işlenir (bkz. 5.2).

### 5.2 Kayıt sonrası fark bildirimi

`saveRule()` (`admin-knowledge.html:277-298`) güncellenir: `result.is_update &&
result.diff_summary` varsa, mevcut `Toast.success` yerine (ya da onun yanında)
içeriği gösteren bir modal/banner açılır — başlık: *"'{title}' güncellendi —
neler değişti?"*, içerik: `diff_summary` metni. Basit bir `alert`-benzeri modal
yeterli (mevcut `rule-modal-overlay` deseni yeniden kullanılabilir, yeni bir
"diff modal" olarak).

### 5.3 Yeni sayfa: `admin-knowledge-history.html`

`admin-knowledge.html` ile aynı iskelet (sidebar, header, Theme.toggle).
İçerik: `GET /knowledge/history` sonucu, en yeniden eskiye, kart listesi —
her kart: başlık, tür rozeti (🧠 Kural / 📋 Örnek), "kim/ne zaman", ve
`diff_summary` (ilk kayıtsa "🆕 İlk kayıt" rozeti, `diff_summary=None`
olduğunda). Opsiyonel: `entry_type` filtre sekmeleri (mevcut tab-bar deseni).

`admin-knowledge.html` header'ına bu sayfaya giden bir link/buton eklenir
("🕓 Değişiklik Geçmişi"). Sidebar navigasyonuna eklenip eklenmeyeceği
implementasyon planında karara bağlanır (mevcut admin sayfa listesi
`js/sidebar.js`'de tanımlı, oraya bir satır eklemek gerekebilir).

## 6. Hata Durumları

- Embedding modeli erişilemezse (`knowledge_service.add_entry` boş liste
  dönerse rule için): mevcut davranış korunur — `503 "Embedding modeli
  kullanılamıyor"`. Versiyon satırı (KnowledgeDocumentVersion) YİNE de
  yazılmaz (transaction bütünlüğü: embedding başarısızsa hiçbir şey commit
  edilmez) — kullanıcı hatayı görür, tekrar dener.
- LLM diff-özeti başarısız olursa (§4.2): kayıt işlemi engellenmez, sabit
  uyarı metni `diff_summary` olarak yazılır.
- Desteklenmeyen dosya uzantısı (`extract-file`): `400`, mevcut
  `_ALLOWED_DOC_EXTS` deseninin genişletilmiş hâli (`.docx,.xlsx,.txt,.md`).
- Boş/whitespace-only içerik: mevcut `add_knowledge_rule`/`add_knowledge_example`
  validasyonları korunur (400).

## 7. Test Planı

- `knowledge_service.save_versioned_entry`: ilk kayıt, aynı içerikle tekrar
  kayıt (no-op), farklı içerikle güncelleme (diff üretimi, eski `is_current`
  False oluyor mu), LLM hatası durumunda fallback metni.
- `testcasegen_router`: `/knowledge/extract-file` — docx/xlsx/txt/md için doğru
  metin çıkarımı, desteklenmeyen uzantı 400; `/knowledge/rules` ve
  `/knowledge/examples` POST — response'ta `is_update`/`diff_summary` alanları;
  `/knowledge/history` — sıralama ve filtre.
- Mevcut `tests/test_testcasegen_router_knowledge.py`,
  `tests/test_knowledge_service.py` dosyalarına eklenir (yeni dosya açılmaz,
  mevcut desen korunur).

## 8. Açık Kalan Küçük Kararlar (plan aşamasında netleşecek)

- `GET /knowledge/history/{id}` (tam içerik görüntüleme) ilk sürüme dahil mi,
  yoksa sonraki bir iyileştirme mi?
- Değişiklik Geçmişi sayfası sidebar'a eklenecek mi yoksa sadece
  admin-knowledge sayfasından link ile mi erişilecek?
