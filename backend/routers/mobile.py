"""
Mobile Test Router - /api/mobile/*
FIXED: DetachedInstanceError Cozumu (Pydantic Model kullanimi)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session
import time

from database import get_db
from models.schemas import MobileTestRequest, MobileTestResponse, InputType, DeviceResponse # DeviceResponse eklendi
from services.appium_service import appium_service
from services.device_service import device_service
from routers.auth import get_current_user

router = APIRouter(prefix="/api/mobile", tags=["Mobile Test"])


@router.post("/run-test", response_model=MobileTestResponse)
async def run_mobile_test(
    request: MobileTestRequest,
    background_tasks: BackgroundTasks,
    restart_app: bool = Query(True, description="Uygulamayi yeniden baslat"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mobil test baslat (Asenkron & Guvenli)
    """
    
    if not appium_service.is_available():
        raise HTTPException(500, "Appium kurulu degil")
    
    # Cihazi DB'den bul
    device_db = device_service.get_device_by_id(db, request.device_id)
    if not device_db:
        raise HTTPException(404, "Cihaz bulunamadi")
    
    # Yetki kontrolu
    if device_db.current_user_id != current_user.id:
        raise HTTPException(403, "Bu cihaz size ait degil. Once kilitleyin.")
    
    # KRITIK DUZELTME:
    # DB objesini (SQLAlchemy) Pydantic modeline ceviriyoruz.
    # Boylece arka planda DB session kapansa bile veriler kaybolmaz.
    device_data = DeviceResponse.model_validate(device_db)
    
    # Adimlari hazirla
    if request.input_type == InputType.NATURAL:
        if not request.natural_text:
            raise HTTPException(400, "natural_text gerekli")
        steps = appium_service.parse_natural_language(request.natural_text)
    else:
        steps = request.steps or []
    
    if not steps:
        raise HTTPException(400, "Test adimi bulunamadi")
    
    test_id = f"test_{int(time.time())}"
    
    # Arka plana at (device_data gonderiyoruz, device_db degil)
    background_tasks.add_task(
        appium_service.run_test,
        device=device_data, 
        steps=steps,
        app_package=request.app_package,
        app_activity=request.app_activity,
        stop_on_fail=request.stop_on_fail,
        restart_app=restart_app,
        test_id=test_id
    )
    
    return MobileTestResponse(
        test_id=test_id,
        success=True,
        message="Test baslatildi, loglar bekleniyor...",
        results=[] 
    )


@router.post("/parse")
async def parse_natural(text: str):
    steps = appium_service.parse_natural_language(text)
    return {"count": len(steps), "steps": [s.dict() for s in steps]}


@router.get("/health")
async def health():
    return {"status": "ok", "appium": appium_service.is_available()}