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
        new_job = Job(name=data.name, description=data.description, user_id=user_id)
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        
        if data.scenario_ids:
            for index, scen_id in enumerate(data.scenario_ids):
                # Senaryo var mi kontrol et
                scenario = db.query(Scenario).filter(Scenario.id == scen_id).first()
                if scenario:
                    job_scenario = JobScenario(job_id=new_job.id, scenario_id=scen_id, order=index + 1)
                    db.add(job_scenario)
            db.commit()
            db.refresh(new_job)
            
        # Olusturulan job'i formatli dondur
        return self._job_to_dict(new_job)

    def update_job(self, db: Session, job_id: int, data: JobCreate):
        job = self.get_job(db, job_id)
        if not job: return None

        job.name = data.name
        job.description = data.description
        
        # Eski iliskileri temizle
        db.query(JobScenario).filter(JobScenario.job_id == job.id).delete()
        
        if data.scenario_ids:
            for index, scen_id in enumerate(data.scenario_ids):
                job_scenario = JobScenario(job_id=job.id, scenario_id=scen_id, order=index + 1)
                db.add(job_scenario)
        
        db.commit()
        db.refresh(job)
        return self._job_to_dict(job)

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