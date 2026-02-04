import time
import os
import logging
import pyautogui
from pywinauto import Desktop as WinDesktop
from PIL import Image

from drivers.base_driver import BaseDriver

# PyAutoGUI fail-safe
pyautogui.FAILSAFE = True

class DesktopDriver(BaseDriver):
    def __init__(self):
        # Global logger kullan (UI Handler'ı yakalasın diye)
        self.logger = logging.getLogger()
        # OpenCV Kontrolü
        try:
            import cv2
            self.logger.info("OpenCV (cv2) Aktif. Super-Vision motoru hazır.")
            self.has_opencv = True
        except ImportError:
            self.logger.warning("OpenCV bulunamadı. Lütfen 'opencv-python' paketini kurun.")
            self.has_opencv = False
        
    def launch_app(self, app_path: str) -> bool:
        self.logger.info(f"Uygulama başlatılıyor: {app_path}")
        try:
            os.startfile(app_path)
            self.logger.info("Pencerenin açılması bekleniyor (Max 15s)...")
            start_time = time.time()
            max_wait = 15
            app_name = os.path.basename(app_path).split('.')[0].lower()
            our_tool_title = "Desktop Otomasyon"
            
            while time.time() - start_time < max_wait:
                try:
                    desktop = WinDesktop(backend="uia")
                    for win in desktop.windows():
                        title = win.window_text()
                        if not title: continue
                        title_lower = title.lower()
                        if our_tool_title.lower() in title_lower: continue
                        if app_name in title_lower or "google chrome" in title_lower or "edge" in title_lower:
                            if win.is_visible():
                                win.maximize()
                                win.set_focus()
                                self.logger.info(f"Pencere yakalandı ve tam ekran yapıldı: {title}")
                                return True
                    # Fallback
                    desktop_windows = desktop.windows(enabled_only=True, visible_only=True)
                    if desktop_windows and our_tool_title.lower() not in desktop_windows[0].window_text().lower():
                        pyautogui.hotkey('win', 'up')
                        time.sleep(0.5)
                except: pass
                time.sleep(1.5)
            return True
        except Exception as e:
            self.logger.error(f"Uygulama başlatılamadı: {e}")
            return False

    def click(self, target: str, timeout: int = 10, text_hint: str = None, button: str = 'left') -> bool:
        """
        ABSOLUTE VISION v26:
        1. Super-Scale: 0.7x - 1.3x arası 13 farklı ölçekte arama.
        2. Blur Normalization: Anti-aliasing hatalarını giderme.
        3. Color Correlation: Renk doğrulaması (Siyah-beyaz eşleşmeyi renkli teyit eder).
        4. Dynamic Confidence: Zamanla esneyen tolerans.
        """
        try:
            if "," in target and os.path.sep not in target:
                x, y = map(int, target.split(","))
                pyautogui.click(x, y, button=button)
                self.logger.info(f"Koordinata tıklandı: {x},{y}")
                return True
            
            self.logger.info(f"Absolute Vision Arama: {os.path.basename(target)}")
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                # Zaman geçtikçe güven eşiğini hafifçe düşür (0.85 -> 0.70)
                elapsed = time.time() - start_time
                confidence = max(0.65, 0.85 - (elapsed / timeout) * 0.20)
                
                # --- KATMAN 1: ABSOLUTE VISION (OpenCV + Color Check) ---
                if self.has_opencv:
                    coords = self._find_image_opencv(target, threshold=confidence)
                    if coords:
                        target_x, target_y = coords
                        
                        # --- ROBUST KLİK SİTESİ (v33 & v36) ---
                        # 1. Fareyi oraya taşı (Görsel onay için)
                        pyautogui.moveTo(target_x, target_y, duration=0.2)
                        
                        # 2. PRE-CLICK STABILIZATION (v36): "Nişan Alma" Beklemesi
                        time.sleep(0.3) 

                        # 3. Bas-Bekle-Bırak (Tıklamayı kaçırmasın diye)
                        pyautogui.mouseDown(button=button)
                        time.sleep(0.05)
                        pyautogui.mouseUp(button=button)
                        
                        self.logger.info(f"Görsel bulundu (Absolute Vision %{int(confidence*100)}): {target}")
                        return True
                
                # --- KATMAN 2: STANDARD FALLBACK ---
                try:
                    needle = Image.open(target)
                    location = pyautogui.locateOnScreen(needle, grayscale=True, confidence=min(0.8, confidence))
                    if location:
                        center = pyautogui.center(location)
                        pyautogui.click(center, button=button)
                        self.logger.info(f"Görsel bulundu (Standard Fallback): {target}")
                        return True
                except: pass

                # --- KATMAN 3: YAPIŞAL UIA ---
                if text_hint:
                    try:
                        desktop = WinDesktop(backend="uia")
                        for win in desktop.windows(visible_only=True, enabled_only=True):
                            try:
                                child = win.child_window(title_re=f".*{text_hint}.*", found_index=0)
                                if child.exists():
                                    child.click_input(button=button)
                                    self.logger.info(f"Yapısal (UIA) ile tıklandı: {text_hint}")
                                    return True
                            except: continue
                    except: pass

                time.sleep(0.3)

            self.logger.error(f"Ekranda bulunamadı: {target}")
            return False
        except Exception as e:
            self.logger.error(f"Tıklama hatası: {e}")
            return False

    def _find_image_opencv(self, target_path: str, threshold: float = 0.8):
        """Absolute Vision: Multi-Scale + Blur + Color Verification."""
        try:
            import cv2
            import numpy as np
            
            # Ekranı al ve normalize et
            screen_img = np.array(pyautogui.screenshot())
            screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            
            # Blur uygulaması (Anti-aliasing gürültüsünü engellemek için)
            screen_gray = cv2.GaussianBlur(screen_gray, (3, 3), 0)
            
            template_bgr = cv2.imread(target_path)
            if template_bgr is None: return None
            template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.GaussianBlur(template_gray, (3, 3), 0)
            
            h, w = template_gray.shape[:2]
            
            # Ultra-Fine Scaling: 0.7 ile 1.3 arası 13 kademe
            scales = np.linspace(0.7, 1.3, 13)
            
            best_match = None
            max_val = -1
            
            # PHASE 1: STANDARD MULTI-SCALE SEARCH
            for scale in scales:
                rw, rh = int(w * scale), int(h * scale)
                if rw < 20 or rh < 20: continue
                
                resized_gray = cv2.resize(template_gray, (rw, rh))
                res = cv2.matchTemplate(screen_gray, resized_gray, cv2.TM_CCOEFF_NORMED)
                _, val, _, loc = cv2.minMaxLoc(res)
                
                if val > max_val:
                    max_val = val
                    best_match = (loc, scale, rw, rh)

            # PHASE 2: PROFESSIONAL EDGE-MATCHING FALLBACK (v34)
            # Eğer normal arama başarısız olursa, sadece "şekil" (kenar) bulmaya çalış.
            # Bu profesyonel RPA araçlarının renk değişimlerine karşı kullandığı bir yöntemdir.
            if max_val < threshold:
                self.logger.info("Vision Teşhis: Şekil bazlı (Edge-Matching) yedek plan deneniyor...")
                screen_edges = cv2.Canny(screen_gray, 50, 150)
                template_edges = cv2.Canny(template_gray, 50, 150)
                
                for scale in scales:
                    rw, rh = int(w * scale), int(h * scale)
                    if rw < 20 or rh < 20: continue
                    resized_edges = cv2.resize(template_edges, (rw, rh))
                    res = cv2.matchTemplate(screen_edges, resized_edges, cv2.TM_CCOEFF_NORMED)
                    _, val, _, loc = cv2.minMaxLoc(res)
                    if val > max_val:
                        max_val = val
                        best_match = (loc, scale, rw, rh)

            # DIAGNOSTIC LOGGING
            self.logger.info(f"Vision Teşhis: [Ölçek: {len(scales)}] [En İyi: %{int(max_val*100)}] [Eşik: %{int(threshold*100)}]")

            # Eşik değer kontrolü ve RENK DOĞRULAMASI (Color Verification)
            if max_val >= threshold and best_match:
                loc, scale, rw, rh = best_match
                
                # Bulunan bölgeyi renkli olarak kes
                detected_region = screen_bgr[loc[1]:loc[1]+rh, loc[0]:loc[0]+rw]
                target_resized_bgr = cv2.resize(template_bgr, (rw, rh))
                
                # Renk korelasyonu (Piksel bazlı renk eşleşme kontrolü)
                color_res = cv2.matchTemplate(detected_region, target_resized_bgr, cv2.TM_CCORR_NORMED)
                _, color_val, _, _ = cv2.minMaxLoc(color_res)
                
                self.logger.info(f"Vision Teşhis: Renk Onayı Skoru: %{int(color_val*100)} (Eşik: %70)")
                
                if color_val > 0.60: # v34: Renk toleransı biraz daha esnetildi
                    center_x = loc[0] + rw // 2
                    center_y = loc[1] + rh // 2
                    
                    # DPI DÜZELTMESİ (Stabil Model)
                    from core.config import get_dpi_scaling
                    scaling = get_dpi_scaling()
                    target_x = center_x / scaling
                    target_y = center_y / scaling
                    
                    self.logger.info(f"Hassas Koordinatlar Hesaplandı: ({int(target_x)}, {int(target_y)}) [DPI Skaler: {scaling:.2f}]")
                    return (target_x, target_y)
                else:
                    self.logger.info(f"DİKKAT: Şekil bulundu (%{int(max_val*100)}) ama RENK TUTMADI (%{int(color_val*100)}).")
            
            return None
        except Exception as e:
            self.logger.debug(f"OpenCV Vision Hatası: {e}")
            return None

    def type_text(self, text: str, interval: float = 0.1) -> bool:
        try:
            # GÜVENLİK (v35): Hassas verileri loglama!
            self.logger.info(f"Metin yazılıyor: [GİZLİ METİN - {len(text)} karakter]")
            import random
            for char in text:
                pyautogui.write(char)
                time.sleep(interval + random.uniform(0, 0.05))
            return True
        except: return False

    def wait(self, seconds: float):
        self.logger.info(f"Bekleniyor: {seconds} sn")
        time.sleep(seconds)

    def assert_exists(self, target: str, timeout: int = 10) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._find_image_opencv(target): return True
            time.sleep(0.5)
        return False

    def take_screenshot(self, save_path: str) -> str:
        try:
            pyautogui.screenshot().save(save_path)
            return save_path
        except: return ""

    def handle_popup(self, image_path: str = "assets/connection_error_popup.png") -> bool:
        try:
            loc = self._find_image_opencv(image_path)
            if loc:
                pyautogui.click(loc)
                time.sleep(0.5)
                pyautogui.press('enter')
                return True
            return False
        except: return False

    def validate_window(self, title: str, timeout: int = 5) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                desktop = WinDesktop(backend="uia")
                for win in desktop.windows():
                    if title.lower() in win.window_text().lower(): return True
            except: pass
            time.sleep(0.5)
        return False

    def press_key(self, key: str) -> bool:
        try:
            pyautogui.press(key)
            return True
        except: return False

    def scroll(self, clicks: int) -> bool:
        try:
            pyautogui.scroll(clicks)
            return True
        except: return False
