"""
Selenium Service - Web Test
Windows WinError 193 duzeltmesi
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import re
import uuid
from typing import List, Dict, Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import *

from models.schemas import TestStep, StepResult

# ChromeDriver manager - otomatik indir
try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER = True
except:
    WEBDRIVER_MANAGER = False


class SeleniumService:
    def __init__(self):
        self.driver = None
    
    def create_driver(self, headless: bool = False):
        options = Options()
        
        if headless:
            options.add_argument('--headless=new')
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        
        # Windows icin ozel ayarlar
        if os.name == 'nt':
            options.add_argument('--disable-features=VizDisplayCompositor')
        
        try:
            if WEBDRIVER_MANAGER:
                # Otomatik ChromeDriver indir
                driver_path = ChromeDriverManager().install()
                
                # Windows'ta path duzeltmesi
                # Bazen webdriver_manager .exe yerine klasor doner
                if os.name == 'nt' and not driver_path.endswith('.exe'):
                    # chromedriver.exe'yi bul
                    driver_dir = os.path.dirname(driver_path)
                    for f in os.listdir(driver_dir):
                        if f == 'chromedriver.exe':
                            driver_path = os.path.join(driver_dir, f)
                            break
                    
                    # Hala bulamadiysa parent'ta ara
                    if not driver_path.endswith('.exe'):
                        parent_dir = os.path.dirname(driver_dir)
                        for root, dirs, files in os.walk(parent_dir):
                            for f in files:
                                if f == 'chromedriver.exe':
                                    driver_path = os.path.join(root, f)
                                    break
                
                print(f"[SELENIUM] ChromeDriver path: {driver_path}")
                service = Service(executable_path=driver_path)
            else:
                # System PATH'te chromedriver olmali
                service = Service()
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.implicitly_wait(5)
            
        except Exception as e:
            print(f"[SELENIUM] Driver creation error: {e}")
            raise Exception(f"Chrome driver olusturulamadi: {str(e)}")
        
        return self.driver
    
    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def find_element_smart(self, locator_type: str, locator_value: str):
        strategies = []
        locator_type = locator_type.lower()
        
        if locator_type == 'id':
            strategies.append((By.ID, locator_value))
        elif locator_type == 'xpath':
            strategies.append((By.XPATH, locator_value))
        elif locator_type == 'css':
            strategies.append((By.CSS_SELECTOR, locator_value))
        elif locator_type in ['text', 'auto']:
            strategies.extend([
                (By.XPATH, f"//*[text()='{locator_value}']"),
                (By.XPATH, f"//*[contains(text(),'{locator_value}')]"),
                (By.XPATH, f"//button[contains(.,'{locator_value}')]"),
                (By.XPATH, f"//a[contains(.,'{locator_value}')]"),
                (By.XPATH, f"//*[@placeholder='{locator_value}']"),
                (By.XPATH, f"//*[@placeholder][contains(@placeholder,'{locator_value}')]"),
                (By.XPATH, f"//*[@aria-label='{locator_value}']"),
                (By.XPATH, f"//input[@name='{locator_value}']"),
                (By.XPATH, f"//input[@id='{locator_value}']"),
                (By.ID, locator_value),
                (By.NAME, locator_value),
            ])
        else:
            strategies.append((By.XPATH, locator_value))
        
        for by_type, by_value in strategies:
            try:
                wait = WebDriverWait(self.driver, 2)
                element = wait.until(EC.presence_of_element_located((by_type, by_value)))
                return element
            except:
                continue
        
        raise NoSuchElementException(f"Element bulunamadi: {locator_value}")
    
    def execute_action(self, action: str, target: str, value: str, locator_type: str = "auto") -> Dict[str, Any]:
        result = {"success": True, "message": ""}
        action = action.lower().strip()
        
        try:
            if action in ['open', 'navigate', 'goto', 'git', 'ac']:
                url = target or value
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(1)
                result["message"] = f"Sayfa acildi: {url}"
            
            elif action in ['click', 'tikla', 'bas']:
                element = self.find_element_smart(locator_type, target)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.3)
                element.click()
                time.sleep(0.5)
                result["message"] = f"Tiklandi: {target}"
            
            elif action in ['type', 'write', 'yaz', 'gir']:
                element = self.find_element_smart(locator_type, target)
                element.clear()
                element.send_keys(value)
                result["message"] = f"Yazildi: {value}"
            
            elif action in ['wait', 'bekle']:
                seconds = float(target or value or 1)
                time.sleep(seconds)
                result["message"] = f"Beklendi: {seconds}s"
            
            elif action in ['verify', 'dogrula', 'kontrol', 'gor']:
                text_to_find = target or value
                found = text_to_find.lower() in self.driver.page_source.lower()
                result["success"] = found
                result["message"] = f"Dogrulama: {'Basarili' if found else 'Basarisiz'} - {text_to_find}"
            
            elif action in ['scroll', 'kaydir']:
                direction = (target or value or 'down').lower()
                if direction in ['down', 'asagi']:
                    self.driver.execute_script("window.scrollBy(0, 500);")
                elif direction in ['up', 'yukari']:
                    self.driver.execute_script("window.scrollBy(0, -500);")
                result["message"] = f"Kaydirildi: {direction}"
            
            elif action in ['back', 'geri']:
                self.driver.back()
                result["message"] = "Geri gidildi"
            
            elif action in ['refresh', 'yenile']:
                self.driver.refresh()
                result["message"] = "Sayfa yenilendi"
            
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
            match = re.search(r'"([^"]+)"\s*(?:butonuna|dugmesine|linkine|elementine|yazisina|alanina|sekmesine|menusune)?\s*(?:tiklanir|tikla|bas|basilir|click)', line, re.IGNORECASE)
            if match:
                step.action = 'click'
                step.target = match.group(1)
                step.locator_type = 'text'
                commands.append(step)
                continue
            
            # YAZ
            match = re.search(r'"([^"]+)"\s*(?:alanina|kutusuna|inputuna|yerine)\s*["\']?([^"\']+)["\']?\s*(?:yazilir|girilir|yaz|gir)', line, re.IGNORECASE)
            if match:
                step.action = 'type'
                step.target = match.group(1)
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            # DOGRULA
            match = re.search(r'"([^"]+)"\s*(?:yazisi|metni|elementi)?\s*(?:gorulur|goruntulenir|kontrol|dogrulanir|var mi)', line, re.IGNORECASE)
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
            
            # SCROLL
            if re.search(r'(?:sayfa|ekran)\s*(?:asagi|asagiya)\s*(?:kaydirilir|kaydir)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
            
            if re.search(r'(?:sayfa|ekran)\s*(?:yukari|yukariya)\s*(?:kaydirilir|kaydir)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'up'
                commands.append(step)
                continue
            
            # GERI
            if re.search(r'geri\s*(?:tusuna|git|basilir|don)', line, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            # YENILE
            if re.search(r'(?:sayfa)?\s*(?:yenilenir|yenile|refresh)', line, re.IGNORECASE):
                step.action = 'refresh'
                commands.append(step)
                continue
        
        return commands
    
    def run_test(self, url: str, steps: List[TestStep], headless: bool = False, stop_on_fail: bool = True) -> Dict[str, Any]:
        test_id = str(uuid.uuid4())[:8]
        results = []
        start_time = time.time()
        
        try:
            self.create_driver(headless)
            
            if url:
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(2)
            
            for i, step in enumerate(steps):
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
            return {
                "test_id": test_id,
                "success": False,
                "message": str(e),
                "results": results,
                "duration": round(time.time() - start_time, 2)
            }
        
        finally:
            self.close_driver()


selenium_service = SeleniumService()
