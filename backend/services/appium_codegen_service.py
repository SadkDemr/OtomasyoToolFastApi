"""
Appium Java Kod Üretici - Ortak Çekirdek
=========================================
Java Generator ve BDD Generator'ın paylaştığı kısım:
  - Locator XPath üretimi (çoklu attribute + index)
  - Normalize edilmiş adım (action) -> Java satırları
  - Android/iOS test şablonları (capabilities, driver init, try/finally)

Davranış referansı BDD Generator'dır (üretimde çalışan taraf) — Java Generator
bu modülü kullanarak aynı locator/wait/assert stiline hizalanır.
"""

import re
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1: XPATH
# ══════════════════════════════════════════════════════════════════════════════

def extract_xpath_value(xpath: str) -> Optional[str]:
    """
    XPath içinden attribute değerini çıkarır.
    Öncelik: @name > @label > @value > @text

    "//XCUIElementTypeTextField[@name='textField']"        → "textField"
    "(//XCUIElementTypeTextField[@name='textField'])[1]"   → "textField"
    "//XCUIElementTypeButton[@value='Kullanıcı ayarları']" → "Kullanıcı ayarları"
    """
    clean = re.sub(r'^\((.+)\)\[\d+\]$', r'\1', xpath.strip())

    for attr in ('name', 'label', 'value', 'text'):
        m = re.search(rf"@{attr}='([^']+)'", clean)
        if m:
            return m.group(1)
        m = re.search(rf'@{attr}="([^"]+)"', clean)
        if m:
            return m.group(1)

    return None


def extract_xpath_index(xpath: str) -> int:
    """XPath sonundaki index değerini döner. Yoksa default 1."""
    m = re.search(r'\)\[(\d+)\]$', xpath.strip())
    return int(m.group(1)) if m else 1


def build_ios_xpath(value: str, index: int = 1) -> str:
    v = value.replace("'", "\\'")
    return f"(//*[@name='{v}' or @label='{v}' or @value='{v}'])[{index}]"


def build_android_xpath(value: str, index: int = 1) -> str:
    v = value.replace("'", "\\'")
    return f"(//*[@text='{v}' or @content-desc='{v}'])[{index}]"


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2: JAVA SATIR ÜRETİCİ (action → Java)
# ══════════════════════════════════════════════════════════════════════════════

def je(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def action_to_java(
    action:      str,
    xpath_val:   Optional[str],
    param:       Optional[str],
    raw_step:    str,
    platform:    str,
    full_xpath:  Optional[str] = None,
    xpath_index: int = 1,
) -> tuple[list[str], str]:
    """
    Normalize edilmiş bir adımı ({action, element, param}) Java satırlarına çevirir.
    Returns (java_lines, method)
    method: "mapped" | "page" | "todo"
    full_xpath: attribute çıkarılamadığında direkt kullanılacak ham XPath
    xpath_index: XPath'teki index değeri (yoksa default 1)
    """
    is_ios = platform.lower() != "android"

    # ── Page context ─────────────────────────────────────────────────────────
    if action == "page_context":
        return ([f'// PAGE: {param or ""}', 'Thread.sleep(500);'], "page")

    # ── Klavye gizle ─────────────────────────────────────────────────────────
    if action == "hide_keyboard":
        return ([
            f'// {raw_step}',
            'try { driver.hideKeyboard(); } catch (Exception ignored) {}',
        ], "mapped")

    # ── Ekran görüntüsü ───────────────────────────────────────────────────────
    if action == "screenshot":
        return ([
            f'// {raw_step}',
            '// File shot = driver.getScreenshotAs(OutputType.FILE);',
        ], "mapped")

    # ── Wait ─────────────────────────────────────────────────────────────────
    if action == "wait":
        ms = int(param) * 1000 if param and str(param).isdigit() else 2000
        return ([f'// {raw_step}', f'Thread.sleep({ms});'], "mapped")

    # ── Scroll / Kaydır ───────────────────────────────────────────────────────
    if action in ("scroll_down", "scroll_up"):
        direction = "down" if action == "scroll_down" else "up"
        if is_ios:
            code = (f'{{ Map<String, Object> _sc = new HashMap<>();'
                    f' _sc.put("direction", "{direction}");'
                    f' driver.executeScript("mobile: scroll", _sc); }}')
        else:
            code = f'driver.executeScript("mobile:scroll", ImmutableMap.of("direction", "{direction}"));'
        return ([f'// {raw_step}', code], "mapped")

    # ── Sola / Sağa swipe ─────────────────────────────────────────────────────
    if action in ("swipe_left", "swipe_right"):
        direction = "left" if action == "swipe_left" else "right"
        if is_ios:
            code = (f'{{ Map<String, Object> _sw = new HashMap<>();'
                    f' _sw.put("direction", "{direction}");'
                    f' driver.executeScript("mobile: swipe", _sw); }}')
        else:
            code = f'driver.executeScript("mobile:scroll", ImmutableMap.of("direction", "{direction}"));'
        return ([f'// {raw_step}', code], "mapped")

    # ── Back ─────────────────────────────────────────────────────────────────
    if action == "back":
        if is_ios:
            code = 'driver.navigate().back();'
        else:
            code = 'driver.pressKey(new KeyEvent(AndroidKey.BACK));'
        return ([f'// {raw_step}', code], "mapped")

    # ── Type (element lookup yok, aktif elemana yazar) ────────────────────────
    if action == "type":
        value = je(param or "")
        if is_ios:
            type_line = f'driver.switchTo().activeElement().sendKeys("{value}");'
        else:
            type_line = f'driver.executeScript("mobile: type", Map.of("text", "{value}"));'
        return ([
            f'// {raw_step}',
            type_line,
            'try { driver.hideKeyboard(); } catch (Exception ignored) {}',
        ], "mapped")

    # ── Element görünene kadar bekle (sade findElement) ───────────────────────
    if action == "wait_for_element":
        if xpath_val is None and full_xpath is None:
            return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")
        if xpath_val is not None:
            uxp = build_ios_xpath(xpath_val, xpath_index) if is_ios else build_android_xpath(xpath_val, xpath_index)
        else:
            uxp = je(full_xpath)
        if is_ios:
            line = f'driver.findElement(AppiumBy.xpath("{uxp}")).isDisplayed();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).isDisplayed();'
        return ([f'// {raw_step}', line], "mapped")

    # ── Element gerektiren aksiyonlar ─────────────────────────────────────────
    if xpath_val is None and full_xpath is None:
        return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")

    if xpath_val is not None:
        uxp = build_ios_xpath(xpath_val, xpath_index) if is_ios else build_android_xpath(xpath_val, xpath_index)
    else:
        uxp = je(full_xpath)

    if action == "click":
        if is_ios:
            line = f'driver.findElement(AppiumBy.xpath("{uxp}")).click();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).click();'
        return ([f'// {raw_step}', line], "mapped")

    if action == "clear":
        if is_ios:
            line = f'driver.findElement(AppiumBy.xpath("{uxp}")).clear();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).clear();'
        return ([f'// {raw_step}', line], "mapped")

    if action == "assert":
        if is_ios:
            line = f'driver.findElement(AppiumBy.xpath("{uxp}")).isDisplayed();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).isDisplayed();'
        return ([f'// {raw_step}', line], "mapped")

    return ([f'// TODO: {raw_step}'], "todo")


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3: ŞABLONLAR
# ══════════════════════════════════════════════════════════════════════════════

def safe_class_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]', '', name or "GeneratedTest") or "GeneratedTest"


def build_android_template(
    *,
    steps_code:       str,
    app_package:      Optional[str] = "",
    app_activity:     Optional[str] = "",
    udid:             Optional[str] = "",
    device_name:      Optional[str] = "Android Device",
    platform_version: Optional[str] = "15",
    appium_url:       Optional[str] = "http://localhost:4723",
    no_reset:         bool = True,
) -> str:
    pkg      = app_package      or ""
    act      = app_activity     or ""
    udid     = udid             or ""
    device   = device_name      or "Android Device"
    version  = platform_version or "15"
    appium   = appium_url       or "http://localhost:4723"
    no_reset_s = "true" if no_reset else "false"

    udid_line = f'\ncapabilities.setCapability("udid", "{udid}");'             if udid else ""
    act_line  = f'\ncapabilities.setCapability("appActivity", "{act}");'       if act  else ""
    pkg_line  = f'\ncapabilities.setCapability("appPackage", "{pkg}");'        if pkg  else ""
    restart_lines = (
        f'driver.terminateApp("{pkg}");\ndriver.activateApp("{pkg}");'
        if pkg else "// app_package girilmedi"
    )
    act_end = f'driver.terminateApp("{pkg}");' if pkg else ""

    body = steps_code.rstrip()

    return f"""\
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.nativekey.AndroidKey;
import io.appium.java_client.android.nativekey.KeyEvent;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import com.google.common.collect.ImmutableMap;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "Android");
capabilities.setCapability("platformVersion", "{version}");
capabilities.setCapability("deviceName", "{device}");{udid_line}
capabilities.setCapability("automationName", "UiAutomator2");{pkg_line}{act_line}
capabilities.setCapability("appium:noReset", {no_reset_s});

AndroidDriver driver = new AndroidDriver(new URL("{appium}"), capabilities);
driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(10));
// ── CONFIG END ────────────────────────────────────────────────────

{restart_lines}
Thread.sleep(2000);

// ── TEST ADIMLARI ─────────────────────────────────────────────────
{body}

// ── TEST SONU ─────────────────────────────────────────────────────
{act_end}
driver.quit();
"""


def build_ios_template(
    *,
    steps_code:       str,
    bundle_id:        Optional[str] = "",
    udid:             Optional[str] = "",
    device_name:      Optional[str] = "iPhone Device",
    platform_version: Optional[str] = "18",
    appium_url:       Optional[str] = "http://localhost:4723",
    no_reset:         bool = True,
) -> str:
    bundle_id = bundle_id        or ""
    udid      = udid             or ""
    device    = device_name      or "iPhone Device"
    version   = platform_version or "18"
    appium    = appium_url       or "http://localhost:4723"
    no_reset_s = "true" if no_reset else "false"

    udid_line   = f'\ncapabilities.setCapability("udid", "{udid}");'          if udid      else ""
    bundle_line = f'\ncapabilities.setCapability("bundleId", "{bundle_id}");' if bundle_id else ""
    restart_lines = (
        f'driver.terminateApp("{bundle_id}");\n    driver.activateApp("{bundle_id}");'
        if bundle_id else "// bundle_id girilmedi"
    )
    terminate_line = f'driver.terminateApp("{bundle_id}");' if bundle_id else ""

    body = steps_code.rstrip()

    return f"""\
import io.appium.java_client.AppiumBy;
import io.appium.java_client.ios.IOSDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.DesiredCapabilities;
import java.net.URL;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;

// ── CONFIG ────────────────────────────────────────────────────────
DesiredCapabilities capabilities = new DesiredCapabilities();
capabilities.setCapability("platformName", "iOS");
capabilities.setCapability("platformVersion", "{version}");
capabilities.setCapability("deviceName", "{device}");{udid_line}
capabilities.setCapability("automationName", "XCUITest");{bundle_line}
capabilities.setCapability("noReset", {no_reset_s});
// ── CONFIG END ────────────────────────────────────────────────────

IOSDriver driver = null;

try {{
    driver = new IOSDriver(new URL("{appium}"), capabilities);
    driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(5));

    {restart_lines}
    Thread.sleep(2000);

// ── TEST ADIMLARI ─────────────────────────────────────────────────
{body}

// ── TEST SONU ─────────────────────────────────────────────────────
}} catch (Exception e) {{
    throw e;
}} finally {{
    if (driver != null) {{
        try {{ {terminate_line} }} catch (Exception ignored) {{}}
        driver.quit();
    }}
}}
"""
