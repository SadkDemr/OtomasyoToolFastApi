"""
BDD Generator Service
=====================
Gherkin BDD senaryolarını Java Appium koduna çevirir.
JSON mapping dosyasındaki XPath'leri kullanır.
"""

import re
import textwrap
from typing import Optional

from services.appium_codegen_service import (
    extract_xpath_value,
    extract_xpath_index,
    action_to_java as _action_to_java,
)


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

    # ── I see/click/tap <element> element in <n> seconds → wait_for_element ──
    m = re.match(r'^(?:I\s+)?(?:see|click|tap)\s+(.+?)\s+element\s+in\s+(\d+)\s+seconds?$', t, re.IGNORECASE)
    if m:
        return {"action": "wait_for_element", "element_key": m.group(1).strip(), "param": m.group(2), "page": None}

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
# (appium_codegen_service.action_to_java — Java Generator ile paylaşılıyor)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4.5: CUSTOM STEP PARSER (MySteps.java desteği)
# ══════════════════════════════════════════════════════════════════════════════

def _java_annotation_to_py_regex(pattern: str) -> str:
    r"""
    Java @And annotation string'ini Python regex'ine dönüştürür.
    Java kaynak \\w → dosyada çift backslash → Python'da \w (word char).
    """
    # Java source'daki çift backslash → tek backslash (regex meta)
    p = pattern.replace('\\\\', '\\')
    # Cucumber expression → regex
    p = p.replace('{int}',        r'(-?\d+)')
    p = p.replace('{float}',      r'(-?\d+\.?\d*)')
    p = p.replace('{string}',     r'"([^"]*)"')
    p = p.replace('{word}',       r'(\w+)')
    p = p.replace('{bigdecimal}', r'(-?\d+\.?\d*)')
    if not p.startswith('^'):
        p = '^' + p
    if not p.endswith('$'):
        p = p + '$'
    return p


_ANNOTATION_RE = re.compile(
    r'@(?:And|Given|When|Then|But)\s*\(\s*(?:value\s*=\s*)?"([^"]+)"\s*\)\s*'
    r'public\s+\S+\s+(\w+)\s*\(([^)]*)\)',
    re.DOTALL,
)

# Framework satırları: MobileDevice ve AppiumDriver driver = device.getDriver()
_FRAMEWORK_LINE_RE = re.compile(
    r'^\s*(?:'
    r'MobileDevice\s+\w+\s*=\s*\w+\.getCurrentDevice\(\)'
    r'|AppiumDriver<[^>]+>\s+\w+\s*=\s*\w+\.getDriver\(\)'
    r')\s*;',
)


def _extract_method_body(java_code: str, method_name: str) -> str:
    """Method imzasından sonraki süslü parantez bloğunu çıkarır."""
    pat = re.compile(
        rf'public\s+\S+\s+{re.escape(method_name)}\s*\([^)]*\)[^{{]*\{{',
        re.DOTALL,
    )
    m = pat.search(java_code)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(java_code) and depth:
        c = java_code[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        i += 1
    return java_code[m.end(): i - 1]


def _adapt_body(body: str) -> str:
    """
    Method body'yi standalone Appium koduna uyarlar:
      - MobileDevice / AppiumDriver driver = device.getDriver() satırlarını siler
      - device.getDriver()     → driver
      - device.findSelector(x) → By.xpath("/* x */")
    Ardından ortak indent'i kaldırır ve 4 boşluk ekler.
    """
    out = []
    for line in body.splitlines():
        if _FRAMEWORK_LINE_RE.match(line):
            continue
        if re.match(r'^\s*import\s+java\.util\s*;', line):
            continue
        line = re.sub(r'\b\w+\.getDriver\(\)', 'driver', line)
        line = re.sub(r'\b\w+\.findSelector\(([^)]+)\)', r'By.xpath("/* \1 */")', line)
        line = line.replace('MobileElement', 'WebElement')
        out.append(line)
    cleaned = textwrap.dedent('\n'.join(out)).strip()
    return '\n'.join('    ' + ln if ln.strip() else '' for ln in cleaned.splitlines())


def parse_java_custom_steps(java_code: str) -> list:
    """
    MySteps.java içindeki @And/@When/@Then/@Given adımlarını çıkarır.
    Returns: [{"pattern", "method_name", "param_types", "py_regex", "body"}]
    """
    results = []
    for m in _ANNOTATION_RE.finditer(java_code):
        annotation_pattern = m.group(1)
        method_name        = m.group(2)
        params_raw         = m.group(3).strip()

        param_types: list[str] = []
        if params_raw:
            for param in params_raw.split(','):
                parts = param.strip().split()
                if len(parts) >= 2:
                    param_types.append(parts[0])

        try:
            py_regex = _java_annotation_to_py_regex(annotation_pattern)
            re.compile(py_regex)
        except re.error:
            continue

        raw_body     = _extract_method_body(java_code, method_name)
        adapted_body = _adapt_body(raw_body) if raw_body else ""

        results.append({
            "pattern":     annotation_pattern,
            "method_name": method_name,
            "param_types": param_types,
            "py_regex":    py_regex,
            "body":        adapted_body,
        })
    return results


def match_custom_step(step_text: str, custom_steps: list) -> Optional[dict]:
    """Step metnini custom adım listesiyle eşleştirir; ilk eşleşeni döner."""
    for cs in custom_steps:
        try:
            m = re.match(cs["py_regex"], step_text, re.IGNORECASE)
            if m:
                return {**cs, "captured": list(m.groups())}
        except re.error:
            continue
    return None


def _custom_step_to_java(
    method_name: str,
    body:        str,
    raw_step:    str,
) -> tuple[list[str], str]:
    """
    Custom step için method body'yi inline eder.
    { } bloğu kullanarak değişken çakışmalarını önler.
    """
    if body:
        lines = [
            f'// ── {raw_step}',
            f'// [{method_name}()]',
            '{',
            body,
            '}',
        ]
    else:
        lines = [f'// TODO (body çıkarılamadı): {raw_step}']
    return (lines, "custom")


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 5: ANA FONKSİYON
# ══════════════════════════════════════════════════════════════════════════════

def generate_bdd_java(
    bdd_text:     str,
    mappings:     dict,     # {"pageName": {"elementKey": "//xpath...", ...}, ...}
    platform:     str  = "ios",
    custom_steps: list = None,  # parse_java_custom_steps() çıktısı
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
        # ── Custom step eşleşme (MySteps.java'dan yüklenenler) ────────────
        if custom_steps:
            cm = match_custom_step(step["text"], custom_steps)
            if cm:
                java_lines, _ = _custom_step_to_java(
                    cm["method_name"], cm.get("body", ""), step["raw"]
                )
                code_blocks.append("\n".join(java_lines))
                report.append({
                    "step":        step["raw"],
                    "method":      "custom",
                    "page":        current_page,
                    "xpath_value": cm["method_name"],
                })
                continue

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
        if java_lines:
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
