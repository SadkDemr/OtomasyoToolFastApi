"""
Appium Service - ADVANCED v5.4 (FLAG FIX)
=========================================
FIX: Test başlarken eski 'stop_requested' bayrağı temizleniyor.
"""
import sys
import os
import time
import re
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
    print("[APPIUM] Appium kütüphanesi eksik!")


@dataclass
class AdvancedTestStep:
    action: str = ""
    target: str = ""
    value: str = ""
    locator_type: str = "auto"
    index: int = 0
    timeout: int = 7
    optional: bool = False
    # IF/ELSE için gerekli alanlar
    condition: str = ""
    else_action: str = ""
    else_target: str = ""


class AppiumService:
    def __init__(self):
        self.driver = None
        self.current_device_id = None
        self.variables: Dict[str, str] = {}

    def is_available(self) -> bool:
        return APPIUM_AVAILABLE

    def _log(self, step_num: int, action: str, target: str, status: str, message: str = ""):
        print(f"[TEST] Adım {step_num}: {action} '{target}' -> {status}")
        if EMU_SERVICE and self.current_device_id:
            emulator_service.add_log(self.current_device_id, step_num, action, target, status, message)

    def _set_state(self, state: str, current: int = 0, total: int = 0):
        if EMU_SERVICE and self.current_device_id:
            state_map = {"running": TestRunState.RUNNING, "success": TestRunState.SUCCESS, "failed": TestRunState.FAILED, "stopped": TestRunState.STOPPED}
            emulator_service.set_test_state(self.current_device_id, state_map.get(state, TestRunState.IDLE), current, total)

    def _is_stopped(self) -> bool:
        if EMU_SERVICE and self.current_device_id:
            session = emulator_service.get_session(self.current_device_id)
            if session and session.stop_requested:
                return True
        return False

    def create_driver(self, device):
        device_id = device.device_id if hasattr(device, 'device_id') else str(device)
        appium_url = getattr(device, 'appium_url', None) or "http://localhost:4723"
        
        print(f"[APPIUM] Driver: {device_id} @ {appium_url}")
        self.current_device_id = device_id
        
        options = UiAutomator2Options()
        options.platform_name = 'Android'
        options.udid = device_id
        options.automation_name = 'UiAutomator2'
        options.no_reset = True
        options.new_command_timeout = 120
        options.set_capability('appium:autoGrantPermissions', True)
        options.set_capability('appium:ignoreHiddenApiPolicyError', True)
        
        # KLAVYE AYARLARI
        options.set_capability('unicodeKeyboard', False)
        options.set_capability('resetKeyboard', False)
        
        self.driver = appium_webdriver.Remote(appium_url, options=options)
        self.driver.implicitly_wait(2)
        print(f"[APPIUM] ✅ Driver hazır")
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
            self.driver.terminate_app(package)
            time.sleep(1)
            self.driver.activate_app(package)
            time.sleep(2)
        except Exception as e:
            print(f"[APPIUM] Restart hatası: {e}")

    def find_element_smart(self, locator_type: str, value: str, index: int = 0, timeout: int = 7):
        """Akıllı element bulma"""
        strategies = []
        
        if locator_type == 'id':
            strategies.append((AppiumBy.ID, value))
        elif locator_type == 'xpath':
            strategies.append((AppiumBy.XPATH, value))
        else:
            strategies = [
                (AppiumBy.XPATH, f"//*[@text='{value}']"),
                (AppiumBy.XPATH, f"//*[contains(@text, '{value}')]"),
                (AppiumBy.XPATH, f"//*[@content-desc='{value}']"),
                (AppiumBy.XPATH, f"//*[contains(@content-desc, '{value}')]"),
                (AppiumBy.ACCESSIBILITY_ID, value),
                (AppiumBy.XPATH, f"//*[contains(@resource-id, '{value}')]"),
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@hint, '{value}')]"),
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@text, '{value}')]"),
                (AppiumBy.XPATH, f"//android.widget.Button[contains(@text, '{value}')]"),
                (AppiumBy.XPATH, f"//android.widget.TextView[contains(@text, '{value}')]"),
                (AppiumBy.XPATH, f"//*[contains(@text, '{value}')]/following-sibling::android.widget.EditText"),
                (AppiumBy.XPATH, f"//*[contains(@text, '{value}')]/parent::*/android.widget.EditText"),
            ]
        
        per_timeout = min(1.5, timeout / len(strategies))
        
        for by_type, by_value in strategies:
            try:
                if index != 0:
                    elements = WebDriverWait(self.driver, per_timeout).until(lambda d: d.find_elements(by_type, by_value))
                    if elements:
                        return elements[index] if index < len(elements) else elements[-1]
                else:
                    return WebDriverWait(self.driver, per_timeout).until(EC.presence_of_element_located((by_type, by_value)))
            except:
                continue
        
        raise Exception(f"Element bulunamadı: '{value}'")

    def element_exists(self, target: str, timeout: float = 2.0) -> bool:
        try:
            self.find_element_smart("auto", target, timeout=timeout)
            return True
        except:
            return False

    def execute_action(self, step: AdvancedTestStep) -> Dict[str, Any]:
        result = {"success": False, "message": ""}
        action = step.action.lower().strip()
        target = step.target
        value = step.value
        
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # BEKLE
                if action in ['wait', 'bekle']:
                    seconds = float(target or value or 1)
                    time.sleep(seconds)
                    result = {"success": True, "message": f"{seconds}s beklendi"}
                    break
                
                # SCROLL
                elif action in ['scroll', 'kaydir', 'swipe']:
                    direction = (target or value or 'down').lower()
                    size = self.driver.get_window_size()
                    if direction in ['down', 'asagi', 'aşağı']:
                        self.driver.swipe(size['width']//2, int(size['height']*0.7), size['width']//2, int(size['height']*0.3), 500)
                    elif direction in ['up', 'yukari', 'yukarı']:
                        self.driver.swipe(size['width']//2, int(size['height']*0.3), size['width']//2, int(size['height']*0.7), 500)
                    result = {"success": True, "message": f"Kaydırıldı: {direction}"}
                    break
                
                # GERİ
                elif action in ['back', 'geri']:
                    self.driver.back()
                    result = {"success": True, "message": "Geri gidildi"}
                    break
                
                # ANA EKRAN
                elif action in ['home', 'ana']:
                    self.driver.press_keycode(3)
                    result = {"success": True, "message": "Ana ekrana gidildi"}
                    break
                
                # IF EXISTS
                elif action == 'if_exists':
                    exists = self.element_exists(target, timeout=3)
                    if exists:
                        try:
                            el = self.find_element_smart("auto", target, timeout=2)
                            el.click()
                            result = {"success": True, "message": f"'{target}' bulundu ve tıklandı"}
                        except:
                            result = {"success": True, "message": f"'{target}' var ama tıklanamadı"}
                    else:
                        result = {"success": True, "message": f"'{target}' bulunamadı, atlandı"}
                    break
                
                # SADECE YAZ (Hedefsiz)
                elif action in ['type_only', 'sadece_yaz', 'write']:
                    text_to_type = target or value
                    try:
                        active = self.driver.switch_to.active_element
                        active.send_keys(text_to_type)
                        print(f"[APPIUM] Aktif alana yazıldı: {text_to_type}")
                    except Exception as e:
                        print(f"[APPIUM] Aktif alan hatası: {e}")
                    result = {"success": True, "message": f"'{text_to_type}' yazıldı"}
                    break
                
                # ELEMENT GEREKTİREN İŞLEMLER
                else:
                    el = self.find_element_smart(step.locator_type, target, index=step.index, timeout=step.timeout)
                    
                    if action in ['tap', 'tikla', 'tıkla', 'bas', 'click', 'dokun']:
                        el.click()
                        result = {"success": True, "message": f"'{target}' tıklandı"}
                    
                    elif action in ['type', 'yaz', 'gir', 'doldur']:
                        el.click()
                        time.sleep(0.5) 
                        try: el.clear()
                        except: pass
                        try: el.click()
                        except: pass
                        el.send_keys(value)
                        try: self.driver.hide_keyboard()
                        except: pass
                        result = {"success": True, "message": f"'{value}' yazıldı"}
                    
                    elif action in ['verify', 'dogrula', 'doğrula', 'kontrol', 'gor', 'gör', 'bul']:
                        result = {"success": True, "message": f"'{target}' görüldü ✓"}
                    
                    else:
                        result = {"success": False, "message": f"Bilinmeyen: {action}"}
                    
                    break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    if step.optional:
                        result = {"success": True, "message": f"Opsiyonel atlandı: {e}"}
                    else:
                        result = {"success": False, "message": str(e)}
        
        return result

    def parse_natural_language(self, text: str) -> List[AdvancedTestStep]:
        """Türkçe doğal dil parser"""
        commands = []
        if not text:
            return commands
        
        lines = text.strip().split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            
            clean = re.sub(r'^\d+[\.\)\-\:]\s*', '', line)
            step = AdvancedTestStep()
            
            # Opsiyonel ve Index kontrolleri
            if clean.lower().startswith('[opsiyonel]') or clean.lower().startswith('[optional]'):
                step.optional = True
                clean = re.sub(r'^\[(?:opsiyonel|optional)\]\s*', '', clean, flags=re.IGNORECASE)
            
            idx_match = re.match(r'^(\d+)\.\s*["\']', clean)
            if idx_match:
                step.index = int(idx_match.group(1)) - 1
                clean = re.sub(r'^\d+\.\s*', '', clean)
            
            ordinals = {'birinci': 0, 'ilk': 0, 'ikinci': 1, 'üçüncü': 2, 'son': -1}
            for word, idx in ordinals.items():
                if clean.lower().startswith(word):
                    step.index = idx
                    clean = re.sub(rf'^{word}\s*', '', clean, flags=re.IGNORECASE)
                    break
            
            matched = False
            
            # PARSER KURALLARI
            match = re.search(r'(?:eğer|eger|if)?\s*["\']([^"\']+)["\']\s*(?:varsa|görünürse)\s*(?:tıkla|tikla|kapat|bas)', clean, re.IGNORECASE)
            if match:
                step.action = 'if_exists'; step.target = match.group(1); step.optional = True
                commands.append(step); matched = True; continue
            
            match = re.search(r'(\d+(?:\.\d+)?)\s*(?:saniye|sn|s)\s*(?:bekle|beklenir)?', clean, re.IGNORECASE)
            if match:
                step.action = 'wait'; step.target = match.group(1)
                commands.append(step); matched = True; continue
            
            match = re.search(r'^["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir)$', clean, re.IGNORECASE)
            if match:
                step.action = 'type_only'; step.target = match.group(1)
                commands.append(step); matched = True; continue
            
            match = re.search(r'["\']([^"\']+)["\']\s*(?:alanına|alanina|kutusuna|yerine|inputuna)?\s*(?:tıkla|tikla|bas|dokun|gir)', clean, re.IGNORECASE)
            if match and i < len(lines):
                next_line = lines[i].strip()
                next_clean = re.sub(r'^\d+[\.\)\-\:]\s*', '', next_line)
                write_match = re.search(r'^["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir)$', next_clean, re.IGNORECASE)
                if write_match:
                    step.action = 'type'; step.target = match.group(1); step.value = write_match.group(1)
                    commands.append(step); i += 1; matched = True; continue
            
            match = re.search(r'["\']([^"\']+)["\']\s*(?:alanına|alanina|kutusuna|yerine|inputuna|kısmına|bölümüne)?\s*["\']([^"\']+)["\']\s*(?:yaz|yazılır|gir|girilir|doldur)', clean, re.IGNORECASE)
            if match:
                step.action = 'type'; step.target = match.group(1); step.value = match.group(2)
                commands.append(step); matched = True; continue
            
            match = re.search(r'["\']([^"\']+)["\']\s*(?:butonuna|düğmesine|elementine|yazısına|sekmesine|üzerine|alanına|alanina)?\s*(?:tıkla|tikla|tıklanır|bas|basılır|click|dokun|seç)', clean, re.IGNORECASE)
            if match:
                step.action = 'tap'; step.target = match.group(1)
                commands.append(step); matched = True; continue
            
            match = re.search(r'(?:tıkla|tikla|bas|dokun)\s*["\']([^"\']+)["\']', clean, re.IGNORECASE)
            if match:
                step.action = 'tap'; step.target = match.group(1)
                commands.append(step); matched = True; continue
            
            match = re.search(r'["\']([^"\']+)["\']\s*(?:yazısı|metni|elementi)?\s*(?:görülür|gorulur|gör|gor|kontrol|doğrulanır|var|bulunur|mevcut|görünmeli|olmalı|bul)', clean, re.IGNORECASE)
            if match:
                step.action = 'verify'; step.target = match.group(1)
                commands.append(step); matched = True; continue
            
            if re.search(r'(?:ekran|sayfa)?\s*(?:aşağı|asagi)\s*(?:kaydır|kaydir|scroll)', clean, re.IGNORECASE):
                step.action = 'scroll'; step.target = 'down'; commands.append(step); matched = True; continue
            
            if re.search(r'(?:ekran|sayfa)?\s*(?:yukarı|yukari)\s*(?:kaydır|kaydir|scroll)', clean, re.IGNORECASE):
                step.action = 'scroll'; step.target = 'up'; commands.append(step); matched = True; continue
            
            if re.search(r'geri\s*(?:git|dön|bas)?', clean, re.IGNORECASE):
                step.action = 'back'; commands.append(step); matched = True; continue
            
            if not matched:
                print(f"[PARSE] ⚠️ Anlaşılamadı: {clean}")
        
        return commands

    def run_test(self, device, steps: List[AdvancedTestStep], app_package: str = "", 
                 app_activity: str = "", stop_on_fail: bool = True,
                 restart_app: bool = True, test_id: str = "") -> Dict[str, Any]:
        
        device_id = device.device_id if hasattr(device, 'device_id') else str(device)
        
        print(f"\n{'='*50}")
        print(f"[TEST] BAŞLIYOR - {len(steps)} adım")
        print(f"{'='*50}\n")
        
        if EMU_SERVICE:
            emulator_service.clear_logs(device_id)
            emulator_service.ensure_session(device_id, 1)
            
            # --- FIX: ESKİ DURDURMA EMRİNİ TEMİZLE ---
            session = emulator_service.get_session(device_id)
            if session:
                session.stop_requested = False
            # ----------------------------------------
        
        results = []
        start_time = time.time()
        self.variables = {}
        stopped_by_user = False

        try:
            self._set_state("running", 0, len(steps))
            self.create_driver(device)
            
            if restart_app and app_package:
                self.restart_application(app_package)
            
            for i, step in enumerate(steps):
                if self._is_stopped():
                    print("[TEST] 🛑 Kullanıcı tarafından durduruldu!")
                    stopped_by_user = True
                    break
                
                step_num = i + 1
                self._log(step_num, step.action, step.target, "running")
                self._set_state("running", step_num, len(steps))
                
                res = self.execute_action(step)
                
                status = "success" if res["success"] else "failed"
                self._log(step_num, step.action, step.target, status, res["message"])
                
                results.append(StepResult(step_number=step_num, action=step.action, success=res["success"], message=res["message"]))
                
                print(f"[TEST] {step_num}/{len(steps)}: {step.action} -> {status}")
                
                if not res["success"] and stop_on_fail and not step.optional:
                    self._set_state("failed", step_num, len(steps))
                    break
                
                time.sleep(0.3)
            
            # DURDURMA SONUCU
            if stopped_by_user:
                self._set_state("stopped", len(results), len(steps))
                return {
                    "test_id": test_id,
                    "success": False,
                    "message": "Stopped by user",
                    "results": results,
                    "duration": round(time.time() - start_time, 2)
                }

            failed = sum(1 for r in results if not r.success)
            duration = round(time.time() - start_time, 2)
            
            if failed == 0:
                self._set_state("success", len(results), len(steps))
                print(f"\n[TEST] ✅ BAŞARILI! ({duration}s)")
            else:
                self._set_state("failed", len(results), len(steps))
                print(f"\n[TEST] ❌ {failed} HATA ({duration}s)")
            
            return {"test_id": test_id, "success": failed == 0, "message": "OK" if failed == 0 else f"{failed} hata", "results": results, "duration": duration}
            
        except Exception as e:
            print(f"\n[TEST] ❌ HATA: {e}")
            self._set_state("failed")
            import traceback
            traceback.print_exc()
            return {"test_id": test_id, "success": False, "message": str(e), "results": results, "duration": round(time.time() - start_time, 2)}
        finally:
            self.close_driver()


appium_service = AppiumService()