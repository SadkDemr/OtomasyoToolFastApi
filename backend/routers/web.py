"""
Web Test Router
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException
from models.schemas import WebTestRequest, WebTestResponse, InputType
from services.selenium_service import selenium_service

router = APIRouter(prefix="/api/web", tags=["Web Test"])


@router.post("/run-test", response_model=WebTestResponse)
async def run_web_test(request: WebTestRequest):
    """Web testi baslat"""
    try:
        if request.input_type == InputType.NATURAL:
            if not request.natural_text:
                raise HTTPException(400, "natural_text gerekli")
            steps = selenium_service.parse_natural_language(request.natural_text)
        else:
            steps = request.steps or []
        
        if not steps:
            raise HTTPException(400, "Test adimi bulunamadi")
        
        result = selenium_service.run_test(
            url=request.url,
            steps=steps,
            headless=request.headless,
            stop_on_fail=request.stop_on_fail
        )
        return WebTestResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/parse")
async def parse_natural(text: str):
    """Dogal dili parse et"""
    steps = selenium_service.parse_natural_language(text)
    return {"count": len(steps), "steps": [s.dict() for s in steps]}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "web_test"}
