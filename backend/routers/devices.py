"""
Devices Router - Cihaz Yonetimi API
FIXED: Boolean handling for lock/unlock functions solved.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models.schemas import DeviceCreate, DeviceUpdate, DeviceResponse, DeviceListResponse, DeviceLockResponse
from services.device_service import device_service
from routers.auth import get_current_user
from models.db_models import Device

router = APIRouter(prefix="/api/devices", tags=["Devices"])

def device_to_response(device: Device, db: Session) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        device_id=device.device_id,
        type=device.type,
        os=device.os,
        os_version=device.os_version,
        appium_url=device.appium_url,
        status=device.status,
        current_user_id=device.current_user_id
    )

@router.get("", response_model=DeviceListResponse)
def list_devices(db: Session = Depends(get_db)):
    devices = device_service.get_all_devices(db)
    response_list = [device_to_response(d, db) for d in devices]
    return DeviceListResponse(devices=response_list)

@router.post("", response_model=DeviceResponse)
def create_device(data: DeviceCreate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        new_device = device_service.create_device(db, data)
        return device_to_response(new_device, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{device_id}", response_model=DeviceResponse)
def update_device(device_id: int, data: DeviceUpdate, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    updated_device = device_service.update_device(db, device_id, data)
    if not updated_device:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı")
    return device_to_response(updated_device, db)

@router.post("/{device_id}/lock", response_model=DeviceLockResponse)
def lock_device(device_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    # FIX: Servis True/False döner. Dictionary değil.
    is_locked = device_service.lock_device(db, device_id, current_user.id)
    
    if not is_locked:
         raise HTTPException(status_code=400, detail="Cihaz kilitlenemedi. Müsait olmayabilir.")
    
    # Başarılı ise güncel cihaz bilgisini çekip dönelim
    device = device_service.get_device_by_id(db, device_id)
    return DeviceLockResponse(
        success=True,
        message="Cihaz kilitlendi",
        device=device_to_response(device, db)
    )

@router.post("/{device_id}/release", response_model=DeviceLockResponse)
def release_device(device_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    # FIX: Servis True/False döner.
    is_released = device_service.release_device(db, device_id, current_user.id)
    
    if not is_released:
         raise HTTPException(status_code=400, detail="Cihaz kilidi açılamadı.")
    
    device = device_service.get_device_by_id(db, device_id)
    return DeviceLockResponse(
        success=True,
        message="Cihaz serbest bırakıldı",
        device=device_to_response(device, db) if device else None
    )

@router.delete("/{device_id}")
def delete_device(device_id: int, current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    success = device_service.delete_device(db, device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True, "message": "Device deleted"}