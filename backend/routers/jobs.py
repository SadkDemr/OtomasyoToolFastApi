"""
Jobs Router - İş Paketleri API
FIXED: Update & History Endpoints Added
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from database import get_db
from models.schemas import JobCreate, JobResponse
from models.db_models import JobExecution
from services.job_service import job_service
from services.dispatcher_service import dispatcher
from services.device_service import device_service
from routers.auth import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

@router.get("", response_model=List[JobResponse])
def list_jobs(db: Session = Depends(get_db)):
    return job_service.get_all_jobs(db)

@router.post("", response_model=JobResponse)
def create_job(data: JobCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_service.create_job(db, current_user.id, data)

# --- YENİ: GÜNCELLEME ---
@router.put("/{job_id}", response_model=JobResponse)
def update_job(job_id: int, data: JobCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    updated_job = job_service.update_job(db, job_id, data)
    if not updated_job:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated_job

@router.delete("/{job_id}")
def delete_job(job_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    success = job_service.delete_job(db, job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}

@router.post("/{job_id}/run")
async def run_job(job_id: int, background_tasks: BackgroundTasks, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    background_tasks.add_task(dispatcher.run_job, job_id)
    return {"success": True, "message": "Job başlatıldı."}

@router.post("/{job_id}/stop")
def stop_job(job_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    executions = db.query(JobExecution).filter(JobExecution.job_id == job_id, JobExecution.status == "running").all()
    count = 0
    for exc in executions:
        exc.status = "stopped"
        exc.end_time = datetime.now()
        count += 1
    db.commit()

    devs = device_service.get_all_devices(db)
    for d in devs:
        if d.status == "busy": device_service.release_device(db, d.id, 1)
            
    return {"success": True, "message": f"{count} job durduruldu."}

# --- YENİ: GEÇMİŞ & LOGLAR ---
@router.get("/{job_id}/history")
def get_job_history(job_id: int, db: Session = Depends(get_db)):
    """Job'ın geçmiş koşumlarını ve detaylı loglarını getirir"""
    return job_service.get_job_history(db, job_id)