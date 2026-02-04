import time
import logging
import threading
from typing import Callable, Optional

from drivers.base_driver import BaseDriver
from core.scenario import Scenario, Action

class AutomationRunner:
    def __init__(self, driver: BaseDriver):
        self.driver = driver
        self.logger = logging.getLogger("Runner")
        self.is_running = False
        self.stop_requested = False
        self.current_thread = None
        self.action_delay = 0.5 # Default delay in seconds

    def run_scenario(self, scenario: Scenario, on_step_complete: Optional[Callable] = None, on_finish: Optional[Callable] = None):
        """
        Senaryoyu ayrı bir thread'de çalıştırır.
        """
        if self.is_running:
            self.logger.warning("Şu anda zaten bir senaryo çalışıyor.")
            return

        self.stop_requested = False
        self.is_running = True
        
        def _run():
            self.logger.info(f"Senaryo başlatıldı: {scenario.name}")
            success = True
            error_msg = ""
            
            for index, action in enumerate(scenario.actions):
                if self.stop_requested:
                    self.logger.info("Senaryo kullanıcı tarafından durduruldu.")
                    success = False
                    error_msg = "Kullanıcı durdurdu."
                    break

                self.logger.info(f"Adım {index + 1}/{len(scenario.actions)}: {action.type} - {action.description}")
                
                # Global stabilization delay
                if index > 0:
                    time.sleep(self.action_delay)
                    
                step_success = self._execute_action(action)

                if on_step_complete:
                    on_step_complete(index, step_success, action)

                if not step_success:
                    self.logger.error(f"Adım başarısız: {action.description}")
                    success = False
                    error_msg = f"Adım başarısız: {index+1}"
                    # Fail olduğunda durmalı mı? Şimdilik evet.
                    break
            
            self.is_running = False
            self.logger.info(f"Senaryo tamamlandı. Başarılı: {success}")
            if on_finish:
                on_finish(success, error_msg)

        self.current_thread = threading.Thread(target=_run)
        self.current_thread.daemon = True
        self.current_thread.start()

    def stop(self):
        """Çalışan senaryoyu durdurur."""
        if self.is_running:
            self.stop_requested = True
            self.logger.info("Durdurma isteği gönderildi...")

    def _execute_action(self, action: Action) -> bool:
        try:
            if action.type == "CLICK":
                target = action.params.get("target")
                text_hint = action.params.get("text_hint")
                button = action.params.get("button", "left")
                timeout = int(action.params.get("timeout", 10))
                return self.driver.click(target, timeout=timeout, text_hint=text_hint, button=button)
            
            elif action.type == "TYPE":
                text = action.params.get("text", "")
                interval = action.params.get("interval", 0.1)
                return self.driver.type_text(text, interval)
            
            elif action.type == "WAIT":
                seconds = float(action.params.get("seconds", 1.0))
                self.driver.wait(seconds)
                return True
            
            elif action.type == "LAUNCH_APP":
                path = action.params.get("path")
                return self.driver.launch_app(path)
            
            elif action.type == "ASSERT_EXISTS":
                target = action.params.get("target")
                timeout = int(action.params.get("timeout", 10))
                return self.driver.assert_exists(target, timeout)
            
            elif action.type == "VALIDATE_WINDOW":
                title = action.params.get("title")
                timeout = int(action.params.get("timeout", 5))
                return self.driver.validate_window(title, timeout)

            elif action.type == "VALIDATE_ELEMENT":
                window_title = action.params.get("window_title")
                element_name = action.params.get("element_name")
                timeout = int(action.params.get("timeout", 5))
                return self.driver.validate_element(window_title, element_name, timeout)
            
            elif action.type == "PRESS_KEY":
                key = action.params.get("key")
                return self.driver.press_key(key)

            elif action.type == "SCROLL":
                amount = int(action.params.get("amount", 0))
                return self.driver.scroll(amount)

            elif action.type == "READ_TEXT":
                region = action.params.get("region")
                result = self.driver.read_text(region)
                action.result = result
                return True
            
            else:
                self.logger.error(f"Bilinmeyen aksiyon tipi: {action.type}")
                return False
                
        except Exception as e:
            self.logger.error(f"Aksiyon hatası ({action.type}): {e}")
            return False
