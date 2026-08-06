"""
Device Service - FIXED
Uses DeviceStatus Enum consistently to fix display issues.
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

    def get_available_devices(self, db: Session):
        return db.query(Device).filter(Device.status == DeviceStatus.AVAILABLE.value).all()

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

    def update_status(self, db: Session, device_id: int, status: str):
        """Helper to update status easily"""
        dev = self.get_device_by_id(db, device_id)
        if dev:
            dev.status = status
            db.commit()
            db.refresh(dev)

    def lock_device(self, db: Session, device_id: int, user_id: int):
        device = db.query(Device).filter(Device.id == device_id).first()
        if device and device.status == DeviceStatus.AVAILABLE.value:
            device.status = DeviceStatus.BUSY.value
            device.current_user_id = user_id
            db.commit()
            db.refresh(device)
            return True
        return False

    def release_device(self, db: Session, device_id: int, user_id: int):
        device = self.get_device_by_id(db, device_id)
        if device:
            # Sadece kullaniciya aitse veya admin zorla birakiyorsa (user_id=1 genelde admindir)
            device.status = DeviceStatus.AVAILABLE.value
            device.current_user_id = None
            db.commit()
            return True
        return False

    def sync_adb_devices(self, db: Session):
        """ADB ile bağlı cihazları tarar ve veritabanını günceller"""
        try:
            # ADB yolunu bul (once proje-ici platform-tools, sonra PATH, sonra bilinen sabit konumlar
            # - emulator_service.py::_find_adb() ile ayni oncelik sirasi)
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            adb_path = os.path.join(base, "platform-tools", "adb.exe")
            if not os.path.exists(adb_path):
                adb_path = shutil.which("adb")
            if not adb_path:
                user_path = os.path.expanduser("~")
                paths = [
                    os.path.join(user_path, "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
                    "C:\\platform-tools\\adb.exe",
                    "C:\\Android\\platform-tools\\adb.exe"
                ]
                for p in paths:
                    if os.path.exists(p):
                        adb_path = p
                        break

            if not adb_path:
                print("❌ ADB bulunamadı.")
                return

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # ADB Devices komutunu çalıştır
            output = subprocess.check_output([adb_path, 'devices'], encoding='utf-8', startupinfo=startupinfo)
            lines = output.strip().split('\n')[1:] # Basligi atla
            
            connected_udids = []
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 2 and parts[1] == 'device':
                    udid = parts[0]
                    connected_udids.append(udid)
                    
                    dev = db.query(Device).filter(Device.device_id == udid).first()
                    
                    if not dev:
                        # YENI CIHAZ
                        print(f"🆕 ADB Yeni Cihaz Buldu: {udid}")
                        new_dev = Device(
                            name=f"Android_{udid[-4:]}", 
                            device_id=udid, 
                            type="physical", 
                            os="android", 
                            status=DeviceStatus.AVAILABLE.value # Enum Value
                        )
                        db.add(new_dev)
                    else:
                        # MEVCUT CIHAZ ONLINE OLDU
                        if dev.status == DeviceStatus.OFFLINE.value:
                            dev.status = DeviceStatus.AVAILABLE.value
                            print(f"✅ Cihaz {udid} tekrar ONLINE oldu.")
            
            db.commit()

            # Offline Kontrolü
            all_devs = db.query(Device).filter(Device.type == "physical").all()
            for d in all_devs:
                if d.device_id not in connected_udids:
                    # Eger bagli degilse ve durumu busy veya offline degilse -> OFFLINE yap
                    # (Busy ise test kosuyordur, hemen offline yapmayalim belki anlik kopukluktur ama genelde yapilir)
                    if d.status != DeviceStatus.OFFLINE.value:
                        d.status = DeviceStatus.OFFLINE.value
                        print(f"❌ Cihaz {d.device_id} bağlantısı koptu (OFFLINE).")
            
            db.commit()

        except Exception as e:
            print(f"Sync Hatası: {e}")

device_service = DeviceService()