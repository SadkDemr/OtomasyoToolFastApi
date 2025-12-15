"""
Emulator Router - /api/emulator/*
WebSocket ile canli ekran ve log
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.emulator_service import emulator_service

router = APIRouter(prefix="/api/emulator", tags=["Emulator"])


class TapRequest(BaseModel):
    x: int
    y: int


class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration: int = 300


class TextRequest(BaseModel):
    text: str


class LaunchRequest(BaseModel):
    package: str
    activity: str = ""


@router.get("/status")
async def get_status():
    adb_ok = emulator_service.is_adb_available()
    devices = emulator_service.get_connected_devices() if adb_ok else []
    return {
        "adb_available": adb_ok,
        "adb_path": emulator_service.adb_path,
        "connected_devices": devices
    }


@router.get("/devices")
async def get_devices():
    devices = emulator_service.get_connected_devices()
    return {"devices": devices, "count": len(devices)}


@router.post("/{device_id}/connect")
async def connect(device_id: str):
    if not emulator_service.is_adb_available():
        raise HTTPException(503, "ADB bulunamadi")
    
    devices = emulator_service.get_connected_devices()
    ids = [d['device_id'] for d in devices]
    
    if device_id not in ids:
        raise HTTPException(404, f"Cihaz bagli degil: {device_id}")
    
    emulator_service.create_session(device_id, 1)
    size = emulator_service.get_screen_size(device_id)
    
    return {"success": True, "screen_width": size[0], "screen_height": size[1]}


@router.post("/{device_id}/disconnect")
async def disconnect(device_id: str):
    emulator_service.close_session(device_id)
    return {"success": True}


@router.post("/{device_id}/launch")
async def launch_app(device_id: str, req: LaunchRequest):
    ok = emulator_service.launch_app(device_id, req.package, req.activity)
    return {"success": ok}


@router.post("/{device_id}/tap")
async def tap(device_id: str, req: TapRequest):
    ok = emulator_service.send_tap(device_id, req.x, req.y)
    return {"success": ok}


@router.post("/{device_id}/swipe")
async def swipe(device_id: str, req: SwipeRequest):
    ok = emulator_service.send_swipe(device_id, req.x1, req.y1, req.x2, req.y2, req.duration)
    return {"success": ok}


@router.post("/{device_id}/text")
async def text(device_id: str, req: TextRequest):
    ok = emulator_service.send_text(device_id, req.text)
    return {"success": ok}


@router.post("/{device_id}/back")
async def back(device_id: str):
    return {"success": emulator_service.press_back(device_id)}


@router.post("/{device_id}/home")
async def home(device_id: str):
    return {"success": emulator_service.press_home(device_id)}


@router.post("/{device_id}/recent")
async def recent(device_id: str):
    return {"success": emulator_service.press_recent(device_id)}


@router.get("/{device_id}/screen")
async def get_screen(device_id: str):
    """Tek frame al"""
    frame = emulator_service.capture_screen(device_id)
    if frame:
        return {"success": True, "image": frame}
    return {"success": False, "message": "Frame alinamadi"}


@router.get("/{device_id}/logs")
async def get_logs(device_id: str):
    return {"logs": emulator_service.get_logs(device_id)}


@router.delete("/{device_id}/logs")
async def clear_logs(device_id: str):
    emulator_service.clear_logs(device_id)
    return {"success": True}


@router.get("/{device_id}/test/state")
async def test_state(device_id: str):
    return emulator_service.get_test_state(device_id)


@router.post("/{device_id}/test/stop")
async def stop(device_id: str):
    emulator_service.stop_test(device_id)
    return {"success": True}


@router.websocket("/{device_id}/stream")
async def stream(websocket: WebSocket, device_id: str):
    await websocket.accept()
    print(f"[WS] Connected: {device_id}")
    
    # Session yoksa olustur
    session = emulator_service.ensure_session(device_id, 1)
    
    try:
        # Baslangic bilgisi
        size = emulator_service.get_screen_size(device_id)
        await websocket.send_json({
            "type": "init", 
            "width": size[0], 
            "height": size[1]
        })
        
        last_frame_hash = None
        last_log_count = 0
        
        while True:
            # Gelen mesajlari kontrol et
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                data = json.loads(msg)
                
                msg_type = data.get("type", "")
                
                if msg_type == "tap":
                    emulator_service.send_tap(device_id, data["x"], data["y"])
                elif msg_type == "swipe":
                    emulator_service.send_swipe(device_id, data["x1"], data["y1"], data["x2"], data["y2"], data.get("duration", 300))
                elif msg_type == "text":
                    emulator_service.send_text(device_id, data["text"])
                elif msg_type == "back":
                    emulator_service.press_back(device_id)
                elif msg_type == "home":
                    emulator_service.press_home(device_id)
                elif msg_type == "recent":
                    emulator_service.press_recent(device_id)
                    
            except asyncio.TimeoutError:
                pass
            
            # Frame gonder
            frame = emulator_service.get_cached_frame(device_id)
            frame_hash = hash(frame) if frame else None
            
            # Test state al
            state = emulator_service.get_test_state(device_id)
            current_log_count = len(state.get("logs", []))
            
            # Frame veya log degistiyse gonder
            should_send = False
            
            if frame and frame_hash != last_frame_hash:
                should_send = True
                last_frame_hash = frame_hash
            
            if current_log_count != last_log_count:
                should_send = True
                last_log_count = current_log_count
            
            if should_send:
                await websocket.send_json({
                    "type": "frame",
                    "image": frame,
                    "test_state": state
                })
            
            # 50ms bekle
            await asyncio.sleep(0.05)
            
    except WebSocketDisconnect:
        print(f"[WS] Disconnected: {device_id}")
    except Exception as e:
        print(f"[WS] Error: {e}")
