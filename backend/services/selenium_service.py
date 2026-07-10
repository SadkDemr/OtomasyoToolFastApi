"""
Selenium Service - Web Test v4
==============================
YENİ ÖZELLİKLER:
1. Varsayılan Headless mode (Chrome açılmaz)
2. Her adımda otomatik screenshot
3. PDF rapor oluşturma
4. WebSocket ile canlı log
5. Screenshot'lı log yapısı
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import re
import uuid
import base64
import json
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import *

try:
    from models.schemas import TestStep, StepResult
except:
    class TestStep:
        def __init__(self):
            self.action = ""
            self.target = ""
            self.value = ""
            self.locator_type = "auto"
    
    class StepResult:
        def __init__(self, step_number=0, action="", success=True, message=""):
            self.step_number = step_number
            self.action = action
            self.success = success
            self.message = message

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER = True
except ImportError:
    WEBDRIVER_MANAGER = False
    print("[SELENIUM] webdriver-manager yüklü değil. pip install webdriver-manager")


def _resolve_local_chromedriver() -> Optional[str]:
    """Offline modda kullanilacak yerel chromedriver.exe yolunu dondurur, yoksa None.

    CHROMEDRIVER_PATH ortam degiskeni varsa onceliklidir; yoksa backend kok
    dizinindeki chromedriver/chromedriver.exe dosyasina bakilir. Ikisi de yoksa
    (gelistirme ortami) None doner ve mevcut webdriver-manager davranisina dusulur.
    """
    env_path = os.environ.get("CHROMEDRIVER_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_path = os.path.join(backend_root, "chromedriver", "chromedriver.exe")
    if os.path.isfile(default_path):
        return default_path
    return None

# PDF oluşturma için (opsiyonel)
PDF_AVAILABLE = False
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
    PDF_AVAILABLE = True
except ImportError:
    pass  # PDF desteği yok, sessizce devam et


class WebTestResult:
    """Test sonucu - screenshot dahil"""
    def __init__(self):
        self.step_number: int = 0
        self.action: str = ""
        self.target: str = ""
        self.success: bool = True
        self.message: str = ""
        self.screenshot: str = ""
        self.timestamp: str = ""
        self.duration: float = 0


class SeleniumService:
    def __init__(self):
        self.driver = None
        self.log_callback: Optional[Callable] = None
        self.current_test_id: str = ""
        self.screenshots_dir = Path("screenshots")
        self.reports_dir = Path("reports")
        self.test_results: List[WebTestResult] = []
        
        self.screenshots_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)
    
    def set_log_callback(self, callback: Callable):
        self.log_callback = callback
    
    def _send_log(self, step_num: int, action: str, status: str, message: str = "", screenshot: str = ""):
        print(f"[WEB] Adım {step_num}: {action} -> {status}")
        if self.log_callback:
            try:
                self.log_callback({
                    "test_id": self.current_test_id,
                    "step": step_num,
                    "action": action,
                    "status": status,
                    "message": message,
                    "screenshot": screenshot,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                print(f"[WEB] Log callback error: {e}")
    
    def _take_screenshot(self) -> str:
        try:
            if self.driver:
                return self.driver.get_screenshot_as_base64()
        except Exception as e:
            print(f"[WEB] Screenshot hatası: {e}")
        return ""
    
    def _save_screenshot(self, step_num: int, screenshot_base64: str) -> str:
        if not screenshot_base64:
            return ""
        try:
            filename = f"{self.current_test_id}_step_{step_num}.png"
            filepath = self.screenshots_dir / filename
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(screenshot_base64))
            return str(filepath)
        except Exception as e:
            print(f"[WEB] Screenshot kayıt hatası: {e}")
            return ""
    
    def create_driver(self, headless: bool = True):
        """Chrome driver - VARSAYILAN HEADLESS"""
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
        options.add_argument('--force-device-scale-factor=1')
        
        if os.name == 'nt':
            options.add_argument('--disable-features=VizDisplayCompositor')
        
        try:
            local_driver = _resolve_local_chromedriver()
            if local_driver:
                print(f"[SELENIUM] Yerel ChromeDriver kullaniliyor (offline mod): {local_driver}")
                service = Service(executable_path=local_driver)
            elif WEBDRIVER_MANAGER:
                driver_path = ChromeDriverManager().install()
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
            print(f"[SELENIUM] Driver oluşturuldu (headless={headless})")
        except Exception as e:
            print(f"[SELENIUM] Driver hatası: {e}")
            raise Exception(f"Chrome driver oluşturulamadı: {str(e)}")
        return self.driver
    
    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def find_element_smart(self, locator_type: str, value: str, timeout: int = 10):
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
                (By.XPATH, f"//label[contains(.,'{value}')]/following::input[1]"),
                (By.XPATH, f"//input[@name='{value}']"),
                (By.XPATH, f"//input[@id='{value}']"),
                (By.XPATH, f"//textarea[@name='{value}']"),
                (By.ID, value),
                (By.NAME, value),
                (By.CLASS_NAME, value),
            ]
        
        per_timeout = min(1.5, timeout / len(strategies))
        for by_type, by_value in strategies:
            try:
                wait = WebDriverWait(self.driver, per_timeout)
                element = wait.until(EC.presence_of_element_located((by_type, by_value)))
                if element.is_displayed():
                    return element
            except:
                continue
        raise NoSuchElementException(f"Element bulunamadı: {value}")
    
    def execute_action(self, action: str, target: str, value: str, locator_type: str = "auto") -> Dict[str, Any]:
        result = {"success": True, "message": ""}
        action = action.lower().strip()
        
        try:
            if action in ['open', 'navigate', 'goto', 'git', 'ac', 'aç', 'url']:
                url = target or value
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(1)
                result["message"] = f"Sayfa açıldı: {url}"
            
            elif action in ['click', 'tikla', 'tıkla', 'bas']:
                element = self.find_element_smart(locator_type, target)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.3)
                try:
                    element.click()
                except:
                    self.driver.execute_script("arguments[0].click();", element)
                result["message"] = f"'{target}' tıklandı"
            
            elif action in ['type', 'yaz', 'gir', 'doldur', 'write']:
                element = self.find_element_smart(locator_type, target)
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.2)
                element.clear()
                element.send_keys(value)
                result["message"] = f"'{target}' alanına '{value}' yazıldı"
            
            elif action in ['verify', 'dogrula', 'doğrula', 'kontrol', 'assert']:
                try:
                    element = self.find_element_smart('auto', target, timeout=5)
                    result["message"] = f"'{target}' doğrulandı"
                except:
                    result["success"] = False
                    result["message"] = f"'{target}' bulunamadı"
            
            elif action in ['wait', 'bekle', 'dur']:
                seconds = float(target or value or 1)
                time.sleep(seconds)
                result["message"] = f"{seconds}s beklendi"
            
            elif action in ['scroll', 'kaydir', 'kaydır']:
                direction = (target or value or 'down').lower()
                if direction in ['down', 'aşağı', 'asagi']:
                    self.driver.execute_script("window.scrollBy(0, 500);")
                else:
                    self.driver.execute_script("window.scrollBy(0, -500);")
                result["message"] = f"Sayfa {direction} kaydırıldı"
            
            elif action in ['back', 'geri']:
                self.driver.back()
                result["message"] = "Geri gidildi"
            
            elif action in ['refresh', 'yenile']:
                self.driver.refresh()
                time.sleep(1)
                result["message"] = "Sayfa yenilendi"
            
            elif action in ['press', 'key', 'tus', 'tuş']:
                key = (target or value).lower()
                ae = self.driver.switch_to.active_element
                if key == 'enter':
                    ae.send_keys(Keys.ENTER)
                elif key == 'tab':
                    ae.send_keys(Keys.TAB)
                elif key in ['escape', 'esc']:
                    ae.send_keys(Keys.ESCAPE)
                elif key in ['up', 'down', 'left', 'right']:
                    ae.send_keys(getattr(Keys, f'ARROW_{key.upper()}'))
                elif key == 'space':
                    ae.send_keys(Keys.SPACE)
                elif key == 'double_space':
                    ae.send_keys(Keys.SPACE)
                    ae.send_keys(Keys.SPACE)
                elif key == 'delete':
                    ae.send_keys(Keys.DELETE)
                elif key == 'backspace':
                    ae.send_keys(Keys.BACK_SPACE)
                elif key == 'home':
                    ae.send_keys(Keys.HOME)
                elif key == 'end':
                    ae.send_keys(Keys.END)
                elif key in ['pageup', 'page_up']:
                    ae.send_keys(Keys.PAGE_UP)
                elif key in ['pagedown', 'page_down']:
                    ae.send_keys(Keys.PAGE_DOWN)
                elif '+' in key:
                    mod_name, letter = key.split('+', 1)
                    mod_key = {'ctrl': Keys.CONTROL, 'shift': Keys.SHIFT, 'alt': Keys.ALT}.get(mod_name)
                    if mod_key:
                        ActionChains(self.driver).key_down(mod_key).send_keys(letter).key_up(mod_key).perform()
                    else:
                        result["success"] = False
                        result["message"] = f"Bilinmeyen kısayol: {key}"
                else:
                    result["success"] = False
                    result["message"] = f"Bilinmeyen tuş: {key}"
                if result["success"]:
                    result["message"] = f"{key.upper()} tuşuna basıldı"
            
            elif action in ['screenshot', 'ss', 'ekran']:
                result["message"] = "Ekran görüntüsü alındı"
            
            else:
                result["success"] = False
                result["message"] = f"Bilinmeyen aksiyon: {action}"
        
        except Exception as e:
            result["success"] = False
            result["message"] = str(e)
        
        return result
    
    def parse_natural_language(self, text: str) -> List[TestStep]:
        commands = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('//'):
                continue
            
            line = re.sub(r'^\d+[\.\)\-]\s*', '', line)
            step = TestStep()
            
            match = re.search(r'(?:git|aç|ac|open|navigate)\s*["\']?([^"\']+)["\']?', line, re.IGNORECASE)
            if match and ('http' in match.group(1) or '.' in match.group(1)):
                step.action = 'navigate'
                step.target = match.group(1).strip()
                commands.append(step)
                continue
            
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:butonuna|düğmesine|linkine|elementine|yazısına|sekmesine|menüsüne|üzerine|alanına)?\s*(?:tıkla|tikla|bas|click|seç|sec)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'click'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            match = re.search(r'(?:tıkla|tikla|bas|click)\s*["\']([^"\']+)["\']', line, re.IGNORECASE)
            if match:
                step.action = 'click'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:alanına|kutusuna|inputuna|yerine)?\s*["\']?([^"\']+)["\']?\s*(?:yaz|gir|doldur)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'type'
                step.target = match.group(1).strip()
                step.value = match.group(2).strip()
                commands.append(step)
                continue
            
            match = re.search(
                r'["\']([^"\']+)["\']\s*(?:yazısı|metni)?\s*(?:görülür|görünür|gör|kontrol|doğrulanır|var|bulunur)',
                line, re.IGNORECASE
            )
            if match:
                step.action = 'verify'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            match = re.search(r'(\d+(?:\.\d+)?)\s*(?:saniye|sn|s)\s*(?:bekle|dur)?', line, re.IGNORECASE)
            if match:
                step.action = 'wait'
                step.target = match.group(1)
                commands.append(step)
                continue
            
            if re.search(r'(?:aşağı|asagi)\s*(?:kaydır|kaydir|scroll)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'down'
                commands.append(step)
                continue
            
            if re.search(r'(?:yukarı|yukari)\s*(?:kaydır|kaydir|scroll)', line, re.IGNORECASE):
                step.action = 'scroll'
                step.target = 'up'
                commands.append(step)
                continue
            
            if re.search(r'backspace|geri\s*sil', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'backspace'
                commands.append(step)
                continue

            if re.search(r'geri\s*(?:git|dön)?', line, re.IGNORECASE):
                step.action = 'back'
                commands.append(step)
                continue
            
            if re.search(r'(?:yenile|refresh)', line, re.IGNORECASE):
                step.action = 'refresh'
                commands.append(step)
                continue
            
            match = re.search(r'(sağ|sag|sol|yukarı|yukari|aşağı|asagi)\s*ok(?:\s*tuşuna?)?\s*bas', line, re.IGNORECASE)
            if match:
                _arrow_map = {'sağ': 'right', 'sag': 'right', 'sol': 'left',
                              'yukarı': 'up', 'yukari': 'up', 'aşağı': 'down', 'asagi': 'down'}
                step.action = 'press'
                step.target = _arrow_map[match.group(1).lower()]
                commands.append(step)
                continue

            if re.search(r'çift\s*boşluk|cift\s*bosluk', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'double_space'
                commands.append(step)
                continue

            if re.search(r'boşluk(?:\s*tuşuna?)?\s*bas|bosluk\s*tusuna?\s*bas', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'space'
                commands.append(step)
                continue

            if re.search(r'delete(?:\s*tuşuna?)?\s*bas|sil\s*tuşuna?\s*bas', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'delete'
                commands.append(step)
                continue

            if re.search(r'home\s*tuşuna?\s*bas', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'home'
                commands.append(step)
                continue

            if re.search(r'end\s*tuşuna?\s*bas', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'end'
                commands.append(step)
                continue

            if re.search(r'page\s*up', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'pageup'
                commands.append(step)
                continue

            if re.search(r'page\s*down', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'pagedown'
                commands.append(step)
                continue

            if re.search(r'tümünü\s*seç|tumunu\s*sec', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'ctrl+a'
                commands.append(step)
                continue

            if re.search(r'kopyala', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'ctrl+c'
                commands.append(step)
                continue

            if re.search(r'yapıştır|yapistir', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'ctrl+v'
                commands.append(step)
                continue

            if re.search(r'enter\s*(?:bas)?', line, re.IGNORECASE):
                step.action = 'press'
                step.target = 'enter'
                commands.append(step)
                continue
        
        return commands
    
    def run_test(self, url: str, steps: List[TestStep], headless: bool = True, 
                 stop_on_fail: bool = True, log_callback: Callable = None,
                 scenario_name: str = "Test") -> Dict[str, Any]:
        """Test çalıştır - VARSAYILAN HEADLESS"""
        self.current_test_id = str(uuid.uuid4())[:8]
        self.test_results = []
        
        if log_callback:
            self.log_callback = log_callback
        
        results = []
        start_time = time.time()
        
        try:
            self.create_driver(headless)
            
            if url:
                if not url.startswith('http'):
                    url = 'https://' + url
                self.driver.get(url)
                time.sleep(2)
                initial_ss = self._take_screenshot()
                self._send_log(0, "navigate", "success", f"Başlangıç: {url}", initial_ss)
            
            for i, step in enumerate(steps):
                step_num = i + 1
                step_start = time.time()
                
                self._send_log(step_num, step.action, "running", step.target)
                
                test_result = WebTestResult()
                test_result.step_number = step_num
                test_result.action = step.action
                test_result.target = step.target
                test_result.timestamp = datetime.now().isoformat()
                
                try:
                    action_result = self.execute_action(step.action, step.target, step.value, step.locator_type)
                    test_result.success = action_result.get("success", True)
                    test_result.message = action_result.get("message", "")
                except Exception as e:
                    test_result.success = False
                    test_result.message = str(e)
                
                time.sleep(0.3)
                screenshot = self._take_screenshot()
                test_result.screenshot = screenshot
                test_result.duration = round(time.time() - step_start, 2)
                
                if screenshot:
                    self._save_screenshot(step_num, screenshot)
                
                self.test_results.append(test_result)
                
                step_result = StepResult(
                    step_number=step_num,
                    action=step.action,
                    success=test_result.success,
                    message=test_result.message
                )
                results.append(step_result)
                
                status = "success" if test_result.success else "failed"
                self._send_log(step_num, step.action, status, test_result.message, screenshot)
                
                print(f"[WEB] Adım {step_num}/{len(steps)}: {step.action} -> {'✓' if test_result.success else '✗'}")
                
                if not test_result.success and stop_on_fail:
                    break
            
            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            
            return {
                "test_id": self.current_test_id,
                "success": failed == 0,
                "message": "Test tamamlandı" if failed == 0 else "Test başarısız",
                "summary": {"total": len(steps), "executed": len(results), "passed": passed, "failed": failed},
                "results": results,
                "detailed_results": [
                    {"step_number": r.step_number, "action": r.action, "target": r.target,
                     "success": r.success, "message": r.message, "screenshot": r.screenshot, "duration": r.duration}
                    for r in self.test_results
                ],
                "duration": round(time.time() - start_time, 2),
                "scenario_name": scenario_name
            }
        except Exception as e:
            return {"test_id": self.current_test_id, "success": False, "message": str(e), 
                    "results": results, "duration": round(time.time() - start_time, 2)}
        finally:
            self.close_driver()
    
    def generate_pdf_report(self, scenario_name: str = "Test Raporu") -> Optional[str]:
        """PDF rapor oluştur"""
        if not PDF_AVAILABLE:
            print("[SELENIUM] reportlab yüklü değil")
            return None
        if not self.test_results:
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = re.sub(r'[^\w\s-]', '', scenario_name).strip().replace(' ', '_')
            filename = f"{safe_name}_{timestamp}.pdf"
            filepath = self.reports_dir / filename
            
            doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
            
            styles = getSampleStyleSheet()
            story = []
            
            title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, spaceAfter=30)
            story.append(Paragraph(f"{scenario_name}", title_style))
            story.append(Paragraph(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles['Normal']))
            story.append(Paragraph(f"Test ID: {self.current_test_id}", styles['Normal']))
            story.append(Spacer(1, 20))
            
            passed = sum(1 for r in self.test_results if r.success)
            failed = sum(1 for r in self.test_results if not r.success)
            
            summary_data = [
                ['Toplam', 'Basarili', 'Basarisiz', 'Durum'],
                [str(len(self.test_results)), str(passed), str(failed), 
                 'BASARILI' if failed == 0 else 'BASARISIZ']
            ]
            summary_table = Table(summary_data, colWidths=[35*mm, 35*mm, 35*mm, 45*mm])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(summary_table)
            story.append(Spacer(1, 30))
            
            story.append(Paragraph("Test Adimlari", styles['Heading2']))
            story.append(Spacer(1, 10))
            
            for result in self.test_results:
                status_text = "[OK]" if result.success else "[FAIL]"
                step_title = f"{status_text} Adim {result.step_number}: {result.action}"
                if result.target:
                    step_title += f" - '{result.target}'"
                
                story.append(Paragraph(step_title, styles['Heading3']))
                if result.message:
                    story.append(Paragraph(f"Sonuc: {result.message}", styles['Normal']))
                
                if result.screenshot:
                    try:
                        temp_path = self.screenshots_dir / f"temp_{result.step_number}.png"
                        with open(temp_path, "wb") as f:
                            f.write(base64.b64decode(result.screenshot))
                        img = Image(str(temp_path), width=160*mm, height=90*mm)
                        story.append(img)
                        temp_path.unlink()
                    except:
                        pass
                
                story.append(Spacer(1, 15))
            
            doc.build(story)
            print(f"[SELENIUM] PDF: {filepath}")
            return str(filepath)
        except Exception as e:
            print(f"[SELENIUM] PDF hatası: {e}")
            return None


selenium_service = SeleniumService()