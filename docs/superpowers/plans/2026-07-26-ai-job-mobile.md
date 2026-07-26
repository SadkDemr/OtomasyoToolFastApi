# AI Test Generator — Mobil Job Sistemi (Faz 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI Test Generator'da kayıtlı mobil senaryoları, seçilen ADB cihazlarında matris halinde (senaryo × cihaz) paralel çalıştıran, manuel veya zamanlanmış (tek seferlik/tekrarlı) tetiklenebilen bir Job sistemi kurmak.

**Architecture:** Yeni DB tabloları (`AiJob*`) job tanımını ve koşum geçmişini tutar. `ai_job_service.py` her (senaryo, cihaz) hücresi için mevcut `_generate_steps`/`_build_mobile_template` fonksiyonlarını (ai_test_generator_router.py) yeniden kullanarak script üretir, bağımsız bir subprocess olarak çalıştırır, `asyncio.gather` ile tüm hücreleri paralel yürütür. Sonuçlar DB'ye yazılır, canlı güncellemeler in-memory `asyncio.Queue` pub/sub üzerinden WebSocket'e akar. Bir arka plan `asyncio` döngüsü (mevcut `_session_idle_reaper` deseniyle aynı) zamanlanmış job'ları tetikler.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (SQLite), asyncio, vanilla JS (mevcut `js/app.js` / `Auth` / `API` helper'ları).

## Global Constraints

- Bu repoda otomatik test framework'ü (pytest vs.) yok — doğrulama adımları sunucuyu çalıştırıp `curl`/tarayıcı ile yapılır (bkz. CLAUDE.md: "For UI or frontend changes ... test in a browser").
- Türkçe UI/yorum/metin konvansiyonu korunur.
- Eski `Job`/`JobScenario`/`JobDevice`/`JobExecution`/`TestResult`/`Scenario`/`Device` modellerine ve `job_service.py`'ye **dokunulmaz** — onlar hiçbir router'a bağlı değil, artık kullanılmıyorlar.
- Kayıtlı `script.py` içinde eski cihazın `device_id`'si gömülü olduğu için job motoru onu kullanmaz; her hücre için `steps.json`'daki `steps`/`params` ile script'i hedef cihaza göre **yeniden üretir**.
- Python venv: `backend\venv\Scripts\python.exe` (Windows).

---

### Task 1: DB Modelleri

**Files:**
- Modify: `backend/models/db_models.py` (dosya sonuna ekle)

**Interfaces:**
- Produces: `AiJob`, `AiJobScenario`, `AiJobDevice`, `AiJobSchedule`, `AiJobRun`, `AiJobRunResult` SQLAlchemy modelleri (Task 2+ bunları import edip kullanır).

- [ ] **Step 1: Modelleri dosya sonuna ekle**

`backend/models/db_models.py` dosyasının en altına ekle:

```python
# --- AI TEST GENERATOR: JOB SISTEMI (Faz 1: Mobil) ---
class AiJob(Base):
    __tablename__ = "ai_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, index=True)
    platform = Column(String, default="mobile")
    created_at = Column(DateTime, default=datetime.utcnow)

    scenarios = relationship("AiJobScenario", back_populates="job", cascade="all, delete-orphan")
    devices   = relationship("AiJobDevice",   back_populates="job", cascade="all, delete-orphan")
    schedule  = relationship("AiJobSchedule", back_populates="job", cascade="all, delete-orphan")
    runs      = relationship("AiJobRun",      back_populates="job", cascade="all, delete-orphan")


class AiJobScenario(Base):
    __tablename__ = "ai_job_scenarios"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    scenario_folder = Column(String)

    job = relationship("AiJob", back_populates="scenarios")


class AiJobDevice(Base):
    __tablename__ = "ai_job_devices"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    device_id = Column(String)
    device_name = Column(String, nullable=True)

    job = relationship("AiJob", back_populates="devices")


class AiJobSchedule(Base):
    __tablename__ = "ai_job_schedules"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    schedule_type = Column(String)  # 'once' | 'daily' | 'weekly'
    run_at = Column(DateTime)
    enabled = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)

    job = relationship("AiJob", back_populates="schedule")


class AiJobRun(Base):
    __tablename__ = "ai_job_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("ai_jobs.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")       # running | completed | interrupted
    trigger_type = Column(String, default="manual")  # manual | scheduled
    total_cells = Column(Integer, default=0)
    passed_cells = Column(Integer, default=0)
    failed_cells = Column(Integer, default=0)

    job = relationship("AiJob", back_populates="runs")
    results = relationship("AiJobRunResult", back_populates="job_run", cascade="all, delete-orphan")


class AiJobRunResult(Base):
    __tablename__ = "ai_job_run_results"

    id = Column(Integer, primary_key=True, index=True)
    job_run_id = Column(Integer, ForeignKey("ai_job_runs.id"))
    scenario_folder = Column(String)
    scenario_name = Column(String, nullable=True)
    device_id = Column(String)
    device_name = Column(String, nullable=True)
    status = Column(String, default="queued")  # queued | running | pass | fail | error
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    log_json = Column(Text, nullable=True)

    job_run = relationship("AiJobRun", back_populates="results")
```

- [ ] **Step 2: Tabloların oluştuğunu doğrula**

Run (proje kökünden):
```bash
cd backend && venv/Scripts/python.exe -c "from database import init_db; init_db(); import sqlite3; c = sqlite3.connect('test_platform.db'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ai_job%'\")])"
```
Expected: `['ai_jobs', 'ai_job_scenarios', 'ai_job_devices', 'ai_job_schedules', 'ai_job_runs', 'ai_job_run_results']` (sıra farklı olabilir, hepsi listede olmalı).

- [ ] **Step 3: Commit**

```bash
git add backend/models/db_models.py
git commit -m "AI Job sistemi icin DB modelleri eklendi (Faz 1: Mobil)"
```

---

### Task 2: Job CRUD servisi

**Files:**
- Create: `backend/services/ai_job_service.py`

**Interfaces:**
- Consumes: `AiJob`, `AiJobScenario`, `AiJobDevice`, `AiJobSchedule` (Task 1)
- Produces: `create_job(db, user_id, name, scenario_folders, device_ids, schedule) -> AiJob`, `list_jobs(db, user_id) -> list[AiJob]`, `get_job(db, job_id, user_id) -> AiJob | None`, `update_job(db, job_id, name, scenario_folders, device_ids, schedule) -> AiJob`, `delete_job(db, job_id) -> None`, `job_to_dict(job) -> dict` — Task 4 (router) bunları çağırır.

- [ ] **Step 1: Servis dosyasını oluştur (CRUD bölümü)**

`backend/services/ai_job_service.py`:

```python
"""
AI Test Generator — Job Servisi (Faz 1: Mobil)
CRUD + çalıştırma motoru + zamanlayıcı.
"""
import asyncio
import json as _json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from models.db_models import (
    AiJob, AiJobScenario, AiJobDevice, AiJobSchedule,
    AiJobRun, AiJobRunResult,
)


class JobAlreadyRunningError(Exception):
    pass


# ══════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════

def create_job(
    db: Session, user_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None,
) -> AiJob:
    job = AiJob(user_id=user_id, name=name, platform="mobile")
    db.add(job)
    db.commit()
    db.refresh(job)

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job.id, scenario_folder=folder))
    for device_id in device_ids:
        db.add(AiJobDevice(job_id=job.id, device_id=device_id, device_name=device_id))
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


def list_jobs(db: Session, user_id: int) -> list[AiJob]:
    return db.query(AiJob).filter(AiJob.user_id == user_id).order_by(AiJob.created_at.desc()).all()


def get_job(db: Session, job_id: int, user_id: int) -> AiJob | None:
    return db.query(AiJob).filter(AiJob.id == job_id, AiJob.user_id == user_id).first()


def update_job(
    db: Session, job_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None,
) -> AiJob:
    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    job.name = name

    db.query(AiJobScenario).filter(AiJobScenario.job_id == job_id).delete()
    db.query(AiJobDevice).filter(AiJobDevice.job_id == job_id).delete()
    db.query(AiJobSchedule).filter(AiJobSchedule.job_id == job_id).delete()

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job_id, scenario_folder=folder))
    for device_id in device_ids:
        db.add(AiJobDevice(job_id=job_id, device_id=device_id, device_name=device_id))
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


def delete_job(db: Session, job_id: int) -> None:
    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    if job:
        db.delete(job)
        db.commit()


def job_to_dict(job: AiJob) -> dict:
    sched = job.schedule[0] if job.schedule else None
    return {
        "id": job.id,
        "name": job.name,
        "platform": job.platform,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "scenarios": [s.scenario_folder for s in job.scenarios],
        "devices": [{"device_id": d.device_id, "device_name": d.device_name} for d in job.devices],
        "schedule": ({
            "schedule_type": sched.schedule_type,
            "run_at": sched.run_at.isoformat(),
            "enabled": sched.enabled,
            "last_triggered_at": sched.last_triggered_at.isoformat() if sched.last_triggered_at else None,
        } if sched else None),
    }
```

- [ ] **Step 2: CRUD'u python REPL üzerinden doğrula**

Run:
```bash
cd backend && venv/Scripts/python.exe -c "
from database import SessionLocal, init_db
init_db()
from services import ai_job_service as s
db = SessionLocal()
job = s.create_job(db, user_id=1, name='Test Job', scenario_folders=['deneme'], device_ids=['emulator-5554'], schedule=None)
print('created:', s.job_to_dict(job))
jobs = s.list_jobs(db, 1)
print('listed:', len(jobs))
s.delete_job(db, job.id)
print('deleted, remaining:', len(s.list_jobs(db, 1)))
"
```
Expected: `created: {...}` sözlüğü isim/senaryo/cihaz alanlarıyla basılır, `listed: 1`, `deleted, remaining: 0`. (user_id=1 DB'de olmayabilir — FK zorunlu değil çünkü SQLite'ta varsayılan olarak FK constraint kapalı, hata vermez.)

- [ ] **Step 3: Commit**

```bash
git add backend/services/ai_job_service.py
git commit -m "AI Job CRUD servisi eklendi"
```

---

### Task 3: Çalıştırma motoru (script üretimi + paralel koşum + pub/sub)

**Files:**
- Modify: `backend/services/ai_job_service.py` (aynı dosyaya ekleme)

**Interfaces:**
- Consumes: `ai_test_generator_router.GenerateRequest`, `StepItem`, `_generate_steps`, `_build_mobile_template`, `_get_user_workspace` (mevcut, `backend/routers/ai_test_generator_router.py`); Task 1 modelleri; Task 2 CRUD fonksiyonları.
- Produces: `async def run_job(job_id, db, trigger_type="manual") -> int` (run_id döner), `def stop_run(run_id) -> None`, `def subscribe(run_id) -> asyncio.Queue`, `def unsubscribe(run_id, q) -> None`, `list_runs(db, job_id) -> list[AiJobRun]`, `get_run(db, run_id) -> AiJobRun | None`, `run_to_dict(run, include_cells=False) -> dict` — Task 4 (router) ve Task 5 (scheduler) bunları kullanır.

- [ ] **Step 1: Importları ve pub/sub altyapısını dosya başına ekle**

`backend/services/ai_job_service.py` dosyasının import bloğuna ekle (mevcut importların altına):

```python
import os
import subprocess
import sys
import tempfile
```

Dosyanın CRUD bölümünden sonra, dosya sonuna ekle:

```python
# ══════════════════════════════════════════════════════════════
# CANLI GUNCELLEME PUB/SUB (in-memory, run_id -> Queue listesi)
# ══════════════════════════════════════════════════════════════

_run_event_queues: dict[int, list[asyncio.Queue]] = {}
_active_procs: dict[int, "subprocess.Popen"] = {}   # cell_id -> proc
_stopped_runs: set[int] = set()


def subscribe(run_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _run_event_queues.setdefault(run_id, []).append(q)
    return q


def unsubscribe(run_id: int, q: asyncio.Queue) -> None:
    subs = _run_event_queues.get(run_id, [])
    if q in subs:
        subs.remove(q)
    if run_id in _run_event_queues and not _run_event_queues[run_id]:
        _run_event_queues.pop(run_id, None)


async def _publish(run_id: int, event: dict) -> None:
    for q in list(_run_event_queues.get(run_id, [])):
        await q.put(event)


def stop_run(run_id: int) -> None:
    """Kuyruktaki hücrelerin başlamasını engeller, çalışanları terminate eder."""
    _stopped_runs.add(run_id)
    from database import SessionLocal
    db = SessionLocal()
    try:
        cells = db.query(AiJobRunResult).filter(
            AiJobRunResult.job_run_id == run_id,
            AiJobRunResult.status.in_(["queued", "running"]),
        ).all()
        for c in cells:
            proc = _active_procs.get(c.id)
            if proc and proc.poll() is None:
                proc.terminate()
    finally:
        db.close()
```

- [ ] **Step 2: Tek hücre script üretimi ve subprocess koşumu**

Dosya sonuna ekle:

```python
# ══════════════════════════════════════════════════════════════
# TEK HUCRE: SCRIPT URETIMI + SUBPROCESS KOSUMU
# ══════════════════════════════════════════════════════════════

async def _generate_cell_script(steps_data: dict, device_id: str) -> str:
    """steps.json icerigini hedef cihaza gore script'e derler (kayitli script.py KULLANILMAZ)."""
    from routers.ai_test_generator_router import (
        GenerateRequest, StepItem, _generate_steps, _build_mobile_template,
    )
    params = steps_data.get("params", {}) or {}
    steps_list = [StepItem(**s) for s in steps_data.get("steps", [])]
    req = GenerateRequest(
        steps_list=steps_list,
        platform="mobile",
        device_id=device_id,
        app_package=params.get("app_package", ""),
        app_activity=params.get("app_activity", ""),
        appium_url=params.get("appium_url") or "http://localhost:4723",
    )
    steps_code, _report = await _generate_steps(req)
    return _build_mobile_template(req, steps_code)


async def _run_cell(script: str, cell_id: int) -> dict:
    """Script'i bagimsiz bir subprocess olarak calistirir, adim sonuclarini toplar.
    /execute endpoint'inden bagimsizdir (SSE yok) — job motoru paralel hucreler icin bunu kullanir."""
    step_outcomes: dict[int, str] = {}
    terminal_lines: list[str] = []

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_job_cell_"
    ) as f:
        f.write(script)
        tmp = f.name

    popen_kw: dict = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen([sys.executable, tmp], **popen_kw)
    _active_procs[cell_id] = proc
    exit_code = -1
    try:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, proc.stdout.readline)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text.startswith("STEP_DONE:"):
                idx_s = text.split(":", 1)[1].strip()
                try: step_outcomes[int(idx_s)] = "pass"
                except ValueError: pass
            elif text.startswith("STEP_FAIL:"):
                idx_s = text.split(":", 1)[1].strip()
                try: step_outcomes[int(idx_s)] = "fail"
                except ValueError: pass
            elif not text.startswith("STEP_START:"):
                terminal_lines.append(text)

        await loop.run_in_executor(None, proc.wait)
        exit_code = proc.returncode
    finally:
        _active_procs.pop(cell_id, None)
        try:
            os.unlink(tmp)
        except Exception:
            pass

    if exit_code == 0 and all(v == "pass" for v in step_outcomes.values()):
        status = "pass"
    elif exit_code == 0:
        status = "fail"
    else:
        status = "error"

    return {
        "status": status,
        "exit_code": exit_code,
        "steps": [{"index": i, "status": v} for i, v in sorted(step_outcomes.items())],
        "terminal": "\n".join(terminal_lines[-200:]),
    }
```

- [ ] **Step 3: Hücre koordinasyonu ve run_job motoru**

Dosya sonuna ekle:

```python
# ══════════════════════════════════════════════════════════════
# HUCRE KOORDINASYONU + RUN_JOB MOTORU
# ══════════════════════════════════════════════════════════════

async def _execute_cell(run_id: int, cell_id: int, steps_data: dict | None, device_id: str) -> None:
    from database import SessionLocal
    db = SessionLocal()
    try:
        cell = db.query(AiJobRunResult).filter(AiJobRunResult.id == cell_id).first()
        if not cell:
            return

        if run_id in _stopped_runs:
            cell.status = "error"
            cell.log_json = _json.dumps({"error": "Koşum durduruldu"})
            db.commit()
            await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
            return

        cell.status = "running"
        cell.started_at = datetime.utcnow()
        db.commit()
        await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "running"})

        if not steps_data:
            cell.status = "error"
            cell.ended_at = datetime.utcnow()
            cell.log_json = _json.dumps({"error": "Senaryo dosyası okunamadı"})
            db.commit()
            await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
            return

        try:
            script = await _generate_cell_script(steps_data, device_id)
            result = await _run_cell(script, cell_id)
            cell.status = result["status"]
            cell.log_json = _json.dumps(result)
        except Exception as e:
            cell.status = "error"
            cell.log_json = _json.dumps({"error": str(e)})

        cell.ended_at = datetime.utcnow()
        db.commit()
        await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": cell.status})
    finally:
        db.close()


async def run_job(job_id: int, db: Session, trigger_type: str = "manual") -> int:
    from routers.ai_test_generator_router import _get_user_workspace

    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    if not job:
        raise ValueError("Job bulunamadı")

    already = db.query(AiJobRun).filter(AiJobRun.job_id == job_id, AiJobRun.status == "running").first()
    if already:
        raise JobAlreadyRunningError(f"Job {job_id} zaten çalışıyor (run_id={already.id})")

    scenario_folders = [s.scenario_folder for s in job.scenarios]
    devices = [(d.device_id, d.device_name) for d in job.devices]
    if not scenario_folders or not devices:
        raise ValueError("Job'da senaryo veya cihaz tanımlı değil")

    ws = _get_user_workspace(job.user_id, db)
    if not ws:
        raise ValueError("Kullanıcının git workspace'i bulunamadı")

    run = AiJobRun(
        job_id=job_id, started_at=datetime.utcnow(), status="running",
        trigger_type=trigger_type, total_cells=len(scenario_folders) * len(devices),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    scenario_data: dict[str, dict] = {}
    for folder in scenario_folders:
        steps_file = Path(ws.local_path) / "ai_scenarios" / folder / "steps.json"
        if steps_file.exists():
            scenario_data[folder] = _json.loads(steps_file.read_text(encoding="utf-8"))

    cells: list[AiJobRunResult] = []
    for folder in scenario_folders:
        data = scenario_data.get(folder)
        name = data.get("name", folder) if data else folder
        for device_id, device_name in devices:
            cell = AiJobRunResult(
                job_run_id=run.id, scenario_folder=folder, scenario_name=name,
                device_id=device_id, device_name=device_name or device_id, status="queued",
            )
            db.add(cell)
            cells.append(cell)
    db.commit()
    for c in cells:
        db.refresh(c)

    await _publish(run.id, {"type": "run_started", "run_id": run.id, "total": len(cells)})

    await asyncio.gather(*[
        _execute_cell(run.id, cell.id, scenario_data.get(cell.scenario_folder), cell.device_id)
        for cell in cells
    ])

    _stopped_runs.discard(run.id)

    results = db.query(AiJobRunResult).filter(AiJobRunResult.job_run_id == run.id).all()
    run.passed_cells = sum(1 for r in results if r.status == "pass")
    run.failed_cells = sum(1 for r in results if r.status in ("fail", "error"))
    run.status = "completed"
    run.ended_at = datetime.utcnow()
    db.commit()

    await _publish(run.id, {
        "type": "run_completed", "run_id": run.id,
        "passed": run.passed_cells, "failed": run.failed_cells, "total": run.total_cells,
    })
    return run.id


def list_runs(db: Session, job_id: int) -> list[AiJobRun]:
    return db.query(AiJobRun).filter(AiJobRun.job_id == job_id).order_by(AiJobRun.started_at.desc()).all()


def get_run(db: Session, run_id: int) -> AiJobRun | None:
    return db.query(AiJobRun).filter(AiJobRun.id == run_id).first()


def run_to_dict(run: AiJobRun, include_cells: bool = False) -> dict:
    d = {
        "id": run.id,
        "job_id": run.job_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "total_cells": run.total_cells,
        "passed_cells": run.passed_cells,
        "failed_cells": run.failed_cells,
    }
    if include_cells:
        d["cells"] = [
            {
                "id": c.id,
                "scenario_folder": c.scenario_folder,
                "scenario_name": c.scenario_name,
                "device_id": c.device_id,
                "device_name": c.device_name,
                "status": c.status,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "ended_at": c.ended_at.isoformat() if c.ended_at else None,
                "log": _json.loads(c.log_json) if c.log_json else None,
            }
            for c in run.results
        ]
    return d
```

- [ ] **Step 4: Motoru gerçek bir senaryoyla doğrula (cihaz gerektirmez — hata yolunu test eder)**

Run (var olmayan cihazla — script üretimi ve "cihaz yok" hata akışını doğrular, gerçek Appium koşumu Task 7'de fiziksel/emülatör cihazla yapılacak):
```bash
cd backend && venv/Scripts/python.exe -c "
import asyncio
from database import SessionLocal, init_db
init_db()
from services import ai_job_service as s

async def main():
    db = SessionLocal()
    job = s.create_job(db, user_id=1, name='Motor Testi', scenario_folders=['olmayan_senaryo'], device_ids=['no-such-device'], schedule=None)
    try:
        run_id = await s.run_job(job.id, db, trigger_type='manual')
        print('run_id:', run_id)
    except ValueError as e:
        print('beklenen hata (workspace yok ise):', e)
    s.delete_job(db, job.id)

asyncio.run(main())
"
```
Expected: Eğer test kullanıcısının git workspace'i yoksa `ValueError: Kullanıcının git workspace'i bulunamadı` basılır (beklenen). Workspace varsa `run_id: N` basılır ve DB'de `ai_job_run_results` tablosunda `status='error'` (senaryo dosyası bulunamadı) kayıtları oluşur — hata fırlatmadan uçtan uca akışın çalıştığını gösterir.

- [ ] **Step 5: Commit**

```bash
git add backend/services/ai_job_service.py
git commit -m "AI Job calistirma motoru: paralel hucre kosumu + pub/sub"
```

---

### Task 4: REST + WebSocket router

**Files:**
- Create: `backend/routers/ai_job_router.py`
- Modify: `backend/main.py:35-84` (import + `app.include_router`)

**Interfaces:**
- Consumes: `services.ai_job_service.*` (Task 2, 3)
- Produces: `router` (APIRouter, prefix `/api/ai-jobs`) — Task 6 (frontend) bu endpoint'leri çağırır.

- [ ] **Step 1: Router dosyasını oluştur**

`backend/routers/ai_job_router.py`:

```python
"""
AI Test Generator — Job Router (Faz 1: Mobil)
Job CRUD, manuel tetikleme, kosum gecmisi, canli WebSocket.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User
from services import ai_job_service

router = APIRouter(prefix="/api/ai-jobs", tags=["ai-jobs"])


class JobScheduleIn(BaseModel):
    schedule_type: str   # 'once' | 'daily' | 'weekly'
    run_at: str           # ISO datetime string


class JobIn(BaseModel):
    name: str
    scenario_folders: list[str]
    device_ids: list[str]
    schedule: Optional[JobScheduleIn] = None


@router.post("")
async def create_job(body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.scenario_folders or not body.device_ids:
        raise HTTPException(400, "En az bir senaryo ve bir cihaz seçilmeli")
    job = ai_job_service.create_job(
        db, current_user.id, body.name, body.scenario_folders, body.device_ids,
        body.schedule.dict() if body.schedule else None,
    )
    return ai_job_service.job_to_dict(job)


@router.get("")
async def list_jobs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = ai_job_service.list_jobs(db, current_user.id)
    return {"jobs": [ai_job_service.job_to_dict(j) for j in jobs]}


@router.get("/{job_id}")
async def get_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    return ai_job_service.job_to_dict(job)


@router.put("/{job_id}")
async def update_job(job_id: int, body: JobIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    if not body.scenario_folders or not body.device_ids:
        raise HTTPException(400, "En az bir senaryo ve bir cihaz seçilmeli")
    job = ai_job_service.update_job(
        db, job_id, body.name, body.scenario_folders, body.device_ids,
        body.schedule.dict() if body.schedule else None,
    )
    return ai_job_service.job_to_dict(job)


@router.delete("/{job_id}")
async def delete_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    ai_job_service.delete_job(db, job_id)
    return {"ok": True}


@router.post("/{job_id}/run")
async def trigger_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    try:
        run_id = await ai_job_service.run_job(job_id, db, trigger_type="manual")
    except ai_job_service.JobAlreadyRunningError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"run_id": run_id}


@router.get("/{job_id}/runs")
async def job_runs(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = ai_job_service.get_job(db, job_id, current_user.id)
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    runs = ai_job_service.list_runs(db, job_id)
    return {"runs": [ai_job_service.run_to_dict(r) for r in runs]}


@router.get("/runs/{run_id}")
async def run_detail(run_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = ai_job_service.get_run(db, run_id)
    if not run or run.job.user_id != current_user.id:
        raise HTTPException(404, "Koşum bulunamadı")
    return ai_job_service.run_to_dict(run, include_cells=True)


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = ai_job_service.get_run(db, run_id)
    if not run or run.job.user_id != current_user.id:
        raise HTTPException(404, "Koşum bulunamadı")
    ai_job_service.stop_run(run_id)
    return {"ok": True}


@router.websocket("/ws/{run_id}")
async def job_run_ws(websocket: WebSocket, run_id: int):
    await websocket.accept()
    q = ai_job_service.subscribe(run_id)
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
            if event.get("type") == "run_completed":
                break
    except WebSocketDisconnect:
        pass
    finally:
        ai_job_service.unsubscribe(run_id, q)
```

- [ ] **Step 2: main.py'ye mount et**

`backend/main.py:41` civarına (uploads_router importunun altına) ekle:
```python
# 🗓️ AI Test Generator - Job sistemi (Faz 1: Mobil)
from routers.ai_job_router import router as ai_job_router
```

`backend/main.py:84` civarına (`app.include_router(uploads_router)` satırının altına) ekle:
```python
# 🗓️ AI Job Sistemi
app.include_router(ai_job_router)
```

- [ ] **Step 3: Sunucuyu başlatıp endpoint'leri doğrula**

Run:
```bash
cd backend && venv/Scripts/python.exe main.py
```
Expected: Konsolda hata yok, "Swagger: http://localhost:8000/docs" satırı görünür. Ayrı bir terminalde:
```bash
curl -s http://localhost:8000/docs | grep -o "ai-jobs" | head -1
```
Expected: `ai-jobs` yazdırır (Swagger şemasında router mount edilmiş). Sunucuyu durdur (Ctrl+C).

- [ ] **Step 4: Commit**

```bash
git add backend/routers/ai_job_router.py backend/main.py
git commit -m "AI Job REST+WebSocket router eklendi ve mount edildi"
```

---

### Task 5: Zamanlayıcı + başlangıç temizliği

**Files:**
- Modify: `backend/services/ai_job_service.py` (ekleme)
- Modify: `backend/main.py` (lifespan içine wire etme)

**Interfaces:**
- Consumes: `run_job` (Task 3)
- Produces: `async def ai_job_scheduler_loop()`, `def cleanup_interrupted_runs()` — `main.py` lifespan bunları çağırır.

- [ ] **Step 1: Zamanlayıcı döngüsü ve temizlik fonksiyonunu ekle**

`backend/services/ai_job_service.py` dosya sonuna ekle:

```python
# ══════════════════════════════════════════════════════════════
# ZAMANLAYICI (main.py lifespan'de asyncio.create_task ile başlatılır)
# ══════════════════════════════════════════════════════════════

def cleanup_interrupted_runs() -> None:
    """Sunucu yeniden başlarken yarım kalan koşumları 'interrupted' işaretler."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        stuck_runs = db.query(AiJobRun).filter(AiJobRun.status == "running").all()
        for r in stuck_runs:
            r.status = "interrupted"
            r.ended_at = datetime.utcnow()
        db.query(AiJobRunResult).filter(
            AiJobRunResult.status.in_(["queued", "running"])
        ).update({"status": "error"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


async def ai_job_scheduler_loop() -> None:
    """30sn'de bir zamanı gelmis job'lari tetikler. main.py'deki _session_idle_reaper deseniyle ayni."""
    from database import SessionLocal

    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            due = db.query(AiJobSchedule).filter(
                AiJobSchedule.enabled == True,   # noqa: E712
                AiJobSchedule.run_at <= now,
            ).all()
            for sched in due:
                try:
                    await run_job(sched.job_id, db, trigger_type="scheduled")
                except Exception as e:
                    print(f"[AI-JOB-SCHEDULER] job {sched.job_id} tetiklenemedi: {e}")

                sched.last_triggered_at = now
                if sched.schedule_type == "once":
                    sched.enabled = False
                elif sched.schedule_type == "daily":
                    sched.run_at = sched.run_at + timedelta(days=1)
                elif sched.schedule_type == "weekly":
                    sched.run_at = sched.run_at + timedelta(days=7)
                db.commit()
        except Exception as e:
            print(f"[AI-JOB-SCHEDULER] döngü hatası: {e}")
        finally:
            db.close()
```

- [ ] **Step 2: main.py lifespan'e wire et**

`backend/main.py:43` civarına (idle reaper importunun altına) ekle:
```python
# 🗓️ AI Job Sistemi - zamanlayici + baslangic temizligi
from services.ai_job_service import ai_job_scheduler_loop, cleanup_interrupted_runs
```

`backend/main.py:50` civarındaki lifespan fonksiyonunu güncelle — `asyncio.create_task(_session_idle_reaper())` satırının altına ekle:
```python
    cleanup_interrupted_runs()
    asyncio.create_task(ai_job_scheduler_loop())
```

- [ ] **Step 3: Zamanlayıcının tetiklendiğini doğrula**

Run (1 dakika sonrası için tek seferlik bir job kur, sunucuyu ayakta tut, ~90sn sonra `AiJobRun` oluştuğunu kontrol et):
```bash
cd backend && venv/Scripts/python.exe -c "
from datetime import datetime, timedelta
from database import SessionLocal, init_db
init_db()
from services import ai_job_service as s
db = SessionLocal()
run_at = (datetime.utcnow() + timedelta(seconds=45)).isoformat()
job = s.create_job(db, 1, 'Zamanlama Testi', ['olmayan_senaryo'], ['no-such-device'], {'schedule_type': 'once', 'run_at': run_at})
print('job_id:', job.id, 'run_at(UTC):', run_at)
"
```
Ardından sunucuyu başlat (`venv/Scripts/python.exe main.py`), ~90 saniye bekle, sonra:
```bash
cd backend && venv/Scripts/python.exe -c "
from database import SessionLocal
from services import ai_job_service as s
db = SessionLocal()
runs = s.list_runs(db, <yukaridaki_job_id>)
print([r.status for r in runs])
"
```
Expected: En az bir `AiJobRun` kaydı (`status` muhtemelen `completed`, workspace yoksa scheduler loglarında `ValueError` görünür ama döngü çökmez — bu da doğrulanacak nokta). Sunucuyu durdur, oluşturulan job'ı temizle.

- [ ] **Step 4: Commit**

```bash
git add backend/services/ai_job_service.py backend/main.py
git commit -m "AI Job zamanlayicisi ve baslangic temizligi eklendi"
```

---

### Task 6: Frontend — `ai-jobs-mobile.html`

**Files:**
- Create: `backend/WebArayuz/ai-jobs-mobile.html`
- Modify: `backend/WebArayuz/js/sidebar.js:68-73` (nav item ekle)

**Interfaces:**
- Consumes: `API.get/post/put/delete` (`js/app.js`), `Auth.checkAuth/getToken` (`js/app.js`), `GET/POST/PUT/DELETE /api/ai-jobs*`, `GET /api/ai-gen/scenarios` (client-side `platform === 'mobile'` filtrelenecek), `GET /api/ai-gen/adb/devices` (mevcut).
- Produces: Sidebar'da "Mobil Job'lar" linki, job oluşturma/listeleme/matris/geçmiş UI'ı.

- [ ] **Step 1: Sidebar'a link ekle**

`backend/WebArayuz/js/sidebar.js:68-73` bloğunu güncelle:
```javascript
                section("AI Araçlar",
                    item("ai-generator",   "&#129302;", "AI Test Generator")
                    + item("ai-jobs-mobile","&#128197;", "Mobil Job'lar")
                    + item("java-generator","&#9749;",  "Java Generator")
                    + item("bdd-generator","&#129405;", "BDD Generator")
                    + item("test-history", "&#128203;", "Test Geçmişi")
                  )
```

- [ ] **Step 2: Sayfayı oluştur**

`backend/WebArayuz/ai-jobs-mobile.html`:

```html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mobil Job'lar - Test Otomasyon Platformu</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="css/style.css">
    <style>
        .page-content { padding: 24px; width: 100%; max-width: 1200px; box-sizing: border-box; }
        .toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
        .toolbar-title { font-weight: 600; font-size: 1rem; flex: 1; }
        .btn-primary {
            padding: 8px 16px; background: var(--accent-primary); border: none;
            border-radius: var(--radius-md); color: #fff; font-size: 0.85rem;
            font-weight: 500; cursor: pointer;
        }
        .btn-secondary {
            padding: 8px 14px; background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--radius-md); color: var(--text-secondary); font-size: 0.85rem; cursor: pointer;
        }
        .job-card {
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--radius-md); padding: 16px; margin-bottom: 12px;
            display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
        }
        .job-card-name { font-weight: 600; flex: 1; min-width: 160px; }
        .job-card-meta { font-size: 0.8rem; color: var(--text-muted); }
        .job-card-actions { display: flex; gap: 6px; }
        .empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); font-size: 0.9rem; }

        .modal-overlay {
            position: fixed; inset: 0; background: rgba(0,0,0,0.6);
            display: none; align-items: center; justify-content: center; z-index: 1000; padding: 16px;
        }
        .modal-box {
            background: var(--bg-secondary); border: 1px solid var(--border-color);
            border-radius: var(--radius-lg); padding: 24px; width: 100%; max-width: 640px;
            max-height: 85vh; overflow-y: auto; display: flex; flex-direction: column; gap: 14px;
        }
        .modal-header { display: flex; align-items: center; justify-content: space-between; }
        .form-row { display: flex; flex-direction: column; gap: 6px; }
        .form-row label { font-size: 0.82rem; color: var(--text-secondary); font-weight: 500; }
        .form-row input, .form-row select {
            padding: 8px 10px; border: 1px solid var(--border-color); border-radius: var(--radius-md);
            background: var(--bg-primary); color: var(--text-primary); font-size: 0.85rem;
        }
        .checkbox-list { display: flex; flex-direction: column; gap: 6px; max-height: 160px; overflow-y: auto;
            border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 8px; }
        .checkbox-list label { display: flex; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 400; }

        .matrix-wrap { overflow-x: auto; }
        table.matrix { border-collapse: collapse; width: 100%; }
        table.matrix th, table.matrix td { border: 1px solid var(--border-color); padding: 8px 10px; font-size: 0.82rem; text-align: center; }
        table.matrix th { background: var(--bg-secondary); }
        table.matrix td.scenario-name { text-align: left; font-weight: 500; white-space: nowrap; }
        .cell-status { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; cursor: pointer; }
        .cell-queued  { background: rgba(148,163,184,0.2); color: #94a3b8; }
        .cell-running { background: rgba(59,130,246,0.18); color: #3b82f6; animation: pulse 1.2s infinite; }
        .cell-pass    { background: rgba(16,185,129,0.15); color: #10b981; }
        .cell-fail    { background: rgba(239,68,68,0.15); color: #ef4444; }
        .cell-error   { background: rgba(245,158,11,0.18); color: #f59e0b; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
</head>
<body>
<div id="app-root">
    <div id="sidebar-container"></div>
    <div class="main-content">
        <header class="top-bar"><span class="top-bar-title">🗓️ Mobil Job'lar</span></header>
        <div class="page-content">

            <div class="toolbar">
                <span class="toolbar-title">Job Listesi</span>
                <button class="btn-secondary" onclick="loadJobs()">↺ Yenile</button>
                <button class="btn-primary" onclick="openJobModal()">+ Yeni Job</button>
            </div>
            <div id="jobListWrap"><div class="empty-state">Yükleniyor...</div></div>

            <div class="toolbar" style="margin-top:28px;">
                <span class="toolbar-title">Koşum Matrisi</span>
                <button class="btn-secondary" id="stopRunBtn" style="display:none;" onclick="stopCurrentRun()">⏹ Durdur</button>
            </div>
            <div id="matrixWrap"><div class="empty-state">Bir job çalıştırınca burada görünecek.</div></div>
        </div>
    </div>
</div>

<!-- Job Olustur/Duzenle Modal -->
<div id="jobModal" class="modal-overlay">
    <div class="modal-box">
        <div class="modal-header">
            <strong id="jobModalTitle">Yeni Job</strong>
            <button class="btn-secondary" onclick="closeJobModal()">✕</button>
        </div>
        <input type="hidden" id="jobEditId" value="">
        <div class="form-row">
            <label>Job Adı</label>
            <input type="text" id="jobName" placeholder="Ör: Sabah Regresyon Paketi">
        </div>
        <div class="form-row">
            <label>Senaryolar (mobil)</label>
            <div class="checkbox-list" id="scenarioCheckList"></div>
        </div>
        <div class="form-row">
            <label>Cihazlar (ADB)</label>
            <div class="checkbox-list" id="deviceCheckList"></div>
        </div>
        <div class="form-row">
            <label>Zamanlama</label>
            <select id="scheduleType" onchange="onScheduleTypeChange()">
                <option value="">Zamanlama yok (manuel çalıştır)</option>
                <option value="once">Tek seferlik</option>
                <option value="daily">Her gün tekrarla</option>
                <option value="weekly">Her hafta tekrarla</option>
            </select>
        </div>
        <div class="form-row" id="scheduleAtRow" style="display:none;">
            <label>İlk çalışma zamanı</label>
            <input type="datetime-local" id="scheduleAt">
        </div>
        <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button class="btn-secondary" onclick="closeJobModal()">Vazgeç</button>
            <button class="btn-primary" onclick="saveJob()">Kaydet</button>
        </div>
    </div>
</div>

<!-- Hucre Detay Modal -->
<div id="cellModal" class="modal-overlay">
    <div class="modal-box">
        <div class="modal-header">
            <strong id="cellModalTitle">Hücre Detayı</strong>
            <button class="btn-secondary" onclick="closeCellModal()">✕</button>
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

    let mobileScenarios = [];
    let adbDevices = [];
    let currentRunId = null;
    let currentRunCells = {};   // cell_id -> cell dict
    let ws = null;

    async function init() {
        await Promise.all([loadJobs(), loadScenariosAndDevices()]);
    }

    async function loadScenariosAndDevices() {
        try {
            const sRes = await API.get('/ai-gen/scenarios');
            mobileScenarios = (sRes.scenarios || []).filter(s => s.platform === 'mobile');
        } catch (e) { mobileScenarios = []; }
        try {
            const dRes = await API.get('/ai-gen/adb/devices');
            adbDevices = dRes.devices || [];
        } catch (e) { adbDevices = []; }
    }

    window.loadJobs = async function loadJobs() {
        const wrap = document.getElementById('jobListWrap');
        wrap.innerHTML = '<div class="empty-state">Yükleniyor...</div>';
        try {
            const res = await API.get('/ai-jobs');
            const jobs = res.jobs || [];
            if (!jobs.length) {
                wrap.innerHTML = '<div class="empty-state">Henüz job yok. "+ Yeni Job" ile oluşturun.</div>';
                return;
            }
            wrap.innerHTML = jobs.map(renderJobCard).join('');
        } catch (e) {
            wrap.innerHTML = `<div class="empty-state">Hata: ${e.message}</div>`;
        }
    };

    function renderJobCard(job) {
        const schedText = job.schedule
            ? `${job.schedule.schedule_type} — ${new Date(job.schedule.run_at).toLocaleString('tr-TR')} ${job.schedule.enabled ? '' : '(pasif)'}`
            : 'Zamanlama yok';
        return `
            <div class="job-card">
                <div class="job-card-name">${escapeHtml(job.name)}
                    <div class="job-card-meta">${job.scenarios.length} senaryo × ${job.devices.length} cihaz — ${schedText}</div>
                </div>
                <div class="job-card-actions">
                    <button class="btn-primary" onclick="runJob(${job.id})">▶ Çalıştır</button>
                    <button class="btn-secondary" onclick="editJob(${job.id})">Düzenle</button>
                    <button class="btn-secondary" onclick="showRuns(${job.id})">Geçmiş</button>
                    <button class="btn-secondary" onclick="deleteJob(${job.id})">Sil</button>
                </div>
            </div>`;
    }

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    window.openJobModal = function openJobModal(job) {
        document.getElementById('jobEditId').value = job ? job.id : '';
        document.getElementById('jobModalTitle').textContent = job ? 'Job Düzenle' : 'Yeni Job';
        document.getElementById('jobName').value = job ? job.name : '';

        const scList = document.getElementById('scenarioCheckList');
        scList.innerHTML = mobileScenarios.length
            ? mobileScenarios.map(s => `<label><input type="checkbox" value="${s.folder}" ${job && job.scenarios.includes(s.folder) ? 'checked' : ''}> ${escapeHtml(s.name)}</label>`).join('')
            : '<span style="color:var(--text-muted);font-size:0.82rem;">Mobil senaryo bulunamadı</span>';

        const devList = document.getElementById('deviceCheckList');
        const jobDeviceIds = job ? job.devices.map(d => d.device_id) : [];
        devList.innerHTML = adbDevices.length
            ? adbDevices.map(id => `<label><input type="checkbox" value="${id}" ${jobDeviceIds.includes(id) ? 'checked' : ''}> ${id}</label>`).join('')
            : '<span style="color:var(--text-muted);font-size:0.82rem;">Bağlı ADB cihazı yok</span>';

        const schedSel = document.getElementById('scheduleType');
        schedSel.value = job && job.schedule ? job.schedule.schedule_type : '';
        onScheduleTypeChange();
        if (job && job.schedule) {
            document.getElementById('scheduleAt').value = job.schedule.run_at.slice(0, 16);
        } else {
            document.getElementById('scheduleAt').value = '';
        }

        document.getElementById('jobModal').style.display = 'flex';
    };

    window.closeJobModal = function closeJobModal() {
        document.getElementById('jobModal').style.display = 'none';
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
        const device_ids = Array.from(document.querySelectorAll('#deviceCheckList input:checked')).map(el => el.value);
        const schedType = document.getElementById('scheduleType').value;

        if (!name) { alert('Job adı gerekli'); return; }
        if (!scenario_folders.length) { alert('En az bir senaryo seçin'); return; }
        if (!device_ids.length) { alert('En az bir cihaz seçin'); return; }

        let schedule = null;
        if (schedType) {
            const at = document.getElementById('scheduleAt').value;
            if (!at) { alert('Zamanlama seçtiyseniz bir tarih/saat girin'); return; }
            schedule = { schedule_type: schedType, run_at: new Date(at).toISOString() };
        }

        const body = { name, scenario_folders, device_ids, schedule };
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
        document.getElementById('stopRunBtn').style.display = run.status === 'running' ? 'inline-block' : 'none';
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
            wrap.innerHTML = '<div class="empty-state">Hücre bulunamadı.</div>';
            return;
        }
        const scenarios = [...new Set(cells.map(c => c.scenario_folder))];
        const devices = [...new Set(cells.map(c => c.device_id))];

        let html = '<div class="matrix-wrap"><table class="matrix"><thead><tr><th>Senaryo</th>';
        devices.forEach(d => html += `<th>${escapeHtml(d)}</th>`);
        html += '</tr></thead><tbody>';
        scenarios.forEach(sc => {
            const scName = cells.find(c => c.scenario_folder === sc)?.scenario_name || sc;
            html += `<tr><td class="scenario-name">${escapeHtml(scName)}</td>`;
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
        const labelMap = { queued: 'Bekliyor', running: 'Koşuyor', pass: 'Başarılı', fail: 'Başarısız', error: 'Hata' };
        return `<span class="cell-status cell-${cell.status}" onclick="showCellDetail(${cell.id})">${labelMap[cell.status] || cell.status}</span>`;
    }

    window.showCellDetail = function showCellDetail(cellId) {
        const cell = currentRunCells[cellId];
        if (!cell) return;
        document.getElementById('cellModalTitle').textContent = `${cell.scenario_name} — ${cell.device_id}`;
        const steps = (cell.log && cell.log.steps) || [];
        const terminal = (cell.log && cell.log.terminal) || (cell.log && cell.log.error) || '';
        let body = `<div style="font-size:0.82rem;color:var(--text-muted);">Durum: ${cell.status}</div>`;
        if (steps.length) {
            body += '<div style="display:flex;flex-direction:column;gap:6px;margin-top:8px;">';
            steps.forEach(s => {
                body += `<div>Adım ${s.index}: ${s.status === 'pass' ? '✓' : '✗'} ${s.status}</div>`;
            });
            body += '</div>';
        }
        if (terminal) {
            body += `<pre style="background:#0d1117;color:#e6edf3;padding:12px;border-radius:8px;overflow:auto;max-height:300px;font-size:0.78rem;margin-top:10px;">${escapeHtml(terminal)}</pre>`;
        }
        document.getElementById('cellModalBody').innerHTML = body;
        document.getElementById('cellModal').style.display = 'flex';
    };

    window.closeCellModal = function closeCellModal() {
        document.getElementById('cellModal').style.display = 'none';
    };

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

- [ ] **Step 3: Tarayıcıda manuel doğrula**

Sunucuyu çalıştır (`cd backend && venv/Scripts/python.exe main.py`), tarayıcıda `http://localhost:8000/ui/ai-jobs-mobile.html` aç (giriş yapmış olarak). Kontrol et:
1. Sidebar'da "Mobil Job'lar" linki görünüyor ve tıklanınca bu sayfaya geliyor.
2. "+ Yeni Job" modalı açılıyor, mobil senaryolar ve ADB cihazları listeleniyor (senaryo/cihaz yoksa ilgili boş-durum mesajı görünüyor).
3. Bir job oluşturunca listede kart olarak görünüyor.
4. "Çalıştır" tıklanınca matris tablosu render oluyor ve konsolda WebSocket hata vermiyor (DevTools Network/WS sekmesi).

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/ai-jobs-mobile.html backend/WebArayuz/js/sidebar.js
git commit -m "AI Job Mobil arayuzu eklendi (job olustur/listele/matris/gecmis)"
```

---

### Task 7: Uçtan uca doğrulama (gerçek cihaz/emülatör ile)

**Files:** Yok (yalnızca manuel doğrulama)

- [ ] **Step 1: 2 senaryo + 2 cihazla gerçek koşum**

Ön koşul: AI Test Generator'da en az 2 mobil senaryo kayıtlı olmalı (`ai-generator.html` üzerinden), en az 1 (ideal 2) ADB cihazı/emülatörü bağlı olmalı.

1. Sunucuyu başlat, `ai-jobs-mobile.html` sayfasında bu senaryoları ve cihazları seçerek bir job oluştur.
2. "Çalıştır" tıkla, matrisin canlı güncellendiğini (bekliyor → koşuyor → başarılı/başarısız) doğrula.
3. Bir hücreye tıkla, adım adım log ve terminal çıktısının modalda göründüğünü doğrula.

- [ ] **Step 2: Zamanlanmış tek seferlik koşum**

Yeni bir job oluştururken "Tek seferlik" zamanlama seç, 1-2 dakika sonrası bir saat gir. Sayfa açık kalsın, ~zamanı gelince job'ın "Geçmiş" listesinde otomatik yeni bir koşum belirdiğini doğrula (elle "Çalıştır" tıklamadan).

- [ ] **Step 3: Cihaz kopması senaryosu**

Koşum sırasında cihazlardan birini `adb disconnect` ile veya USB'yi çekerek kopar. O hücrenin `error` durumuna geçtiğini, diğer hücrelerin etkilenmeden devam ettiğini doğrula.

- [ ] **Step 4: Commit (varsa küçük düzeltmeler)**

Doğrulama sırasında bulunan hatalar için düzeltme yap ve:
```bash
git add -A
git commit -m "AI Job Mobil: uctan uca dogrulama sonrasi kucuk duzeltmeler"
```
(Düzeltme yoksa bu adımı atla.)
