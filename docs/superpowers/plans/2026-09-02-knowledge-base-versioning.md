# Bilgi Tabanı Versiyonlama + Dosya Yükleme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin Bilgi Tabanı sayfasına dosya yükleme ekle; aynı başlıkta yeni içerik geldiğinde eskisiyle farkını LLM'e özetlet ve kalıcı bir Değişiklik Geçmişi sayfasında göster.

**Architecture:** Yeni bir `KnowledgeDocumentVersion` tablosu tam metin + versiyon geçmişini tutar (mevcut `KnowledgeEntry` chunk+embedding arama tablosuna dokunulmadan, yanına eklenir). Kayıt/güncelleme tek bir ortak fonksiyondan (`knowledge_service.save_versioned_entry`) geçer: aynı `(entry_type, title)` için önceki versiyon varsa `difflib` ile satır farkı çıkarılır, LLM'e (Ollama) özetlettirilir, arama havuzu (chunk/embedding) yeni içerikle yeniden kurulur, eski arama satırları silinir. Dosya yükleme sadece metin çıkarır (mevcut TestCaseGen doküman-yükleme fonksiyonları yeniden kullanılır); kayıt hâlâ tek bir yoldan (mevcut `POST /knowledge/rules` ve `/knowledge/examples`) geçer.

**Tech Stack:** FastAPI + SQLAlchemy (SQLite), vanilla JS/HTML frontend (no build step, no JS test framework in this repo), Ollama (metin üretimi), Python stdlib `difflib`.

**Spec:** `docs/superpowers/specs/2026-09-02-knowledge-base-versioning-design.md`

## Global Constraints

- Başlık eşleştirmesi **tam, büyük/küçük harf duyarlı** string karşılaştırmasıdır (spec §4.2 notu) — normalize/fuzzy-match yok.
- Otomatik/zamanlanmış (cron) tetikleme YOK — her kayıt admin'in elle "Kaydet"ine bağlı (spec §2).
- Güncelleme sonrası arama havuzu (RAG) SADECE en güncel içeriği görür — eski chunk/embedding satırları silinir, asla iki versiyon aynı anda aranabilir olmaz (spec §4.3).
- LLM diff-özeti başarısız olursa kayıt işlemi ASLA engellenmez — sabit bir uyarı metni `diff_summary` olarak yazılır (spec §4.2, §6).
- `rule` türünde embedding alınamazsa hiçbir şey değişmez/commit edilmez (transaction bütünlüğü) — mevcut `503` davranışı korunur (spec §6).
- Orijinal yüklenen dosya (.docx/.xlsx) diske kaydedilmez, sadece çıkarılan düz metin saklanır (spec §2, mevcut TestCaseGen doküman yükleme deseniyle tutarlı).
- Yeni bağımlılık YOK — `difflib` Python stdlib'de zaten var.
- Kullanıcıya görünen metinler ve kod yorumları Türkçe (mevcut proje kuralı, `CLAUDE.md`).
- `docs/superpowers/plans` yazarken çözülen açık kararlar (spec §8): (1) `GET /knowledge/history/{id}` (tam içerik görüntüleme) bu plana DAHİL DEĞİL — sonraki bir iyileştirme. (2) Değişiklik Geçmişi sayfası `js/sidebar.js`'e eklenmiyor, sadece `admin-knowledge.html` ↔ `admin-knowledge-history.html` arası çapraz link ile erişiliyor.
- Bu repoda JS için otomatik test çalıştırıcı yok — frontend görevlerinde doğrulama adımı `node --check` (sözdizimi) + elle tarayıcı kontrol listesi şeklindedir; yeni bir test aracı kurulmaz (YAGNI, mevcut desen).

---

## Task 1: Veri modeli — `KnowledgeDocumentVersion`

**Files:**
- Modify: `backend/models/db_models.py` (dosya sonuna, mevcut `KnowledgeEntry` sınıfından sonra eklenir)
- Test: `backend/tests/test_knowledge_service.py`

**Interfaces:**
- Produces: `models.db_models.KnowledgeDocumentVersion` — kolonlar: `id`, `entry_type` (str), `title` (str), `full_content` (str), `is_current` (bool, default `True`), `diff_summary` (str|None), `created_by_user_id` (int|None), `created_at` (datetime).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_knowledge_service.py` dosyasının EN ÜSTÜNDEKİ importlara dokunma, sadece dosyanın SONUNA şu testi ekle:

```python
def test_knowledge_document_version_model_defaults(db):
    from models.db_models import KnowledgeDocumentVersion

    row = KnowledgeDocumentVersion(entry_type="rule", title="T", full_content="C")
    db.add(row)
    db.commit()
    db.refresh(row)

    assert row.is_current is True
    assert row.diff_summary is None
    assert row.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run (repo `backend/` dizininde, proje venv'i ile):
```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py::test_knowledge_document_version_model_defaults -v
```
Expected: FAIL — `ImportError: cannot import name 'KnowledgeDocumentVersion'`

- [ ] **Step 3: Write minimal implementation**

`backend/models/db_models.py` dosyasının SONUNA (mevcut `KnowledgeEntry` sınıfının bittiği yerden, dosyanın en altına) şunu ekle:

```python


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"

    id = Column(Integer, primary_key=True, index=True)
    entry_type = Column(String, index=True)   # "rule" | "example"
    title = Column(String, index=True)
    full_content = Column(Text)               # chunklanmamis tam metin (diff icin)
    is_current = Column(Boolean, default=True, index=True)
    diff_summary = Column(Text, nullable=True)  # None ise ilk kayit
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py::test_knowledge_document_version_model_defaults -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models/db_models.py backend/tests/test_knowledge_service.py
git commit -m "KnowledgeDocumentVersion modeli eklendi (bilgi tabani versiyon gecmisi)"
```

---

## Task 2: `testcasegen_service.build_diff_summary_prompt`

**Files:**
- Modify: `backend/services/testcasegen_service.py:487` (mevcut `build_document_title_extraction_prompt` fonksiyonundan hemen sonra, `build_testcase_prompt_from_document`'tan önce eklenir)
- Test: `backend/tests/test_knowledge_service.py`

**Interfaces:**
- Produces: `testcasegen_service.build_diff_summary_prompt(title: str, diff_text: str) -> str`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_knowledge_service.py` dosyasının sonuna ekle:

```python
def test_build_diff_summary_prompt_includes_title_and_diff_lines():
    from services import testcasegen_service

    prompt = testcasegen_service.build_diff_summary_prompt(
        "Sifre Kurali", "-eski minimum 8 karakter\n+yeni minimum 10 karakter"
    )

    assert "Sifre Kurali" in prompt
    assert "eski minimum 8 karakter" in prompt
    assert "yeni minimum 10 karakter" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py::test_build_diff_summary_prompt_includes_title_and_diff_lines -v
```
Expected: FAIL — `AttributeError: module 'services.testcasegen_service' has no attribute 'build_diff_summary_prompt'`

- [ ] **Step 3: Write minimal implementation**

`backend/services/testcasegen_service.py` içinde, `build_document_title_extraction_prompt` fonksiyonunun bittiği satırdan (dosyada satır 487, `'{"titles": [{"text": "...", "excerpt": "..."}]}'` ve kapanış parantezinden) hemen sonra, `build_testcase_prompt_from_document` fonksiyonundan ÖNCE şunu ekle:

```python


def build_diff_summary_prompt(title: str, diff_text: str) -> str:
    return (
        "Aşağıda bir bilgi tabanı kaydının eski ve yeni içeriği arasındaki satır bazlı "
        "fark (unified diff formatı) verildi. '-' ile başlayan satırlar kaldırıldı, "
        "'+' ile başlayan satırlar eklendi. Bu farkı okuyup Türkçe, 2-5 cümlelik, sade "
        "bir dille \"neler değişti\" özeti yaz. Satır numaralarından veya diff "
        "sembollerinden (@@, ---, +++) bahsetme, sadece anlamsal değişikliği anlat. "
        "Sadece özet metnini döndür, başka açıklama ekleme.\n\n"
        f"Kayıt başlığı: \"{title}\"\n\n"
        f"FARK:\n\"\"\"\n{diff_text}\n\"\"\"\n\n"
        "Özet:"
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py::test_build_diff_summary_prompt_includes_title_and_diff_lines -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_knowledge_service.py
git commit -m "testcasegen_service: bilgi tabani fark ozeti prompt'u eklendi"
```

---

## Task 3: `knowledge_service.save_versioned_entry`

**Files:**
- Modify: `backend/services/knowledge_service.py`
- Test: `backend/tests/test_knowledge_service.py`

**Interfaces:**
- Consumes: `models.db_models.KnowledgeDocumentVersion` (Task 1), `testcasegen_service.build_diff_summary_prompt(title, diff_text)` (Task 2), mevcut `ai_service.ollama_generate_text(prompt, model=None, timeout=300.0, num_ctx=...) -> str`, mevcut `knowledge_service.add_entry(db, entry_type, title, content, user_id=None, source_ref=None) -> int`, mevcut `knowledge_service.add_example(db, title, content, user_id=None) -> None`.
- Produces: `knowledge_service.KnowledgeEmbeddingUnavailable` (Exception alt sınıfı), `knowledge_service.save_versioned_entry(db, entry_type: str, title: str, content: str, user_id: int | None = None) -> dict` — döner: `{"is_update": bool, "diff_summary": str | None, "chunks": int}`. `entry_type="rule"` için embedding alınamazsa `KnowledgeEmbeddingUnavailable` fırlatır ve HİÇBİR ŞEY değiştirmez.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_knowledge_service.py` dosyasının sonuna ekle (dosyanın başında zaten `import asyncio`, `import numpy as np`, `import pytest`, `from models.db_models import KnowledgeEntry`, `from services import ai_service, knowledge_service as ks` var — bunlara dokunma):

```python
def test_save_versioned_entry_first_time_creates_version_and_search_rows(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 1}
    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).all()
    assert len(versions) == 1
    assert versions[0].is_current is True
    assert versions[0].diff_summary is None
    assert db.query(KnowledgeEntry).count() == 1


def test_save_versioned_entry_same_content_is_noop(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 0}
    from models.db_models import KnowledgeDocumentVersion
    assert db.query(KnowledgeDocumentVersion).count() == 1
    assert db.query(KnowledgeEntry).count() == 1


def test_save_versioned_entry_update_replaces_search_rows_and_summarizes_diff(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Icerik degisti."

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    assert result["is_update"] is True
    assert result["diff_summary"] == "Icerik degisti."

    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).order_by(KnowledgeDocumentVersion.id).all()
    assert len(versions) == 2
    assert versions[0].is_current is False
    assert versions[1].is_current is True
    assert versions[1].full_content == "yeni icerik"

    entries = db.query(KnowledgeEntry).all()
    assert len(entries) == 1
    assert entries[0].content == "yeni icerik"


def test_save_versioned_entry_llm_failure_falls_back_to_fixed_message(db, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def failing_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        raise RuntimeError("baglanti hatasi")

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_generate_text)

    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))
    result = asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    assert "otomatik özet çıkarılamadı" in result["diff_summary"]


def test_save_versioned_entry_rule_embedding_unavailable_raises_and_changes_nothing(db, monkeypatch):
    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)

    with pytest.raises(ks.KnowledgeEmbeddingUnavailable):
        asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "icerik", user_id=1))

    from models.db_models import KnowledgeDocumentVersion
    assert db.query(KnowledgeDocumentVersion).count() == 0
    assert db.query(KnowledgeEntry).count() == 0


def test_save_versioned_entry_update_embedding_failure_keeps_old_content(db, monkeypatch):
    async def ok_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", ok_embed)
    asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "eski icerik", user_id=1))

    async def failing_embed(text):
        return None

    monkeypatch.setattr(ai_service, "ollama_embed", failing_embed)
    with pytest.raises(ks.KnowledgeEmbeddingUnavailable):
        asyncio.run(ks.save_versioned_entry(db, "rule", "Kural", "yeni icerik", user_id=1))

    from models.db_models import KnowledgeDocumentVersion
    versions = db.query(KnowledgeDocumentVersion).all()
    assert len(versions) == 1
    assert versions[0].full_content == "eski icerik"
    assert versions[0].is_current is True
    entries = db.query(KnowledgeEntry).all()
    assert len(entries) == 1
    assert entries[0].content == "eski icerik"


def test_save_versioned_entry_example_no_embedding_needed(db, monkeypatch):
    result = asyncio.run(ks.save_versioned_entry(db, "example", "Ornek", "adimlar", user_id=1))

    assert result == {"is_update": False, "diff_summary": None, "chunks": 1}
    assert db.query(KnowledgeEntry).filter(KnowledgeEntry.entry_type == "example").count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -k save_versioned_entry -v
```
Expected: FAIL — `AttributeError: module 'services.knowledge_service' has no attribute 'save_versioned_entry'`

- [ ] **Step 3: Write minimal implementation**

`backend/services/knowledge_service.py` dosyasının EN ÜSTÜNDEKİ import bloğunu şuna göre güncelle (mevcut hâli: `import logging` / boş satır / `import numpy as np` / `from sqlalchemy.orm import Session` / boş satır / `from models.db_models import KnowledgeEntry` / `from services import ai_service`):

```python
import difflib
import logging

import numpy as np
from sqlalchemy.orm import Session

from models.db_models import KnowledgeEntry, KnowledgeDocumentVersion
from services import ai_service, testcasegen_service
```

Dosyanın EN SONUNA (mevcut `format_context_block` fonksiyonundan sonra) şunu ekle:

```python


class KnowledgeEmbeddingUnavailable(Exception):
    """rule turu icin embedding alinamadi — save_versioned_entry hicbir sey degistirmedi."""


async def save_versioned_entry(
    db: Session,
    entry_type: str,
    title: str,
    content: str,
    user_id: "int | None" = None,
) -> dict:
    """(entry_type, title) icin versiyon gecmisini gunceller.
    Ayni icerik tekrar gelirse hicbir sey yapmaz (no-op). Farkliysa eski/yeni
    icerik farkini LLM ile ozetler, arama havuzunu (KnowledgeEntry chunk/embedding)
    yeni icerikle yeniden olusturur, eski arama satirlarini siler ve yeni versiyon
    satirini yazar. entry_type="rule" icin embedding alinamazsa
    KnowledgeEmbeddingUnavailable firlatir — bu durumda HICBIR SEY degismez
    (eski versiyon/arama satirlari oldugu gibi kalir).
    Doner: {"is_update": bool, "diff_summary": str | None, "chunks": int}"""
    previous = (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.entry_type == entry_type,
            KnowledgeDocumentVersion.title == title,
            KnowledgeDocumentVersion.is_current == True,  # noqa: E712
        )
        .first()
    )

    if previous is not None and previous.full_content == content:
        return {"is_update": False, "diff_summary": None, "chunks": 0}

    diff_summary = None
    if previous is not None:
        diff_text = "\n".join(difflib.unified_diff(
            previous.full_content.splitlines(), content.splitlines(), lineterm="",
        ))
        try:
            prompt = testcasegen_service.build_diff_summary_prompt(title, diff_text)
            raw = await ai_service.ollama_generate_text(prompt)
            diff_summary = raw.strip() or None
        except Exception:
            diff_summary = (
                "İçerik değişti ama otomatik özet çıkarılamadı — Ollama'ya ulaşılamadı."
            )

    old_rows = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.entry_type == entry_type, KnowledgeEntry.title == title)
        .all()
    )
    old_ids = [r.id for r in old_rows]

    if entry_type == "rule":
        chunks = await add_entry(db, "rule", title, content, user_id=user_id)
        if chunks == 0:
            raise KnowledgeEmbeddingUnavailable()
    else:
        add_example(db, title, content, user_id=user_id)
        chunks = 1

    if old_ids:
        db.query(KnowledgeEntry).filter(KnowledgeEntry.id.in_(old_ids)).delete(synchronize_session=False)

    if previous is not None:
        previous.is_current = False

    db.add(KnowledgeDocumentVersion(
        entry_type=entry_type, title=title, full_content=content,
        is_current=True, diff_summary=diff_summary, created_by_user_id=user_id,
    ))
    db.commit()

    return {"is_update": previous is not None, "diff_summary": diff_summary, "chunks": chunks}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
venv/Scripts/python.exe -m pytest tests/test_knowledge_service.py -v
```
Expected: TÜM testler PASS (yeni eklenenler + Task 1/2'dekiler + dosyadaki mevcut testler).

- [ ] **Step 5: Commit**

```bash
git add backend/services/knowledge_service.py backend/tests/test_knowledge_service.py
git commit -m "knowledge_service: save_versioned_entry ile versiyon/fark takibi eklendi"
```

---

## Task 4: `POST /knowledge/extract-file` endpoint

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_knowledge.py`

**Interfaces:**
- Consumes: mevcut `svc.extract_text_from_docx(bytes) -> tuple[str, bool]`, `svc.extract_text_from_xlsx(bytes) -> tuple[str, bool]` (`testcasegen_service.py`).
- Produces: `POST /api/testcasegen/knowledge/extract-file` (admin, multipart `file`) → `{"text": str, "suggested_title": str}`. Desteklenmeyen uzantıda `400`. Metin çıkmazsa (boş dosya) `400`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_testcasegen_router_knowledge.py` dosyasının sonuna ekle (dosyanın başındaki importlara ve `_client_for` fonksiyonuna dokunma):

```python
def test_extract_file_txt_returns_text_and_suggested_title(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("sifre-kurali.txt", b"En az 8 karakter zorunlu.", "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "En az 8 karakter zorunlu."
    assert body["suggested_title"] == "sifre kurali"


def test_extract_file_rejects_unsupported_extension(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("kural.pdf", b"binary", "application/pdf")},
    )
    assert resp.status_code == 400


def test_extract_file_rejects_empty_text(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("bos.txt", b"   ", "text/plain")},
    )
    assert resp.status_code == 400


def test_extract_file_requires_admin(db_session):
    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.post(
        "/api/testcasegen/knowledge/extract-file",
        files={"file": ("kural.txt", b"icerik", "text/plain")},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -k extract_file -v
```
Expected: FAIL — `404 Not Found` (endpoint henüz yok).

- [ ] **Step 3: Write minimal implementation**

`backend/routers/testcasegen_router.py` içinde `_ALLOWED_DOC_EXTS = {".docx", ".xlsx"}` satırına (satır 171) DOKUNMA — o farklı bir endpoint için (`/sessions/{id}/document/upload`). Şu MEVCUT bloğu:

```python
# ── Bilgi Tabanı (Admin) ────────────────────────────────────────────────

class KnowledgeRuleIn(BaseModel):
    title: str
    content: str


@router.post("/knowledge/rules")
```

şuna değiştir (yeni sabit + yeni endpoint, `KnowledgeRuleIn` sınıfı aynen korunuyor):

```python
# ── Bilgi Tabanı (Admin) ────────────────────────────────────────────────

_KNOWLEDGE_FILE_EXTS = {".docx", ".xlsx", ".txt", ".md"}


@router.post("/knowledge/extract-file")
async def extract_knowledge_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in _KNOWLEDGE_FILE_EXTS:
        raise HTTPException(400, "Sadece .docx, .xlsx, .txt veya .md desteklenir")

    content = await file.read()
    try:
        if ext == ".docx":
            text, _truncated = svc.extract_text_from_docx(content)
        elif ext == ".xlsx":
            text, _truncated = svc.extract_text_from_xlsx(content)
        else:
            text = content.decode("utf-8", errors="replace")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not text.strip():
        raise HTTPException(400, "Dosyadan metin çıkarılamadı, dosya boş görünüyor")

    base_name = file.filename.rsplit(".", 1)[0] if file.filename and "." in file.filename else (file.filename or "")
    suggested_title = re.sub(r"[_-]+", " ", base_name).strip()

    return {"text": text, "suggested_title": suggested_title}


class KnowledgeRuleIn(BaseModel):
    title: str
    content: str


@router.post("/knowledge/rules")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -k extract_file -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_knowledge.py
git commit -m "testcasegen_router: bilgi tabani icin dosyadan metin cikarma endpoint'i eklendi"
```

---

## Task 5: `/knowledge/rules` ve `/knowledge/examples` POST — versiyonlu kayda geçiş

**Files:**
- Modify: `backend/routers/testcasegen_router.py:667-676` (`add_knowledge_rule`), `:724-735` (`add_knowledge_example`)
- Test: `backend/tests/test_testcasegen_router_knowledge.py`

**Interfaces:**
- Consumes: `knowledge_service.save_versioned_entry` (Task 3), `knowledge_service.KnowledgeEmbeddingUnavailable` (Task 3).
- Produces: `POST /knowledge/rules` ve `POST /knowledge/examples` response'una `is_update: bool` ve `diff_summary: str | None` alanları eklenir (mevcut alanlar korunur).

- [ ] **Step 1: Write the failing tests**

Önce mevcut testte KIRILACAK bir assertion var — `backend/tests/test_testcasegen_router_knowledge.py` içindeki `test_admin_can_add_list_and_delete_rule` testinde şu satırı:

```python
    assert add_resp.json() == {"status": "ok", "chunks": 1}
```

şuna değiştir:

```python
    assert add_resp.json() == {"status": "ok", "chunks": 1, "is_update": False, "diff_summary": None}
```

Sonra dosyanın sonuna yeni testler ekle:

```python
def test_add_rule_same_content_is_noop(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "Icerik"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "chunks": 0, "is_update": False, "diff_summary": None}
    assert len(client.get("/api/testcasegen/knowledge/rules").json()["rules"]) == 1


def test_add_rule_update_replaces_content_and_returns_diff_summary(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Icerik 'eski' den 'yeni' ye degistirildi."

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "eski icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "yeni icerik"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_update"] is True
    assert body["diff_summary"] == "Icerik 'eski' den 'yeni' ye degistirildi."

    rules = client.get("/api/testcasegen/knowledge/rules").json()["rules"]
    assert len(rules) == 1
    assert rules[0]["content"] == "yeni icerik"


def test_add_rule_update_llm_failure_uses_fallback_message(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1, 0.2]

    async def failing_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        raise RuntimeError("Ollama'ya ulasilamadi")

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)
    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "eski icerik"})
    resp = client.post("/api/testcasegen/knowledge/rules", json={"title": "Kural", "content": "yeni icerik"})

    assert resp.status_code == 200
    assert "otomatik özet çıkarılamadı" in resp.json()["diff_summary"]


def test_add_example_and_list(db_session):
    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    resp = client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "adimlar"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "is_update": False, "diff_summary": None}

    examples = client.get("/api/testcasegen/knowledge/examples").json()["examples"]
    assert len(examples) == 1
    assert examples[0]["content"] == "adimlar"


def test_add_example_update_returns_diff_summary(db_session, monkeypatch):
    async def fake_generate_text(prompt, model=None, timeout=300.0, num_ctx=None):
        return "Adim sirasi degisti."

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_generate_text)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "eski adimlar"})
    resp = client.post("/api/testcasegen/knowledge/examples", json={"title": "Ornek", "content": "yeni adimlar"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "is_update": True, "diff_summary": "Adim sirasi degisti."}
    examples = client.get("/api/testcasegen/knowledge/examples").json()["examples"]
    assert len(examples) == 1
    assert examples[0]["content"] == "yeni adimlar"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -v
```
Expected: Yukarıdaki yeni testler ve düzeltilen `test_admin_can_add_list_and_delete_rule` FAIL (response'ta `is_update`/`diff_summary` yok, no-op/update davranışı yok).

- [ ] **Step 3: Write minimal implementation**

`backend/routers/testcasegen_router.py` içindeki `add_knowledge_rule` fonksiyonunu (Task 4 sonrası hâlâ aynı yerde, `KnowledgeRuleIn` sınıfının hemen altında) şu MEVCUT hâlinden:

```python
@router.post("/knowledge/rules")
async def add_knowledge_rule(
    body: KnowledgeRuleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    added = await knowledge_service.add_entry(db, "rule", body.title, body.content, user_id=current_user.id)
    if added == 0:
        raise HTTPException(503, "Embedding modeli kullanılamıyor, kural kaydedilemedi")
    return {"status": "ok", "chunks": added}
```

şuna değiştir:

```python
@router.post("/knowledge/rules")
async def add_knowledge_rule(
    body: KnowledgeRuleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = await knowledge_service.save_versioned_entry(
            db, "rule", body.title, body.content, user_id=current_user.id
        )
    except knowledge_service.KnowledgeEmbeddingUnavailable:
        raise HTTPException(503, "Embedding modeli kullanılamıyor, kural kaydedilemedi")
    return {
        "status": "ok", "chunks": result["chunks"],
        "is_update": result["is_update"], "diff_summary": result["diff_summary"],
    }
```

`add_knowledge_example` fonksiyonunu şu MEVCUT hâlinden:

```python
@router.post("/knowledge/examples")
async def add_knowledge_example(
    body: KnowledgeExampleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(400, "Başlık ve içerik gerekli")
    knowledge_service.add_example(db, title, content, user_id=current_user.id)
    return {"status": "ok"}
```

şuna değiştir:

```python
@router.post("/knowledge/examples")
async def add_knowledge_example(
    body: KnowledgeExampleIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(400, "Başlık ve içerik gerekli")
    result = await knowledge_service.save_versioned_entry(
        db, "example", title, content, user_id=current_user.id
    )
    return {"status": "ok", "is_update": result["is_update"], "diff_summary": result["diff_summary"]}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -v
```
Expected: TÜM testler PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_knowledge.py
git commit -m "testcasegen_router: kural/ornek kaydi save_versioned_entry uzerinden geciyor, diff_summary donuyor"
```

---

## Task 6: `GET /knowledge/history` endpoint

**Files:**
- Modify: `backend/routers/testcasegen_router.py` (import satırı + `# ── Bilgi Tabanı Sohbet ──` başlığından önce, `knowledge_status` fonksiyonunun altına yeni endpoint)
- Test: `backend/tests/test_testcasegen_router_knowledge.py`

**Interfaces:**
- Consumes: `models.db_models.KnowledgeDocumentVersion` (Task 1).
- Produces: `GET /api/testcasegen/knowledge/history?entry_type=rule|example` (opsiyonel filtre, admin) → `{"versions": [{"id", "entry_type", "title", "is_current", "diff_summary", "created_by": str|None, "created_at"}, ...]}`, en yeniden eskiye sıralı.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_testcasegen_router_knowledge.py` dosyasının sonuna ekle:

```python
def test_knowledge_history_lists_versions_newest_first_with_filter(db_session, monkeypatch):
    async def fake_embed(text):
        return [0.1]

    monkeypatch.setattr(ai_service, "ollama_embed", fake_embed)

    admin = User(username="a", email="a@example.com", hashed_password="x", role="admin")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_for(db_session, admin)
    client.post("/api/testcasegen/knowledge/rules", json={"title": "R1", "content": "icerik"})
    client.post("/api/testcasegen/knowledge/examples", json={"title": "E1", "content": "adimlar"})

    all_versions = client.get("/api/testcasegen/knowledge/history").json()["versions"]
    assert len(all_versions) == 2
    assert all_versions[0]["title"] == "E1"  # en son eklenen once gelir

    rule_versions = client.get("/api/testcasegen/knowledge/history?entry_type=rule").json()["versions"]
    assert len(rule_versions) == 1
    assert rule_versions[0]["title"] == "R1"
    assert rule_versions[0]["created_by"] == "a"
    assert rule_versions[0]["is_current"] is True
    assert rule_versions[0]["diff_summary"] is None


def test_knowledge_history_requires_admin(db_session):
    user = User(username="u", email="u@example.com", hashed_password="x", role="user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client = _client_for(db_session, user)
    resp = client.get("/api/testcasegen/knowledge/history")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -k knowledge_history -v
```
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Write minimal implementation**

`backend/routers/testcasegen_router.py` satır 23'teki importu:

```python
from models.db_models import User, KnowledgeEntry
```

şuna değiştir:

```python
from models.db_models import User, KnowledgeEntry, KnowledgeDocumentVersion
```

`knowledge_status` fonksiyonunun (mevcut satır 773-776) hemen ALTINA, `# ── Bilgi Tabanı Sohbet ──` başlığından ÖNCE şunu ekle:

```python


@router.get("/knowledge/history")
async def knowledge_history(
    entry_type: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeDocumentVersion, User.username).outerjoin(
        User, KnowledgeDocumentVersion.created_by_user_id == User.id
    )
    if entry_type:
        q = q.filter(KnowledgeDocumentVersion.entry_type == entry_type)
    rows = q.order_by(KnowledgeDocumentVersion.created_at.desc()).all()
    return {"versions": [
        {
            "id": v.id, "entry_type": v.entry_type, "title": v.title,
            "is_current": v.is_current, "diff_summary": v.diff_summary,
            "created_by": username, "created_at": v.created_at.isoformat(),
        }
        for v, username in rows
    ]}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_knowledge.py -v
```
Expected: TÜM testler PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_knowledge.py
git commit -m "testcasegen_router: bilgi tabani degisiklik gecmisi listeleme endpoint'i eklendi"
```

---

## Task 7: Frontend — `admin-knowledge.html` dosya yükleme + fark bildirimi

**Files:**
- Modify: `backend/WebArayuz/admin-knowledge.html`

**Interfaces:**
- Consumes: `POST /api/testcasegen/knowledge/extract-file` (Task 4), `POST /knowledge/rules` / `/knowledge/examples` response'undaki `is_update`/`diff_summary` (Task 5), global `API_URL` ve `Auth.getToken()` (`js/app.js` — sayfa zaten `<script src="js/app.js">` yüklüyor).

- [ ] **Step 1: `<style>` bloğuna dosya yükleme + fark modalı stilleri ekle**

`backend/WebArayuz/admin-knowledge.html` içindeki `<style>` bloğunun SONUNA (mevcut son kural `.rule-modal-foot { ... }`'tan sonra, `</style>`'dan önce) ekle:

```css
.kb-drop-zone {
    border: 2px dashed var(--border-color); border-radius: 9px;
    padding: 12px 16px; text-align: center; cursor: pointer;
    transition: .15s; color: var(--text-muted); font-size: 0.82rem;
    margin-bottom: 14px;
}
.kb-drop-zone:hover, .kb-drop-zone.drag-over {
    border-color: var(--accent-primary); background: rgba(79,70,229,0.04); color: var(--accent-primary);
}
.kb-drop-zone input { display: none; }
.diff-modal-body { font-size: 0.9rem; line-height: 1.6; color: var(--text-primary); white-space: pre-wrap; }
```

- [ ] **Step 2: Header'a Değişiklik Geçmişi linki ekle**

Mevcut:
```html
            <div class="header-right"><button class="theme-toggle" onclick="Theme.toggle()">🌙</button></div>
```

şuna değiştir:
```html
            <div class="header-right">
                <a class="btn btn-secondary" href="admin-knowledge-history.html" style="text-decoration:none;">🕓 Değişiklik Geçmişi</a>
                <button class="theme-toggle" onclick="Theme.toggle()">🌙</button>
            </div>
```

- [ ] **Step 3: Modal'a dosya yükleme alanı ekle**

Mevcut:
```html
        <div class="rule-modal-body">
            <div class="fm-group">
                <label class="fm-label" id="fTitleLabel">Başlık *</label>
```

şuna değiştir:
```html
        <div class="rule-modal-body">
            <div class="kb-drop-zone" id="kbDropZone">
                <input type="file" id="kbFileInput" accept=".docx,.xlsx,.txt,.md">
                📁 Dosyadan doldur (.docx, .xlsx, .txt, .md) veya <strong>tıkla</strong>
            </div>
            <div class="fm-group">
                <label class="fm-label" id="fTitleLabel">Başlık *</label>
```

- [ ] **Step 4: `ruleModal` overlay'inin hemen ALTINA yeni bir "fark" modal'ı ekle**

Mevcut (dosyanın `<!-- ── Kural Modal ──...` bloğunu kapatan) şu satırdan:
```html
</div>

<script src="js/app.js"></script>
```

`</div>\n\n<script` arasına şu yeni bloğu ekle (yani mevcut kapanışı koru, sadece `<script` etiketinden önce yeni modal'ı ekle):
```html
</div>

<!-- ── Fark Bildirimi Modal ── -->
<div class="rule-modal-overlay" id="diffModal">
    <div class="rule-modal-box" style="width:min(480px,100%);">
        <div class="rule-modal-head">
            <div class="rule-modal-head-title">
                <span>🔄</span>
                <span id="diffModalTitle">Güncellendi</span>
            </div>
            <button class="rule-modal-close" onclick="closeDiffModal()">✕</button>
        </div>
        <div class="rule-modal-body">
            <div class="diff-modal-body" id="diffModalBody"></div>
        </div>
        <div class="rule-modal-foot">
            <button class="btn btn-primary" onclick="closeDiffModal()">Tamam</button>
        </div>
    </div>
</div>

<script src="js/app.js"></script>
```

- [ ] **Step 5: JS — dosya yükleme akışı ve fark bildirimi**

`<script>` bloğu içinde, `let mode = "rule";` satırından hemen sonra (mevcut `const MODES = {` tanımından ÖNCE) DOKUNMA — bunun yerine `esc(...)` fonksiyonunun (dosyanın en sonunda, `})();`'ten hemen önce) ÜSTÜNE şunu ekle:

```javascript
    // ── Dosyadan doldurma ─────────────────────────────────────────────────────
    const kbDropZone  = document.getElementById("kbDropZone");
    const kbFileInput = document.getElementById("kbFileInput");

    kbDropZone.addEventListener("click", () => kbFileInput.click());
    kbDropZone.addEventListener("dragover",  e => { e.preventDefault(); kbDropZone.classList.add("drag-over"); });
    kbDropZone.addEventListener("dragleave", () => kbDropZone.classList.remove("drag-over"));
    kbDropZone.addEventListener("drop", e => {
        e.preventDefault();
        kbDropZone.classList.remove("drag-over");
        const file = e.dataTransfer.files[0];
        if (file) uploadKnowledgeFile(file);
    });
    kbFileInput.addEventListener("change", e => {
        if (e.target.files[0]) { uploadKnowledgeFile(e.target.files[0]); e.target.value = ""; }
    });

    async function uploadKnowledgeFile(file) {
        const formData = new FormData();
        formData.append("file", file);
        try {
            const resp = await fetch(`${API_URL}/testcasegen/knowledge/extract-file`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                body: formData,
            });
            if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || "Dosya okunamadı"); }
            const data = await resp.json();
            const fTitle = document.getElementById("fTitle");
            if (!fTitle.value.trim()) fTitle.value = data.suggested_title || "";
            document.getElementById("fContent").value = data.text || "";
            Toast.success("Dosya içeriği metin alanına dolduruldu");
        } catch (e) {
            Toast.error(e.message);
        }
    }

    // ── Fark bildirimi ──────────────────────────────────────────────────────
    window.closeDiffModal = function () {
        document.getElementById("diffModal").classList.remove("active");
    };

    function showDiffModal(title, diffSummary) {
        document.getElementById("diffModalTitle").textContent = `"${title}" güncellendi`;
        document.getElementById("diffModalBody").textContent = diffSummary;
        document.getElementById("diffModal").classList.add("active");
    }

```

Sonra mevcut `saveRule()` fonksiyonunu şu MEVCUT hâlinden:

```javascript
    window.saveRule = async function () {
        const cfg = MODES[mode];
        const btn = document.getElementById("saveBtn");
        const title = document.getElementById("fTitle").value.trim();
        const content = document.getElementById("fContent").value.trim();

        if (!title)   { Toast.error("Başlık gerekli"); return; }
        if (!content) { Toast.error("İçerik gerekli"); return; }

        btn.disabled = true; btn.textContent = "Kaydediliyor...";
        try {
            const result = await API.post(cfg.addPath, { title, content });
            const chunkNote = result.chunks > 1 ? ` (${result.chunks} parçaya bölündü)` : "";
            Toast.success(`${cfg.savedMsg}${chunkNote}`);
            closeModal();
            loadRules();
        } catch (e) {
            Toast.error(e.message);
        } finally {
            btn.disabled = false; btn.textContent = "Kaydet";
        }
    };
```

şuna değiştir (tek eklenen satır: `if (result.is_update ...) showDiffModal(...)`):

```javascript
    window.saveRule = async function () {
        const cfg = MODES[mode];
        const btn = document.getElementById("saveBtn");
        const title = document.getElementById("fTitle").value.trim();
        const content = document.getElementById("fContent").value.trim();

        if (!title)   { Toast.error("Başlık gerekli"); return; }
        if (!content) { Toast.error("İçerik gerekli"); return; }

        btn.disabled = true; btn.textContent = "Kaydediliyor...";
        try {
            const result = await API.post(cfg.addPath, { title, content });
            const chunkNote = result.chunks > 1 ? ` (${result.chunks} parçaya bölündü)` : "";
            Toast.success(`${cfg.savedMsg}${chunkNote}`);
            closeModal();
            loadRules();
            if (result.is_update && result.diff_summary) showDiffModal(title, result.diff_summary);
        } catch (e) {
            Toast.error(e.message);
        } finally {
            btn.disabled = false; btn.textContent = "Kaydet";
        }
    };
```

- [ ] **Step 6: Sözdizimi kontrolü**

Bu repoda JS için otomatik test çalıştırıcı yok — `node --check` ile inline `<script>` bloğunun sözdizimini doğrula:

```bash
sed -n '/<script>/,/<\/script>/p' backend/WebArayuz/admin-knowledge.html | sed '1d;$d' > /tmp/admin_knowledge_check.js
node --check /tmp/admin_knowledge_check.js
```
Expected: çıktı vermeden biter (hata yoksa sessiz çıkar, exit code 0).

- [ ] **Step 7: Elle tarayıcı doğrulaması (checklist)**

Sunucuyu başlat (`python main.py`), admin ile giriş yap, `/ui/admin-knowledge.html` sayfasına git:
- [ ] "+ Yeni Kural" → modal açılınca dosya yükleme alanı görünüyor mu?
- [ ] Bir `.txt` dosyası sürükle-bırak veya tıkla-seç ile yükle → başlık (boşsa) ve içerik alanı otomatik doluyor mu?
- [ ] Aynı başlıkla farklı içerik gönder (Ollama çalışıyor olmalı) → kayıt sonrası "güncellendi — neler değişti?" modal'ı açılıyor mu?
- [ ] Aynı başlıkla AYNI içeriği tekrar gönder → hiçbir fark modalı açılmamalı, "Kural eklendi" toast'ı görünmeli.
- [ ] Header'daki "🕓 Değişiklik Geçmişi" linki tıklanabiliyor mu (Task 8 tamamlanana kadar 404 verecek, bu normal).

- [ ] **Step 8: Commit**

```bash
git add backend/WebArayuz/admin-knowledge.html
git commit -m "admin-knowledge.html: dosya yukleme ve fark bildirimi eklendi"
```

---

## Task 8: Frontend — `admin-knowledge-history.html` (yeni sayfa)

**Files:**
- Create: `backend/WebArayuz/admin-knowledge-history.html`

**Interfaces:**
- Consumes: `GET /api/testcasegen/knowledge/history?entry_type=...` (Task 6), global `API`/`Auth`/`Toast`/`Theme` nesneleri (`js/app.js`, `js/sidebar.js` — mevcut her admin sayfasında olduğu gibi).

- [ ] **Step 1: Dosyayı oluştur**

`backend/WebArayuz/admin-knowledge-history.html`:

```html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Değişiklik Geçmişi - Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
    <style>
        .hist-list { display:flex; flex-direction:column; gap:12px; }
        .hist-card { padding:16px 20px; }
        .hist-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; flex-wrap:wrap; }
        .hist-title { font-size:0.98rem; font-weight:600; }
        .hist-meta { font-size:0.78rem; color:var(--text-muted); }
        .hist-summary { font-size:0.85rem; color:var(--text-secondary); line-height:1.6; white-space:pre-wrap; }
        .hist-badge { font-size:0.7rem; padding:2px 8px; border-radius:999px; font-weight:600; }
        .hist-badge.new    { background:rgba(59,130,246,.12); color:#3b82f6; }
        .hist-badge.update { background:rgba(245,158,11,.12); color:#f59e0b; }
        .tab-btn.active { background:var(--accent-primary); color:#fff; border-color:var(--accent-primary); }
        .empty-state { text-align:center; padding:60px 20px; color:var(--text-muted); }
        .empty-icon  { font-size:3rem; opacity:.3; margin-bottom:12px; }
    </style>
</head>
<body>
<div class="app-container">
    <div id="sidebar-container"></div>
    <main class="main-content">
        <header class="header">
            <div class="header-left"><h1 class="page-title">🕓 Bilgi Tabanı Değişiklik Geçmişi</h1></div>
            <div class="header-right">
                <a class="btn btn-secondary" href="admin-knowledge.html" style="text-decoration:none;">🧠 Bilgi Tabanına Dön</a>
                <button class="theme-toggle" onclick="Theme.toggle()">🌙</button>
            </div>
        </header>

        <div class="page-content">
            <div class="tab-bar" style="display:flex;gap:8px;margin-bottom:22px;">
                <button class="btn btn-secondary tab-btn active" id="tabAllBtn" onclick="filterHistory(null)">Tümü</button>
                <button class="btn btn-secondary tab-btn" id="tabRuleBtn" onclick="filterHistory('rule')">🧠 Kurallar</button>
                <button class="btn btn-secondary tab-btn" id="tabExampleBtn" onclick="filterHistory('example')">📋 Örnekler</button>
            </div>
            <div class="hist-list" id="histList">
                <div class="empty-state"><div class="empty-icon">🕓</div><p>Yükleniyor...</p></div>
            </div>
        </div>
    </main>
</div>

<script src="js/app.js"></script>
<script src="js/sidebar.js"></script>
<script>
(function () {
    "use strict";
    let currentFilter = null;

    document.addEventListener("DOMContentLoaded", () => {
        if (!Auth.checkAuth()) return;
        if (!Auth.isAdmin()) { Toast.error("Yetkiniz yok"); location.href = "index.html"; return; }
        loadHistory();
    });

    window.filterHistory = function (entryType) {
        currentFilter = entryType;
        document.getElementById("tabAllBtn").classList.toggle("active", entryType === null);
        document.getElementById("tabRuleBtn").classList.toggle("active", entryType === "rule");
        document.getElementById("tabExampleBtn").classList.toggle("active", entryType === "example");
        loadHistory();
    };

    async function loadHistory() {
        const list = document.getElementById("histList");
        try {
            const qs = currentFilter ? `?entry_type=${currentFilter}` : "";
            const data = await API.get(`/testcasegen/knowledge/history${qs}`);
            renderHistory(data.versions || []);
        } catch (e) {
            list.innerHTML = `<div class="empty-state"><p style="color:var(--danger);">Yükleme hatası: ${e.message}</p></div>`;
        }
    }

    function renderHistory(versions) {
        const list = document.getElementById("histList");
        if (!versions.length) {
            list.innerHTML = `<div class="empty-state"><div class="empty-icon">🕓</div><p>Henüz kayıt yok</p></div>`;
            return;
        }
        list.innerHTML = versions.map(v => {
            const created = v.created_at ? new Date(v.created_at).toLocaleString("tr-TR") : "";
            const typeIcon = v.entry_type === "rule" ? "🧠" : "📋";
            const badge = v.diff_summary
                ? `<span class="hist-badge update">Güncellendi</span>`
                : `<span class="hist-badge new">İlk kayıt</span>`;
            const summary = v.diff_summary
                ? esc(v.diff_summary)
                : `<span style="opacity:.6;">İlk kez eklendi, karşılaştırılacak önceki versiyon yok.</span>`;
            return `
            <div class="card hist-card">
                <div class="hist-head">
                    <span class="hist-title">${typeIcon} ${esc(v.title)}</span>
                    ${badge}
                </div>
                <div class="hist-meta">${created}${v.created_by ? " · " + esc(v.created_by) : ""}${v.is_current ? "" : " · (eski versiyon)"}</div>
                <div class="hist-summary" style="margin-top:8px;">${summary}</div>
            </div>`;
        }).join("");
    }

    function esc(s) { if (!s) return ""; const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Sözdizimi kontrolü**

```bash
sed -n '/<script>/,/<\/script>/p' backend/WebArayuz/admin-knowledge-history.html | sed '1d;$d' > /tmp/admin_knowledge_history_check.js
node --check /tmp/admin_knowledge_history_check.js
```
Expected: hatasız (sessiz) çıkış.

- [ ] **Step 3: Elle tarayıcı doğrulaması (checklist)**

Sunucu çalışırken admin ile `/ui/admin-knowledge-history.html`'e git:
- [ ] Sayfa açılıyor, "Yükleniyor..." sonrası kayıtlar (Task 7'de eklenenler varsa) listeleniyor mu?
- [ ] "Kurallar" / "Örnekler" sekmeleri filtreleme yapıyor mu?
- [ ] Bir kayıt güncellendiğinde (diff_summary dolu) "Güncellendi" rozeti ve özet metni görünüyor mu?
- [ ] İlk kayıtlarda "İlk kayıt" rozeti ve açıklama metni görünüyor mu?
- [ ] "🧠 Bilgi Tabanına Dön" linki `admin-knowledge.html`'e gidiyor mu, oradaki "🕓 Değişiklik Geçmişi" linki de buraya geri dönüyor mu (çapraz link doğrulaması)?

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/admin-knowledge-history.html
git commit -m "admin-knowledge-history.html: bilgi tabani degisiklik gecmisi sayfasi eklendi"
```

---

## Son Doğrulama

Tüm task'lar bittikten sonra, backend'in tamamı için regresyon kontrolü:

```bash
cd backend
venv/Scripts/python.exe -m pytest tests/ -v
```
Expected: TÜM testler PASS (yeni eklenenler dahil, mevcut hiçbir test kırılmamış olmalı).
