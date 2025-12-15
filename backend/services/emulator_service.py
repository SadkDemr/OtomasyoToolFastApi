"""
Emulator Service - ADB ile emulator kontrolu
Canlı ekran + Canlı log destegi
"""

import subprocess
import base64
import os
import threading
import time
import asyncio
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, field
from enum import Enum


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
    status: str  # pending, running, success, failed
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
    pause_requested: bool = False
    logs: List[StepLog] = field(default_factory=list)
    last_frame: Optional[str] = None
    frame_lock: threading.Lock = field(default_factory=threading.Lock)
    log_lock: threading.Lock = field(default_factory=threading.Lock)
    websockets: List = field(default_factory=list)  # Aktif WebSocket baglantilari


class EmulatorService:
    def __init__(self):
        self.sessions: Dict[str, EmulatorSession] = {}
        self.adb_path = self._find_adb()
        self._frame_threads: Dict[str, threading.Thread] = {}
        self._stop_frames: Dict[str, bool] = {}
    
    def _find_adb(self) -> str:
        # Proje icindeki platform-tools
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local = os.path.join(base, "platform-tools", "adb.exe")
        if os.path.exists(local):
            return local
        
        # Linux/Mac
        local_unix = os.path.join(base, "platform-tools", "adb")
        if os.path.exists(local_unix):
            return local_unix
        
        # System PATH
        try:
            r = subprocess.run(['adb', 'version'], capture_output=True, timeout=5)
            if r.returncode == 0:
                return 'adb'
        except:
            pass
        
        return local if os.name == 'nt' else 'adb'
    
    def is_adb_available(self) -> bool:
        try:
            r = subprocess.run([self.adb_path, 'version'], capture_output=True, timeout=5)
            return r.returncode == 0
        except:
            return False
    
    def get_connected_devices(self) -> List[dict]:
        try:
            r = subprocess.run([self.adb_path, 'devices'], capture_output=True, text=True, timeout=10)
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
    
    def _capture_frame_sync(self, device_id: str) -> Optional[str]:
        """Senkron frame yakala"""
        try:
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'exec-out', 'screencap', '-p'],
                capture_output=True, timeout=3
            )
            if r.returncode == 0 and r.stdout and len(r.stdout) > 100:
                return base64.b64encode(r.stdout).decode('utf-8')
        except Exception as e:
            print(f"Frame capture error: {e}")
        return None
    
    def _frame_capture_loop(self, device_id: str):
        """Arka planda surekli frame yakala"""
        print(f"[EMU] Frame capture started for {device_id}")
        
        while not self._stop_frames.get(device_id, False):
            session = self.sessions.get(device_id)
            if not session or not session.is_active:
                break
            
            frame = self._capture_frame_sync(device_id)
            if frame:
                with session.frame_lock:
                    session.last_frame = frame
            
            # 80ms bekle (~12 FPS - stabil)
            time.sleep(0.08)
        
        print(f"[EMU] Frame capture stopped for {device_id}")
    
    def start_frame_capture(self, device_id: str):
        """Frame yakalama thread'ini baslat"""
        self._stop_frames[device_id] = False
        
        # Eski thread varsa bekle
        if device_id in self._frame_threads:
            old_thread = self._frame_threads[device_id]
            if old_thread.is_alive():
                self._stop_frames[device_id] = True
                old_thread.join(timeout=2)
        
        self._stop_frames[device_id] = False
        thread = threading.Thread(target=self._frame_capture_loop, args=(device_id,), daemon=True)
        thread.start()
        self._frame_threads[device_id] = thread
    
    def stop_frame_capture(self, device_id: str):
        """Frame yakalama thread'ini durdur"""
        self._stop_frames[device_id] = True
    
    def get_cached_frame(self, device_id: str) -> Optional[str]:
        """Cache'lenmis frame'i al"""
        session = self.sessions.get(device_id)
        if session:
            with session.frame_lock:
                return session.last_frame
        return None
    
    def capture_screen(self, device_id: str) -> Optional[str]:
        """Uyumluluk icin"""
        cached = self.get_cached_frame(device_id)
        if cached:
            return cached
        return self._capture_frame_sync(device_id)
    
    def get_screen_size(self, device_id: str) -> tuple:
        try:
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'wm', 'size'],
                capture_output=True, text=True, timeout=5
            )
            if 'Physical size:' in r.stdout:
                s = r.stdout.split(':')[1].strip()
                w, h = map(int, s.split('x'))
                return (w, h)
        except:
            pass
        return (1080, 1920)
    
    def send_tap(self, device_id: str, x: int, y: int) -> bool:
        try:
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'input', 'tap', str(x), str(y)],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
        except:
            return False
    
    def send_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        try:
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'input', 'swipe',
                 str(x1), str(y1), str(x2), str(y2), str(duration)],
                capture_output=True, timeout=10
            )
            return r.returncode == 0
        except:
            return False
    
    def send_text(self, device_id: str, text: str) -> bool:
        try:
            t = text.replace(' ', '%s').replace('&', '\\&').replace('<', '\\<').replace('>', '\\>')
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'input', 'text', t],
                capture_output=True, timeout=10
            )
            return r.returncode == 0
        except:
            return False
    
    def send_key(self, device_id: str, keycode: int) -> bool:
        try:
            r = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'input', 'keyevent', str(keycode)],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
        except:
            return False
    
    def press_back(self, device_id: str) -> bool:
        return self.send_key(device_id, 4)
    
    def press_home(self, device_id: str) -> bool:
        return self.send_key(device_id, 3)
    
    def press_recent(self, device_id: str) -> bool:
        return self.send_key(device_id, 187)
    
    def launch_app(self, device_id: str, package: str, activity: str = "") -> bool:
        try:
            if activity:
                cmd = [self.adb_path, '-s', device_id, 'shell', 'am', 'start', '-n', f'{package}/{activity}']
            else:
                cmd = [self.adb_path, '-s', device_id, 'shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1']
            
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            return r.returncode == 0
        except:
            return False
    
    # === SESSION ===
    
    def create_session(self, device_id: str, user_id: int) -> EmulatorSession:
        # Eski session varsa kapat
        if device_id in self.sessions:
            self.close_session(device_id)
        
        session = EmulatorSession(device_id=device_id, user_id=user_id)
        self.sessions[device_id] = session
        
        # Frame capture baslat
        self.start_frame_capture(device_id)
        
        print(f"[EMU] Session created for {device_id}")
        return session
    
    def get_session(self, device_id: str) -> Optional[EmulatorSession]:
        return self.sessions.get(device_id)
    
    def ensure_session(self, device_id: str, user_id: int = 1) -> EmulatorSession:
        """Session yoksa olustur"""
        session = self.get_session(device_id)
        if not session:
            session = self.create_session(device_id, user_id)
        return session
    
    def close_session(self, device_id: str):
        self.stop_frame_capture(device_id)
        if device_id in self.sessions:
            self.sessions[device_id].is_active = False
            del self.sessions[device_id]
        print(f"[EMU] Session closed for {device_id}")
    
    # === LOGS ===
    
    def add_log(self, device_id: str, step_number: int, action: str, target: str, status: str, message: str = ""):
        """Log ekle ve WebSocket'lere bildir"""
        session = self.get_session(device_id)
        if not session:
            return
        
        with session.log_lock:
            # Ayni adim varsa guncelle
            existing = None
            for log in session.logs:
                if log.step_number == step_number:
                    existing = log
                    break
            
            if existing:
                existing.status = status
                existing.message = message
                existing.timestamp = time.time()
            else:
                log = StepLog(
                    step_number=step_number,
                    action=action,
                    target=target,
                    status=status,
                    message=message,
                    timestamp=time.time()
                )
                session.logs.append(log)
        
        print(f"[LOG] Step {step_number}: {action} -> {status}")
    
    def clear_logs(self, device_id: str):
        session = self.get_session(device_id)
        if session:
            with session.log_lock:
                session.logs = []
    
    def get_logs(self, device_id: str) -> List[dict]:
        session = self.get_session(device_id)
        if session:
            with session.log_lock:
                return [
                    {
                        "step": l.step_number,
                        "action": l.action,
                        "target": l.target,
                        "status": l.status,
                        "message": l.message,
                        "timestamp": l.timestamp
                    }
                    for l in session.logs
                ]
        return []
    
    # === TEST STATE ===
    
    def set_test_state(self, device_id: str, state: TestRunState, current_step: int = 0, total_steps: int = 0):
        session = self.get_session(device_id)
        if session:
            session.test_state = state
            session.current_step = current_step
            session.total_steps = total_steps
    
    def stop_test(self, device_id: str):
        s = self.get_session(device_id)
        if s:
            s.stop_requested = True
            s.test_state = TestRunState.STOPPED
    
    def get_test_state(self, device_id: str) -> dict:
        s = self.get_session(device_id)
        if not s:
            return {"state": "no_session", "current_step": 0, "total_steps": 0, "logs": []}
        
        return {
            "state": s.test_state.value,
            "current_step": s.current_step,
            "total_steps": s.total_steps,
            "logs": self.get_logs(device_id)
        }


emulator_service = EmulatorService()
