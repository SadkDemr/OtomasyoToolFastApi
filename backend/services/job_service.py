"""
Job Service - Test Paketleri Yonetimi
FIXED: Data mapping added (Solves 500 Error & Create Job Issue)
"""
import sys, os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
from sqlalchemy import desc

from models.db_models import Job, JobScenario, Scenario, JobExecution, TestResult
from models.schemas import JobCreate
from models.db_models import Job, JobScenario, JobDevice

class JobService:
    
    # --- BU FONKSIYON EKSIKTI, GERI EKLENDI ---
    def _job_to_dict(self, job):
        """Job verisini API semasina uygun sozluge cevirir"""
        return {
            "id": job.id,
            "name": job.name,
            "description": job.description,
            "created_at": job.created_at,
            "scenarios": [
                {
                    "id": item.scenario.id,
                    "name": item.scenario.name,
                    "type": item.scenario.type
                }
                for item in job.scenarios if item.scenario
            ]
        }

    def get_all_jobs(self, db: Session):
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
        # Veriyi dogru formata cevirip donuyoruz
        return [self._job_to_dict(job) for job in jobs]

    def get_job(self, db: Session, job_id: int):
        return db.query(Job).filter(Job.id == job_id).first()

    def create_job(self, db: Session, user_id: int, data: JobCreate):
        new_job = Job(
            user_id=user_id,
            name=data.name,
            description=data.description
        )
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        
        # Senaryoları ekle
        for idx, s_id in enumerate(data.scenario_ids):
            assoc = JobScenario(job_id=new_job.id, scenario_id=s_id, order=idx)
            db.add(assoc)
            
        # --- YENI: Cihazları ekle ---
        for d_id in data.device_ids:
            dev_assoc = JobDevice(job_id=new_job.id, device_id=d_id)
            db.add(dev_assoc)
            
        db.commit()
        db.refresh(new_job)
        return new_job

    def update_job(self, db: Session, job_id: int, data: JobCreate):
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job: return None
        
        job.name = data.name
        job.description = data.description
        
        # Eski ilişkileri temizle
        db.query(JobScenario).filter(JobScenario.job_id == job_id).delete()
        db.query(JobDevice).filter(JobDevice.job_id == job_id).delete() # Cihazları da temizle
        
        # Yeniden ekle (Senaryolar)
        for idx, s_id in enumerate(data.scenario_ids):
            assoc = JobScenario(job_id=job.id, scenario_id=s_id, order=idx)
            db.add(assoc)
            
        # Yeniden ekle (Cihazlar)
        for d_id in data.device_ids:
            dev_assoc = JobDevice(job_id=job.id, device_id=d_id)
            db.add(dev_assoc)
            
        db.commit()
        db.refresh(job)
        return job

    def delete_job(self, db: Session, job_id: int):
        job = self.get_job(db, job_id)
        if job:
            db.delete(job)
            db.commit()
            return True
        return False

    def get_job_history(self, db: Session, job_id: int):
        executions = db.query(JobExecution).filter(JobExecution.job_id == job_id).order_by(desc(JobExecution.start_time)).all()
        
        result = []
        for exc in executions:
            # Senaryo isimlerini JOIN ile cek
            query = db.query(TestResult, Scenario.name).outerjoin(
                Scenario, TestResult.scenario_id == Scenario.id
            ).filter(TestResult.job_execution_id == exc.id).all()
            
            results_data = []
            for tr, scen_name in query:
                results_data.append({
                    "id": tr.id,
                    "scenario_name": scen_name if scen_name else "Silinmiş Senaryo",
                    "status": tr.status,
                    "log_json": json.loads(tr.log_json) if tr.log_json else []
                })

            result.append({
                "execution_id": exc.id,
                "status": exc.status,
                "start_time": exc.start_time,
                "end_time": exc.end_time,
                "total": exc.total_tests,
                "passed": exc.passed_tests,
                "failed": exc.failed_tests,
                "results": results_data
            })
        return result

job_service = JobService()