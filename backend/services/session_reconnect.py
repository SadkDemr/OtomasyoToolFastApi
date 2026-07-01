"""
Session Reconnect Helpers
--------------------------
Var olan bir Selenium/Appium WebDriver session'ına, session_id + command_executor URL'i
ile YENİ session açmadan yeniden bağlanır. "Oturum Başlat" scripti driver'ı quit() etmeden
bırakır; bu fonksiyonlar sonraki bir Python sürecinden o session'a geri bağlanmak için kullanılır.

ÖNEMLİ (Task 1 spike bulgusu — bkz. docs/superpowers/specs/2026-07-01-step-run-comment-design.md):
"Oturum Başlat" tarafındaki script/subprocess normal şekilde (script sonu / sys.exit) BİTMEMELİ.
selenium.webdriver.common.service.Service.__del__, interpreter kapanırken Service nesnesi GC
edildiğinde chromedriver'ın /shutdown endpoint'ini çağırıp chromedriver+chrome'u kapatıyor —
driver.quit() hiç çağrılmasa bile. Tarayıcıyı canlı bırakmak için o script'in en sonunda
`os._exit(0)` çağrılması gerekir (normal interpreter shutdown/finalizer'ları atlar). Bu modüldeki
attach_* fonksiyonları zaten var olan (uzaktaki) bir session'a HTTP üzerinden bağlanır, kendi
Service alt-süreci başlatmaz; bu yüzden bu fonksiyonların çağrıldığı script normal şekilde
bitebilir — os._exit(0) kısıtı sadece session'ı İLK AÇAN script içindir.
"""
from selenium.webdriver import Remote as _SeleniumRemote
from selenium.webdriver.chrome.options import Options as _ChromeOptions


def attach_selenium_session(command_executor_url: str, session_id: str) -> _SeleniumRemote:
    class _AttachedRemote(_SeleniumRemote):
        def start_session(self, capabilities):
            # NOT: Remote.__init__ 'capabilities' adinda bir property expose eder
            # (read-only, self.caps'e delege eder) - dogrudan self.capabilities = {}
            # atamasi AttributeError firlatir. Gercek depolama alani self.caps.
            self.session_id = session_id
            self.caps = {}

    return _AttachedRemote(command_executor=command_executor_url, options=_ChromeOptions())


def attach_appium_session(command_executor_url: str, session_id: str):
    from appium.webdriver.webdriver import WebDriver as _AppiumRemote
    from appium.options.android import UiAutomator2Options

    class _AttachedAppiumRemote(_AppiumRemote):
        def start_session(self, capabilities):
            # Ayni sebep: Appium WebDriver da self.caps kullanir (self.capabilities
            # degil) - bkz. appium/webdriver/webdriver.py satir 337.
            self.session_id = session_id
            self.caps = {}

    return _AttachedAppiumRemote(command_executor_url, options=UiAutomator2Options())
