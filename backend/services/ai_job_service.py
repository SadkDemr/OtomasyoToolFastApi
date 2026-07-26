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
