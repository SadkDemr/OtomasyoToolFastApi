"""
Dispatcher Service - Gelişmiş İş Dağıtıcı
Fixes:
1. Router tarafından oluşturulan Execution ID'yi kullanır (Logların görünmesini sağlar).
2. Döngü içinde 'Cancelled' durumunu kontrol eder (Durdur butonunun gerçekten durdurmasını sağlar).
"""
import asyncio
import json
import time
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models.db_models import Job, JobExecution, TestResult, Device, JobDevice, DeviceStatus
from models.schemas import TestStep

# Sınıfın kendisini import ediyoruz (Her worker yeni instance alsın diye)
from services.appium_service import AppiumService 
from services.device_service import device_service

class DispatcherService:

    async def run_job(self, job_id: int):
        """
        Job'ı başlatır ve kuyruğu yönetir.
        """
        db: Session = SessionLocal()
        try:
            # 1. Job ve Execution Kontrolü
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                print(f"❌ Job #{job_id} bulunamadı.")
                return

            # Router'ın oluşturduğu "pending" durumundaki son execution'ı bul
            execution = db.query(JobExecution).filter(
                JobExecution.job_id == job_id,
                JobExecution.status == "pending"
            ).order_by(JobExecution.id.desc()).first()

            if not execution:
                # Bulamazsa yeni oluştur (Fallback)
                execution = JobExecution(
                    job_id=job.id,
                    user_id=job.user_id,
                    status="pending",
                    start_time=datetime.now(),
                    total_tests=len(job.scenarios)
                )
                db.add(execution)
                db.commit()
            
            # Durumu running'e çek
            execution.status = "running"
            execution.total_tests = len(job.scenarios) # Sayıyı güncelle
            db.commit()
            
            execution_id = execution.id # ID'yi sakla

            # 2. Cihazları Hazırla
            assigned_job_devices = db.query(JobDevice).filter(JobDevice.job_id == job_id).all()
            target_device_ids = [jd.device_id for jd in assigned_job_devices]

            devices = []
            if target_device_ids:
                devices = db.query(Device).filter(Device.id.in_(target_device_ids)).all()
            else:
                devices = db.query(Device).filter(Device.status == DeviceStatus.AVAILABLE.value).all()

            available_devices = [d for d in devices if d.status != DeviceStatus.OFFLINE.value]

            if not available_devices:
                print("❌ Hata: Uygun cihaz bulunamadı!")
                execution.status = "failed"
                db.commit()
                return

            # 3. Kuyruğu Doldur
            queue = asyncio.Queue()
            # Senaryoları JobScenario tablosundaki sıraya (order) göre al
            sorted_scenarios = sorted(job.scenarios, key=lambda x: x.order if x.order is not None else 0)
            
            # İlişkili senaryo objelerini çek
            for job_scen in sorted_scenarios:
                queue.put_nowait((job_scen.scenario, execution_id))

            print(f"🚀 Job #{job_id} (Exec #{execution_id}) BAŞLADI. Kuyruk: {queue.qsize()} | Cihaz: {len(available_devices)}")

            # 4. Workerları Başlat
            tasks = []
            for device in available_devices:
                # Cihazı meşgul yap
                device_service.update_status(db, device.id, DeviceStatus.BUSY.value)
                # Worker başlat
                task = asyncio.create_task(self.device_worker(device.id, queue, execution_id))
                tasks.append(task)

            # 5. İşlerin bitmesini bekle
            await queue.join()

            # 6. Temizlik
            for task in tasks: task.cancel()
            
            # Cihazları boşa çıkar
            for device in available_devices:
                device_service.update_status(db, device.id, DeviceStatus.AVAILABLE.value)

            # 7. Son Durum Güncellemesi
            # Tekrar DB'den çek (Workerlar güncellemiş olabilir)
            db.refresh(execution)
            if execution.status != "cancelled":
                execution.status = "completed"
                execution.end_time = datetime.now()
                db.commit()
                
            print(f"🏁 Job #{job_id} Tamamlandı.")

        except Exception as e:
            print(f"🔥 Dispatcher Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            db.close()


    async def device_worker(self, device_id: int, queue: asyncio.Queue, execution_id: int):
        """
        Cihaz bazlı işçi fonksiyonu.
        Sürekli olarak Job iptal edildi mi diye kontrol eder.
        """
        # Her worker için KENDİ db session'ı
        db = SessionLocal()
        
        try:
            device = db.query(Device).filter(Device.id == device_id).first()
            dev_name = device.name if device else f"Device-{device_id}"
            local_service = AppiumService() # Her worker'a özel servis

            print(f"📱 Worker Hazır: {dev_name}")

            while True:
                try:
                    # Kuyruktan iş al
                    item = await queue.get()
                    scenario_obj, _ = item

                    # --- KRİTİK KONTROL: JOB İPTAL Mİ? ---
                    # Her senaryoya başlamadan önce DB'ye bakıyoruz
                    current_exec = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
                    if current_exec and current_exec.status == "cancelled":
                        print(f"🛑 Job İPTAL EDİLMİŞ. {dev_name} senaryoyu atlıyor: {scenario_obj.name}")
                        queue.task_done()
                        continue # Sıradakine geç (O da iptal görecek ve hızlıca bitecek)

                    print(f"▶️ {dev_name} -> {scenario_obj.name} çalışıyor...")

                    # Senaryo Adımlarını Hazırla
                    steps = []
                    if scenario_obj.natural_steps:
                        steps = local_service.parse_natural_language(scenario_obj.natural_steps)
                    elif scenario_obj.steps_json:
                        try:
                            raw = json.loads(scenario_obj.steps_json)
                            steps = [TestStep(**s) for s in raw]
                        except: pass
                    
                    # Config
                    app_package = ""
                    if scenario_obj.config_json:
                        try:
                            c = json.loads(scenario_obj.config_json)
                            app_package = c.get("appPackage") or c.get("app_package", "")
                        except: pass

                    # Testi Çalıştır (Thread içinde)
                    loop = asyncio.get_running_loop()
                    test_result_data = await loop.run_in_executor(
                        None, 
                        lambda: local_service.run_test(
                            device=device,
                            steps=steps,
                            app_package=app_package,
                            test_id=f"{execution_id}_{scenario_obj.id}",
                            restart_app=True
                        )
                    )

                    success = test_result_data.get("success", False)
                    result_logs = test_result_data.get("results", [])
                    
                    # Sonuçları Kaydet
                    log_json_data = [
                        {"step": r.step_number, "action": r.action, "success": r.success, "message": r.message} 
                        for r in result_logs
                    ]

                    result_record = TestResult(
                        scenario_id=scenario_obj.id,
                        user_id=1, # TODO: Dinamik al
                        job_execution_id=execution_id,
                        device_name=dev_name,
                        status="success" if success else "failed",
                        log_json=json.dumps(log_json_data),
                        executed_at=datetime.now()
                    )
                    db.add(result_record)
                    
                    # İstatistik güncelle
                    if current_exec:
                        if success: current_exec.passed_tests += 1
                        else: current_exec.failed_tests += 1
                    
                    db.commit()
                    
                    status_icon = "✅" if success else "❌"
                    print(f"{status_icon} {dev_name} -> {scenario_obj.name} bitti.")

                except asyncio.CancelledError:
                    print(f"🛑 Worker thread durduruldu: {dev_name}")
                    break
                except Exception as e:
                    print(f"❌ Worker Hata ({dev_name}): {e}")
                finally:
                    queue.task_done()

        finally:
            db.close()

dispatcher = DispatcherService()