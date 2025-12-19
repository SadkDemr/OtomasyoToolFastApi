"""
Device Service - Cihaz Yönetimi ve ADB
FIXED: Debug Logs for ADB Sync
"""
import subprocess
import shutil
import os
from sqlalchemy.orm import Session
from models.db_models import Device, DeviceStatus
from models.schemas import DeviceCreate

class DeviceService:
    
    def get_all_devices(self, db: Session):
        return db.query(Device).all()

    def get_device_by_id(self, db: Session, device_id: int):
        return db.query(Device).filter(Device.id == device_id).first()

    def create_device(self, db: Session, device: DeviceCreate):
        db_device = Device(
            name=device.name,
            device_id=device.device_id,
            type=device.type,
            os=device.os,
            os_version=device.os_version,
            appium_url=device.appium_url,
            status=DeviceStatus.AVAILABLE.value
        )
        db.add(db_device)
        db.commit()
        db.refresh(db_device)
        return db_device

    def lock_device(self, db: Session, device_id: int, user_id: int):
        device = self.get_device_by_id(db, device_id)
        # Status 'available' ise veya 'offline' ise (ama offline iken locklamak riskli)
        # Sadece available ise kilitle
        if device and device.status == DeviceStatus.AVAILABLE.value:
            device.status = DeviceStatus.BUSY.value
            device.current_user_id = user_id
            db.commit()
            return True
        return False

    def release_device(self, db: Session, device_id: int, user_id: int):
        device = self.get_device_by_id(db, device_id)
        if device:
            device.status = DeviceStatus.AVAILABLE.value
            device.current_user_id = None
            db.commit()
            return True
        return False

    def sync_adb_devices(self, db: Session):
        """ADB ile bağlı cihazları tarar ve veritabanını günceller"""
        try:
            adb_path = shutil.which("adb")
            if not adb_path:
                # Windows yolları
                user_path = os.path.expanduser("~")
                paths = [
                    os.path.join(user_path, "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
                    "C:\\platform-tools\\adb.exe"
                ]
                for p in paths:
                    if os.path.exists(p):
                        adb_path = p
                        break
            
            if not adb_path: return

            # Komutu Çalıştır
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            output = subprocess.check_output([adb_path, 'devices'], encoding='utf-8', startupinfo=startupinfo)
            lines = output.strip().split('\n')[1:]
            
            connected_ids = []
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 2 and parts[1] == 'device':
                    udid = parts[0]
                    connected_ids.append(udid)
                    
                    # Cihazı DB'de bul
                    dev = db.query(Device).filter(Device.device_id == udid).first()
                    if not dev:
                        print(f"🆕 ADB Yeni Cihaz Buldu: {udid}")
                        new_dev = Device(name=f"Android_{udid[:4]}", device_id=udid, type="physical", os="android", status="available")
                        db.add(new_dev)
                    else:
                        # Eğer cihaz OFFLINE ise AVAILABLE yap
                        if dev.status == "offline":
                            dev.status = "available"
                            print(f"✅ Cihaz {udid} tekrar ONLINE oldu.")
            
            # 3. Bağlı olmayanları OFFLINE yap
            all_devs = db.query(Device).all()
            for d in all_devs:
                # Sadece fiziksel cihazları kontrol et
                if d.type == "physical" and d.device_id not in connected_ids:
                    # Meşgul değilse offline yap (Meşgulse test koşuyordur, dokunma)
                    if d.status != "busy" and d.status != "offline":
                        d.status = "offline"
                        print(f"❌ Cihaz {d.device_id} bağlantısı koptu (OFFLINE).")
            
            db.commit()

        except Exception as e:
            print(f"Sync Hatası: {e}")

device_service = DeviceService()