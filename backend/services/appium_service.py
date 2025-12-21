"""
Appium Service - CLEAN VERSION
PIL importu kaldırıldı.
Tuple hatası (virgül eksikliği) giderildi.
Yazma (Type) işlemi güçlendirildi.
"""
import sys
import os
import time
import re
from typing import List, Dict, Any
from models.schemas import TestStep, StepResult

# Emülatör servisi (Loglar için)
from services.emulator_service import emulator_service, TestRunState
EMU_SERVICE = True

try:
    from appium import webdriver as appium_webdriver
    from appium.options.android import UiAutomator2Options
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
    APPIUM_AVAILABLE = True
except ImportError:
    APPIUM_AVAILABLE = False
    print("!!! APPIUM KUTUPHANESI EKSIK !!!")


class AppiumService:
    def __init__(self):
        self.driver = None
        self.current_device_id = None

    def is_available(self) -> bool: return APPIUM_AVAILABLE

    def _log(self, step_num, action, target, status, message=""):
        print(f"[TEST-LOG] Adim {step_num}: {action} -> {status} ({message})")
        if self.current_device_id:
            emulator_service.add_log(
                self.current_device_id, step_num, action, target, status, message)

    def _set_state(self, state, current=0, total=0):
        if self.current_device_id:
            s_map = {"running": TestRunState.RUNNING, "success": TestRunState.SUCCESS,
                "failed": TestRunState.FAILED, "stopped": TestRunState.STOPPED}
            emulator_service.set_test_state(self.current_device_id, s_map.get(
                state, TestRunState.IDLE), current, total)

    def _is_stopped(self):
        if self.current_device_id:
            s = emulator_service.get_session(self.current_device_id)
            if s and s.stop_requested: return True
        return False

    def create_driver(self, device):
        print(f"[DEBUG] Driver olusturuluyor: {device.device_id}")
        self.current_device_id = device.device_id
        url = device.appium_url or "http://localhost:4723"

        options = UiAutomator2Options()
        options.platform_name = 'Android'
        options.udid = device.device_id
        options.automation_name = 'UiAutomator2'
        options.no_reset = True
        options.new_command_timeout = 60

        try:
            self.driver = appium_webdriver.Remote(url, options=options)
            self.driver.implicitly_wait(2)
        except Exception as e:
            print(f"[DEBUG] Driver HATASI: {e}")
            raise e
        return self.driver

    def close_driver(self):
        if self.driver:
            try: self.driver.quit()
            except: pass
            self.driver = None
        self.current_device_id = None

    def restart_application(self, package):
        try:
            self.driver.terminate_app(package)
            time.sleep(1)
            self.driver.activate_app(package)
            time.sleep(2)
        except Exception as e:
            print(f"[DEBUG] Restart hatasi: {e}")

    def find_element_smart(self, locator_type, value):
        strategies = []
        if locator_type == 'id': strategies.append((AppiumBy.ID, value))
        elif locator_type == 'xpath': strategies.append((AppiumBy.XPATH, value))
        else:  # Auto detection
            strategies = [
                (AppiumBy.XPATH, f"//*[@text='{value}']"),
                (AppiumBy.XPATH, f"//*[contains(@text, '{value}')]"),
                (AppiumBy.XPATH, f"//*[@resource-id='{value}']"),
                (AppiumBy.XPATH, f"//*[@text='{value}']/following-sibling::android.widget.EditText"),
                (AppiumBy.XPATH, f"//*[@text='{value}']/parent::*/android.widget.EditText"),
                # --- DUZELTME: Buraya virgül eklendi ---
                (AppiumBy.XPATH, f"//*[contains(@text, '{value}')]/following-sibling::android.widget.EditText"),
                (AppiumBy.ACCESSIBILITY_ID, value),
                (AppiumBy.XPATH, f"//android.widget.EditText[contains(@text, '{value}')]")
            ]

        for by, val in strategies:
            try:
                # 4 saniye bekle
                el = WebDriverWait(self.driver, 4).until(
                    EC.presence_of_element_located((by, val)))
                return el
            except: continue
        raise Exception(f"Element bulunamadi: '{value}'")

    # --- RETRY MEKANİZMASI ---
    def execute_action(self, action, target, value, locator_type="auto"):
        res = {"success": False, "message": ""}
        action = action.lower()

        # 3 kereye kadar tekrar dene (StaleElementReferenceException için)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if action in ['wait', 'bekle']:
                    t = float(target or value or 1)
                    time.sleep(t)
                    res = {"success": True, "message": f"{t}s beklendi"}
                    break

                # Önce elementi bul
                el = None
                if action not in ['wait', 'bekle']:
                    el = self.find_element_smart(locator_type, target)

                # Aksiyonu yap
                if action in ['tap', 'tikla', 'bas']:
                    el.click()
                    res = {"success": True, "message": "Tiklandi"}

                elif action in ['type', 'yaz', 'gir']:
                    # --- YAZMA FIX (Click -> Clear -> Click -> Type) ---
                    el.click()
                    time.sleep(0.5) 
                    
                    try: el.clear()
                    except: pass
                    
                    try: el.click()
                    except: pass
                    
                    el.send_keys(str(value))
                    
                    try: self.driver.hide_keyboard()
                    except: pass
                    res = {"success": True, "message": f"'{value}' yazildi"}

                elif action in ['verify', 'dogrula']:
                    res = {"success": True, "message": "Dogrulandi"}

                else:
                    res = {"success": False,
                        "message": f"Bilinmeyen islem: {action}"}

                # Hata almadık, döngüden çık
                break

            except (StaleElementReferenceException, NoSuchElementException) as e:
                # Bayat element hatası ise, biraz bekle ve tekrar dene
                if attempt < max_retries - 1:
                    print(
                        f"[DEBUG] Bayat element ({action}), tekrar deneniyor... ({attempt+1})")
                    time.sleep(1)
                    continue
                else:
                    res = {"success": False, "message": str(e)}
            except Exception as e:
                res = {"success": False, "message": str(e)}
                break  # Diğer hatalarda tekrar deneme

        return res


    def parse_natural_language(self, text: str) -> List[TestStep]:
        commands = []
        lines = text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'): continue

            # Satır başındaki maddeleri (1. veya -) temizle
            clean_line = re.sub(r'^\d+[\.\)\-]\s*', '', line)

            step = TestStep()
            matched = False

            # 1. YAZMA KOMUTLARI
            # Örnek: "Şifre" alanına "1234" yaz
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:alanina|kutusuna|inputuna|bölümüne)?\s*["\']([^"\']+)["\']\s*(?:yaz|gir|doldur)', clean_line, re.IGNORECASE)
            if match:
                step.action = 'type'
                step.target = match.group(1)  # Hedef (Şifre Giriniz)
                step.value = match.group(2)  # Değer (121212)
                commands.append(step); matched = True

            # 2. DOĞRULAMA KOMUTLARI
            # Örnek: "Başarılı" metnini kontrol et
            if not matched:
                match = re.search(
                    r'["\']([^"\']+)["\']\s*(?:yazisini|metnini|yazısını)?\s*(?:gör|kontrol et|dogrula|doğrula|var mi)', clean_line, re.IGNORECASE)
                if match:
                    step.action = 'verify'
                    step.target = match.group(1)
                    commands.append(step); matched = True

            # 3. TIKLAMA KOMUTLARI
            # Örnek: "Giriş Yap" butonuna tıkla
            if not matched:
                match = re.search(
                    r'["\']([^"\']+)["\']\s*(?:butonuna|tusuna|elementine|linkine)?\s*(?:tikla|tıkla|bas)', clean_line, re.IGNORECASE)
                if match:
                    step.action = 'tap'
                    step.target = match.group(1)
                    commands.append(step); matched = True

            # 4. BEKLEME KOMUTLARI
            if not matched:
                match = re.search(r'(\d+)\s*(?:sn|saniye|san|s)',
                                  clean_line, re.IGNORECASE)
                if match:
                    step.action = 'wait'
                    step.target = match.group(1)
                    commands.append(step); matched = True

            if not matched:
                print(f"[UYARI] Parse edilemedi: {clean_line}")

        return commands

    def run_test(self, device, steps, app_package="", app_activity="", stop_on_fail=True, restart_app=True, test_id=""):
        print(f"[DEBUG] TEST BASLIYOR... ID: {test_id}")
        if EMU_SERVICE: 
            emulator_service.clear_logs(device.device_id)
            emulator_service.ensure_session(device.device_id, 1)

        try:
            self._set_state("running", 0, len(steps))
            self.create_driver(device)
            
            if restart_app and app_package:
                self.restart_application(app_package)
            
            results = []
            for i, step in enumerate(steps):
                if self._is_stopped(): break
                
                self._log(i+1, step.action, step.target, "running", "...")
                self._set_state("running", i+1, len(steps))
                
                res = self.execute_action(step.action, step.target, step.value)
                
                status = "success" if res["success"] else "failed"
                self._log(i+1, step.action, step.target, status, res["message"])
                
                results.append(StepResult(step_number=i+1, action=step.action, success=res["success"], message=res["message"]))
                
                if not res["success"] and stop_on_fail: 
                    self._set_state("failed", i+1, len(steps)); break
            
            failed = sum(1 for r in results if not r.success)
            self._set_state("success" if failed==0 else "failed", len(results), len(steps))
            return {"test_id": test_id, "success": failed==0, "results": results}
            
        except Exception as e:
            print(f"[DEBUG] TEST KRITIK HATA: {e}")
            self._set_state("failed")
            return {"test_id": test_id, "success": False, "message": str(e)}
        finally:
            self.close_driver()

# BU SATIR ÖNEMLİ (Tekil kullanım için)
appium_service = AppiumService()