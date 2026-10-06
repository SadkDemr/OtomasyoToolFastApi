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


def _xp_literal(value: str) -> str:
    """XPath 1.0 string literal'i. XPath'te \\' kaçışı yoktur — değerde tek
    tırnak varsa (Ali'nin Hesabı) çift tırnakla sarılır, ikisi de varsa concat()."""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in value.split("'")) + ")"


def build_ios_xpath(value: str, index: int = 1) -> str:
    v = _xp_literal(value)
    return f"(//*[@name={v} or @label={v} or @value={v}])[{index}]"


def build_android_xpath(value: str, index: int = 1) -> str:
    v = _xp_literal(value)
    return f"(//*[@text={v} or @content-desc={v}])[{index}]"


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2: JAVA SATIR ÜRETİCİ (action → Java)
# ══════════════════════════════════════════════════════════════════════════════

def je(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


# ── Değişken desteği: ${Ad} → vars.get("Ad") ─────────────────────────────────
# Test adımlarında ${Ornek_Data} gibi yazılan yer tutucular sabit metin olarak
# değil, JMeter JSR223 bağlamındaki `vars` sözlüğünden okunacak şekilde üretilir.
_VAR_RE  = re.compile(r'\$\{\s*([A-Za-z0-9_\-.]+)\s*\}')
_XP_SLOT = '\x01'  # XPath şablonunda değerin geçtiği yerleri işaretlemek için


def has_vars(text: Optional[str]) -> bool:
    return bool(text) and bool(_VAR_RE.search(text))


def java_value_expr(text: Optional[str]) -> str:
    """
    Metni Java string ifadesine çevirir; ${X} → vars.get("X").

    "${Ornek_Data}"   → vars.get("Ornek_Data")
    "TR${Iban} nolu"  → "TR" + vars.get("Iban") + " nolu"
    "düz metin"       → "düz metin"   (tırnaklar dahil)
    """
    if not text:
        return '""'
    parts: list[str] = []
    last = 0
    for m in _VAR_RE.finditer(text):
        if m.start() > last:
            parts.append(f'"{je(text[last:m.start()])}"')
        parts.append(f'vars.get("{m.group(1)}")')
        last = m.end()
    if last < len(text):
        parts.append(f'"{je(text[last:])}"')
    return ' + '.join(parts) if parts else '""'


def _xpath_java(
    xpath_val:   Optional[str],
    full_xpath:  Optional[str],
    xpath_index: int,
    is_ios:      bool,
) -> tuple[list[str], str]:
    """
    XPath'i Java ifadesi olarak üretir.

    Değişken yoksa düz string literal döner ("(//*[@text='X'])[1]").
    ${X} varsa önce `String _xv = vars.get("X");` satırı üretilir ve XPath bu
    değişkenle birleştirilir — aynı değer XPath içinde birden çok attribute
    için tekrarlandığından tek değişkende toplamak hem kısa hem okunur.

    Returns (prelude_lines, xpath_java_expression)
    """
    if xpath_val is None:
        return [], f'"{je(full_xpath or "")}"'
    if not has_vars(xpath_val):
        uxp = build_ios_xpath(xpath_val, xpath_index) if is_ios else build_android_xpath(xpath_val, xpath_index)
        return [], f'"{je(uxp)}"'

    tmpl = build_ios_xpath(_XP_SLOT, xpath_index) if is_ios else build_android_xpath(_XP_SLOT, xpath_index)
    segs = tmpl.split(_XP_SLOT)
    parts: list[str] = []
    for i, seg in enumerate(segs):
        if seg:
            parts.append(f'"{je(seg)}"')
        if i < len(segs) - 1:
            parts.append('_xv')
    return [f'String _xv = {java_value_expr(xpath_val)};'], ' + '.join(parts)


def _wrap(prelude: list[str], lines: list[str]) -> list[str]:
    """Yerel değişken tanımı gereken adımları `{ }` bloğuna alır — aynı isimli
    değişken (_xv) birden çok adımda tanımlandığında derleme hatası olmasın."""
    if not prelude:
        return lines
    return ['{'] + [f'    {l}' for l in prelude + lines] + ['}']


def _build_swipe_java(direction: str) -> str:
    """W3C Actions (Selenium 4 PointerInput/Sequence) tabanlı kaydırma.
    Appium 2'nin TouchAction/mobile-command yerine önerdiği standart yöntem —
    Android ve iOS'ta birebir aynı kodla çalışır. Eskiden kullanılan
    driver.executeScript("mobile:scroll" / "mobile: scroll", ...) çağrıları
    sürücü/versiyona göre isim değiştirdiği için .jmx gibi ortamlarda
    çalışmıyordu; bu yöntem doğrudan Selenium API'sini kullandığı için
    sürücüden bağımsızdır."""
    if direction in ("down", "up"):
        start_y, end_y = ("0.75", "0.25") if direction == "down" else ("0.25", "0.75")
        return (
            '{\n'
            '    Dimension _sz = driver.manage().window().getSize();\n'
            '    int _x = _sz.width / 2;\n'
            f'    int _startY = (int) (_sz.height * {start_y});\n'
            f'    int _endY   = (int) (_sz.height * {end_y});\n'
            '    PointerInput _finger = new PointerInput(PointerInput.Kind.TOUCH, "finger");\n'
            '    Sequence _swipe = new Sequence(_finger, 1);\n'
            '    _swipe.addAction(_finger.createPointerMove(Duration.ZERO, PointerInput.Origin.viewport(), _x, _startY));\n'
            '    _swipe.addAction(_finger.createPointerDown(0));\n'
            '    _swipe.addAction(_finger.createPointerMove(Duration.ofMillis(400), PointerInput.Origin.viewport(), _x, _endY));\n'
            '    _swipe.addAction(_finger.createPointerUp(0));\n'
            '    driver.perform(Arrays.asList(_swipe));\n'
            '}'
        )
    start_x, end_x = ("0.8", "0.2") if direction == "left" else ("0.2", "0.8")
    return (
        '{\n'
        '    Dimension _sz = driver.manage().window().getSize();\n'
        '    int _y = _sz.height / 2;\n'
        f'    int _startX = (int) (_sz.width * {start_x});\n'
        f'    int _endX   = (int) (_sz.width * {end_x});\n'
        '    PointerInput _finger = new PointerInput(PointerInput.Kind.TOUCH, "finger");\n'
        '    Sequence _swipe = new Sequence(_finger, 1);\n'
        '    _swipe.addAction(_finger.createPointerMove(Duration.ZERO, PointerInput.Origin.viewport(), _startX, _y));\n'
        '    _swipe.addAction(_finger.createPointerDown(0));\n'
        '    _swipe.addAction(_finger.createPointerMove(Duration.ofMillis(400), PointerInput.Origin.viewport(), _endX, _y));\n'
        '    _swipe.addAction(_finger.createPointerUp(0));\n'
        '    driver.perform(Arrays.asList(_swipe));\n'
        '}'
    )


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
    # W3C Actions tabanlı — Android/iOS'ta aynı kod, sürücüye özel "mobile:"
    # komut isimlerine bağımlı değil (bkz. _build_swipe_java).
    if action in ("scroll_down", "scroll_up"):
        direction = "down" if action == "scroll_down" else "up"
        return ([f'// {raw_step}', _build_swipe_java(direction)], "mapped")

    # ── Sola / Sağa swipe ─────────────────────────────────────────────────────
    if action in ("swipe_left", "swipe_right"):
        direction = "left" if action == "swipe_left" else "right"
        return ([f'// {raw_step}', _build_swipe_java(direction)], "mapped")

    # ── Uzun bas / basılı tut ────────────────────────────────────────────────
    if action == "long_press":
        if xpath_val is None and full_xpath is None:
            return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")
        _pre, _xp = _xpath_java(xpath_val, full_xpath, xpath_index, is_ios)
        by_cls = "AppiumBy" if is_ios else "By"
        return ([
            f'// {raw_step}',
            '{',
            *[f'    {l}' for l in _pre],
            f'    WebElement _el = driver.findElement({by_cls}.xpath({_xp}));',
            '    PointerInput _finger = new PointerInput(PointerInput.Kind.TOUCH, "finger");',
            '    Sequence _press = new Sequence(_finger, 1);',
            '    _press.addAction(_finger.createPointerMove(Duration.ZERO, PointerInput.Origin.element(_el), 0, 0));',
            '    _press.addAction(_finger.createPointerDown(0));',
            '    _press.addAction(new org.openqa.selenium.interactions.Pause(_finger, Duration.ofMillis(1200)));',
            '    _press.addAction(_finger.createPointerUp(0));',
            '    driver.perform(Arrays.asList(_press));',
            '}',
        ], "mapped")

    # ── Back ─────────────────────────────────────────────────────────────────
    if action == "back":
        if is_ios:
            code = 'driver.navigate().back();'
        else:
            code = 'driver.pressKey(new KeyEvent(AndroidKey.BACK));'
        return ([f'// {raw_step}', code], "mapped")

    # ── Type ─────────────────────────────────────────────────────────────────
    # Hedef eleman biliniyorsa (xpath_val/full_xpath) o elemanı bulup tıklayıp
    # doğrudan üzerine yazar — activeElement() ile arada yarış durumu (race
    # condition) oluşmaz. Eleman bilinmiyorsa (örn. "sadece yaz" / "121212
    # girilir" gibi hedefsiz adımlar) aktif elemana yazma stratejisine düşer.
    if action == "type":
        value = java_value_expr(param)  # ${X} → vars.get("X"), yoksa tırnaklı literal
        if xpath_val is not None or full_xpath is not None:
            _pre, _xp = _xpath_java(xpath_val, full_xpath, xpath_index, is_ios)
            by_cls = "AppiumBy" if is_ios else "By"
            return ([
                f'// {raw_step}',
                '{',
                *[f'    {l}' for l in _pre],
                f'    WebElement _el = driver.findElement({by_cls}.xpath({_xp}));',
                '    _el.click();',
                f'    _el.sendKeys({value});',
                '}',
                'try { driver.hideKeyboard(); } catch (Exception ignored) {}',
            ], "mapped")
        if is_ios:
            type_line = f'driver.switchTo().activeElement().sendKeys({value});'
        else:
            type_line = f'driver.executeScript("mobile: type", Map.of("text", {value}));'
        return ([
            f'// {raw_step}',
            type_line,
            'try { driver.hideKeyboard(); } catch (Exception ignored) {}',
        ], "mapped")

    # ── Element görünene kadar bekle (sade findElement) ───────────────────────
    if action == "wait_for_element":
        if xpath_val is None and full_xpath is None:
            return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")
        pre, xp = _xpath_java(xpath_val, full_xpath, xpath_index, is_ios)
        by_cls = "AppiumBy" if is_ios else "By"
        return ([f'// {raw_step}'] + _wrap(pre, [
            f'driver.findElement({by_cls}.xpath({xp})).isDisplayed();'
        ]), "mapped")

    # ── Element gerektiren aksiyonlar ─────────────────────────────────────────
    if xpath_val is None and full_xpath is None:
        return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")

    pre, xp = _xpath_java(xpath_val, full_xpath, xpath_index, is_ios)
    by_cls  = "AppiumBy" if is_ios else "By"

    if action == "click":
        return ([f'// {raw_step}'] + _wrap(pre, [
            f'driver.findElement({by_cls}.xpath({xp})).click();'
        ]), "mapped")

    if action == "clear":
        return ([f'// {raw_step}'] + _wrap(pre, [
            f'driver.findElement({by_cls}.xpath({xp})).clear();'
        ]), "mapped")

    if action == "assert":
        return ([f'// {raw_step}'] + _wrap(pre, [
            f'driver.findElement({by_cls}.xpath({xp})).isDisplayed();'
        ]), "mapped")

    # ── Negatif doğrulama: elemanın EKRANDA OLMAMASI ─────────────────────────
    # "'Cebe Havale' butonunun gelmediği görülür" gibi adımlar için.
    # findElement yerine findElements kullanılır (eleman yoksa exception değil
    # boş liste döner) ve implicit wait geçici olarak kısaltılır — aksi halde
    # her negatif kontrol, elemanı boşuna 10 sn beklediği için testi yavaşlatır.
    if action == "assert_not_visible":
        restore = 5 if is_ios else 10
        label   = je(xpath_val or full_xpath or "")
        inner   = pre + [
            'driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(2));',
            f'java.util.List<WebElement> _absent = driver.findElements({by_cls}.xpath({xp}));',
            f'driver.manage().timeouts().implicitlyWait(Duration.ofSeconds({restore}));',
            'boolean _gorunuyor = false;',
            'for (WebElement _e : _absent) {',
            '    try { if (_e.isDisplayed()) { _gorunuyor = true; break; } } catch (Exception ignored) {}',
            '}',
            'if (_gorunuyor) {',
            f'    throw new AssertionError("Görülmemesi gereken eleman ekranda: {label}");',
            '}',
        ]
        return ([f'// {raw_step}', '{'] + [f'    {l}' for l in inner] + ['}'], "mapped")

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
    act_end = (
        'try {\n'
        '    driver.executeScript("mobile: shell", Map.of(\n'
        '        "command", "am",\n'
        f'        "args", Arrays.asList("force-stop", "{pkg}")\n'
        '    ));\n'
        '} catch (Exception e) {\n'
        '    throw e;\n'
        '}'
    ) if pkg else "// app_package girilmedi"

    body = steps_code.rstrip()

    return f"""\
import io.appium.java_client.android.AndroidDriver;
import io.appium.java_client.android.nativekey.AndroidKey;
import io.appium.java_client.android.nativekey.KeyEvent;
import org.openqa.selenium.By;
import org.openqa.selenium.Dimension;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.interactions.PointerInput;
import org.openqa.selenium.interactions.Sequence;
import org.openqa.selenium.remote.DesiredCapabilities;
import java.net.URL;
import java.time.Duration;
import java.util.Arrays;
import java.util.Map;

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
import org.openqa.selenium.Dimension;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.interactions.PointerInput;
import org.openqa.selenium.interactions.Sequence;
import org.openqa.selenium.remote.DesiredCapabilities;
import org.openqa.selenium.support.ui.WebDriverWait;
import java.net.URL;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;

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
