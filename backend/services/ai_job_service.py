"""
AI Test Generator — Job Servisi (Faz 1: Mobil)
CRUD + çalıştırma motoru + zamanlayıcı.
"""
import asyncio
import json as _json
import os
import subprocess
import sys
import tempfile
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
        loop = asyncio.get_running_loop()
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


# ══════════════════════════════════════════════════════════════
# HUCRE KOORDINASYONU + RUN_JOB MOTORU
# ══════════════════════════════════════════════════════════════

async def _execute_cell(run_id: int, cell_id: int, steps_data: dict | None, device_id: str) -> None:
    """Bu fonksiyon HİÇBİR istisnayı çağırana sızdırmamalıdır: run_job bunları
    asyncio.gather(...) ile paralel bekliyor; burada yakalanmayan bir hata gather'ı
    ve dolayısıyla tüm run_job'u kesintiye uğratıp AiJobRun'ı 'running' durumunda
    kilitli bırakır. Bu yüzden dış try/except, script üretimi/koşumu için zaten var
    olan iç try/except'in ÜSTÜNE, DB sorgusu/commit/_publish çağrılarını da kapsayacak
    şekilde eklenmiştir."""
    db = None
    try:
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
        except Exception as outer_e:
            # Sorgu/status="running" commit/_publish gibi iç try/except'in DIŞINDA kalan
            # bir adım patladı. Hücreyi en iyi çaba (best-effort) ile "error"a çek; bu
            # fallback'in kendisi de patlarsa yut — hiçbir şekilde yukarı sızdırma.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                cell = db.query(AiJobRunResult).filter(AiJobRunResult.id == cell_id).first()
                if cell:
                    cell.status = "error"
                    cell.ended_at = datetime.utcnow()
                    cell.log_json = _json.dumps({"error": f"Hücre çalıştırılamadı: {outer_e}"})
                    db.commit()
            except Exception:
                pass
            try:
                await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
            except Exception:
                pass
    except Exception:
        # SessionLocal() açılışı bile başarısız olursa buraya düşer; bu fonksiyon için
        # "hiçbir istisna sızdırma" garantisini korumak amacıyla yutulur. run_job kendi
        # try/finally'sinde AiJobRun'ı yine de terminal bir duruma taşıyacaktır.
        pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


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

    # Bu noktadan sonra AiJobRun DB'de status="running" olarak var. Aşağıdaki blokta
    # (senaryo okuma, hücre oluşturma, asyncio.gather, tally) HERHANGİ bir istisna
    # oluşursa, run zaten "running"a kilitli kalmasın: try/finally ile run'ı her
    # koşulda (başarı/hata) terminal bir duruma taşıyıp öyle çıkıyoruz. run_job'un
    # eski davranışını korumak için orijinal istisna finally sonrası yeniden fırlatılır.
    gather_error: Exception | None = None
    cells: list[AiJobRunResult] = []
    scenario_data: dict[str, dict] = {}
    try:
        db.refresh(run)
        for folder in scenario_folders:
            steps_file = Path(ws.local_path) / "ai_scenarios" / folder / "steps.json"
            if steps_file.exists():
                scenario_data[folder] = _json.loads(steps_file.read_text(encoding="utf-8"))

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
    except Exception as e:
        gather_error = e
    finally:
        _stopped_runs.discard(run.id)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            results = db.query(AiJobRunResult).filter(AiJobRunResult.job_run_id == run.id).all()
            run.passed_cells = sum(1 for r in results if r.status == "pass")
            run.failed_cells = sum(1 for r in results if r.status in ("fail", "error"))
            # Eğer gather aşamasında (senaryo okuma, hücre oluşturma, paralel koşum)
            # bir istisna fırlatıldıysa, sonuç "interrupted"; aksi halde normal tamamlanış.
            run.status = "interrupted" if gather_error is not None else "completed"
        except Exception:
            # Tally'nin kendisi (DB sorgusu) başarısız oldu — tam sonucu hesaplayamadık,
            # ama run'ı "running"da bırakmamak için elde ne varsa onunla "interrupted"
            # olarak işaretle.
            run.status = "interrupted"
        run.ended_at = datetime.utcnow()
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        try:
            await _publish(run.id, {
                "type": "run_completed", "run_id": run.id,
                "passed": run.passed_cells, "failed": run.failed_cells, "total": run.total_cells,
            })
        except Exception:
            pass

    if gather_error is not None:
        raise gather_error
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
