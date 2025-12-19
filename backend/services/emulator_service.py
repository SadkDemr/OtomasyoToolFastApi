"""
Emulator Service - ADB ile emulator kontrolu
FIXED: Missing 'get_session' method added back.
ULTRA LOW LATENCY MODE (270px width + Low Quality)
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

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[UYARI] PIL yuklu degil.")

class TestRunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUCCESS = "success"
    FAILED = "failed"

@dataclass
class StepLog:
    step_number: int; action: str; target: str; status: str; message: str = ""; timestamp: float = 0

@dataclass
class EmulatorSession:
    device_id: str; user_id: int; is_active: bool = True
    test_state: TestRunState = TestRunState.IDLE
    current_step: int = 0; total_steps: int = 0; stop_requested: bool = False
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
        self.adb_global_lock = threading.Lock()
    
    def _find_adb(self) -> str:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local = os.path.join(base, "platform-tools", "adb.exe")
        return local if os.path.exists(local) else 'adb'
    
    def is_adb_available(self) -> bool:
        try: return subprocess.run([self.adb_path, 'version'], capture_output=True).returncode == 0
        except: return False
    
    def get_connected_devices(self) -> List[dict]:
        try:
            r = subprocess.run([self.adb_path, 'devices'], capture_output=True, text=True, timeout=2)
            devices = []
            for line in r.stdout.strip().split('\n')[1:]:
                if '\t' in line:
                    did, status = line.split('\t')
                    if status == 'device':
                        devices.append({'device_id': did, 'status': 'online', 'type': 'emulator' if did.startswith('emulator') else 'physical'})
            return devices
        except: return []
    
    def _capture_frame_sync(self, device_id: str) -> Optional[str]:
        # Lock check (Non-blocking)
        if not self.adb_global_lock.acquire(blocking=False): return None
        
        try:
            r = subprocess.run([self.adb_path, '-s', device_id, 'exec-out', 'screencap', '-p'], capture_output=True, timeout=2)
            if r.returncode == 0 and r.stdout:
                if PIL_AVAILABLE:
                    try:
                        image = Image.open(BytesIO(r.stdout))
                        # ULTRA LOW RES: 270px width (Hızı 10 kat artırır)
                        image.thumbnail((270, 540)) 
                        buffered = BytesIO()
                        # Quality 40 (Artefakt olabilir ama çok hızlıdır)
                        image.save(buffered, format="JPEG", quality=40)
                        return base64.b64encode(buffered.getvalue()).decode('utf-8')
                    except: pass
                return base64.b64encode(r.stdout).decode('utf-8')
        except: pass
        finally: self.adb_global_lock.release()
        return None
    
    def _frame_capture_loop(self, device_id: str):
        while not self._stop_frames.get(device_id, False):
            session = self.sessions.get(device_id)
            if not session or not session.is_active: break
            
            frame = self._capture_frame_sync(device_id)
            if frame:
                with session.frame_lock: session.last_frame = frame
            
            time.sleep(0.05) # 20 FPS hedefi
    
    def start_frame_capture(self, device_id: str):
        self._stop_frames[device_id] = False
        if device_id not in self._frame_threads or not self._frame_threads[device_id].is_alive():
            t = threading.Thread(target=self._frame_capture_loop, args=(device_id,), daemon=True)
            t.start(); self._frame_threads[device_id] = t
    
    def stop_frame_capture(self, device_id: str): self._stop_frames[device_id] = True
    
    def get_cached_frame(self, device_id: str) -> Optional[str]:
        s = self.sessions.get(device_id)
        if s: 
            with s.frame_lock: return s.last_frame
        return None
    
    def get_screen_size(self, device_id: str) -> tuple:
        # Sadece bir kere al, sürekli sorma
        return (1080, 1920) 

    # Input Eventleri (Hızlı - Fire & Forget)
    def send_tap(self, device_id: str, x: int, y: int) -> bool:
        with self.adb_global_lock:
            subprocess.Popen([self.adb_path, '-s', device_id, 'shell', 'input', 'tap', str(x), str(y)])
        return True
    
    def send_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int=200) -> bool:
        with self.adb_global_lock:
            subprocess.Popen([self.adb_path, '-s', device_id, 'shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration)])
        return True
        
    def send_text(self, device_id: str, text: str) -> bool:
        with self.adb_global_lock:
            t = text.replace(' ', '%s').replace('&', '\\&')
            subprocess.Popen([self.adb_path, '-s', device_id, 'shell', 'input', 'text', t])
        return True

    def send_key(self, device_id: str, k: int) -> bool:
        with self.adb_global_lock:
            subprocess.Popen([self.adb_path, '-s', device_id, 'shell', 'input', 'keyevent', str(k)])
        return True

    def press_back(self, d): return self.send_key(d, 4)
    def press_home(self, d): return self.send_key(d, 3)
    def press_recent(self, d): return self.send_key(d, 187)
    
    # Session & Logs
    def create_session(self, device_id: str, user_id: int) -> EmulatorSession:
        if device_id in self.sessions: self.stop_frame_capture(device_id)
        s = EmulatorSession(device_id, user_id)
        self.sessions[device_id] = s
        self.start_frame_capture(device_id)
        return s

    # --- EKLENEN KISIM (Unutulan Metot) ---
    def get_session(self, device_id: str) -> Optional[EmulatorSession]:
        return self.sessions.get(device_id)
    # --------------------------------------

    def ensure_session(self, did, uid=1):
        return self.sessions.get(did) or self.create_session(did, uid)

    def close_session(self, did):
        self.stop_frame_capture(did)
        if did in self.sessions: del self.sessions[did]

    def add_log(self, did, step, act, tgt, sts, msg=""):
        s = self.sessions.get(did)
        if s:
            with s.log_lock:
                s.logs.append(StepLog(step, act, tgt, sts, msg, time.time()))

    def clear_logs(self, did):
        s = self.sessions.get(did)
        if s: 
            with s.log_lock: s.logs = []

    def get_logs(self, did):
        s = self.sessions.get(did)
        if not s: return []
        with s.log_lock: return [{"step": l.step_number, "action": l.action, "target": l.target, "status": l.status, "message": l.message} for l in s.logs]

    def set_test_state(self, did, state, cs=0, ts=0):
        s = self.sessions.get(did)
        if s: s.test_state = state; s.current_step = cs; s.total_steps = ts

    def get_test_state(self, did):
        s = self.sessions.get(did)
        if not s: return {"state": "no_session"}
        return {"state": s.test_state.value, "current_step": s.current_step, "total_steps": s.total_steps, "logs": self.get_logs(did)}
    
    def stop_test(self, did):
        s = self.sessions.get(did)
        if s: s.stop_requested = True

emulator_service = EmulatorService()