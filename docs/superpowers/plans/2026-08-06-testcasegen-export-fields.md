# TestCaseGen Export Alanları (Area Path/Assigned To/State) + Title Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TestCaseGen'in ADO Excel export'unda şu an her zaman boş yazılan Area Path/Assigned To/State kolonlarını, login kullanıcının hesabına kalıcı olarak bağlı varsayılan değerlerle doldurmak; ayrıca Adım 4'teki test case tablosunda üretilen Title'ı elle düzenlenebilir yapmak.

**Architecture:** `User` modeline 3 nullable kolon eklenir (`tcg_area_path`, `tcg_assigned_to`, `tcg_state`); yeni `GET/PUT /api/testcasegen/defaults` endpoint'leri bu kolonları okur/yazar (Assigned To boşsa `full_name`/`username`'e, State boşsa `"Design"`e düşer). Export endpoint'i bu 3 alanı doğrudan `current_user`'dan okuyup `build_export_workbook`'a geçirir — istemciden ayrıca gönderilmez. Title override, TestCaseGen'de **zaten var olan** `PUT /api/testcasegen/sessions/{session_id}/titles/{title_id}` endpoint'ine (bkz. `backend/routers/testcasegen_router.py:243-253`) Adım 4 tablosundan bağlanarak yapılır — yeni bir backend endpoint'i gerekmiyor, sadece frontend kablolaması.

**Tech Stack:** FastAPI + SQLAlchemy 2.x (SQLite, `ALTER TABLE` tabanlı hafif migration), Pydantic v2, pytest + `fastapi.testclient.TestClient`, vanilla JS (`fetch`/`API.*` helper, template literal render).

## Global Constraints

- UI/mesajlar/hata metinleri Türkçe olacak (proje kuralı, `CLAUDE.md`).
- `.env` dosyası yok — konfigürasyon kod içinde veya `ai_config.json`'da (bu görevde ikisi de kullanılmıyor).
- Scenario/Folder/Device gibi diğer varlıklarda olduğu gibi, yeni alanlar da `user_id`/`current_user` üzerinden kullanıcıya izole edilecek (başka kullanıcının varsayılanı görünmeyecek/değişmeyecek).
- SQLite şema değişiklikleri `backend/database.py::_run_migrations()` içindeki `ALTER TABLE ... ADD COLUMN` listesine eklenir (mevcut `last_login`/`upload_only` örnekleriyle aynı desen); Alembic yok.
- DB'ye yazan router endpoint'leri mevcut projede `user.alan = değer; db.commit(); db.refresh(user)` deseniyle çalışır (bkz. `backend/routers/admin_users_router.py:209-214`).
- Bu depoda frontend/JS test runner'ı yok — frontend değişiklikleri için doğrulama adımı gerçek tarayıcıda manuel yapılır, otomatik test yazılmaz.
- TestCaseGen session state'i dosya tabanlıdır (`testcasegen_data/`), DB değil — bu görevdeki yeni 3 alan (`tcg_area_path`/`tcg_assigned_to`/`tcg_state`) ise **kullanıcı profiline** ait, DB'de (`users` tablosu) saklanır. İki store'u birbirine karıştırma.

---

## Dosya Yapısı

| Dosya | Değişiklik |
|---|---|
| `backend/models/db_models.py` | `User` modeline 3 nullable kolon eklenir |
| `backend/database.py` | `_run_migrations()` listesine 3 `ALTER TABLE` satırı eklenir |
| `backend/routers/testcasegen_router.py` | `GET/PUT /defaults` endpoint'leri eklenir; `export_testcases` + `ExportIn` kullanımı `current_user.tcg_*` okuyacak şekilde güncellenir; yeni importlar (`Session`, `get_db`) |
| `backend/services/testcasegen_service.py` | `build_export_workbook` imzası 3 yeni parametre alır, Test Case satırına yazar |
| `backend/tests/test_testcasegen_router_defaults.py` | **Yeni** — `GET/PUT /defaults` testleri (gerçek in-memory SQLite + DB'ye bağlı kullanıcı) |
| `backend/tests/test_testcasegen_router_export.py` | `_FakeUser`'a `tcg_area_path`/`tcg_assigned_to`/`tcg_state`/`full_name`/`username` eklenir; export'un bu alanları doğru hücrelere yazdığını doğrulayan yeni test eklenir |
| `backend/WebArayuz/testcasegen.html` | Adım 4'e "Export Bilgileri" paneli (CSS + `renderStep4`/`loadTcgDefaults`/`saveTcgDefaults`) + test case tablosundaki Title hücresi editable input olur (`editTestcaseTitle`) |

---

### Task 1: `User` modeline export varsayılanı kolonları + migration

**Files:**
- Modify: `backend/models/db_models.py:18-37`
- Modify: `backend/database.py:48-56`

**Interfaces:**
- Produces: `User.tcg_area_path: str | None`, `User.tcg_assigned_to: str | None`, `User.tcg_state: str | None` — Task 2 ve Task 3 bu 3 attribute'u okuyup yazacak.

Bu görevde otomatik test yok (salt şema değişikliği); doğrulama Task 2'nin testleri üzerinden gelir (in-memory DB, `Base.metadata.create_all` güncel model tanımını kullanır).

- [ ] **Step 1: `User` modeline 3 kolon ekle**

`backend/models/db_models.py` dosyasında `upload_only` satırının hemen altına ekle:

```python
    upload_only = Column(Boolean, default=False)  # True ise login sonrasi sadece dosya yukleme sayfasi gorunur
    tcg_area_path = Column(String, nullable=True)
    tcg_assigned_to = Column(String, nullable=True)
    tcg_state = Column(String, nullable=True)  # "Design" | "Ready" | "Closed"
```

- [ ] **Step 2: `_run_migrations()` listesine ekle**

`backend/database.py` içindeki `migrations` listesinin sonuna ekle:

```python
    migrations = [
        "ALTER TABLE repositories ADD COLUMN provider TEXT NOT NULL DEFAULT 'generic'",
        "ALTER TABLE repositories ADD COLUMN editor_type TEXT NOT NULL DEFAULT 'ai'",
        "ALTER TABLE scenario_share_permissions ADD COLUMN owner_user_id INTEGER",
        "ALTER TABLE users ADD COLUMN last_login DATETIME",
        "ALTER TABLE users ADD COLUMN upload_only BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN tcg_area_path TEXT",
        "ALTER TABLE users ADD COLUMN tcg_assigned_to TEXT",
        "ALTER TABLE users ADD COLUMN tcg_state TEXT",
    ]
```

- [ ] **Step 3: Söz dizimi kontrolü**

Run: `cd backend && python -c "import models.db_models, database"`
Expected: hata yok (import başarılı).

- [ ] **Step 4: Commit**

```bash
git add backend/models/db_models.py backend/database.py
git commit -m "TestCaseGen: User modeline export varsayilani kolonlari (area_path/assigned_to/state)"
```

---

### Task 2: `GET/PUT /api/testcasegen/defaults` endpoint'leri

**Files:**
- Modify: `backend/routers/testcasegen_router.py` (importlar + yeni endpoint bloğu, `# ── Export` bölümünden önce eklenir)
- Test: `backend/tests/test_testcasegen_router_defaults.py` (yeni dosya)

**Interfaces:**
- Consumes: `User.tcg_area_path/tcg_assigned_to/tcg_state` (Task 1), `database.get_db`
- Produces: `GET /api/testcasegen/defaults` → `{"area_path": str, "assigned_to": str, "state": str}`; `PUT /api/testcasegen/defaults` (body `{"area_path": str, "assigned_to": str, "state": "Design"|"Ready"|"Closed"}`) → aynı şekilde günceli döner. Task 4 (frontend) bu iki endpoint'i tüketecek.

- [ ] **Step 1: Testi yaz (in-memory DB + gerçek kullanıcı satırı)**

`backend/tests/test_testcasegen_router_defaults.py` dosyasını oluştur:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from models.db_models import User
from routers.auth import get_current_user
from routers.testcasegen_router import router as testcasegen_router


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    user = User(username="tester", email="tester@example.com", hashed_password="x", full_name="Test Kullanici")
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        yield db

    app = FastAPI()
    app.include_router(testcasegen_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_get_defaults_falls_back_to_full_name_and_design(client):
    resp = client.get("/api/testcasegen/defaults")
    assert resp.status_code == 200
    assert resp.json() == {"area_path": "", "assigned_to": "Test Kullanici", "state": "Design"}


def test_put_defaults_then_get_returns_saved_values(client):
    put_resp = client.put(
        "/api/testcasegen/defaults",
        json={"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"}

    get_resp = client.get("/api/testcasegen/defaults")
    assert get_resp.json() == {"area_path": "Mobil\\Hesaplama", "assigned_to": "Baska Kisi", "state": "Ready"}


def test_put_defaults_rejects_invalid_state(client):
    resp = client.put(
        "/api/testcasegen/defaults",
        json={"area_path": "", "assigned_to": "", "state": "GecersizDeger"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_defaults.py -v`
Expected: FAIL — `404 Not Found` (endpoint henüz yok).

- [ ] **Step 3: Endpoint'leri implemente et**

`backend/routers/testcasegen_router.py` en üstteki importları güncelle (mevcut `from routers.auth import get_current_user` satırının yanına ekle):

```python
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User
```

`# ── Export ───...` bölümünden hemen önce (mevcut `edit_step` fonksiyonunun altına) yeni bir bölüm ekle:

```python
# ── Export Varsayılanları ────────────────────────────────────────────────

class TcgDefaultsOut(BaseModel):
    area_path: str
    assigned_to: str
    state: str


def _tcg_defaults_dict(user: User) -> dict:
    return {
        "area_path": user.tcg_area_path or "",
        "assigned_to": user.tcg_assigned_to or user.full_name or user.username,
        "state": user.tcg_state or "Design",
    }


@router.get("/defaults", response_model=TcgDefaultsOut)
async def get_tcg_defaults(current_user: User = Depends(get_current_user)):
    return _tcg_defaults_dict(current_user)


class TcgDefaultsIn(BaseModel):
    area_path: str = ""
    assigned_to: str = ""
    state: Literal["Design", "Ready", "Closed"] = "Design"


@router.put("/defaults", response_model=TcgDefaultsOut)
async def set_tcg_defaults(
    body: TcgDefaultsIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.tcg_area_path = body.area_path
    current_user.tcg_assigned_to = body.assigned_to
    current_user.tcg_state = body.state
    db.commit()
    db.refresh(current_user)
    return _tcg_defaults_dict(current_user)
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_defaults.py -v`
Expected: `3 passed`

- [ ] **Step 5: Mevcut testcasegen testlerinin kırılmadığını doğrula**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_titles.py tests/test_testcasegen_router_generate.py tests/test_testcasegen_router_screens.py -v`
Expected: hepsi PASS (bu görev bu dosyaların davranışını değiştirmiyor).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_defaults.py
git commit -m "TestCaseGen: GET/PUT /api/testcasegen/defaults endpoint'leri"
```

---

### Task 3: Export'un Area Path/Assigned To/State'i yazması

**Files:**
- Modify: `backend/services/testcasegen_service.py:408-435`
- Modify: `backend/routers/testcasegen_router.py` (`export_testcases` fonksiyonu, `# ── Export` bölümü)
- Modify: `backend/tests/test_testcasegen_router_export.py`

**Interfaces:**
- Consumes: `User.tcg_area_path/tcg_assigned_to/tcg_state` (Task 1), `_tcg_defaults_dict` (Task 2)
- Produces: `svc.build_export_workbook(testcases, titles_by_id, area_path: str, assigned_to: str, state: str) -> Workbook` — imza değişti, çağıran tek yer `export_testcases`.

- [ ] **Step 1: Mevcut `_FakeUser`'ı güncelle ve yeni testi yaz**

`backend/tests/test_testcasegen_router_export.py` içindeki `_FakeUser` sınıfını güncelle:

```python
class _FakeUser:
    id = 1
    full_name = "Test Kullanici"
    username = "tester"
    tcg_area_path = "Mobil\\Hesaplama"
    tcg_assigned_to = "Test Kullanici"
    tcg_state = "Ready"
```

Dosyanın sonuna yeni test ekle:

```python
def test_export_writes_area_path_assigned_to_state_on_testcase_row(client, monkeypatch):
    session_id, tc_id = _session_with_generated_testcase(client, monkeypatch)
    resp = client.post(f"/api/testcasegen/sessions/{session_id}/export", json={"testcase_ids": [tc_id]})
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    testcase_row = ws[2]
    assert testcase_row[6].value == "Mobil\\Hesaplama"
    assert testcase_row[7].value == "Test Kullanici"
    assert testcase_row[8].value == "Ready"
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_export.py -v`
Expected: `test_export_writes_area_path_assigned_to_state_on_testcase_row` FAIL (hücreler hâlâ `None`); diğer iki mevcut test hâlâ PASS olmalı (henüz `_FakeUser`'a alan eklemek onları bozmaz).

- [ ] **Step 3: `build_export_workbook`'u güncelle**

`backend/services/testcasegen_service.py:408-435`'i şu şekilde değiştir:

```python
def build_export_workbook(testcases: list, titles_by_id: dict, area_path: str, assigned_to: str, state: str):
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
        ws.append([None, "Test Case", title_text, None, None, None, area_path, assigned_to, state])
        for i, step in enumerate(tc["steps"], start=1):
            ws.append([None, None, None, i, step.get("step_action", ""),
                       step.get("step_expected", ""), None, None, None])

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if cell.font.name != "Arial" or not cell.font.bold:
                cell.font = Font(name="Arial", bold=False)

    return wb
```

- [ ] **Step 4: `export_testcases`'ı güncelle**

`backend/routers/testcasegen_router.py` içindeki `export_testcases` fonksiyonunu güncelle:

```python
@router.post("/sessions/{session_id}/export")
async def export_testcases(session_id: str, body: ExportIn, current_user: User = Depends(get_current_user)):
    session = _load_or_404(current_user.id, session_id)
    if not body.testcase_ids:
        raise HTTPException(400, "Dışa aktarılacak test case seçilmedi")

    titles_by_id = {t["id"]: t for t in session["titles"]}
    testcases = [tc for tc in session["testcases"] if tc["id"] in body.testcase_ids]
    if not testcases:
        raise HTTPException(400, "Seçilen test case'ler bulunamadı")

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

(`_tcg_defaults_dict` Task 2'de eklendi — export da aynı fallback mantığını kullanır: kullanıcı hiç ayarlamamışsa Assigned To otomatik login kullanıcının adı, State `"Design"` olur.)

- [ ] **Step 5: Testleri çalıştır, hepsinin geçtiğini doğrula**

Run: `cd backend && python -m pytest tests/test_testcasegen_router_export.py -v`
Expected: `3 passed`

- [ ] **Step 6: Tüm testcasegen test paketini çalıştır**

Run: `cd backend && python -m pytest tests/ -k testcasegen -v`
Expected: hepsi PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/testcasegen_service.py backend/routers/testcasegen_router.py backend/tests/test_testcasegen_router_export.py
git commit -m "TestCaseGen: export Area Path/Assigned To/State alanlarini kullanici varsayilanindan yazar"
```

---

### Task 4: Frontend — Adım 4'te Export Bilgileri paneli

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html` (CSS bloğu + `renderStep4` + yeni `loadTcgDefaults`/`saveTcgDefaults` fonksiyonları)

**Interfaces:**
- Consumes: `GET/PUT /api/testcasegen/defaults` (Task 2), mevcut `API.get`/`API.put` helper (`backend/WebArayuz/js/app.js:101-104`), mevcut `Toast.error` (bkz. `editTestcaseStep` kullanımı).
- Produces: DOM'da `#tcgAreaPath` / `#tcgAssignedTo` / `#tcgState` id'li input/select — Task 5'te değişiklik yok ama bu id'ler sabit kalmalı.

Bu depoda JS test runner'ı yok — doğrulama tarayıcıda manuel yapılır (adımlar aşağıda).

- [ ] **Step 1: CSS ekle**

`backend/WebArayuz/testcasegen.html` içinde `.tcg-live-controls select { ... }` kuralının (satır ~116) altına ekle:

```css
        .tcg-defaults-panel { display: flex; gap: 16px; flex-wrap: wrap; }
        .tcg-defaults-field { display: flex; flex-direction: column; gap: 4px; min-width: 160px; flex: 1; }
        .tcg-defaults-field label { font-size: 0.78rem; color: var(--text-secondary); font-weight: 500; }
        .tcg-defaults-field input, .tcg-defaults-field select {
            padding: 8px 12px; border-radius: var(--ai-radius); border: 1px solid var(--border-color);
            background: var(--bg-secondary); color: var(--text-primary); font-size: 0.85rem;
        }
        .tcg-defaults-field input:disabled, .tcg-defaults-field select:disabled { opacity: 0.5; }
```

- [ ] **Step 2: `renderStep4()`'e paneli ekle**

`renderStep4()` fonksiyonunu (mevcut hali `backend/WebArayuz/testcasegen.html:911-928`) şu şekilde güncelle:

```javascript
        function renderStep4() {
            const panel = document.getElementById("panel-4");
            panel.innerHTML = `
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.download}<h3>Export Bilgileri</h3></div>
                    <div class="tcg-defaults-panel">
                        <div class="tcg-defaults-field">
                            <label for="tcgAreaPath">Area Path</label>
                            <input type="text" id="tcgAreaPath" onchange="saveTcgDefaults()">
                        </div>
                        <div class="tcg-defaults-field">
                            <label for="tcgAssignedTo">Assigned To</label>
                            <input type="text" id="tcgAssignedTo" onchange="saveTcgDefaults()">
                        </div>
                        <div class="tcg-defaults-field">
                            <label for="tcgState">State</label>
                            <select id="tcgState" onchange="saveTcgDefaults()">
                                <option value="Design">Design</option>
                                <option value="Ready">Ready</option>
                                <option value="Closed">Closed</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="tcg-card">
                    <div class="tcg-card-header">${ICONS.flask}<h3>Test Case Üretimi</h3></div>
                    <div class="tcg-title-checklist" id="titleChecklist"></div>
                    <button class="tcg-btn primary" id="genBtn" onclick="runGenerateTestcases()">${ICONS.flask} Test Case Oluştur</button>
                    <button class="tcg-btn" id="retryGenBtn" style="display:none;" onclick="runGenerateTestcases()">${ICONS.retry} Tekrar Dene</button>
                </div>
                <div id="testcaseTableWrap"></div>
                <div class="tcg-actions">
                    <button class="tcg-btn" onclick="goToStep(3)">${ICONS.chevronLeft} Geri</button>
                    <button class="tcg-btn success" onclick="exportSelectedTestcases()">${ICONS.download} Excel'e Aktar</button>
                </div>
            `;
            renderTitleChecklist();
            renderTestcaseTable();
            loadTcgDefaults();
        }

        async function loadTcgDefaults() {
            try {
                const d = await API.get("/testcasegen/defaults");
                document.getElementById("tcgAreaPath").value = d.area_path;
                document.getElementById("tcgAssignedTo").value = d.assigned_to;
                document.getElementById("tcgState").value = d.state;
            } catch (e) {
                Toast.error(e.message);
            }
        }

        async function saveTcgDefaults() {
            const fields = ["tcgAreaPath", "tcgAssignedTo", "tcgState"].map(id => document.getElementById(id));
            fields.forEach(el => { el.disabled = true; });
            try {
                await API.put("/testcasegen/defaults", {
                    area_path: document.getElementById("tcgAreaPath").value,
                    assigned_to: document.getElementById("tcgAssignedTo").value,
                    state: document.getElementById("tcgState").value,
                });
            } catch (e) {
                Toast.error(e.message);
            } finally {
                fields.forEach(el => { el.disabled = false; });
            }
        }
```

- [ ] **Step 3: Manuel tarayıcı doğrulaması**

1. Backend'i başlat: `cd backend && python main.py`
2. `http://localhost:8000/ui/testcasegen.html`'e login ol.
3. Bir oturum oluştur, en az 1 ekran yükle, başlık çıkar, önceliklendir, Adım 4'e geç.
4. "Export Bilgileri" panelinin göründüğünü, Assigned To alanının login kullanıcının adıyla otomatik dolduğunu, State'in "Design" geldiğini doğrula.
5. Area Path'e bir değer yaz, alandan çık (`onchange` tetiklenir) — hata Toast'u çıkmadığını doğrula.
6. Sayfayı yenile (F5), Adım 4'e tekrar git — yazdığın Area Path değerinin kaybolmadığını doğrula.
7. "Excel'e Aktar" ile bir test case export et, xlsx'i aç, Area Path/Assigned To/State kolonlarının dolu geldiğini doğrula.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: Adim 4'e Export Bilgileri paneli (Area Path/Assigned To/State)"
```

---

### Task 5: Frontend — Adım 4 tablosunda Title inline düzenleme

**Files:**
- Modify: `backend/WebArayuz/testcasegen.html` (`renderTestcaseTable` + yeni `editTestcaseTitle` fonksiyonu)

**Interfaces:**
- Consumes: mevcut `PUT /api/testcasegen/sessions/{session_id}/titles/{title_id}` endpoint'i (body `{"text": str}`, döner: güncel `session` — bkz. `backend/routers/testcasegen_router.py:243-253`, **değişmiyor**), mevcut `API.put`, mevcut `renderTitleChecklist`/`renderTestcaseTable`.
- Produces: yok (bu son görev, kimse buna bağımlı değil).

- [ ] **Step 1: Title hücresini editable input yap**

`renderTestcaseTable()` içindeki (bkz. `backend/WebArayuz/testcasegen.html:960-967`) başlık satırını güncelle:

```javascript
            _session.testcases.forEach(tc => {
                const title = titlesById[tc.title_id];
                rows += `<tr class="tcg-title-row">
                    <td><input type="checkbox" class="tcg-export-checkbox" value="${tc.id}" checked></td>
                    <td>Test Case</td>
                    <td><input type="text" class="tcg-step-input" value="${title ? title.text.replace(/"/g, '&quot;') : ''}"
                               onchange="editTestcaseTitle('${tc.id}', this.value, this)"></td>
                    <td colspan="2"></td>
                </tr>`;
```

(Diğer step-action/step-expected input'larıyla aynı `.tcg-step-input` sınıfı ve `.replace(/"/g, '&quot;')` kaçışı kullanılıyor — mevcut desenle tutarlı, `escapeHtml` yerine bu proje step input'larında hep bu deseni kullanıyor.)

- [ ] **Step 2: `editTestcaseTitle` fonksiyonunu ekle**

`editTestcaseStep` fonksiyonunun (bkz. `backend/WebArayuz/testcasegen.html:995-1017`) altına ekle:

```javascript
        async function editTestcaseTitle(tcId, newTitle, inputEl) {
            const tc = _session.testcases.find(t => t.id === tcId);
            inputEl.disabled = true;
            try {
                _session = await API.put(`/testcasegen/sessions/${_session.id}/titles/${tc.title_id}`, { text: newTitle });
                renderTitleChecklist();
                renderTestcaseTable();
            } catch (e) {
                Toast.error(e.message);
                inputEl.disabled = false;
            }
        }
```

(Başarı durumunda `renderTestcaseTable()` DOM'u yeniden oluşturduğu için eski `inputEl` zaten atılıyor — bu nedenle `finally` yerine sadece hata durumunda `inputEl.disabled = false` yeterli.)

- [ ] **Step 3: Manuel tarayıcı doğrulaması**

1. Adım 4'te üretilmiş bir test case tablosunda Title hücresine tıkla, metni değiştir, dışarı tıkla.
2. Toast hatası çıkmadığını, hücrenin yeni değeri gösterdiğini doğrula.
3. Adım 3'e geri dön (kanban) — aynı başlığın güncellenmiş metinle göründüğünü doğrula (title nesnesi paylaşımlı olduğu için).
4. "Excel'e Aktar" ile export et, xlsx'teki Title hücresinin güncellenmiş metni içerdiğini doğrula.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/testcasegen.html
git commit -m "TestCaseGen: Adim 4 tablosunda Title inline duzenlenebilir"
```
