# TestCaseGen Paylaşımlı Bilgi Tabanı (RAG) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TestCaseGen'de üretilen/tüketilen bilgiyi (yüklenen analiz dökümanları, onaylı senaryolar, kullanıcı düzeltmeleri, admin kuralları) SQLite'ta kalıcı ve aranabilir tutup, yeni senaryo üretimlerinde ilgili parçaları LLM prompt'una enjekte eden paylaşımlı bir RAG katmanı eklemek.

**Architecture:** Yeni `KnowledgeEntry` tablosu (tüm kullanıcılar arasında paylaşımlı) + yeni `services/knowledge_service.py` (embed → chunk → sakla → cosine-similarity ile getir). Embedding, Ollama üzerinden ayrı hafif bir modelle (`nomic-embed-text`) alınır — üretim modeli `qwen2.5vl:7b`'ye dokunulmaz. `testcasegen_router.py`'daki 4 nokta veri besler (döküman yükleme, export, adım düzeltme, admin `.md` kuralı); 2 nokta bu veriyi geri okuyup prompt'a ekler (`generate-testcases`, `document/extract-titles`). Tüm besleme/geri-okuma çağrıları `try/except` ile sarılı — embedding modeli kurulu değilse ana akış hiç etkilenmez.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (SQLite), Ollama (`nomic-embed-text` embedding + mevcut üretim modeli), numpy (cosine similarity), pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-08-21-testcasegen-knowledge-base-design.md`

## Global Constraints

- Paylaşımlı bilgi tabanı — kullanıcı bazlı izolasyon YOK, tüm `KnowledgeEntry` kayıtları tüm kullanıcıların üretimlerinde kullanılabilir.
- `CHUNK_CHAR_LIMIT = 1000` — içerik bu uzunlukta sabit parçalara bölünür (kelime sınırında).
- Embedding modeli: `nomic-embed-text` (config key: `ollama_embed_model`, varsayılan bu). Üretim modeli (`qwen2.5vl:7b` / `gemma3:4b`) değişmiyor.
- Her `add_entry`/`search` çağrısı, çağıran router endpoint'inde `try/except Exception: pass` (add_entry) veya `except Exception: context = []` (search) ile sarılmalı — embedding modeli kurulu değilse veya Ollama'ya ulaşılamazsa ana akış (upload/export/edit/generate) ASLA bozulmamalı.
- `.md` kural yönetimi (`POST/GET/DELETE /knowledge/rules`) sadece admin (`Depends(require_admin)`).

**Spec'ten bilinçli sapma:** Spec, retrieval'in `extract-titles` (ekran tabanlı, vision, SSE) akışına da uygulanmasını öneriyordu. Bu plan bunu YAPMIYOR: o akış ekran başına çağrılıyor (per-screen SSE loop), sorgu metni genelde zayıf (`user_note` çoğu zaman boş) ve CPU-only sunucuda her ekrana bir embedding round-trip'i daha eklemek, bu özelliğin çıkış noktası olan "CPU'da yavaşlık" sorununu büyütür. Retrieval sadece **generate-testcases** (screens+document dalları) ve **document/extract-titles**'a eklenir — ikisi de tek seferlik, zengin metin sorgulu çağrılar.

---

### Task 1: Embedding altyapısı — `KnowledgeEntry` modeli + `ai_service.ollama_embed()`

**Files:**
- Modify: `backend/models/db_models.py` (import satırı + dosya sonu)
- Modify: `backend/services/ai_service.py` (dosya sonu)
- Test: `backend/tests/test_ai_service_embedding.py` (yeni)

**Interfaces:**
- Consumes: yok
- Produces:
  - `models.db_models.KnowledgeEntry` — SQLAlchemy modeli (`id`, `entry_type`, `title`, `content`, `embedding: bytes`, `embedding_dim: int`, `source_ref`, `created_by_user_id`, `created_at`)
  - `ai_service.get_embedding_config() -> dict` — `{"url": str, "model": str}`
  - `ai_service.ollama_embed(text: str) -> Optional[list[float]]` — başarısızsa `None`

- [ ] **Step 1: Başarısız testi yaz**

`backend/tests/test_ai_service_embedding.py`:

```python
import asyncio
import httpx
import pytest

from services import ai_service


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        return _FakeResponse({"embedding": [0.1, 0.2, 0.3]})


def test_ollama_embed_returns_embedding_list(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    result = asyncio.run(ai_service.ollama_embed("bir metin"))
    assert result == [0.1, 0.2, 0.3]


def test_ollama_embed_uses_configured_model(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse({"embedding": [0.5]})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(ai_service, "get_embedding_config", lambda: {
        "url": "http://localhost:11434/api/embeddings", "model": "nomic-embed-text",
    })
    asyncio.run(ai_service.ollama_embed("metin"))
    assert captured["json"]["model"] == "nomic-embed-text"
    assert captured["json"]["prompt"] == "metin"


def test_ollama_embed_returns_none_on_connection_error(monkeypatch):
    class FailingClient(_FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("baglanti yok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    result = asyncio.run(ai_service.ollama_embed("metin"))
    assert result is None


def test_ollama_embed_returns_none_on_http_error(monkeypatch):
    class ErrorResponse(_FakeResponse):
        def raise_for_status(self):
            raise httpx.HTTPStatusError("model yok", request=None, response=None)

    class ErrorClient(_FakeAsyncClient):
        async def post(self, url, json):
            return ErrorResponse({})

    monkeypatch.setattr(httpx, "AsyncClient", ErrorClient)
    result = asyncio.run(ai_service.ollama_embed("metin"))
    assert result is None
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_ai_service_embedding.py -v`
Expected: FAIL — `AttributeError: module 'services.ai_service' has no attribute 'ollama_embed'`

- [ ] **Step 3: `db_models.py`'a `KnowledgeEntry` ekle**

`backend/models/db_models.py` satır 4'ü güncelle:

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, LargeBinary
```

Dosyanın en sonuna (mevcut son satır 396, `AiJobRunResult` sınıfından sonra) ekle:

```python


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String, index=True)  # "document" | "scenario" | "correction" | "rule"
    title = Column(String)
    content = Column(Text)
    embedding = Column(LargeBinary)
    embedding_dim = Column(Integer)
    source_ref = Column(String, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: `ai_service.py`'a embedding fonksiyonlarını ekle**

`backend/services/ai_service.py` dosyasının sonuna (mevcut `ollama_generate_vision` fonksiyonundan sonra, satır 193 civarı) ekle:

```python


def get_embedding_config() -> dict:
    """Embedding modeli URL ve model adı (config > varsayılan)"""
    cfg = get_ai_config()
    return {
        "url": cfg.get("ollama_embed_url", "http://localhost:11434/api/embeddings"),
        "model": cfg.get("ollama_embed_model", "nomic-embed-text"),
    }


async def ollama_embed(text: str) -> Optional[List[float]]:
    """Embedding modeline istek atar; model kurulu değilse veya Ollama'ya ulaşılamazsa None döner
    (çağıran taraf bunu 'bilgi tabanını atla' olarak yorumlar, asla hata fırlatmaz)."""
    cfg = get_embedding_config()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(cfg["url"], json={"model": cfg["model"], "prompt": text})
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception:
        return None
```

- [ ] **Step 5: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_ai_service_embedding.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/models/db_models.py backend/services/ai_service.py backend/tests/test_ai_service_embedding.py
git commit -m "TestCaseGen: KnowledgeEntry modeli ve Ollama embedding entegrasyonu"
```

---

### Task 2: `knowledge_service.add_entry` — chunking + kayıt

**Files:**
- Create: `backend/services/knowledge_service.py`
- Test: `backend/tests/test_knowledge_service.py` (yeni)

**Interfaces:**
- Consumes: `ai_service.ollama_embed(text) -> Optional[list[float]]` (Task 1), `models.db_models.KnowledgeEntry` (Task 1)
- Produces:
  - `knowledge_service.CHUNK_CHAR_LIMIT: int = 1000`
  - `knowledge_service.add_entry(db: Session, entry_type: str, title: str, content: str, user_id: int | None = None, source_ref: str | None = None) -> int` — eklenen parça sayısını döner

- [ ] **Step 1: Başarısız testi yaz**

`backend/tests/test_knowledge_service.py`:

```python
import asyncio

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import KnowledgeEntry
from services import ai_service, knowledge_service as ks


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_add_entry_stores_embedding_and_returns_count(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    added = asyncio.run(ks.add_entry(db, "document", "analiz.docx", "Kisa bir dokuman metni.", user_id=1, source_ref="s1"))

    assert added == 1
    rows = db.query(KnowledgeEntry).all()
    assert len(rows) == 1
    assert rows[0].entry_type == "document"
    assert rows[0].title == "analiz.docx"
    assert rows[0].content == "Kisa bir dokuman metni."
    assert rows[0].source_ref == "s1"
    assert rows[0].created_by_user_id == 1
    vec = np.frombuffer(rows[0].embedding, dtype=np.float32)
    assert list(vec) == pytest.approx([0.1, 0.2, 0.3])
    assert rows[0].embedding_dim == 3


def test_add_entry_chunks_long_content(db, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    long_text = ("kelime " * 400).strip()  # ~2800 karakter, CHUNK_CHAR_LIMIT'i (1000) asar
    added = asyncio.run(ks.add_entry(db, "document", "buyuk.docx", long_text))

    assert added >= 3
    rows = db.query(KnowledgeEntry).all()
    assert len(rows) == added
    assert all(len(r.content) <= ks.CHUNK_CHAR_LIMIT for r in rows)


def test_add_entry_skips_chunk_when_embedding_unavailable(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    added = asyncio.run(ks.add_entry(db, "rule", "Kural", "icerik"))

    assert added == 0
    assert db.query(KnowledgeEntry).count() == 0


def test_add_entry_empty_content_returns_zero(db, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    added = asyncio.run(ks.add_entry(db, "rule", "Bos", "   "))

    assert added == 0
    assert db.query(KnowledgeEntry).count() == 0
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.knowledge_service'`

- [ ] **Step 3: `knowledge_service.py`'ı implemente et**

`backend/services/knowledge_service.py`:

```python
"""
Knowledge Service - TestCaseGen paylaşımlı bilgi tabanı (RAG)
---------------------------------------------------------------
- Yüklenen analiz dökümanları, onaylı senaryolar, kullanıcı düzeltmeleri
  ve admin .md kuralları KnowledgeEntry olarak saklanır.
- Ollama embedding modeli (varsayılan: nomic-embed-text) ile vektörleştirilir.
- search(): cosine similarity ile en alakalı içerikleri döner.
"""

import numpy as np
from sqlalchemy.orm import Session

from models.db_models import KnowledgeEntry
from services import ai_service

CHUNK_CHAR_LIMIT = 1000


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= CHUNK_CHAR_LIMIT:
            chunks.append(remaining.strip())
            break
        cut = remaining.rfind(" ", 0, CHUNK_CHAR_LIMIT)
        if cut <= 0:
            cut = CHUNK_CHAR_LIMIT
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [c for c in chunks if c]


async def add_entry(
    db: Session,
    entry_type: str,
    title: str,
    content: str,
    user_id: "int | None" = None,
    source_ref: "str | None" = None,
) -> int:
    """content'i CHUNK_CHAR_LIMIT parçalara böler, her parça için embedding alır.
    Embedding alınamayan parçalar atlanır. Eklenen parça sayısını döner."""
    added = 0
    for chunk in _chunk_text(content):
        embedding = await ai_service.ollama_embed(chunk)
        if embedding is None:
            continue
        vec = np.asarray(embedding, dtype=np.float32)
        db.add(KnowledgeEntry(
            entry_type=entry_type,
            title=title,
            content=chunk,
            embedding=vec.tobytes(),
            embedding_dim=int(vec.shape[0]),
            source_ref=source_ref,
            created_by_user_id=user_id,
        ))
        added += 1
    if added:
        db.commit()
    return added
```

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -v`
Expected: 4 passed

(Not: `numpy` henüz `requirements.txt`'e eklenmedi — Task 3'te ekleniyor. Bu venv'de opencv üzerinden zaten kurulu olduğundan testler bu adımda da geçer.)

- [ ] **Step 5: Commit**

```bash
git add backend/services/knowledge_service.py backend/tests/test_knowledge_service.py
git commit -m "TestCaseGen: knowledge_service.add_entry - chunking ve embedding kaydi"
```

---

### Task 3: `knowledge_service.search` + `format_context_block`

**Files:**
- Modify: `backend/services/knowledge_service.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_knowledge_service.py`

**Interfaces:**
- Consumes: `ai_service.ollama_embed` (Task 1), `KnowledgeEntry` (Task 1), `add_entry` (Task 2, testte fixture verisi oluşturmak için)
- Produces:
  - `knowledge_service.search(db: Session, query_text: str, top_k: int = 5, entry_types: list[str] | None = None) -> list[str]`
  - `knowledge_service.format_context_block(snippets: list[str]) -> str`

- [ ] **Step 1: Başarısız testleri ekle**

`backend/tests/test_knowledge_service.py` dosyasının sonuna ekle:

```python
def test_search_ranks_by_cosine_similarity(db, monkeypatch):
    embeddings = {
        "sorgu": [1.0, 0.0],
        "alakali": [0.9, 0.1],
        "alakasiz": [0.0, 1.0],
    }

    async def fake_embed(text):
        return embeddings[text]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.add_entry(db, "document", "t1", "alakali"))
    asyncio.run(ks.add_entry(db, "document", "t2", "alakasiz"))

    result = asyncio.run(ks.search(db, "sorgu", top_k=5))
    assert result == ["alakali", "alakasiz"]


def test_search_respects_top_k(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    for i in range(3):
        asyncio.run(ks.add_entry(db, "document", f"t{i}", f"icerik {i}"))

    result = asyncio.run(ks.search(db, "sorgu", top_k=2))
    assert len(result) == 2


def test_search_filters_by_entry_types(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.add_entry(db, "document", "t1", "dokuman icerik"))
    asyncio.run(ks.add_entry(db, "rule", "t2", "kural icerik"))

    result = asyncio.run(ks.search(db, "sorgu", entry_types=["rule"]))
    assert result == ["kural icerik"]


def test_search_returns_empty_list_when_embedding_unavailable(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    result = asyncio.run(ks.search(db, "sorgu"))
    assert result == []


def test_search_returns_empty_list_when_no_entries(db, monkeypatch):
    async def fake_embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    result = asyncio.run(ks.search(db, "sorgu"))
    assert result == []


def test_format_context_block_empty_returns_empty_string():
    assert ks.format_context_block([]) == ""


def test_format_context_block_formats_bullet_list():
    block = ks.format_context_block(["birinci", "ikinci"])
    assert "İlgili geçmiş bilgi" in block
    assert "- birinci" in block
    assert "- ikinci" in block
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -v`
Expected: FAIL — `AttributeError: module 'services.knowledge_service' has no attribute 'search'`

- [ ] **Step 3: `requirements.txt`'e `numpy` ekle**

`backend/requirements.txt` dosyasına (uygun bir bölümün altına, örn. `# Excel` bloğunun yanına) ekle:

```
# Embedding / RAG
numpy>=1.26.0
```

Run: `cd backend && venv/Scripts/python.exe -m pip install "numpy>=1.26.0"`
Expected: `Requirement already satisfied` veya `Successfully installed`

- [ ] **Step 4: `search` ve `format_context_block`'u implemente et**

`backend/services/knowledge_service.py` dosyasının sonuna ekle:

```python


async def search(
    db: Session,
    query_text: str,
    top_k: int = 5,
    entry_types: "list[str] | None" = None,
) -> list[str]:
    """query_text'i embed eder, kayıtlı KnowledgeEntry'ler arasından cosine similarity'ye göre
    en alakalı top_k içeriği döner. Embedding alınamazsa veya hiç kayıt yoksa boş liste döner."""
    query_embedding = await ai_service.ollama_embed(query_text)
    if query_embedding is None:
        return []
    query_vec = np.asarray(query_embedding, dtype=np.float32)

    q = db.query(KnowledgeEntry)
    if entry_types:
        q = q.filter(KnowledgeEntry.entry_type.in_(entry_types))
    rows = q.all()
    if not rows:
        return []

    scored = []
    for row in rows:
        vec = np.frombuffer(row.embedding, dtype=np.float32)
        if vec.shape[0] != query_vec.shape[0]:
            continue
        denom = float(np.linalg.norm(query_vec) * np.linalg.norm(vec))
        score = float(np.dot(query_vec, vec) / denom) if denom else 0.0
        scored.append((score, row.content))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [content for _, content in scored[:top_k]]


def format_context_block(snippets: list[str]) -> str:
    if not snippets:
        return ""
    bullet_list = "\n".join(f"- {s}" for s in snippets)
    return f"İlgili geçmiş bilgi / kurallar:\n{bullet_list}\n\n"
```

- [ ] **Step 5: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add backend/services/knowledge_service.py backend/requirements.txt backend/tests/test_knowledge_service.py
git commit -m "TestCaseGen: knowledge_service.search - cosine similarity ile retrieval"
```

---

### Task 4: Besleme noktası — döküman yükleme + onaylı senaryo (export)

**Files:**
- Modify: `backend/routers/testcasegen_router.py:23` (import), `:171-202` (`upload_document`), `:525-538` (`export_testcases`)
- Test: `backend/tests/test_testcasegen_router_document.py`, `backend/tests/test_testcasegen_router_export.py`

**Interfaces:**
- Consumes: `knowledge_service.add_entry` (Task 2)
- Produces: yok (uç noktalar dışa mimari arayüz eklemiyor)

- [ ] **Step 1: Başarısız testleri ekle — döküman yükleme**

`backend/tests/test_testcasegen_router_document.py` dosyasının importlarını güncelle (mevcut importların üstüne/yanına ekle):

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from services import knowledge_service
```

`client` fixture'ını `get_db` override edecek şekilde güncelle:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
```

Dosyanın sonuna ekle:

```python
def test_upload_document_adds_knowledge_entry(client, monkeypatch):
    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Giris ekrani test edilir.")
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "document"
    assert calls[0][1] == "analiz.docx"
    assert "Giris ekrani test edilir." in calls[0][2]


def test_upload_document_succeeds_even_if_knowledge_add_entry_fails(client, monkeypatch):
    async def failing_add_entry(*args, **kwargs):
        raise RuntimeError("embedding modeli yok")

    monkeypatch.setattr(knowledge_service, "add_entry", failing_add_entry)

    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Giris ekrani test edilir.")
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v`
Expected: FAIL — mevcut testler de dahil hepsi `db` fixture eksikliğinden veya `knowledge_service` importundan patlar (henüz router değişmedi)

- [ ] **Step 3: `upload_document`'a knowledge_service entegrasyonu ekle**

`backend/routers/testcasegen_router.py:23` satırını güncelle:

```python
from services import ai_service, testcasegen_service as svc, knowledge_service
```

`:172-202` arasındaki `upload_document` fonksiyonunu güncelle:

```python
@router.post("/sessions/{session_id}/document/upload")
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in _ALLOWED_DOC_EXTS:
        raise HTTPException(400, "Sadece .docx veya .xlsx desteklenir")

    content = await file.read()
    try:
        if ext == ".docx":
            text, truncated = svc.extract_text_from_docx(content)
        else:
            text, truncated = svc.extract_text_from_xlsx(content)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not text.strip():
        raise HTTPException(400, "Dökümandan metin çıkarılamadı, dosya boş görünüyor")

    session["document"] = {
        "filename": file.filename,
        "ext": ext,
        "extracted_text": text,
        "truncated": truncated,
        "candidate_titles": [],
    }
    svc.save_session(current_user.id, session_id, session)

    try:
        await knowledge_service.add_entry(
            db, "document", file.filename, text,
            user_id=current_user.id, source_ref=session_id,
        )
    except Exception:
        pass

    return session
```

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v`
Expected: hepsi (mevcut + 2 yeni) passed

- [ ] **Step 5: Başarısız testleri ekle — onaylı senaryo (export)**

`backend/tests/test_testcasegen_router_export.py` dosyasının importlarını güncelle:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from services import knowledge_service
```

`client` fixture'ını güncelle (Task 4 Step 1'deki ile aynı desen):

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
```

`_session_with_generated_testcase(client, monkeypatch)` yardımcı fonksiyonu `(session_id, tc_id)` tuple'ı döner (dosyanın mevcut hali). Dosyanın sonuna ekle:

```python
def test_export_adds_scenario_knowledge_entry_per_testcase(client, monkeypatch):
    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session_id, tc_id = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(
        f"/api/testcasegen/sessions/{session_id}/export",
        json={"testcase_ids": [tc_id]},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "scenario"


def test_export_succeeds_even_if_knowledge_add_entry_fails(client, monkeypatch):
    async def failing_add_entry(*args, **kwargs):
        raise RuntimeError("embedding modeli yok")

    monkeypatch.setattr(knowledge_service, "add_entry", failing_add_entry)

    session_id, tc_id = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(
        f"/api/testcasegen/sessions/{session_id}/export",
        json={"testcase_ids": [tc_id]},
    )
    assert resp.status_code == 200
```

- [ ] **Step 6: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_export.py -v`
Expected: FAIL — yeni 2 test `AttributeError`/`assert` ile başarısız (henüz router değişmedi)

- [ ] **Step 7: `export_testcases`'a knowledge_service entegrasyonu ekle**

`backend/routers/testcasegen_router.py:525-538` civarındaki `export_testcases` fonksiyonunu güncelle (imza + testcase döngüsünden sonra, `defaults = ...` satırından önce):

```python
@router.post("/sessions/{session_id}/export")
async def export_testcases(
    session_id: str,
    body: ExportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    if not body.testcase_ids:
        raise HTTPException(400, "Dışa aktarılacak test case seçilmedi")

    titles_by_id = {t["id"]: t for t in session["titles"]}
    testcases = [tc for tc in session["testcases"] if tc["id"] in body.testcase_ids]
    if not testcases:
        raise HTTPException(400, "Seçilen test case'ler bulunamadı")

    for tc in testcases:
        title = titles_by_id.get(tc["title_id"])
        title_text = title["text"] if title else ""
        steps_text = "\n".join(
            f"Adım: {s['step_action']} → Beklenen: {s['step_expected']}" for s in tc["steps"]
        )
        try:
            await knowledge_service.add_entry(
                db, "scenario", title_text, steps_text,
                user_id=current_user.id, source_ref=tc["id"],
            )
        except Exception:
            pass

    defaults = _tcg_defaults_dict(current_user)
    wb = svc.build_export_workbook(
        testcases, titles_by_id,
        defaults["area_path"], defaults["assigned_to"], defaults["state"],
    )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="testcases_{session_id[:8]}.xlsx"'},
    )
```

- [ ] **Step 8: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py tests/test_testcasegen_router_export.py -v`
Expected: hepsi passed

- [ ] **Step 9: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_document.py backend/tests/test_testcasegen_router_export.py
git commit -m "TestCaseGen: dokuman yukleme ve export akislari bilgi tabanini besliyor"
```

---

### Task 5: Besleme noktası — kullanıcı düzeltmesi (`edit_step`)

**Files:**
- Modify: `backend/routers/testcasegen_router.py:464-475` (`edit_step`)
- Test: `backend/tests/test_testcasegen_router_generate.py`

**Interfaces:**
- Consumes: `knowledge_service.add_entry` (Task 2)
- Produces: yok

- [ ] **Step 1: Başarısız testleri ekle**

`backend/tests/test_testcasegen_router_generate.py` dosyasının importlarını güncelle:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from services import knowledge_service
```

`client` fixture'ını güncelle (Task 4'teki aynı desen):

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
```

Dosyanın sonuna ekle:

```python
def test_edit_step_adds_correction_entry_when_changed(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tikla", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tıklanır", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == "correction"
    assert "X tikla" in calls[0][2]
    assert "X tıklanır" in calls[0][2]


def test_edit_step_skips_correction_entry_when_unchanged(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    calls = []

    async def fake_add_entry(db, entry_type, title, content, user_id=None, source_ref=None):
        calls.append((entry_type, title, content))
        return 1

    monkeypatch.setattr(knowledge_service, "add_entry", fake_add_entry)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tıklanır", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    assert calls == []
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_generate.py -v -k edit_step`
Expected: FAIL (henüz router değişmedi, `calls` boş kalır çünkü `add_entry` hiç çağrılmıyor)

- [ ] **Step 3: `edit_step`'e düzeltme tespiti ekle**

`backend/routers/testcasegen_router.py:464-475` civarındaki `edit_step` fonksiyonunu güncelle:

```python
@router.put("/sessions/{session_id}/testcases/{tc_id}/steps/{idx}")
async def edit_step(
    session_id: str,
    tc_id: str,
    idx: int,
    body: StepIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    old_step = None
    target_tc = None
    for tc in session["testcases"]:
        if tc["id"] == tc_id:
            old_step = tc["steps"][idx]
            validated = svc.validate_steps([{"step_action": body.step_action, "step_expected": body.step_expected}])
            tc["steps"][idx] = validated[0]
            target_tc = tc
            break
    else:
        raise HTTPException(404, "Test case bulunamadı")
    svc.save_session(current_user.id, session_id, session)

    new_step = target_tc["steps"][idx]
    if (old_step["step_action"], old_step["step_expected"]) != (new_step["step_action"], new_step["step_expected"]):
        titles_by_id = {t["id"]: t for t in session["titles"]}
        title = titles_by_id.get(target_tc["title_id"])
        title_text = title["text"] if title else ""
        correction_text = (
            f"Eski: {old_step['step_action']} → {old_step['step_expected']}\n"
            f"Doğrusu: {new_step['step_action']} → {new_step['step_expected']}"
        )
        try:
            await knowledge_service.add_entry(
                db, "correction", title_text, correction_text,
                user_id=current_user.id, source_ref=tc_id,
            )
        except Exception:
            pass

    return {"testcases": session["testcases"]}
```

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_generate.py -v`
Expected: hepsi (mevcut + 2 yeni) passed

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_generate.py
git commit -m "TestCaseGen: adim duzeltmeleri bilgi tabanina correction olarak kaydediliyor"
```

---

### Task 6: Admin kural yönetimi + bilgi tabanı durum endpoint'i

**Files:**
- Modify: `backend/routers/testcasegen_router.py:21-22` (import), dosya sonu (yeni endpoint'ler)
- Test: `backend/tests/test_testcasegen_router_knowledge.py` (yeni)

**Interfaces:**
- Consumes: `knowledge_service.add_entry` (Task 2), `ai_service.ollama_embed` (Task 1), `models.db_models.KnowledgeEntry` (Task 1)
- Produces:
  - `POST /api/testcasegen/knowledge/rules` (admin) — `{title, content}` → `{"status": "ok"}`
  - `GET /api/testcasegen/knowledge/rules` (admin) — `{"rules": [{id, title, content, created_at}, ...]}`
  - `DELETE /api/testcasegen/knowledge/rules/{entry_id}` (admin) — `{"status": "ok"}`
  - `GET /api/testcasegen/knowledge/status` — `{"embedding_model_available": bool}`

- [ ] **Step 1: Başarısız testleri yaz**

`backend/tests/test_testcasegen_router_knowledge.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from models.db_models import User
from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestSession()


def _client_for(db, user):
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: (yield db)
    return TestClient(app)


def test_add_rule_requires_admin(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    assert resp.status_code == 403


def test_admin_can_add_list_and_delete_rule(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    add_resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    assert add_resp.status_code == 200

    list_resp = client.get("/api/testcasegen/knowledge/rules")
    rules = list_resp.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["title"] == "Kural"
    assert rules[0]["content"] == "Icerik"

    del_resp = client.delete(f"/api/testcasegen/knowledge/rules/{rules[0]['id']}")
    assert del_resp.status_code == 200
    assert client.get("/api/testcasegen/knowledge/rules").json()["rules"] == []


def test_delete_unknown_rule_returns_404(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.delete("/api/testcasegen/knowledge/rules/999")
    assert resp.status_code == 404


def test_knowledge_status_reports_true_when_embedding_available(monkeypatch):
    async def fake_embed_ok(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_ok)
    app = FastAPI()
    app.include_router(testcasegen_router)
    client = TestClient(app)
    resp = client.get("/api/testcasegen/knowledge/status")
    assert resp.json() == {"embedding_model_available": True}


def test_knowledge_status_reports_false_when_embedding_unavailable(monkeypatch):
    async def fake_embed_fail(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed_fail)
    app = FastAPI()
    app.include_router(testcasegen_router)
    client = TestClient(app)
    resp = client.get("/api/testcasegen/knowledge/status")
    assert resp.json() == {"embedding_model_available": False}
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -v`
Expected: FAIL — `404 Not Found` (endpoint'ler henüz yok)

- [ ] **Step 3: Admin endpoint'lerini ekle**

`backend/routers/testcasegen_router.py:21-22` satırlarını güncelle:

```python
from routers.auth import get_current_user, require_admin
from models.db_models import User, KnowledgeEntry
```

Dosyanın sonuna (`export_testcases` fonksiyonundan sonra) ekle:

```python


# ── Bilgi Tabanı (Admin) ────────────────────────────────────────────────

class KnowledgeRuleIn(BaseModel):
    title: str
    content: str


@router.post("/knowledge/rules")
async def add_knowledge_rule(
    body: KnowledgeRuleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    await knowledge_service.add_entry(db, "rule", body.title, body.content, user_id=current_user.id)
    return {"status": "ok"}


@router.get("/knowledge/rules")
async def list_knowledge_rules(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.entry_type == "rule")
        .order_by(KnowledgeEntry.created_at.desc())
        .all()
    )
    return {"rules": [
        {"id": r.id, "title": r.title, "content": r.content, "created_at": r.created_at.isoformat()}
        for r in rows
    ]}


@router.delete("/knowledge/rules/{entry_id}")
async def delete_knowledge_rule(
    entry_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.id == entry_id, KnowledgeEntry.entry_type == "rule")
        .first()
    )
    if not row:
        raise HTTPException(404, "Kural bulunamadı")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


@router.get("/knowledge/status")
async def knowledge_status():
    embedding = await ai_service.ollama_embed("ping")
    return {"embedding_model_available": embedding is not None}
```

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_knowledge.py
git commit -m "TestCaseGen: admin icin bilgi tabani kural yonetimi ve durum endpoint'i"
```

---

### Task 7: Retrieval enjeksiyonu — `generate-testcases` ve `document/extract-titles`

**Files:**
- Modify: `backend/routers/testcasegen_router.py:213-233` (`extract_titles_from_document`), `:403-456` (`generate_testcases`)
- Test: `backend/tests/test_testcasegen_router_document.py`, `backend/tests/test_testcasegen_router_generate.py`

**Interfaces:**
- Consumes: `knowledge_service.search`, `knowledge_service.format_context_block` (Task 3)
- Produces: yok

- [ ] **Step 1: Başarısız testleri ekle**

`backend/tests/test_testcasegen_router_document.py` dosyasının sonuna ekle:

```python
def test_extract_titles_from_document_injects_rule_context(client, monkeypatch):
    captured = {}

    async def fake_text(prompt, model=None, timeout=60.0):
        captured["prompt"] = prompt
        return '{"titles": []}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    async def fake_search(db, query_text, top_k=5, entry_types=None):
        assert entry_types == ["rule"]
        return ["Sirket standardi: her ekran icin en az 1 negatif senaryo yazilmali"]

    monkeypatch.setattr(knowledge_service, "search", fake_search)

    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Giris ekrani test edilir.")
    client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    client.post(f"/api/testcasegen/sessions/{session['id']}/document/extract-titles")
    assert "negatif senaryo" in captured["prompt"]


def test_extract_titles_from_document_continues_when_search_fails(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"titles": []}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    async def failing_search(db, query_text, top_k=5, entry_types=None):
        raise RuntimeError("db hatasi")

    monkeypatch.setattr(knowledge_service, "search", failing_search)

    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Giris ekrani test edilir.")
    client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/document/extract-titles")
    assert resp.status_code == 200
```

`backend/tests/test_testcasegen_router_generate.py` dosyasının sonuna ekle:

```python
def test_generate_testcases_injects_knowledge_context_into_prompt(client, monkeypatch):
    captured = {}

    async def fake_text(prompt, model=None, timeout=60.0):
        captured["prompt"] = prompt
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    async def fake_search(db, query_text, top_k=5, entry_types=None):
        return ["Onceki kural: sifre alaninda en az 8 karakter olmali"]

    monkeypatch.setattr(knowledge_service, "search", fake_search)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert "en az 8 karakter olmali" in captured["prompt"]


def test_generate_testcases_continues_when_knowledge_search_fails(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)

    async def failing_search(db, query_text, top_k=5, entry_types=None):
        raise RuntimeError("db hatasi")

    monkeypatch.setattr(knowledge_service, "search", failing_search)

    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py tests/test_testcasegen_router_generate.py -v -k "injects_knowledge or injects_rule_context or knowledge_search_fails or search_fails"`
Expected: FAIL — `captured["prompt"]` içinde context metni yok (henüz retrieval eklenmedi)

- [ ] **Step 3: `extract_titles_from_document`'a retrieval ekle**

`backend/routers/testcasegen_router.py:213-233` civarındaki fonksiyonu güncelle:

```python
@router.post("/sessions/{session_id}/document/extract-titles")
async def extract_titles_from_document(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    document = session.get("document")
    if not document:
        raise HTTPException(400, "Önce bir analiz dökümanı yükleyin")

    try:
        context = await knowledge_service.search(db, document["extracted_text"][:1000], top_k=5, entry_types=["rule"])
    except Exception:
        context = []
    context_block = knowledge_service.format_context_block(context)

    prompt = context_block + svc.build_document_title_extraction_prompt(document["extracted_text"])
    try:
        raw = await ai_service.ollama_generate_text(prompt)
    except Exception as e:
        raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")

    parsed = svc.extract_json_object(raw)
    candidates = parsed.get("titles", []) if parsed else []
    document["candidate_titles"] = [
        {"text": c.get("text", ""), "excerpt": c.get("excerpt", "")}
        for c in candidates if c.get("text")
    ]
    svc.save_session(current_user.id, session_id, session)
    return session
```

- [ ] **Step 4: `generate_testcases`'a retrieval ekle**

`backend/routers/testcasegen_router.py:403-456` civarındaki fonksiyonu güncelle:

```python
@router.post("/sessions/{session_id}/generate-testcases")
async def generate_testcases(
    session_id: str,
    body: GenerateTestcasesIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _load_or_404(current_user.id, session_id)
    titles_by_id = {t["id"]: t for t in session["titles"]}
    screens_by_index = {s["index"]: s for s in session["screens"]}

    created = []
    for title_id in body.title_ids:
        title = titles_by_id.get(title_id)
        if not title:
            continue

        try:
            context = await knowledge_service.search(db, title["text"], top_k=5)
        except Exception:
            context = []
        context_block = knowledge_service.format_context_block(context)

        if title.get("source") == "document":
            prompt = context_block + svc.build_testcase_prompt_from_document(title["text"], title.get("doc_excerpt") or "")
            try:
                raw = await ai_service.ollama_generate_text(prompt)
            except Exception as e:
                raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")
        else:
            screens = [
                {
                    "index": i,
                    "summary": screens_by_index[i].get("screen_summary", ""),
                    "note": screens_by_index[i].get("user_note", ""),
                }
                for i in title["screen_indices"] if i in screens_by_index
            ]
            images_b64 = []
            for i in title["screen_indices"]:
                screen = screens_by_index.get(i)
                if not screen:
                    continue
                image_path = svc.screen_image_path(current_user.id, session_id, i, screen["image_ext"])
                if image_path.exists():
                    images_b64.append(base64.b64encode(image_path.read_bytes()).decode())

            prompt = context_block + svc.build_testcase_prompt(title["text"], screens)
            try:
                if images_b64:
                    raw = await ai_service.ollama_generate_vision(prompt, images_b64)
                else:
                    raw = await ai_service.ollama_generate_text(prompt)
            except Exception as e:
                raise HTTPException(503, f"Ollama servisine ulaşılamadı: {e}")

        parsed = svc.extract_json_object(raw)
        raw_steps = parsed.get("steps", []) if parsed else []
        steps = svc.validate_steps(raw_steps)
        testcase = {"id": str(uuid.uuid4()), "title_id": title_id, "steps": steps}
        session["testcases"].append(testcase)
        created.append(testcase)

    svc.save_session(current_user.id, session_id, session)
    return {"testcases": created}
```

- [ ] **Step 5: Tüm TestCaseGen testlerini çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/ -k testcasegen -v`
Expected: hepsi passed (regresyon yok)

- [ ] **Step 6: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_document.py backend/tests/test_testcasegen_router_generate.py
git commit -m "TestCaseGen: generate-testcases ve dokuman baslik cikarma bilgi tabanindan besleniyor"
```

---

### Task 8: Tam regresyon doğrulaması

**Files:** yok (sadece doğrulama)

**Interfaces:**
- Consumes: Task 1-7'nin tüm çıktıları
- Produces: yok

- [ ] **Step 1: Tam backend test suite'ini çalıştır**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q`
Expected: tüm testler (yeni ~25 + mevcut 143) passed, 0 failed

- [ ] **Step 2: Sunucuyu manuel başlatıp `/docs`'ta yeni endpoint'lerin göründüğünü doğrula**

Run: `cd backend && venv/Scripts/python.exe main.py` (arka planda başlat), sonra `http://localhost:8000/docs` adresinde `POST/GET/DELETE /api/testcasegen/knowledge/rules` ve `GET /api/testcasegen/knowledge/status` endpoint'lerinin listelendiğini gözle doğrula. Sunucuyu durdur.

- [ ] **Step 3: Operasyonel not — embedding modelini sunucuya kur**

Bu adım kod değişikliği değil, deployment notu: prod sunucuda çalıştırılmalı (bu plan bunu otomatik yapmaz):

```bash
ollama pull nomic-embed-text
```

Kurulu değilse `knowledge/status` `{"embedding_model_available": false}` döner ve tüm bilgi tabanı özellikleri sessizce devre dışı kalır (ana akışlar bozulmaz).
