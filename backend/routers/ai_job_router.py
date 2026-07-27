"""
AI Test Generator — Job Router (Faz 1: Mobil)
Job CRUD, manuel tetikleme, kosum gecmisi, canli WebSocket.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user
from models.db_models import User
from services import ai_job_service

router = APIRouter(prefix="/api/ai-jobs", tags=["ai-jobs"])


class JobScheduleIn(BaseModel):
    schedule_type: str   # 'once' | 'daily' | 'weekly'
    run_at: str           # ISO datetime string


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


@router.get("")
async def list_jobs(
    platform: Optional[str] = None,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    jobs = ai_job_service.list_jobs(db, current_user.id, platform=platform)
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
    """Koşum olaylarını yayınlar.

    Sadece kuyruğu beklemek yetmez: Starlette istemci kopmasını yalnızca receive
    kanalı üzerinden bildirir. Tarayıcı sekmesi kapandığında `q.get()` sonsuza kadar
    beklerdi ve finally'deki unsubscribe hiç çalışmayıp kuyruk sızardı. Bu yüzden
    kuyruk ve receive aynı anda beklenir (FIRST_COMPLETED).
    """
    await websocket.accept()
    q = ai_job_service.subscribe(run_id)
    get_task: asyncio.Task | None = None
    recv_task: asyncio.Task | None = None
    try:
        while True:
            # Tamamlanan task her turda yeniden kurulur; tamamlanmayan task İPTAL
            # EDİLMEZ, bir sonraki tura taşınır → olay/mesaj kaybı olmaz.
            if get_task is None:
                get_task = asyncio.ensure_future(q.get())
            if recv_task is None:
                recv_task = asyncio.ensure_future(websocket.receive())

            done, _pending = await asyncio.wait(
                {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if recv_task in done:
                try:
                    msg = recv_task.result()
                except Exception:
                    break              # bağlantı koptu / receive hata verdi
                recv_task = None
                if msg.get("type") == "websocket.disconnect":
                    break
                # istemciden gelen diğer mesajlar (ping vb.) yok sayılır

            if get_task in done:
                event = get_task.result()
                get_task = None
                await websocket.send_json(event)
                if event.get("type") == "run_completed":
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        pending = [t for t in (get_task, recv_task) if t is not None]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        ai_job_service.unsubscribe(run_id, q)
