"""
Dispatcher Service - Akıllı Job Dağıtıcı
FIXED: Saves Logs to Database (Persistent History)
"""
import asyncio
import json
import time
from datetime import datetime
from sqlalchemy.exc import OperationalError
from services.device_service import device_service
from services.appium_service import appium_service
from services.job_service import job_service
from models.db_models import DeviceStatus, JobExecution, TestResult
from database import SessionLocal

class DispatcherService:
    async def run_job(self, job_id: int):
        # 1. Job Hazırlığı
        temp_db = SessionLocal()
        queue = []
        job_name = ""
        execution_id = None
        
        try:
            job = job_service.get_job(temp_db, job_id)
            if not job or not job.scenarios:
                print("❌ Job boş.")
                return
            job_name = job.name
            
            # Execution Kaydı (Retry Mekanizması ile)
            for attempt in range(3):
                try:
                    new_exec = JobExecution(
                        job_id=job.id, user_id=job.user_id, status="running",
                        total_tests=len(job.scenarios), start_time=datetime.now(),
                        passed_tests=0, failed_tests=0
                    )
                    temp_db.add(new_exec)
                    temp_db.commit()
                    temp_db.refresh(new_exec)
                    execution_id = new_exec.id
                    break
                except OperationalError:
                    time.sleep(1); temp_db.rollback()
            
            print(f"🚀 JOB BAŞLATILDI: {job_name} (Exec ID: {execution_id})")
            
            # Kuyruk ve TestResult Kayıtları
            for s in job.scenarios:
                t_scen = s.scenario if hasattr(s, 'scenario') else s
                if t_scen:
                    # TestResult kaydı oluştur (Pending)
                    tr = TestResult(
                        scenario_id=t_scen.id, user_id=job.user_id,
                        job_execution_id=execution_id, status="pending", log_json="[]"
                    )
                    temp_db.add(tr)
                    temp_db.commit()
                    temp_db.refresh(tr)
                    
                    queue.append({
                        "result_id": tr.id, # DB ID'si önemli
                        "id": t_scen.id,
                        "name": t_scen.name,
                        "natural_steps": t_scen.natural_steps,
                        "config_json": t_scen.config_json
                    })

        except Exception as e:
            print(f"❌ Başlatma hatası: {e}"); return
        finally:
            temp_db.close()

        # 2. Döngü
        while queue:
            db = SessionLocal()
            try:
                # Durdurma Kontrolü
                curr = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
                if curr and curr.status == "stopped":
                    print("🛑 Döngü durduruldu."); break

                # Cihaz Bul
                devs = [d for d in device_service.get_all_devices(db) if d.status == DeviceStatus.AVAILABLE.value]
                if not devs:
                    await asyncio.sleep(2); continue

                device = devs[0]
                item = queue.pop(0)
                
                print(f"▶️ {item['name']} -> {device.name}")
                device_service.lock_device(db, device.id, 1)
                
                # Testi Çalıştır (Asenkron)
                asyncio.create_task(self._run_and_save(device.id, item, execution_id))
                
            except Exception as e:
                print(f"Döngü hatası: {e}"); await asyncio.sleep(3)
            finally:
                db.close()
        
        # Bitiş (Basit kontrol, gerçekte tüm taskların bitmesini beklemek gerekir)
        await asyncio.sleep(2) 

    async def _run_and_save(self, device_id, item, exec_id):
        db = SessionLocal()
        try:
            # Durumu Running yap
            tr = db.query(TestResult).filter(TestResult.id == item['result_id']).first()
            if tr: tr.status = "running"; db.commit()

            device = device_service.get_device_by_id(db, device_id)
            steps = appium_service.parse_natural_language(item['natural_steps'])
            cfg = json.loads(item['config_json']) if item.get('config_json') else {}

            # Testi Koş
            res = await asyncio.to_thread(
                appium_service.run_test, device=device, steps=steps,
                app_package=cfg.get("app_package"), app_activity=cfg.get("app_activity"),
                stop_on_fail=True, restart_app=cfg.get("restart_app", True),
                test_id=f"EXEC-{exec_id}"
            )

            # Sonucu Kaydet
            status = "passed" if res['success'] else "failed"
            
            # Yeniden DB bağlantısı (Thread güvenliği için)
            save_db = SessionLocal()
            try:
                # TestResult Güncelle
                final_tr = save_db.query(TestResult).filter(TestResult.id == item['result_id']).first()
                if final_tr:
                    final_tr.status = status
                    # Logları JSON olarak kaydet
                    logs = []
                    for r in res['results']:
                        logs.append({
                            "step": r.step_number, "action": r.action, 
                            "success": r.success, "message": r.message
                        })
                    final_tr.log_json = json.dumps(logs)
                
                # JobExecution İstatistiklerini Güncelle
                job_exec = save_db.query(JobExecution).filter(JobExecution.id == exec_id).first()
                if job_exec:
                    if status == "passed": job_exec.passed_tests += 1
                    else: job_exec.failed_tests += 1
                    
                    # Eğer hepsi bittiyse Completed yap (Basit mantık)
                    if (job_exec.passed_tests + job_exec.failed_tests) >= job_exec.total_tests:
                        job_exec.status = "completed"
                        job_exec.end_time = datetime.now()

                save_db.commit()
                print(f"🏁 Kaydedildi: {item['name']} -> {status}")
            finally:
                save_db.close()

        except Exception as e:
            print(f"Test hatası: {e}")
        finally:
            try: device_service.release_device(db, device_id, 1)
            except: pass
            db.close()

dispatcher = DispatcherService()