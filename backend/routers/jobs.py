"""
Jobs Router - FİNAL SÜRÜM (UI & LOG FIX)
------------------------------------------------
1. FIXED: Log nesneleri hem dict hem object olarak okunabilir hale getirildi (Hata çözüldü).
2. UI FIX: Çalışan job'lar için log listesi boş olsa bile "Başlatılıyor..." kaydı eklenir.
3. STOP FIX: stop_job emulator_service üzerinden durdurma sinyali gönderir.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from database import get_db
from models.db_models import Job, JobScenario, JobDevice, Scenario, Device, JobExecution
from models.schemas import JobCreate, JobResponse, JobListResponse
from routers.auth import get_current_user

# --- KRİTİK IMPORTLAR ---
from services.dispatcher_service import dispatcher
from services.emulator_service import emulator_service

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(
    status: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """İş paketlerini listele"""
    query = db.query(Job).filter(Job.user_id == current_user.id)
    jobs = query.order_by(Job.created_at.desc()).all()
    return JobListResponse(total=len(jobs), jobs=[JobResponse.model_validate(j) for j in jobs])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Tek iş paketi detayı"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    return JobResponse.model_validate(job)


@router.get("/{job_id}/scenarios")
def get_job_scenarios(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """İş paketindeki senaryoları getir"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    
    job_scenarios = db.query(JobScenario).filter(JobScenario.job_id == job_id).all()
    scenario_ids = [js.scenario_id for js in job_scenarios]
    scenarios = db.query(Scenario).filter(Scenario.id.in_(scenario_ids)).all()
    
    return {
        "job_id": job_id,
        "scenarios": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "description": s.description
            }
            for s in scenarios
        ]
    }


@router.get("/{job_id}/devices")
def get_job_devices(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """İş paketindeki cihazları getir"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    
    job_devices = db.query(JobDevice).filter(JobDevice.job_id == job_id).all()
    device_ids = [jd.device_id for jd in job_devices]
    devices = db.query(Device).filter(Device.id.in_(device_ids)).all()
    
    return {
        "job_id": job_id,
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "device_id": d.device_id,
                "type": d.type,
                "status": d.status
            }
            for d in devices
        ]
    }


@router.get("/{job_id}/history")
def get_job_history(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """İş paketinin çalışma geçmişini ve CANLI LOGLARI getir"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")

    # 1. Veritabanındaki kayıtlı (bitmiş veya süren) testleri çek
    executions = db.query(JobExecution).filter(
        JobExecution.job_id == job_id
    ).order_by(JobExecution.start_time.desc()).all()

    history_data = []
    
    for exc in executions:
        results_data = []
        
        # A) Veritabanına yazılmış (BİTMİŞ) senaryo sonuçlarını ekle
        for res in exc.results:
            scen_name = "Senaryo"
            scen = db.query(Scenario).filter(Scenario.id == res.scenario_id).first()
            if scen: scen_name = scen.name

            logs = []
            if res.log_json:
                try: logs = json.loads(res.log_json)
                except: logs = []

            results_data.append({
                "scenario_name": scen_name,
                "device_name": res.device_name,
                "status": res.status,
                "log_json": logs
            })

        # B) Eğer Job hala çalışıyorsa (Running), hafızadaki (RAM) CANLI LOGLARI da ekle!
        if exc.status == "running" or exc.status == "pending":
            # Bu job'a ait cihazları bul
            job_devices = db.query(JobDevice).filter(JobDevice.job_id == job_id).all()
            for jd in job_devices:
                device = db.query(Device).filter(Device.id == jd.device_id).first()
                if device:
                    # EmulatorService'den bu cihazın anlık loglarını sor
                    session = emulator_service.get_session(device.device_id)
                    
                    live_logs = []
                    if session and session.logs:
                        for l in session.logs:
                            # HATA DÜZELTME: Hem dict hem object desteği
                            if isinstance(l, dict):
                                step_val = l.get("step", l.get("step_number", 0))
                                action_val = l.get("action", "")
                                msg_val = l.get("message", "")
                                success_val = (l.get("status") == "success")
                            else:
                                step_val = getattr(l, "step", getattr(l, "step_number", 0))
                                action_val = getattr(l, "action", "")
                                msg_val = getattr(l, "message", "")
                                success_val = (getattr(l, "status", "") == "success")
                            
                            live_logs.append({
                                "step": step_val,
                                "action": action_val,
                                "message": msg_val,
                                "success": success_val
                            })
                    
                    # Log olsun veya olmasın, çalışıyorsa listede göster
                    if session: # Session varsa çalışıyordur
                        results_data.insert(0, { # En üste ekle
                            "scenario_name": "▶️ Şu an Çalışıyor...",
                            "device_name": device.name,
                            "status": "running",
                            "log_json": live_logs
                        })

        history_data.append({
            "id": exc.id,
            "status": exc.status,
            "start_time": exc.start_time,
            "end_time": exc.end_time,
            "total_tests": exc.total_tests,
            "passed_tests": exc.passed_tests,
            "failed_tests": exc.failed_tests,
            "results": results_data
        })

    return history_data


@router.post("", response_model=JobResponse)
def create_job(data: JobCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Yeni iş paketi oluştur"""
    job = Job(
        name=data.name,
        description=data.description,
        user_id=current_user.id,
        created_at=datetime.utcnow()
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    for sid in data.scenario_ids:
        js = JobScenario(job_id=job.id, scenario_id=sid)
        db.add(js)
    
    for did in data.device_ids:
        jd = JobDevice(job_id=job.id, device_id=did)
        db.add(jd)
    
    db.commit()
    return JobResponse.model_validate(job)


@router.post("/{job_id}/run")
async def run_job(
    job_id: int, 
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """İş paketini başlat"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    
    new_execution = JobExecution(
        job_id=job.id,
        user_id=current_user.id,
        status="pending",
        start_time=datetime.utcnow()
    )
    db.add(new_execution)
    db.commit()

    # Motoru çalıştır
    background_tasks.add_task(dispatcher.run_job, job_id)
    
    return {"success": True, "message": "Job başlatıldı", "execution_id": new_execution.id}


@router.post("/{job_id}/stop")
def stop_job(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """İş paketini GERÇEKTEN durdur"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    
    # 1. DB'deki durumu güncelle
    active_execution = db.query(JobExecution).filter(
        JobExecution.job_id == job_id,
        JobExecution.status.in_(["pending", "running"])
    ).order_by(JobExecution.start_time.desc()).first()
    
    if active_execution:
        active_execution.status = "cancelled"
        active_execution.end_time = datetime.utcnow()
        db.commit()
        
        # 2. Çalışan cihazlara "DUR" sinyali gönder
        job_devices = db.query(JobDevice).filter(JobDevice.job_id == job_id).all()
        stopped_devices = []
        
        for jd in job_devices:
            device = db.query(Device).filter(Device.id == jd.device_id).first()
            if device:
                session = emulator_service.get_session(device.device_id)
                if session:
                    session.stop_requested = True
                    stopped_devices.append(device.name)
        
        return {"success": True, "message": f"Job durduruldu. Sinyal: {', '.join(stopped_devices)}"}
    else:
        return {"success": False, "message": "Aktif çalışan bir iş bulunamadı"}


@router.delete("/{job_id}")
def delete_job(job_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """İş paketini sil"""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(404, "Job bulunamadı")
    
    db.query(JobScenario).filter(JobScenario.job_id == job_id).delete()
    db.query(JobDevice).filter(JobDevice.job_id == job_id).delete()
    db.query(JobExecution).filter(JobExecution.job_id == job_id).delete()
    
    db.delete(job)
    db.commit()
    
    return {"success": True, "message": "Silindi"}