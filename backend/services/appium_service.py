"""
Appium Service - Mobil Test Otomasyonu
Canli log destegi ile
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import re
import uuid
from typing import List, Dict, Any

from models.schemas import TestStep, StepResult
from models.db_models import Device

# Emulator service - canli log icin
try:
    from services.emulator_service import emulator_service, TestRunState
    EMU_SERVICE = True
except:
    emulator_service = None
    EMU_SERVICE = False

try:
    from appium import webdriver as appium_webdriver
    from appium.options.android import UiAutomator2Options
    from appium.options.ios import XCUITestOptions
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    APPIUM_AVAILABLE = True
except ImportError:
    APPIUM_AVAILABLE = False


class AppiumService:
    def __init__(self):
        self.driver = None
        self.current_device_id = None
    
    def is_available(self) -> bool:
        return APPIUM_AVAILABLE
    
    def _log(self, step_num: int, action: str, target: str, status: str, message: str = ""):
        """Emulator service'e log ekle (canli)"""
        if EMU_SERVICE and emulator_service and self.current_device_id:
            emulator_service.add_log(self.current_device_id, step_num, action, target, status, message)
    
    def _set_state(self, state: str, current_step: int = 0, total_steps: int = 0):
        """Test durumunu guncelle"""
        if EMU_SERVICE and emulator_service and self.current_device_id:
            state_map = {
                "running": TestRunState.RUNNING,
                "success": TestRunState.SUCCESS,
                "failed": TestRunState.FAILED,
                "stopped": TestRunState.STOPPED,
                "idle": TestRunState.IDLE
            }
            emulator_service.set_test_state(
                self.current_device_id, 
                state_map.get(state, TestRunState.IDLE), 
                current_step, 
                total_steps
            )
    
    def _is_stopped(self) -> bool:
        """Test durduruldu mu kontrol et"""
        if EMU_SERVICE and emulator_service and self.current_device_id:
            session = emulator_service.get_session(self.current_device_id)
            if session and session.stop_requested:
                return True
        return False
    
    def create_driver(self, device: Device, app_package: str = "", app_activity: str = ""):
        if not APPIUM_AVAILABLE:
            raise Exception("Appium kurulu degil. pip install Appium-Python-Client")
        
        self.current_device_id = device.device_id
        
        # Appium 2.x icin URL
        appium_url = device.appium_url or "http://localhost:4723"
        if appium_url.endswith("/wd/hub"):
            appium_url = appium_url.replace("/wd/hub", "")
        
        print(f"[APPIUM] Connecting to {appium_url} for device {device.device_id}")
        
        if device.os == "android":
            options = UiAutomator2Options()
            options.platform_name = 'Android'
            options.device_name = device.name
            options.udid = device.device_id
            options.automation_name = 'UiAutomator2'
            options.no_reset = True
            options.auto_grant_permissions = True
            options.new_command_timeout = 300
            
            if app_package:
                options.app_package = app_package
                if app_activity:
                    options.app_activity = app_activity
        else:
            options = XCUITestOptions()
            options.platform_name = 'iOS'
            options.device_name = device.name
            options.udid = device.device_id
            options.automation_name = 'XCUITest'
            options.no_reset = True
            
            if app_package:
                options.bundle_id = app_package
        
        self.driver = appium_webdriver.Remote(appium_url, options=options)
        self.driver.implicitly_wait(10)
        
        # App package varsa uygulamayi baslat
        if app_package and device.os == "android":
            time.sleep(1)
            self._launch_app_adb(device.device_id, app_package, app_activity)
        
        return self.driver
    
    def _launch_app_adb(self, device_id: str, package: str, activity: str = ""):
        """ADB ile uygulamayi baslat"""
        import subprocess
        try:
            if activity:
                cmd = ['adb', '-s', device_id, 'shell', 'am', 'start', '-n', f'{package}/{activity}']
            else:
                cmd = ['adb', '-s', device_id, 'shell', 'monkey', '-p', package, '-c', 'android.intent.category.LAUNCHER', '1']
            
            subprocess.run(cmd, capture_output=True, timeout=10)
            time.sleep(2)
            print(f"[APPIUM] App launched: {package}")
        except Exception as e:
            print(f"[APPIUM] App launch error: {e}")
    
    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
        self.current_device_id = None
    
    def find_element_smart(self, locator_type: str, locator_value: str):
        if not APPIUM_AVAILABLE:
            raise Exception("Appium kurulu degil")
        
        strategies = []
        locator_type = locator_type.lower()
        
        if locator_type == 'id':
            strategies.append((AppiumBy.ID, locator_value))
        elif locator_type == 'xpath':
            strategies.append((AppiumBy.XPATH, locator_value))
        elif locator_type in ['text', 'auto']:
            strategies.extend([
                (AppiumBy.XPATH, f"//*[@text='{locator_value}']"),
                (AppiumBy.XPATH, f"//*[contains(@text, '{locator_value}')]"),
                (AppiumBy.XPATH, f"//*[@content-desc='{locator_value}']"),
                (AppiumBy.XPATH, f"//*[contains(@content-desc, '{locator_value}')]"),
                (AppiumBy.ACCESSIBILITY_ID, locator_value),
            ])
        else:
            strategies.append((AppiumBy.XPATH, locator_value))
        
        for by_type, by_value in strategies:
            try:
                wait = WebDriverWait(self.driver, 5)
                element = wait.until(EC.presence_of_element_located((by_type, by_value)))
                return element
            except:
                continue
        
        raise Exception(f"Element bulunamadi: {locator_value}")
    
    def execute_action(self, action: str, target: str, value: str, locator_type: str = "auto") -> Dict[str, Any]:
        result = {"success": True, "message": ""}
        action = action.lower().strip()
        
        try:
            if action in ['wait', 'bekle']:
                seconds = float(target or value or 1)
                time.sleep(seconds)
                result["message"] = f"{seconds}s beklendi"
            
            elif action in ['click', 'tap', 'tikla', 'bas', 'dokun']:
                element = self.find_element_smart(locator_type, target)
                element.click()
                time.sleep(0.5)
                result["message"] = f"Tiklandi"
            
            elif action in ['type', 'write', 'yaz', 'gir']:
                element = self.find_element_smart(locator_type, target)
                element.clear()
                element.send_keys(value)
                result["message"] = f"'{value}' yazildi"
            
            elif action in ['verify', 'dogrula', 'kontrol', 'gor']:
                text_to_find = target or value
                found = text_to_find.lower() in self.driver.page_source.lower()
                result["success"] = found
                result["message"] = "Bulundu" if found else "Bulunamadi"
            
            elif action in ['scroll', 'swipe', 'kaydir']:
                size = self.driver.get_window_size()
                direction = (target or value or 'down').lower()
                if direction in ['down', 'asagi']:
                    self.driver.swipe(
                        size['width'] // 2, 
                        int(size['height'] * 0.7), 
                        size['width'] // 2, 
                        int(size['height'] * 0.3), 
                        500
                    )
                elif direction in ['up', 'yukari']:
                    self.driver.swipe(
                        size['width'] // 2, 
                        int(size['height'] * 0.3), 
                        size['width'] // 2, 
                        int(size['height'] * 0.7), 
                        500
                    )
                result["message"] = f"Kaydirildi"
            
            elif action in ['back', 'geri']:
                self.driver.back()
                result["message"] = "Geri gidildi"
            
            elif action in ['home', 'ana']:
                self.driver.press_keycode(3)
                result["message"] = "Ana ekrana donuldu"
            
            elif action in ['launch', 'baslat', 'ac']:
                package = target or value
                if package and self.current_device_id:
                    self._launch_app_adb(self.current_device_id, package)
                    result["message"] = f"Uygulama baslatildi"
                else:
                    result["success"] = False
                    result["message"] = "Paket adi belirtilmedi"
            
            else:
                result["message"] = f"Aksiyon: {action}"
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["message"] = str(e)
        
        return result
    
    def parse_natural_language(self, text: str) -> List[TestStep]:
        commands = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            line = re.sub(r'^\d+[\.\)\-]\s*', '', line)
            step = TestStep()
            
            # TIKLA
            match = re.search(r'"([^"]+)"\s*(?:butonuna|elementine|yazisina|alanina|sekmesine|menusune|tiklanir|tikla|dokun|bas|basilir)', line, re.IGNORECASE)
            if match:
                step.action = 'tap'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # YAZ
            match = re.search(r'"([^"]+)"\s*(?:alanina|kutusuna|inputuna)\s*["\']?([^"\']+)["\']?\s*(?:yazilir|girilir|yaz|gir)', line, re.IGNORECASE)
            if match:
                step.action = 'type'
                step.target = match.group(1)
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            # DOGRULA
            match = re.search(r'"([^"]+)"\s*(?:yazisi|metni|elementi)?\s*(?:gorulur|goruntulenir|kontrol|var)', line, re.IGNORECASE)
            if match:
                step.action = 'verify'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # BEKLE
            match = re.search(r'(\d+)\s*(?:saniye|sn)\s*(?:beklenir|bekle)?', line, re.IGNORECASE)
            if match:
                step.action = 'wait'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # GERI
            if re.search(r'geri\s*(?:tusuna|basilir|git|don)', line, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            # SCROLL
            if re.search(r'(?:ekran|sayfa)\s*(?:asagi|asagiya)\s*(?:kaydirilir|kaydir)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
            
            if re.search(r'(?:ekran|sayfa)\s*(?:yukari|yukariya)\s*(?:kaydirilir|kaydir)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'up'
                commands.append(step)
                continue
            
            # UYGULAMA BASLAT
            match = re.search(r'(?:uygulama|app)\s*(?:baslatilir|acilir|baslat|ac)\s*[:\-]?\s*([^\s]+)?', line, re.IGNORECASE)
            if match:
                step.action = 'launch'
                step.target = match.group(1) if match.group(1) else ''
                commands.append(step)
                continue
        
        return commands
    
    def run_test(self, device: Device, steps: List[TestStep], app_package: str = "", app_activity: str = "", stop_on_fail: bool = True) -> Dict[str, Any]:
        test_id = str(uuid.uuid4())[:8]
        results = []
        start_time = time.time()
        
        if not APPIUM_AVAILABLE:
            return {
                "test_id": test_id,
                "success": False,
                "message": "Appium kurulu degil",
                "results": []
            }
        
        # Loglari temizle
        if EMU_SERVICE and emulator_service:
            emulator_service.clear_logs(device.device_id)
            # Session yoksa olustur
            emulator_service.ensure_session(device.device_id, 1)
        
        try:
            self._set_state("running", 0, len(steps))
            
            # Driver olustur
            self.create_driver(device, app_package, app_activity)
            time.sleep(2)
            
            for i, step in enumerate(steps):
                # Durduruldu mu?
                if self._is_stopped():
                    self._log(i + 1, step.action, step.target or step.value, "stopped", "Test durduruldu")
                    break
                
                # Log: running
                self._log(i + 1, step.action, step.target or step.value, "running", "Calisiyor...")
                self._set_state("running", i + 1, len(steps))
                
                step_result = StepResult(
                    step_number=i + 1,
                    total_steps=len(steps),
                    action=step.action,
                    target=step.target,
                    value=step.value,
                    original=f"{step.action}: {step.target}",
                    success=True
                )
                
                try:
                    action_result = self.execute_action(
                        step.action, 
                        step.target, 
                        step.value, 
                        step.locator_type
                    )
                    step_result.success = action_result.get("success", True)
                    step_result.message = action_result.get("message", "")
                    
                    # Log: success or failed
                    status = "success" if step_result.success else "failed"
                    self._log(i + 1, step.action, step.target or step.value, status, step_result.message)
                    
                except Exception as e:
                    step_result.success = False
                    step_result.error = str(e)
                    step_result.message = str(e)
                    self._log(i + 1, step.action, step.target or step.value, "failed", str(e))
                    
                    try:
                        step_result.screenshot = self.driver.get_screenshot_as_base64()
                    except:
                        pass
                
                results.append(step_result)
                
                # Kisa bekleme (log guncellenmesi icin)
                time.sleep(0.3)
                
                if not step_result.success and stop_on_fail:
                    self._set_state("failed", i + 1, len(steps))
                    break
            
            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            
            final_state = "success" if failed == 0 else "failed"
            self._set_state(final_state, len(results), len(steps))
            
            return {
                "test_id": test_id,
                "success": failed == 0,
                "message": "Test tamamlandi" if failed == 0 else "Test basarisiz",
                "summary": {
                    "total": len(steps),
                    "executed": len(results),
                    "passed": passed,
                    "failed": failed
                },
                "results": results,
                "duration": round(time.time() - start_time, 2)
            }
            
        except Exception as e:
            self._set_state("failed", 0, len(steps))
            self._log(0, "error", "connection", "failed", str(e))
            return {
                "test_id": test_id,
                "success": False,
                "message": str(e),
                "results": results,
                "duration": round(time.time() - start_time, 2)
            }
            
        finally:
            self.close_driver()


appium_service = AppiumService()
