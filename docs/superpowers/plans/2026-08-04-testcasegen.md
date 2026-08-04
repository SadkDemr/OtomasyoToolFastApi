# TestCaseGen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "TestCaseGen" page that turns mobile-app screenshots into prioritized, ADO-formatted test cases via a 4-step wizard (collect screens → extract titles with Ollama vision → rule-based prioritize → generate + validate steps), with `.xlsx` export.

**Architecture:** New router (`testcasegen_router.py`) + service (`testcasegen_service.py`) pair, following the existing router/service split used by every other module. State is file-based (JSON + PNGs under `backend/testcasegen_data/{user_id}/{session_id}/`), no DB. Ollama access goes through two new shared helpers added to `ai_service.py`. The frontend is a single-file SPA (`testcasegen.html`) matching `ai-generator.html`'s design tokens and workflow-stepper component; the live-device panel re-implements the same WebSocket protocol `emulator.html` already speaks to `/api/emulator/{device_id}/stream` (no backend changes to the emulator module).

**Tech Stack:** FastAPI, httpx (existing dep), openpyxl (existing dep), pytest (new dev dep), vanilla JS/HTML/CSS (existing frontend convention, no build step, no JS test framework in this repo).

## Global Constraints

- Backend code, comments, and all UI copy are in Turkish, matching the rest of the platform (CLAUDE.md: "Language: UI, comments, and scenario steps are primarily in Turkish").
- All new endpoints require `Depends(get_current_user)` (multi-user isolation — CLAUDE.md convention); state is scoped by `current_user.id`.
- Ollama model/URL always come from `ai_service.get_ollama_config()` (`ai_config.json` > env, default `gemma3:4b` / `http://localhost:11434/api/generate`) — never hardcode a different default.
- No database changes, no new SQLAlchemy models/migrations (explicit spec scope exclusion).
- No automatic push to Azure DevOps — export is a downloadable `.xlsx` file only.
- Frontend has no test runner in this repo; frontend tasks are verified manually (start the server, use the page), consistent with every other page in `WebArayuz/`.
- Priority `level` values are always one of the literal strings `"high" | "medium" | "low"`.

---

## Task 1: Shared Ollama helpers in `ai_service.py`

**Files:**
- Modify: `backend/services/ai_service.py`
- Test: `backend/tests/test_ai_service_ollama.py`

**Interfaces:**
- Produces: `async def ollama_generate_text(prompt: str, model: str | None = None, timeout: float = 60.0) -> str`, `async def ollama_generate_vision(prompt: str, images_b64: list[str], model: str | None = None, timeout: float = 90.0) -> str`. Both raise on transport/HTTP failure (caller wraps in try/except and converts to HTTP 503).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/__init__.py` (empty file) if it doesn't exist, then create `backend/tests/test_ai_service_ollama.py`:

```python
import asyncio
import json
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
        self.sent_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        self.sent_json = json
        return _FakeResponse({"response": "merhaba"})


def test_ollama_generate_text_returns_response_field(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    result = asyncio.run(ai_service.ollama_generate_text("bir prompt"))
    assert result == "merhaba"


def test_ollama_generate_text_uses_configured_model(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse({"response": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(ai_service, "get_ollama_config", lambda: {
        "url": "http://localhost:11434/api/generate", "model": "gemma3:4b",
    })
    asyncio.run(ai_service.ollama_generate_text("prompt"))
    assert captured["json"]["model"] == "gemma3:4b"
    assert captured["json"]["prompt"] == "prompt"
    assert captured["json"]["stream"] is False
    assert "images" not in captured["json"]


def test_ollama_generate_vision_sends_images(monkeypatch):
    captured = {}

    class RecordingClient(_FakeAsyncClient):
        async def post(self, url, json):
            captured["json"] = json
            return _FakeResponse({"response": "gorsel yaniti"})

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    result = asyncio.run(ai_service.ollama_generate_vision("prompt", ["YmFzZTY0"]))
    assert result == "gorsel yaniti"
    assert captured["json"]["images"] == ["YmFzZTY0"]


def test_ollama_generate_text_propagates_connection_error(monkeypatch):
    class FailingClient(_FakeAsyncClient):
        async def post(self, url, json):
            raise httpx.ConnectError("baglanti yok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(ai_service.ollama_generate_text("prompt"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ai_service_ollama.py -v`
Expected: FAIL — `AttributeError: module 'services.ai_service' has no attribute 'ollama_generate_text'` (or `httpx` not imported yet).

- [ ] **Step 3: Add `httpx` import and the two helpers to `ai_service.py`**

Add near the top of `backend/services/ai_service.py` (after the existing `import` block, e.g. after line 13 `from typing import Optional, List`):

```python
import httpx
```

Add at the end of the file, after `generate_scenario_variants`:

```python
# ──────────────────────────────────────────────────────
# Ollama yardımcıları (paylaşılan — TestCaseGen ve benzeri modüller için)
# ──────────────────────────────────────────────────────

async def _ollama_post(payload: dict, timeout: float) -> str:
    cfg = get_ollama_config()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(cfg["url"], json={**payload, "model": payload.get("model") or cfg["model"]})
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()


async def ollama_generate_text(prompt: str, model: Optional[str] = None, timeout: float = 60.0) -> str:
    """Ollama'ya salt metin isteği gönderir, 'response' alanını döndürür."""
    return await _ollama_post({"model": model, "prompt": prompt, "stream": False}, timeout)


async def ollama_generate_vision(prompt: str, images_b64: List[str], model: Optional[str] = None, timeout: float = 90.0) -> str:
    """Ollama'ya görüntü(ler) + metin isteği gönderir (vision-capable model gerekir)."""
    return await _ollama_post({"model": model, "prompt": prompt, "images": images_b64, "stream": False}, timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ai_service_ollama.py -v`
Expected: 4 passed.

- [ ] **Step 5: Add `pytest` to requirements and commit**

Add to `backend/requirements.txt` (anywhere in the file, e.g. after the `httpx>=0.24.0` line):

```
pytest>=7.4.0
```

```bash
git add backend/services/ai_service.py backend/tests/__init__.py backend/tests/test_ai_service_ollama.py backend/requirements.txt
git commit -m "TestCaseGen: paylasilan Ollama helper'lari (ollama_generate_text/vision) ai_service.py'a eklendi"
```

---

## Task 2: JSON extraction helpers in `testcasegen_service.py`

**Files:**
- Create: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_json.py`

**Interfaces:**
- Produces: `def clean_json_text(text: str) -> str`, `def extract_json_object(text: str) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_json.py`:

```python
from services.testcasegen_service import clean_json_text, extract_json_object


def test_clean_json_text_strips_markdown_fence_with_lang():
    raw = "```json\n{\"a\": 1}\n```"
    assert clean_json_text(raw) == '{"a": 1}'


def test_clean_json_text_strips_plain_fence():
    raw = "```\n{\"a\": 1}\n```"
    assert clean_json_text(raw) == '{"a": 1}'


def test_clean_json_text_passthrough_when_no_fence():
    raw = '{"a": 1}'
    assert clean_json_text(raw) == '{"a": 1}'


def test_extract_json_object_parses_clean_json():
    result = extract_json_object('{"screen_titles": [{"screen_index": 0}]}')
    assert result == {"screen_titles": [{"screen_index": 0}]}


def test_extract_json_object_parses_fenced_json_with_surrounding_text():
    raw = 'Iste sonuc:\n```json\n{"screen_titles": []}\n```\nTesekkurler.'
    result = extract_json_object(raw)
    assert result == {"screen_titles": []}


def test_extract_json_object_returns_none_on_invalid_json():
    assert extract_json_object("bu bir JSON degil") is None


def test_extract_json_object_returns_none_on_empty_string():
    assert extract_json_object("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_json.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.testcasegen_service'`.

- [ ] **Step 3: Create `testcasegen_service.py` with the JSON helpers**

Create `backend/services/testcasegen_service.py`:

```python
"""
TestCaseGen Service
--------------------
Ekran görüntülerinden test case başlığı çıkarma, kural tabanlı
önceliklendirme, adım doğrulama ve ADO formatlı Excel export.
Veritabanı YOK — state dosya tabanlı (bkz. session_* fonksiyonları).
"""

import json
import re
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────
# JSON temizleme / parse
# ──────────────────────────────────────────────────────

def clean_json_text(text: str) -> str:
    """Markdown code fence'leri (```json ... ``` veya ``` ... ```) temizler."""
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> Optional[dict]:
    """LLM çıktısından ilk JSON nesnesini çıkarır. Parse edilemezse None döner."""
    if not text:
        return None
    cleaned = clean_json_text(text)
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = cleaned[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_json.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_json.py
git commit -m "TestCaseGen: LLM JSON cikti temizleme/parse helper'lari"
```

---

## Task 3: Session file storage (create/list/load/save/delete, screens CRUD)

**Files:**
- Modify: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_sessions.py`

**Interfaces:**
- Consumes: nothing new (pure file I/O).
- Produces:
  - `DATA_DIR: Path` (module-level, monkeypatched in tests)
  - `def create_session(user_id: int) -> dict`
  - `def list_sessions(user_id: int) -> list[dict]`
  - `def load_session(user_id: int, session_id: str) -> dict` (raises `FileNotFoundError`)
  - `def save_session(user_id: int, session_id: str, session: dict) -> None`
  - `def delete_session(user_id: int, session_id: str) -> None`
  - `def screen_image_path(user_id: int, session_id: str, index: int, ext: str) -> Path`
  - `def add_screen(user_id: int, session_id: str, image_bytes: bytes, ext: str = ".png", note: str = "") -> dict` (returns updated session)
  - `def reorder_screens(user_id: int, session_id: str, order: list[int]) -> dict`
  - `def update_screen_note(user_id: int, session_id: str, index: int, note: str) -> dict`
  - `def delete_screen(user_id: int, session_id: str, index: int) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_sessions.py`:

```python
import pytest

from services import testcasegen_service as svc


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    yield tmp_path


def test_create_session_returns_empty_session_with_id():
    session = svc.create_session(user_id=1)
    assert session["user_id"] == 1
    assert session["current_step"] == 1
    assert session["screens"] == []
    assert session["titles"] == []
    assert session["testcases"] == []
    assert "id" in session and len(session["id"]) > 0


def test_create_session_persists_to_disk():
    session = svc.create_session(user_id=1)
    loaded = svc.load_session(user_id=1, session_id=session["id"])
    assert loaded["id"] == session["id"]


def test_load_session_missing_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        svc.load_session(user_id=1, session_id="does-not-exist")


def test_list_sessions_returns_only_that_users_sessions():
    s1 = svc.create_session(user_id=1)
    svc.create_session(user_id=2)
    sessions = svc.list_sessions(user_id=1)
    assert [s["id"] for s in sessions] == [s1["id"]]


def test_delete_session_removes_it():
    session = svc.create_session(user_id=1)
    svc.delete_session(user_id=1, session_id=session["id"])
    with pytest.raises(FileNotFoundError):
        svc.load_session(user_id=1, session_id=session["id"])


def test_add_screen_appends_with_incrementing_index():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"fake-png-bytes-1", ext=".png", note="ilk ekran")
    session = svc.add_screen(1, session["id"], b"fake-png-bytes-2", ext=".png")
    assert [s["index"] for s in session["screens"]] == [0, 1]
    assert session["screens"][0]["user_note"] == "ilk ekran"
    img_path = svc.screen_image_path(1, session["id"], 0, ".png")
    assert img_path.read_bytes() == b"fake-png-bytes-1"


def test_reorder_screens_changes_order_and_reindexes():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="A")
    session = svc.add_screen(1, session["id"], b"b", note="B")
    session = svc.add_screen(1, session["id"], b"c", note="C")
    session = svc.reorder_screens(1, session["id"], order=[2, 0, 1])
    assert [s["user_note"] for s in session["screens"]] == ["C", "A", "B"]
    assert [s["index"] for s in session["screens"]] == [0, 1, 2]


def test_update_screen_note_changes_note_only():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="eski not")
    session = svc.update_screen_note(1, session["id"], index=0, note="yeni not")
    assert session["screens"][0]["user_note"] == "yeni not"


def test_delete_screen_removes_and_reindexes():
    session = svc.create_session(user_id=1)
    session = svc.add_screen(1, session["id"], b"a", note="A")
    session = svc.add_screen(1, session["id"], b"b", note="B")
    session = svc.delete_screen(1, session["id"], index=0)
    assert len(session["screens"]) == 1
    assert session["screens"][0]["user_note"] == "B"
    assert session["screens"][0]["index"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_sessions.py -v`
Expected: FAIL — `AttributeError: module 'services.testcasegen_service' has no attribute 'DATA_DIR'`.

- [ ] **Step 3: Add session/screen storage functions to `testcasegen_service.py`**

Add near the top of `backend/services/testcasegen_service.py` (after the existing imports), and the functions after the JSON-helpers section:

```python
import uuid
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "testcasegen_data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_dir(user_id: int, session_id: str) -> Path:
    return DATA_DIR / str(user_id) / session_id


def _session_json_path(user_id: int, session_id: str) -> Path:
    return _session_dir(user_id, session_id) / "session.json"


def _screens_dir(user_id: int, session_id: str) -> Path:
    return _session_dir(user_id, session_id) / "screenshots"


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
    }
    _session_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    _screens_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    save_session(user_id, session_id, session)
    return session


def list_sessions(user_id: int) -> list:
    base = DATA_DIR / str(user_id)
    if not base.exists():
        return []
    sessions = []
    for entry in sorted(base.iterdir()):
        json_path = entry / "session.json"
        if json_path.exists():
            try:
                sessions.append(load_session(user_id, entry.name))
            except (FileNotFoundError, json.JSONDecodeError):
                continue
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions


def load_session(user_id: int, session_id: str) -> dict:
    json_path = _session_json_path(user_id, session_id)
    if not json_path.exists():
        raise FileNotFoundError(f"Oturum bulunamadı: {session_id}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(user_id: int, session_id: str, session: dict) -> None:
    session["updated_at"] = _now_iso()
    json_path = _session_json_path(user_id, session_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def delete_session(user_id: int, session_id: str) -> None:
    import shutil
    d = _session_dir(user_id, session_id)
    if d.exists():
        shutil.rmtree(d)


def screen_image_path(user_id: int, session_id: str, index: int, ext: str = ".png") -> Path:
    return _screens_dir(user_id, session_id) / f"{index}{ext}"


def add_screen(user_id: int, session_id: str, image_bytes: bytes, ext: str = ".png", note: str = "") -> dict:
    session = load_session(user_id, session_id)
    index = len(session["screens"])
    _screens_dir(user_id, session_id).mkdir(parents=True, exist_ok=True)
    screen_image_path(user_id, session_id, index, ext).write_bytes(image_bytes)
    session["screens"].append({
        "index": index,
        "image_ext": ext,
        "user_note": note,
        "candidate_titles": [],
        "screen_summary": "",
        "parse_error": False,
    })
    save_session(user_id, session_id, session)
    return session


def _reindex_and_rename_screens(user_id: int, session_id: str, session: dict) -> None:
    """Ekranlar yer değiştirdikten sonra dosya adlarını da yeni index'e göre yeniden adlandırır."""
    tmp_paths = []
    for new_idx, screen in enumerate(session["screens"]):
        old_path = screen_image_path(user_id, session_id, screen["index"], screen["image_ext"])
        tmp_path = old_path.with_suffix(old_path.suffix + f".tmp{new_idx}")
        old_path.rename(tmp_path)
        tmp_paths.append((tmp_path, new_idx))
    for tmp_path, new_idx in tmp_paths:
        screen = session["screens"][new_idx]
        final_path = screen_image_path(user_id, session_id, new_idx, screen["image_ext"])
        tmp_path.rename(final_path)
        screen["index"] = new_idx


def reorder_screens(user_id: int, session_id: str, order: list) -> dict:
    session = load_session(user_id, session_id)
    if sorted(order) != list(range(len(session["screens"]))):
        raise ValueError("Geçersiz sıralama: her index tam olarak bir kez geçmeli")
    session["screens"] = [session["screens"][i] for i in order]
    _reindex_and_rename_screens(user_id, session_id, session)
    save_session(user_id, session_id, session)
    return session


def update_screen_note(user_id: int, session_id: str, index: int, note: str) -> dict:
    session = load_session(user_id, session_id)
    session["screens"][index]["user_note"] = note
    save_session(user_id, session_id, session)
    return session


def delete_screen(user_id: int, session_id: str, index: int) -> dict:
    session = load_session(user_id, session_id)
    screen = session["screens"][index]
    screen_image_path(user_id, session_id, index, screen["image_ext"]).unlink(missing_ok=True)
    del session["screens"][index]
    _reindex_and_rename_screens(user_id, session_id, session)
    save_session(user_id, session_id, session)
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_sessions.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_sessions.py
git commit -m "TestCaseGen: dosya tabanli oturum/ekran depolama (create/list/load/save/delete + screens CRUD)"
```

---

## Task 4: Rule-based prioritization scoring engine

**Files:**
- Modify: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_scoring.py`

**Interfaces:**
- Produces: `WEIGHTS: dict`, `THRESHOLD_HIGH: float`, `THRESHOLD_MEDIUM: float`, `def score_title(text: str, screen_note: str, screen_index: int) -> tuple[float, str]` (returns `(score, level)`, `level` is `"high"|"medium"|"low"`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_scoring.py`:

```python
from services.testcasegen_service import score_title


def test_transaction_screen_scores_high():
    score, level = score_title("Tutar girilip onaylanır", "", screen_index=0)
    assert level == "high"


def test_info_only_screen_scores_low():
    score, level = score_title("Hakkımızda sayfası görüntülenir", "", screen_index=0)
    assert level == "low"


def test_negative_potential_raises_score_to_at_least_medium():
    score, level = score_title("Zorunlu alan doğrulaması yapılır", "", screen_index=0)
    assert level in ("medium", "high")


def test_depth_penalty_lowers_score_for_later_screens():
    score_early, _ = score_title("Tutar girilip onaylanır", "", screen_index=0)
    score_late, _ = score_title("Tutar girilip onaylanır", "", screen_index=10)
    assert score_late < score_early


def test_screen_note_contributes_to_scoring():
    score_with_note, _ = score_title("Ekran açılır", "tutar onaylanır", screen_index=0)
    score_without_note, _ = score_title("Ekran açılır", "", screen_index=0)
    assert score_with_note > score_without_note


def test_score_is_rounded_to_two_decimals():
    score, _ = score_title("Herhangi bir ekran", "", screen_index=0)
    assert score == round(score, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_scoring.py -v`
Expected: FAIL — `ImportError: cannot import name 'score_title'`.

- [ ] **Step 3: Add scoring engine to `testcasegen_service.py`**

Add after the session/screen storage section:

```python
# ──────────────────────────────────────────────────────
# Kural tabanlı önceliklendirme (LLM karar vermez, sadece skor üzerinden gerekçe alır)
# ──────────────────────────────────────────────────────

WEIGHTS = {
    "transaction": 3.0,        # form/tutar girişi/onay butonu içeren ekran
    "info_only": -1.0,         # salt bilgi gösterimi
    "negative_potential": 1.5, # validasyon gerektiren input alanı → hata senaryosu riski
    "depth_penalty": 0.3,      # ana akıştan her adım uzaklaştıkça düşen ağırlık
}
THRESHOLD_HIGH = 3.0
THRESHOLD_MEDIUM = 1.0

TRANSACTION_KEYWORDS = [
    "onayla", "öde", "ödeme", "gönder", "kaydet", "tutar", "miktar",
    "transfer", "satın al", "işlem yap", "onaylanır", "gönderilir",
]
INFO_KEYWORDS = [
    "hakkımızda", "sıkça sorulan", "sss", "bilgilendirme", "yardım",
    "iletişim", "kullanım koşulları", "gizlilik",
]
NEGATIVE_KEYWORDS = [
    "doğrulama", "zorunlu alan", "hatalı", "geçersiz", "input", "şifre",
    "gir", "girilir", "validasyon",
]


def score_title(text: str, screen_note: str, screen_index: int) -> tuple:
    haystack = f"{text} {screen_note}".lower()
    score = 0.0
    if any(k in haystack for k in TRANSACTION_KEYWORDS):
        score += WEIGHTS["transaction"]
    if any(k in haystack for k in INFO_KEYWORDS):
        score += WEIGHTS["info_only"]
    if any(k in haystack for k in NEGATIVE_KEYWORDS):
        score += WEIGHTS["negative_potential"]
    score -= WEIGHTS["depth_penalty"] * screen_index

    if score >= THRESHOLD_HIGH:
        level = "high"
    elif score >= THRESHOLD_MEDIUM:
        level = "medium"
    else:
        level = "low"
    return round(score, 2), level
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_scoring.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_scoring.py
git commit -m "TestCaseGen: kural tabanli onceliklendirme skorlama motoru"
```

---

## Task 5: Step validator (4 kesin kural)

**Files:**
- Modify: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_validator.py`

**Interfaces:**
- Produces: `def validate_steps(steps: list[dict]) -> list[dict]` — each input step is `{"step_action": str, "step_expected": str}`; each output step is the same dict plus `"violations": [{"rule": str, "message": str}]` (empty list if none).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_validator.py`:

```python
from services.testcasegen_service import validate_steps


def test_valid_step_has_no_violations():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": "Onay ekranı açılır"}]
    result = validate_steps(steps)
    assert result[0]["violations"] == []


def test_imperative_mood_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıkla', "step_expected": "Onay ekranı açılır"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "imperative_mood" in rules


def test_passive_mood_synonyms_are_not_flagged():
    for action in ['"Kaydet" tıklanır', "Form doldurulur", "Sayfa açılır", "Metin yazılır"]:
        result = validate_steps([{"step_action": action, "step_expected": "Sonuç görülür"}])
        rules = [v["rule"] for v in result[0]["violations"]]
        assert "imperative_mood" not in rules, f"'{action}' yanlış işaretlendi"


def test_missing_at_notation_for_variable_is_flagged():
    steps = [{"step_action": "Güncel kur alanı kontrol edilir", "step_expected": "Kur görüntülenir"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "missing_variable_notation" in rules


def test_at_notation_present_is_not_flagged():
    steps = [{"step_action": "@güncel_kur alanı kontrol edilir", "step_expected": "Kur görüntülenir"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "missing_variable_notation" not in rules


def test_multiple_actions_in_one_step_is_flagged():
    steps = [{"step_action": '"Ad" alanına yazılır ve "Devam" tıklanır', "step_expected": "Sonraki ekran açılır"}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "multiple_actions" in rules


def test_empty_step_expected_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": ""}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "empty_expected" in rules


def test_whitespace_only_step_expected_is_flagged():
    steps = [{"step_action": '"Devam" butonuna tıklanır', "step_expected": "   "}]
    result = validate_steps(steps)
    rules = [v["rule"] for v in result[0]["violations"]]
    assert "empty_expected" in rules


def test_validate_steps_preserves_original_fields():
    steps = [{"step_action": "X", "step_expected": "Y"}]
    result = validate_steps(steps)
    assert result[0]["step_action"] == "X"
    assert result[0]["step_expected"] == "Y"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_validator.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_steps'`.

- [ ] **Step 3: Add validator to `testcasegen_service.py`**

Add after the scoring section:

```python
# ──────────────────────────────────────────────────────
# Test case adım validator'ü (4 kesin kural)
# ──────────────────────────────────────────────────────

_IMPERATIVE_PATTERNS = [
    r'\btıkla\b', r'\btıklayınız\b', r'\baç\b', r'\byaz\b', r'\bgir\b',
    r'\bgiriniz\b', r'\bseç\b', r'\bseçiniz\b', r'\bonayla\b', r'\bonaylayınız\b',
    r'\bbas\b', r'\bbasınız\b', r'\bkaydet\b', r'\bdoldur\b', r'\bdolduruniz\b',
    r'\bkapat\b', r'\bsil\b', r'\bgönder\b', r'\bgönderiniz\b',
]

_VARIABLE_KEYWORDS = ["kur", "tutar", "bakiye", "hesaplanan", "miktar", "oran", "komisyon", "vade"]

_ACTION_VERB_PATTERN = re.compile(
    r'\b(tıklanır|açılır|yazılır|girilir|seçilir|onaylanır|basılır|kaydedilir|gönderilir|doldurulur)\b'
)


def _check_imperative(step_action: str) -> Optional[str]:
    # Tirnak icindeki UI eleman adlari (ör. "Kaydet" buton etiketi) haric tutulur —
    # aksi halde birçok yaygin buton etiketi (Kaydet/Onayla/Gönder/Sil/Kapat) emir
    # kipiyle ayni kelime oldugu için yanlis pozitif üretirdi.
    unquoted = re.sub(r'"[^"]*"', '', step_action)
    lowered = unquoted.lower()
    for pattern in _IMPERATIVE_PATTERNS:
        if re.search(pattern, lowered):
            return "Emir kipi tespit edildi — pasif çatı kullanılmalı (örn. 'tıklanır', 'açılır')"
    return None


def _check_variable_notation(step_action: str) -> Optional[str]:
    lowered = step_action.lower()
    at_tokens = re.findall(r'@\w+', lowered)
    for keyword in _VARIABLE_KEYWORDS:
        match = re.search(rf'\b{keyword}\w*\b', lowered)
        if not match:
            continue
        word = match.group(0)
        if any(keyword in tok for tok in at_tokens):
            continue
        return f"'{keyword}' değişken gibi görünüyor ama @ notasyonu kullanılmamış (örn. @{keyword})"
    return None


def _check_multiple_actions(step_action: str) -> Optional[str]:
    lowered = step_action.lower()
    if ' ve ' not in lowered:
        return None
    if len(_ACTION_VERB_PATTERN.findall(lowered)) >= 2:
        return 'Step Action birden fazla aksiyon içeriyor gibi görünüyor (" ve " ile birleştirilmiş)'
    return None


def _check_empty_expected(step_expected: str) -> Optional[str]:
    if not step_expected or not step_expected.strip():
        return "Step Expected boş bırakılamaz"
    return None


def validate_steps(steps: list) -> list:
    checks = [
        ("imperative_mood", lambda s: _check_imperative(s["step_action"])),
        ("missing_variable_notation", lambda s: _check_variable_notation(s["step_action"])),
        ("multiple_actions", lambda s: _check_multiple_actions(s["step_action"])),
        ("empty_expected", lambda s: _check_empty_expected(s["step_expected"])),
    ]
    result = []
    for step in steps:
        violations = []
        for rule, check in checks:
            message = check(step)
            if message:
                violations.append({"rule": rule, "message": message})
        result.append({**step, "violations": violations})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_validator.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_validator.py
git commit -m "TestCaseGen: adim validator (emir kipi, @ notasyonu, coklu aksiyon, bos expected)"
```

---

## Task 6: Prompt builders

**Files:**
- Modify: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_prompts.py`

**Interfaces:**
- Produces:
  - `def build_title_extraction_prompt(screen_note: str, prev_note: str, prev_summary: str) -> str`
  - `def build_rationale_prompt(title_text: str, level: str, score: float) -> str`
  - `def build_testcase_prompt(title_text: str, screen_summary: str, screen_note: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_prompts.py`:

```python
from services.testcasegen_service import (
    build_title_extraction_prompt,
    build_rationale_prompt,
    build_testcase_prompt,
)


def test_title_extraction_prompt_requires_json_only():
    prompt = build_title_extraction_prompt("", "", "")
    assert "JSON" in prompt
    assert "screen_titles" in prompt
    assert "candidate_titles" in prompt
    assert "screen_summary" in prompt


def test_title_extraction_prompt_includes_previous_screen_context():
    prompt = build_title_extraction_prompt("bu ekran onay ekranı", "önceki not", "önceki özet")
    assert "önceki not" in prompt
    assert "önceki özet" in prompt
    assert "bu ekran onay ekranı" in prompt


def test_rationale_prompt_asks_for_explanation_not_decision():
    prompt = build_rationale_prompt("Ödeme onaylanır", "high", 4.5)
    assert "gerekçe" in prompt.lower()
    assert "Ödeme onaylanır" in prompt
    assert "high" in prompt


def test_testcase_prompt_includes_all_four_rules():
    prompt = build_testcase_prompt("Ödeme onaylanır", "Ekranda tutar ve onay butonu var", "not yok")
    assert "pasif" in prompt.lower()
    assert "@Param" in prompt or "@" in prompt
    assert "Step Expected" in prompt
    assert "Ödeme onaylanır" in prompt


def test_testcase_prompt_requires_json_steps_schema():
    prompt = build_testcase_prompt("Baslik", "ozet", "not")
    assert "steps" in prompt
    assert "step_action" in prompt
    assert "step_expected" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_prompts.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_title_extraction_prompt'`.

- [ ] **Step 3: Add prompt builders to `testcasegen_service.py`**

Add after the validator section:

```python
# ──────────────────────────────────────────────────────
# Ollama prompt üreticileri
# ──────────────────────────────────────────────────────

def build_title_extraction_prompt(screen_note: str, prev_note: str, prev_summary: str) -> str:
    context = ""
    if prev_note or prev_summary:
        context = (
            f"\nBir önceki ekranın notu: \"{prev_note}\"\n"
            f"Bir önceki ekranın özeti: \"{prev_summary}\"\n"
            "Bu bağlamı akış bütünlüğünü korumak için kullan.\n"
        )
    note_line = f"\nKullanıcının bu ekran için notu: \"{screen_note}\"\n" if screen_note else ""
    return (
        "Sen bir mobil uygulama test analistisin. Sana verilen ekran görüntüsünü incele.\n"
        f"{context}{note_line}\n"
        "Bu ekrandan test edilebilecek 2-5 aday test case başlığı çıkar ve ekranın kısa bir özetini yaz.\n\n"
        "SADECE aşağıdaki şemaya uyan JSON döndür, başka hiçbir metin ekleme, markdown code fence kullanma:\n"
        '{"screen_titles": [{"screen_index": 0, "candidate_titles": ["...", "..."], "screen_summary": "..."}]}'
    )


def build_rationale_prompt(title_text: str, level: str, score: float) -> str:
    return (
        "Aşağıdaki test case başlığına, kural tabanlı bir motor tarafından zaten "
        f"'{level}' önceliği ve {score} skoru atandı. Karar değiştirme, sadece bu "
        "skoru 1-2 cümlelik kısa bir gerekçeye çevir (Türkçe, test analistine hitaben):\n\n"
        f"Başlık: \"{title_text}\"\n"
        f"Öncelik: {level}\n"
        f"Skor: {score}\n\n"
        "Yalnızca gerekçe cümlesini döndür, başka açıklama ekleme."
    )


def build_testcase_prompt(title_text: str, screen_summary: str, screen_note: str) -> str:
    return (
        "Sen bir mobil uygulama test otomasyon uzmanısın. Aşağıdaki test case başlığı için "
        "adım adım test senaryosu üret.\n\n"
        f"Test case başlığı: \"{title_text}\"\n"
        f"Ekran özeti: \"{screen_summary}\"\n"
        f"Kullanıcı notu: \"{screen_note}\"\n\n"
        "KESİN KURALLAR:\n"
        "1. Her Step Action pasif fiil çatısıyla yazılmalı (\"tıklanır\", \"açılır\", \"görülür\" — "
        "\"tıkla\", \"aç\" gibi EMİR KİPİ YASAK).\n"
        "2. Her Step Action'da TEK bir aksiyon olmalı (birden fazla tıklama/yazma tek satırda birleştirilmemeli).\n"
        "3. Dinamik/değişken değerler (güncel kur, hesaplanan tutar gibi) @ParamAdı notasyonuyla yazılmalı "
        "(örn. @güncel_kur, @hesaplanan_tutar).\n"
        "4. Her step'in boş olmayan bir Step Expected (beklenen sonuç) alanı olmalı.\n\n"
        "SADECE aşağıdaki şemaya uyan JSON döndür, başka metin/markdown fence ekleme:\n"
        '{"steps": [{"step_action": "...", "step_expected": "..."}]}'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_prompts.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_prompts.py
git commit -m "TestCaseGen: Ollama prompt ureticileri (baslik cikarma, gerekce, test case)"
```

---

## Task 7: Export workbook builder (openpyxl, ADO format)

**Files:**
- Modify: `backend/services/testcasegen_service.py`
- Test: `backend/tests/test_testcasegen_export.py`

**Interfaces:**
- Produces: `def build_export_workbook(testcases: list[dict], titles_by_id: dict) -> openpyxl.Workbook`. `testcases` items are `{"id": str, "title_id": str, "steps": [{"step_action": str, "step_expected": str, ...}]}`. `titles_by_id` maps `title_id -> {"text": str, ...}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_testcasegen_export.py`:

```python
from services.testcasegen_service import build_export_workbook


def _sample_testcases():
    titles_by_id = {"t1": {"text": "Ödeme onaylanır"}}
    testcases = [{
        "id": "tc1",
        "title_id": "t1",
        "steps": [
            {"step_action": '"Devam" butonuna tıklanır', "step_expected": "Onay ekranı açılır"},
            {"step_action": '"Onayla" butonuna tıklanır', "step_expected": "İşlem tamamlanır"},
        ],
    }]
    return testcases, titles_by_id


def test_export_header_row():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    header = [cell.value for cell in ws[1]]
    assert header == [
        "ID", "Work Item Type", "Title", "Test Step",
        "Step Action", "Step Expected", "Area Path", "Assigned To", "State",
    ]
    assert ws[1][0].font.bold is True


def test_export_title_row_has_title_and_type_only():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    title_row = [cell.value for cell in ws[2]]
    assert title_row[1] == "Test Case"
    assert title_row[2] == "Ödeme onaylanır"
    assert title_row[3] is None  # Test Step boş
    assert title_row[4] is None  # Step Action boş


def test_export_step_rows_have_step_fields_only():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    step1_row = [cell.value for cell in ws[3]]
    assert step1_row[2] is None  # Title boş
    assert step1_row[3] == 1     # Test Step sıra no
    assert step1_row[4] == '"Devam" butonuna tıklanır'
    assert step1_row[5] == "Onay ekranı açılır"

    step2_row = [cell.value for cell in ws[4]]
    assert step2_row[3] == 2


def test_export_uses_arial_font():
    testcases, titles_by_id = _sample_testcases()
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    assert ws[3][4].font.name == "Arial"


def test_export_multiple_testcases_appended_sequentially():
    titles_by_id = {"t1": {"text": "Başlık 1"}, "t2": {"text": "Başlık 2"}}
    testcases = [
        {"id": "tc1", "title_id": "t1", "steps": [{"step_action": "A", "step_expected": "B"}]},
        {"id": "tc2", "title_id": "t2", "steps": [{"step_action": "C", "step_expected": "D"}]},
    ]
    wb = build_export_workbook(testcases, titles_by_id)
    ws = wb.active
    # satir1=header, satir2=tc1 baslik, satir3=tc1 step, satir4=tc2 baslik, satir5=tc2 step
    assert ws[4][2].value == "Başlık 2"
    assert ws[5][4].value == "C"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_testcasegen_export.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_export_workbook'`.

- [ ] **Step 3: Add export builder to `testcasegen_service.py`**

Add `import openpyxl` and `from openpyxl.styles import Font` near the top imports, and add this function at the end of the file:

```python
def build_export_workbook(testcases: list, titles_by_id: dict):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test Cases"

    headers = ["ID", "Work Item Type", "Title", "Test Step", "Step Action",
               "Step Expected", "Area Path", "Assigned To", "State"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(name="Arial", bold=True)

    widths = [8, 16, 40, 10, 55, 45, 20, 20, 12]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    for tc in testcases:
        title_text = titles_by_id.get(tc["title_id"], {}).get("text", "")
        ws.append([None, "Test Case", title_text, None, None, None, None, None, None])
        for i, step in enumerate(tc["steps"], start=1):
            ws.append([None, None, None, i, step.get("step_action", ""),
                       step.get("step_expected", ""), None, None, None])

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if cell.font.name != "Arial" or not cell.font.bold:
                cell.font = Font(name="Arial", bold=False)

    return wb
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_testcasegen_export.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/testcasegen_service.py backend/tests/test_testcasegen_export.py
git commit -m "TestCaseGen: ADO formatinda xlsx export builder (openpyxl)"
```

---

## Task 8: Router — sessions & screens endpoints (Step 1)

**Files:**
- Create: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_screens.py`

**Interfaces:**
- Consumes: `testcasegen_service.create_session/list_sessions/load_session/delete_session/add_screen/reorder_screens/update_screen_note/delete_screen` (Task 3), `routers.auth.get_current_user`.
- Produces: `router = APIRouter(prefix="/api/testcasegen", tags=["testcasegen"])` with endpoints below, importable as `from routers.testcasegen_router import router as testcasegen_router`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_router_screens.py`:

```python
import base64
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import testcasegen_service as svc


class _FakeUser:
    id = 1
    username = "tester"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    return TestClient(app)


def test_create_and_get_session(client):
    resp = client.post("/api/testcasegen/sessions")
    assert resp.status_code == 200
    session = resp.json()
    assert session["screens"] == []

    resp2 = client.get(f"/api/testcasegen/sessions/{session['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == session["id"]


def test_get_missing_session_returns_404(client):
    resp = client.get("/api/testcasegen/sessions/does-not-exist")
    assert resp.status_code == 404


def test_list_sessions(client):
    client.post("/api/testcasegen/sessions")
    client.post("/api/testcasegen/sessions")
    resp = client.get("/api/testcasegen/sessions")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2


def test_delete_session(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.delete(f"/api/testcasegen/sessions/{session['id']}")
    assert resp.status_code == 200
    resp2 = client.get(f"/api/testcasegen/sessions/{session['id']}")
    assert resp2.status_code == 404


def test_upload_screens_multipart(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("screen1.png", io.BytesIO(b"fake-bytes"), "image/png"))]
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["screens"]) == 1


def test_capture_screen_from_base64(client):
    session = client.post("/api/testcasegen/sessions").json()
    b64 = base64.b64encode(b"fake-frame-bytes").decode()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/screens/capture",
        json={"image_b64": b64, "note": "ADB'den yakalandı"},
    )
    assert resp.status_code == 200
    screens = resp.json()["screens"]
    assert screens[0]["user_note"] == "ADB'den yakalandı"


def test_capture_screen_invalid_base64_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/screens/capture",
        json={"image_b64": "not-valid-base64!!"},
    )
    assert resp.status_code == 400


def test_reorder_screens(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)
    files = [("files", ("b.png", io.BytesIO(b"b"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/screens/reorder",
        json={"order": [1, 0]},
    )
    assert resp.status_code == 200
    assert resp.json()["screens"][0]["index"] == 0


def test_edit_screen_note(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/screens/0",
        json={"note": "güncellendi"},
    )
    assert resp.status_code == 200
    assert resp.json()["screens"][0]["user_note"] == "güncellendi"


def test_delete_screen(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"a"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.delete(f"/api/testcasegen/sessions/{session['id']}/screens/0")
    assert resp.status_code == 200
    assert resp.json()["screens"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_screens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'routers.testcasegen_router'`.

- [ ] **Step 3: Create `testcasegen_router.py` (sessions + screens endpoints)**

Create `backend/routers/testcasegen_router.py`:

```python
"""
TestCaseGen Router
-------------------
Ekran görüntüsü -> başlık çıkarma -> önceliklendirme -> test case üretimi -> ADO xlsx export.
Veritabanı YOK — state dosya tabanlı (services/testcasegen_service.py).
"""

import base64
import io
import json as _json
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User
from services import ai_service, testcasegen_service as svc

router = APIRouter(prefix="/api/testcasegen", tags=["testcasegen"])


def _sse(event: str, data: str) -> str:
    result = f"event: {event}\n"
    for line in data.split("\n"):
        result += f"data: {line}\n"
    return result + "\n"


def _load_or_404(user_id: int, session_id: str) -> dict:
    try:
        return svc.load_session(user_id, session_id)
    except FileNotFoundError:
        raise HTTPException(404, "Oturum bulunamadı")


# ── Oturumlar ────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(current_user: User = Depends(get_current_user)):
    return svc.create_session(current_user.id)


@router.get("/sessions")
async def list_sessions(current_user: User = Depends(get_current_user)):
    return {"sessions": svc.list_sessions(current_user.id)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: User = Depends(get_current_user)):
    return _load_or_404(current_user.id, session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: User = Depends(get_current_user)):
    svc.delete_session(current_user.id, session_id)
    return {"ok": True}


# ── Ekranlar (Adım 1) ───────────────────────────────────────────────────

@router.post("/sessions/{session_id}/screens/upload")
async def upload_screens(
    session_id: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(current_user.id, session_id)
    session = None
    for f in files:
        content = await f.read()
        ext = "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".png"
        session = svc.add_screen(current_user.id, session_id, content, ext=ext)
    return session


class CaptureIn(BaseModel):
    image_b64: str
    note: str = ""


@router.post("/sessions/{session_id}/screens/capture")
async def capture_screen(session_id: str, body: CaptureIn, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    try:
        image_bytes = base64.b64decode(body.image_b64, validate=True)
    except Exception:
        raise HTTPException(400, "Geçersiz görsel verisi (base64 decode edilemedi)")
    return svc.add_screen(current_user.id, session_id, image_bytes, ext=".png", note=body.note)


class ReorderIn(BaseModel):
    order: list[int]


@router.put("/sessions/{session_id}/screens/reorder")
async def reorder_screens(session_id: str, body: ReorderIn, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    try:
        return svc.reorder_screens(current_user.id, session_id, body.order)
    except ValueError as e:
        raise HTTPException(400, str(e))


class NoteIn(BaseModel):
    note: str


@router.put("/sessions/{session_id}/screens/{idx}")
async def edit_screen_note(session_id: str, idx: int, body: NoteIn, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    return svc.update_screen_note(current_user.id, session_id, idx, body.note)


@router.delete("/sessions/{session_id}/screens/{idx}")
async def delete_screen(session_id: str, idx: int, current_user: User = Depends(get_current_user)):
    _load_or_404(current_user.id, session_id)
    return svc.delete_screen(current_user.id, session_id, idx)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_screens.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_screens.py
git commit -m "TestCaseGen: router - oturum ve ekran (Adim 1) endpoint'leri"
```

---

## Task 9: Router — extract-titles SSE + titles CRUD (Step 2)

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_titles.py`

**Interfaces:**
- Consumes: `ai_service.ollama_generate_vision` (Task 1), `testcasegen_service.extract_json_object` (Task 2), `testcasegen_service.build_title_extraction_prompt` (Task 6), `testcasegen_service.screen_image_path/load_session/save_session` (Task 3).
- Produces: `POST /sessions/{id}/extract-titles` (SSE), `POST /sessions/{id}/titles`, `PUT /sessions/{id}/titles/{title_id}`, `DELETE /sessions/{id}/titles/{title_id}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_router_titles.py`:

```python
import io
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router
from services import ai_service, testcasegen_service as svc


class _FakeUser:
    id = 1
    username = "tester"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    return TestClient(app)


def _session_with_one_screen(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"fake-png"), "image/png"))]
    session = client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files).json()
    return session


def test_extract_titles_streams_sse_and_persists_titles(client, monkeypatch):
    async def fake_vision(prompt, images_b64, model=None, timeout=90.0):
        return '{"screen_titles": [{"screen_index": 0, "candidate_titles": ["Baslik A"], "screen_summary": "ozet"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)
    session = _session_with_one_screen(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 200
    assert "screen_done" in resp.text
    assert "Baslik A" in resp.text
    assert "complete" in resp.text

    updated = client.get(f"/api/testcasegen/sessions/{session['id']}").json()
    assert updated["screens"][0]["candidate_titles"] == ["Baslik A"]
    assert updated["screens"][0]["parse_error"] is False


def test_extract_titles_marks_parse_error_on_invalid_json(client, monkeypatch):
    async def fake_vision(prompt, images_b64, model=None, timeout=90.0):
        return "bu JSON degil, ham metin"

    monkeypatch.setattr(ai_service, "ollama_generate_vision", fake_vision)
    session = _session_with_one_screen(client)

    client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    updated = client.get(f"/api/testcasegen/sessions/{session['id']}").json()
    assert updated["screens"][0]["parse_error"] is True
    assert updated["screens"][0]["screen_summary"] == "bu JSON degil, ham metin"


def test_extract_titles_without_screens_returns_400(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 400


def test_extract_titles_reports_ollama_error_via_sse(client, monkeypatch):
    async def failing_vision(prompt, images_b64, model=None, timeout=90.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_vision", failing_vision)
    session = _session_with_one_screen(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/extract-titles")
    assert resp.status_code == 200
    assert "event: error" in resp.text


def test_add_edit_delete_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_index": 0, "text": "Elle eklenen baslik"},
    )
    assert resp.status_code == 200
    title_id = resp.json()["titles"][0]["id"]

    resp2 = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}",
        json={"text": "Guncellenmis baslik"},
    )
    assert resp2.json()["titles"][0]["text"] == "Guncellenmis baslik"

    resp3 = client.delete(f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}")
    assert resp3.json()["titles"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_titles.py -v`
Expected: FAIL — 404s on the not-yet-defined `/extract-titles` and `/titles` routes.

- [ ] **Step 3: Add titles endpoints to `testcasegen_router.py`**

Add `import uuid` to the imports at the top, and append the following to `backend/routers/testcasegen_router.py`:

```python
# ── Başlık çıkarma (Adım 2) ─────────────────────────────────────────────

@router.post("/sessions/{session_id}/extract-titles")
async def extract_titles(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    screens = session["screens"]
    if not screens:
        raise HTTPException(400, "Önce en az bir ekran görüntüsü ekleyin")

    async def stream():
        prev_note, prev_summary = "", ""
        for screen in screens:
            image_path = svc.screen_image_path(current_user.id, session_id, screen["index"], screen["image_ext"])
            image_b64 = base64.b64encode(image_path.read_bytes()).decode()
            prompt = svc.build_title_extraction_prompt(screen.get("user_note", ""), prev_note, prev_summary)
            try:
                raw = await ai_service.ollama_generate_vision(prompt, [image_b64])
            except Exception as e:
                yield _sse("error", f"Ollama servisine ulaşılamadı: {e}")
                return

            parsed = svc.extract_json_object(raw)
            entries = parsed.get("screen_titles") if parsed else None
            if entries:
                entry = entries[0]
                screen["candidate_titles"] = entry.get("candidate_titles", [])
                screen["screen_summary"] = entry.get("screen_summary", "")
                screen["parse_error"] = False
            else:
                screen["candidate_titles"] = []
                screen["screen_summary"] = raw
                screen["parse_error"] = True

            prev_note = screen.get("user_note", "")
            prev_summary = screen["screen_summary"]
            svc.save_session(current_user.id, session_id, session)

            yield _sse("screen_done", _json.dumps({
                "screen_index": screen["index"],
                "candidate_titles": screen["candidate_titles"],
                "screen_summary": screen["screen_summary"],
                "parse_error": screen["parse_error"],
            }, ensure_ascii=False))

        yield _sse("complete", "")

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class TitleIn(BaseModel):
    screen_index: int
    text: str


@router.post("/sessions/{session_id}/titles")
async def add_title(session_id: str, body: TitleIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["titles"].append({
        "id": str(uuid.uuid4()),
        "screen_index": body.screen_index,
        "text": body.text,
        "score": None,
        "level": None,
        "level_source": None,
        "rationale": "",
    })
    svc.save_session(current_user.id, session_id, session)
    return session


class TitleTextIn(BaseModel):
    text: str


@router.put("/sessions/{session_id}/titles/{title_id}")
async def edit_title(session_id: str, title_id: str, body: TitleTextIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for title in session["titles"]:
        if title["id"] == title_id:
            title["text"] = body.text
            break
    else:
        raise HTTPException(404, "Başlık bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return session


@router.delete("/sessions/{session_id}/titles/{title_id}")
async def delete_title(session_id: str, title_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    session["titles"] = [t for t in session["titles"] if t["id"] != title_id]
    svc.save_session(current_user.id, session_id, session)
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_titles.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_titles.py
git commit -m "TestCaseGen: router - baslik cikarma SSE + basliklar CRUD (Adim 2)"
```

---

## Task 10: Router — prioritize + manual priority override (Step 3)

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_priority.py`

**Interfaces:**
- Consumes: `testcasegen_service.score_title` (Task 4), `testcasegen_service.build_rationale_prompt` (Task 6), `ai_service.ollama_generate_text` (Task 1).
- Produces: `POST /sessions/{id}/prioritize`, `PUT /sessions/{id}/titles/{title_id}/priority`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_router_priority.py`:

```python
import pytest
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


def _session_with_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_index": 0, "text": "Tutar girilip onaylanır"},
    ).json()
    return session


def test_prioritize_assigns_score_level_and_rationale(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "Bu ekran doğrudan bir ödeme onayı içerdiği için yüksek öncelikli."

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize")
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] in ("high", "medium", "low")
    assert title["level_source"] == "rule"
    assert "yüksek öncelikli" in title["rationale"]


def test_prioritize_falls_back_to_generic_rationale_on_ollama_failure(client, monkeypatch):
    async def failing_text(prompt, model=None, timeout=60.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_text)
    session = _session_with_title(client)

    resp = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize")
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] in ("high", "medium", "low")  # skor yine hesaplanir
    assert title["rationale"]  # bos degil, generic mesaj var


def test_manual_priority_override_sets_level_source_manual(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return "gerekce"

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    session = client.post(f"/api/testcasegen/sessions/{session['id']}/prioritize").json()
    title_id = session["titles"][0]["id"]

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}/priority",
        json={"level": "low"},
    )
    assert resp.status_code == 200
    title = resp.json()["titles"][0]
    assert title["level"] == "low"
    assert title["level_source"] == "manual"


def test_manual_priority_rejects_invalid_level(client):
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/titles/{title_id}/priority",
        json={"level": "urgent"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_priority.py -v`
Expected: FAIL — 404 on `/prioritize` and `/titles/{title_id}/priority`.

- [ ] **Step 3: Add prioritize endpoints to `testcasegen_router.py`**

Add `from typing import Literal` to imports, and append:

```python
# ── Önceliklendirme (Adım 3) ────────────────────────────────────────────

@router.post("/sessions/{session_id}/prioritize")
async def prioritize(session_id: str, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    screens_by_index = {s["index"]: s for s in session["screens"]}

    for title in session["titles"]:
        screen = screens_by_index.get(title["screen_index"], {})
        score, level = svc.score_title(title["text"], screen.get("user_note", ""), title["screen_index"])
        title["score"] = score
        title["level"] = level
        title["level_source"] = "rule"

        prompt = svc.build_rationale_prompt(title["text"], level, score)
        try:
            rationale = await ai_service.ollama_generate_text(prompt)
            title["rationale"] = rationale.strip() or "Gerekçe üretilemedi."
        except Exception:
            title["rationale"] = "Gerekçe üretilemedi (Ollama servisine ulaşılamadı), skor kural motorundan geldi."

    svc.save_session(current_user.id, session_id, session)
    return session


class PriorityIn(BaseModel):
    level: Literal["high", "medium", "low"]


@router.put("/sessions/{session_id}/titles/{title_id}/priority")
async def set_priority(session_id: str, title_id: str, body: PriorityIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for title in session["titles"]:
        if title["id"] == title_id:
            title["level"] = body.level
            title["level_source"] = "manual"
            break
    else:
        raise HTTPException(404, "Başlık bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_priority.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_priority.py
git commit -m "TestCaseGen: router - onceliklendirme + manuel override (Adim 3)"
```

---

## Task 11: Router — generate-testcases + step edit (Step 4)

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_generate.py`

**Interfaces:**
- Consumes: `testcasegen_service.build_testcase_prompt`, `extract_json_object`, `validate_steps` (Tasks 2, 5, 6), `ai_service.ollama_generate_text` (Task 1).
- Produces: `POST /sessions/{id}/generate-testcases`, `PUT /sessions/{id}/testcases/{tc_id}/steps/{idx}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_router_generate.py`:

```python
import pytest
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


def _session_with_title(client):
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_index": 0, "text": "Odeme onaylanir"},
    ).json()
    return session


def test_generate_testcases_creates_and_validates_steps(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return (
            '{"steps": [\n'
            '  {"step_action": "\\"Devam\\" butonuna tiklanir", "step_expected": "Onay ekrani acilir"},\n'
            '  {"step_action": "\\"Onayla\\" tikla", "step_expected": ""}\n'
            ']}'
        )

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 200
    testcases = resp.json()["testcases"]
    assert len(testcases) == 1
    steps = testcases[0]["steps"]
    assert steps[0]["violations"] == []
    assert len(steps[1]["violations"]) >= 1  # emir kipi + bos expected


def test_generate_testcases_unknown_title_id_is_skipped(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": []}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": ["bilinmeyen-id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["testcases"] == []


def test_generate_testcases_ollama_failure_returns_503(client, monkeypatch):
    async def failing_text(prompt, model=None, timeout=60.0):
        raise ConnectionError("ollama kapali")

    monkeypatch.setattr(ai_service, "ollama_generate_text", failing_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]

    resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    )
    assert resp.status_code == 503


def test_edit_step_revalidates(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tikla", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = _session_with_title(client)
    title_id = session["titles"][0]["id"]
    gen_resp = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    tc_id = gen_resp["testcases"][0]["id"]
    assert gen_resp["testcases"][0]["steps"][0]["violations"] != []

    resp = client.put(
        f"/api/testcasegen/sessions/{session['id']}/testcases/{tc_id}/steps/0",
        json={"step_action": "X tiklanir", "step_expected": "Y"},
    )
    assert resp.status_code == 200
    updated_step = resp.json()["testcases"][0]["steps"][0]
    assert updated_step["violations"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_generate.py -v`
Expected: FAIL — 404 on `/generate-testcases`.

- [ ] **Step 3: Add generate-testcases + step edit endpoints**

Append to `backend/routers/testcasegen_router.py`:

```python
# ── Test case üretimi (Adım 4) ──────────────────────────────────────────

class GenerateTestcasesIn(BaseModel):
    title_ids: list[str]


@router.post("/sessions/{session_id}/generate-testcases")
async def generate_testcases(session_id: str, body: GenerateTestcasesIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    titles_by_id = {t["id"]: t for t in session["titles"]}
    screens_by_index = {s["index"]: s for s in session["screens"]}

    created = []
    for title_id in body.title_ids:
        title = titles_by_id.get(title_id)
        if not title:
            continue
        screen = screens_by_index.get(title["screen_index"], {})
        prompt = svc.build_testcase_prompt(title["text"], screen.get("screen_summary", ""), screen.get("user_note", ""))
        try:
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


class StepIn(BaseModel):
    step_action: str
    step_expected: str


@router.put("/sessions/{session_id}/testcases/{tc_id}/steps/{idx}")
async def edit_step(session_id: str, tc_id: str, idx: int, body: StepIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    for tc in session["testcases"]:
        if tc["id"] == tc_id:
            validated = svc.validate_steps([{"step_action": body.step_action, "step_expected": body.step_expected}])
            tc["steps"][idx] = validated[0]
            break
    else:
        raise HTTPException(404, "Test case bulunamadı")
    svc.save_session(current_user.id, session_id, session)
    return {"testcases": session["testcases"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_generate.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_generate.py
git commit -m "TestCaseGen: router - test case uretimi + step duzenleme/revalidate (Adim 4)"
```

---

## Task 12: Router — export endpoint

**Files:**
- Modify: `backend/routers/testcasegen_router.py`
- Test: `backend/tests/test_testcasegen_router_export.py`

**Interfaces:**
- Consumes: `testcasegen_service.build_export_workbook` (Task 7).
- Produces: `POST /sessions/{id}/export`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_testcasegen_router_export.py`:

```python
import io

import openpyxl
import pytest
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


def _session_with_generated_testcase(client, monkeypatch):
    async def fake_text(prompt, model=None, timeout=60.0):
        return '{"steps": [{"step_action": "X tiklanir", "step_expected": "Y"}]}'

    monkeypatch.setattr(ai_service, "ollama_generate_text", fake_text)
    session = client.post("/api/testcasegen/sessions").json()
    session = client.post(
        f"/api/testcasegen/sessions/{session['id']}/titles",
        json={"screen_index": 0, "text": "Baslik"},
    ).json()
    title_id = session["titles"][0]["id"]
    gen = client.post(
        f"/api/testcasegen/sessions/{session['id']}/generate-testcases",
        json={"title_ids": [title_id]},
    ).json()
    return session["id"], gen["testcases"][0]["id"]


def test_export_returns_valid_xlsx(client, monkeypatch):
    session_id, tc_id = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(f"/api/testcasegen/sessions/{session_id}/export", json={"testcase_ids": [tc_id]})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    assert ws[1][0].value == "ID"
    assert ws[2][2].value == "Baslik"


def test_export_no_testcase_ids_returns_400(client, monkeypatch):
    session_id, _ = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(f"/api/testcasegen/sessions/{session_id}/export", json={"testcase_ids": []})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_export.py -v`
Expected: FAIL — 404 on `/export`.

- [ ] **Step 3: Add export endpoint**

Append to `backend/routers/testcasegen_router.py`:

```python
# ── Export ───────────────────────────────────────────────────────────────

class ExportIn(BaseModel):
    testcase_ids: list[str]


@router.post("/sessions/{session_id}/export")
async def export_testcases(session_id: str, body: ExportIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if not body.testcase_ids:
        raise HTTPException(400, "Dışa aktarılacak test case seçilmedi")

    titles_by_id = {t["id"]: t for t in session["titles"]}
    testcases = [tc for tc in session["testcases"] if tc["id"] in body.testcase_ids]
    if not testcases:
        raise HTTPException(400, "Seçilen test case'ler bulunamadı")

    wb = svc.build_export_workbook(testcases, titles_by_id)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="testcases_{session_id[:8]}.xlsx"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_export.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full backend test suite, then commit**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests across Tasks 1-12 pass.

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_export.py
git commit -m "TestCaseGen: router - xlsx export endpoint"
```

---

## Task 13: Wire router into `main.py` + sidebar link

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/WebArayuz/js/sidebar.js`

**Interfaces:**
- Consumes: `routers.testcasegen_router.router` (Task 8-12).

- [ ] **Step 1: Register the router in `main.py`**

In `backend/main.py`, add this import after line 38 (`from routers.ai_job_router import router as ai_job_router`):

```python
# 🧪 TestCaseGen (ekran -> baslik -> onceliklendirme -> test case + ADO export)
from routers.testcasegen_router import router as testcasegen_router
```

Add this after line 82 (`app.include_router(ai_job_router)`):

```python
# 🧪 TestCaseGen
app.include_router(testcasegen_router)
```

- [ ] **Step 2: Add the sidebar link**

In `backend/WebArayuz/js/sidebar.js`, modify the "AI Araçlar" section (around line 59-65) to add the new item after "AI Job'lar":

```javascript
                + section("AI Araçlar",
                    item("ai-generator",   "&#129302;", "AI Test Generator")
                    + item("ai-jobs",       "&#128197;", "AI Job'lar")
                    + item("testcasegen",  "&#128221;", "Test Case Gen")
                    + item("java-generator","&#9749;",  "Java Generator")
                    + item("bdd-generator","&#129405;", "BDD Generator")
                    + item("test-history", "&#128203;", "Test Geçmişi")
                  )
```

- [ ] **Step 3: Verify the server starts and the route is registered**

Run: `cd backend && python -c "from main import app; print([r.path for r in app.routes if 'testcasegen' in r.path])"`
Expected: prints a list containing `/api/testcasegen/sessions` and the other TestCaseGen paths (confirms the import and `include_router` call work without errors).

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/WebArayuz/js/sidebar.js
git commit -m "TestCaseGen: router'i main.py'a bagla, sidebar'a link ekle"
```

---

## Task 14: Frontend skeleton — page shell, stepper, session bootstrap

**Files:**
- Create: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `GET/POST /api/testcasegen/sessions`, `js/app.js` (`Auth`, `API`, `Toast`), `js/sidebar.js`, `css/style.css` design tokens (same `:root` block as `ai-generator.html`).
- Produces: page shell with a 4-step `workflow-stepper` (copied from `ai-generator.html`'s `.wf-step`/`.wf-num`/`.wf-label` component), a `#step-panels` container with one `<div class="step-panel" data-step="N">` per step (empty placeholders — filled in Tasks 15-19), a session picker (`toggleSessionList()`/`switchToSession()`/`deleteSessionFromList()` backed by `GET/DELETE /api/testcasegen/sessions`, satisfying the spec's "resume or delete a past session" requirement) and "+ Yeni Oturum" button, and global JS state `let _session = null;`, `let _currentStep = 1;`.

This task has no automated tests (no JS test runner in this repo — see Global Constraints). Verify manually per Step 3 below.

- [ ] **Step 1: Create the page shell**

Create `backend/WebArayuz/testcasegen.html`:

```html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TestCaseGen - Test Otomasyon Platformu</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
    <style>
        :root {
            --ai-accent: #6366f1;
            --ai-accent-hover: #4f46e5;
            --ai-green: #22c55e;
            --ai-green-hover: #16a34a;
            --ai-red: #ef4444;
            --ai-yellow: #f59e0b;
            --ai-blue: #3b82f6;
            --ai-cyan: #06b6d4;
            --ai-radius: 10px;
            --ai-radius-lg: 14px;
            --ai-transition: 160ms ease;
        }
        .page-content {
            padding: 24px; width: 100%; max-width: 1440px; box-sizing: border-box; overflow-x: hidden;
        }
        .workflow-stepper {
            display: flex; align-items: center; gap: 0; margin-bottom: 20px;
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--ai-radius-lg); padding: 12px 20px; overflow-x: auto;
        }
        .wf-step { display: flex; align-items: center; gap: 8px; white-space: nowrap; cursor: pointer; }
        .wf-num {
            width: 22px; height: 22px; border-radius: 50%; background: var(--bg-tertiary);
            border: 1.5px solid var(--border-color); font-size: 0.7rem; font-weight: 700;
            color: var(--text-muted); display: flex; align-items: center; justify-content: center;
            flex-shrink: 0; transition: var(--ai-transition);
        }
        .wf-step.active .wf-num { background: var(--ai-accent); border-color: var(--ai-accent); color: #fff; }
        .wf-step.done .wf-num { background: var(--ai-green); border-color: var(--ai-green); color: #fff; }
        .wf-label { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); transition: var(--ai-transition); }
        .wf-step.active .wf-label { color: var(--text-primary); }
        .wf-step.done .wf-label { color: var(--ai-green); }
        .wf-arrow { margin: 0 12px; color: var(--border-color); flex-shrink: 0; }
        .step-panel { display: none; }
        .step-panel.active { display: block; }
        .tcg-card {
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--ai-radius-lg); padding: 20px; margin-bottom: 16px;
        }
        .tcg-actions { display: flex; gap: 10px; margin-top: 16px; }
        .tcg-btn {
            padding: 8px 16px; border-radius: var(--ai-radius); border: 1px solid var(--border-color);
            background: var(--bg-tertiary); color: var(--text-primary); cursor: pointer; font-size: 0.85rem;
        }
        .tcg-btn.primary { background: var(--ai-accent); border-color: var(--ai-accent); color: #fff; }
        .tcg-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
</head>
<body>
    <div class="app-layout">
        <div id="sidebar-container"></div>
        <main class="main-content">
            <div class="page-content">
                <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <h1>🧪 TestCaseGen</h1>
                        <p style="color:var(--text-muted); margin-bottom:20px;">
                            Ekran görüntülerinden ADO formatında test case üret.
                        </p>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <button class="tcg-btn" onclick="startNewSession()">+ Yeni Oturum</button>
                        <button class="tcg-btn" onclick="toggleSessionList()">📂 Oturumlarım</button>
                    </div>
                </div>
                <div id="sessionListPanel" class="tcg-card" style="display:none;"></div>

                <div class="workflow-stepper" id="stepper"></div>

                <div id="step-panels">
                    <div class="step-panel" data-step="1" id="panel-1"></div>
                    <div class="step-panel" data-step="2" id="panel-2"></div>
                    <div class="step-panel" data-step="3" id="panel-3"></div>
                    <div class="step-panel" data-step="4" id="panel-4"></div>
                </div>
            </div>
        </main>
    </div>

    <script src="js/app.js"></script>
    <script src="js/sidebar.js"></script>
    <script>
        if (!Auth.checkAuth()) { /* checkAuth zaten login.html'e yönlendirir */ }

        let _session = null;
        let _currentStep = 1;

        const STEP_LABELS = ["Ekran Toplama", "Başlık Çıkarma", "Önceliklendirme", "Test Case Üretimi"];

        function renderStepper() {
            const stepper = document.getElementById("stepper");
            stepper.innerHTML = STEP_LABELS.map((label, i) => {
                const stepNum = i + 1;
                const cls = stepNum === _currentStep ? "active" : (stepNum < _currentStep ? "done" : "");
                const arrow = i < STEP_LABELS.length - 1 ? '<span class="wf-arrow">→</span>' : "";
                return `<div class="wf-step ${cls}" onclick="goToStep(${stepNum})">
                    <div class="wf-num">${stepNum < _currentStep ? "✓" : stepNum}</div>
                    <div class="wf-label">${label}</div>
                </div>${arrow}`;
            }).join("");
        }

        function goToStep(stepNum) {
            _currentStep = stepNum;
            document.querySelectorAll(".step-panel").forEach(p => {
                p.classList.toggle("active", parseInt(p.dataset.step, 10) === stepNum);
            });
            renderStepper();
            if (stepNum === 1) renderStep1();
            if (stepNum === 2) renderStep2();
            if (stepNum === 3) renderStep3();
            if (stepNum === 4) renderStep4();
        }

        function setSessionUrlParam(sessionId) {
            const url = new URL(window.location);
            url.searchParams.set("session", sessionId);
            window.history.replaceState({}, "", url);
        }

        async function startNewSession() {
            try {
                _session = await API.post("/testcasegen/sessions");
                setSessionUrlParam(_session.id);
                document.getElementById("sessionListPanel").style.display = "none";
                goToStep(1);
            } catch (e) {
                Toast.error("Oturum başlatılamadı: " + e.message);
            }
        }

        async function toggleSessionList() {
            const panel = document.getElementById("sessionListPanel");
            if (panel.style.display === "block") { panel.style.display = "none"; return; }
            try {
                const data = await API.get("/testcasegen/sessions");
                panel.innerHTML = data.sessions.length
                    ? data.sessions.map(s => `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border-color);">
                            <span style="cursor:pointer;" onclick="switchToSession('${s.id}')">
                                ${s.id.slice(0, 8)}… — ${s.screens.length} ekran, ${s.testcases.length} test case
                                <span style="color:var(--text-muted); font-size:0.75rem;">(${s.created_at})</span>
                            </span>
                            <button class="tcg-btn" onclick="deleteSessionFromList('${s.id}')">🗑</button>
                        </div>`).join("")
                    : '<p style="color:var(--text-muted);">Henüz oturum yok.</p>';
                panel.style.display = "block";
            } catch (e) {
                Toast.error("Oturumlar listelenemedi: " + e.message);
            }
        }

        async function switchToSession(sessionId) {
            try {
                _session = await API.get(`/testcasegen/sessions/${sessionId}`);
                setSessionUrlParam(sessionId);
                document.getElementById("sessionListPanel").style.display = "none";
                goToStep(1);
            } catch (e) {
                Toast.error("Oturum yüklenemedi: " + e.message);
            }
        }

        async function deleteSessionFromList(sessionId) {
            try {
                await API.delete(`/testcasegen/sessions/${sessionId}`);
                if (_session && _session.id === sessionId) _session = null;
                await toggleSessionList(); // listeyi kapat
                await toggleSessionList(); // guncel listeyle tekrar ac
            } catch (e) {
                Toast.error("Oturum silinemedi: " + e.message);
            }
        }

        async function initSession() {
            const params = new URLSearchParams(window.location.search);
            const existingId = params.get("session");
            try {
                if (existingId) {
                    _session = await API.get(`/testcasegen/sessions/${existingId}`);
                } else {
                    _session = await API.post("/testcasegen/sessions");
                    setSessionUrlParam(_session.id);
                }
            } catch (e) {
                Toast.error("Oturum başlatılamadı: " + e.message);
                return;
            }
            goToStep(1);
        }

        // renderStep1..4 sonraki görevlerde tanımlanacak (şimdilik boş placeholder yok —
        // her görev kendi render fonksiyonunu ekleyecek).
        initSession();
    </script>
</body>
</html>
```

- [ ] **Step 2: Add temporary stub render functions so the page doesn't throw**

This step is superseded by Task 15-19 (each adds its own real `renderStepN`). To confirm the shell works standalone before those exist, temporarily verify with the browser console open — no code change needed if you run Step 3 after Task 15 lands. If you want to verify Task 14 in isolation first, you may add this scratch snippet at the end of the `<script>` block and remove it once Task 15 starts:

```javascript
// GEÇİCİ — Task 15 renderStep1'i ekleyince bu bloğu sil.
if (typeof renderStep1 !== "function") { window.renderStep1 = () => {}; }
if (typeof renderStep2 !== "function") { window.renderStep2 = () => {}; }
if (typeof renderStep3 !== "function") { window.renderStep3 = () => {}; }
if (typeof renderStep4 !== "function") { window.renderStep4 = () => {}; }
```

- [ ] **Step 3: Manually verify in the browser**

Run: `cd backend && python main.py` (venv aktifken), then open `http://localhost:8000/ui/testcasegen.html` in a browser, logged in.
Expected: page loads without console errors, sidebar shows "Test Case Gen" as active, stepper shows 4 steps with step 1 highlighted, URL gains a `?session=<uuid>` query param, and `GET /api/testcasegen/sessions/<uuid>` (checked via DevTools Network tab) returns 200. Reload the page, click "📂 Oturumlarım" — the just-created session appears in the list; clicking "+ Yeni Oturum" creates a second session and switches the URL param to it; clicking the first session in the list switches back and reloads its state; the 🗑 button deletes a session and refreshes the list.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: frontend iskelet - sayfa govdesi, 4 adimli stepper, oturum baslatma"
```

---

## Task 15: Frontend Step 1 — manual upload + reorder list

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `POST /sessions/{id}/screens/upload`, `PUT /sessions/{id}/screens/reorder`, `PUT /sessions/{id}/screens/{idx}`, `DELETE /sessions/{id}/screens/{idx}` (Task 8).
- Produces: `function renderStep1()`, replacing the stub from Task 14.

No automated tests (frontend, no test runner). Verify manually per Step 3.

- [ ] **Step 1: Remove the Task 14 stub for `renderStep1`**

Remove `if (typeof renderStep1 !== "function") { window.renderStep1 = () => {}; }` from the temporary block added in Task 14 Step 2 (leave the other three stubs in place until their tasks land).

- [ ] **Step 2: Implement `renderStep1` with upload + drag-to-reorder list**

Add to the `<script>` block in `testcasegen.html`, before `initSession();`:

```javascript
function renderStep1() {
    const panel = document.getElementById("panel-1");
    panel.innerHTML = `
        <div class="tcg-card">
            <h3>Ekran Görüntüsü Yükle</h3>
            <div id="dropzone" style="border:2px dashed var(--border-color); border-radius:var(--ai-radius);
                 padding:30px; text-align:center; cursor:pointer; margin-bottom:16px;">
                Dosyaları buraya sürükleyin veya tıklayıp seçin
                <input type="file" id="fileInput" multiple accept="image/*" style="display:none;">
            </div>
            <div id="screenList"></div>
            <div class="tcg-actions">
                <button class="tcg-btn primary" id="step1NextBtn" onclick="goToStep(2)">Devam →</button>
            </div>
        </div>
    `;

    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");
    dropzone.onclick = () => fileInput.click();
    dropzone.ondragover = (e) => { e.preventDefault(); dropzone.style.borderColor = "var(--ai-accent)"; };
    dropzone.ondragleave = () => { dropzone.style.borderColor = "var(--border-color)"; };
    dropzone.ondrop = async (e) => {
        e.preventDefault();
        dropzone.style.borderColor = "var(--border-color)";
        await uploadFiles(e.dataTransfer.files);
    };
    fileInput.onchange = async (e) => { await uploadFiles(e.target.files); fileInput.value = ""; };

    renderScreenList();
}

async function uploadFiles(fileList) {
    const formData = new FormData();
    for (const file of fileList) formData.append("files", file);
    try {
        const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/screens/upload`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${Auth.getToken()}` },
            body: formData,
        });
        if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || "Yükleme hatası"); }
        _session = await resp.json();
        renderScreenList();
    } catch (e) {
        Toast.error(e.message);
    }
}

function renderScreenList() {
    const container = document.getElementById("screenList");
    if (!_session.screens.length) {
        container.innerHTML = '<p style="color:var(--text-muted);">Henüz ekran eklenmedi.</p>';
        return;
    }
    container.innerHTML = _session.screens.map((s, i) => `
        <div class="tcg-screen-row" draggable="true" data-index="${i}"
             style="display:flex; align-items:center; gap:12px; padding:8px; border:1px solid var(--border-color);
                    border-radius:var(--ai-radius); margin-bottom:8px; cursor:move; background:var(--bg-primary);">
            <span style="font-weight:600;">#${i + 1}</span>
            <img data-index="${i}" style="height:60px; border-radius:4px;">
            <input type="text" value="${(s.user_note || "").replace(/"/g, '&quot;')}" placeholder="Not ekle (opsiyonel)"
                   style="flex:1;" onchange="editScreenNote(${i}, this.value)">
            <button class="tcg-btn" onclick="deleteScreenAt(${i})">🗑</button>
        </div>
    `).join("");

    _session.screens.forEach(async (_, i) => {
        try {
            const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/screens/${i}/image`, {
                headers: { "Authorization": `Bearer ${Auth.getToken()}` },
            });
            const blob = await resp.blob();
            const imgEl = container.querySelector(`img[data-index="${i}"]`);
            if (imgEl) imgEl.src = URL.createObjectURL(blob);
        } catch (e) { /* thumbnail yuklenemedi, sessizce atla */ }
    });

    let dragSrc = null;
    container.querySelectorAll(".tcg-screen-row").forEach(row => {
        row.addEventListener("dragstart", () => { dragSrc = row.dataset.index; });
        row.addEventListener("dragover", (e) => e.preventDefault());
        row.addEventListener("drop", async (e) => {
            e.preventDefault();
            const dstIndex = parseInt(row.dataset.index, 10);
            const srcIndex = parseInt(dragSrc, 10);
            if (srcIndex === dstIndex) return;
            const order = _session.screens.map((_, i) => i);
            order.splice(srcIndex, 1);
            order.splice(dstIndex, 0, srcIndex);
            await reorderScreens(order);
        });
    });
}

async function reorderScreens(order) {
    try {
        _session = await API.put(`/testcasegen/sessions/${_session.id}/screens/reorder`, { order });
        renderScreenList();
    } catch (e) {
        Toast.error(e.message);
    }
}

async function editScreenNote(index, note) {
    try {
        _session = await API.put(`/testcasegen/sessions/${_session.id}/screens/${index}`, { note });
    } catch (e) {
        Toast.error(e.message);
    }
}

async function deleteScreenAt(index) {
    try {
        _session = await API.delete(`/testcasegen/sessions/${_session.id}/screens/${index}`);
        renderScreenList();
    } catch (e) {
        Toast.error(e.message);
    }
}
```

Note: thumbnails are loaded via `fetch` + `Authorization` header + `URL.createObjectURL`, not a direct `<img src="...">` URL, because this app authenticates with a `Bearer` header (not cookies) and plain `<img>` tags cannot send custom headers.

- [ ] **Step 3: Add a screen-image-serving endpoint (needed by the thumbnail fetch above)**

This is a small backend addition needed for the frontend to actually display thumbnails. Add to `backend/routers/testcasegen_router.py`, after the `delete_screen` endpoint (from Task 8):

```python
from fastapi.responses import FileResponse


@router.get("/sessions/{session_id}/screens/{idx}/image")
async def get_screen_image(session_id: str, idx: int, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if idx < 0 or idx >= len(session["screens"]):
        raise HTTPException(404, "Ekran bulunamadı")
    screen = session["screens"][idx]
    path = svc.screen_image_path(current_user.id, session_id, idx, screen["image_ext"])
    if not path.exists():
        raise HTTPException(404, "Görsel dosyası bulunamadı")
    return FileResponse(path)
```

Add a corresponding test to `backend/tests/test_testcasegen_router_screens.py` (append to the file):

```python
def test_get_screen_image_returns_file_bytes(client):
    session = client.post("/api/testcasegen/sessions").json()
    files = [("files", ("a.png", io.BytesIO(b"raw-image-bytes"), "image/png"))]
    client.post(f"/api/testcasegen/sessions/{session['id']}/screens/upload", files=files)

    resp = client.get(f"/api/testcasegen/sessions/{session['id']}/screens/0/image")
    assert resp.status_code == 200
    assert resp.content == b"raw-image-bytes"


def test_get_screen_image_missing_index_returns_404(client):
    session = client.post("/api/testcasegen/sessions").json()
    resp = client.get(f"/api/testcasegen/sessions/{session['id']}/screens/0/image")
    assert resp.status_code == 404
```

Run: `cd backend && python -m pytest tests/test_testcasegen_router_screens.py -v`
Expected: all tests (the original 10 plus these 2) pass.

- [ ] **Step 4: Manually verify in the browser**

Run: `cd backend && python main.py`, open `http://localhost:8000/ui/testcasegen.html`.
Expected: drag-drop and file-picker upload both work, thumbnails render, drag-to-reorder changes the numbered order, note field saves on blur/change, delete button removes a row and renumbers the rest.

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/testcasegen.html backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_screens.py
git commit -m "TestCaseGen: frontend Adim 1 - manuel upload, surukle-birak siralama, gorsel servis endpoint'i"
```

---

## Task 16: Frontend Step 1 — embedded ADB live view + capture

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `GET /api/emulator/devices`, `POST /api/emulator/{device_id}/connect`, `WS /api/emulator/{device_id}/stream` (existing `emulator.py`, unmodified), `POST /sessions/{id}/screens/capture` (Task 8).

No automated tests (frontend + requires a real/emulated ADB device). Verify manually per Step 3.

- [ ] **Step 1: Add the live-device panel markup to `renderStep1`**

In `testcasegen.html`, modify the `renderStep1()` panel HTML (from Task 15) to add a second card before the "Devam →" button. Replace the `panel.innerHTML = ...` block with:

```javascript
    panel.innerHTML = `
        <div class="tcg-card">
            <h3>Ekran Görüntüsü Yükle</h3>
            <div id="dropzone" style="border:2px dashed var(--border-color); border-radius:var(--ai-radius);
                 padding:30px; text-align:center; cursor:pointer; margin-bottom:16px;">
                Dosyaları buraya sürükleyin veya tıklayıp seçin
                <input type="file" id="fileInput" multiple accept="image/*" style="display:none;">
            </div>
            <div id="screenList"></div>
        </div>
        <div class="tcg-card">
            <h3>ADB ile Canlı Yakalama</h3>
            <div style="display:flex; gap:10px; align-items:center; margin-bottom:12px;">
                <select id="tcgDeviceSelect" style="flex:1;"></select>
                <button class="tcg-btn" id="tcgConnectBtn" onclick="tcgToggleConnection()">🔗 Bağlan</button>
                <button class="tcg-btn primary" id="tcgCaptureBtn" onclick="tcgCaptureFrame()" disabled>📸 Yakala</button>
            </div>
            <div id="tcgPhoneWrap" style="position:relative; width:300px;">
                <img id="tcgScreenImage" style="width:100%; border:1px solid var(--border-color); border-radius:var(--ai-radius);">
            </div>
        </div>
        <div class="tcg-actions">
            <button class="tcg-btn primary" id="step1NextBtn" onclick="goToStep(2)">Devam →</button>
        </div>
    `;

    loadTcgDevices();
    document.getElementById("tcgScreenImage").addEventListener("click", (e) => {
        if (!_tcgWs || _tcgWs.readyState !== WebSocket.OPEN) return;
        const img = e.target;
        const rect = img.getBoundingClientRect();
        const x = Math.round((e.clientX - rect.left) / rect.width * img.naturalWidth);
        const y = Math.round((e.clientY - rect.top) / rect.height * img.naturalHeight);
        _tcgWs.send(JSON.stringify({ type: "tap", x, y }));
    });
```

(Note: the dropzone/fileInput wiring and `renderScreenList()` call from Task 15's `renderStep1` body must remain below this — only the returned HTML template and the two new lines at the end are added here.)

- [ ] **Step 2: Implement the WS connect/capture JS functions**

Add to the `<script>` block, after `renderScreenList`/upload helpers from Task 15:

```javascript
let _tcgWs = null;
let _tcgDeviceId = null;
let _tcgLastFrameB64 = null;

async function loadTcgDevices() {
    const select = document.getElementById("tcgDeviceSelect");
    select.innerHTML = '<option value="">Cihaz seçin...</option>';
    try {
        const data = await API.get("/emulator/devices");
        (data.devices || []).forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.type || "device"})`;
            select.appendChild(opt);
        });
    } catch (e) {
        Toast.error("Cihaz listesi alınamadı: " + e.message);
    }
}

async function tcgToggleConnection() {
    if (_tcgWs) { tcgDisconnect(); return; }
    const deviceId = document.getElementById("tcgDeviceSelect").value;
    if (!deviceId) { Toast.error("Lütfen bir cihaz seçin"); return; }
    try {
        await API.post(`/emulator/${deviceId}/connect`);
        _tcgDeviceId = deviceId;
        tcgConnectWebSocket(deviceId);
    } catch (e) {
        Toast.error(e.message || "Bağlantı hatası");
    }
}

function tcgConnectWebSocket(deviceId) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.hostname}:8000/api/emulator/${deviceId}/stream`;
    _tcgWs = new WebSocket(wsUrl);

    _tcgWs.onopen = () => {
        document.getElementById("tcgConnectBtn").textContent = "🔌 Kes";
        document.getElementById("tcgCaptureBtn").disabled = false;
        Toast.success("Cihaza bağlandı");
    };
    _tcgWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "frame") {
            _tcgLastFrameB64 = data.image;
            document.getElementById("tcgScreenImage").src = "data:image/png;base64," + data.image;
        }
    };
    _tcgWs.onclose = () => {
        document.getElementById("tcgConnectBtn").textContent = "🔗 Bağlan";
        document.getElementById("tcgCaptureBtn").disabled = true;
        _tcgWs = null;
    };
    _tcgWs.onerror = () => Toast.error("Bağlantı hatası — cihaz bağlantısı koptu");
}

function tcgDisconnect() {
    if (_tcgWs) { _tcgWs.close(); _tcgWs = null; }
    document.getElementById("tcgConnectBtn").textContent = "🔗 Bağlan";
    document.getElementById("tcgCaptureBtn").disabled = true;
}

async function tcgCaptureFrame() {
    if (!_tcgLastFrameB64) { Toast.error("Henüz bir kare alınmadı, biraz bekleyin"); return; }
    try {
        _session = await API.post(`/testcasegen/sessions/${_session.id}/screens/capture`, {
            image_b64: _tcgLastFrameB64, note: "",
        });
        renderScreenList();
        Toast.success("Ekran yakalandı");
    } catch (e) {
        Toast.error(e.message);
    }
}
```

- [ ] **Step 3: Manually verify with a connected device/emulator**

Run: `cd backend && python main.py`, connect an Android device/emulator with `adb devices` showing it, open `http://localhost:8000/ui/testcasegen.html`.
Expected: device appears in the dropdown, "Bağlan" opens a live-updating screen, clicking the screen taps the real device (compare with `emulator.html` behavior — same WS protocol), "Yakala" appends the current frame to the screen list below with a thumbnail.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: frontend Adim 1 - gomulu ADB canli ekran + yakalama"
```

---

## Task 17: Frontend Step 2 — SSE title extraction UI

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `POST /sessions/{id}/extract-titles` (SSE, Task 9), `POST/PUT/DELETE /sessions/{id}/titles` (Task 9).
- Produces: `function renderStep2()`, replacing the stub from Task 14.

No automated tests (frontend). Verify manually per Step 3.

- [ ] **Step 1: Remove the Task 14 stub for `renderStep2`**

Remove `if (typeof renderStep2 !== "function") { window.renderStep2 = () => {}; }`.

- [ ] **Step 2: Implement `renderStep2` with SSE progress + editable title list**

Add to the `<script>` block:

```javascript
function renderStep2() {
    const panel = document.getElementById("panel-2");
    panel.innerHTML = `
        <div class="tcg-card">
            <h3>Başlık Çıkarma</h3>
            <button class="tcg-btn primary" id="extractBtn" onclick="runExtractTitles()">🤖 Başlıkları Çıkar</button>
            <button class="tcg-btn" id="retryExtractBtn" style="display:none;" onclick="runExtractTitles()">🔁 Tekrar Dene</button>
            <div id="extractProgress" style="margin-top:12px; color:var(--text-muted);"></div>
            <div id="titlesResult" style="margin-top:16px;"></div>
        </div>
        <div class="tcg-actions">
            <button class="tcg-btn" onclick="goToStep(1)">← Geri</button>
            <button class="tcg-btn primary" onclick="goToStep(3)">Devam →</button>
        </div>
    `;
    renderTitlesResult();
}

async function runExtractTitles() {
    const btn = document.getElementById("extractBtn");
    const retryBtn = document.getElementById("retryExtractBtn");
    const progress = document.getElementById("extractProgress");
    btn.disabled = true;
    retryBtn.style.display = "none";
    progress.textContent = `0 / ${_session.screens.length} ekran işlendi...`;

    try {
        const response = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/extract-titles`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${Auth.getToken()}` },
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Başlık çıkarma başlatılamadı");
        }

        let done = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
            const { done: readerDone, value } = await reader.read();
            if (readerDone) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split("\n\n");
            buffer = parts.pop();
            for (const part of parts) {
                const evtMatch = part.match(/^event:\s*(\S+)/m);
                const dataLines = [...part.matchAll(/^data:\s*(.*)/gm)].map(m => m[1]);
                const evtType = evtMatch ? evtMatch[1] : "log";
                const dataText = dataLines.join("\n");

                if (evtType === "screen_done") {
                    const payload = JSON.parse(dataText);
                    const screen = _session.screens[payload.screen_index];
                    screen.candidate_titles = payload.candidate_titles;
                    screen.screen_summary = payload.screen_summary;
                    screen.parse_error = payload.parse_error;
                    done += 1;
                    progress.textContent = `${done} / ${_session.screens.length} ekran işlendi...`;
                    renderTitlesResult();
                } else if (evtType === "error") {
                    throw new Error(dataText || "Ollama hatası");
                } else if (evtType === "complete") {
                    progress.textContent = "Tamamlandı.";
                }
            }
        }
    } catch (e) {
        Toast.error(e.message);
        progress.textContent = "Hata: " + e.message;
        retryBtn.style.display = "inline-block";
    } finally {
        btn.disabled = false;
    }
}

function renderTitlesResult() {
    const container = document.getElementById("titlesResult");
    container.innerHTML = _session.screens.map((screen, i) => {
        if (screen.parse_error) {
            return `
                <div class="tcg-card">
                    <strong>Ekran #${i + 1}</strong> — JSON parse edilemedi, ham yanıt (düzenleyebilirsiniz):
                    <textarea style="width:100%; min-height:80px; margin-top:8px;"
                              onchange="editRawScreenSummary(${i}, this.value)">${screen.screen_summary || ""}</textarea>
                </div>`;
        }
        const titles = (screen.candidate_titles || []).map((t, ti) => `
            <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
                <input type="text" value="${t.replace(/"/g, '&quot;')}" style="flex:1;"
                       onchange="editCandidateTitle(${i}, ${ti}, this.value)">
                <button class="tcg-btn" onclick="removeCandidateTitle(${i}, ${ti})">🗑</button>
            </div>`).join("");
        return `
            <div class="tcg-card">
                <strong>Ekran #${i + 1}</strong> <span style="color:var(--text-muted);">${screen.screen_summary || ""}</span>
                <div style="margin-top:8px;">${titles}</div>
                <button class="tcg-btn" onclick="addCandidateTitle(${i})">+ Başlık Ekle</button>
            </div>`;
    }).join("");
}

function editRawScreenSummary(screenIndex, value) {
    _session.screens[screenIndex].screen_summary = value;
}

function editCandidateTitle(screenIndex, titleIndex, value) {
    _session.screens[screenIndex].candidate_titles[titleIndex] = value;
}

function removeCandidateTitle(screenIndex, titleIndex) {
    _session.screens[screenIndex].candidate_titles.splice(titleIndex, 1);
    renderTitlesResult();
}

function addCandidateTitle(screenIndex) {
    _session.screens[screenIndex].candidate_titles.push("Yeni başlık");
    renderTitlesResult();
}
```

Note: candidate title edits above are kept client-side on `_session.screens[i].candidate_titles` for immediate UI feedback; Task 18's "Önceliklendir" step promotes the finalized candidates into `_session.titles` server-side entries (one `POST /titles` call per finalized candidate) before scoring — this happens in `renderStep3`'s `runPrioritize()`, not here.

- [ ] **Step 3: Manually verify in the browser**

Run: `cd backend && python main.py`, ensure Ollama is running with a vision-capable model (`ollama pull gemma3:4b` if needed), open the page, complete Step 1 with at least one screenshot, go to Step 2.
Expected: clicking "Başlıkları Çıkar" shows incrementing progress, resulting titles are editable/removable/addable per screen; stopping Ollama first and retrying shows the error message + "Tekrar Dene" button (per spec's error-handling requirement).

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: frontend Adim 2 - SSE ilerleme + duzenlenebilir baslik listesi"
```

---

## Task 18: Frontend Step 3 — kanban prioritization

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `POST /sessions/{id}/titles` (promote finalized candidates, Task 9), `POST /sessions/{id}/prioritize` (Task 10), `PUT /sessions/{id}/titles/{id}/priority` (Task 10).
- Produces: `function renderStep3()`, replacing the stub from Task 14.

No automated tests (frontend). Verify manually per Step 3.

- [ ] **Step 1: Remove the Task 14 stub for `renderStep3`**

Remove `if (typeof renderStep3 !== "function") { window.renderStep3 = () => {}; }`.

- [ ] **Step 2: Implement `renderStep3` with a 3-column drag-and-drop kanban**

Add to the `<script>` block:

```javascript
async function promoteCandidateTitles() {
    // Adim 2'de düzenlenen candidate_titles'lari, henüz _session.titles'ta
    // karşılığı olmayanlar için sunucuda kalıcı title kaydına çevirir.
    const existingTexts = new Set(_session.titles.map(t => `${t.screen_index}:${t.text}`));
    for (const screen of _session.screens) {
        for (const text of (screen.candidate_titles || [])) {
            const key = `${screen.index}:${text}`;
            if (existingTexts.has(key)) continue;
            _session = await API.post(`/testcasegen/sessions/${_session.id}/titles`, {
                screen_index: screen.index, text,
            });
            existingTexts.add(key);
        }
    }
}

function renderStep3() {
    const panel = document.getElementById("panel-3");
    panel.innerHTML = `
        <div class="tcg-card">
            <h3>Önceliklendirme</h3>
            <button class="tcg-btn primary" id="prioritizeBtn" onclick="runPrioritize()">⚖️ Önceliklendir</button>
            <button class="tcg-btn" id="retryPrioritizeBtn" style="display:none;" onclick="runPrioritize()">🔁 Tekrar Dene</button>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-top:16px;">
            <div class="tcg-card" id="col-high" data-level="high" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                <h4 style="color:var(--ai-red);">High</h4><div class="kanban-list"></div>
            </div>
            <div class="tcg-card" id="col-medium" data-level="medium" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                <h4 style="color:var(--ai-yellow);">Medium</h4><div class="kanban-list"></div>
            </div>
            <div class="tcg-card" id="col-low" data-level="low" ondragover="event.preventDefault()" ondrop="onKanbanDrop(event)">
                <h4 style="color:var(--text-muted);">Low</h4><div class="kanban-list"></div>
            </div>
        </div>
        <div class="tcg-actions">
            <button class="tcg-btn" onclick="goToStep(2)">← Geri</button>
            <button class="tcg-btn primary" onclick="goToStep(4)">Devam →</button>
        </div>
    `;
    renderKanban();
}

async function runPrioritize() {
    const btn = document.getElementById("prioritizeBtn");
    const retryBtn = document.getElementById("retryPrioritizeBtn");
    btn.disabled = true;
    try {
        await promoteCandidateTitles();
        _session = await API.post(`/testcasegen/sessions/${_session.id}/prioritize`);
        retryBtn.style.display = "none";
        renderKanban();
        Toast.success("Önceliklendirme tamamlandı");
    } catch (e) {
        Toast.error(e.message);
        retryBtn.style.display = "inline-block";
    } finally {
        btn.disabled = false;
    }
}

function renderKanban() {
    ["high", "medium", "low"].forEach(level => {
        const col = document.querySelector(`#col-${level} .kanban-list`);
        const titles = _session.titles.filter(t => t.level === level);
        col.innerHTML = titles.map(t => `
            <div class="tcg-kanban-card" draggable="true" data-id="${t.id}"
                 style="padding:8px; border:1px solid var(--border-color); border-radius:var(--ai-radius);
                        margin-bottom:8px; cursor:move; background:var(--bg-primary);"
                 ondragstart="event.dataTransfer.setData('text/plain', '${t.id}')">
                <div>${t.text}</div>
                <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">${t.rationale || ""}</div>
            </div>`).join("");
    });
}

async function onKanbanDrop(event) {
    event.preventDefault();
    const titleId = event.dataTransfer.getData("text/plain");
    const level = event.currentTarget.dataset.level;
    try {
        _session = await API.put(`/testcasegen/sessions/${_session.id}/titles/${titleId}/priority`, { level });
        renderKanban();
    } catch (e) {
        Toast.error(e.message);
    }
}
```

- [ ] **Step 3: Manually verify in the browser**

Complete Steps 1-2, go to Step 3.
Expected: clicking "Önceliklendir" promotes edited titles and populates the three columns based on rule-based score, each card shows the Ollama-generated rationale, dragging a card between columns persists the new level (`PUT .../priority`) and marks it `level_source: "manual"` (check via `GET /api/testcasegen/sessions/{id}` in DevTools).

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: frontend Adim 3 - kanban onceliklendirme + surukle-birak override"
```

---

## Task 19: Frontend Step 4 — test case table, validation highlighting, export

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html`

**Interfaces:**
- Consumes: `POST /sessions/{id}/generate-testcases` (Task 11), `PUT /sessions/{id}/testcases/{tc_id}/steps/{idx}` (Task 11), `POST /sessions/{id}/export` (Task 12).
- Produces: `function renderStep4()`, replacing the stub from Task 14.

No automated tests (frontend). Verify manually per Step 3.

- [ ] **Step 1: Remove the Task 14 stub for `renderStep4`**

Remove `if (typeof renderStep4 !== "function") { window.renderStep4 = () => {}; }`. At this point all four Task 14 stub lines should be gone from `testcasegen.html`.

- [ ] **Step 2: Implement `renderStep4` with checkbox selection, table, and export**

Add to the `<script>` block:

```javascript
function renderStep4() {
    const panel = document.getElementById("panel-4");
    const titlesById = Object.fromEntries(_session.titles.map(t => [t.id, t]));
    const checkboxes = _session.titles.map(t => `
        <label style="display:block; margin-bottom:4px;">
            <input type="checkbox" class="tcg-title-checkbox" value="${t.id}"> ${t.text}
            <span style="font-size:0.75rem; color:var(--text-muted);">(${t.level || "-"})</span>
        </label>`).join("");

    panel.innerHTML = `
        <div class="tcg-card">
            <h3>Test Case Üretimi</h3>
            <div style="margin-bottom:12px;">${checkboxes || "<p>Önce Adım 3'te başlık önceliklendirin.</p>"}</div>
            <button class="tcg-btn primary" id="genBtn" onclick="runGenerateTestcases()">🧪 Test Case Oluştur</button>
            <button class="tcg-btn" id="retryGenBtn" style="display:none;" onclick="runGenerateTestcases()">🔁 Tekrar Dene</button>
        </div>
        <div id="testcaseTableWrap"></div>
        <div class="tcg-actions">
            <button class="tcg-btn" onclick="goToStep(3)">← Geri</button>
            <button class="tcg-btn primary" onclick="exportSelectedTestcases()">📥 Excel'e Aktar</button>
        </div>
    `;
    renderTestcaseTable();
}

async function runGenerateTestcases() {
    const ids = [...document.querySelectorAll(".tcg-title-checkbox:checked")].map(el => el.value);
    if (!ids.length) { Toast.error("En az bir başlık seçin"); return; }
    const btn = document.getElementById("genBtn");
    const retryBtn = document.getElementById("retryGenBtn");
    btn.disabled = true;
    try {
        const result = await API.post(`/testcasegen/sessions/${_session.id}/generate-testcases`, { title_ids: ids });
        _session.testcases = _session.testcases.concat(result.testcases);
        retryBtn.style.display = "none";
        renderTestcaseTable();
        Toast.success(`${result.testcases.length} test case üretildi`);
    } catch (e) {
        Toast.error(e.message);
        retryBtn.style.display = "inline-block";
    } finally {
        btn.disabled = false;
    }
}

function renderTestcaseTable() {
    const wrap = document.getElementById("testcaseTableWrap");
    const titlesById = Object.fromEntries(_session.titles.map(t => [t.id, t]));
    if (!_session.testcases.length) { wrap.innerHTML = ""; return; }

    let rows = "";
    _session.testcases.forEach(tc => {
        const title = titlesById[tc.title_id];
        rows += `<tr>
            <td><input type="checkbox" class="tcg-export-checkbox" value="${tc.id}" checked></td>
            <td>Test Case</td>
            <td>${title ? title.text : ""}</td>
            <td colspan="2"></td>
        </tr>`;
        tc.steps.forEach((step, si) => {
            const hasViolations = step.violations && step.violations.length > 0;
            const rowStyle = hasViolations ? 'background:rgba(239,68,68,0.12);' : '';
            const tooltip = hasViolations ? step.violations.map(v => v.message).join(" | ") : "";
            rows += `<tr style="${rowStyle}" title="${tooltip.replace(/"/g, '&quot;')}">
                <td></td><td></td><td></td>
                <td>${si + 1}</td>
                <td><input type="text" value="${step.step_action.replace(/"/g, '&quot;')}"
                           onchange="editTestcaseStep('${tc.id}', ${si}, this.value, null)"></td>
                <td><input type="text" value="${step.step_expected.replace(/"/g, '&quot;')}"
                           onchange="editTestcaseStep('${tc.id}', ${si}, null, this.value)"></td>
            </tr>`;
        });
    });

    wrap.innerHTML = `
        <div class="tcg-card">
            <table style="width:100%; border-collapse:collapse;">
                <thead><tr>
                    <th>Seç</th><th>Work Item Type</th><th>Title</th><th>Step</th>
                    <th>Step Action</th><th>Step Expected</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}

async function editTestcaseStep(tcId, stepIndex, newAction, newExpected) {
    const tc = _session.testcases.find(t => t.id === tcId);
    const step = tc.steps[stepIndex];
    const action = newAction !== null ? newAction : step.step_action;
    const expected = newExpected !== null ? newExpected : step.step_expected;
    try {
        const result = await API.put(
            `/testcasegen/sessions/${_session.id}/testcases/${tcId}/steps/${stepIndex}`,
            { step_action: action, step_expected: expected },
        );
        _session.testcases = result.testcases;
        renderTestcaseTable();
    } catch (e) {
        Toast.error(e.message);
    }
}

async function exportSelectedTestcases() {
    const ids = [...document.querySelectorAll(".tcg-export-checkbox:checked")].map(el => el.value);
    if (!ids.length) { Toast.error("Dışa aktarılacak test case seçilmedi"); return; }
    try {
        const resp = await fetch(`${API_URL}/testcasegen/sessions/${_session.id}/export`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${Auth.getToken()}`,
            },
            body: JSON.stringify({ testcase_ids: ids }),
        });
        if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || "Export hatası"); }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `testcases_${_session.id.slice(0, 8)}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        Toast.error(e.message);
    }
}
```

- [ ] **Step 3: Manually verify in the browser**

Complete Steps 1-3, go to Step 4.
Expected: checking a title and clicking "Test Case Oluştur" populates the ADO-column table; rows with rule violations are highlighted red with a hover tooltip explaining why; editing a Step Action/Expected re-validates and clears the highlight when fixed; "Excel'e Aktar" downloads a `.xlsx` file that opens correctly with title rows and step rows matching the ADO layout described in the spec.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: frontend Adim 4 - test case tablosu, validasyon vurgusu, xlsx export"
```

---

## Task 20: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests from Tasks 1-12 pass (approximately 70 tests), zero failures.

- [ ] **Step 2: Start the server and smoke-test the full wizard end to end**

Run: `cd backend && python main.py`, then in a browser: log in → open `testcasegen.html` from the sidebar → upload 2-3 screenshots (or capture via ADB if a device is available) → extract titles → prioritize → generate test cases for at least one High and one Low title → fix any flagged violations → export → open the downloaded `.xlsx` and confirm it matches the ADO layout (title row then step rows, correct columns filled).

Expected: no unhandled exceptions in the browser console or server log; the full flow described in the spec (`docs/superpowers/specs/2026-08-04-testcasegen-design.md`) works end to end.

- [ ] **Step 3: Confirm nothing else broke**

Run: `cd backend && python -c "from main import app; print('OK', len(app.routes), 'routes')"`
Expected: prints `OK <N> routes` with no import errors — confirms every existing router still imports cleanly alongside the new one.
