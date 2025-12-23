"""
Emulator Service - ULTRA LOW LATENCY VERSION v4
===============================================
DÜZELTMELER:
1. Ekran yakalama 50ms -> 30ms (33 FPS hedef)
2. Input gönderimi fire & forget (bekleme yok)
3. Küçük resim boyutu (240px) + düşük kalite (30%)
4. ADB komutları için thread pool
5. Async input handling
6. Klavye açma/kapama fonksiyonları
"""

import subprocess
import base64
import os
import threading
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

PIL_AVAILABLE = False
try:
    from PIL import Image  # type: ignore
    PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore


class TestRunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class StepLog:
    step_number: int
    action: str
    target: str
    status: str
    message: str = ""
    timestamp: float = 0


@dataclass
class EmulatorSession:
    device_id: str
    user_id: int
    is_active: bool = True
    test_state: TestRunState = TestRunState.IDLE
    current_step: int = 0
    total_steps: int = 0
    stop_requested: bool = False
    logs: List[StepLog] = field(default_factory=list)
    last_frame: Optional[str] = None
    frame_lock: threading.Lock = field(default_factory=threading.Lock)
    log_lock: threading.Lock = field(default_factory=threading.Lock)


class EmulatorService:
    def __init__(self):
        self.sessions: Dict[str, EmulatorSession] = {}
        self.adb_path = self._find_adb()
        self._frame_threads: Dict[str, threading.Thread] = {}
        self._stop_frames: Dict[str, bool] = {}
        
        # Input komutları için thread pool (fire & forget)
        self._input_executor = ThreadPoolExecutor(max_workers=4)
        
        # Screen size cache
        self._screen_sizes: Dict[str, tuple] = {}

    def _find_adb(self) -> str:
        """ADB yolunu bul"""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local = os.path.join(base, "platform-tools", "adb.exe")
        if os.path.exists(local):
            return local
        
        import shutil
        system_adb = shutil.which("adb")
        if system_adb:
            return system_adb
        
        paths = [
            os.path.expanduser("~") + "\\AppData\\Local\\Android\\Sdk\\platform-tools\\adb.exe",
            "C:\\platform-tools\\adb.exe",
            "C:\\Android\\platform-tools\\adb.exe"
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        
        return 'adb'

    def _get_startupinfo(self):
        """Windows için startupinfo döndür"""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return startupinfo

    def is_adb_available(self) -> bool:
        """ADB mevcut mu kontrol et"""
        try:
            result = subprocess.run(
                [self.adb_path, 'version'],
                capture_output=True,
                timeout=2,
                startupinfo=self._get_startupinfo()
            )
            return result.returncode == 0
        except:
            return False

    def get_connected_devices(self) -> List[dict]:
        """Bağlı cihazları listele"""
        try:
            r = subprocess.run(
                [self.adb_path, 'devices'],
                capture_output=True,
                text=True,
                timeout=2,
                startupinfo=self._get_startupinfo()
            )
            
            devices = []
            for line in r.stdout.strip().split('\n')[1:]:
                if '\t' in line:
                    did, status = line.split('\t')
                    if status == 'device':
                        devices.append({
                            'device_id': did,
                            'status': 'online',
                            'type': 'emulator' if did.startswith('emulator') else 'physical'
                        })
            return devices
        except:
            return []

    def _run_adb_command(self, device_id: str, *args, timeout: float = 1.5) -> Optional[bytes]:
        """ADB komutu çalıştır - optimize edilmiş"""
        try:
            cmd = [self.adb_path, '-s', device_id] + list(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                startupinfo=self._get_startupinfo()
            )
            
            if result.returncode == 0:
                return result.stdout
            return None
        except:
            return None

    def _run_adb_async(self, device_id: str, *args):
        """ADB komutu asenkron çalıştır (fire & forget) - INPUT İÇİN"""
        try:
            cmd = [self.adb_path, '-s', device_id] + list(args)
            subprocess.Popen(
                cmd, 
                startupinfo=self._get_startupinfo(), 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[ADB] Async error: {e}")

    def _capture_frame_sync(self, device_id: str) -> Optional[str]:
        """Ekran görüntüsü yakala - optimize edilmiş"""
        try:
            raw = self._run_adb_command(device_id, 'exec-out', 'screencap', '-p', timeout=0.8)
            
            if not raw or len(raw) < 1000:
                return None
            
            if PIL_AVAILABLE:
                try:
                    image = Image.open(BytesIO(raw))
                    
                    # ULTRA KÜÇÜK: 240px genişlik (hız için)
                    ratio = 240 / image.width
                    new_height = int(image.height * ratio)
                    image = image.resize((240, new_height), Image.Resampling.NEAREST)
                    
                    buffered = BytesIO()
                    image.save(buffered, format="JPEG", quality=30, optimize=False)
                    return base64.b64encode(buffered.getvalue()).decode('utf-8')
                except Exception as e:
                    pass
            
            return base64.b64encode(raw).decode('utf-8')
        except:
            return None

    def _frame_capture_loop(self, device_id: str):
        """Frame yakalama döngüsü - 33 FPS hedef"""
        while not self._stop_frames.get(device_id, False):
            session = self.sessions.get(device_id)
            if not session or not session.is_active:
                break
            
            start = time.time()
            
            frame = self._capture_frame_sync(device_id)
            if frame:
                with session.frame_lock:
                    session.last_frame = frame
            
            elapsed = time.time() - start
            sleep_time = max(0.01, 0.03 - elapsed)
            time.sleep(sleep_time)

    def start_frame_capture(self, device_id: str):
        """Frame yakalama başlat"""
        self._stop_frames[device_id] = False
        
        if device_id in self._frame_threads and self._frame_threads[device_id].is_alive():
            return
        
        t = threading.Thread(target=self._frame_capture_loop, args=(device_id,), daemon=True)
        t.start()
        self._frame_threads[device_id] = t

    def stop_frame_capture(self, device_id: str):
        """Frame yakalama durdur"""
        self._stop_frames[device_id] = True

    def get_cached_frame(self, device_id: str) -> Optional[str]:
        """Önbellekteki frame'i getir"""
        session = self.sessions.get(device_id)
        if session:
            with session.frame_lock:
                return session.last_frame
        return None

    def get_screen_size(self, device_id: str) -> tuple:
        """Ekran boyutunu getir (cache'li)"""
        if device_id in self._screen_sizes:
            return self._screen_sizes[device_id]
        
        try:
            output = self._run_adb_command(device_id, 'shell', 'wm', 'size')
            if output:
                text = output.decode('utf-8')
                import re
                match = re.search(r'(\d+)x(\d+)', text)
                if match:
                    size = (int(match.group(1)), int(match.group(2)))
                    self._screen_sizes[device_id] = size
                    return size
        except:
            pass
        
        return (1080, 1920)

    # ============ INPUT KOMUTLARI (HIZLI - FIRE & FORGET) ============

    def send_tap(self, device_id: str, x: int, y: int) -> bool:
        """Ekrana dokun"""
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'tap', str(x), str(y)
        )
        return True

    def send_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 200) -> bool:
        """Kaydırma hareketi"""
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'swipe',
            str(x1), str(y1), str(x2), str(y2), str(duration)
        )
        return True

    def send_text(self, device_id: str, text: str) -> bool:
        """Metin gönder"""
        escaped = text.replace(' ', '%s').replace('&', '\\&').replace('<', '\\<').replace('>', '\\>').replace("'", "\\'").replace('"', '\\"').replace('(', '\\(').replace(')', '\\)')
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'text', escaped
        )
        return True

    def send_key(self, device_id: str, keycode: int) -> bool:
        """Tuş gönder"""
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'keyevent', str(keycode)
        )
        return True

    def press_back(self, device_id: str) -> bool:
        """Geri tuşu"""
        return self.send_key(device_id, 4)

    def press_home(self, device_id: str) -> bool:
        """Ana ekran tuşu"""
        return self.send_key(device_id, 3)

    def press_recent(self, device_id: str) -> bool:
        """Son uygulamalar tuşu"""
        return self.send_key(device_id, 187)

    def show_keyboard(self, device_id: str) -> bool:
        """Klavyeyi göster"""
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'keyevent', '62'
        )
        return True

    def hide_keyboard(self, device_id: str) -> bool:
        """Klavyeyi gizle"""
        self._input_executor.submit(
            self._run_adb_async, device_id, 'shell', 'input', 'keyevent', '111'
        )
        return True

    def press_enter(self, device_id: str) -> bool:
        """Enter tuşu"""
        return self.send_key(device_id, 66)

    def press_delete(self, device_id: str) -> bool:
        """Delete/Backspace tuşu"""
        return self.send_key(device_id, 67)

    def press_tab(self, device_id: str) -> bool:
        """Tab tuşu"""
        return self.send_key(device_id, 61)

    # ============ SESSION YÖNETİMİ ============

    def create_session(self, device_id: str, user_id: int) -> EmulatorSession:
        """Yeni oturum oluştur"""
        if device_id in self.sessions:
            self.stop_frame_capture(device_id)
        
        session = EmulatorSession(device_id=device_id, user_id=user_id)
        self.sessions[device_id] = session
        self.start_frame_capture(device_id)
        return session

    def get_session(self, device_id: str) -> Optional[EmulatorSession]:
        """Oturum getir"""
        return self.sessions.get(device_id)

    def ensure_session(self, device_id: str, user_id: int = 1) -> EmulatorSession:
        """Oturum var mı kontrol et, yoksa oluştur"""
        return self.sessions.get(device_id) or self.create_session(device_id, user_id)

    def close_session(self, device_id: str):
        """Oturumu kapat"""
        self.stop_frame_capture(device_id)
        if device_id in self.sessions:
            del self.sessions[device_id]
        if device_id in self._screen_sizes:
            del self._screen_sizes[device_id]

    # ============ LOG YÖNETİMİ ============

    def add_log(self, device_id: str, step: int, action: str, target: str, status: str, message: str = ""):
        """Log ekle"""
        session = self.sessions.get(device_id)
        if session:
            with session.log_lock:
                session.logs.append(StepLog(
                    step_number=step,
                    action=action,
                    target=target,
                    status=status,
                    message=message,
                    timestamp=time.time()
                ))

    def clear_logs(self, device_id: str):
        """Logları temizle"""
        session = self.sessions.get(device_id)
        if session:
            with session.log_lock:
                session.logs = []

    def get_logs(self, device_id: str) -> List[dict]:
        """Logları getir"""
        session = self.sessions.get(device_id)
        if not session:
            return []
        
        with session.log_lock:
            return [{
                "step": log.step_number,
                "action": log.action,
                "target": log.target,
                "status": log.status,
                "message": log.message
            } for log in session.logs]

    # ============ TEST STATE YÖNETİMİ ============

    def set_test_state(self, device_id: str, state: TestRunState, current: int = 0, total: int = 0):
        """Test durumunu ayarla"""
        session = self.sessions.get(device_id)
        if session:
            session.test_state = state
            session.current_step = current
            session.total_steps = total

    def get_test_state(self, device_id: str) -> dict:
        """Test durumunu getir"""
        session = self.sessions.get(device_id)
        if not session:
            return {"state": "no_session"}
        
        return {
            "state": session.test_state.value,
            "current_step": session.current_step,
            "total_steps": session.total_steps,
            "logs": self.get_logs(device_id)
        }

    def stop_test(self, device_id: str):
        """Testi durdur"""
        session = self.sessions.get(device_id)
        if session:
            session.stop_requested = True
            session.test_state = TestRunState.STOPPED

    def reset_stop_flag(self, device_id: str):
        """Stop flag'ini sıfırla"""
        session = self.sessions.get(device_id)
        if session:
            session.stop_requested = False

    def is_test_stopped(self, device_id: str) -> bool:
        """Test durduruldu mu kontrol et"""
        session = self.sessions.get(device_id)
        if session:
            return session.stop_requested
        return False


emulator_service = EmulatorService()