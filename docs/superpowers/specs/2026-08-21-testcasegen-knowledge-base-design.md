# TestCaseGen — Paylaşımlı Bilgi Tabanı (RAG) Tasarımı

**Tarih:** 2026-08-21
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

Sunucuda GPU yok (CPU-only), bu yüzden Gemini gibi bulut LLM'ler kullanılamıyor (API key verilemiyor) ve yerel modellerin gerçek bir fine-tuning'i pratik değil (CPU'da günler sürer). Bunun yerine TestCaseGen'in ürettiği/tükettiği bilgiyi kalıcı, aranabilir bir depoda tutup her yeni üretimde ilgili parçaları LLM prompt'una enjekte eden bir **RAG (retrieval-augmented generation)** katmanı ekliyoruz — "eğitim" yerine "hafıza".

Depo **tüm kullanıcılar arasında paylaşımlı** (şirket-geneli bilgi tabanı): bir kullanıcının yüklediği analiz dökümanı veya düzelttiği bir adım, başka bir kullanıcının senaryo üretiminde de referans olarak kullanılabilir.

**Kapsam dışı (bilinçli YAGNI kararları):**
- Ayrı bir vektör veritabanı (Chroma/FAISS) — ölçek "küçük başla" kararına göre SQLite + brute-force cosine similarity yeterli. Kayıt sayısı binleri aşarsa ayrı bir iterasyonda değerlendirilir.
- Kullanıcıya özel/izole bilgi tabanı seçeneği — bu iterasyonda sadece paylaşımlı mod var.
- Düzeltmelerin admin onayından geçmesi — otomatik olarak havuza eklenir (kullanıcı kararı).
- Bilgi tabanı girdilerini düzenleme/silme UI'ı (admin rules hariç) — sadece admin, kendi eklediği `rule` tipi kayıtları silebilir. `document`/`scenario`/`correction` kayıtları için silme arayüzü şimdilik yok.
- Chunking için akıllı (cümle/anlam sınırlı) bölme — sabit karakter uzunluğunda basit bölme yeterli.

## Yeni Bağımlılık

Sunucuda Ollama'ya embedding modeli eklenmesi gerekiyor: `ollama pull nomic-embed-text` (~274MB, CPU'da hızlı — üretim modeli `qwen2.5vl:7b`'ye dokunulmuyor, o aynen kalıyor).

`backend/requirements.txt`'e `numpy` eklenir (cosine similarity hesaplaması için; opencv üzerinden zaten transitive olarak kurulu olabilir ama doğrudan bağımlılık olarak belirtilir).

## Veri Modeli

### Yeni tablo: `KnowledgeEntry` (`backend/models/db_models.py`)

```python
class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String, index=True)   # "document" | "scenario" | "correction" | "rule"
    title = Column(String)                     # kısa etiket (dosya adı, senaryo başlığı, vs.)
    content = Column(Text)                     # gömülen metin parçası
    embedding = Column(LargeBinary)             # numpy float32 array, .tobytes()
    embedding_dim = Column(Integer)             # float32 sayısını byte'tan geri çözmek için (örn. 768)
    source_ref = Column(String, nullable=True)  # session_id / testcase_id gibi izlenebilirlik bilgisi
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # rule için admin, diğerlerinde işlemi yapan kullanıcı
    created_at = Column(DateTime, default=datetime.utcnow)
```

Yeni tablo olduğu için migration script gerekmiyor — `database.py::init_db()` içindeki `Base.metadata.create_all(bind=engine)` otomatik oluşturur.

## Backend Değişiklikleri

### `services/ai_service.py` — yeni fonksiyon

```python
def get_embedding_config() -> dict:
    cfg = get_ai_config()
    return {
        "url": cfg.get("ollama_embed_url", "http://localhost:11434/api/embeddings"),
        "model": cfg.get("ollama_embed_model", "nomic-embed-text"),
    }

async def ollama_embed(text: str) -> Optional[list[float]]:
    """Embedding modeline istek atar; model kurulu değilse veya Ollama'ya ulaşılamazsa None döner (retrieval'i asla bloklamaz)."""
    cfg = get_embedding_config()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(cfg["url"], json={"model": cfg["model"], "prompt": text})
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception:
        return None
```

### Yeni servis: `backend/services/knowledge_service.py`

- `CHUNK_CHAR_LIMIT = 1000` — içerik bu uzunlukta parçalara bölünür (basit sabit-uzunluk bölme, kelime sınırında kesilir).
- `async def add_entry(db: Session, entry_type: str, title: str, content: str, user_id: int | None = None, source_ref: str | None = None) -> int` — içeriği parçalara böler, her parça için `ai_service.ollama_embed()` çağırır, embedding `None` dönerse o parça atlanır (log yazılır), başarıyla eklenen parça sayısını döner.
- `async def search(db: Session, query_text: str, top_k: int = 5, entry_types: list[str] | None = None) -> list[str]` — query'yi embed eder; embedding alınamazsa boş liste döner (retrieval sessizce atlanır). Aksi halde `entry_types` filtresine uyan tüm `KnowledgeEntry` satırlarını çeker, numpy ile cosine similarity hesaplar, en yüksek `top_k` satırın `content`'ini döner.
- `def format_context_block(snippets: list[str]) -> str` — boşsa `""`, doluysa prompt'a eklenecek "İlgili geçmiş bilgi / kurallar:\n- ...\n- ..." bloğu üretir.

### `routers/testcasegen_router.py` — 4 besleme noktası

1. **Doküman yükleme** (`POST /sessions/{id}/document/upload`, mevcut endpoint — 2026-08-19 spec'inde tanımlı): metin çıkarıldıktan sonra `await knowledge_service.add_entry(db, "document", body.filename, extracted_text, user_id=current_user.id, source_ref=session_id)` çağrısı eklenir. Hata olsa da upload akışını bloklamaz (`try/except`, hata sadece loglanır).
2. **Onaylı senaryo** (`POST /sessions/{id}/export`): export edilen her testcase için, steps'i düz metne çevirip (`"Adım: ... → Beklenen: ..."` satırları) `add_entry(db, "scenario", title["text"], steps_text, user_id=current_user.id, source_ref=tc["id"])` çağrılır. Export akışını bloklamaz.
3. **Düzeltme** (`PUT /sessions/{id}/testcases/{tc_id}/steps/{idx}`): `tc["steps"][idx]` üzerine yazmadan önce eski değer saklanır; `validated[0] != eski_değer` ise `add_entry(db, "correction", title_text, f"Eski: {eski}\nDoğrusu: {yeni}", user_id=current_user.id, source_ref=tc_id)` çağrılır. Kaydetme akışını bloklamaz.
4. **Admin kuralı** (yeni endpoint): `POST /api/testcasegen/knowledge/rules` — `Depends(require_admin)`, body `{title: str, content: str}` (`.md` metni), `add_entry(db, "rule", title, content, user_id=admin.id)`. `GET /api/testcasegen/knowledge/rules` (admin) — listele. `DELETE /api/testcasegen/knowledge/rules/{id}` (admin) — sil.

**Retrieval — üretim noktaları:**
- `POST /sessions/{id}/generate-testcases`: `svc.build_testcase_prompt(...)` çağrılmadan önce `context = await knowledge_service.search(db, title["text"], top_k=5)`; dönen blok prompt'un başına eklenir.
- `POST /sessions/{id}/extract-titles` ve `POST /sessions/{id}/document/extract-titles`: aynı şekilde, ilgili prompt builder'lara `context_block` parametresi eklenir.

Tüm retrieval çağrıları `try/except` ile sarılır — embedding modeli kurulu değilse veya Ollama'ya ulaşılamazsa üretim knowledge-base'siz (eskisi gibi) devam eder, kullanıcıya hata gösterilmez.

### `routers/testcasegen_router.py` (veya yeni `knowledge_router.py`) — admin durum endpoint'i

`GET /api/testcasegen/knowledge/status` — embedding modelinin Ollama'da kurulu olup olmadığını döner (`ai_service.ollama_embed("test")` ile hızlı bir kontrol veya `/api/tags` listesinde `nomic-embed-text` var mı kontrolü). Admin panelinde "Bilgi tabanı: aktif / embedding modeli eksik" rozeti için kullanılır.

## Frontend Değişiklikleri

- **`testcasegen.html`:** Değişiklik yok — retrieval tamamen backend'de, kullanıcı akışını etkilemez.
- **Admin paneli (`WebArayuz/admin-*.html` — uygun bir sayfaya eklenir, örn. yeni `admin-knowledge.html` veya mevcut ai-config sayfasına bölüm):** `.md` kural ekleme/listeleme/silme formu, `knowledge/status` rozeti.

## Hata Yönetimi

| Durum | Davranış |
|---|---|
| Embedding modeli kurulu değil / Ollama'ya ulaşılamıyor | `ollama_embed` → `None`, `add_entry`/`search` sessizce atlanır (log), ana akış (upload/export/save/generate) hatasız devam eder |
| `search` sonucu boş (hiç kayıt yok) | Prompt'a context bloğu eklenmez, eskisi gibi üretim yapılır |
| Admin olmayan kullanıcı `rules` endpoint'ine istek atarsa | 403 (`require_admin` zaten bunu sağlıyor) |
| Çok uzun içerik (`content` parametresi) | `CHUNK_CHAR_LIMIT` (1000 karakter) parçalara bölünür, her parça ayrı `KnowledgeEntry` satırı olur |

## Test Kapsamı

- `test_knowledge_service.py` (yeni) — `add_entry`/`search` birim testleri: mock `ollama_embed` ile sabit vektörler kullanılarak cosine similarity sıralamasının doğruluğu; embedding `None` döndüğünde `add_entry`'nin sessizce atladığı; `entry_types` filtresinin çalıştığı.
- `test_testcasegen_router_knowledge.py` (yeni) — 4 besleme noktasının her birinde (mock `knowledge_service.add_entry`) ilgili çağrının doğru `entry_type`/`content` ile yapıldığı; `generate_testcases`'ın prompt'una `search` sonucunun enjekte edildiği (mock `knowledge_service.search`); admin `rules` CRUD endpoint'lerinin yetki kontrolü (403 non-admin, 200 admin).
- Mevcut TestCaseGen testleri (ekran + döküman akışları) değişmeden geçmeli — knowledge-base entegrasyonu `try/except` ile sarılı olduğundan, `knowledge_service` mock'lanmadığı testlerde bile (gerçek Ollama yoksa `ollama_embed` `None` döner) ana akışı bozmamalı.
