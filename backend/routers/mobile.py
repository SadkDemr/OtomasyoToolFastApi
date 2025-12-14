"""
Mobile Test Router - /api/mobile/*
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.schemas import MobileTestRequest, MobileTestResponse, InputType
from services.appium_service import appium_service
from services.device_service import device_service
from routers.auth import get_current_user

router = APIRouter(prefix="/api/mobile", tags=["Mobile Test"])


@router.post("/run-test", response_model=MobileTestResponse)
async def run_mobile_test(
    request: MobileTestRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mobil test baslat
    
    - Cihaz kilitli olmali (lock)
    - Sadece kendi kilitlediginiz cihazda test yapabilirsiniz
    """
    
    if not appium_service.is_available():
        return MobileTestResponse(
            test_id="error",
            success=False,
            message="Appium kurulu degil. pip install Appium-Python-Client"
        )
    
    # Cihazi bul
    device = device_service.get_device_by_id(db, request.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadi")
    
    # Cihaz kullaniciya ait mi?
    if device.current_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu cihaz size ait degil. Once cihazi kilitleyin.")
    
    # Adimlari hazirla
    if request.input_type == InputType.NATURAL:
        if not request.natural_text:
            raise HTTPException(status_code=400, detail="natural_text gerekli")
        steps = appium_service.parse_natural_language(request.natural_text)
    else:
        steps = request.steps or []
    
    if not steps:
        raise HTTPException(status_code=400, detail="Test adimi bulunamadi")
    
    # Testi calistir
    result = appium_service.run_test(
        device=device,
        steps=steps,
        app_package=request.app_package,
        app_activity=request.app_activity,
        stop_on_fail=request.stop_on_fail
    )
    
    return MobileTestResponse(**result)


@router.post("/parse")
async def parse_natural(text: str):
    """Dogal dili parse et"""
    steps = appium_service.parse_natural_language(text)
    return {"count": len(steps), "steps": [s.dict() for s in steps]}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "mobile_test", "appium": appium_service.is_available()}