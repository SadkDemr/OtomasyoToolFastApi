import asyncio
import json
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models.db_models import Job, JobExecution, TestResult, Device, JobDevice, DeviceStatus
from services.device_service import device_service

# --- DÜZELTME 1: appium_service nesnesi yerine SINIFIN KENDISINI import et ---
# Böylece her worker kendine özel bir kopyasını oluşturabilir.
from services.appium_service import AppiumService 
from models.schemas import TestStep

class DispatcherService:

    async def run_job(self, job_id: int):
        """
        Job'ı başlatır. Eğer cihaz seçilmemişse otomatik havuz oluşturur.
        """
        db: Session = SessionLocal()
        try:
            # 1. Job Bilgilerini Çek
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                print(f"❌ Job #{job_id} bulunamadı.")
                return

            # Job'a atanmış cihazları bul
            assigned_job_devices = db.query(JobDevice).filter(
                JobDevice.job_id == job_id).all()
            target_device_ids = [jd.device_id for jd in assigned_job_devices]

            devices = []

            # --- OTOMATİK CİHAZ SEÇİMİ ---
            if target_device_ids:
                print(f"🎯 Job #{job_id} için özel seçilmiş {len(target_device_ids)} cihaz var.")
                devices = db.query(Device).filter(Device.id.in_(target_device_ids)).all()
            else:
                print(f"⚠️ Job #{job_id} için cihaz seçilmemiş. Tüm uygun cihazlar taranıyor...")
                devices = db.query(Device).filter(Device.status == DeviceStatus.AVAILABLE.value).all()

            # Offline olanları ele
            available_devices = [d for d in devices if d.status != DeviceStatus.OFFLINE.value]

            if not available_devices:
                print("❌ Hata: Çalıştırılabilecek uygun (Online/Available) cihaz bulunamadı!")
                return

            # 2. Execution Kaydı Oluştur
            execution = JobExecution(
                job_id=job.id,
                user_id=job.user_id,
                status="running",
                start_time=datetime.now(),
                total_tests=len(job.scenarios)
            )
            db.add(execution)
            db.commit()
            db.refresh(execution)

            # 3. Kuyruğu (Queue) Oluştur ve Doldur
            queue = asyncio.Queue()
            sorted_scenarios = sorted(job.scenarios, key=lambda x: x.order if x.order is not None else 0)
            
            if not sorted_scenarios:
                print("⚠️ Job içinde senaryo yok!")
                return

            for job_scenario in sorted_scenarios:
                queue.put_nowait((job_scenario.scenario, execution.id))

            print(f"🚀 Job #{job_id} BAŞLADI. Kuyruk: {queue.qsize()} senaryo | Havuz: {len(available_devices)} cihaz.")

            # 4. Worker'ları (Cihazları) Hazırla
            tasks = []
            for device in available_devices:
                device_service.update_status(db, device.id, DeviceStatus.BUSY.value)
                task = asyncio.create_task(self.device_worker(device.id, device.appium_url, queue, db))
                tasks.append(task)

            # 5. Tüm işlerin bitmesini bekle
            await queue.join()

            # 6. İşçileri bitir
            for task in tasks:
                task.cancel()

            # 7. Job Status Güncelle
            execution.status = "completed"
            execution.end_time = datetime.now()
            
            # Cihazları boşa çıkar
            for device in available_devices:
                device_service.update_status(db, device.id, DeviceStatus.AVAILABLE.value)

            db.commit()
            print(f"🏁 Job #{job_id} Tamamlandı.")

        except Exception as e:
            print(f"🔥 Job Dispatcher Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()


    async def device_worker(self, device_id: int, appium_url: str, queue: asyncio.Queue, db: Session):
        """
        Bu fonksiyon her cihaz için ayrı bir thread gibi çalışır.
        """
        device = db.query(Device).filter(Device.id == device_id).first()
        dev_name = device.name if device else f"Device-{device_id}"

        # --- DÜZELTME 2: Her Worker için YENİ bir AppiumService Örneği ---
        # Bu sayede 'self.driver' değişkenleri birbirine karışmaz.
        local_service = AppiumService()

        print(f"📱 Worker Hazır: {dev_name}")

        while True:
            try:
                item = await queue.get()
                scenario_obj, execution_id = item
            except asyncio.CancelledError:
                print(f"🛑 Worker Durduruldu (Boşta): {dev_name}")
                break

            try:
                print(f"▶️ {dev_name} -> {scenario_obj.name} çalışıyor...")

                # A) Senaryo adımlarını parse et
                steps = []
                if scenario_obj.natural_steps:
                    steps = local_service.parse_natural_language(scenario_obj.natural_steps)
                elif scenario_obj.steps_json:
                    try:
                        raw_steps = json.loads(scenario_obj.steps_json)
                        for s in raw_steps: steps.append(TestStep(**s))
                    except: pass
                
                # B) Config'den paket bilgilerini al
                app_package = ""
                app_activity = ""
                if scenario_obj.config_json:
                    try:
                        conf = json.loads(scenario_obj.config_json)
                        app_package = conf.get("appPackage", "") or conf.get("app_package", "")
                        app_activity = conf.get("appActivity", "") or conf.get("app_activity", "")
                    except: pass

                # C) Testi Paralel Çalıştır
                loop = asyncio.get_running_loop()
                
                # --- DÜZELTME 3: local_service kullanıyoruz ---
                test_result_data = await loop.run_in_executor(
                    None, 
                    lambda: local_service.run_test(
                        device=device,
                        steps=steps,
                        app_package=app_package,
                        app_activity=app_activity,
                        test_id=f"{execution_id}_{scenario_obj.id}",
                        restart_app=True
                    )
                )

                success = test_result_data.get("success", False)
                result_logs = test_result_data.get("results", [])
                
                log_json_data = [
                    {
                        "step": r.step_number,
                        "action": r.action,
                        "success": r.success,
                        "message": r.message
                    } for r in result_logs
                ]

                try:
                    result = TestResult(
                        scenario_id=scenario_obj.id,
                        user_id=1,
                        job_execution_id=execution_id,
                        device_name=dev_name,
                        status="success" if success else "failed",
                        log_json=json.dumps(log_json_data),
                        executed_at=datetime.now(),
                        duration_seconds=0
                    )
                    db.add(result)

                    exc = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
                    if exc:
                        if success: exc.passed_tests += 1
                        else: exc.failed_tests += 1
                    db.commit()
                except Exception as db_err:
                    print(f"❌ DB Yazma Hatası: {db_err}")
                    db.rollback()

                status_icon = "✅" if success else "❌"
                print(f"{status_icon} {dev_name} -> {scenario_obj.name} bitti.")

            except asyncio.CancelledError:
                print(f"🛑 Worker Durduruldu (İşlem Sırasında): {dev_name}")
                queue.task_done()
                break

            except Exception as e:
                print(f"❌ Worker Kritik Hata ({dev_name}): {e}")

            finally:
                queue.task_done()

dispatcher = DispatcherService()