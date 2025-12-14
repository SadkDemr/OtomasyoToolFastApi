"""
Devices Router - /api/devices/*
Cihaz CRUD ve Kilitleme islemleri
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.db_models import User
from models.schemas import (
    DeviceCreate, DeviceUpdate, DeviceResponse, 
    DeviceListResponse, DeviceLockResponse, DeviceType
)
from services.device_service import device_service
from routers.auth import get_current_user

router = APIRouter(prefix="/api/devices", tags=["Devices"])


# ============ HELPER ============

def device_to_response(device, db: Session = None) -> DeviceResponse:
    """Device model'i response'a çevir"""
    current_user_name = None
    if device.current_user_id and db:
        user = db.query(User).filter(User.id == device.current_user_id).first()
        if user:
            current_user_name = user.username
    
    return DeviceResponse(
        id=device.id,
        name=device.name,
        device_id=device.device_id,
        type=device.type,
        os=device.os,
        os_version=device.os_version,
        appium_url=device.appium_url,
        status=device.status,
        current_user_id=device.current_user_id,
        current_user_name=current_user_name,
        locked_at=device.locked_at,
        is_active=device.is_active,
        created_at=device.created_at
    )


# ============ ENDPOINTS ============

@router.get("", response_model=DeviceListResponse)
async def list_devices(
    type: Optional[str] = Query(None, description="Filtre: emulator, physical"),
    db: Session = Depends(get_db)
):
    """
    Tüm cihazları listele (login gerekmez)
    
    - **type**: Opsiyonel filtre (emulator/physical)
    """
    
    if type:
        devices = device_service.get_devices_by_type(db, type)
    else:
        devices = device_service.get_all_devices(db)
    
    available = sum(1 for d in devices if d.status == "available")
    in_use = sum(1 for d in devices if d.status == "in_use")
    
    return DeviceListResponse(
        total=len(devices),
        available=available,
        in_use=in_use,
        devices=[device_to_response(d, db) for d in devices]
    )


@router.get("/available", response_model=DeviceListResponse)
async def list_available_devices(db: Session = Depends(get_db)):
    """
    Müsait cihazları listele
    """
    
    devices = device_service.get_available_devices(db)
    
    return DeviceListResponse(
        total=len(devices),
        available=len(devices),
        in_use=0,
        devices=[device_to_response(d, db) for d in devices]
    )


@router.get("/my", response_model=Optional[DeviceResponse])
async def get_my_device(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Benim kullandığım cihaz
    """
    
    device = device_service.get_user_current_device(db, current_user.id)
    
    if not device:
        return None
    
    return device_to_response(device, db)


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, db: Session = Depends(get_db)):
    """
    Cihaz detayı
    """
    
    device = device_service.get_device_by_id(db, device_id)
    
    if not device:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı")
    
    return device_to_response(device, db)


@router.post("", response_model=DeviceResponse)
async def create_device(
    data: DeviceCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Yeni cihaz ekle (Admin)
    
    - **name**: Cihaz adı
    - **device_id**: UDID veya emulator-5554
    - **type**: emulator, physical
    - **os**: android, ios
    - **os_version**: OS versiyonu
    - **appium_url**: Appium server URL
    """
    
    # Admin kontrolü
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    result = device_service.create_device(db, data)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return device_to_response(result["device"], db)


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int,
    data: DeviceUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihaz güncelle (Admin)
    """
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    result = device_service.update_device(db, device_id, data)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return device_to_response(result["device"], db)


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihaz sil (Admin)
    """
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    result = device_service.delete_device(db, device_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@router.post("/{device_id}/lock", response_model=DeviceLockResponse)
async def lock_device(
    device_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihazı kilitle (kullanmaya başla)
    
    Başarılı olursa cihaz "in_use" olur ve 
    diğer kullanıcılar bu cihazı kullanamaz.
    """
    
    result = device_service.lock_device(db, device_id, current_user.id)
    
    device_resp = None
    if result.get("device"):
        device_resp = device_to_response(result["device"], db)
    
    return DeviceLockResponse(
        success=result["success"],
        message=result["message"],
        device=device_resp
    )


@router.post("/{device_id}/unlock", response_model=DeviceLockResponse)
async def unlock_device(
    device_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihaz kilidini aç (kullanımı bırak)
    
    Sadece cihazı kilitleyen kişi veya admin açabilir.
    """
    
    is_admin = current_user.role == "admin"
    result = device_service.unlock_device(db, device_id, current_user.id, is_admin)
    
    device_resp = None
    if result.get("device"):
        device_resp = device_to_response(result["device"], db)
    
    return DeviceLockResponse(
        success=result["success"],
        message=result["message"],
        device=device_resp
    )


@router.post("/{device_id}/offline")
async def set_offline(
    device_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihazı çevrimdışı yap (Admin)
    """
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    result = device_service.set_device_offline(db, device_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@router.post("/{device_id}/online")
async def set_online(
    device_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cihazı çevrimiçi yap (Admin)
    """
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    
    result = device_service.set_device_online(db, device_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result
