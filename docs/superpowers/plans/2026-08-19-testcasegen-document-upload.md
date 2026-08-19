# TestCaseGen — Analiz Dökümanından Test Case Üretimi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TestCaseGen sayfasına, kullanıcının bir Word (.docx) veya Excel (.xlsx) analiz dökümanı yükleyip doğrudan bu dökümandan aday test case başlıkları ve adım adım test case'ler üretebilmesini sağlayan alternatif bir giriş yolu eklemek.

**Architecture:** Mevcut ekran-görüntüsü tabanlı akış (Ekran Toplama → Başlık Çıkarma → Önceliklendirme → Test Case Üretimi) korunur. Session'a paralel bir `document` alanı eklenir; `title` kaydına `source` (`"screens"` | `"document"`) ve `doc_excerpt` alanları eklenir. Önceliklendirme ve export adımları jenerik kalır (title kaynağından bağımsız çalışır); sadece Adım 1-2 (giriş + başlık çıkarma) ve Adım 4'ün LLM çağrısı (görsel yerine metin) title kaynağına göre dallanır.

**Tech Stack:** FastAPI (Python), `python-docx` (yeni bağımlılık), mevcut `openpyxl`, vanilla JS frontend (`testcasegen.html`), dosya tabanlı JSON session state.

**Referans spec:** `docs/superpowers/specs/2026-08-19-testcasegen-document-upload-design.md`

## Global Constraints

- Sadece `.docx` ve `.xlsx` desteklenir — PDF yok.
- Çıkarılan döküman metni 15.000 karakterle sınırlanır; chunking/map-reduce yok (kapsam dışı).
- Bir `title` kaydı ya `screens` ya da `document` kaynaklıdır — karışık kaynak yok.
- Dökümandan çıkarılan aday başlıklar otomatik listeye eklenmez; kullanıcı her birini elle "+ Başlık Ekle" ile onaylar (mevcut ekran akışıyla aynı UX).
- Yeni bağımlılık: `python-docx` (`backend/requirements.txt`).

---

### Task 1: Döküman metni çıkarma yardımcı fonksiyonları

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/services/testcasegen_service.py` (üstteki import bloğu + dosyanın sonuna yeni fonksiyonlar)
- Test: `backend/tests/test_testcasegen_document_extraction.py` (yeni)

**Interfaces:**
- Consumes: yok (bu görev yeni bir alt sistemin temeli)
- Produces:
  - `DOC_TEXT_CHAR_LIMIT: int = 15000`
  - `extract_text_from_docx(file_bytes: bytes) -> tuple[str, bool]` — `(metin, kesildi_mi)`. Geçersiz dosya için `ValueError` fırlatır.
  - `extract_text_from_xlsx(file_bytes: bytes) -> tuple[str, bool]` — aynı sözleşme.

- [ ] **Step 1: `requirements.txt`'e bağımlılığı ekle**

`backend/requirements.txt` dosyasındaki `# Excel` bölümünün altına ekle:

```
# Word (analiz dökümanı okuma)
python-docx>=1.1.0
```

- [ ] **Step 2: Kütüphaneyi venv'e kur**

Run: `cd backend && venv/Scripts/python.exe -m pip install python-docx>=1.1.0`
Expected: `Successfully installed python-docx-...`

- [ ] **Step 3: Başarısız testleri yaz**

`backend/tests/test_testcasegen_document_extraction.py` dosyasını oluştur:

```python
import io

import openpyxl
import pytest
from docx import Document as DocxDocument

from services import testcasegen_service as svc


def _make_docx_bytes(paragraphs, table_rows=None):
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table_rows:
        table = doc.add_table(rows=0, cols=len(table_rows[0]))
        for row in table_rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = val
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes(sheet_name, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_text_from_docx_reads_paragraphs_and_tables():
    data = _make_docx_bytes(
        ["Giris ekrani kullanici adi ve sifre alir.", "Onayla butonuna basilinca giris yapilir."],
        table_rows=[["Alan", "Zorunlu"], ["Kullanici Adi", "Evet"]],
    )
    text, truncated = svc.extract_text_from_docx(data)
    assert "Giris ekrani kullanici adi ve sifre alir." in text
    assert "Kullanici Adi | Evet" in text
    assert truncated is False


def test_extract_text_from_docx_truncates_long_text():
    data = _make_docx_bytes(["a" * 20000])
    text, truncated = svc.extract_text_from_docx(data)
    assert len(text) == svc.DOC_TEXT_CHAR_LIMIT
    assert truncated is True


def test_extract_text_from_docx_invalid_bytes_raises_value_error():
    with pytest.raises(ValueError):
        svc.extract_text_from_docx(b"not a docx file")


def test_extract_text_from_xlsx_reads_sheet_rows():
    data = _make_xlsx_bytes("Analiz", [["Ekran", "Aksiyon"], ["Login", "Kullanici giris yapar"]])
    text, truncated = svc.extract_text_from_xlsx(data)
    assert "Sayfa: Analiz" in text
    assert "Login | Kullanici giris yapar" in text
    assert truncated is False


def test_extract_text_from_xlsx_invalid_bytes_raises_value_error():
    with pytest.raises(ValueError):
        svc.extract_text_from_xlsx(b"not an xlsx file")
```

- [ ] **Step 4: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_document_extraction.py -v`
Expected: FAIL — `AttributeError: module 'services.testcasegen_service' has no attribute 'extract_text_from_docx'`

- [ ] **Step 5: `testcasegen_service.py`'ın import bloğuna `docx` ekle**

`backend/services/testcasegen_service.py` dosyasının en üstündeki import bloğunu (satır 9-17 civarı) şu şekilde güncelle:

```python
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from docx import Document as DocxDocument
from openpyxl.styles import Font
```

- [ ] **Step 6: Çıkarma fonksiyonlarını implemente et**

Dosyanın en sonuna (`build_export_workbook`'tan sonra) ekle:

```python
# ──────────────────────────────────────────────────────
# Analiz dökümanından metin çıkarma (Word/Excel)
# ──────────────────────────────────────────────────────

DOC_TEXT_CHAR_LIMIT = 15000


def _truncate_doc_text(text: str) -> tuple[str, bool]:
    if len(text) > DOC_TEXT_CHAR_LIMIT:
        return text[:DOC_TEXT_CHAR_LIMIT], True
    return text, False


def extract_text_from_docx(file_bytes: bytes) -> tuple[str, bool]:
    import io
    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"Word dosyası okunamadı: {e}")

    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return _truncate_doc_text("\n".join(parts))


def extract_text_from_xlsx(file_bytes: bytes) -> tuple[str, bool]:
    import io
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as e:
        raise ValueError(f"Excel dosyası okunamadı: {e}")

    parts = []
    for sheet in wb.worksheets:
        parts.append(f"Sayfa: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return _truncate_doc_text("\n".join(parts))
```

- [ ] **Step 7: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_document_extraction.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt backend/services/testcasegen_service.py backend/tests/test_testcasegen_document_extraction.py
git commit -m "TestCaseGen: Word/Excel analiz dokumanindan metin cikarma"
```

---

### Task 2: Döküman tabanlı prompt üreticileri

**Files:**
- Modify: `backend/services/testcasegen_service.py` (Ollama prompt üreticileri bölümüne ekleme)
- Modify: `backend/tests/test_testcasegen_prompts.py`

**Interfaces:**
- Consumes: yok
- Produces:
  - `build_document_title_extraction_prompt(doc_text: str) -> str`
  - `build_testcase_prompt_from_document(title_text: str, doc_excerpt: str) -> str`

- [ ] **Step 1: Başarısız testleri yaz**

`backend/tests/test_testcasegen_prompts.py`'nin en üstündeki import satırına ekle:

```python
from services.testcasegen_service import (
    build_title_extraction_prompt,
    build_rationale_prompt,
    build_testcase_prompt,
    build_document_title_extraction_prompt,
    build_testcase_prompt_from_document,
)
```

Dosyanın sonuna ekle:

```python
def test_document_title_extraction_prompt_requires_json_titles_schema():
    prompt = build_document_title_extraction_prompt("Bu dokuman giris ekranini anlatir.")
    assert "JSON" in prompt
    assert "titles" in prompt
    assert "excerpt" in prompt
    assert "Bu dokuman giris ekranini anlatir." in prompt


def test_testcase_prompt_from_document_includes_excerpt_and_rules():
    prompt = build_testcase_prompt_from_document("Odeme onaylanir", "Kullanici tutari girer ve onayla butonuna basar.")
    assert "Odeme onaylanir" in prompt
    assert "Kullanici tutari girer ve onayla butonuna basar." in prompt
    assert "pasif" in prompt.lower()
    assert "step_expected" in prompt
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_document_title_extraction_prompt'`

- [ ] **Step 3: Prompt fonksiyonlarını implemente et**

`backend/services/testcasegen_service.py`'de `build_testcase_prompt` fonksiyonunun hemen altına (Excel export bölümünden önce) ekle:

```python
def build_document_title_extraction_prompt(doc_text: str) -> str:
    return (
        "Sen bir mobil/web uygulama test analistisin. Aşağıda bir analiz/gereksinim dökümanının "
        "metni verildi. Bu dökümanı oku ve test edilebilecek 5-15 aday test case başlığı çıkar. "
        "Her başlık için, o başlığı dökümanın hangi kısmına dayandırdığını gösteren kısa bir alıntı "
        "(excerpt) ekle — alıntı dökümandan birebir veya yakın bir cümle/ifade olmalı.\n\n"
        f"DÖKÜMAN METNİ:\n\"\"\"\n{doc_text}\n\"\"\"\n\n"
        "SADECE aşağıdaki şemaya uyan JSON döndür, başka hiçbir metin ekleme, markdown code fence kullanma:\n"
        '{"titles": [{"text": "...", "excerpt": "..."}]}'
    )


def build_testcase_prompt_from_document(title_text: str, doc_excerpt: str) -> str:
    return (
        "Sen bir mobil uygulama test otomasyon uzmanısın. Aşağıdaki test case başlığı ve bu başlığın "
        "dayandığı analiz dökümanı alıntısı için adım adım test senaryosu üret.\n\n"
        f"Test case başlığı: \"{title_text}\"\n"
        f"Analiz dökümanı alıntısı: \"{doc_excerpt}\"\n\n"
        "NOT: Sana bu akışın ekran görüntüsü verilmedi, sadece yazılı döküman alıntısı var. "
        "Alıntıda somut bir buton/alan/menü adı geçiyorsa onu birebir kullan. Geçmiyorsa, "
        "gereksinimi karşılayacak makul bir arayüz etkileşimi öner ama uydurma isimleri kesin "
        "gerçekmiş gibi sunma — genel/açıklayıcı ifade kullan (örn. \"ilgili onay butonuna\").\n\n"
        "KESİN KURALLAR:\n"
        "1. Her Step Action pasif fiil çatısıyla yazılmalı (\"tıklanır\", \"açılır\", \"görülür\" — "
        "\"tıkla\", \"aç\" gibi EMİR KİPİ YASAK).\n"
        "2. Her Step Action'da TEK bir aksiyon olmalı (birden fazla tıklama/yazma tek satırda birleştirilmemeli).\n"
        "3. Dinamik/değişken değerler (güncel kur, hesaplanan tutar gibi) @ParamAdı notasyonuyla yazılmalı "
        "(örn. @güncel_kur, @hesaplanan_tutar).\n"
        "4. Her step'in boş olmayan bir Step Expected (beklenen sonuç) alanı olmalı.\n"
        "5. Yukarıdaki döküman alıntısını bir Step Action/Step Expected içine birebir YAPIŞTIRMA — "
        "bu sadece bağlam bilgisi, çıktıda asla birebir görünmemeli.\n\n"
        "SADECE aşağıdaki şemaya uyan JSON döndür, başka metin/markdown fence ekleme:\n"
        '{"steps": [{"step_action": "...", "step_expected": "..."}]}'
    )
```

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_prompts.py -v`
Expected: tüm testler (eski + yeni 2) PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_prompts.py
git commit -m "TestCaseGen: dokuman tabanli baslik/testcase prompt uretici fonksiyonlari"
```

---

### Task 3: Session veri modeli — `document` alanı ve title `source` alanı

**Files:**
- Modify: `backend/services/testcasegen_service.py` (`create_session`, `load_session`)
- Modify: `backend/tests/test_testcasegen_sessions.py`

**Interfaces:**
- Consumes: yok
- Produces:
  - `create_session(user_id)["document"] is None`
  - `load_session(...)["document"]` her zaman mevcut (eski session'larda `None`'a varsayılanır)
  - `load_session(...)["titles"][i]["source"]` her zaman mevcut (`"screens"` varsayılan), `["doc_excerpt"]` her zaman mevcut (`None` varsayılan)

- [ ] **Step 1: Başarısız testleri yaz**

`backend/tests/test_testcasegen_sessions.py`'nin sonuna ekle:

```python
def test_create_session_has_null_document():
    session = svc.create_session(user_id=1)
    assert session["document"] is None


def test_load_session_missing_document_key_defaults_to_none():
    session = svc.create_session(user_id=1)
    del session["document"]
    svc.save_session(1, session["id"], session)

    loaded = svc.load_session(1, session["id"])
    assert loaded["document"] is None


def test_load_session_adds_default_source_and_doc_excerpt_to_old_titles():
    session = svc.create_session(user_id=1)
    session["titles"] = [{"id": "t1", "screen_indices": [0], "text": "Eski title"}]
    svc.save_session(1, session["id"], session)

    loaded = svc.load_session(1, session["id"])
    assert loaded["titles"][0]["source"] == "screens"
    assert loaded["titles"][0]["doc_excerpt"] is None
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_sessions.py -v -k "document or source"`
Expected: FAIL — `KeyError: 'document'`

- [ ] **Step 3: `create_session`'ı güncelle**

`backend/services/testcasegen_service.py` içindeki `create_session` fonksiyonunda (satır 77-92 civarı) sözlüğe ekle:

```python
def create_session(user_id: int) -> dict:
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "user_id": user_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "current_step": 1,
        "screens": [],
        "titles": [],
        "testcases": [],
        "document": None,
    }
    _session_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    _screens_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    save_session(user_id, session_id, session)
    return session
```

- [ ] **Step 4: `load_session`'ı güncelle**

Aynı dosyada `load_session` fonksiyonunu (satır 111-120 civarı) şu şekilde güncelle:

```python
def load_session(user_id: int, session_id: str) -> dict:
    json_path = _session_json_path(user_id, session_id)
    if not json_path.exists():
        raise FileNotFoundError(f"Oturum bulunamadı: {session_id}")
    with open(json_path, "r", encoding="utf-8") as f:
        session = json.load(f)
    session.setdefault("document", None)
    for title in session.get("titles", []):
        if "screen_indices" not in title and "screen_index" in title:
            title["screen_indices"] = [title.pop("screen_index")]
        title.setdefault("source", "screens")
        title.setdefault("doc_excerpt", None)
    return session
```

- [ ] **Step 5: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_sessions.py -v`
Expected: tüm testler PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_sessions.py
git commit -m "TestCaseGen: session document alani ve title source geriye donuk uyumlulugu"
```

---

### Task 4: Router — döküman yükleme/silme/başlık çıkarma endpoint'leri

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_document.py` (yeni)

**Interfaces:**
- Consumes: `svc.extract_text_from_docx`, `svc.extract_text_from_xlsx`, `svc.DOC_TEXT_CHAR_LIMIT` (Task 1); `svc.build_document_title_extraction_prompt` (Task 2); `svc.extract_json_object`, `ai_service.ollama_generate_text` (mevcut)
- Produces:
  - `POST /api/testcasegen/sessions/{session_id}/document/upload` (multipart `file`) → session dict
  - `DELETE /api/testcasegen/sessions/{session_id}/document` → session dict
  - `POST /api/testcasegen/sessions/{session_id}/document/extract-titles` → session dict (`document.candidate_titles` dolu)

- [ ] **Step 1: Başarısız testleri yaz**

`backend/tests/test_testcasegen_router_document.py` dosyasını oluştur:

```python
import io

import openpyxl
import pytest
from docx import Document as DocxDocument
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, testcasegen_service as svc


class _FakeUser:
    id = 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    return TestClient(app)


def _docx_bytes(text):
    doc = DocxDocument()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_upload_document_rejects_unsupported_extension(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400


def test_upload_document_stores_extracted_text(client):
    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Giris ekrani kullanici adi ve sifre alir.")
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("analiz.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document"]["filename"] == "analiz.docx"
    assert "Giris ekrani kullanici adi ve sifre alir." in body["document"]["extracted_text"]
    assert body["document"]["truncated"] is False


def test_upload_document_empty_text_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("")
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("bos.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 400


def test_delete_document_clears_field(client):
    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Bir seyler yaz.")
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("a.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()
    resp = client.delete(f"/api/testcasegen/sessions/{session['id']}/document")
    assert resp.status_code == 200
    assert resp.json()["document"] is None


def test_extract_titles_from_document_without_upload_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/document/extract-titles")
    assert resp.status_code == 400


def test_extract_titles_from_document_populates_candidates(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"titles": [{"text": "Giris basarili senaryo", "excerpt": "Kullanici adi ve sifre girilir"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Kullanici adi ve sifre girilir, giris yapilir.")
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("a.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/document/extract-titles")
    assert resp.status_code == 200
    candidates = resp.json()["document"]["candidate_titles"]
    assert candidates == [{"text": "Giris basarili senaryo", "excerpt": "Kullanici adi ve sifre girilir"}]


def test_extract_titles_from_document_ollama_failure_returns_503(client, monkeypatch):
    async def failing_text(prompt, model=None, timeout=60.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_text)
    session = client.post("/api/testcasegen/sessions").json()
    data = _docx_bytes("Bir metin.")
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/document/upload",
        files={"file": ("a.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    ).json()

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/document/extract-titles")
    assert resp.status_code == 503
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v`
Expected: FAIL — `404 Not Found` (endpoint'ler henüz yok)

- [ ] **Step 3: Endpoint'leri implemente et**

`backend/routers/testcasegen_router.py` dosyasında `get_screen_image` endpoint'inin bittiği yere (`# ── Başlık çıkarma (Adım 2) ──` yorumundan hemen önce) ekle:

```python
# ── Analiz Dökümanı (Adım 1 alternatifi) ────────────────────────────────

_ALLOWED_DOC_EXTS = {".docx", ".xlsx"}


@router.post("/sessions/{session_id}/document/upload")
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
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
    return session


@router.delete("/sessions/{session_id}/document")
async def delete_document(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["document"] = None
    svc.save_session(current_user.id, session_id, session)
    return session


@router.post("/sessions/{session_id}/document/extract-titles")
async def extract_titles_from_document(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    document = session.get("document")
    if not document:
        raise HTTPException(400, "Önce bir analiz dökümanı yükleyin")

    prompt = svc.build_document_title_extraction_prompt(document["extracted_text"])
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

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_document.py
git commit -m "TestCaseGen: dokuman yukleme/silme/baslik cikarma endpoint'leri"
```

---

### Task 5: Router — `titles` ve `prioritize` endpoint'lerini döküman kaynaklı title'lar için genelleştir

**Files:**
- Modify: `backend/routers/testcasegen_router.py` (`TitleIn`, `add_title`, `prioritize`)
- Modify: `backend/tests/test_testcasegen_router_document.py`

**Interfaces:**
- Consumes: `session["document"]` (Task 3-4)
- Produces: `POST /sessions/{id}/titles` artık `doc_excerpt: str | None` alanı kabul eder; eklenen title'da `source` alanı doğru hesaplanır; `POST /sessions/{id}/prioritize` `screen_indices == []` olan title'larda hata vermez.

- [ ] **Step 1: Başarısız testleri yaz**

`backend/tests/test_testcasegen_router_document.py` dosyasının sonuna ekle:

```python
def test_add_title_with_doc_excerpt_sets_document_source(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"text": "Odeme akisi", "doc_excerpt": "Kullanici tutar girer, onaylar."},
    )
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["source"] == "document"
    assert title["doc_excerpt"] == "Kullanici tutar girer, onaylar."
    assert title["screen_indices"] == []


def test_add_title_without_screens_or_doc_excerpt_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"text": "Baslik"},
    )
    assert resp.status_code == 400


def test_prioritize_scores_document_sourced_title_without_crash(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "Gerekce metni."

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"text": "Odeme onaylanir", "doc_excerpt": "Kullanici odeme onaylar."},
    ).json()

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize")
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] in ("high", "medium", "low")
    assert title["score"] is not None
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v -k "doc_excerpt or prioritize_scores"`
Expected: FAIL — `screen_indices` alanı zorunlu olduğundan 422 (Pydantic validation error) veya `IndexError`

- [ ] **Step 3: `TitleIn` ve `add_title`'ı güncelle**

`backend/routers/testcasegen_router.py` içindeki `TitleIn` sınıfını ve `add_title` endpoint'ini (mevcut `screen_indices: list[int]` zorunlu alanlı hali) şu şekilde değiştir:

```python
class TitleIn(BaseModel):
    text: str
    screen_indices: list[int] = []
    doc_excerpt: Optional[str] = None


@router.post("/sessions/{session_id}/titles")
async def add_title(session_id: str, body: TitleIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if not body.screen_indices and not body.doc_excerpt:
        raise HTTPException(400, "Ekran veya döküman alıntısı belirtilmeli")
    source = "document" if body.doc_excerpt else "screens"
    session["titles"].append({
        "id": str(uuid.uuid4()),
        "source": source,
        "screen_indices": body.screen_indices,
        "doc_excerpt": body.doc_excerpt,
        "text": body.text,
        "score": None,
        "level": None,
        "level_source": None,
        "rationale": "",
    })
    svc.save_session(current_user.id, session_id, session)
    return session
```

- [ ] **Step 4: `prioritize` endpoint'inde derinlik hesaplamasını düzelt**

`prioritize` endpoint'i içindeki döngüde şu satırları:

```python
        indices = title["screen_indices"]
        combined_note = " ".join(
            screens_by_index[i]["user_note"] for i in indices if i in screens_by_index and screens_by_index[i].get("user_note")
        )
        score, level = svc.score_title(title["text"], combined_note, indices[-1])
```

şununla değiştir:

```python
        indices = title["screen_indices"]
        if title.get("source") == "document":
            combined_note = title.get("doc_excerpt") or ""
            depth_index = 0
        else:
            combined_note = " ".join(
                screens_by_index[i]["user_note"] for i in indices if i in screens_by_index and screens_by_index[i].get("user_note")
            )
            depth_index = indices[-1] if indices else 0
        score, level = svc.score_title(title["text"], combined_note, depth_index)
```

- [ ] **Step 5: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py tests/test_testcasegen_router_titles.py tests/test_testcasegen_router_priority.py -v`
Expected: tüm testler PASS (eski ekran-akışı testleri de dahil, geriye dönük uyumlu)

- [ ] **Step 6: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_document.py
git commit -m "TestCaseGen: titles ve prioritize endpoint'leri dokuman kaynakli title'lari destekliyor"
```

---

### Task 6: Router — `generate-testcases` döküman dallanması

**Files:**
- Modify: `backend/routers/testcasegen_router.py` (`generate_testcases`)
- Modify: `backend/tests/test_testcasegen_router_document.py`

**Interfaces:**
- Consumes: `svc.build_testcase_prompt_from_document` (Task 2), `title["source"]`/`title["doc_excerpt"]` (Task 5)
- Produces: `POST /sessions/{id}/generate-testcases` döküman kaynaklı title'lar için `ollama_generate_text` + `build_testcase_prompt_from_document` kullanır; ekran kaynaklı title'lar için davranış değişmez.

- [ ] **Step 1: Başarısız testi yaz**

`backend/tests/test_testcasegen_router_document.py` dosyasının sonuna ekle:

```python
def test_generate_testcases_for_document_title_uses_text_prompt_not_vision(client, monkeypatch):
    captured = {}

    async def fake_text(prompt, model=None, timeout=60.0):
        captured["prompt"] = prompt
        return '{"steps": [{"step_action": "X tıklanır", "step_expected": "Y görülür"}]}'

    async def fake_vision(prompt, images_b64, model=None, timeout=60.0):
        raise AssertionError("Dokuman kaynakli title icin vision cagrilmamali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)

    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"text": "Odeme onaylanir", "doc_excerpt": "Kullanici tutari girer ve onaylar."},
    ).json()
    title_id = session["titles"][0]["id"]

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 200
    testcases = resp.json()["testcases"]
    assert len(testcases) == 1
    assert "Kullanici tutari girer ve onaylar." in captured["prompt"]
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py -v -k generate_testcases_for_document`
Expected: FAIL — mevcut kod `screen_indices` boş olduğundan boş `screens` listesiyle `build_testcase_prompt` çağırır, alıntı prompt'ta yer almaz

- [ ] **Step 3: `generate_testcases`'ı dallandır**

`backend/routers/testcasegen_router.py` içindeki `generate_testcases` fonksiyonundaki döngü gövdesini (title bulunduktan sonraki kısmı) şu şekilde değiştir:

```python
    created = []
    for title_id in body.title_ids:
        title = titles_by_id.get(title_id)
        if not title:
            continue

        if title.get("source") == "document":
            prompt = svc.build_testcase_prompt_from_document(title["text"], title.get("doc_excerpt") or "")
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

            prompt = svc.build_testcase_prompt(title["text"], screens)
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

(Ekran dalındaki kod bir önceki oturumda eklenen vision/text dallanmasıyla birebir aynı — sadece `if title.get("source") == "document"` bloğu yeni.)

- [ ] **Step 4: Testleri tekrar çalıştır ve geçtiğini doğrula**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_testcasegen_router_document.py tests/test_testcasegen_router_generate.py -v`
Expected: tüm testler PASS

- [ ] **Step 5: Tüm testcasegen test paketini çalıştır**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/ -k testcasegen -v`
Expected: tüm testler PASS (bu noktada backend tarafı tamamlanmış olmalı)

- [ ] **Step 6: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_document.py
git commit -m "TestCaseGen: generate-testcases dokuman kaynakli title'lar icin text-only prompt kullaniyor"
```

---

### Task 7: Frontend — Adım 1 paneline döküman yükleme alanı

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html` (`renderStep1`)

**Interfaces:**
- Consumes: `POST /sessions/{id}/document/upload`, `DELETE /sessions/{id}/document` (Task 4)
- Produces: `renderDocUploadArea()`, `uploadDocument(file)`, `removeDocument()` — sonraki frontend görevleri `_session.document` alanının UI'da güncel tutulduğunu varsayar.

**Not:** Bu proje için JS birim test altyapısı yok (backend `pytest`, frontend elle test edilir). Bu yüzden bu görevde "test yaz/çalıştır" yerine elle doğrulama adımları var.

- [ ] **Step 1: `renderStep1()` fonksiyonuna döküman kartını ekle**

`backend/WebArayuz/testcasegen.html` içinde `renderStep1()` fonksiyonundaki (yaklaşık satır 359-402) panel HTML'ine, "Ekran Görüntüsü Yükle" kartından hemen sonra, "ADB ile Canlı Yakalama" kartından önce yeni bir kart ekle:

```html
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.upload}<h3>Analiz Dökümanı Yükle</h3></div>
                    <div id="docUploadArea"></div>
                </div>
```

Fonksiyonun sonunda, `renderScreenList();` çağrısının hemen altına ekle:

```javascript
            renderDocUploadArea();
```

- [ ] **Step 2: Döküman yükleme/silme yardımcı fonksiyonlarını ekle**

`uploadFiles` fonksiyonunun hemen altına ekle:

```javascript
        function renderDocUploadArea() {
            const area = document.getElementById("docUploadArea");
            if (!area) return;
            const doc = _session.document;
            if (doc) {
                area.innerHTML = `
                    <div class="tcg-doc-uploaded" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                        <span>${escapeHtml(doc.filename)}</span>
                        ${doc.truncated ? `<span class="badge badge-warning">Kısaltıldı (ilk 15.000 karakter)</span>` : ""}
                        <button class="tcg-btn" onclick="removeDocument()">${ICONS.trash} Kaldır</button>
                    </div>`;
                return;
            }
            area.innerHTML = `
                <div id="docDropzone" class="tcg-dropzone">
                    ${ICONS.upload}
                    <div class="tcg-dropzone-title">Word (.docx) veya Excel (.xlsx) dosyasını sürükleyin ya da tıklayıp seçin</div>
                    <input type="file" id="docFileInput" accept=".docx,.xlsx" style="display:none;">
                </div>`;
            const docDropzone = document.getElementById("docDropzone");
            const docFileInput = document.getElementById("docFileInput");
            docDropzone.onclick = () => docFileInput.click();
            docDropzone.ondragover = (e) => { e.preventDefault(); docDropzone.classList.add("dragover"); };
            docDropzone.ondragleave = () => { docDropzone.classList.remove("dragover"); };
            docDropzone.ondrop = async (e) => {
                e.preventDefault();
                docDropzone.classList.remove("dragover");
                if (e.dataTransfer.files[0]) await uploadDocument(e.dataTransfer.files[0]);
            };
            docFileInput.onchange = async (e) => {
                if (e.target.files[0]) await uploadDocument(e.target.files[0]);
                docFileInput.value = "";
            };
        }

        async function uploadDocument(file) {
            const formData = new FormData();
            formData.append("file", file);
            try {
                const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/document/upload`, {
                    method: "POST",
                    headers: { "Authorization": `Bearer ${Auth.getToken()}` },
                    body: formData,
                });
                if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || "Yükleme hatası"); }
                _session = await resp.json();
                renderDocUploadArea();
            } catch (e) {
                Toast.error(e.message);
            }
        }

        async function removeDocument() {
            try {
                _session = await API.delete(`/testcasegen/sessions/${_session.id}/document`);
                renderDocUploadArea();
            } catch (e) {
                Toast.error(e.message);
            }
        }
```

- [ ] **Step 3: Elle doğrula**

Run: `cd backend && venv/Scripts/python.exe main.py` (sunucuyu başlat), tarayıcıda `http://localhost:8000/ui/testcasegen.html` aç, yeni oturum başlat.
Expected: Adım 1'de "Analiz Dökümanı Yükle" kartı görünür; küçük bir `.docx` dosyası sürükle-bırak veya tıkla-seç ile yüklendiğinde dosya adı + "Kaldır" butonu görünür; "Kaldır"a basınca dropzone'a geri döner; `.pdf` gibi desteklenmeyen bir dosya seçilirse toast ile hata mesajı gösterilir (backend 400 döner).

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: Adim 1'e analiz dokumani yukleme alani eklendi"
```

---

### Task 8: Frontend — Adım 2 paneline dökümandan başlık çıkarma

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html` (`renderStep2`, `promoteCandidateTitles`)

**Interfaces:**
- Consumes: `POST /sessions/{id}/document/extract-titles`, `POST /sessions/{id}/titles` (`doc_excerpt` ile, Task 5-6), `_session.document` (Task 7)
- Produces: `_docCandidates`, `runExtractTitlesFromDocument()`, `renderDocTitlesResult()`, `editDocCandidateTitle(i, value)`, `removeDocCandidateTitle(i)` — genişletilmiş `promoteCandidateTitles()`

- [ ] **Step 1: `renderStep2()`'ye döküman kartını ekle**

`renderStep2()` fonksiyonunu (yaklaşık satır 599-615) şu şekilde güncelle:

```javascript
        function renderStep2() {
            const panel = document.getElementById("panel-2");
            const docCard = _session.document ? `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.sparkle}<h3>Dökümandan Başlık Çıkarma</h3></div>
                    <button class="tcg-btn primary" id="extractDocBtn" onclick="runExtractTitlesFromDocument()">${ICONS.sparkle} Dökümandan Başlıkları Çıkar</button>
                    <div id="docTitlesResult" style="margin-top:16px;"></div>
                </div>` : "";
            panel.innerHTML = `
                ${docCard}
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.sparkle}<h3>Başlık Çıkarma</h3></div>
                    <button class="tcg-btn primary" id="extractBtn" onclick="runExtractTitles()">${ICONS.sparkle} Başlıkları Çıkar</button>
                    <button class="tcg-btn" id="retryExtractBtn" style="display:none;" onclick="runExtractTitles()">${ICONS.retry} Tekrar Dene</button>
                    <div id="extractProgress" style="margin-top:14px;"></div>
                    <div id="titlesResult" style="margin-top:16px;"></div>
                </div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(1)">${ICONS.chevronLeft} Geri</button>
                    <button class="tcg-btn primary" onclick="goToStep(3)">Devam ${ICONS.chevronRight}</button>
                </div>
            `;
            renderTitlesResult();
            _docCandidates = ((_session.document && _session.document.candidate_titles) || []).map(c => ({ ...c }));
            renderDocTitlesResult();
        }

        let _docCandidates = [];

        async function runExtractTitlesFromDocument() {
            const btn = document.getElementById("extractDocBtn");
            setBtnBusy(btn, true, "Çıkarılıyor…");
            try {
                _session = await API.post(`/testcasegen/sessions/${_session.id}/document/extract-titles`);
                _docCandidates = (_session.document.candidate_titles || []).map(c => ({ ...c }));
                renderDocTitlesResult();
                Toast.success("Döküman başlıkları çıkarıldı");
            } catch (e) {
                Toast.error(e.message);
            } finally {
                setBtnBusy(btn, false);
            }
        }

        function renderDocTitlesResult() {
            const container = document.getElementById("docTitlesResult");
            if (!container) return;
            container.innerHTML = _docCandidates.length ? _docCandidates.map((c, i) => `
                <div class="tcg-title-chip">
                    <input type="text" value="${(c.text || "").replace(/"/g, '&quot;')}"
                           onchange="editDocCandidateTitle(${i}, this.value)">
                    <button onclick="removeDocCandidateTitle(${i})" title="Sil">${ICONS.trash}</button>
                </div>
                <div style="font-size:0.75rem; color:var(--text-muted); margin:2px 0 10px;">${escapeHtml(c.excerpt || "")}</div>
            `).join("") : `<p class="tcg-empty-hint">Henüz aday başlık yok — "Dökümandan Başlıkları Çıkar" ile üretin.</p>`;
        }

        function editDocCandidateTitle(index, value) {
            _docCandidates[index].text = value;
        }

        function removeDocCandidateTitle(index) {
            _docCandidates.splice(index, 1);
            renderDocTitlesResult();
        }
```

- [ ] **Step 2: `promoteCandidateTitles()`'ı döküman adaylarını da gönderecek şekilde genişlet**

`promoteCandidateTitles()` fonksiyonunun (yaklaşık satır 801-821) sonuna, mevcut `for (const group of groupScreensByFlow())` döngüsünden sonra ekle:

```javascript
            const existingDocKeys = new Set(
                _session.titles.filter(t => t.source === "document").map(t => `${t.doc_excerpt}:${t.text}`)
            );
            for (const c of _docCandidates) {
                const key = `${c.excerpt}:${c.text}`;
                if (existingDocKeys.has(key)) continue;
                const updated = await API.post(`/testcasegen/sessions/${_session.id}/titles`, {
                    text: c.text, doc_excerpt: c.excerpt,
                });
                _session.titles = updated.titles;
                existingDocKeys.add(key);
            }
```

- [ ] **Step 3: Elle doğrula**

Sunucu çalışırken tarayıcıda: Adım 1'de bir `.docx` yükle → Adım 2'ye geç → "Dökümandan Başlıkları Çıkar" butonuna bas → aday başlık kartları (metin + alıntı) görünmeli, her birinde düzenle/sil çalışmalı → Adım 3'e "Devam" ile geçmeden önce Adım 3'teki "Önceliklendir" butonuna basıldığında (bu `promoteCandidateTitles()`'ı tetikler) aday başlıkların gerçek `title` kaydına dönüştüğünü, kanban'da göründüğünü doğrula.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: Adim 2'ye dokumandan baslik cikarma UI'i eklendi"
```

---

### Task 9: Frontend — döküman kaynaklı title'lar için rozet

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html` (`renderKanban`)

**Interfaces:**
- Consumes: `title.source` (Task 5)
- Produces: yok (bu son görsel dokunuş)

- [ ] **Step 1: `renderKanban()`'daki kart HTML'ini güncelle**

`renderKanban()` fonksiyonu içindeki (yaklaşık satır 876-881) kart satırını:

```javascript
                        <div>${escapeHtml(t.text)} ${t.screen_indices.length > 1 ? `<span class="badge badge-primary">${t.screen_indices.length} ekran</span>` : ""}</div>
```

şununla değiştir:

```javascript
                        <div>${escapeHtml(t.text)} ${t.screen_indices.length > 1 ? `<span class="badge badge-primary">${t.screen_indices.length} ekran</span>` : ""}${t.source === "document" ? `<span class="badge badge-primary">📄 Döküman</span>` : ""}</div>
```

- [ ] **Step 2: Elle doğrula**

Adım 3'te (Önceliklendirme) döküman kaynaklı bir başlığın kartında "📄 Döküman" rozetinin göründüğünü, ekran kaynaklı başlıklarda görünmediğini doğrula.

- [ ] **Step 3: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: dokuman kaynakli basliklar icin kanban rozeti"
```

---

### Task 10: Tam regresyon + uçtan uca manuel duman testi

**Files:** yok (sadece doğrulama)

**Interfaces:** yok

- [ ] **Step 1: Tüm backend test paketini çalıştır**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tüm testler PASS, 0 failed

- [ ] **Step 2: Uçtan uca manuel senaryo**

Sunucu çalışırken (`python main.py`), tarayıcıda `testcasegen.html` üzerinden:
1. Yeni oturum başlat.
2. Adım 1'de bir `.docx` analiz dökümanı yükle (gerçek bir ekran görüntüsü yüklemeden).
3. Adım 2'de "Dökümandan Başlıkları Çıkar" — en az bir aday başlık + alıntı görünmeli.
4. Bir adayı düzenle, birini sil, en az bir tanesini bırak.
5. Adım 3'e geç, "Önceliklendir" — başlık kanban'da "📄 Döküman" rozetiyle görünmeli, skor/seviye atanmalı.
6. Adım 4'e geç, başlığı seç, "Test Case Oluştur" — adım adım test case üretilmeli (pasif çatı, boş olmayan expected).
7. Test case'i Excel'e aktar — indirilen dosya açılabilmeli, satırlar doğru sırada olmalı.

Expected: Hiçbir adımda konsol hatası/500 yanıtı olmamalı; üretilen adımlar döküman alıntısındaki somut ifadelerle tutarlı olmalı.

- [ ] **Step 3: Ekran-tabanlı akışın regresyona uğramadığını doğrula**

Aynı sunucuda, döküman yüklemeden klasik ekran-görüntüsü akışını (Adım 1 ekran yükle → Adım 2 başlık çıkar → Adım 3 önceliklendir → Adım 4 üret → export) baştan sona çalıştır.
Expected: Önceki oturumlarda çalışan davranış birebir korunmuş olmalı.
