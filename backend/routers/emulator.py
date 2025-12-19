"""
Emulator Router - /api/emulator/*
FIXED: Log ve State Guncellemeleri Ekran Goruntusunden Bagimsiz Hale Getirildi.
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from services.emulator_service import emulator_service

router = APIRouter(prefix="/api/emulator", tags=["Emulator"])

# --- Request Modelleri (Ayni) ---
class TapRequest(BaseModel):
    x: int; y: int
class SwipeRequest(BaseModel):
    x1: int; y1: int; x2: int; y2: int; duration: int = 300
class TextRequest(BaseModel):
    text: str

# --- Standart Endpointler (Ayni) ---
@router.get("/status")
async def get_status():
    adb_ok = emulator_service.is_adb_available()
    devices = emulator_service.get_connected_devices() if adb_ok else []
    return {"adb_available": adb_ok, "connected_devices": devices}

@router.get("/devices")
async def get_devices():
    devices = emulator_service.get_connected_devices()
    return {"devices": devices, "count": len(devices)}

@router.post("/{device_id}/connect")
async def connect(device_id: str):
    if not emulator_service.is_adb_available(): raise HTTPException(503, "ADB yok")
    emulator_service.create_session(device_id, 1)
    size = emulator_service.get_screen_size(device_id)
    return {"success": True, "screen_width": size[0], "screen_height": size[1]}

@router.post("/{device_id}/disconnect")
async def disconnect(device_id: str):
    emulator_service.close_session(device_id)
    return {"success": True}

# --- Input Endpointleri (Ayni) ---
@router.post("/{device_id}/tap")
async def tap(device_id: str, req: TapRequest):
    return {"success": emulator_service.send_tap(device_id, req.x, req.y)}

@router.post("/{device_id}/swipe")
async def swipe(device_id: str, req: SwipeRequest):
    return {"success": emulator_service.send_swipe(device_id, req.x1, req.y1, req.x2, req.y2, req.duration)}

@router.post("/{device_id}/text")
async def text(device_id: str, req: TextRequest):
    return {"success": emulator_service.send_text(device_id, req.text)}

@router.post("/{device_id}/back")
async def back(device_id: str): return {"success": emulator_service.press_back(device_id)}
@router.post("/{device_id}/home")
async def home(device_id: str): return {"success": emulator_service.press_home(device_id)}
@router.post("/{device_id}/recent")
async def recent(device_id: str): return {"success": emulator_service.press_recent(device_id)}

@router.get("/{device_id}/logs")
async def get_logs(device_id: str): return {"logs": emulator_service.get_logs(device_id)}

@router.delete("/{device_id}/logs")
async def clear_logs(device_id: str): emulator_service.clear_logs(device_id); return {"success": True}

@router.post("/{device_id}/test/stop")
async def stop(device_id: str): emulator_service.stop_test(device_id); return {"success": True}


# --- WEBSOCKET (Kritik Guncelleme) ---
@router.websocket("/{device_id}/stream")
async def stream(websocket: WebSocket, device_id: str):
    await websocket.accept()
    session = emulator_service.ensure_session(device_id, 1)
    
    try:
        size = emulator_service.get_screen_size(device_id)
        # Frontend'e ekran boyutunu bildir
        await websocket.send_json({"type": "init", "width": size[0], "height": size[1]})
        
        last_frame_hash = None
        last_log_count = -1
        last_status = ""
        
        while True:
            # 1. Gelen mesajlari al (Non-blocking)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                data = json.loads(msg)
                mtype = data.get("type")
                
                if mtype == "tap": emulator_service.send_tap(device_id, data["x"], data["y"])
                elif mtype == "swipe": emulator_service.send_swipe(device_id, data["x1"], data["y1"], data["x2"], data["y2"], data.get("duration", 300))
                elif mtype == "text": emulator_service.send_text(device_id, data["text"])
                elif mtype == "back": emulator_service.press_back(device_id)
                elif mtype == "home": emulator_service.press_home(device_id)
                elif mtype == "recent": emulator_service.press_recent(device_id)
            except asyncio.TimeoutError:
                pass
            except Exception:
                break # Baglanti koptu
            
            # 2. Verileri Hazirla
            frame = emulator_service.get_cached_frame(device_id)
            state = emulator_service.get_test_state(device_id)
            
            # --- DEGİSİKLİK KONTROLU ---
            
            # A) Ekran Degisti mi?
            current_frame_hash = hash(frame) if frame else 0
            if frame and current_frame_hash != last_frame_hash:
                try:
                    await websocket.send_json({
                        "type": "frame",
                        "image": frame
                    })
                    last_frame_hash = current_frame_hash
                except: break

            # B) Loglar veya Durum Degisti mi? (Ekrandan bagimsiz gonder)
            current_logs = state.get("logs", [])
            current_status = state.get("state", "idle")
            
            if len(current_logs) != last_log_count or current_status != last_status:
                try:
                    await websocket.send_json({
                        "type": "state", # Yeni tip: Sadece durum guncellemesi
                        "test_state": state
                    })
                    last_log_count = len(current_logs)
                    last_status = current_status
                except: break
            
            # 100ms bekle
            await asyncio.sleep(0.1)
            
    except WebSocketDisconnect:
        pass