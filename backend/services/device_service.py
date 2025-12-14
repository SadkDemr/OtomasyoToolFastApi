"""
Device Service - Cihaz Yonetimi (CRUD + Kilitleme)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from models.db_models import Device, User, DeviceStatus
from models.schemas import DeviceCreate, DeviceUpdate


class DeviceService:
    """Cihaz Yönetim Servisi"""
    
    def get_all_devices(self, db: Session, include_inactive: bool = False) -> List[Device]:
        """Tüm cihazları getir"""
        query = db.query(Device)
        if not include_inactive:
            query = query.filter(Device.is_active == True)
        return query.all()
    
    def get_device_by_id(self, db: Session, device_id: int) -> Optional[Device]:
        """ID ile cihaz getir"""
        return db.query(Device).filter(Device.id == device_id).first()
    
    def get_device_by_device_id(self, db: Session, device_id: str) -> Optional[Device]:
        """UDID ile cihaz getir"""
        return db.query(Device).filter(Device.device_id == device_id).first()
    
    def get_devices_by_type(self, db: Session, device_type: str) -> List[Device]:
        """Tipe göre cihazlar (emulator/physical)"""
        return db.query(Device).filter(
            Device.type == device_type,
            Device.is_active == True
        ).all()
    
    def get_available_devices(self, db: Session) -> List[Device]:
        """Müsait cihazları getir"""
        return db.query(Device).filter(
            Device.status == DeviceStatus.AVAILABLE.value,
            Device.is_active == True
        ).all()
    
    def create_device(self, db: Session, device_data: DeviceCreate) -> dict:
        """Yeni cihaz ekle"""
        
        # UDID kontrolü
        existing = self.get_device_by_device_id(db, device_data.device_id)
        if existing:
            return {"success": False, "message": "Bu cihaz ID zaten kayıtlı"}
        
        new_device = Device(
            name=device_data.name,
            device_id=device_data.device_id,
            type=device_data.type.value,
            os=device_data.os.value,
            os_version=device_data.os_version,
            appium_url=device_data.appium_url,
            status=DeviceStatus.AVAILABLE.value
        )
        
        db.add(new_device)
        db.commit()
        db.refresh(new_device)
        
        return {"success": True, "message": "Cihaz eklendi", "device": new_device}
    
    def update_device(self, db: Session, device_id: int, device_data: DeviceUpdate) -> dict:
        """Cihaz güncelle"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        if device_data.name is not None:
            device.name = device_data.name
        if device_data.os_version is not None:
            device.os_version = device_data.os_version
        if device_data.appium_url is not None:
            device.appium_url = device_data.appium_url
        if device_data.status is not None:
            device.status = device_data.status.value
        
        db.commit()
        db.refresh(device)
        
        return {"success": True, "message": "Cihaz güncellendi", "device": device}
    
    def delete_device(self, db: Session, device_id: int) -> dict:
        """Cihaz sil (soft delete)"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        if device.status == DeviceStatus.IN_USE.value:
            return {"success": False, "message": "Cihaz kullanımda, önce serbest bırakın"}
        
        device.is_active = False
        db.commit()
        
        return {"success": True, "message": "Cihaz silindi"}
    
    def lock_device(self, db: Session, device_id: int, user_id: int) -> dict:
        """Cihazı kilitle (kullanıcıya ata)"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        if not device.is_active:
            return {"success": False, "message": "Cihaz aktif değil"}
        
        if device.status == DeviceStatus.IN_USE.value:
            # Başka biri kullanıyor mu?
            if device.current_user_id != user_id:
                user = db.query(User).filter(User.id == device.current_user_id).first()
                user_name = user.username if user else "Bilinmiyor"
                return {
                    "success": False, 
                    "message": f"Cihaz şu anda {user_name} tarafından kullanılıyor"
                }
            else:
                return {"success": True, "message": "Cihaz zaten sizde", "device": device}
        
        if device.status == DeviceStatus.OFFLINE.value:
            return {"success": False, "message": "Cihaz çevrimdışı"}
        
        # Kilitle
        device.status = DeviceStatus.IN_USE.value
        device.current_user_id = user_id
        device.locked_at = datetime.utcnow()
        
        db.commit()
        db.refresh(device)
        
        return {"success": True, "message": "Cihaz kilitlendi", "device": device}
    
    def unlock_device(self, db: Session, device_id: int, user_id: int, is_admin: bool = False) -> dict:
        """Cihaz kilidini aç"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        if device.status != DeviceStatus.IN_USE.value:
            return {"success": False, "message": "Cihaz zaten serbest"}
        
        # Sadece kilitleyen veya admin açabilir
        if device.current_user_id != user_id and not is_admin:
            return {"success": False, "message": "Bu cihazı sadece kilitleyen kişi veya admin açabilir"}
        
        # Kilidi aç
        device.status = DeviceStatus.AVAILABLE.value
        device.current_user_id = None
        device.locked_at = None
        
        db.commit()
        db.refresh(device)
        
        return {"success": True, "message": "Cihaz serbest bırakıldı", "device": device}
    
    def set_device_offline(self, db: Session, device_id: int) -> dict:
        """Cihazı offline yap"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        device.status = DeviceStatus.OFFLINE.value
        device.current_user_id = None
        device.locked_at = None
        
        db.commit()
        db.refresh(device)
        
        return {"success": True, "message": "Cihaz çevrimdışı yapıldı", "device": device}
    
    def set_device_online(self, db: Session, device_id: int) -> dict:
        """Cihazı online yap"""
        
        device = self.get_device_by_id(db, device_id)
        if not device:
            return {"success": False, "message": "Cihaz bulunamadı"}
        
        device.status = DeviceStatus.AVAILABLE.value
        
        db.commit()
        db.refresh(device)
        
        return {"success": True, "message": "Cihaz çevrimiçi yapıldı", "device": device}
    
    def get_user_current_device(self, db: Session, user_id: int) -> Optional[Device]:
        """Kullanıcının şu an kullandığı cihaz"""
        return db.query(Device).filter(Device.current_user_id == user_id).first()


# Singleton
device_service = DeviceService()
