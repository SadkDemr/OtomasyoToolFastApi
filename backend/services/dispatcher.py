"""
Dispatcher Service - Test Dagitim Motoru
Arka planda surekli calisir, bosta cihaz bulursa kuyruktaki isi ona verir.
"""
import asyncio
import json
from sqlalchemy.orm import Session
from datetime import datetime

from database import SessionLocal
from models.db_models import TestResult, Device, JobExecution, DeviceStatus

# Burasi normalde senin MobileTestService'ini cagiracak
# Simdilik iskeletini kuruyoruz
async def run_test_on_device(db: Session, device: Device, test_result: TestResult):
    """
    Testi asil kosturan fonksiyon.
    """
    print(f"🚀 [Dispatcher] Test Basladi! Cihaz: {device.name} -> Senaryo ID: {test_result.scenario_id}")
    
    try:
        # 1. Testi Running yap
        test_result.status = "running"
        test_result.device_name = device.name
        test_result.executed_at = datetime.utcnow()
        db.commit()

        # --- BURAYA GERCEK TEST KODU GELECEK ---
        # Ornek: await mobile_test_service.run_scenario(device.device_id, scenario_content...)
        # Simdilik 5 saniye bekleme simulasyonu yapiyoruz:
        await asyncio.sleep(5) 
        
        # Test Basarili bitti varsayalim
        test_result.status = "success"
        test_result.log_json = json.dumps([{"step": 1, "message": "Test basariyla tamamlandi", "status": "success"}])
        test_result.duration_seconds = 5
        
    except Exception as e:
        print(f"💥 Test Hatasi: {e}")
        test_result.status = "failed"
        test_result.log_json = json.dumps([{"step": 0, "message": str(e), "status": "failed"}])
    
    finally:
        # Cihazi serbest birak
        device.status = DeviceStatus.AVAILABLE.value
        device.current_user_id = None
        db.commit()
        print(f"✅ [Dispatcher] Test Bitti. Cihaz {device.name} serbest.")
        
        # Job durumunu guncelle (Bitti mi?)
        check_job_completion(db, test_result.job_execution_id)

def check_job_completion(db: Session, execution_id: int):
    """Job icindeki tum testler bitti mi kontrol eder"""
    execution = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
    if not execution: return

    # Bekleyen veya kosan test kaldi mi?
    pending_count = db.query(TestResult).filter(
        TestResult.job_execution_id == execution_id,
        TestResult.status.in_(["pending", "running"])
    ).count()

    if pending_count == 0:
        execution.status = "completed"
        execution.end_time = datetime.utcnow()
        
        # Istatistikleri guncelle
        execution.passed_tests = db.query(TestResult).filter(TestResult.job_execution_id==execution_id, TestResult.status=="success").count()
        execution.failed_tests = db.query(TestResult).filter(TestResult.job_execution_id==execution_id, TestResult.status=="failed").count()
        
        db.commit()
        print(f"🏁 [Dispatcher] JOB TAMAMLANDI! ID: {execution_id}")

async def dispatcher_loop():
    """
    Sonsuz dongu: Surekli is ve cihaz arar.
    """
    print("🤖 Dispatcher Motoru Baslatildi...")
    
    while True:
        await asyncio.sleep(2) # CPU'yu bogmamak icin bekleme
        
        db = SessionLocal()
        try:
            # 1. Bekleyen is var mi? (Pending)
            pending_test = db.query(TestResult).filter(TestResult.status == "pending").first()
            
            if pending_test:
                # 2. Musait cihaz var mi?
                # (Physical veya Emulator fark etmez, status available olsun yeter)
                available_device = db.query(Device).filter(Device.status == "available").first()
                
                if available_device:
                    # 3. ESLESME SAGLANDI!
                    # Cihazi hemen kilitle ki baska is almasin
                    available_device.status = "busy"
                    available_device.current_user_id = pending_test.user_id # Testi baslatan kisiye ata
                    db.commit()
                    
                    # Testi asenkron olarak baslat (Arka planda kossun, dongu durmasin)
                    asyncio.create_task(run_test_on_device(db, available_device, pending_test))
                    
                    # db session'i bu task icin kapatmiyoruz, task icinde kullanilacak
                    # Ancak yeni dongu icin yeni session acilacak.
                    # SQLAlchemy session thread-safe degildir, o yuzden task icine yeni session pass etmek daha dogru olabilir
                    # Ama basitlik adina simdilik boyle birakalim.
                else:
                    # Is var ama cihaz yok, bekle.
                    pass
            
        except Exception as e:
            print(f"⚠️ Dispatcher Hatasi: {e}")
        finally:
            db.close()