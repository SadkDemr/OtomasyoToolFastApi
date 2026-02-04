"""
Appium Service - FULL VERSION v8
================================
TÜM ÖZELLİKLER:
1. YAZMA: ADB + Appium + Broadcast (3 katmanlı garanti)
2. ÖNCE TIKLA SONRA YAZ: İki satırlık format desteği
3. INDEX: 1. "Ürün" tıkla, 2. "Buton" tıkla, son "Element" tıkla
4. IF/ELSE: Eğer "Popup" varsa kapat yoksa "Devam" tıkla
5. OPSİYONEL: [opsiyonel] "Reklam" varsa kapat
6. METIN OLMAYAN INPUT: resource-id, content-desc, hint ile bulma
7. DEĞİŞKEN: @kullanici = "admin", @bakiye kaydet
8. SCROLL: Yukarı/aşağı/element bulana kadar
9. DOĞRULAMA: Ekranda metin kontrolü
10. HIZLI STOP: Anında durdurma
"""
import sys
import os
import time
import re
import subprocess
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas import TestStep, StepResult

try:
    from services.emulator_service import emulator_service, TestRunState
    EMU_SERVICE = True
except:
    EMU_SERVICE = False
    print("[APPIUM] Emulator service yüklenemedi")

try:
    from appium import webdriver as appium_webdriver
    from appium.options.android import UiAutomator2Options
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import *
    APPIUM_AVAILABLE = True
except ImportError:
    APPIUM_AVAILABLE = False
    print("!!! APPIUM KUTUPHANESI EKSIK - pip install Appium-Python-Client !!!")


@dataclass
class AdvancedTestStep:
    """Gelişmiş test adımı"""
    action: str = ""
    target: str = ""
    value: str = ""
    locator_type: str = "auto"
    index: int = 0  # 0=ilk, 1=ikinci, -1=son
    condition: str = ""
    else_action: str = ""
    else_target: str = ""
    else_value: str = ""
    timeout: int = 2  # 2 saniye (hızlı hata)
    optional: bool = False
    raw_line: str = ""  # Debug için orijinal satır


class AppiumService:
    def __init__(self):
        self.driver = None
        self.current_device_id = None
        self.current_platform = 'android'  # 'android' veya 'ios'
        self.variables: Dict[str, str] = {}
        self.adb_path = self._find_adb()

    def _find_adb(self) -> str:
        """ADB yolunu bul"""
        import shutil
        adb = shutil.which("adb")
        if adb:
            return adb
        
        paths = [
            os.path.expanduser("~") + "\\AppData\\Local\\Android\\Sdk\\platform-tools\\adb.exe",
            "C:\\platform-tools\\adb.exe",
            "C:\\Android\\platform-tools\\adb.exe",
            "/usr/bin/adb",
            "/usr/local/bin/adb"
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return "adb"

    def is_available(self) -> bool:
        return APPIUM_AVAILABLE

    def _log(self, step_num: int, action: str, target: str, status: str, message: str = ""):
        print(f"[TEST] Adım {step_num}: {action} '{target}' -> {status}")
        if EMU_SERVICE and self.current_device_id:
            emulator_service.add_log(self.current_device_id, step_num, action, target, status, message)

    def _set_state(self, state: str, current: int = 0, total: int = 0):
        if EMU_SERVICE and self.current_device_id:
            state_map = {"running": TestRunState.RUNNING, "success": TestRunState.SUCCESS, 
                        "failed": TestRunState.FAILED, "stopped": TestRunState.STOPPED}
            emulator_service.set_test_state(self.current_device_id, state_map.get(state, TestRunState.IDLE), current, total)

    def _check_stop(self):
        """Test durdurulduysa exception fırlat"""
        if EMU_SERVICE and self.current_device_id:
            session = emulator_service.get_session(self.current_device_id)
            if session and session.stop_requested:
                raise Exception("STOPPED_BY_USER")

    def _is_stopped(self) -> bool:
        if EMU_SERVICE and self.current_device_id:
            session = emulator_service.get_session(self.current_device_id)
            return session and session.stop_requested
        return False

    # ============ DRIVER YÖNETİMİ ============

    def create_driver(self, device):
        """Android veya iOS cihaz için driver oluştur"""
        device_id = device.device_id if hasattr(device, 'device_id') else str(device)
        appium_url = getattr(device, 'appium_url', None) or "http://localhost:4723"
        platform = getattr(device, 'platform', 'android').lower()
        
        print(f"[APPIUM] Driver: {device_id} @ {appium_url} ({platform})")
        self.current_device_id = device_id
        self.current_platform = platform
        
        if platform == 'ios':
            # iOS - XCUITest Driver
            from appium.options.ios import XCUITestOptions
            
            options = XCUITestOptions()
            options.platform_name = 'iOS'
            options.udid = device_id
            options.automation_name = 'XCUITest'
            options.no_reset = True
            options.new_command_timeout = 300
            
            # iOS özellikleri
            if hasattr(device, 'platform_version'):
                options.platform_version = device.platform_version
            if hasattr(device, 'device_name'):
                options.device_name = device.device_name
            if hasattr(device, 'bundle_id'):
                options.set_capability('bundleId', device.bundle_id)
            
            # WebDriverAgent ayarları
            options.set_capability('useNewWDA', False)
            options.set_capability('wdaStartupRetries', 3)
            options.set_capability('wdaStartupRetryInterval', 20000)
            options.set_capability('showXcodeLog', False)
            
        else:
            # Android - UiAutomator2 Driver
            options = UiAutomator2Options()
            options.platform_name = 'Android'
            options.udid = device_id
            options.automation_name = 'UiAutomator2'
            options.no_reset = True
            options.new_command_timeout = 120
            
            # Klavye ayarları
            options.set_capability('unicodeKeyboard', False)
            options.set_capability('resetKeyboard', False)
            options.set_capability('skipUnlock', True)
            options.set_capability('appium:autoGrantPermissions', True)
            options.set_capability('appium:ignoreHiddenApiPolicyError', True)
        
        self.driver = appium_webdriver.Remote(appium_url, options=options)
        self.driver.implicitly_wait(2)
        print(f"[APPIUM] ✅ Driver hazır ({platform})")
        return self.driver

    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
        self.current_device_id = None

    def restart_application(self, package: str):
        if not package:
            return
        try:
            print(f"[APPIUM] Uygulama yeniden başlatılıyor: {package}")
            self.driver.terminate_app(package)
            time.sleep(0.5)
            self.driver.activate_app(package)
            time.sleep(1.5)
        except Exception as e:
            print(f"[APPIUM] Restart hatası: {e}")

    # ============ ELEMENT BULMA ============

    def find_element_smart(self, locator_type: str, value: str, index: int = 0, 
                          timeout: int = 5, raise_error: bool = True):
        """
        Akıllı element bulma - Birden fazla strateji dener
        index: 0=ilk, 1=ikinci, 2=üçüncü, -1=son
        """
        strategies = []
        
        # Özel karakterleri XPath için escape et
        def escape_xpath(text):
            if "'" in text and '"' in text:
                # Hem tek hem çift tırnak varsa concat kullan
                parts = text.split("'")
                return "concat('" + "', \"'\", '".join(parts) + "')"
            elif "'" in text:
                return f'"{text}"'
            else:
                return f"'{text}'"
        
        # Parantezli metinler için alternatif aramalar
        search_values = [value]
        
        # Parantez varyasyonları: "Text(ABC)" -> "Text (ABC)", "Text( ABC )" vs.
        if '(' in value:
            before_paren = value.split('(')[0].strip()
            in_paren = value.split('(')[1].rstrip(')')
            
            # Farklı boşluk kombinasyonları
            search_values.extend([
                f"{before_paren} ({in_paren})",      # "Text (ABC)"
                f"{before_paren}({in_paren})",       # "Text(ABC)"
                f"{before_paren}( {in_paren} )",    # "Text( ABC )"
                f"{before_paren} ( {in_paren} )",   # "Text ( ABC )"
            ])
            
            # Sadece parantez öncesi
            if before_paren and len(before_paren) > 2:
                search_values.append(before_paren)
            
            # Sadece parantez içi
            if in_paren and len(in_paren) > 2:
                search_values.append(in_paren)
        
        # Türkçe karakter alternatifleri
        tr_map = {'ı': 'i', 'İ': 'I', 'ğ': 'g', 'Ğ': 'G', 'ü': 'u', 'Ü': 'U', 
                  'ş': 's', 'Ş': 'S', 'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C'}
        ascii_value = value
        for tr, en in tr_map.items():
            ascii_value = ascii_value.replace(tr, en)
        if ascii_value != value:
            search_values.append(ascii_value)
        
        # Duplicate'leri kaldır
        search_values = list(dict.fromkeys(search_values))
        
        if locator_type == 'id':
            strategies.append((AppiumBy.ID, value))
        elif locator_type == 'xpath':
            strategies.append((AppiumBy.XPATH, value))
        elif locator_type == 'accessibility_id':
            strategies.append((AppiumBy.ACCESSIBILITY_ID, value))
        else:
            # Auto mod - ÖNCE TAM EŞLEŞMELERİ DENE
            for search_val in search_values:
                escaped = escape_xpath(search_val)
                
                # ========== ÖNCE TAM EŞLEŞMELER ==========
                strategies.extend([
                    # Tam metin eşleşmesi (en güvenilir)
                    (AppiumBy.XPATH, f"//*[@text={escaped}]"),
                    (AppiumBy.XPATH, f"//android.widget.TextView[@text={escaped}]"),
                    (AppiumBy.XPATH, f"//android.widget.Button[@text={escaped}]"),
                    (AppiumBy.XPATH, f"//*[@content-desc={escaped}]"),
                    (AppiumBy.ACCESSIBILITY_ID, search_val),
                    # Clickable tam eşleşme
                    (AppiumBy.XPATH, f"//*[@clickable='true'][@text={escaped}]"),
                    # CheckedTextView tam eşleşme
                    (AppiumBy.XPATH, f"//android.widget.CheckedTextView[@text={escaped}]"),
                    
                    # ========== EK BUTON STRATEJİLERİ ==========
                    # View içinde metin (custom button'lar için)
                    (AppiumBy.XPATH, f"//android.view.View[@text={escaped}]"),
                    (AppiumBy.XPATH, f"//android.view.View[@content-desc={escaped}]"),
                    # Clickable View
                    (AppiumBy.XPATH, f"//android.view.View[@clickable='true'][@text={escaped}]"),
                    (AppiumBy.XPATH, f"//android.view.View[@clickable='true'][@content-desc={escaped}]"),
                    # Enabled ve clickable
                    (AppiumBy.XPATH, f"//*[@enabled='true'][@clickable='true'][@text={escaped}]"),
                    (AppiumBy.XPATH, f"//*[@enabled='true'][@text={escaped}]"),
                    # ImageButton, ImageView
                    (AppiumBy.XPATH, f"//android.widget.ImageButton[@content-desc={escaped}]"),
                    (AppiumBy.XPATH, f"//android.widget.ImageView[@content-desc={escaped}]"),
                    # FrameLayout, LinearLayout içinde
                    (AppiumBy.XPATH, f"//android.widget.FrameLayout[@content-desc={escaped}]"),
                    (AppiumBy.XPATH, f"//android.widget.LinearLayout//*[@text={escaped}]"),
                    # Metin içeren herhangi bir clickable element
                    (AppiumBy.XPATH, f"//*[@clickable='true'][.//*[@text={escaped}]]"),
                    (AppiumBy.XPATH, f"//*[@clickable='true'][.//android.widget.TextView[@text={escaped}]]"),
                ])
            
            # ========== SONRA CONTAINS (sadece uzun metinler için) ==========
            # Kısa metinler (<=3 karakter) için contains KULLANMA - yanlış eşleşme riski yüksek
            for search_val in search_values:
                if len(search_val) <= 3:
                    continue  # "TL", "USD" gibi kısa metinler için contains atla
                
                escaped = escape_xpath(search_val)
                strategies.extend([
                    # Metin içerme (sadece uzun metinler için)
                    (AppiumBy.XPATH, f"//*[contains(@text, {escaped})]"),
                    (AppiumBy.XPATH, f"//*[contains(@content-desc, {escaped})]"),
                    (AppiumBy.XPATH, f"//*[contains(@resource-id, {escaped})]"),
                    (AppiumBy.XPATH, f"//android.widget.TextView[contains(@text, {escaped})]"),
                    (AppiumBy.XPATH, f"//android.widget.Button[contains(@text, {escaped})]"),
                    (AppiumBy.XPATH, f"//*[@clickable='true'][contains(@text, {escaped})]"),
                    (AppiumBy.XPATH, f"//android.widget.CheckedTextView[contains(@text, {escaped})]"),
                ])
            
            # ========== EDİTTEXT STRATEJİLERİ (Label yanındaki input) ==========
            # Bu stratejiler "TL" gibi label'ın yanındaki boş input'u bulmak için
            escaped = escape_xpath(value)
            strategies.extend([
                # 1. Label'ın hemen yanındaki EditText (sibling)
                (AppiumBy.XPATH, f"//*[@text={escaped}]/following-sibling::android.widget.EditText[1]"),
                (AppiumBy.XPATH, f"//*[@text={escaped}]/preceding-sibling::android.widget.EditText[1]"),
                
                # 2. Label ile aynı parent içindeki EditText
                (AppiumBy.XPATH, f"//*[@text={escaped}]/../android.widget.EditText"),
                (AppiumBy.XPATH, f"//*[@text={escaped}]/../..//android.widget.EditText"),
                
                # 3. Label'ın parent'ının içindeki herhangi bir input
                (AppiumBy.XPATH, f"//*[@text={escaped}]/..//*[contains(@class, 'EditText')]"),
                (AppiumBy.XPATH, f"//*[@text={escaped}]/../..//*[contains(@class, 'EditText')]"),
                
                # 4. Content-desc ile aynı stratejiler
                (AppiumBy.XPATH, f"//*[@content-desc={escaped}]/following-sibling::android.widget.EditText[1]"),
                (AppiumBy.XPATH, f"//*[@content-desc={escaped}]/../android.widget.EditText"),
                
                # 5. Resource-id içinde label adı geçen EditText
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@resource-id, 'tl')]") if value.lower() == 'tl' else None,
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@resource-id, 'usd')]") if value.lower() == 'usd' else None,
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@resource-id, '{value.lower()}')]"),
                
                # 6. Hint içeren EditText
                (AppiumBy.XPATH, f"//android.widget.EditText[@hint={escaped}]"),
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@hint, {escaped})]") if len(value) > 2 else None,
                
                # 7. Focusable/clickable EditText (label'dan sonra gelen ilk)
                (AppiumBy.XPATH, f"//*[@text={escaped}]/following::android.widget.EditText[1]"),
            ])
            
            # None değerleri temizle
            strategies = [s for s in strategies if s is not None]
        
        per_timeout = min(0.15, timeout / max(len(strategies), 1))  # Çok hızlı
        
        for by_type, by_value in strategies:
            try:
                self._check_stop()
                
                if index != 0:
                    # Birden fazla element bul ve index'e göre seç
                    elements = WebDriverWait(self.driver, per_timeout).until(
                        lambda d: d.find_elements(by_type, by_value)
                    )
                    if elements:
                        if index == -1:
                            return elements[-1]  # Son element
                        elif index < len(elements):
                            return elements[index]
                else:
                    # İlk elementi bul
                    element = WebDriverWait(self.driver, per_timeout).until(
                        EC.presence_of_element_located((by_type, by_value))
                    )
                    if element:
                        return element
            except:
                continue
        
        if raise_error:
            raise Exception(f"Element bulunamadı: '{value}'")
        return None

    def element_exists(self, target: str, timeout: float = 2.0) -> bool:
        """Element var mı kontrol et"""
        try:
            self.find_element_smart("auto", target, timeout=timeout, raise_error=False)
            return True
        except:
            return False

    def find_input_by_label(self, label: str, timeout: int = 3):
        """
        Label metnine göre yanındaki/altındaki input alanını bul.
        Örnek: "TL" label'ının yanındaki EditText
        """
        print(f"[APPIUM] find_input_by_label: '{label}' aranıyor...")
        
        def escape_xpath(text):
            if "'" in text and '"' in text:
                parts = text.split("'")
                return "concat('" + "', \"'\", '".join(parts) + "')"
            elif "'" in text:
                return f'"{text}"'
            else:
                return f"'{text}'"
        
        escaped = escape_xpath(label)
        label_lower = label.lower()
        
        # Özel stratejiler - Label yanındaki input (ÖNCELİK SIRASINA GÖRE)
        strategies = [
            # 1. Following - Label'dan sonraki ilk EditText (EN ETKİLİ)
            f"//*[@text={escaped}]/following::android.widget.EditText[1]",
            f"//android.widget.TextView[@text={escaped}]/following::android.widget.EditText[1]",
            
            # 2. Aynı satırda/row'da - LinearLayout içinde
            f"//*[@text={escaped}]/..//android.widget.EditText",
            f"//*[@text={escaped}]/../..//android.widget.EditText[1]",
            f"//android.widget.LinearLayout[.//*[@text={escaped}]]//android.widget.EditText",
            
            # 3. Sibling
            f"//*[@text={escaped}]/following-sibling::android.widget.EditText[1]",
            f"//*[@text={escaped}]/following-sibling::*//android.widget.EditText[1]",
            
            # 4. Resource-id içinde label adı geçen
            f"//android.widget.EditText[contains(@resource-id, '{label_lower}')]",
            f"//android.widget.EditText[contains(@resource-id, '{label_lower.replace(' ', '_')}')]",
            
            # 5. Hint içeren
            f"//android.widget.EditText[contains(@hint, {escaped})]",
            f"//android.widget.EditText[@hint={escaped}]",
            
            # 6. Content-desc ile
            f"//*[@content-desc={escaped}]/following::android.widget.EditText[1]",
            f"//*[contains(@content-desc, {escaped})]/following::android.widget.EditText[1]",
            
            # 7. Herhangi bir input tipi
            f"//*[@text={escaped}]/following::*[@focusable='true'][@clickable='true'][1]",
            f"//*[@text={escaped}]/..//*[@class='android.widget.EditText']",
            
            # 8. Genel arama - TL/USD gibi kısa label'lar için
            f"//android.view.View[./android.widget.TextView[@text={escaped}]]//android.widget.EditText",
            f"//android.widget.FrameLayout[.//android.widget.TextView[@text={escaped}]]//android.widget.EditText",
        ]
        
        per_timeout = 0.3  # Her strateji için kısa timeout
        
        for i, xpath in enumerate(strategies):
            try:
                self._check_stop()
                element = WebDriverWait(self.driver, per_timeout).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, xpath))
                )
                if element:
                    print(f"[APPIUM] ✅ Input bulundu (strateji {i+1}): {xpath[:60]}...")
                    return element
            except:
                continue
        
        # Son çare: Tüm EditText'leri bul ve label'a en yakın olanı seç
        print(f"[APPIUM] Stratejiler başarısız, tüm EditText'ler aranıyor...")
        try:
            # Önce label'ı bul
            label_el = self.driver.find_element(AppiumBy.XPATH, f"//*[@text={escaped}]")
            label_loc = label_el.location
            
            # Tüm EditText'leri bul
            all_inputs = self.driver.find_elements(AppiumBy.XPATH, "//android.widget.EditText")
            
            if all_inputs:
                # Label'a en yakın olanı bul (Y koordinatına göre)
                closest = None
                min_dist = float('inf')
                
                for inp in all_inputs:
                    inp_loc = inp.location
                    # Y koordinatı yakın olanı tercih et (aynı satır)
                    y_diff = abs(inp_loc['y'] - label_loc['y'])
                    x_diff = inp_loc['x'] - label_loc['x']  # Sağda olmalı
                    
                    # Sağda ve aynı satırda olanı tercih et
                    if x_diff > 0 and y_diff < 100:
                        dist = y_diff + (x_diff / 10)  # X'e daha az ağırlık
                        if dist < min_dist:
                            min_dist = dist
                            closest = inp
                
                if closest:
                    print(f"[APPIUM] ✅ En yakın EditText bulundu (mesafe: {min_dist:.0f})")
                    return closest
        except Exception as e:
            print(f"[APPIUM] Yakınlık araması başarısız: {e}")
        
        print(f"[APPIUM] ❌ '{label}' için input bulunamadı")
        return None

    def scroll_to_find(self, target: str, max_scrolls: int = 2, direction: str = 'down'):
        """Element bulunana kadar scroll yap - MAX 2 DENEME"""
        for i in range(max_scrolls):
            try:
                self._check_stop()
                
                # Elementi ara - kısa timeout
                el = self.find_element_smart("auto", target, timeout=1, raise_error=False)
                if el:
                    return el
                
                # Driver aktif mi kontrol et
                try:
                    size = self.driver.get_window_size()
                    w, h = size['width'], size['height']
                except Exception as e:
                    print(f"[APPIUM] ⚠️ Driver sorunu, scroll atlanıyor: {e}")
                    return None
                
                if direction == 'down':
                    self.driver.swipe(w//2, int(h*0.7), w//2, int(h*0.3), 300)
                else:
                    self.driver.swipe(w//2, int(h*0.3), w//2, int(h*0.7), 300)
                
                time.sleep(0.3)
            except Exception as e:
                print(f"[APPIUM] Scroll hatası: {e}")
                return None
        
        return None

    def text_exists_on_screen(self, text: str) -> bool:
        """Ekranda metin var mı"""
        try:
            return text.lower() in self.driver.page_source.lower()
        except:
            return False

    def _tap_by_text_adb(self, text: str) -> bool:
        """
        ADB ile UI dump alıp metin koordinatını bulup tıkla.
        SADECE metin eşleşmesi - tahmin yok!
        """
        import xml.etree.ElementTree as ET
        import re
        
        xml_content = None
        
        # Yöntem 1: Appium page_source (daha hızlı)
        try:
            xml_content = self.driver.page_source
            print(f"[ADB] UI dump alındı (page_source)")
        except:
            pass
        
        # Yöntem 2: uiautomator dump
        if not xml_content:
            try:
                dump_cmd = [self.adb_path, "-s", self.current_device_id, "shell", "uiautomator", "dump", "/sdcard/ui.xml"]
                subprocess.run(dump_cmd, capture_output=True, timeout=5)
                
                cat_cmd = [self.adb_path, "-s", self.current_device_id, "shell", "cat", "/sdcard/ui.xml"]
                result = subprocess.run(cat_cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0 and result.stdout.strip():
                    xml_content = result.stdout
                    print(f"[ADB] UI dump alındı (uiautomator)")
            except Exception as e:
                print(f"[ADB] uiautomator dump başarısız: {e}")
        
        if not xml_content:
            print(f"[ADB] UI dump alınamadı")
            return False
        
        try:
            root = ET.fromstring(xml_content)
            
            # Metni ara (text ve content-desc'te)
            text_lower = text.lower().strip()
            text_nospace = text_lower.replace(' ', '')
            
            for node in root.iter():
                node_text = (node.get('text', '') or '').strip()
                content_desc = (node.get('content-desc', '') or '').strip()
                resource_id = (node.get('resource-id', '') or '').lower()
                
                # Eşleşme kontrolleri
                node_text_lower = node_text.lower()
                content_desc_lower = content_desc.lower()
                
                found = (
                    text_lower == node_text_lower or  # Tam eşleşme
                    text_lower == content_desc_lower or  # Tam eşleşme (desc)
                    text_lower in node_text_lower or  # İçerme
                    text_lower in content_desc_lower or  # İçerme (desc)
                    text_nospace == node_text_lower.replace(' ', '') or  # Boşluksuz
                    text_nospace == content_desc_lower.replace(' ', '') or
                    text_lower.replace(' ', '_') in resource_id or
                    text_nospace in resource_id
                )
                
                if found:
                    bounds = node.get('bounds', '')
                    if bounds:
                        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if match:
                            x1, y1, x2, y2 = map(int, match.groups())
                            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                            
                            tap_cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "tap", str(cx), str(cy)]
                            subprocess.run(tap_cmd, capture_output=True, timeout=3)
                            print(f"[ADB] ✅ '{text}' tıklandı ({cx}, {cy})")
                            return True
            
            # BULUNAMADI - Hata dön (tahmin yapma!)
            print(f"[ADB] ❌ '{text}' ekranda bulunamadı")
            return False
            
        except ET.ParseError as e:
            print(f"[ADB] XML parse hatası: {e}")
            return False
        except Exception as e:
            print(f"[ADB] Tıklama hatası: {e}")
            return False

    # ============ METİN YAZMA (3 KATMANLI GARANTİ) ============

    def type_text(self, text: str, element=None) -> bool:
        """
        Metin yazma - Platform'a göre yöntem seçer:
        - Android: ADB input text (en güvenilir)
        - iOS: Appium send_keys
        """
        success = False
        
        # iOS için direkt Appium kullan
        if self.current_platform == 'ios':
            try:
                if element:
                    element.send_keys(str(text))
                else:
                    self.driver.switch_to.active_element.send_keys(str(text))
                print(f"[APPIUM] ✅ iOS'ta yazıldı: {text}")
                return True
            except Exception as e:
                print(f"[APPIUM] iOS yazma hatası: {e}")
                return False
        
        # Android için ADB yöntemleri
        # Yöntem 1: ADB input text
        try:
            # Özel karakterleri escape et
            safe_text = str(text).replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
            safe_text = safe_text.replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
            safe_text = safe_text.replace("(", "\\(").replace(")", "\\)").replace("|", "\\|")
            
            cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "text", safe_text]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, capture_output=True, timeout=3, startupinfo=startupinfo)
            if result.returncode == 0:
                print(f"[ADB] ✅ Yazıldı: {text}")
                success = True
        except Exception as e:
            print(f"[ADB] input text hatası: {e}")
        
        # Yöntem 2: ADB broadcast (Türkçe ve özel karakterler için)
        if not success:
            try:
                # ADBKeyBoard kullanıyorsa
                cmd = [self.adb_path, "-s", self.current_device_id, "shell", 
                       "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text]
                
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                result = subprocess.run(cmd, capture_output=True, timeout=3, startupinfo=startupinfo)
                if result.returncode == 0:
                    print(f"[ADB] ✅ Broadcast ile yazıldı: {text}")
                    success = True
            except Exception as e:
                print(f"[ADB] broadcast hatası: {e}")
        
        # Yöntem 3: Appium send_keys
        if not success:
            try:
                if element:
                    element.send_keys(text)
                else:
                    self.driver.switch_to.active_element.send_keys(text)
                print(f"[APPIUM] ✅ send_keys ile yazıldı: {text}")
                success = True
            except Exception as e:
                print(f"[APPIUM] send_keys hatası: {e}")
        
        return success

    def clear_field(self, element=None):
        """Alanı temizle"""
        try:
            if element:
                element.clear()
            else:
                # Aktif elementi temizle
                active = self.driver.switch_to.active_element
                active.clear()
        except:
            # ADB ile temizle - CTRL+A, DEL
            try:
                cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "keyevent", "KEYCODE_CTRL_LEFT", "KEYCODE_A"]
                subprocess.run(cmd, capture_output=True, timeout=2)
                cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "keyevent", "KEYCODE_DEL"]
                subprocess.run(cmd, capture_output=True, timeout=2)
            except:
                pass

    def show_keyboard(self):
        """Klavyeyi göster"""
        try:
            cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "keyevent", "62"]
            subprocess.run(cmd, capture_output=True, timeout=2)
        except:
            pass

    def hide_keyboard(self):
        """Klavyeyi gizle"""
        try:
            self.driver.hide_keyboard()
        except:
            try:
                cmd = [self.adb_path, "-s", self.current_device_id, "shell", "input", "keyevent", "111"]
                subprocess.run(cmd, capture_output=True, timeout=2)
            except:
                pass

    # ============ EXECUTE ACTION ============

    def execute_action(self, step: AdvancedTestStep) -> Dict[str, Any]:
        """Adım çalıştır"""
        result = {"success": False, "message": ""}
        action = step.action.lower().strip()
        target = step.target
        value = step.value
        
        # Değişken değiştirme
        if target and target.startswith('@'):
            target = self.variables.get(target[1:], target)
        if value and value.startswith('@'):
            value = self.variables.get(value[1:], value)
        
        max_retries = 0  # RETRY YOK - Hızlı hata ver
        
        for attempt in range(max_retries + 1):
            try:
                self._check_stop()
                
                # ========== BEKLE ==========
                if action in ['wait', 'bekle']:
                    seconds = float(target or value or 1)
                    time.sleep(seconds)
                    result = {"success": True, "message": f"{seconds}s beklendi"}
                    break
                
                # ========== GERİ ==========
                elif action in ['back', 'geri']:
                    self.driver.back()
                    result = {"success": True, "message": "Geri gidildi"}
                    break
                
                # ========== ANA EKRAN ==========
                elif action in ['home', 'ana', 'ana_ekran']:
                    self.driver.press_keycode(3)
                    result = {"success": True, "message": "Ana ekrana gidildi"}
                    break
                
                # ========== SCROLL ==========
                elif action in ['scroll', 'kaydir', 'kaydır', 'swipe']:
                    direction = (target or value or 'down').lower()
                    size = self.driver.get_window_size()
                    w, h = size['width'], size['height']
                    
                    if direction in ['down', 'asagi', 'aşağı']:
                        self.driver.swipe(w//2, int(h*0.75), w//2, int(h*0.25), 400)
                    elif direction in ['up', 'yukari', 'yukarı']:
                        self.driver.swipe(w//2, int(h*0.25), w//2, int(h*0.75), 400)
                    elif direction in ['left', 'sol']:
                        self.driver.swipe(int(w*0.8), h//2, int(w*0.2), h//2, 400)
                    elif direction in ['right', 'sag', 'sağ']:
                        self.driver.swipe(int(w*0.2), h//2, int(w*0.8), h//2, 400)
                    
                    result = {"success": True, "message": f"Kaydırıldı: {direction}"}
                    break
                
                # ========== DEĞİŞKEN ATAMA ==========
                elif action in ['set', 'ata', 'kaydet']:
                    self.variables[target] = value
                    result = {"success": True, "message": f"@{target} = '{value}'"}
                    break
                
                # ========== IF EXISTS ==========
                elif action == 'if_exists':
                    exists = self.element_exists(target, timeout=3)
                    result = {"success": True, "message": f"'{target}' {'VAR' if exists else 'YOK'}", "condition_result": exists}
                    
                    # Varsa ve tıkla denildiyse tıkla
                    if exists and step.else_action in ['tap', 'tikla', 'tıkla', 'kapat', 'click']:
                        try:
                            el = self.find_element_smart("auto", target, timeout=2)
                            el.click()
                            result["message"] += " - tıklandı"
                        except:
                            pass
                    break
                
                # ========== IF TEXT ==========
                elif action == 'if_text':
                    exists = self.text_exists_on_screen(target)
                    result = {"success": True, "message": f"Metin '{target}' {'VAR' if exists else 'YOK'}", "condition_result": exists}
                    break
                
                # ========== SADECE YAZ (tıklamadan) ==========
                elif action in ['type_only', 'sadece_yaz', 'write']:
                    text_to_type = value or target
                    self.show_keyboard()
                    time.sleep(0.2)
                    success = self.type_text(text_to_type)
                    self.hide_keyboard()
                    
                    if success:
                        result = {"success": True, "message": f"'{text_to_type}' yazıldı"}
                    else:
                        result = {"success": False, "message": f"Yazılamadı: '{text_to_type}'"}
                    break
                
                # ========== YAZ (önce tıkla) ==========
                elif action in ['type', 'yaz', 'gir', 'doldur']:
                    text_to_type = value or target
                    element = None
                    
                    # Hedef varsa elementi bul ve tıkla
                    if target and value:
                        # ÖNCE label yanındaki input'u ara (en güvenilir yöntem)
                        print(f"[APPIUM] '{target}' için input aranıyor...")
                        element = self.find_input_by_label(target, timeout=2)
                        
                        # Bulamazsa normal arama dene
                        if not element:
                            print(f"[APPIUM] Label yanında input yok, direkt aranıyor...")
                            try:
                                element = self.find_element_smart(step.locator_type, target, index=step.index, timeout=2, raise_error=False)
                            except:
                                element = None
                        
                        if element:
                            print(f"[APPIUM] ✅ Input bulundu, tıklanıyor...")
                            element.click()
                            time.sleep(0.3)
                            # Alanı temizle
                            try:
                                element.clear()
                            except:
                                pass
                        else:
                            result = {"success": False, "message": f"'{target}' alanı bulunamadı"}
                            break
                    
                    # Klavyeyi aç
                    self.show_keyboard()
                    time.sleep(0.2)
                    
                    # Yaz
                    success = self.type_text(text_to_type, element)
                    
                    # Klavyeyi MUTLAKA kapat
                    time.sleep(0.2)
                    self.hide_keyboard()
                    time.sleep(0.2)
                    self.hide_keyboard()  # İkinci deneme
                    
                    if success:
                        msg = f"'{target}' alanına '{text_to_type}' yazıldı" if (target and value) else f"'{text_to_type}' yazıldı"
                        result = {"success": True, "message": msg}
                    else:
                        result = {"success": False, "message": f"Yazılamadı: '{text_to_type}'"}
                    break
                
                # ========== TIKLA ==========
                elif action in ['tap', 'tikla', 'tıkla', 'bas', 'click', 'dokun', 'sec', 'seç']:
                    el = None
                    
                    # Driver aktif mi kontrol et
                    try:
                        _ = self.driver.current_activity
                    except Exception as e:
                        print(f"[APPIUM] ⚠️ Driver çökmüş, ADB ile tıklama deneniyor...")
                        if self._tap_by_text_adb(target):
                            result = {"success": True, "message": f"'{target}' ADB ile tıklandı"}
                            break
                        else:
                            raise Exception(f"Driver çöktü ve ADB ile de bulunamadı: '{target}'")
                    
                    # Normal arama (ÇOK KISA timeout - 0.5 saniye)
                    try:
                        el = self.find_element_smart(step.locator_type, target, index=step.index, timeout=0.5, raise_error=False)
                    except:
                        el = None
                    
                    # Bulamazsa HEMEN ADB'ye geç
                    if not el:
                        print(f"[APPIUM] '{target}' bulunamadı, ADB deneniyor...")
                        if self._tap_by_text_adb(target):
                            result = {"success": True, "message": f"'{target}' ADB ile tıklandı"}
                            break
                        raise Exception(f"Element bulunamadı: '{target}'")
                    
                    el.click()
                    result = {"success": True, "message": f"'{target}' tıklandı"}
                    break
                
                # ========== ÇİFT TIKLA ==========
                elif action in ['double_tap', 'cift_tikla', 'çift_tıkla']:
                    el = self.find_element_smart(step.locator_type, target, index=step.index, timeout=step.timeout)
                    # Appium'da çift tıklama
                    from appium.webdriver.common.touch_action import TouchAction
                    TouchAction(self.driver).tap(el, count=2).perform()
                    result = {"success": True, "message": f"'{target}' çift tıklandı"}
                    break
                
                # ========== SCROLL İLE BUL VE TIKLA ==========
                elif action in ['scroll_tap', 'scroll_tikla', 'kaydır_tıkla']:
                    el = self.scroll_to_find(target, max_scrolls=5)
                    if not el:
                        raise Exception(f"Scroll ile bulunamadı: '{target}'")
                    el.click()
                    result = {"success": True, "message": f"Scroll ile '{target}' bulundu ve tıklandı"}
                    break
                
                # ========== UZUN BAS ==========
                elif action in ['long_press', 'uzun_bas', 'basili_tut']:
                    el = self.find_element_smart(step.locator_type, target, index=step.index, timeout=step.timeout)
                    from appium.webdriver.common.touch_action import TouchAction
                    duration = int(value) if value and value.isdigit() else 1000
                    TouchAction(self.driver).long_press(el, duration=duration).release().perform()
                    result = {"success": True, "message": f"'{target}' uzun basıldı"}
                    break
                
                # ========== DOĞRULA ==========
                elif action in ['verify', 'dogrula', 'doğrula', 'gor', 'gör', 'kontrol', 'bul']:
                    found = self.find_element_smart(step.locator_type, target, timeout=step.timeout, raise_error=False)
                    if found:
                        result = {"success": True, "message": f"'{target}' doğrulandı ✓"}
                    else:
                        # Sayfa kaynağında ara
                        if self.text_exists_on_screen(target):
                            result = {"success": True, "message": f"'{target}' ekranda bulundu ✓"}
                        else:
                            result = {"success": False, "message": f"'{target}' bulunamadı ✗"}
                    break
                
                # ========== METNİ KAYDET ==========
                elif action in ['get_text', 'metni_al', 'kaydet']:
                    el = self.find_element_smart(step.locator_type, target, timeout=step.timeout)
                    text = el.text or el.get_attribute("text") or ""
                    if value:
                        self.variables[value] = text
                    result = {"success": True, "message": f"Metin alındı: '{text}'"}
                    break
                
                # ========== ENTER TUŞU ==========
                elif action in ['enter', 'enter_bas']:
                    self.driver.press_keycode(66)
                    result = {"success": True, "message": "Enter basıldı"}
                    break
                
                # ========== TAB TUŞU ==========
                elif action in ['tab', 'tab_bas']:
                    self.driver.press_keycode(61)
                    result = {"success": True, "message": "Tab basıldı"}
                    break
                
                # ========== EKRAN GÖRÜNTÜSÜ ==========
                elif action in ['screenshot', 'ekran_goruntusu']:
                    filename = target or f"screenshot_{int(time.time())}.png"
                    self.driver.save_screenshot(filename)
                    result = {"success": True, "message": f"Ekran görüntüsü: {filename}"}
                    break
                
                else:
                    result = {"success": False, "message": f"Bilinmeyen aksiyon: {action}"}
                    break
                
            except Exception as e:
                if "STOPPED_BY_USER" in str(e):
                    raise e
                
                if step.optional:
                    result = {"success": True, "message": f"Opsiyonel atlandı: {e}"}
                else:
                    result = {"success": False, "message": str(e)}
                break
        
        return result

    # ============ DOĞAL DİL PARSER ============

    def parse_natural_language(self, text: str) -> List[AdvancedTestStep]:
        """
        Türkçe doğal dil parser - Gelişmiş
        
        Desteklenen formatlar:
        - "Giriş" butonuna tıkla
        - "Email" alanına "test@test.com" yaz
        - "121212" yaz  (aktif alana)
        - 2. "Ürün" elementine tıkla
        - son "Sil" butonuna bas
        - Eğer "Popup" varsa kapat
        - [opsiyonel] "Reklam" varsa tıkla
        - 3 saniye bekle
        - Aşağı kaydır
        - @kullanici = "admin"
        """
        commands = []
        if not text:
            return commands
        
        lines = text.strip().split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            
            # Boş satır veya yorum
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            
            # Satır numarasını temizle (1. 2. 3. vb)
            clean = re.sub(r'^\d+[\.\)\-\:]\s*', '', line)
            step = AdvancedTestStep(raw_line=line)
            matched = False
            
            # ========== OPSİYONEL KONTROL ==========
            if clean.lower().startswith('[opsiyonel]') or clean.lower().startswith('[optional]'):
                step.optional = True
                clean = re.sub(r'^\[(?:opsiyonel|optional)\]\s*', '', clean, flags=re.IGNORECASE)
            
            # ========== XPATH/ID İLE TIKLA ==========
            # xpath:"//android.widget.Button[@text='OK']" tıkla
            # id:"btn_confirm" tıkla
            xpath_match = re.search(r'^xpath:\s*["\']?([^"\']+)["\']?\s*(?:tıkla|tikla|bas|click|tap)$', clean, re.IGNORECASE)
            if xpath_match:
                step.action = 'tap'
                step.target = xpath_match.group(1).strip()
                step.locator_type = 'xpath'
                commands.append(step)
                continue
            
            id_match = re.search(r'^id:\s*["\']?([^"\']+)["\']?\s*(?:tıkla|tikla|bas|click|tap)$', clean, re.IGNORECASE)
            if id_match:
                step.action = 'tap'
                step.target = id_match.group(1).strip()
                step.locator_type = 'id'
                commands.append(step)
                continue
            
            # ========== XPATH/ID İLE YAZ ==========
            # xpath:"//android.widget.EditText[@resource-id='input']" alanına "test" yaz
            # id:"input_email" alanına "test@test.com" yaz
            xpath_type_match = re.search(r'^xpath:\s*["\']?([^"\']+)["\']?\s*(?:alanına|alanina)?\s*["\']([^"\']+)["\']\s*(?:yaz|gir)$', clean, re.IGNORECASE)
            if xpath_type_match:
                step.action = 'type'
                step.target = xpath_type_match.group(1).strip()
                step.value = xpath_type_match.group(2)
                step.locator_type = 'xpath'
                commands.append(step)
                continue
            
            id_type_match = re.search(r'^id:\s*["\']?([^"\']+)["\']?\s*(?:alanına|alanina)?\s*["\']([^"\']+)["\']\s*(?:yaz|gir)$', clean, re.IGNORECASE)
            if id_type_match:
                step.action = 'type'
                step.target = id_type_match.group(1).strip()
                step.value = id_type_match.group(2)
                step.locator_type = 'id'
                commands.append(step)
                continue
            
            # ========== XPATH/ID İLE DOĞRULA ==========
            # xpath:"//android.widget.TextView[@text='Success']" görünür
            xpath_verify_match = re.search(r'^xpath:\s*["\']?([^"\']+)["\']?\s*(?:görünür|gorunur|bulunur|var|exists)$', clean, re.IGNORECASE)
            if xpath_verify_match:
                step.action = 'verify'
                step.target = xpath_verify_match.group(1).strip()
                step.locator_type = 'xpath'
                commands.append(step)
                continue
            
            # ========== INDEX KONTROL ==========
            # "2. element" veya "ikinci element" formatı
            idx_match = re.match(r'^(\d+)\.\s*', clean)
            if idx_match:
                step.index = int(idx_match.group(1)) - 1
                clean = re.sub(r'^\d+\.\s*', '', clean)
            
            # Türkçe sıra sayıları
            ordinals = {
                'birinci': 0, 'ilk': 0, 'ilk ': 0,
                'ikinci': 1, '2.': 1,
                'üçüncü': 2, 'ucuncu': 2, '3.': 2,
                'dördüncü': 3, 'dorduncu': 3, '4.': 3,
                'beşinci': 4, 'besinci': 4, '5.': 4,
                'son': -1, 'sonuncu': -1
            }
            for word, idx in ordinals.items():
                if clean.lower().startswith(word + ' '):
                    step.index = idx
                    clean = clean[len(word):].strip()
                    break
            
            # ========== EĞER ... VARSA (IF/ELSE) ==========
            match = re.search(
                r'(?:eğer|eger|if)\s*["\']([^"\']+)["\']\s*(?:varsa|görünürse|gorunurse|bulunursa)\s*(?:(tıkla|tikla|kapat|click|bas))?(?:\s*yoksa\s*["\']([^"\']+)["\']\s*(?:tıkla|tikla|bas))?',
                clean, re.IGNORECASE
            )
            if match:
                step.action = 'if_exists'
                step.target = match.group(1)
                step.else_action = match.group(2) or 'tap'
                if match.group(3):
                    step.else_target = match.group(3)
                step.optional = True
                commands.append(step)
                continue
            
            # ========== ... VARSA TIKLA/KAPAT (kısa format) ==========
            match = re.search(r'["\']([^"\']+)["\']\s*(?:varsa|görünürse)\s*(tıkla|tikla|kapat|bas)', clean, re.IGNORECASE)
            if match:
                step.action = 'if_exists'
                step.target = match.group(1)
                step.else_action = 'tap'
                step.optional = True
                commands.append(step)
                continue
            
            # ========== BEKLE ==========
            match = re.search(r'(\d+(?:\.\d+)?)\s*(?:saniye|sn|s)\s*(?:bekle|beklenir)?', clean, re.IGNORECASE)
            if match:
                step.action = 'wait'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # ========== SADECE YAZ (tırnak içinde metin + yaz) ==========
            # "121212" yaz - aktif alana yaz
            match = re.search(r'^["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir)$', clean, re.IGNORECASE)
            if match:
                step.action = 'type_only'
                step.value = match.group(1)
                commands.append(step)
                continue
            
            # ========== ÖNCe TIKLA SONRA YAZ (iki satır) ==========
            # Satır 1: "Email" alanına tıkla
            # Satır 2: "test@test.com" yaz
            match = re.search(r'["\']([^"\']+)["\']\s*(?:alanına|alanina|kutusuna|yerine|inputuna|kısmına)?\s*(?:tıkla|tikla|bas|gir)', clean, re.IGNORECASE)
            if match and i < len(lines):
                next_line = lines[i].strip()
                next_clean = re.sub(r'^\d+[\.\)\-\:]\s*', '', next_line)
                # Sonraki satır sadece yazma mı?
                write_match = re.search(r'^["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir)$', next_clean, re.IGNORECASE)
                if write_match:
                    step.action = 'type'
                    step.target = match.group(1)
                    step.value = write_match.group(1)
                    commands.append(step)
                    i += 1  # Sonraki satırı atla
                    continue
            
            # ========== ALAN + YAZ (tek satır) ==========
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:alanına|alanina|kutusuna|yerine|inputuna|kısmına|bölümüne|bolumune)?\s*["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir|doldur|doldurulur)',
                clean, re.IGNORECASE
            )
            if match:
                step.action = 'type'
                step.target = match.group(1)
                step.value = match.group(2)
                commands.append(step)
                continue
            
            # ========== TIKLA ==========
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:butonuna|düğmesine|dugmesine|elementine|yazısına|yazisina|sekmesine|menüsüne|menusune|üzerine|uzerine|alanına|alanina|linkine|ikonuna)?\s*(?:tıkla|tikla|tıklanır|tiklanir|bas|basılır|basilir|click|seç|sec|dokun)',
                clean, re.IGNORECASE
            )
            if match:
                step.action = 'tap'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # Alternatif: tıkla "element"
            match = re.search(r'(?:tıkla|tikla|bas|dokun|seç)\s*["\']([^"\']+)["\']', clean, re.IGNORECASE)
            if match:
                step.action = 'tap'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # ========== DOĞRULA ==========
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:yazısını|yazisini|yazısı|yazisi|metni|metnini|elementi)?\s*(?:görülür|gorulur|görüntülenir|goruntulenir|görünür|gorunur|gör|gor|kontrol|doğrulanır|dogrulanir|doğrula|dogrula|var|bulunur|mevcut|görünmeli|gorunmeli|olmalı|olmali|bul)',
                clean, re.IGNORECASE
            )
            if match:
                step.action = 'verify'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # ========== SCROLL ==========
            if re.search(r'(?:aşağı|asagi|aşağıya|asagiya)\s*(?:kaydır|kaydir|scroll|git)', clean, re.IGNORECASE) or \
               re.search(r'(?:kaydır|kaydir|scroll)\s*(?:aşağı|asagi)', clean, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
            
            if re.search(r'(?:yukarı|yukari|yukarıya|yukariya)\s*(?:kaydır|kaydir|scroll|git)', clean, re.IGNORECASE) or \
               re.search(r'(?:kaydır|kaydir|scroll)\s*(?:yukarı|yukari)', clean, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'up'
                commands.append(step)
                continue
            
            # ========== SCROLL İLE BUL VE TIKLA ==========
            match = re.search(r'(?:scroll|kaydır|kaydir)\s*(?:ile|ederek)?\s*["\']([^"\']+)["\']\s*(?:bul|bulup)?\s*(?:ve\s*)?(?:tıkla|tikla|bas)?', clean, re.IGNORECASE)
            if match:
                step.action = 'scroll_tap'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # ========== GERİ ==========
            if re.search(r'geri\s*(?:git|dön|don|bas|tuşu|tusu)?', clean, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            # ========== ANA EKRAN ==========
            if re.search(r'ana\s*(?:ekran|sayfa|menü|menu)', clean, re.IGNORECASE):
                step.action = 'home'
                commands.append(step)
                continue
            
            # ========== DEĞİŞKEN ==========
            match = re.search(r'@(\w+)\s*(?:=|değişkenine|degiskenine)\s*["\']?([^"\']+)["\']?', clean)
            if match:
                step.action = 'set'
                step.target = match.group(1)
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            # ========== ENTER ==========
            if re.search(r'enter\s*(?:bas|tuşuna|tusuna)?', clean, re.IGNORECASE):
                step.action = 'enter'
                commands.append(step)
                continue
            
            # Eşleşme bulunamadı
            if not matched:
                print(f"[PARSER] ⚠️ Anlaşılamadı: {clean}")
        
        return commands

    # ============ TEST ÇALIŞTIR ============

    def run_test(self, device, steps: List[AdvancedTestStep], app_package: str = "",
                 app_activity: str = "", stop_on_fail: bool = True,
                 restart_app: bool = True, test_id: str = "") -> Dict[str, Any]:
        """Test çalıştır"""
        
        device_id = device.device_id if hasattr(device, 'device_id') else str(device)
        
        print(f"\n{'='*60}")
        print(f"[TEST] BAŞLIYOR - {len(steps)} adım - {device_id}")
        print(f"{'='*60}\n")
        
        if EMU_SERVICE:
            emulator_service.clear_logs(device_id)
            session = emulator_service.get_session(device_id)
            if session:
                session.stop_requested = False
        
        results = []
        start_time = time.time()
        self.variables = {}
        
        try:
            self._set_state("running", 0, len(steps))
            self.create_driver(device)
            
            if restart_app and app_package:
                self.restart_application(app_package)
            
            for i, step in enumerate(steps):
                self._check_stop()
                
                step_num = i + 1
                self._log(step_num, step.action, step.target, "running")
                self._set_state("running", step_num, len(steps))
                
                # Aksiyonu çalıştır
                res = self.execute_action(step)
                
                # IF/ELSE sonuç işleme
                if step.action in ['if_exists', 'if_text']:
                    condition_result = res.get("condition_result", False)
                    if not condition_result and step.else_target:
                        else_step = AdvancedTestStep(action=step.else_action or 'tap', target=step.else_target)
                        self.execute_action(else_step)
                
                status = "success" if res["success"] else "failed"
                self._log(step_num, step.action, step.target, status, res["message"])
                
                results.append(StepResult(
                    step_number=step_num,
                    action=step.action,
                    success=res["success"],
                    message=res["message"]
                ))
                
                print(f"[TEST] {step_num}/{len(steps)}: {step.action} -> {status}")
                
                if not res["success"] and stop_on_fail and not step.optional:
                    self._set_state("failed", step_num, len(steps))
                    break
                
                time.sleep(0.1)  # Adımlar arası kısa bekleme
            
            duration = round(time.time() - start_time, 2)
            failed_count = sum(1 for r in results if not r.success)
            
            if failed_count == 0:
                self._set_state("success", len(results), len(steps))
                print(f"\n[TEST] ✅ BAŞARILI! ({duration}s)")
            else:
                self._set_state("failed", len(results), len(steps))
                print(f"\n[TEST] ❌ {failed_count} HATA ({duration}s)")
            
            return {
                "test_id": test_id,
                "success": failed_count == 0,
                "message": "OK" if failed_count == 0 else f"{failed_count} hata",
                "results": results,
                "duration": duration
            }
            
        except Exception as e:
            msg = str(e)
            if msg == "STOPPED_BY_USER":
                print("\n[TEST] 🛑 KULLANICI TARAFINDAN DURDURULDU")
                self._set_state("stopped", len(results), len(steps))
                return {"test_id": test_id, "success": False, "message": "Durduruldu", "results": results, "duration": round(time.time() - start_time, 2)}
            
            print(f"\n[TEST] ❌ KRİTİK HATA: {e}")
            self._set_state("failed")
            import traceback
            traceback.print_exc()
            return {"test_id": test_id, "success": False, "message": str(e), "results": results, "duration": round(time.time() - start_time, 2)}
        
        finally:
            self.close_driver()


appium_service = AppiumService()