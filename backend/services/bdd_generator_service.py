"""
BDD Generator Service
=====================
Gherkin BDD senaryolarını Java Appium koduna çevirir.
JSON mapping dosyasındaki XPath'leri kullanır.
"""

import re
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1: XPATH DEĞER ÇIKARICI
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


def _build_ios_xpath(value: str, index: int = 1) -> str:
    v = value.replace("'", "\\'")
    return f"(//*[@name='{v}' or @label='{v}' or @value='{v}'])[{index}]"


def _build_android_xpath(value: str, index: int = 1) -> str:
    v = value.replace("'", "\\'")
    return f"(//*[@text='{v}' or @content-desc='{v}'])[{index}]"


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2: GERKİN PARSER
# ══════════════════════════════════════════════════════════════════════════════

_STEP_KW = ('given', 'when', 'then', 'and', 'but', '*')
_SKIP_PREFIXES = ('feature:', 'scenario:', 'background:', 'examples:', 'scenario outline:', '|', '@', '#')


def parse_bdd_steps(text: str) -> list[dict]:
    """
    BDD metnini adımlara ayrıştırır.
    Returns: [{"keyword": "When", "text": "I click loginBtn", "raw": "When I click loginBtn"}]
    """
    steps = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _SKIP_PREFIXES):
            continue
        for kw in _STEP_KW:
            if lower.startswith(kw + ' '):
                steps.append({
                    "keyword": stripped[:len(kw)],
                    "text":    stripped[len(kw) + 1:].strip(),
                    "raw":     stripped,
                })
                break
    return steps


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3: STEP KLASİFİKATÖRÜ
# ══════════════════════════════════════════════════════════════════════════════

def _extract_quoted(text: str) -> list[str]:
    return re.findall(r'["""]([^"""]+)["""]', text)


def classify_step(text: str) -> dict:
    """
    Step metnini analiz eder; aksiyon türünü ve parametrelerini çıkarır.

    action türleri:
        page_context, click, clear, type, assert, wait,
        scroll_down, scroll_up, back, hide_keyboard,
        screenshot, swipe_left, swipe_right, unknown
    """
    t  = text.strip()
    tl = t.lower()

    # ── Klavye gizle ─────────────────────────────────────────────────────────
    if re.search(
        r'klavye.*kapat|klavye.*gizle|klavyeyi|hide.*keyboard|keyboard.*hide|dismiss.*keyboard',
        tl
    ):
        return {"action": "hide_keyboard", "element_key": None, "param": None, "page": None}

    # ── Ekran görüntüsü ───────────────────────────────────────────────────────
    if re.search(r'ekran\s*görüntüsü|screenshot|capture\s*screen', tl):
        return {"action": "screenshot", "element_key": None, "param": None, "page": None}

    # ── I see / see <page> page  →  page context switch ──────────────────────
    m = re.match(r'^(?:I\s+)?see (.+?) page$', t, re.IGNORECASE)
    if m:
        return {"action": "page_context", "element_key": None, "param": None, "page": m.group(1).strip()}

    # ── Türkçe bekleme: X saniye bekle / bekle X saniye ──────────────────────
    m = re.search(r'(\d+)\s*(?:saniye|sn)\s*bekle|bekle\s*(\d+)\s*(?:saniye|sn)', tl)
    if m:
        sec = m.group(1) or m.group(2)
        return {"action": "wait", "element_key": None, "param": sec, "page": None}

    # ── wait for N seconds / I wait N / wait N seconds ───────────────────────
    m = re.search(r'wait\s+(?:for\s+)?(\d+)\s+seconds?', tl)
    if m:
        return {"action": "wait", "element_key": None, "param": m.group(1), "page": None}
    m = re.match(r'^I wait (\d+)', t, re.IGNORECASE)
    if m:
        return {"action": "wait", "element_key": None, "param": m.group(1), "page": None}

    # ── Scroll / Kaydır ───────────────────────────────────────────────────────
    if re.search(r'scroll\s*down|swipe\s*down|aşağı.*kaydır|kaydır.*aşağı|aşağı.*scroll', tl):
        return {"action": "scroll_down", "element_key": None, "param": None, "page": None}
    if re.search(r'scroll\s*up|swipe\s*up|yukarı.*kaydır|kaydır.*yukarı|yukarı.*scroll', tl):
        return {"action": "scroll_up", "element_key": None, "param": None, "page": None}

    # ── Sola / Sağa swipe ─────────────────────────────────────────────────────
    if re.search(r'swipe\s*left|sola\s*kaydır|sola\s*swipe', tl):
        return {"action": "swipe_left", "element_key": None, "param": None, "page": None}
    if re.search(r'swipe\s*right|sağa\s*kaydır|sağa\s*swipe', tl):
        return {"action": "swipe_right", "element_key": None, "param": None, "page": None}

    # ── Geri ─────────────────────────────────────────────────────────────────
    if re.search(r'swipe\s*back|go\s*back|geri\s*git|geri\s*dön|geri\s*gel|^geri$', tl):
        return {"action": "back", "element_key": None, "param": None, "page": None}

    # ── Türkçe tıklama: "text" tıkla / tıkla "text" ──────────────────────────
    m = re.match(r'^["""]([^"""]+)["""]\s*(?:tıkla|bas|seç|dokun|üzerine\s*tıkla|üstüne\s*tıkla)', t, re.IGNORECASE)
    if m:
        return {"action": "click", "element_key": f'"{m.group(1)}"', "param": None, "page": None}
    m = re.match(r'^(?:tıkla|bas|seç)\s+["""]([^"""]+)["""]', t, re.IGNORECASE)
    if m:
        return {"action": "click", "element_key": f'"{m.group(1)}"', "param": None, "page": None}

    # ── Türkçe metin giriş: "text" yaz / "text" gir ──────────────────────────
    m = re.match(r'^["""]([^"""]+)["""]\s*(?:yaz|gir|girişi\s*yap|değerini\s*gir)$', t, re.IGNORECASE)
    if m:
        return {"action": "type", "element_key": None, "param": m.group(1), "page": None}

    # ── Türkçe temizle: "element" temizle / "element" sil ────────────────────
    m = re.match(r'^["""]([^"""]+)["""]\s*(?:temizle|sil)$', t, re.IGNORECASE)
    if m:
        return {"action": "clear", "element_key": m.group(1), "param": None, "page": None}
    m = re.match(r'^(?:temizle|sil)\s+["""]([^"""]+)["""]$', t, re.IGNORECASE)
    if m:
        return {"action": "clear", "element_key": m.group(1), "param": None, "page": None}

    # ── Türkçe assert: "text" görünüyor / gözüküyor ───────────────────────────
    m = re.match(
        r'^["""]([^"""]+)["""]\s*(?:görün|gözük|var\s*mı|görülsün|görüntülen|kontrol|ekranda)',
        t, re.IGNORECASE
    )
    if m:
        return {"action": "assert", "element_key": f'"{m.group(1)}"', "param": None, "page": None}

    # ── <element> element in <n> second(s) → element görünene kadar bekle ──────
    m = re.match(r'^(.+?)\s+element\s+in\s+(\d+)\s+seconds?$', t, re.IGNORECASE)
    if m:
        return {"action": "wait_for_element", "element_key": m.group(1).strip(), "param": m.group(2), "page": None}

    # ── <element> elementini <n> saniye bekle ─────────────────────────────────
    m = re.match(r'^(.+?)\s+elementini?\s+(\d+)\s+(?:saniye|sn)\s*bekle$', t, re.IGNORECASE)
    if m:
        return {"action": "wait_for_element", "element_key": m.group(1).strip(), "param": m.group(2), "page": None}

    # ── click / I click / tap / I tap <element> [element] ────────────────────
    m = re.match(r'^(?:I\s+)?(?:click|tap) (.+?)(?:\s+element)?$', t, re.IGNORECASE)
    if m:
        return {"action": "click", "element_key": m.group(1).strip(), "param": None, "page": None}

    # ── I am sil with / sil with <element> ───────────────────────────────────
    m = re.match(r'^(?:I\s+)?(?:am\s+)?sil\s+with (.+?)(?:\s+element)?$', t, re.IGNORECASE)
    if m:
        return {"action": "clear", "element_key": m.group(1).strip(), "param": None, "page": None}

    # ── type / I type "text" ──────────────────────────────────────────────────
    m = re.match(r'^(?:I\s+)?type (.+)$', t, re.IGNORECASE)
    if m:
        quoted = _extract_quoted(m.group(1))
        param  = quoted[0] if quoted else m.group(1).strip('"\'')
        return {"action": "type", "element_key": None, "param": param, "page": None}

    # ── see / I see <element> [element]  →  assert ───────────────────────────
    m = re.match(r'^(?:I\s+)?see (.+?)(?:\s+element)?$', t, re.IGNORECASE)
    if m:
        return {"action": "assert", "element_key": m.group(1).strip(), "param": None, "page": None}

    return {"action": "unknown", "element_key": None, "param": None, "page": None}


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4: JAVA SATIR ÜRETİCİ
# ══════════════════════════════════════════════════════════════════════════════

def _je(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _action_to_java(
    action:      str,
    xpath_val:   Optional[str],
    param:       Optional[str],
    raw_step:    str,
    platform:    str,
    full_xpath:  Optional[str] = None,
    xpath_index: int = 1,
) -> tuple[list[str], str]:
    """
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
        ms = int(param) * 1000 if param and param.isdigit() else 2000
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

    # ── Type (element lookup yok) ─────────────────────────────────────────────
    if action == "type":
        value = _je(param or "")
        return ([
            f'// {raw_step}',
            f'driver.executeScript("mobile: type", Map.of("text", "{value}"));',
            'try { driver.hideKeyboard(); } catch (Exception ignored) {}',
        ], "mapped")

    # ── Element görünene kadar bekle ─────────────────────────────────────────
    if action == "wait_for_element":
        if xpath_val is None and full_xpath is None:
            return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")
        uxp = _build_ios_xpath(xpath_val, xpath_index) if (xpath_val and is_ios) else (
              _build_android_xpath(xpath_val, xpath_index) if xpath_val else _je(full_xpath))
        secs = int(param) if param and str(param).isdigit() else 20
        if is_ios:
            line = (f'new WebDriverWait(driver, Duration.ofSeconds({secs}))'
                    f'.until(ExpectedConditions.visibilityOfElementLocated(AppiumBy.xpath("{uxp}")));')
        else:
            line = (f'new WebDriverWait(driver, Duration.ofSeconds({secs}))'
                    f'.until(ExpectedConditions.visibilityOfElementLocated(By.xpath("{uxp}")));')
        return ([f'// {raw_step}', line], "mapped")

    # ── Element gerektiren aksiyonlar ─────────────────────────────────────────
    if xpath_val is None and full_xpath is None:
        return ([f'// TODO (element bulunamadı): {raw_step}'], "todo")

    # Attribute değeri varsa index ile XPath üret, yoksa ham XPath'i direkt kullan
    if xpath_val is not None:
        uxp = _build_ios_xpath(xpath_val, xpath_index) if is_ios else _build_android_xpath(xpath_val, xpath_index)
    else:
        uxp = _je(full_xpath)

    if action == "click":
        if is_ios:
            line = f'wait.until(ExpectedConditions.elementToBeClickable(AppiumBy.xpath("{uxp}"))).click();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).click();'
        return ([f'// {raw_step}', line], "mapped")

    if action == "clear":
        if is_ios:
            line = f'wait.until(ExpectedConditions.elementToBeClickable(AppiumBy.xpath("{uxp}"))).clear();'
        else:
            line = f'driver.findElement(By.xpath("{uxp}")).clear();'
        return ([f'// {raw_step}', line], "mapped")

    if action == "assert":
        if is_ios:
            line = f'wait.until(ExpectedConditions.visibilityOfElementLocated(AppiumBy.xpath("{uxp}"))).isDisplayed();'
        else:
            line = f'assertTrue(driver.findElement(By.xpath("{uxp}")).isDisplayed());'
        return ([f'// {raw_step}', line], "mapped")

    return ([f'// TODO: {raw_step}'], "todo")


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 5: ANA FONKSİYON
# ══════════════════════════════════════════════════════════════════════════════

def generate_bdd_java(
    bdd_text: str,
    mappings: dict,   # {"pageName": {"elementKey": "//xpath...", ...}, ...}
    platform: str = "ios",
) -> dict:
    """
    BDD metnini parse edip Java kod bloklarına çevirir.

    Returns:
        steps_code : str         — test adımları Java kodu
        report     : list[dict]  — her adım için analiz
        warnings   : list[str]   — bulunamayan elementler
    """
    steps        = parse_bdd_steps(bdd_text)
    current_page = next(iter(mappings), None)  # ilk sayfa varsayılan

    code_blocks: list[str] = []
    report:      list[dict] = []
    warnings:    list[str]  = []

    for step in steps:
        classified  = classify_step(step["text"])
        action      = classified["action"]
        element_key = classified["element_key"]
        param       = classified["param"]

        # ── Page context değişimi ─────────────────────────────────────────
        if action == "page_context":
            new_page = classified["page"]
            if new_page and new_page in mappings:
                current_page = new_page
            elif new_page:
                warnings.append(f"'{new_page}' sayfası için JSON mapping bulunamadı")
            java_lines, method = _action_to_java(action, None, new_page, step["raw"], platform)
            code_blocks.append("\n".join(java_lines))
            report.append({"step": step["raw"], "method": "page", "page": new_page, "xpath_value": None})
            continue

        # ── Element arama ────────────────────────────────────────────────
        xpath_value = None
        full_xpath  = None
        xpath_index = 1
        found_page  = None

        if element_key:
            # Tırnak içinde literal metin → direkt kullan, JSON'a bakma
            _quoted = re.match(r'^["""]([^"""]+)["""]$', element_key)
            if _quoted:
                xpath_value = _quoted.group(1)
            else:
                # Önce aktif sayfada ara
                if current_page and current_page in mappings and element_key in mappings[current_page]:
                    full_xpath  = mappings[current_page][element_key]
                    xpath_value = extract_xpath_value(full_xpath)
                    xpath_index = extract_xpath_index(full_xpath)
                    found_page  = current_page
                else:
                    # Tüm sayfalarda tara
                    for pname, pmap in mappings.items():
                        if element_key in pmap:
                            full_xpath  = pmap[element_key]
                            xpath_value = extract_xpath_value(full_xpath)
                            xpath_index = extract_xpath_index(full_xpath)
                            found_page  = pname
                            break

                if xpath_value is None and full_xpath is None:
                    warnings.append(
                        f"Element bulunamadı: '{element_key}'"
                        + (f" (sayfa: {current_page})" if current_page else "")
                    )

        java_lines, method = _action_to_java(
            action, xpath_value, param or element_key, step["raw"], platform, full_xpath, xpath_index
        )
        code_blocks.append("\n".join(java_lines))
        report.append({
            "step":        step["raw"],
            "method":      method,
            "page":        found_page or current_page,
            "xpath_value": xpath_value,
        })

    return {
        "steps_code": "\n\n".join(code_blocks),
        "report":     report,
        "warnings":   warnings,
    }
