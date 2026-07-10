"""
Desktop Otomasyon - Web Backend Router
=======================================
Birebir Desktop Otomasyon v37 kaynak kodundan port edildi.
  - desktop_driver.py → Absolute Vision engine
  - recorder.py → Smart Recorder (Wide-Vision 300x300)
  - snip_tool.py → Snip/crop mantığı (frontend'de canvas ile)
  - runner.py → Senaryo çalıştırma motoru

Gerekli paketler:
  pip install pyautogui pynput pillow
  pip install opencv-python  (opsiyonel, Absolute Vision için)
  pip install pytesseract     (opsiyonel, OCR için)
  pip install pywinauto       (opsiyonel, pencere doğrulama için)

main.py'e ekleme:
  from desktop_router import router as desktop_router
  app.include_router(desktop_router, prefix="/api")
"""

import os
import io
import sys
import time
import json
import uuid
import base64
import asyncio
import logging
import datetime
import threading
import queue as queue_module
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("desktop")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(h)

router = APIRouter(prefix="/desktop", tags=["desktop"])

# ============================================================
#  DATA DIRS (kendi kendine oluşturur, core.config'e gerek yok)
# ============================================================
BASE_DATA_DIR = Path(os.environ.get("DESKTOP_DATA_DIR", "./desktop_data"))
ASSETS_DIR = BASE_DATA_DIR / "assets"
SCENARIOS_DIR = BASE_DATA_DIR / "scenarios"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#  REQUEST / RESPONSE MODELS
# ============================================================
class ScreenshotReq(BaseModel):
    region: Optional[Dict[str, int]] = None

class SaveAssetReq(BaseModel):
    name: str
    image_b64: str
    workspace_id: Optional[str] = None

class RecordReq(BaseModel):
    workspace_id: Optional[str] = None

class StepModel(BaseModel):
    type: str
    params: Dict[str, Any] = {}
    description: Optional[str] = ""

class RunReq(BaseModel):
    workspace_id: Optional[str] = None
    action_delay: float = 0.5
    steps: List[StepModel]

class SaveScenarioReq(BaseModel):
    workspace_id: Optional[str] = None
    name: str
    data: Dict[str, Any]

class ListScenariosReq(BaseModel):
    workspace_id: Optional[str] = None

class FolderReq(BaseModel):
    workspace_id: Optional[str] = None


# ============================================================
#  DPI SCALING (desktop_driver.py'den port - core.config yerine)
# ============================================================
_dpi_cache = None

def get_dpi_scaling() -> float:
    """Windows DPI ölçekleme oranını döndürür (1.0 = %100)."""
    global _dpi_cache
    if _dpi_cache is not None:
        return _dpi_cache
    _dpi_cache = 1.0
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            _dpi_cache = dpi / 96.0
            logger.info(f"DPI Scaling: {_dpi_cache:.2f}")
        except Exception as e:
            logger.debug(f"DPI algılama başarısız: {e}")
    return _dpi_cache


# ============================================================
#  LAZY IMPORTS (yoksa hata vermez, graceful degradation)
# ============================================================
_pyautogui = None
_cv2_mod = None      # None=denemedik, False=yok
_pil_image = None

def _pag():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = True
        _pyautogui = pyautogui
    return _pyautogui

def _cv2():
    global _cv2_mod
    if _cv2_mod is None:
        try:
            import cv2
            _cv2_mod = cv2
            logger.info("OpenCV (cv2) Aktif. Absolute Vision motoru hazır.")
        except ImportError:
            _cv2_mod = False
            logger.warning("OpenCV bulunamadı. Standard fallback kullanılacak.")
    return _cv2_mod if _cv2_mod is not False else None

def _pil():
    global _pil_image
    if _pil_image is None:
        from PIL import Image
        _pil_image = Image
    return _pil_image


# ============================================================
#  SCREENSHOT → base64
# ============================================================
def _take_screenshot_b64(region=None):
    """Ekran görüntüsü alıp (base64, width, height) döndürür."""
    if region:
        img = _pag().screenshot(region=(region["x"], region["y"], region["w"], region["h"]))
    else:
        img = _pag().screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), img.width, img.height


@router.post("/screenshot")
async def api_screenshot(req: ScreenshotReq):
    try:
        r = req.region if req.region else None
        b64, w, h = await asyncio.to_thread(_take_screenshot_b64, r)
        return {"screenshot": b64, "width": w, "height": h}
    except Exception as e:
        logger.error(f"Screenshot hatası: {e}")
        raise HTTPException(500, detail=str(e))


# ============================================================
#  SAVE ASSET (Snip Tool'dan gelen crop'u diske kaydet)
# ============================================================
@router.post("/save-asset")
async def api_save_asset(req: SaveAssetReq):
    try:
        ws_dir = ASSETS_DIR / (req.workspace_id or "default")
        ws_dir.mkdir(parents=True, exist_ok=True)
        fp = ws_dir / req.name
        fp.write_bytes(base64.b64decode(req.image_b64))
        logger.info(f"Asset kaydedildi: {fp}")
        return {"saved": True, "path": str(fp), "name": req.name}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ============================================================
#  ABSOLUTE VISION ENGINE
#  Birebir desktop_driver.py → _find_image_opencv'den port
#  Multi-Scale + Blur + Color Verification + Edge Matching
# ============================================================
def _find_image_on_screen(target_path: str, threshold: float = 0.80):
    """
    Absolute Vision v26 — ekranda görsel arar.
    Returns: (x, y) merkez koordinat veya None.
    """
    cv2 = _cv2()
    if cv2 is None:
        return _find_image_fallback(target_path, threshold)

    try:
        import numpy as np

        # Ekranı al ve normalize et
        screen_img = np.array(_pag().screenshot())
        screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)
        screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
        screen_gray = cv2.GaussianBlur(screen_gray, (3, 3), 0)

        template_bgr = cv2.imread(target_path)
        if template_bgr is None:
            return None
        template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.GaussianBlur(template_gray, (3, 3), 0)
        h, w = template_gray.shape[:2]

        # Ultra-Fine Scaling: 0.7 — 1.3, 13 kademe
        scales = np.linspace(0.7, 1.3, 13)
        best_match = None
        max_val = -1

        # PHASE 1: Standard Multi-Scale Search
        for scale in scales:
            rw, rh = int(w * scale), int(h * scale)
            if rw < 20 or rh < 20:
                continue
            resized = cv2.resize(template_gray, (rw, rh))
            res = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if val > max_val:
                max_val = val
                best_match = (loc, scale, rw, rh)

        # PHASE 2: Edge-Matching Fallback (v34)
        if max_val < threshold:
            screen_edges = cv2.Canny(screen_gray, 50, 150)
            template_edges = cv2.Canny(template_gray, 50, 150)
            for scale in scales:
                rw, rh = int(w * scale), int(h * scale)
                if rw < 20 or rh < 20:
                    continue
                resized_edges = cv2.resize(template_edges, (rw, rh))
                res = cv2.matchTemplate(screen_edges, resized_edges, cv2.TM_CCOEFF_NORMED)
                _, val, _, loc = cv2.minMaxLoc(res)
                if val > max_val:
                    max_val = val
                    best_match = (loc, scale, rw, rh)

        logger.info(f"Vision Teşhis: [Ölçek: {len(scales)}] [En İyi: %{int(max_val*100)}] [Eşik: %{int(threshold*100)}]")

        if max_val >= threshold and best_match:
            loc, scale, rw, rh = best_match

            # Color Verification (Renk Doğrulaması)
            detected = screen_bgr[loc[1]:loc[1]+rh, loc[0]:loc[0]+rw]
            target_resized = cv2.resize(template_bgr, (rw, rh))
            if detected.shape == target_resized.shape:
                color_res = cv2.matchTemplate(detected, target_resized, cv2.TM_CCORR_NORMED)
                _, color_val, _, _ = cv2.minMaxLoc(color_res)
            else:
                color_val = 0.70

            logger.info(f"Vision Teşhis: Renk Onayı: %{int(color_val*100)} (Eşik: %60)")

            if color_val > 0.60:
                cx = loc[0] + rw // 2
                cy = loc[1] + rh // 2
                scaling = get_dpi_scaling()
                return (cx / scaling, cy / scaling)
            else:
                logger.info(f"DİKKAT: Şekil bulundu ama RENK TUTMADI.")

        return None
    except Exception as e:
        logger.debug(f"OpenCV Vision Hatası: {e}")
        return None


def _find_image_fallback(target_path: str, threshold: float = 0.80):
    """Standard pyautogui fallback (OpenCV yoksa)."""
    try:
        needle = _pil().open(target_path)
        location = _pag().locateOnScreen(needle, grayscale=True, confidence=min(0.8, threshold))
        if location:
            center = _pag().center(location)
            return (center.x, center.y)
    except Exception:
        pass
    return None


def _find_b64_on_screen(b64_data: str, threshold=0.80, timeout=10):
    """base64 görseli ekranda ara. Temp dosya oluşturup siler."""
    tmp = ASSETS_DIR / f"_tmp_{uuid.uuid4().hex[:8]}.png"
    try:
        tmp.write_bytes(base64.b64decode(b64_data))
        start = time.time()
        while time.time() - start < timeout:
            elapsed = time.time() - start
            conf = max(0.65, 0.85 - (elapsed / timeout) * 0.20)
            coords = _find_image_on_screen(str(tmp), threshold=conf)
            if coords:
                return coords
            time.sleep(0.3)
        return None
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def _do_robust_click(x, y, button="left"):
    """
    desktop_driver.py'deki Robust Klik Sitesi (v33 & v36):
    1. Fareyi taşı (görsel onay)
    2. Pre-click stabilization (nişan alma beklemesi)
    3. Bas-Bekle-Bırak
    """
    _pag().moveTo(x, y, duration=0.2)
    time.sleep(0.3)  # Pre-click stabilization
    _pag().mouseDown(button=button)
    time.sleep(0.05)
    _pag().mouseUp(button=button)


# ============================================================
#  SMART RECORDER (recorder.py'den birebir port)
#  Wide-Vision 300x300 Context Capture
# ============================================================
class _RecorderState:
    def __init__(self):
        self.active = False
        self.workspace_id = None
        self.ws_queues: list = []
        self.mouse_listener = None
        self.keyboard_listener = None
        self.type_buffer = ""
        self.last_click_time = 0.0
        self.last_space_time = 0.0

_rec = _RecorderState()


def _rec_broadcast(msg: dict):
    """Tüm bağlı WebSocket client'lara mesaj gönder."""
    data = json.dumps(msg, ensure_ascii=False)
    dead = []
    for q in _rec.ws_queues:
        try:
            q.put_nowait(data)
        except Exception:
            dead.append(q)
    for d in dead:
        if d in _rec.ws_queues:
            _rec.ws_queues.remove(d)


def _rec_flush_type():
    """Tip buffer'ını flush et (recorder.py → _flush_type_buffer)."""
    if _rec.type_buffer:
        text = _rec.type_buffer
        _rec.type_buffer = ""
        _rec_broadcast({
            "type": "step",
            "action_type": "TYPE",
            "text": text,
            "description": f"Type '{text}'"
        })


def _rec_on_click(x, y, button, pressed):
    """
    recorder.py → on_click birebir port.
    Wide-Vision 300x300 capture around click point.
    """
    if not _rec.active or not pressed:
        return

    _rec_flush_type()

    # Debounce (0.5s)
    now = time.time()
    if now - _rec.last_click_time < 0.5:
        return
    _rec.last_click_time = now

    btn_str = "left" if str(button) == "Button.left" else "right"

    try:
        # Wide-Vision Capture: 300x300 around click
        region_size = 300
        left = max(0, int(x - region_size / 2))
        top = max(0, int(y - region_size / 2))

        ss = _pag().screenshot(region=(left, top, region_size, region_size))

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"wide_click_{ts}.png"

        ws_dir = ASSETS_DIR / (_rec.workspace_id or "default")
        ws_dir.mkdir(parents=True, exist_ok=True)
        filepath = ws_dir / filename
        ss.save(str(filepath))

        # base64 for frontend thumbnail
        buf = io.BytesIO()
        ss.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        btn_label = "Sağ" if btn_str == "right" else "Sol"
        _rec_broadcast({
            "type": "step",
            "action_type": "CLICK",
            "filename": filename,
            "filepath": str(filepath),
            "screenshot": b64,
            "button": btn_str,
            "x": int(x), "y": int(y),
            "description": f"CLICK ({btn_label}) (Img: {filename})"
        })
        logger.info(f"Wide-Vision Capture: {filename} ({region_size}x{region_size})")
    except Exception as e:
        logger.error(f"Recorder capture hatası: {e}")


def _rec_on_key(key):
    """recorder.py → on_press birebir port."""
    try:
        from pynput import keyboard as kb
    except ImportError:
        return

    if key == kb.Key.esc:
        _rec_stop()
        return False  # pynput listener'ı durdur

    if not _rec.active:
        return

    try:
        if hasattr(key, "char") and key.char:
            _rec.type_buffer += key.char
        elif key == kb.Key.space:
            now = time.time()
            if now - _rec.last_space_time < 0.4:
                if _rec.type_buffer.endswith(" "):
                    _rec.type_buffer = _rec.type_buffer[:-1]
                _rec_flush_type()
                _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                              "key": "double_space", "description": "Press Key: double_space"})
                _rec.last_space_time = 0.0
            else:
                _rec.type_buffer += " "
                _rec.last_space_time = now
        elif key == kb.Key.enter:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "enter", "description": "Press Key: enter"})
        elif key == kb.Key.tab:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "tab", "description": "Press Key: tab"})
        elif key == kb.Key.backspace:
            if _rec.type_buffer:
                _rec.type_buffer = _rec.type_buffer[:-1]
            else:
                _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                              "key": "backspace", "description": "Press Key: backspace"})
        elif key in (kb.Key.up, kb.Key.down, kb.Key.left, kb.Key.right):
            _rec_flush_type()
            key_name = {kb.Key.up: "up", kb.Key.down: "down",
                        kb.Key.left: "left", kb.Key.right: "right"}[key]
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": key_name, "description": f"Press Key: {key_name}"})
        elif key == kb.Key.delete:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "delete", "description": "Press Key: delete"})
        elif key == kb.Key.home:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "home", "description": "Press Key: home"})
        elif key == kb.Key.end:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "end", "description": "Press Key: end"})
        elif key == kb.Key.page_up:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "pageup", "description": "Press Key: pageup"})
        elif key == kb.Key.page_down:
            _rec_flush_type()
            _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                          "key": "pagedown", "description": "Press Key: pagedown"})
        else:
            _rec_flush_type()
    except Exception:
        pass


def _rec_start(workspace_id=None):
    """recorder.py → start() birebir port."""
    from pynput import mouse, keyboard

    _rec.active = True
    _rec.workspace_id = workspace_id
    _rec.type_buffer = ""
    _rec.last_click_time = 0.0

    _rec.mouse_listener = mouse.Listener(on_click=_rec_on_click)
    _rec.keyboard_listener = keyboard.Listener(on_press=_rec_on_key)
    _rec.mouse_listener.start()
    _rec.keyboard_listener.start()
    logger.info("Recording started (v25 Wide-Vision Active)...")


def _rec_stop():
    """recorder.py → stop() birebir port."""
    _rec.active = False
    _rec_flush_type()
    try:
        if _rec.mouse_listener:
            _rec.mouse_listener.stop()
    except Exception:
        pass
    try:
        if _rec.keyboard_listener:
            _rec.keyboard_listener.stop()
    except Exception:
        pass
    _rec_broadcast({"type": "stopped"})
    logger.info("Smart Recorder stopped")


@router.post("/record/start")
async def api_record_start(req: RecordReq):
    if _rec.active:
        return {"status": "already_recording"}
    try:
        await asyncio.to_thread(_rec_start, req.workspace_id)
        return {"status": "recording"}
    except ImportError:
        raise HTTPException(500, detail="pynput paketi yüklü değil: pip install pynput")
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/record/stop")
async def api_record_stop():
    await asyncio.to_thread(_rec_stop)
    return {"status": "stopped"}


@router.websocket("/record/ws")
async def ws_record(ws: WebSocket):
    await ws.accept()
    q = queue_module.Queue()
    _rec.ws_queues.append(q)
    try:
        while True:
            try:
                msg = q.get(timeout=0.15)
                await ws.send_text(msg)
                if '"stopped"' in msg:
                    break
            except queue_module.Empty:
                if not _rec.active and q.empty():
                    await asyncio.sleep(0.3)
                    if q.empty():
                        break
    except WebSocketDisconnect:
        pass
    finally:
        if q in _rec.ws_queues:
            _rec.ws_queues.remove(q)


# ============================================================
#  STEP EXECUTION (runner.py + desktop_driver.py'den port)
# ============================================================
def _execute_step(step: dict, action_delay: float = 0.5) -> dict:
    """Tek bir otomasyon adımını çalıştır."""
    stype = step.get("type", "")
    params = step.get("params", {})
    result = {"success": False, "error": None, "screenshot": None}

    try:
        # ─── CLICK ───
        if stype == "CLICK":
            button = params.get("button", "left")
            b64 = params.get("screenshot_b64") or params.get("screenshot")
            target_name = params.get("target_name") or params.get("filename", "")
            filepath = params.get("filepath", "")

            found = False

            # 1. Dosya yoluyla ara
            if filepath and os.path.isfile(filepath):
                coords = _find_image_on_screen(filepath, threshold=0.75)
                if coords:
                    _do_robust_click(coords[0], coords[1], button)
                    found = True

            # 2. Asset adıyla ara
            if not found and target_name:
                for f in ASSETS_DIR.rglob(target_name):
                    coords = _find_image_on_screen(str(f), threshold=0.75)
                    if coords:
                        _do_robust_click(coords[0], coords[1], button)
                        found = True
                        break

            # 3. base64 ile ara
            if not found and b64:
                coords = _find_b64_on_screen(b64, timeout=8)
                if coords:
                    _do_robust_click(coords[0], coords[1], button)
                    found = True

            result["success"] = found
            if not found:
                result["error"] = "Ekranda bulunamadı"

        # ─── CLICK_TEXT (OCR) ───
        elif stype == "CLICK_TEXT":
            text = params.get("text", "")
            try:
                import pytesseract
                img = _pag().screenshot()
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                for i, word in enumerate(data["text"]):
                    if text.lower() in str(word).lower() and int(data["conf"][i]) > 50:
                        x = data["left"][i] + data["width"][i] // 2
                        y = data["top"][i] + data["height"][i] // 2
                        sc = get_dpi_scaling()
                        _pag().click(x / sc, y / sc, button=params.get("button", "left"))
                        result["success"] = True
                        break
                if not result["success"]:
                    result["error"] = f"Metin bulunamadı: '{text}'"
            except ImportError:
                result["error"] = "pytesseract yüklü değil: pip install pytesseract"

        # ─── TYPE ───
        elif stype == "TYPE":
            import random
            text = params.get("text", "")
            for ch in text:
                _pag().write(ch)
                time.sleep(0.05 + random.uniform(0, 0.03))
            result["success"] = True

        # ─── PRESS_KEY ───
        elif stype == "PRESS_KEY":
            key = params.get("key", "enter")
            if key == "double_space":
                _pag().press("space")
                time.sleep(0.05)
                _pag().press("space")
            elif "+" in key:
                _pag().hotkey(*key.split("+"))
            else:
                _pag().press(key)
            result["success"] = True

        # ─── SCROLL ───
        elif stype == "SCROLL":
            _pag().scroll(int(params.get("amount", 0)))
            result["success"] = True

        # ─── WAIT ───
        elif stype == "WAIT":
            time.sleep(float(params.get("seconds", 1)))
            result["success"] = True

        # ─── LAUNCH_APP ───
        elif stype == "LAUNCH_APP":
            path = params.get("path", "")
            if sys.platform == "win32":
                os.startfile(path)
            else:
                import subprocess
                subprocess.Popen([path])
            time.sleep(2)
            result["success"] = True

        # ─── ASSERT_EXISTS ───
        elif stype == "ASSERT_EXISTS":
            b64 = params.get("screenshot_b64") or params.get("screenshot")
            filepath = params.get("filepath", "")
            target_name = params.get("target_name", "")
            found = False

            if filepath and os.path.isfile(filepath):
                found = _find_image_on_screen(filepath, threshold=0.70) is not None
            if not found and target_name:
                for f in ASSETS_DIR.rglob(target_name):
                    if _find_image_on_screen(str(f), threshold=0.70):
                        found = True
                        break
            if not found and b64:
                found = _find_b64_on_screen(b64, timeout=5) is not None

            result["success"] = found
            if not found:
                result["error"] = "Ekranda bulunamadı (Assert)"

        # ─── VALIDATE_WINDOW ───
        elif stype == "VALIDATE_WINDOW":
            title = params.get("title", "")
            timeout = float(params.get("timeout", 5))
            try:
                from pywinauto import Desktop as WinDesktop
                start = time.time()
                while time.time() - start < timeout:
                    for win in WinDesktop(backend="uia").windows():
                        if title.lower() in win.window_text().lower():
                            result["success"] = True
                            break
                    if result["success"]:
                        break
                    time.sleep(0.5)
                if not result["success"]:
                    result["error"] = f"Pencere bulunamadı: '{title}'"
            except ImportError:
                result["error"] = "pywinauto yüklü değil"

        # ─── READ_TEXT (OCR) ───
        elif stype == "READ_TEXT":
            region = params.get("region")
            try:
                import pytesseract
                if region:
                    img = _pag().screenshot(region=(region["x"], region["y"], region["w"], region["h"]))
                else:
                    img = _pag().screenshot()
                result["text"] = pytesseract.image_to_string(img, lang="tur+eng").strip()
                result["success"] = True
            except ImportError:
                result["error"] = "pytesseract yüklü değil"

        else:
            result["error"] = f"Bilinmeyen aksiyon: {stype}"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Adım hatası [{stype}]: {e}")

    # Post-step delay (WAIT hariç)
    if action_delay > 0 and stype != "WAIT":
        time.sleep(action_delay)

    return result


# ============================================================
#  RUN SCENARIO (WebSocket ile canlı güncelleme)
# ============================================================
class _RunState:
    def __init__(self):
        self.active = False
        self.stop_flag = False
        self.ws_clients: Dict[str, list] = {}

_run = _RunState()


def _run_broadcast(test_id: str, msg: dict):
    data = json.dumps(msg, ensure_ascii=False)
    for q in _run.ws_clients.get(test_id, []):
        try:
            q.put_nowait(data)
        except Exception:
            pass


def _run_thread(test_id: str, steps: list, delay: float):
    """Senaryoyu arka plan thread'inde çalıştır."""
    _run.active = True
    _run.stop_flag = False
    results = []

    for i, step in enumerate(steps):
        if _run.stop_flag:
            _run_broadcast(test_id, {"type": "complete", "stopped": True})
            break

        _run_broadcast(test_id, {"type": "step_start", "index": i})
        res = _execute_step(step, delay)

        # Her adım sonrası ekran görüntüsü
        try:
            b64, _, _ = _take_screenshot_b64()
            res["screenshot"] = b64
        except Exception:
            pass

        _run_broadcast(test_id, {
            "type": "step_result", "index": i,
            "success": res["success"], "error": res.get("error"),
            "screenshot": res.get("screenshot"),
        })
        results.append(res)

    _run.active = False
    failed = sum(1 for r in results if not r["success"])
    _run_broadcast(test_id, {"type": "complete", "total": len(results), "failed": failed})


@router.post("/run")
async def api_run(req: RunReq):
    if _run.active:
        raise HTTPException(409, detail="Zaten çalışan bir senaryo var")
    test_id = uuid.uuid4().hex[:12]
    _run.ws_clients[test_id] = []
    steps = [{"type": s.type, "params": s.params, "description": s.description} for s in req.steps]
    t = threading.Thread(target=_run_thread, args=(test_id, steps, req.action_delay), daemon=True)
    t.start()
    return {"test_id": test_id, "status": "running"}


@router.post("/stop")
async def api_stop():
    _run.stop_flag = True
    return {"status": "stopping"}


@router.websocket("/ws/{test_id}")
async def ws_run(ws: WebSocket, test_id: str):
    await ws.accept()
    q = queue_module.Queue()
    if test_id not in _run.ws_clients:
        _run.ws_clients[test_id] = []
    _run.ws_clients[test_id].append(q)
    try:
        while True:
            try:
                msg = q.get(timeout=0.2)
                await ws.send_text(msg)
                if '"complete"' in msg:
                    break
            except queue_module.Empty:
                if not _run.active and q.empty():
                    await asyncio.sleep(0.5)
                    if q.empty():
                        break
    except WebSocketDisconnect:
        pass
    finally:
        clients = _run.ws_clients.get(test_id, [])
        if q in clients:
            clients.remove(q)


# ============================================================
#  SENARYO KAYDET / LİSTELE
# ============================================================
@router.post("/save-scenario")
async def api_save_scenario(req: SaveScenarioReq):
    ws_dir = SCENARIOS_DIR / (req.workspace_id or "default")
    ws_dir.mkdir(parents=True, exist_ok=True)
    fp = ws_dir / f"{req.name}.json"
    fp.write_text(json.dumps(req.data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "path": str(fp)}


@router.post("/list-scenarios")
async def api_list_scenarios(req: ListScenariosReq):
    ws_dir = SCENARIOS_DIR / (req.workspace_id or "default")
    out = []
    if ws_dir.exists():
        for f in sorted(ws_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append({"name": data.get("name", f.stem), "file": f.name, "data": data})
            except Exception:
                pass
    return {"scenarios": out}


@router.post("/open-folder")
async def api_open_folder(req: FolderReq):
    folder = ASSETS_DIR / (req.workspace_id or "default")
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(folder))
        return {"opened": True}
    raise HTTPException(400, detail="Sadece Windows'ta desteklenir")


# ============================================================
#  STATUS
# ============================================================
@router.get("/status")
async def api_status():
    return {
        "active": True,
        "recording": _rec.active,
        "running": _run.active,
        "opencv": _cv2() is not None,
        "dpi_scaling": get_dpi_scaling(),
    }