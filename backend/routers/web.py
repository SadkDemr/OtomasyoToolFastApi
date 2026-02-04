"""
Web Test Router - /api/web/*
- Canlı log akışı (WebSocket)
- Her adımda screenshot
- PDF rapor (screenshot'lı)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
import json
import uuid
import threading
from pathlib import Path
from queue import Queue

router = APIRouter(prefix="/api/web", tags=["Web Test"])

# Aktif WebSocket bağlantıları
active_websockets: Dict[str, WebSocket] = {}

# Test sonuçları cache (PDF için)
test_results_cache: Dict[str, Dict] = {}

# Log queue'ları (thread-safe)
log_queues: Dict[str, Queue] = {}


class WebTestRequest(BaseModel):
    url: str = ""
    input_type: str = "natural"
    natural_text: str = ""
    steps: List[Dict] = []
    headless: bool = True
    stop_on_fail: bool = True
    scenario_name: str = "Web Test"


# ============ WEBSOCKET ============

@router.websocket("/ws/{test_id}")
async def websocket_endpoint(websocket: WebSocket, test_id: str):
    """Canlı test logları için WebSocket"""
    await websocket.accept()
    active_websockets[test_id] = websocket
    log_queues[test_id] = Queue()
    print(f"[WS] Bağlandı: {test_id}")
    
    try:
        # Log queue'dan mesajları gönder
        while True:
            # Queue'da mesaj var mı kontrol et
            if test_id in log_queues and not log_queues[test_id].empty():
                while not log_queues[test_id].empty():
                    data = log_queues[test_id].get_nowait()
                    await websocket.send_json(data)
                    
                    # Test bittiyse çık
                    if data.get("type") == "complete":
                        return
            
            # Client'tan ping bekle
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass
                
    except WebSocketDisconnect:
        print(f"[WS] Bağlantı kapandı: {test_id}")
    except Exception as e:
        print(f"[WS] Hata: {e}")
    finally:
        if test_id in active_websockets:
            del active_websockets[test_id]
        if test_id in log_queues:
            del log_queues[test_id]


def queue_log(test_id: str, data: dict):
    """Log'u queue'ya ekle (thread-safe)"""
    if test_id in log_queues:
        log_queues[test_id].put(data)


# ============ TEST ENDPOINT (CANLI LOG) ============

@router.post("/start-test")
async def start_test(request: WebTestRequest, background_tasks: BackgroundTasks):
    """
    Test başlat - WebSocket üzerinden canlı log
    """
    test_id = str(uuid.uuid4())[:8]
    log_queues[test_id] = Queue()
    
    # Background'da testi çalıştır
    background_tasks.add_task(
        run_test_background,
        test_id,
        request.url,
        request.natural_text,
        request.headless,
        request.stop_on_fail,
        request.scenario_name
    )
    
    return {
        "test_id": test_id,
        "ws_url": f"/api/web/ws/{test_id}",
        "message": "Test başlatıldı"
    }


def run_test_background(test_id: str, url: str, natural_text: str, 
                        headless: bool, stop_on_fail: bool, scenario_name: str):
    """Background'da test çalıştır"""
    
    try:
        from services.selenium_service import selenium_service
    except ImportError as e:
        queue_log(test_id, {"type": "error", "message": str(e)})
        return
    
    steps = selenium_service.parse_natural_language(natural_text)
    if not steps:
        queue_log(test_id, {"type": "error", "message": "Adımlar parse edilemedi"})
        return
    
    # Her adımda çağrılacak callback
    def live_callback(data):
        data["test_id"] = test_id
        data["type"] = "step"
        queue_log(test_id, data)
    
    # Testi çalıştır
    selenium_service.current_test_id = test_id
    result = selenium_service.run_test(
        url=url,
        steps=steps,
        headless=headless,
        stop_on_fail=stop_on_fail,
        log_callback=live_callback,
        scenario_name=scenario_name
    )
    
    # PDF oluştur
    pdf_path = selenium_service.generate_pdf_report(scenario_name)
    pdf_url = f"/api/web/report/{os.path.basename(pdf_path)}" if pdf_path else None
    
    # Cache'le
    test_results_cache[test_id] = {"result": result, "pdf_url": pdf_url}
    
    # Test bitti bildirimi
    queue_log(test_id, {
        "type": "complete",
        "test_id": test_id,
        "success": result.get("success", False),
        "message": result.get("message", ""),
        "summary": result.get("summary"),
        "duration": result.get("duration", 0),
        "pdf_url": pdf_url,
        "detailed_results": result.get("detailed_results", [])
    })


# ============ SYNC TEST ============

@router.post("/run-test")
async def run_web_test(request: WebTestRequest):
    """Senkron test - canlı log yok, sonucu bekler"""
    
    try:
        from services.selenium_service import selenium_service
    except ImportError as e:
        raise HTTPException(500, f"Selenium service yüklenemedi: {e}")
    
    if request.input_type == "natural" and request.natural_text:
        steps = selenium_service.parse_natural_language(request.natural_text)
    else:
        steps = [
            type('Step', (), {
                'action': s.get('action', ''),
                'target': s.get('target', ''),
                'value': s.get('value', ''),
                'locator_type': s.get('locator_type', 'auto')
            })()
            for s in request.steps
        ]
    
    if not steps:
        raise HTTPException(400, "Test adımları boş")
    
    result = selenium_service.run_test(
        url=request.url,
        steps=steps,
        headless=request.headless,
        stop_on_fail=request.stop_on_fail,
        scenario_name=request.scenario_name
    )
    
    pdf_path = selenium_service.generate_pdf_report(request.scenario_name)
    pdf_url = f"/api/web/report/{os.path.basename(pdf_path)}" if pdf_path else None
    
    return {
        "test_id": result.get("test_id", ""),
        "success": result.get("success", False),
        "message": result.get("message", ""),
        "summary": result.get("summary"),
        "results": [
            {"step_number": r.step_number, "action": r.action, "success": r.success, "message": r.message}
            for r in result.get("results", [])
        ],
        "detailed_results": result.get("detailed_results", []),
        "duration": result.get("duration", 0),
        "pdf_url": pdf_url
    }


# ============ PDF RAPOR ============

@router.get("/report/{filename}")
async def download_report(filename: str):
    """PDF rapor indir"""
    reports_dir = Path("reports")
    filepath = reports_dir / filename
    
    if not filepath.exists():
        matching = list(reports_dir.glob(f"*{filename.split('.')[0]}*.pdf"))
        if matching:
            filepath = matching[-1]
        else:
            raise HTTPException(404, "Rapor bulunamadı")
    
    return FileResponse(path=str(filepath), filename=filepath.name, media_type="application/pdf")


@router.get("/reports")
async def list_reports():
    """Tüm raporları listele"""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    
    return [
        {"filename": f.name, "url": f"/api/web/report/{f.name}", "size": f.stat().st_size}
        for f in sorted(reports_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)
    ][:20]


@router.get("/test-result/{test_id}")
async def get_test_result(test_id: str):
    """Test sonucunu getir"""
    if test_id in test_results_cache:
        return test_results_cache[test_id]
    raise HTTPException(404, "Test sonucu bulunamadı")


@router.get("/status")
async def get_status():
    try:
        from services.selenium_service import selenium_service, PDF_AVAILABLE
        return {"available": True, "pdf_available": PDF_AVAILABLE}
    except Exception as e:
        return {"available": False, "message": str(e)}