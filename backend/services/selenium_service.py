"""
Selenium Service - Web Test v3
==============================
DÜZELTMELER:
1. ChromeDriver otomatik indirilmesi
2. Windows uyumluluğu
3. Gelişmiş element bulma
4. Türkçe parse genişletildi
5. Canlı log callback desteği
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import re
import uuid
from typing import List, Dict, Any, Callable, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import *

from models.schemas import TestStep, StepResult

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER = True
except ImportError:
    WEBDRIVER_MANAGER = False
    print("[SELENIUM] webdriver-manager yüklü değil. pip install webdriver-manager")


class SeleniumService:
    def __init__(self):
        self.driver = None
        self.log_callback: Optional[Callable] = None
        self.current_test_id: str = ""
    
    def set_log_callback(self, callback: Callable):
        """Canlı log için callback ayarla"""
        self.log_callback = callback
    
    def _send_log(self, step_num: int, action: str, status: str, message: str = ""):
        """Log gönder (callback varsa)"""
        print(f"[WEB] Adım {step_num}: {action} -> {status}")
        if self.log_callback:
            try:
                self.log_callback({
                    "test_id": self.current_test_id,
                    "step": step_num,
                    "action": action,
                    "status": status,
                    "message": message
                })
            except Exception as e:
                print(f"[WEB] Log callback error: {e}")
    
    def create_driver(self, headless: bool = False):
        """Chrome driver oluştur"""
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
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        if os.name == 'nt':
            options.add_argument('--disable-features=VizDisplayCompositor')
        
        try:
            if WEBDRIVER_MANAGER:
                driver_path = ChromeDriverManager().install()
                
                # Windows'ta .exe dosyasını bul
                if os.name == 'nt' and not driver_path.endswith('.exe'):
                    driver_dir = os.path.dirname(driver_path)
                    for f in os.listdir(driver_dir):
                        if f == 'chromedriver.exe':
                            driver_path = os.path.join(driver_dir, f)
                            break
                    
                    if not driver_path.endswith('.exe'):
                        parent_dir = os.path.dirname(driver_dir)
                        for root, dirs, files in os.walk(parent_dir):
                            for f in files:
                                if f == 'chromedriver.exe':
                                    driver_path = os.path.join(root, f)
                                    break
                
                print(f"[SELENIUM] ChromeDriver: {driver_path}")
                service = Service(executable_path=driver_path)
            else:
                service = Service()
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.implicitly_wait(5)
            print("[SELENIUM] Driver oluşturuldu")
            
        except Exception as e:
            print(f"[SELENIUM] Driver hatası: {e}")
            raise Exception(f"Chrome driver oluşturulamadı: {str(e)}")
        
        return self.driver
    
    def close_driver(self):
        """Driver'ı kapat"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def find_element_smart(self, locator_type: str, value: str, timeout: int = 10):
        """Akıllı element bulma - birden fazla strateji dener"""
        strategies = []
        locator_type = locator_type.lower()
        
        if locator_type == 'id':
            strategies.append((By.ID, value))
        elif locator_type == 'xpath':
            strategies.append((By.XPATH, value))
        elif locator_type == 'css':
            strategies.append((By.CSS_SELECTOR, value))
        elif locator_type == 'name':
            strategies.append((By.NAME, value))
        else:
            # Auto mod - tüm stratejileri dene
            strategies = [
                (By.XPATH, f"//*[text()='{value}']"),
                (By.XPATH, f"//button[text()='{value}']"),
                (By.XPATH, f"//a[text()='{value}']"),
                (By.XPATH, f"//*[contains(text(),'{value}')]"),
                (By.XPATH, f"//button[contains(.,'{value}')]"),
                (By.XPATH, f"//a[contains(.,'{value}')]"),
                (By.XPATH, f"//*[@placeholder='{value}']"),
                (By.XPATH, f"//*[contains(@placeholder,'{value}')]"),
                (By.XPATH, f"//*[@aria-label='{value}']"),
                (By.XPATH, f"//*[contains(@aria-label,'{value}')]"),
                (By.XPATH, f"//label[contains(.,'{value}')]/following::input[1]"),
                (By.XPATH, f"//input[@name='{value}']"),
                (By.XPATH, f"//input[@id='{value}']"),
                (By.XPATH, f"//textarea[@name='{value}']"),
                (By.XPATH, f"//select[@name='{value}']"),
                (By.ID, value),
                (By.NAME, value),
                (By.CLASS_NAME, value),
            ]
        
        per_strategy_timeout = min(1.5, timeout / len(strategies))
        
        for by_type, by_value in strategies:
            try:
                wait = WebDriverWait(self.driver, per_strategy_timeout)
                element = wait.until(EC.presence_of_element_located((by_type, by_value)))
                if element.is_displayed():
                    return element
            except:
                continue
        
        raise NoSuchElementException(f"Element bulunamadı: {value}")
    
    def execute_action(self, action: str, target: str, value: str, locator_type: str = "auto") -> Dict[str, Any]:
        """Aksiyon çalıştır"""
        result = {"success": True, "message": ""}
        action = action.lower().strip()
        
        try:
            # URL GİT
            if action in ['open', 'navigate', 'goto', 'git', 'ac', 'aç', 'url']:
                url = target or value
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(1)
                result["message"] = f"Sayfa açıldı: {url}"
            
            # TIKLA
            elif action in ['click', 'tikla', 'tıkla', 'bas']:
                element = self.find_element_smart(locator_type, target)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.3)
                
                try:
                    element.click()
                except:
                    self.driver.execute_script("arguments[0].click();", element)
                
                time.sleep(0.5)
                result["message"] = f"Tıklandı: {target}"
            
            # YAZ
            elif action in ['type', 'write', 'yaz', 'gir', 'doldur']:
                element = self.find_element_smart(locator_type, target)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.2)
                
                try:
                    element.clear()
                except:
                    element.send_keys(Keys.CONTROL + "a")
                    element.send_keys(Keys.DELETE)
                
                element.send_keys(value)
                result["message"] = f"Yazıldı: {value}"
            
            # BEKLE
            elif action in ['wait', 'bekle', 'dur']:
                seconds = float(target or value or 1)
                time.sleep(seconds)
                result["message"] = f"Beklendi: {seconds}s"
            
            # DOĞRULA
            elif action in ['verify', 'dogrula', 'doğrula', 'kontrol', 'gor', 'gör', 'assert']:
                text_to_find = target or value
                
                try:
                    self.find_element_smart("auto", text_to_find, timeout=3)
                    result["success"] = True
                    result["message"] = f"Doğrulandı: '{text_to_find}'"
                except:
                    # Sayfa kaynağında ara
                    if text_to_find.lower() in self.driver.page_source.lower():
                        result["success"] = True
                        result["message"] = f"Sayfada bulundu: '{text_to_find}'"
                    else:
                        result["success"] = False
                        result["message"] = f"Bulunamadı: '{text_to_find}'"
            
            # SCROLL AŞAĞI
            elif action in ['scroll', 'kaydir', 'kaydır']:
                direction = (target or value or 'down').lower()
                if direction in ['down', 'asagi', 'aşağı']:
                    self.driver.execute_script("window.scrollBy(0, 500);")
                elif direction in ['up', 'yukari', 'yukarı']:
                    self.driver.execute_script("window.scrollBy(0, -500);")
                elif direction in ['top', 'en_ust', 'en_üst']:
                    self.driver.execute_script("window.scrollTo(0, 0);")
                elif direction in ['bottom', 'en_alt']:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                result["message"] = f"Kaydırıldı: {direction}"
            
            # GERİ
            elif action in ['back', 'geri']:
                self.driver.back()
                time.sleep(0.5)
                result["message"] = "Geri gidildi"
            
            # İLERİ
            elif action in ['forward', 'ileri']:
                self.driver.forward()
                time.sleep(0.5)
                result["message"] = "İleri gidildi"
            
            # YENİLE
            elif action in ['refresh', 'yenile']:
                self.driver.refresh()
                time.sleep(1)
                result["message"] = "Sayfa yenilendi"
            
            # TEMİZLE
            elif action in ['clear', 'temizle', 'sil']:
                element = self.find_element_smart(locator_type, target)
                element.clear()
                result["message"] = f"Temizlendi: {target}"
            
            # FORM GÖNDER
            elif action in ['submit', 'gonder', 'gönder']:
                element = self.find_element_smart(locator_type, target)
                element.submit()
                result["message"] = "Form gönderildi"
            
            # TUŞ BAS
            elif action in ['press', 'key', 'tus', 'tuş', 'enter']:
                key_map = {
                    'enter': Keys.ENTER,
                    'tab': Keys.TAB,
                    'escape': Keys.ESCAPE,
                    'esc': Keys.ESCAPE,
                    'space': Keys.SPACE,
                    'backspace': Keys.BACKSPACE,
                    'delete': Keys.DELETE,
                    'up': Keys.UP,
                    'down': Keys.DOWN,
                    'left': Keys.LEFT,
                    'right': Keys.RIGHT,
                }
                key = key_map.get((target or 'enter').lower(), Keys.ENTER)
                webdriver.ActionChains(self.driver).send_keys(key).perform()
                result["message"] = f"Tuş basıldı: {target or 'enter'}"
            
            # EKRAN GÖRÜNTÜSÜ
            elif action in ['screenshot', 'ss', 'ekran', 'goruntu', 'görüntü']:
                filename = target or f"screenshot_{int(time.time())}.png"
                if not filename.endswith('.png'):
                    filename += '.png'
                self.driver.save_screenshot(filename)
                result["message"] = f"Ekran görüntüsü: {filename}"
            
            # BEKLE ELEMENT
            elif action in ['wait_element', 'element_bekle']:
                wait = WebDriverWait(self.driver, int(value or 10))
                wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(),'{target}')]")))
                result["message"] = f"Element beklendi: {target}"
            
            # HOVER
            elif action in ['hover', 'uzerine_git', 'üzerine_git']:
                element = self.find_element_smart(locator_type, target)
                webdriver.ActionChains(self.driver).move_to_element(element).perform()
                result["message"] = f"Hover: {target}"
            
            # ÇİFT TIKLA
            elif action in ['double_click', 'cift_tikla', 'çift_tıkla']:
                element = self.find_element_smart(locator_type, target)
                webdriver.ActionChains(self.driver).double_click(element).perform()
                result["message"] = f"Çift tıklandı: {target}"
            
            # SAĞ TIKLA
            elif action in ['right_click', 'sag_tikla', 'sağ_tıkla']:
                element = self.find_element_smart(locator_type, target)
                webdriver.ActionChains(self.driver).context_click(element).perform()
                result["message"] = f"Sağ tıklandı: {target}"
            
            else:
                result["message"] = f"Bilinmeyen aksiyon: {action}"
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["message"] = f"Hata: {str(e)}"
        
        return result
    
    def parse_natural_language(self, text: str) -> List[TestStep]:
        """Türkçe doğal dili test adımlarına çevir"""
        commands = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            
            # Satır numarasını temizle
            line = re.sub(r'^\d+[\.\)\-]\s*', '', line)
            step = TestStep()
            
            # URL GİT
            match = re.search(r'(?:git|aç|ac|open|navigate)\s*["\']?([^"\']+)["\']?', line, re.IGNORECASE)
            if match and ('http' in match.group(1) or '.' in match.group(1)):
                step.action = 'navigate'
                step.target = match.group(1).strip()
                commands.append(step)
                continue
            
            # TIKLA
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:butonuna|düğmesine|dugmesine|linkine|elementine|yazısına|yazisina|sekmesine|menüsüne|menusune|üzerine|uzerine|alanına|alanina)?\s*(?:tıkla|tikla|tıklanır|tiklanir|bas|basılır|basilir|click|seç|sec)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'click'
                step.target = match.group(1)
                step.locator_type = 'auto'
                commands.append(step)
                continue
            
            # Alternatif TIKLA
            match = re.search(
                r'(?:tıkla|tikla|bas|click)\s*["\']([^"\']+)["\']',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'click'
                step.target = match.group(1)
                step.locator_type = 'auto'
                commands.append(step)
                continue
            
            # YAZ
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:alanına|alanina|kutusuna|inputuna|yerine|kısmına|kismina|bölümüne|bolumune)?\s*["\']?([^"\']+)["\']?\s*(?:yazılır|yazilir|yaz|girilir|gir|doldur|doldurulur|yazar)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'type'
                step.target = match.group(1).strip()
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            # DOĞRULA
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:yazısı|yazisi|yazısını|yazisini|metni|metnini|elementi|mesajı|mesaji)?\s*(?:görülür|gorulur|görüntülenir|goruntulenir|görünür|gorunur|gör|gor|kontrol|doğrulanır|dogrulanir|var|bulunur|mevcut|görünmeli|gorunmeli|olmalı|olmali)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'verify'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # BEKLE
            match = re.search(r'(\d+(?:\.\d+)?)\s*(?:saniye|sn|s)\s*(?:beklenir|bekle|bekler|dur)?', line, re.IGNORECASE)
            if match:
                step.action = 'wait'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            # SCROLL AŞAĞI
            if re.search(r'(?:sayfa|ekran)?\s*(?:aşağı|asagi)\s*(?:kaydırılır|kaydirilir|kaydır|kaydir|scroll)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
            
            # SCROLL YUKARI
            if re.search(r'(?:sayfa|ekran)?\s*(?:yukarı|yukari)\s*(?:kaydırılır|kaydirilir|kaydır|kaydir|scroll)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'up'
                commands.append(step)
                continue
            
            # GERİ
            if re.search(r'geri\s*(?:git|gidilir|tuşuna|tusuna|bas|dön|don)?', line, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            # YENİLE
            if re.search(r'(?:sayfa)?\s*(?:yenilenir|yenile|refresh)', line, re.IGNORECASE):
                step.action = 'refresh'
                commands.append(step)
                continue
            
            # ENTER BAS
            if re.search(r'enter\s*(?:bas|tuşuna|tusuna)?', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'enter'
                commands.append(step)
                continue
            
            # EKRAN GÖRÜNTÜSÜ
            if re.search(r'(?:ekran\s*)?(?:görüntüsü|goruntusü|screenshot|ss)', line, re.IGNORECASE):
                step.action = 'screenshot'
                step.target = f"screenshot_{int(time.time())}.png"
                commands.append(step)
                continue
        
        return commands
    
    def run_test(self, url: str, steps: List[TestStep], headless: bool = False, 
                 stop_on_fail: bool = True, log_callback: Callable = None) -> Dict[str, Any]:
        """Test çalıştır"""
        self.current_test_id = str(uuid.uuid4())[:8]
        
        if log_callback:
            self.log_callback = log_callback
        
        results = []
        start_time = time.time()
        
        try:
            self.create_driver(headless)
            
            # İlk URL'ye git
            if url:
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(2)
            
            # Adımları çalıştır
            for i, step in enumerate(steps):
                step_num = i + 1
                
                # Log gönder - başlıyor
                self._send_log(step_num, step.action, "running")
                
                step_result = StepResult(
                    step_number=step_num,
                    action=step.action,
                    success=True,
                    message=""
                )
                
                try:
                    action_result = self.execute_action(step.action, step.target, step.value, step.locator_type)
                    step_result.success = action_result.get("success", True)
                    step_result.message = action_result.get("message", "")
                    
                except Exception as e:
                    step_result.success = False
                    step_result.message = str(e)
                
                results.append(step_result)
                
                # Log gönder - sonuç
                status = "success" if step_result.success else "failed"
                self._send_log(step_num, step.action, status, step_result.message)
                
                print(f"[WEB] Adım {step_num}/{len(steps)}: {step.action} -> {'✓' if step_result.success else '✗'}")
                
                if not step_result.success and stop_on_fail:
                    break
            
            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            
            return {
                "test_id": self.current_test_id,
                "success": failed == 0,
                "message": "Test tamamlandı" if failed == 0 else "Test başarısız",
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
            return {
                "test_id": self.current_test_id,
                "success": False,
                "message": str(e),
                "results": results,
                "duration": round(time.time() - start_time, 2)
            }
        
        finally:
            self.close_driver()


selenium_service = SeleniumService()