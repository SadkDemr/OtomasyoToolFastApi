import threading
import time
import os
import datetime
import pyautogui
from pynput import mouse, keyboard
import logging

class Recorder:
    def __init__(self, on_action_recorded, on_stop, exclude_window=None):
        self.logger = logging.getLogger("Recorder")
        self.on_action_recorded = on_action_recorded
        self.on_stop = on_stop
        self.exclude_window = exclude_window
        self.is_recording = False
        self.mouse_listener = None
        self.keyboard_listener = None
        
        self.last_click_time = 0
        self.type_buffer = ""
        self.last_key_time = 0
        
    def start(self):
        self.is_recording = True
        self.type_buffer = ""
        self.logger.info("Recording started (v25 Wide-Vision Active)...")
        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self.keyboard_listener = keyboard.Listener(on_press=self.on_press)
        self.mouse_listener.start()
        self.keyboard_listener.start()
        
    def stop(self):
        if not self.is_recording: return
        self.is_recording = False
        self._flush_type_buffer()
        if self.mouse_listener: self.mouse_listener.stop()
        if self.keyboard_listener: self.keyboard_listener.stop()
        if self.on_stop: self.on_stop()

    def on_click(self, x, y, button, pressed):
        if not self.is_recording or not pressed: return
        self._flush_type_buffer()

        if self.exclude_window:
            try:
                wx = self.exclude_window.winfo_rootx()
                wy = self.exclude_window.winfo_rooty()
                ww = self.exclude_window.winfo_width()
                wh = self.exclude_window.winfo_height()
                if self.exclude_window.winfo_viewable():
                    if wx <= x <= wx + ww and wy <= y <= wy + wh: return
            except: pass

        if time.time() - self.last_click_time < 0.5: return
        self.last_click_time = time.time()
        
        btn_str = 'left' if button == mouse.Button.left else 'right'
        self._capture_and_record(x, y, button=btn_str)

    def on_press(self, key):
        if key == keyboard.Key.esc:
            self.stop()
            return
        if not self.is_recording: return
        try:
            if hasattr(key, 'char') and key.char:
                self.type_buffer += key.char
            elif key == keyboard.Key.space:
                self.type_buffer += " "
            else:
                self._flush_type_buffer()
        except: pass

    def _flush_type_buffer(self):
        if self.type_buffer:
            self.on_action_recorded("TYPE", {"text": self.type_buffer})
            self.type_buffer = ""

    def _capture_and_record(self, x, y, button='left'):
        """v25: Geniş Açı (Wide-Vision) 300x300 Context Capture."""
        try:
            region_size = 300
            left = max(0, int(x - region_size / 2))
            top = max(0, int(y - region_size / 2))
            
            screenshot = pyautogui.screenshot(region=(left, top, region_size, region_size))
            
            from core.config import ASSETS_DIR
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"wide_click_{timestamp}.png"
            filepath = os.path.join(ASSETS_DIR, filename)
            
            screenshot.save(filepath)
            self.logger.info(f"Wide-Vision Capture: {filename} (300x300)")
            
            # Callback to UI
            params = {"target": filepath, "by_image": True, "button": button}
            self.on_action_recorded("CLICK", params)
        except Exception as e:
            self.logger.error(f"Capture error: {e}")
