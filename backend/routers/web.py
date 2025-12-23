"""
Web Test Router - /api/web/*
Web otomasyon testleri için endpoint'ler
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter(prefix="/api/web", tags=["Web Test"])


class WebTestStep(BaseModel):
    action: str = ""
    target: str = ""
    value: str = ""
    locator_type: str = "auto"


class WebTestRequest(BaseModel):
    url: str = ""
    input_type: str = "natural"  # natural | steps
    natural_text: str = ""
    steps: List[WebTestStep] = []
    headless: bool = False
    stop_on_fail: bool = True


class WebTestResponse(BaseModel):
    test_id: str
    success: bool
    message: str
    summary: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = []
    duration: float = 0


@router.post("/run-test", response_model=WebTestResponse)
async def run_web_test(request: WebTestRequest):
    """Web testi çalıştır"""
    
    try:
        from services.selenium_service import selenium_service
    except ImportError as e:
        raise HTTPException(500, f"Selenium service yüklenemedi: {e}")
    
    # Natural language parse
    if request.input_type == "natural" and request.natural_text:
        steps = selenium_service.parse_natural_language(request.natural_text)
    else:
        steps = [
            type('Step', (), {
                'action': s.action,
                'target': s.target,
                'value': s.value,
                'locator_type': s.locator_type
            })()
            for s in request.steps
        ]
    
    if not steps:
        raise HTTPException(400, "Test adımları boş veya parse edilemedi")
    
    # Testi çalıştır
    result = selenium_service.run_test(
        url=request.url,
        steps=steps,
        headless=request.headless,
        stop_on_fail=request.stop_on_fail
    )
    
    return WebTestResponse(
        test_id=result.get("test_id", ""),
        success=result.get("success", False),
        message=result.get("message", ""),
        summary=result.get("summary"),
        results=[
            {
                "step_number": r.step_number,
                "action": r.action,
                "success": r.success,
                "message": r.message
            }
            for r in result.get("results", [])
        ],
        duration=result.get("duration", 0)
    )


@router.post("/parse-natural")
async def parse_natural_language(text: str):
    """Doğal dil metnini test adımlarına çevir"""
    try:
        from services.selenium_service import selenium_service
        steps = selenium_service.parse_natural_language(text)
        return {
            "success": True,
            "steps": [
                {
                    "action": s.action,
                    "target": s.target,
                    "value": s.value,
                    "locator_type": getattr(s, 'locator_type', 'auto')
                }
                for s in steps
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/status")
async def get_status():
    """Selenium servis durumu"""
    try:
        from services.selenium_service import selenium_service
        return {
            "available": True,
            "message": "Selenium servisi hazır"
        }
    except Exception as e:
        return {
            "available": False,
            "message": str(e)
        }