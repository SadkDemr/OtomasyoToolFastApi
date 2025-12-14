"""
Appium Service - Mobil Test Otomasyonu
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import re
import uuid
from typing import List, Dict, Any

from models.schemas import TestStep, StepResult
from models.db_models import Device

try:
    from appium import webdriver as appium_webdriver
    from appium.options.android import UiAutomator2Options
    from appium.options.ios import XCUITestOptions
    from appium.webdriver.common.appiumby import AppiumBy
    APPIUM_AVAILABLE = True
except ImportError:
    APPIUM_AVAILABLE = False


class AppiumService:
    def __init__(self):
        self.driver = None
    
    def is_available(self) -> bool:
        return APPIUM_AVAILABLE
    
    def create_driver(self, device: Device, app_package: str = "", app_activity: str = ""):
        if not APPIUM_AVAILABLE:
            raise Exception("Appium kurulu degil")
        
        appium_url = device.appium_url or "http://localhost:4723/wd/hub"
        
        if device.os == "android":
            options = UiAutomator2Options()
            options.platform_name = 'Android'
            options.device_name = device.name
            options.udid = device.device_id
            options.automation_name = 'UiAutomator2'
            options.no_reset = True
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
        return self.driver
    
    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def find_element_smart(self, locator_type: str, locator_value: str):
        if not APPIUM_AVAILABLE:
            raise Exception("Appium kurulu degil")
        
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
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
                (AppiumBy.ACCESSIBILITY_ID, locator_value),
            ])
        else:
            strategies.append((AppiumBy.XPATH, locator_value))
        
        for by_type, by_value in strategies:
            try:
                wait = WebDriverWait(self.driver, 2)
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
                result["message"] = f"Beklendi: {seconds}s"
            
            elif action in ['click', 'tap', 'tikla', 'bas', 'dokun']:
                element = self.find_element_smart(locator_type, target)
                element.click()
                time.sleep(0.5)
                result["message"] = f"Tiklandi: {target}"
            
            elif action in ['type', 'write', 'yaz', 'gir']:
                element = self.find_element_smart(locator_type, target)
                element.clear()
                element.send_keys(value)
                result["message"] = f"Yazildi: {value}"
            
            elif action in ['verify', 'dogrula', 'kontrol']:
                text_to_find = target or value
                found = text_to_find.lower() in self.driver.page_source.lower()
                result["success"] = found
                result["message"] = f"Dogrulama: {'OK' if found else 'FAIL'}"
            
            elif action in ['scroll', 'swipe', 'kaydir']:
                size = self.driver.get_window_size()
                direction = (target or value or 'down').lower()
                if direction in ['down', 'asagi']:
                    self.driver.swipe(size['width']//2, int(size['height']*0.7), size['width']//2, int(size['height']*0.3), 500)
                elif direction in ['up', 'yukari']:
                    self.driver.swipe(size['width']//2, int(size['height']*0.3), size['width']//2, int(size['height']*0.7), 500)
                result["message"] = f"Kaydirildi: {direction}"
            
            elif action in ['back', 'geri']:
                self.driver.back()
                result["message"] = "Geri gidildi"
            
            else:
                result["message"] = f"Aksiyon: {action}"
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
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
            
            match = re.search(r'"([^"]+)"\s*(?:butonuna|elementine|yazisina|alanina)\s*(?:tiklanir|dokun|bas)', line, re.IGNORECASE)
            if match:
                step.action = 'tap'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            match = re.search(r'"([^"]+)"\s*(?:alanina|kutusuna)\s*["\']?([^"\']+)["\']?\s*(?:yazilir|girilir)', line, re.IGNORECASE)
            if match:
                step.action = 'type'
                step.target = match.group(1)
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            match = re.search(r'"([^"]+)"\s*(?:yazisi|metni)?\s*(?:gorulur|goruntulenir)', line, re.IGNORECASE)
            if match:
                step.action = 'verify'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            match = re.search(r'(\d+)\s*(?:saniye|sn)', line, re.IGNORECASE)
            if match:
                step.action = 'wait'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            if re.search(r'geri\s*(?:tusuna|basilir)', line, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            if re.search(r'(?:ekran)\s*(?:asagi)\s*(?:kaydirilir)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
        
        return commands
    
    def run_test(self, device: Device, steps: List[TestStep], app_package: str = "", app_activity: str = "", stop_on_fail: bool = True) -> Dict[str, Any]:
        test_id = str(uuid.uuid4())[:8]
        results = []
        start_time = time.time()
        
        if not APPIUM_AVAILABLE:
            return {"test_id": test_id, "success": False, "message": "Appium kurulu degil", "results": []}
        
        try:
            self.create_driver(device, app_package, app_activity)
            
            for i, step in enumerate(steps):
                step_result = StepResult(step_number=i+1, total_steps=len(steps), action=step.action, target=step.target, value=step.value, success=True)
                
                try:
                    action_result = self.execute_action(step.action, step.target, step.value, step.locator_type)
                    step_result.success = action_result.get("success", True)
                    step_result.message = action_result.get("message", "")
                except Exception as e:
                    step_result.success = False
                    step_result.error = str(e)
                    try:
                        step_result.screenshot = self.driver.get_screenshot_as_base64()
                    except:
                        pass
                
                results.append(step_result)
                if not step_result.success and stop_on_fail:
                    break
            
            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            
            return {
                "test_id": test_id,
                "success": failed == 0,
                "message": "Test tamamlandi" if failed == 0 else "Test basarisiz",
                "summary": {"total": len(steps), "executed": len(results), "passed": passed, "failed": failed},
                "results": results,
                "duration": round(time.time() - start_time, 2)
            }
        except Exception as e:
            return {"test_id": test_id, "success": False, "message": str(e), "results": results, "duration": round(time.time() - start_time, 2)}
        finally:
            self.close_driver()


appium_service = AppiumService()