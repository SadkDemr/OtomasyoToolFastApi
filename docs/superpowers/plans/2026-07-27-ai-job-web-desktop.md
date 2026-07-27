# AI Job Sistemi — Web + Desktop (Faz 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Mobil-only AI Job system (`ai_job_service.py` / `ai_job_router.py` / `ai-jobs-mobile.html`) to also support Web (Selenium, parallel by browser) and Desktop (image-based, fully sequential, single global lock) platforms.

**Architecture:** No new DB tables — `AiJob.platform` and `AiJobDevice.device_id/device_name` are already generic. Service layer gains platform-aware branches: device/browser validation, per-platform `GenerateRequest` construction (mobile/web/desktop templates), and desktop-lock integration in the run engine. Frontend: `ai-jobs-mobile.html` becomes `ai-jobs.html` with a Mobil/Web/Desktop tab bar driving scenario filter, unit-checklist source, job-list filter, and run-matrix rendering.

**Tech Stack:** FastAPI + SQLAlchemy (Python 3.12), vanilla JS/HTML frontend (no build step), asyncio for the job engine.

## Global Constraints

- No DB migration — reuse `AiJob`, `AiJobScenario`, `AiJobDevice`, `AiJobSchedule`, `AiJobRun`, `AiJobRunResult` as-is (see `backend/models/db_models.py:313-393`).
- No automated test framework exists in this repo (`backend/` has zero project-level `pytest`/`TestClient` usage — verified via search). "Tests" in this plan are standalone verification scripts run with `python -c`/heredoc, plus a manual end-to-end checklist for the parts that need a running server + browser/devices. Do not introduce a new test framework as part of this work.
- Desktop platform must never run two automations concurrently — reuse the existing global `_get_desktop_lock()` from `backend/routers/ai_test_generator_router.py`, do not create a second lock.
- Keep the existing Mobil behavior byte-for-byte compatible (same validation errors, same script output) — Mobil is a live, working feature.
- UI text/comments are Turkish, matching the rest of the codebase.

---

### Task 1: Pure per-platform helpers in `ai_job_service.py` (device validation + GenerateRequest construction)

**Files:**
- Modify: `backend/services/ai_job_service.py`
- Test: standalone script run via `python` from `backend/` (no test framework in repo)

**Interfaces:**
- Produces: `_normalize_device_ids(platform: str, device_ids: list[str]) -> list[tuple[str, str]]` — raises `ValueError` on invalid input, returns `(device_id, device_name)` pairs.
- Produces: `_build_job_generate_request(platform: str, steps_list: list, params: dict, device_id: str, system_port: int | None) -> GenerateRequest` — pure, no DB/network/async.
- Consumes (Task 2): both functions are called from `create_job`/`update_job`/`_generate_cell_script`.

These two functions are added near the top of `backend/services/ai_job_service.py`, right after the existing `_validate_scenario_folders` (currently ends at line 47, i.e. right before the `# CRUD` section comment at line 50).

- [ ] **Step 1: Write the failing verification script**

Create `backend/scripts/verify_job_platform_helpers.py`:

```python
"""Gecici dogrulama scripti — ai_job_service platform helper'lari icin.
pytest yok; bu script python -c yerine dosya olarak tutulur ki hata mesaji
okunabilir kalsin. Calistirma: `python scripts/verify_job_platform_helpers.py`
"""
import sys
sys.path.insert(0, ".")

from services.ai_job_service import _normalize_device_ids, _build_job_generate_request

def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)

# ── _normalize_device_ids ────────────────────────────────────────────────
check("mobile: cihaz id'leri aynen (id,id) doner",
      _normalize_device_ids("mobile", ["emulator-5554"]) == [("emulator-5554", "emulator-5554")])

try:
    _normalize_device_ids("mobile", [])
    check("mobile: bos liste ValueError firlatir", False)
except ValueError:
    check("mobile: bos liste ValueError firlatir", True)

check("web: gecerli tarayicilar kucuk harfe normalize edilir",
      _normalize_device_ids("web", ["Chrome", "firefox"]) == [("chrome", "chrome"), ("firefox", "firefox")])

try:
    _normalize_device_ids("web", ["opera"])
    check("web: taninmayan tarayici ValueError firlatir", False)
except ValueError:
    check("web: taninmayan tarayici ValueError firlatir", True)

try:
    _normalize_device_ids("web", [])
    check("web: bos liste ValueError firlatir", False)
except ValueError:
    check("web: bos liste ValueError firlatir", True)

check("desktop: girdi ne olursa olsun tek sozde-birim doner",
      _normalize_device_ids("desktop", []) == [("desktop", "Masaüstü")])
check("desktop: dolu device_ids gonderilse bile yok sayilir",
      _normalize_device_ids("desktop", ["anything"]) == [("desktop", "Masaüstü")])

# ── _build_job_generate_request ──────────────────────────────────────────
req_mobile = _build_job_generate_request(
    "mobile", steps_list=[], params={"app_package": "com.x", "app_activity": ".Main", "appium_url": "http://x:1"},
    device_id="emulator-5554", system_port=8210,
)
check("mobile: GenerateRequest platform/device_id/system_port dogru",
      req_mobile.platform == "mobile" and req_mobile.device_id == "emulator-5554" and req_mobile.system_port == 8210
      and req_mobile.app_package == "com.x" and req_mobile.app_activity == ".Main")

req_web = _build_job_generate_request(
    "web", steps_list=[], params={"target_url": "https://example.com"},
    device_id="firefox", system_port=None,
)
check("web: GenerateRequest browser=device_id, target_url params'tan geliyor",
      req_web.platform == "web" and req_web.browser == "firefox" and req_web.target_url == "https://example.com")

req_desktop = _build_job_generate_request(
    "desktop", steps_list=[], params={"app_path": r"C:\app.exe", "window_title": "MyApp", "reuse_instance": False},
    device_id="desktop", system_port=None,
)
check("desktop: GenerateRequest app_path/window_title/reuse_instance params'tan geliyor",
      req_desktop.platform == "desktop" and req_desktop.app_path == r"C:\app.exe"
      and req_desktop.window_title == "MyApp" and req_desktop.reuse_instance is False)

try:
    _build_job_generate_request("bogus", steps_list=[], params={}, device_id="x", system_port=None)
    check("bilinmeyen platform ValueError firlatir", False)
except ValueError:
    check("bilinmeyen platform ValueError firlatir", True)

print("\nTUM KONTROLLER GECTI")
```

- [ ] **Step 2: Run it, confirm it fails with ImportError (functions don't exist yet)**

Run (from `backend/` directory):
```bash
python scripts/verify_job_platform_helpers.py
```
Expected: `ImportError: cannot import name '_normalize_device_ids' from 'services.ai_job_service'`

- [ ] **Step 3: Implement the two helpers**

In `backend/services/ai_job_service.py`, insert immediately after the `_validate_scenario_folders` function (after line 47, before the `# CRUD` section header at line 50):

```python
_WEB_BROWSERS = {"chrome", "firefox", "edge"}


def _normalize_device_ids(platform: str, device_ids: list[str]) -> list[tuple[str, str]]:
    """Platforma gore (device_id, device_name) ciftleri uretir.

    - mobile: ADB serial'i hem id hem ad olarak kullanilir, en az bir tane sarttir.
    - web: sadece {chrome, firefox, edge} kabul edilir (kucuk harfe normalize edilir),
      en az bir tane sarttir.
    - desktop: kullanicidan device_ids gelse bile yok sayilir — global desktop kilidi
      yuzunden paralellik yok, tek sabit sozde-birim doner.
    """
    if platform == "desktop":
        return [("desktop", "Masaüstü")]

    if platform == "web":
        clean: list[tuple[str, str]] = []
        for d in device_ids:
            name = (d or "").strip().lower()
            if name not in _WEB_BROWSERS:
                raise ValueError(f"Geçersiz tarayıcı: {d!r}")
            clean.append((name, name))
        if not clean:
            raise ValueError("En az bir tarayıcı seçilmeli")
        return clean

    # mobile (varsayilan)
    if not device_ids:
        raise ValueError("En az bir cihaz seçilmeli")
    return [(d, d) for d in device_ids]


def _build_job_generate_request(
    platform: str, steps_list: list, params: dict, device_id: str, system_port: int | None,
):
    """Job hucresi icin GenerateRequest olusturur. Salt Python — DB/network/async yok,
    bu yuzden bagimsiz test edilebilir. GenerateRequest import'u fonksiyon ici (lazy):
    ai_test_generator_router agir bir modul, module-level import ai_job_service'i
    gereksiz yere ona baglar (bkz. _generate_cell_script'teki ayni desen)."""
    from routers.ai_test_generator_router import GenerateRequest

    if platform == "mobile":
        return GenerateRequest(
            steps_list=steps_list, platform="mobile", device_id=device_id, system_port=system_port,
            app_package=params.get("app_package", ""), app_activity=params.get("app_activity", ""),
            appium_url=params.get("appium_url") or "http://localhost:4723",
        )
    if platform == "web":
        return GenerateRequest(
            steps_list=steps_list, platform="web", browser=device_id,
            target_url=params.get("target_url", ""),
        )
    if platform == "desktop":
        return GenerateRequest(
            steps_list=steps_list, platform="desktop",
            app_path=params.get("app_path", ""), window_title=params.get("window_title", ""),
            reuse_instance=params.get("reuse_instance", True),
        )
    raise ValueError(f"Bilinmeyen platform: {platform!r}")
```

- [ ] **Step 4: Run the verification script again, confirm it passes**

```bash
python scripts/verify_job_platform_helpers.py
```
Expected: every line printed as `[OK] ...`, ending with `TUM KONTROLLER GECTI`, exit code 0.

- [ ] **Step 5: Delete the scratch verification script (its job is done, keep the repo clean)**

```bash
rm backend/scripts/verify_job_platform_helpers.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/ai_job_service.py
git commit -m "ai-job: platform bazli cihaz dogrulama ve GenerateRequest uretici helper'lari"
```

---

### Task 2: Wire the helpers into CRUD + script generation

**Files:**
- Modify: `backend/services/ai_job_service.py`

**Interfaces:**
- Consumes: `_normalize_device_ids`, `_build_job_generate_request` from Task 1.
- Produces: `create_job(..., platform: str = "mobile")`, `update_job(..., platform: str = "mobile")` — both now store `platform` on the job and use normalized device pairs. `_generate_cell_script(platform, steps_data, device_id, system_port=None)` — **signature changed**, gains a leading `platform` argument (breaking change for its one caller, fixed in Task 3).

- [ ] **Step 1: Replace `create_job`**

In `backend/services/ai_job_service.py`, replace the existing `create_job` function (lines 54-78):

```python
def create_job(
    db: Session, user_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None, platform: str = "mobile",
) -> AiJob:
    scenario_folders = _validate_scenario_folders(scenario_folders)
    device_pairs = _normalize_device_ids(platform, device_ids)
    job = AiJob(user_id=user_id, name=name, platform=platform)
    db.add(job)
    db.commit()
    db.refresh(job)

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job.id, scenario_folder=folder))
    for device_id, device_name in device_pairs:
        db.add(AiJobDevice(job_id=job.id, device_id=device_id, device_name=device_name))
    if schedule:
        db.add(AiJobSchedule(
            job_id=job.id,
            schedule_type=schedule["schedule_type"],
            run_at=datetime.fromisoformat(schedule["run_at"]),
            enabled=True,
        ))
    db.commit()
    db.refresh(job)
    return job
```

- [ ] **Step 2: Replace `update_job`**

Replace the existing `update_job` function (lines 89-116):

```python
def update_job(
    db: Session, job_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None, platform: str = "mobile",
) -> AiJob:
    scenario_folders = _validate_scenario_folders(scenario_folders)
    device_pairs = _normalize_device_ids(platform, device_ids)
    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    job.name = name
    job.platform = platform

    db.query(AiJobScenario).filter(AiJobScenario.job_id == job_id).delete()
    db.query(AiJobDevice).filter(AiJobDevice.job_id == job_id).delete()
    db.query(AiJobSchedule).filter(AiJobSchedule.job_id == job_id).delete()

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job_id, scenario_folder=folder))
    for device_id, device_name in device_pairs:
        db.add(AiJobDevice(job_id=job_id, device_id=device_id, device_name=device_name))
    if schedule:
        db.add(AiJobSchedule(
            job_id=job_id,
            schedule_type=schedule["schedule_type"],
            run_at=datetime.fromisoformat(schedule["run_at"]),
            enabled=True,
        ))

    db.commit()
    db.refresh(job)
    return job
```

- [ ] **Step 3: Replace `_generate_cell_script`**

Replace the existing `_generate_cell_script` function (lines 246-266):

```python
async def _generate_cell_script(
    platform: str, steps_data: dict, device_id: str, system_port: int | None = None,
) -> str:
    """steps.json icerigini hedef birime (cihaz/tarayici/masaustu) gore script'e derler
    (kayitli script.py KULLANILMAZ). system_port yalnizca mobile'da anlamlidir."""
    from routers.ai_test_generator_router import (
        StepItem, _generate_steps, _build_mobile_template, _build_web_template, _build_desktop_template,
    )
    params = steps_data.get("params", {}) or {}
    steps_list = [StepItem(**s) for s in steps_data.get("steps", [])]
    req = _build_job_generate_request(platform, steps_list, params, device_id, system_port)
    steps_code, _report = await _generate_steps(req)
    build_fn = {
        "mobile": _build_mobile_template,
        "web": _build_web_template,
        "desktop": _build_desktop_template,
    }[platform]
    return build_fn(req, steps_code)
```

- [ ] **Step 4: Confirm the module still imports cleanly**

```bash
cd backend && python -c "import services.ai_job_service; print('OK')"
```
Expected: `OK` (no `SyntaxError`/`NameError` — this only catches syntax issues since `create_job`/`update_job`/`_generate_cell_script` need a DB session or event loop to actually run, which Task 6's manual checklist covers).

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_job_service.py
git commit -m "ai-job: create_job/update_job/_generate_cell_script platform parametresi kullansin"
```

---

### Task 3: Thread `platform` through the run engine + desktop lock integration

**Files:**
- Modify: `backend/services/ai_job_service.py`

**Interfaces:**
- Consumes: `_get_desktop_lock()` from `backend/routers/ai_test_generator_router.py` (existing `asyncio.Lock`, already used by the manual `/execute` endpoint — see lines 105-111, 3910-3914, 3942-3944, 4042-4046 of that file).
- Produces: `_execute_cell(run_id, cell_id, steps_data, device_id, system_port, platform)` — **signature changed**, gains trailing `platform` arg. `_run_job_cells(run_id, device_groups, scenario_data, platform)` — **signature changed**, gains trailing `platform` arg and now acquires/releases the desktop lock for the whole group when `platform == "desktop"`. `run_job` — internal only, same external signature `(job_id, db, trigger_type)`; now rejects desktop jobs early if the desktop lock is already held, and skips `system_port` allocation for non-mobile platforms.

- [ ] **Step 1: Replace `_execute_cell`'s call into `_generate_cell_script`**

In `backend/services/ai_job_service.py`, this function's signature and its one call site both change. Replace the function header and the two lines that call `_generate_cell_script`/reference `steps_data` (inside the existing `_execute_cell` function, which currently starts at line 435):

```python
async def _execute_cell(
    run_id: int, cell_id: int, steps_data: dict | None,
    device_id: str, system_port: int | None, platform: str,
) -> None:
```

(This replaces the current signature at lines 435-438. Keep everything else in the function body the same **except** the line that currently reads:)

```python
                script = await _generate_cell_script(steps_data, device_id, system_port)
```

(around line 475) — change it to:

```python
                script = await _generate_cell_script(platform, steps_data, device_id, system_port)
```

- [ ] **Step 2: Replace `_run_job_cells`**

Replace the existing `_run_job_cells` function (lines 587-616):

```python
async def _run_job_cells(
    run_id: int, device_groups: list[list[dict]], scenario_data: dict[str, dict], platform: str,
) -> None:
    """FAZ 2 (arka plan): hücreleri koşturur ve run'ı sonlandırır.

    device_groups: her eleman TEK bir cihaza/tarayıcıya ait hücre listesidir. Gruplar
    birbirine paralel, grup İÇİ hücreler ise SIRAYLA koşar. Desktop'ta grup sayısı
    her zaman 1'dir (tek sözde-birim) — bu yüzden desktop zaten doğal olarak tam
    sıralı çalışır; global _get_desktop_lock() burada AYRICA tutulur ki bu run
    sürerken manuel bir "Test Et" çalıştırması (AI Test Generator sayfası) veya
    başka bir desktop job'ı araya giremesin.

    Bu fonksiyon asyncio.create_task ile fire-and-forget çağrıldığı için HİÇBİR
    istisnayı dışarı sızdırmamalıdır (aksi halde "Task exception was never retrieved").
    """
    interrupted = False
    desktop_lock = None
    try:
        if platform == "desktop":
            from routers.ai_test_generator_router import _get_desktop_lock
            desktop_lock = _get_desktop_lock()
            await desktop_lock.acquire()

        async def _device_sequence(cells: list[dict]) -> None:
            for c in cells:
                await _execute_cell(
                    run_id, c["cell_id"], scenario_data.get(c["scenario_folder"]),
                    c["device_id"], c["system_port"], platform,
                )

        await asyncio.gather(*[_device_sequence(g) for g in device_groups])
    except Exception as e:
        interrupted = True
        print(f"[AI-JOB] run {run_id} koşumu kesintiye uğradı: {e}")
    finally:
        if desktop_lock is not None and desktop_lock.locked():
            try:
                desktop_lock.release()
            except RuntimeError:
                pass
        _stopped_runs.discard(run_id)
        try:
            await _finalize_run(run_id, interrupted)
        except Exception as e:
            print(f"[AI-JOB] run {run_id} finalize hatası: {e}")
```

- [ ] **Step 3: Update `run_job`'s early desktop-lock check and cell-planning loop**

In `run_job` (currently starting at line 619), insert a desktop-lock check right after the "already running" check (after the block that currently reads, around lines 637-639):

```python
    already = db.query(AiJobRun).filter(AiJobRun.job_id == job_id, AiJobRun.status == "running").first()
    if already:
        raise JobAlreadyRunningError(f"Job {job_id} zaten çalışıyor (run_id={already.id})")
```

add immediately after it:

```python
    if job.platform == "desktop":
        from routers.ai_test_generator_router import _get_desktop_lock
        if _get_desktop_lock().locked():
            raise JobAlreadyRunningError("Başka bir desktop testi şu anda çalışıyor, lütfen bekleyin")
```

Then, in the cell-planning loop further down (currently around lines 686-700), the `plan` dict's `system_port` must only be allocated for mobile. Replace:

```python
        for c in cells:
            plan = {
                "cell_id": c.id,
                "scenario_folder": c.scenario_folder,
                "device_id": c.device_id,
                # Port CİHAZA bağlı ve process genelinde global — eşzamanlı koşumlar
                # farklı cihazlar için asla aynı portu almaz (bkz. _acquire_system_port).
                "system_port": _acquire_system_port(c.device_id),
            }
```

with:

```python
        for c in cells:
            plan = {
                "cell_id": c.id,
                "scenario_folder": c.scenario_folder,
                "device_id": c.device_id,
                # Port yalnizca mobile'da anlamlidir (UiAutomator2 systemPort). Web/desktop
                # icin gereksiz port tahsis etmeyelim (bkz. _acquire_system_port).
                "system_port": _acquire_system_port(c.device_id) if job.platform == "mobile" else None,
            }
```

Finally, update the `asyncio.create_task` call at the end of the try block (currently the line `asyncio.create_task(_run_job_cells(run_id, device_groups, scenario_data))`) to pass the platform through:

```python
        asyncio.create_task(_run_job_cells(run_id, device_groups, scenario_data, job.platform))
```

- [ ] **Step 4: Confirm the module still imports cleanly**

```bash
cd backend && python -c "import services.ai_job_service; print('OK')"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_job_service.py
git commit -m "ai-job: run motoru platform-farkinda calissin, desktop icin global kilit kullansin"
```

---

### Task 4: Router changes (`platform` field + list filter)

**Files:**
- Modify: `backend/routers/ai_job_router.py`

**Interfaces:**
- Consumes: `ai_job_service.create_job(..., platform=...)`, `ai_job_service.update_job(..., platform=...)` from Task 2.
- Produces: `JobIn.platform: str` (validated against `{"mobile", "web", "desktop"}`), `GET /api/ai-jobs?platform=` query filter.

- [ ] **Step 1: Add `platform` to `JobIn` with validation**

In `backend/routers/ai_job_router.py`, replace the `JobIn` class (lines 25-29):

```python
from pydantic import BaseModel, field_validator

_VALID_PLATFORMS = {"mobile", "web", "desktop"}


class JobIn(BaseModel):
    name: str
    platform: str = "mobile"
    scenario_folders: list[str]
    device_ids: list[str]
    schedule: Optional[JobScheduleIn] = None

    @field_validator("platform")
    @classmethod
    def _check_platform(cls, v: str) -> str:
        if v not in _VALID_PLATFORMS:
            raise ValueError(f"Geçersiz platform: {v!r}")
        return v
```

Note: the existing import line at the top of the file currently reads `from pydantic import BaseModel` — this step's `from pydantic import BaseModel, field_validator` replaces that import (don't leave both).

- [ ] **Step 2: Relax the device-selection precondition for desktop, pass `platform` through**

In `create_job` (router function, currently lines 32-43), replace:

```python
@router.post("")
async def create_job(body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.scenario_folders or not body.device_ids:
        raise HTTPException(400, "En az bir senaryo ve bir cihaz seçilmeli")
    try:
        job = ai_job_service.create_job(
            db, current_user.id, body.name, body.scenario_folders, body.device_ids,
            body.schedule.dict() if body.schedule else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ai_job_service.job_to_dict(job)
```

with:

```python
@router.post("")
async def create_job(body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.scenario_folders:
        raise HTTPException(400, "En az bir senaryo seçilmeli")
    if body.platform != "desktop" and not body.device_ids:
        raise HTTPException(400, "En az bir cihaz/tarayıcı seçilmeli")
    try:
        job = ai_job_service.create_job(
            db, current_user.id, body.name, body.scenario_folders, body.device_ids,
            body.schedule.dict() if body.schedule else None, platform=body.platform,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ai_job_service.job_to_dict(job)
```

Apply the same precondition change to `update_job` (router function, currently lines 60-74) — replace:

```python
@router.put("/{job_id}")
async def update_job(job_id: int, body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    if not body.scenario_folders or not body.device_ids:
        raise HTTPException(400, "En az bir senaryo ve bir cihaz seçilmeli")
    try:
        job = ai_job_service.update_job(
            db, job_id, body.name, body.scenario_folders, body.device_ids,
            body.schedule.dict() if body.schedule else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ai_job_service.job_to_dict(job)
```

with:

```python
@router.put("/{job_id}")
async def update_job(job_id: int, body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    if not body.scenario_folders:
        raise HTTPException(400, "En az bir senaryo seçilmeli")
    if body.platform != "desktop" and not body.device_ids:
        raise HTTPException(400, "En az bir cihaz/tarayıcı seçilmeli")
    try:
        job = ai_job_service.update_job(
            db, job_id, body.name, body.scenario_folders, body.device_ids,
            body.schedule.dict() if body.schedule else None, platform=body.platform,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return ai_job_service.job_to_dict(job)
```

- [ ] **Step 3: Add `?platform=` filter to `list_jobs`**

Replace the existing `list_jobs` function (lines 46-49):

```python
@router.get("")
async def list_jobs(
    platform: Optional[str] = None,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    jobs = ai_job_service.list_jobs(db, current_user.id, platform=platform)
    return {"jobs": [ai_job_service.job_to_dict(j) for j in jobs]}
```

- [ ] **Step 4: Add the `platform` filter to the service-layer `list_jobs`**

In `backend/services/ai_job_service.py`, replace the existing `list_jobs` function:

```python
def list_jobs(db: Session, user_id: int) -> list[AiJob]:
    return db.query(AiJob).filter(AiJob.user_id == user_id).order_by(AiJob.created_at.desc()).all()
```

with:

```python
def list_jobs(db: Session, user_id: int, platform: str | None = None) -> list[AiJob]:
    q = db.query(AiJob).filter(AiJob.user_id == user_id)
    if platform:
        q = q.filter(AiJob.platform == platform)
    return q.order_by(AiJob.created_at.desc()).all()
```

- [ ] **Step 5: Confirm both modules still import cleanly**

```bash
cd backend && python -c "import routers.ai_job_router, services.ai_job_service; print('OK')"
```
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/ai_job_router.py backend/services/ai_job_service.py
git commit -m "ai-job: JobIn.platform alani + platform bazli filtre/dogrulama"
```

---

### Task 5: Frontend — unify into `ai-jobs.html` with a platform tab bar

**Files:**
- Create: `backend/WebArayuz/ai-jobs.html`
- Delete: `backend/WebArayuz/ai-jobs-mobile.html`
- Modify: `backend/WebArayuz/js/sidebar.js:70`

**Interfaces:**
- Consumes: `GET /api/ai-jobs?platform=`, `POST/PUT /api/ai-jobs` body now includes `platform`, `GET /ai-gen/scenarios`, `GET /ai-gen/adb/devices` — all from Task 4.
- No new backend interfaces produced.

- [ ] **Step 1: Create `backend/WebArayuz/ai-jobs.html`**

```html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Job'lar - Test Otomasyon Platformu</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
    <style>
        /* NOT: Tum ozel siniflar "aijob-" onekli — site genelindeki css/style.css'te
           ayni isimli siniflar (ornegin .modal-overlay + .active toggle konvansiyonu)
           mevcut oldugu icin isim carpismasini onlemek amacli (bkz. test-history.html'in
           kendi "hist-" onek konvansiyonu). */

        .page-content { padding: 28px; width: 100%; max-width: 1200px; box-sizing: border-box; }

        .aijob-tabs { display: flex; gap: 6px; margin-bottom: 18px; border-bottom: 1px solid var(--border-color); }
        .aijob-tab {
            padding: 10px 18px; font-size: 0.88rem; font-weight: 600; color: var(--text-muted);
            background: transparent; border: none; border-bottom: 2px solid transparent; cursor: pointer;
            transition: var(--transition); display: flex; align-items: center; gap: 6px;
        }
        .aijob-tab:hover { color: var(--text-primary); }
        .aijob-tab.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }

        .aijob-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }
        .aijob-toolbar-title { font-weight: 600; font-size: 1.05rem; flex: 1; display: flex; align-items: center; gap: 8px; }
        .aijob-toolbar-count {
            font-size: 0.72rem; font-weight: 600; color: var(--text-muted);
            background: var(--bg-tertiary); border-radius: 999px; padding: 2px 9px;
        }

        .aijob-btn {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 9px 16px; border-radius: var(--radius-md);
            font-size: 0.85rem; font-weight: 500; cursor: pointer;
            border: 1px solid transparent; transition: var(--transition);
            line-height: 1.2;
        }
        .aijob-btn:active { transform: scale(0.97); }
        .aijob-btn-primary { background: var(--accent-primary); color: #fff; box-shadow: var(--shadow-sm); }
        .aijob-btn-primary:hover { background: var(--accent-hover); box-shadow: var(--shadow-md); }
        .aijob-btn-secondary { background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary); }
        .aijob-btn-secondary:hover { background: var(--bg-hover, var(--bg-tertiary)); border-color: var(--accent-primary); color: var(--accent-primary); }
        .aijob-btn-danger { background: transparent; border-color: var(--border-color); color: var(--text-muted); }
        .aijob-btn-danger:hover { background: rgba(239,68,68,0.08); border-color: var(--danger); color: var(--danger); }
        .aijob-btn-sm { padding: 6px 12px; font-size: 0.78rem; }
        .aijob-btn[disabled] { opacity: 0.5; cursor: not-allowed; pointer-events: none; }

        /* ── Job kartlari ─────────────────────────────────────────────── */
        .aijob-list { display: flex; flex-direction: column; gap: 10px; }
        .aijob-card {
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--radius-lg); padding: 16px 18px;
            display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
            transition: var(--transition);
            animation: aijob-fade-up 0.25s ease both;
        }
        .aijob-card:hover { box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--accent-primary) 35%, var(--border-color)); }
        .aijob-card-icon {
            width: 42px; height: 42px; min-width: 42px; border-radius: var(--radius-md);
            background: rgba(16,185,129,0.12); color: var(--success);
            display: flex; align-items: center; justify-content: center; font-size: 1.15rem;
        }
        .aijob-card-body { flex: 1; min-width: 180px; }
        .aijob-card-name { font-weight: 600; font-size: 0.95rem; color: var(--text-primary); }
        .aijob-card-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 5px; }
        .aijob-chip {
            display: inline-flex; align-items: center; gap: 4px;
            font-size: 0.74rem; font-weight: 500; color: var(--text-muted);
            background: var(--bg-tertiary); border-radius: 999px; padding: 3px 10px;
        }
        .aijob-chip-schedule { color: var(--accent-primary); background: rgba(79,70,229,0.1); }
        .aijob-chip-schedule.is-paused { color: var(--text-muted); background: var(--bg-tertiary); }
        .aijob-card-actions { display: flex; gap: 6px; flex-wrap: wrap; }

        /* ── Bos durum (site genelindeki .empty-state-icon konvansiyonuyla ayni) ── */
        .aijob-empty { text-align: center; padding: 54px 20px; }
        .aijob-empty .empty-state-icon { font-size: 2rem; }
        .aijob-empty-title { font-size: 1.02rem; font-weight: 600; margin-bottom: 6px; color: var(--text-primary); }
        .aijob-empty-desc { color: var(--text-muted); font-size: 0.86rem; }
        .aijob-empty-err { color: var(--danger); }

        /* ── Modal ────────────────────────────────────────────────────── */
        .aijob-modal-overlay {
            position: fixed; inset: 0; background: rgba(15,15,26,0.55); backdrop-filter: blur(3px);
            display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 16px;
            opacity: 0; visibility: hidden; transition: var(--transition);
        }
        .aijob-modal-overlay.active { opacity: 1; visibility: visible; }
        .aijob-modal-box {
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--radius-lg); box-shadow: var(--shadow-lg);
            padding: 24px; width: 100%; max-width: 640px;
            max-height: 85vh; overflow-y: auto; display: flex; flex-direction: column; gap: 16px;
            transform: scale(0.94) translateY(8px); transition: var(--transition);
        }
        .aijob-modal-overlay.active .aijob-modal-box { transform: scale(1) translateY(0); }
        .aijob-modal-header { display: flex; align-items: center; justify-content: space-between; }
        .aijob-modal-title { font-size: 1.05rem; font-weight: 600; }
        .aijob-modal-close {
            width: 32px; height: 32px; border-radius: var(--radius-md);
            border: none; background: transparent; color: var(--text-muted);
            cursor: pointer; font-size: 1.05rem; transition: var(--transition);
        }
        .aijob-modal-close:hover { background: var(--bg-tertiary); color: var(--text-primary); }

        .aijob-form-row { display: flex; flex-direction: column; gap: 6px; }
        .aijob-form-row label { font-size: 0.82rem; color: var(--text-secondary); font-weight: 600; }
        .aijob-form-row input, .aijob-form-row select {
            padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md);
            background: var(--bg-primary); color: var(--text-primary); font-size: 0.88rem;
            transition: var(--transition); font-family: inherit;
        }
        .aijob-form-row input:focus, .aijob-form-row select:focus {
            outline: none; border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px rgba(79,70,229,0.15);
        }

        .aijob-check-list {
            display: flex; flex-direction: column; gap: 4px; max-height: 168px; overflow-y: auto;
            border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 6px;
            background: var(--bg-primary);
        }
        .aijob-check-list label {
            display: flex; align-items: center; gap: 10px; font-size: 0.86rem; font-weight: 400;
            padding: 8px 10px; border-radius: var(--radius-sm); cursor: pointer; transition: var(--transition);
        }
        .aijob-check-list label:hover { background: var(--bg-tertiary); }
        .aijob-check-list input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent-primary); cursor: pointer; }
        .aijob-check-empty { color: var(--text-muted); font-size: 0.82rem; padding: 10px; }

        .aijob-modal-footer { display: flex; gap: 8px; justify-content: flex-end; padding-top: 4px; border-top: 1px solid var(--border-color); margin-top: 2px; }

        /* ── Kosum matrisi ────────────────────────────────────────────── */
        .aijob-matrix-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--radius-lg); background: var(--bg-secondary); }
        table.aijob-matrix { border-collapse: collapse; width: 100%; }
        table.aijob-matrix th, table.aijob-matrix td {
            border-bottom: 1px solid var(--border-color); padding: 11px 14px; font-size: 0.84rem; text-align: center;
        }
        table.aijob-matrix th {
            background: var(--bg-tertiary); color: var(--text-secondary); font-weight: 600;
            font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em;
            position: sticky; top: 0;
        }
        table.aijob-matrix tbody tr:last-child td { border-bottom: none; }
        table.aijob-matrix tbody tr:hover td { background: var(--bg-primary); }
        table.aijob-matrix td.aijob-scenario-name { text-align: left; font-weight: 500; white-space: nowrap; color: var(--text-primary); }

        .aijob-cell-status {
            display: inline-flex; align-items: center; gap: 5px;
            padding: 4px 12px; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
            cursor: pointer; transition: var(--transition); border: 1px solid transparent;
        }
        .aijob-cell-status:hover { transform: translateY(-1px); box-shadow: var(--shadow-sm); }
        .aijob-cell-queued  { background: var(--bg-tertiary); color: var(--text-muted); }
        .aijob-cell-running { background: rgba(245,158,11,0.14); color: var(--warning); animation: runPulse 1.2s infinite; }
        .aijob-cell-pass    { background: rgba(16,185,129,0.14); color: var(--success); }
        .aijob-cell-fail    { background: rgba(239,68,68,0.14); color: var(--danger); }
        .aijob-cell-error   { background: rgba(245,158,11,0.2); color: #b45309; }

        @keyframes aijob-fade-up { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        .aijob-step-line { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: var(--radius-sm); background: var(--bg-primary); font-size: 0.85rem; }
        .aijob-step-line.pass { border-left: 3px solid var(--success); }
        .aijob-step-line.fail { border-left: 3px solid var(--danger); }
        .aijob-terminal {
            background: #0d1117; color: #e6edf3; padding: 14px; border-radius: var(--radius-md);
            overflow: auto; max-height: 300px; font-size: 0.78rem; margin-top: 4px;
            font-family: 'JetBrains Mono', monospace; white-space: pre-wrap; line-height: 1.6;
        }

        @media (max-width: 640px) {
            .page-content { padding: 16px; }
            .aijob-card { flex-direction: column; align-items: flex-start; }
            .aijob-card-actions { width: 100%; }
        }
    </style>
</head>
<body>
<div id="app-root">
    <div id="sidebar-container"></div>
    <div class="main-content">
        <header class="top-bar"><span class="top-bar-title" id="topBarTitle">🗓️ Mobil Job'lar</span></header>
        <div class="page-content">

            <div class="aijob-tabs" id="platformTabs">
                <button class="aijob-tab active" data-platform="mobile" onclick="switchPlatform('mobile')">📱 Mobil</button>
                <button class="aijob-tab" data-platform="web" onclick="switchPlatform('web')">🌐 Web</button>
                <button class="aijob-tab" data-platform="desktop" onclick="switchPlatform('desktop')">🖥️ Desktop</button>
            </div>

            <div class="aijob-toolbar">
                <span class="aijob-toolbar-title">📋 Job Listesi <span class="aijob-toolbar-count" id="jobCount">0</span></span>
                <button class="aijob-btn aijob-btn-secondary" onclick="loadJobs()">↺ Yenile</button>
                <button class="aijob-btn aijob-btn-primary" onclick="openJobModal()">+ Yeni Job</button>
            </div>
            <div id="jobListWrap"><div class="aijob-empty">Yükleniyor...</div></div>

            <div class="aijob-toolbar" style="margin-top:32px;">
                <span class="aijob-toolbar-title">🧩 Koşum Matrisi</span>
                <button class="aijob-btn aijob-btn-danger" id="stopRunBtn" style="display:none;" onclick="stopCurrentRun()">⏹ Durdur</button>
            </div>
            <div id="matrixWrap"><div class="aijob-empty"><div class="empty-state-icon">🧩</div><div class="aijob-empty-desc">Bir job çalıştırınca burada görünecek.</div></div></div>
        </div>
    </div>
</div>

<!-- Job Olustur/Duzenle Modal -->
<div id="jobModal" class="aijob-modal-overlay">
    <div class="aijob-modal-box">
        <div class="aijob-modal-header">
            <strong class="aijob-modal-title" id="jobModalTitle">Yeni Job</strong>
            <button class="aijob-modal-close" onclick="closeJobModal()" aria-label="Kapat">✕</button>
        </div>
        <input type="hidden" id="jobEditId" value="">
        <div class="aijob-form-row">
            <label for="jobName">Job Adı</label>
            <input type="text" id="jobName" placeholder="Ör: Sabah Regresyon Paketi">
        </div>
        <div class="aijob-form-row">
            <label>Senaryolar</label>
            <div class="aijob-check-list" id="scenarioCheckList"></div>
        </div>
        <div class="aijob-form-row" id="unitFormRow">
            <label id="unitLabel">Cihazlar (ADB)</label>
            <div class="aijob-check-list" id="deviceCheckList"></div>
        </div>
        <div class="aijob-form-row">
            <label for="scheduleType">Zamanlama</label>
            <select id="scheduleType" onchange="onScheduleTypeChange()">
                <option value="">Zamanlama yok (manuel çalıştır)</option>
                <option value="once">Tek seferlik</option>
                <option value="daily">Her gün tekrarla</option>
                <option value="weekly">Her hafta tekrarla</option>
            </select>
        </div>
        <div class="aijob-form-row" id="scheduleAtRow" style="display:none;">
            <label for="scheduleAt">İlk çalışma zamanı</label>
            <input type="datetime-local" id="scheduleAt">
        </div>
        <div class="aijob-modal-footer">
            <button class="aijob-btn aijob-btn-secondary" onclick="closeJobModal()">Vazgeç</button>
            <button class="aijob-btn aijob-btn-primary" onclick="saveJob()">Kaydet</button>
        </div>
    </div>
</div>

<!-- Hucre Detay Modal -->
<div id="cellModal" class="aijob-modal-overlay">
    <div class="aijob-modal-box">
        <div class="aijob-modal-header">
            <strong class="aijob-modal-title" id="cellModalTitle">Hücre Detayı</strong>
            <button class="aijob-modal-close" onclick="closeCellModal()" aria-label="Kapat">✕</button>
        </div>
        <div id="cellModalBody"></div>
    </div>
</div>

<script src="js/app.js"></script>
<script src="js/sidebar.js"></script>
<script>
(function () {
    "use strict";
    if (!Auth.checkAuth()) return;

    const PLATFORM_META = {
        mobile:  { title: "Mobil Job'lar",  icon: '📱', unitLabel: 'Cihazlar (ADB)', emptyUnit: 'Bağlı ADB cihazı yok — bir telefon/emülatör bağlayın.' },
        web:     { title: "Web Job'lar",    icon: '🌐', unitLabel: 'Tarayıcılar',    emptyUnit: 'Tarayıcı bulunamadı.' },
        desktop: { title: "Desktop Job'lar", icon: '🖥️', unitLabel: '',              emptyUnit: '' },
    };
    const WEB_BROWSERS = [
        { id: 'chrome',  name: 'Chrome' },
        { id: 'firefox', name: 'Firefox' },
        { id: 'edge',    name: 'Edge' },
    ];

    let currentPlatform = 'mobile';
    let scenarios = [];
    let units = [];   // mobile: ADB cihazlari [{id,name}]; web: WEB_BROWSERS; desktop: []
    let currentRunId = null;
    let currentRunCells = {};   // cell_id -> cell dict
    let ws = null;

    async function init() {
        await Promise.all([loadJobs(), loadScenariosAndUnits()]);
    }

    window.switchPlatform = async function switchPlatform(platform) {
        currentPlatform = platform;
        document.querySelectorAll('.aijob-tab').forEach(t => t.classList.toggle('active', t.dataset.platform === platform));
        document.getElementById('topBarTitle').textContent = `🗓️ ${PLATFORM_META[platform].title}`;
        currentRunId = null;
        currentRunCells = {};
        if (ws) { try { ws.close(); } catch (e) {} }
        document.getElementById('matrixWrap').innerHTML = '<div class="aijob-empty"><div class="empty-state-icon">🧩</div><div class="aijob-empty-desc">Bir job çalıştırınca burada görünecek.</div></div>';
        document.getElementById('stopRunBtn').style.display = 'none';
        await Promise.all([loadJobs(), loadScenariosAndUnits()]);
    };

    async function loadScenariosAndUnits() {
        try {
            const sRes = await API.get('/ai-gen/scenarios');
            scenarios = (sRes.scenarios || []).filter(s => s.platform === currentPlatform);
        } catch (e) { scenarios = []; }

        if (currentPlatform === 'mobile') {
            try {
                const dRes = await API.get('/ai-gen/adb/devices');
                units = (dRes.devices || []).map(id => ({ id, name: id }));
            } catch (e) { units = []; }
        } else if (currentPlatform === 'web') {
            units = WEB_BROWSERS;
        } else {
            units = [];
        }
    }

    window.loadJobs = async function loadJobs() {
        const wrap = document.getElementById('jobListWrap');
        wrap.innerHTML = '<div class="aijob-empty">Yükleniyor...</div>';
        try {
            const res = await API.get(`/ai-jobs?platform=${currentPlatform}`);
            const jobs = res.jobs || [];
            document.getElementById('jobCount').textContent = jobs.length;
            if (!jobs.length) {
                wrap.innerHTML = '<div class="aijob-empty"><div class="empty-state-icon">📅</div><div class="aijob-empty-title">Henüz job yok</div><div class="aijob-empty-desc">"+ Yeni Job" ile senaryo × koşum paketi oluşturun.</div></div>';
                return;
            }
            wrap.innerHTML = '<div class="aijob-list">' + jobs.map(renderJobCard).join('') + '</div>';
        } catch (e) {
            wrap.innerHTML = `<div class="aijob-empty"><div class="empty-state-icon">⚠️</div><div class="aijob-empty-desc aijob-empty-err">Hata: ${escapeHtml(e.message)}</div></div>`;
        }
    };

    function renderJobCard(job) {
        const schedChip = job.schedule
            ? `<span class="aijob-chip aijob-chip-schedule${job.schedule.enabled ? '' : ' is-paused'}">⏱ ${scheduleLabel(job.schedule)}</span>`
            : `<span class="aijob-chip">🖐 Manuel</span>`;
        const unitChip = job.platform === 'desktop' ? '' : `<span class="aijob-chip">📶 ${job.devices.length} ${job.platform === 'web' ? 'tarayıcı' : 'cihaz'}</span>`;
        return `
            <div class="aijob-card">
                <div class="aijob-card-icon">${(PLATFORM_META[job.platform] || {}).icon || '🧪'}</div>
                <div class="aijob-card-body">
                    <div class="aijob-card-name">${escapeHtml(job.name)}</div>
                    <div class="aijob-card-meta">
                        <span class="aijob-chip">🧪 ${job.scenarios.length} senaryo</span>
                        ${unitChip}
                        ${schedChip}
                    </div>
                </div>
                <div class="aijob-card-actions">
                    <button class="aijob-btn aijob-btn-primary aijob-btn-sm" onclick="runJob(${job.id})">▶ Çalıştır</button>
                    <button class="aijob-btn aijob-btn-secondary aijob-btn-sm" onclick="editJob(${job.id})">✎ Düzenle</button>
                    <button class="aijob-btn aijob-btn-secondary aijob-btn-sm" onclick="showRuns(${job.id})">🕒 Geçmiş</button>
                    <button class="aijob-btn aijob-btn-danger aijob-btn-sm" onclick="deleteJob(${job.id})">🗑</button>
                </div>
            </div>`;
    }

    function scheduleLabel(sched) {
        const typeMap = { once: 'Tek seferlik', daily: 'Her gün', weekly: 'Her hafta' };
        const dt = new Date(sched.run_at).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' });
        return `${typeMap[sched.schedule_type] || sched.schedule_type} — ${dt}${sched.enabled ? '' : ' (pasif)'}`;
    }

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // UTC ISO string ("2026-07-26T09:00:00Z") -> datetime-local degeri ("2026-07-26T09:00" yerel saatte)
    function utcToLocalInput(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        const pad = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    window.openJobModal = function openJobModal(job) {
        document.getElementById('jobEditId').value = job ? job.id : '';
        document.getElementById('jobModalTitle').textContent = job ? 'Job Düzenle' : 'Yeni Job';
        document.getElementById('jobName').value = job ? job.name : '';

        const scList = document.getElementById('scenarioCheckList');
        scList.innerHTML = scenarios.length
            ? scenarios.map(s => `<label><input type="checkbox" value="${escapeHtml(s.folder)}" ${job && job.scenarios.includes(s.folder) ? 'checked' : ''}> ${escapeHtml(s.name)}</label>`).join('')
            : `<div class="aijob-check-empty">${currentPlatform} senaryosu bulunamadı — önce AI Test Generator'da bir senaryo kaydedin.</div>`;

        const unitRow = document.getElementById('unitFormRow');
        if (currentPlatform === 'desktop') {
            unitRow.style.display = 'none';
        } else {
            unitRow.style.display = 'flex';
            document.getElementById('unitLabel').textContent = PLATFORM_META[currentPlatform].unitLabel;
            const unitList = document.getElementById('deviceCheckList');
            const jobUnitIds = job ? job.devices.map(d => d.device_id) : [];
            unitList.innerHTML = units.length
                ? units.map(u => `<label><input type="checkbox" value="${escapeHtml(u.id)}" ${jobUnitIds.includes(u.id) ? 'checked' : ''}> ${escapeHtml(u.name)}</label>`).join('')
                : `<div class="aijob-check-empty">${PLATFORM_META[currentPlatform].emptyUnit}</div>`;
        }

        const schedSel = document.getElementById('scheduleType');
        schedSel.value = job && job.schedule ? job.schedule.schedule_type : '';
        onScheduleTypeChange();
        if (job && job.schedule) {
            // run_at UTC ("...Z") geliyor; datetime-local girdisi YEREL saat bekler.
            // saveJob'daki yerel→UTC (toISOString) dönüşümünün tersi yapılır, aksi
            // halde her düzenlemede kayıt UTC farkı kadar kayardı.
            document.getElementById('scheduleAt').value = utcToLocalInput(job.schedule.run_at);
        } else {
            document.getElementById('scheduleAt').value = '';
        }

        document.getElementById('jobModal').classList.add('active');
    };

    window.closeJobModal = function closeJobModal() {
        document.getElementById('jobModal').classList.remove('active');
    };

    window.onScheduleTypeChange = function onScheduleTypeChange() {
        const type = document.getElementById('scheduleType').value;
        document.getElementById('scheduleAtRow').style.display = type ? 'flex' : 'none';
    };

    window.editJob = async function editJob(jobId) {
        const job = await API.get(`/ai-jobs/${jobId}`);
        openJobModal(job);
    };

    window.saveJob = async function saveJob() {
        const editId = document.getElementById('jobEditId').value;
        const name = document.getElementById('jobName').value.trim();
        const scenario_folders = Array.from(document.querySelectorAll('#scenarioCheckList input:checked')).map(el => el.value);
        const device_ids = currentPlatform === 'desktop'
            ? []
            : Array.from(document.querySelectorAll('#deviceCheckList input:checked')).map(el => el.value);
        const schedType = document.getElementById('scheduleType').value;

        if (!name) { alert('Job adı gerekli'); return; }
        if (!scenario_folders.length) { alert('En az bir senaryo seçin'); return; }
        if (currentPlatform !== 'desktop' && !device_ids.length) {
            alert(currentPlatform === 'web' ? 'En az bir tarayıcı seçin' : 'En az bir cihaz seçin');
            return;
        }

        let schedule = null;
        if (schedType) {
            const at = document.getElementById('scheduleAt').value;
            if (!at) { alert('Zamanlama seçtiyseniz bir tarih/saat girin'); return; }
            schedule = { schedule_type: schedType, run_at: new Date(at).toISOString() };
        }

        const body = { name, platform: currentPlatform, scenario_folders, device_ids, schedule };
        try {
            if (editId) {
                await API.put(`/ai-jobs/${editId}`, body);
            } else {
                await API.post('/ai-jobs', body);
            }
            closeJobModal();
            loadJobs();
        } catch (e) {
            alert('Kaydedilemedi: ' + e.message);
        }
    };

    window.deleteJob = async function deleteJob(jobId) {
        if (!confirm('Bu job silinsin mi?')) return;
        await API.delete(`/ai-jobs/${jobId}`);
        loadJobs();
    };

    window.runJob = async function runJob(jobId) {
        try {
            const res = await API.post(`/ai-jobs/${jobId}/run`, {});
            openRunMatrix(res.run_id);
        } catch (e) {
            alert('Çalıştırılamadı: ' + e.message);
        }
    };

    window.showRuns = async function showRuns(jobId) {
        const res = await API.get(`/ai-jobs/${jobId}/runs`);
        const runs = res.runs || [];
        if (!runs.length) { alert('Bu job için henüz koşum yok'); return; }
        openRunMatrix(runs[0].id);
    };

    async function openRunMatrix(runId) {
        currentRunId = runId;
        const run = await API.get(`/ai-jobs/runs/${runId}`);
        currentRunCells = {};
        run.cells.forEach(c => currentRunCells[c.id] = c);
        renderMatrix();
        connectWs(runId);
        document.getElementById('stopRunBtn').style.display = run.status === 'running' ? 'inline-flex' : 'none';
    }

    window.stopCurrentRun = async function stopCurrentRun() {
        if (!currentRunId) return;
        await API.post(`/ai-jobs/runs/${currentRunId}/stop`, {});
        document.getElementById('stopRunBtn').style.display = 'none';
    };

    function renderMatrix() {
        const cells = Object.values(currentRunCells);
        const wrap = document.getElementById('matrixWrap');
        if (!cells.length) {
            wrap.innerHTML = '<div class="aijob-empty"><div class="empty-state-icon">🧩</div><div class="aijob-empty-desc">Hücre bulunamadı.</div></div>';
            return;
        }
        const scenarioFolders = [...new Set(cells.map(c => c.scenario_folder))];
        const devices = [...new Set(cells.map(c => c.device_id))];

        let html = '<div class="aijob-matrix-wrap"><table class="aijob-matrix"><thead><tr><th>Senaryo</th>';
        devices.forEach(d => html += `<th>${d === 'desktop' ? 'Sonuç' : escapeHtml(d)}</th>`);
        html += '</tr></thead><tbody>';
        scenarioFolders.forEach(sc => {
            const scName = cells.find(c => c.scenario_folder === sc)?.scenario_name || sc;
            html += `<tr><td class="aijob-scenario-name">${escapeHtml(scName)}</td>`;
            devices.forEach(d => {
                const cell = cells.find(c => c.scenario_folder === sc && c.device_id === d);
                html += `<td>${cell ? cellBadge(cell) : '-'}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        wrap.innerHTML = html;
    }

    function cellBadge(cell) {
        const labelMap = { queued: '⏳ Bekliyor', running: '⚡ Koşuyor', pass: '✓ Başarılı', fail: '✗ Başarısız', error: '⚠ Hata' };
        return `<span class="aijob-cell-status aijob-cell-${cell.status}" onclick="showCellDetail(${cell.id})">${labelMap[cell.status] || cell.status}</span>`;
    }

    window.showCellDetail = function showCellDetail(cellId) {
        const cell = currentRunCells[cellId];
        if (!cell) return;
        document.getElementById('cellModalTitle').textContent = `${cell.scenario_name} — ${cell.device_id === 'desktop' ? 'Masaüstü' : cell.device_id}`;
        const steps = (cell.log && cell.log.steps) || [];
        const terminal = (cell.log && cell.log.terminal) || (cell.log && cell.log.error) || '';
        let body = `<div style="font-size:0.82rem;color:var(--text-muted);">Durum: ${escapeHtml(cell.status)}</div>`;
        if (steps.length) {
            body += '<div style="display:flex;flex-direction:column;gap:6px;margin-top:8px;">';
            steps.forEach(s => {
                const ok = s.status === 'pass';
                body += `<div class="aijob-step-line ${ok ? 'pass' : 'fail'}">${ok ? '✓' : '✗'}&nbsp; Adım ${s.index}</div>`;
            });
            body += '</div>';
        }
        if (terminal) {
            body += `<pre class="aijob-terminal">${escapeHtml(terminal)}</pre>`;
        }
        document.getElementById('cellModalBody').innerHTML = body;
        document.getElementById('cellModal').classList.add('active');
    };

    window.closeCellModal = function closeCellModal() {
        document.getElementById('cellModal').classList.remove('active');
    };

    // Backdrop tiklamasi ve ESC ile kapatma (her iki modal icin ortak)
    document.querySelectorAll('.aijob-modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) overlay.classList.remove('active');
        });
    });
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') {
            document.querySelectorAll('.aijob-modal-overlay.active').forEach(o => o.classList.remove('active'));
        }
    });

    function connectWs(runId) {
        if (ws) { try { ws.close(); } catch (e) {} }
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${window.location.hostname}:8000/api/ai-jobs/ws/${runId}`);
        ws.onmessage = (ev) => {
            const event = JSON.parse(ev.data);
            if (event.type === 'cell_update' && currentRunCells[event.cell_id]) {
                currentRunCells[event.cell_id].status = event.status;
                renderMatrix();
            } else if (event.type === 'run_completed') {
                document.getElementById('stopRunBtn').style.display = 'none';
                openRunMatrix(runId);  // final hali cek (log_json dahil)
            }
        };
    }

    init();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Delete the old mobile-only page**

```bash
rm "backend/WebArayuz/ai-jobs-mobile.html"
```

- [ ] **Step 3: Update the sidebar link**

In `backend/WebArayuz/js/sidebar.js`, replace the line (currently line 70):

```javascript
                + item("ai-jobs-mobile","&#128197;", "Mobil Job'lar")
```

with:

```javascript
                + item("ai-jobs",       "&#128197;", "AI Job'lar")
```

- [ ] **Step 4: Confirm no other file references the deleted page**

```bash
grep -rl "ai-jobs-mobile" "backend/WebArayuz" || echo "NO REFERENCES LEFT"
```
Expected: `NO REFERENCES LEFT` (any hit here besides the deleted file itself means a link was missed).

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/ai-jobs.html backend/WebArayuz/js/sidebar.js
git add -u backend/WebArayuz/ai-jobs-mobile.html
git commit -m "ai-job: ai-jobs-mobile.html -> ai-jobs.html, Mobil/Web/Desktop sekmeleri eklendi"
```

---

### Task 6: Manual end-to-end verification

**Files:** none (verification only)

This system touches a running server, real browsers, and (for mobile/desktop) real devices/apps — there is no way to automate this in the current codebase, so it's a manual pass. Do this after Tasks 1-5 are committed.

- [ ] **Step 1: Start the server**

```bash
cd backend && python main.py
```
Expected: server starts on `http://localhost:8000` without traceback; open `http://localhost:8000/ui/ai-jobs.html` in a browser, log in, confirm the three tabs (Mobil/Web/Desktop) render and "Mobil" is active by default.

- [ ] **Step 2: Web job — parallel browsers**

In the AI Test Generator page, save at least 2 Web scenarios (platform="web", each with a `target_url`). Switch to the **Web** tab in AI Job'lar, create a job selecting both scenarios and both Chrome+Firefox, click "Çalıştır". Confirm: the run matrix shows 2 rows × 2 columns (`chrome`, `firefox`), both columns progress independently (roughly in parallel), and each cell reaches `pass`/`fail`/`error` with a WS-driven live update (no manual refresh needed).

- [ ] **Step 3: Desktop job — sequential, single column**

Save at least 2 Desktop scenarios. Switch to the **Desktop** tab — confirm no cihaz/tarayıcı checklist is shown in "+ Yeni Job". Create a job with both scenarios, run it. Confirm: the matrix has exactly one column labeled "Sonuç", and the two scenarios visibly run one after another (not concurrently — the running app window should only show one automation active at a time).

- [ ] **Step 4: Desktop lock conflict**

While the Desktop job from Step 3 is running, go to the AI Test Generator page and try to manually execute a Desktop test ("Test Et" / `/execute`). Confirm it's rejected (423) while the job's desktop automation is active. Then, with no desktop job running, trigger a Desktop job while a manual desktop test is running — confirm the job is rejected via a clear error (not silently queued forever).

- [ ] **Step 5: Tab isolation sanity check**

Switch between Mobil/Web/Desktop tabs a few times. Confirm each tab only lists jobs/scenarios for its own platform, the sidebar's "AI Job'lar" link highlights as active on this page, and creating a job under one tab doesn't leak into another tab's job list.
