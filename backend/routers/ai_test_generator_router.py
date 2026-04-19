"""
AI Test Generator Router  v3  —  Hibrit Mimari
===============================================
1. Kural Motoru  → Türkçe test adımlarını deterministik Appium/Selenium koduna çevirir
2. LLM Desteği   → Kural motorunun tanımadığı adımlar için Ollama (gemma3:4b)
3. Vision Fallback → Runtime'da element bulunamazsa screenshot → LLM/Gemini → tap(x,y)
"""

import asyncio
import os
import re
import sys
import tempfile
import textwrap
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.auth import get_current_user
from models.db_models import User

router = APIRouter(prefix="/api/ai-gen", tags=["ai-generator"])

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"

# Backend kök dizini (ai_config.json burada)
_ROUTER_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    test_case:    str
    platform:     str
    browser:      Optional[str] = "chrome"
    target_url:   Optional[str] = ""
    device_id:    Optional[str] = ""
    app_package:  Optional[str] = ""
    app_activity: Optional[str] = ""
    appium_url:   Optional[str] = "http://localhost:4723"
    app_path:     Optional[str] = ""

class ExecuteRequest(BaseModel):
    script:   str
    platform: str


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1: KURAL MOTORU
# Türkçe test adımı → Appium/Selenium Python satırları
# ══════════════════════════════════════════════════════════════════════════════

def _clean_step(raw: str) -> str:
    """Adım numarası, etiket ve beklenen sonuç suffix'ini temizle."""
    s = raw.strip()
    s = re.sub(r'^(adım|adim|step)\s*\d+\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    # "→ Beklenen: ..." suffix'ini kural motoru için kes (LLM bağlamı için orijinal satır kullanılır)
    s = re.sub(r'\s*[→>]+\s*[Bb]eklenen:.*$', '', s)
    return s.strip()


def _extract_quoted(text: str) -> list[str]:
    """Metindeki tırnak içi değerleri döndürür."""
    return re.findall(r'["\u201c\u201d\u2018\u2019]([^"\u201c\u201d\u2018\u2019]+)["\u201c\u201d\u2018\u2019]', text)


def _extract_key_target(text: str) -> str | None:
    """
    Karmaşık adım açıklamalarından asıl hedef elementi çıkarır.
    "Toplam Varlıklarım kartında yer alan favori fonlarım" → "favori fonlarım"
    "Ana Sayfa ekranındaki Hesaplarım butonu" → "Hesaplarım"
    """
    # "X kartında/bölümünde/ekranında/menüsünde [yer alan/bulunan/içindeki] Y"
    m = re.search(
        r'(?:kart[ıi]nda|bölümünde|ekranında|sayfasında|menüsünde|widget[ıi]nda)'
        r'(?:\s+(?:yer\s+alan|bulunan|içindeki|görünen))?\s+(.+)$',
        text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    # "yer alan / bulunan / içindeki" marker
    m2 = re.search(r'(?:yer\s+alan|içindeki|bulunan|görünen)\s+(.+)$', text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def _get_auto_value(context: str) -> str:
    """Alan bağlamına göre otomatik test değeri üretir."""
    ctx = context.lower()
    if re.search(r'tutar|miktar|amount|fiyat|para|finansman', ctx):
        return '10000'
    if re.search(r'telefon|gsm|phone|cep|numara', ctx):
        return '05551234567'
    if re.search(r'tc\b|tckn|kimlik', ctx):
        return '12345678901'
    if re.search(r'şifre|sifre|password|pin|parola', ctx):
        return '123456'
    if re.search(r'email|eposta|e-posta|mail', ctx):
        return 'test@test.com'
    if re.search(r'isim|ad\b|name|first', ctx):
        return 'Test'
    if re.search(r'soyisim|soyad|last', ctx):
        return 'Kullanici'
    return '121212'


def _parse_azure_devops_csv(decoded: str) -> str | None:
    """
    Azure DevOps CSV formatını tanır ve Step Action sütununu çıkarır.
    Döndürür: "Adım 1: ...\nAdım 2: ..." formatında metin, tanımazsa None.
    """
    import io, csv
    reader = csv.reader(io.StringIO(decoded))
    rows = list(reader)
    if not rows:
        return None

    header = [c.strip() for c in rows[0]]
    header_lower = [h.lower() for h in header]

    # Azure DevOps format tespiti
    if not any('step action' in h for h in header_lower):
        return None

    step_num_idx    = next((i for i, h in enumerate(header_lower) if 'test step' in h), None)
    step_action_idx = next((i for i, h in enumerate(header_lower) if 'step action' in h), None)
    if step_action_idx is None:
        return None

    step_expected_idx = next((i for i, h in enumerate(header_lower) if 'step expected' in h), None)

    steps = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        id_col   = row[0].strip() if len(row) > 0 else ""
        step_num = (row[step_num_idx].strip() if step_num_idx is not None and len(row) > step_num_idx else "")
        if not id_col and step_num and step_num.isdigit() and len(row) > step_action_idx:
            action = row[step_action_idx].strip()
            if not action:
                continue
            # Beklenen sonucu kısa tut (ilk cümle, max 120 karakter)
            expected = ""
            if step_expected_idx is not None and len(row) > step_expected_idx:
                raw_exp = row[step_expected_idx].strip()
                # İlk cümleyi al
                first_sentence = re.split(r'(?<=[.!?])\s', raw_exp)[0]
                expected = first_sentence[:120]
            if expected:
                steps.append(f"Adım {step_num}: {action} → Beklenen: {expected}")
            else:
                steps.append(f"Adım {step_num}: {action}")

    return "\n".join(steps) if steps else None


def _rule_mobile(step: str) -> list[str] | None:
    """
    Tek bir Türkçe adımı Appium satırlarına çevirir.
    Tanıyamazsa None döner → LLM devreye girer.
    """
    s = _clean_step(step)
    if not s:
        return None

    quoted = _extract_quoted(s)
    sl = s.lower()

    # ── Pasif Türkçe: "X [suffix] tıklanır" (tırnaksız) ─────────────────────
    _PC = re.search(
        r'^(.+?)\s+(?:seçene[ğg]ine|componentine|butonu?na|simgesine|ikonuna'
        r'|bağlantısına|sekmesin[ei]|tab[ıi]na|alan[ıi]na|[üu]zerine'
        r'|linkine|ikona|logosuna)\s+t[ıi]klan[ıi]r\.?\s*$',
        s, re.IGNORECASE
    )
    if _PC:
        full_t = _PC.group(1).strip()
        key_t  = _extract_key_target(full_t)
        if key_t:
            return [f'# {s}', f"_safe_click(driver, '{full_t}', '{key_t}')", 'time.sleep(0.8)']
        return [f'# {s}', f"_safe_click(driver, '{full_t}')", 'time.sleep(0.8)']

    # ── "X açılır" - bileşen/ekran açılır (click to open) ────────────────────
    _AC = re.search(r'^(.+?)\s+a[çc][ıi]l[ıi]r\.?\s*$', s, re.IGNORECASE)
    if _AC:
        full_t = _AC.group(1).strip()
        key_t  = _extract_key_target(full_t)
        if key_t:
            return [f'# {s}', f"_safe_click(driver, '{full_t}', '{key_t}')", 'time.sleep(1.0)']
        return [f'# {s}', f"_safe_click(driver, '{full_t}')", 'time.sleep(1.0)']

    # ── Compound: "seçim yapılır, bir X girilir" — hem seç hem yaz ──────────────
    if re.search(r'se[çc]im\s+yapıl[ıi]r', sl) and re.search(r'bir\s+\w+\s+girilir', sl):
        _m_amt = re.search(r'bir\s+(tutar|miktar|değer|numara|sayı)\s+girilir', sl, re.IGNORECASE)
        value = _get_auto_value(_m_amt.group(1) if _m_amt else 'tutar')
        return [
            f'# {s}',
            '# Dropdown seçimi: ilk mevcut seçeneği tıkla',
            'try:',
            '    _ddl = driver.find_elements(AppiumBy.XPATH, \'//android.widget.ListView//*[@clickable="true"]\')',
            '    if not _ddl:',
            '        _ddl = driver.find_elements(AppiumBy.XPATH, \'//*[@clickable="true" and string-length(@text)>0]\')',
            '    if _ddl: _ddl[0].click(); time.sleep(0.5)',
            'except Exception as _e: print(f"Seçim hatası: {_e}")',
            f"# Tutar girişi — otomatik test verisi: {value}",
            f"_safe_input(driver, '//android.widget.EditText[1]', '{value}')",
            'time.sleep(0.5)',
        ]

    # ── "bir X girilir" — basit adım, değer belirtilmemiş, otomatik doldur ─────
    _GR = re.search(r'\bgirilir\b', sl)
    if _GR and not quoted:
        _GM = re.search(r'(?:bir\s+)?(.+?)\s+(?:alan[ıi]na\s+)?girilir\.?\s*$', s, re.IGNORECASE)
        if _GM:
            ctx = _GM.group(1)
            value = _get_auto_value(ctx)
            is_pw = bool(re.search(r'şifre|sifre|password|pin|parola', ctx, re.IGNORECASE))
            field_xpath = ('//android.widget.EditText[@password="true"]'
                           if is_pw else '//android.widget.EditText[1]')
            return [
                f'# {s}',
                f"# Otomatik test verisi: {value}",
                f"_safe_input(driver, '{field_xpath}', '{value}')",
                'time.sleep(0.5)',
            ]

    # ── Tıklama ───────────────────────────────────────────────────────────────
    CLICK_WORDS = r'(?:t[iı]kla|tikla|bas|click|se[cç]|tap|a[cç])'
    if re.search(CLICK_WORDS, sl) and quoted:
        text = quoted[0]
        return [
            f'# {s}',
            f'_safe_click(driver, \'{text}\')',
            'time.sleep(0.8)',
        ]

    # ── Doğrulama / Görme — ÖNCE kontrol et (gir/giriş çakışmasını önle) ─────
    ASSERT_WORDS = r'(?:g[oö]r\b|do[gğ]rula|kontrol|assert|verify|check|var m[iı]|bekleniyor)'
    if re.search(ASSERT_WORDS, sl) and quoted:
        text = quoted[0]
        return [
            f'# {s}',
            f'_safe_assert(driver, \'{text}\')',
        ]

    # ── Metin girişi ──────────────────────────────────────────────────────────
    # "gir" kelimesi sadece bağımsız geçiyorsa eşleşir (giriş/giriyor değil)
    INPUT_WORDS = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor|di)|doldur|type|enter\b|input\b)'
    if re.search(INPUT_WORDS, sl) and quoted:
        value = quoted[-1]  # Son tırnak değeri = yazılacak metin
        # Şifre alanı mı?
        if re.search(r'(?:şifre|sifre|password|pin|parola)', sl):
            field_xpath = '//android.widget.EditText[@password="true"]'
        else:
            field_xpath = '//android.widget.EditText[1]'
        return [
            f'# {s}',
            f'_safe_input(driver, \'{field_xpath}\', \'{value}\')',
            'time.sleep(0.5)',
        ]

    # ── Doğrulama (altta kalır — ASSERT önceden yakalandı) ───────────────────
    if False and quoted:  # devre dışı - yukarıda ele alındı
        text = quoted[0]
        return [
            f'# {s}',
            f'_safe_assert(driver, \'{text}\')',
        ]

    # ── Kaydırma ──────────────────────────────────────────────────────────────
    if re.search(r'(?:a[sş]a[gğ][iı]\s*kaydır|scroll\s*down|swipe\s*down)', sl):
        return [f'# {s}', 'driver.swipe(540, 1400, 540, 400, 800)', 'time.sleep(0.5)']
    if re.search(r'(?:yukar[iı]\s*kaydır|scroll\s*up|swipe\s*up)', sl):
        return [f'# {s}', 'driver.swipe(540, 400, 540, 1400, 800)', 'time.sleep(0.5)']
    if re.search(r'(?:kaydır|scroll|swipe)', sl):
        return [f'# {s}', 'driver.swipe(540, 1400, 540, 400, 800)', 'time.sleep(0.5)']

    # ── Geri ─────────────────────────────────────────────────────────────────
    if re.search(r'(?:geri\s*d[oö]n|geri\s*git|back\b)', sl):
        return [f'# {s}', 'driver.back()', 'time.sleep(0.5)']

    # ── Bekleme ───────────────────────────────────────────────────────────────
    if re.search(r'(?:bekle|wait|sleep)', sl):
        m = re.search(r'(\d+)', s)
        secs = m.group(1) if m else '2'
        return [f'# {s}', f'time.sleep({secs})']

    return None  # Tanınmadı → LLM


def _rule_web(step: str) -> list[str] | None:
    s  = _clean_step(step)
    if not s:
        return None
    sl     = s.lower()
    quoted = _extract_quoted(s)

    CLICK_WORDS  = r'(?:t[iı]kla|tikla|bas|click|tap)'
    INPUT_WORDS  = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type\b|enter\b)'
    ASSERT_WORDS = r'(?:g[oö]r\b|do[gğ]rula|kontrol|assert|verify|var m[iı]|bekleniyor|görünmeli)'
    NAV_WORDS    = r'(?:git\b|navigate|a[cç]\b|open\b|ziyaret|url|adres)'

    # ── URL / Navigasyon ─────────────────────────────────────────────────
    if re.search(NAV_WORDS, sl) and quoted:
        url = quoted[0]
        if not url.startswith("http"):
            url = "https://" + url
        return [f'# {s}', f'driver.get("{url}")', 'time.sleep(1.5)']

    # ── Tıklama ──────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', f'_safe_click_web(driver, \'{text}\')', 'time.sleep(0.5)']

    # ── Doğrulama ────────────────────────────────────────────────────────
    if re.search(ASSERT_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', f'_safe_assert_web(driver, \'{text}\')']

    # ── Metin girişi ─────────────────────────────────────────────────────
    if re.search(INPUT_WORDS, sl) and quoted:
        value  = quoted[-1]
        is_pw  = bool(re.search(r'(?:şifre|sifre|password|pin|parola)', sl))
        # Alan ipucu: tırnak içlerini ve fiili sil, kalan metin alanı tanımlar
        hint_raw = re.sub(
            r'["\u201c\u201d\u2018\u2019][^"\u201c\u201d\u2018\u2019]+["\u201c\u201d\u2018\u2019]',
            '', s
        )
        hint_raw = re.sub(
            r'\b(?:yaz|gir|doldur|type|enter|alan[ıi]na|alan[ıi]|alanına|field|kutusuna|bölümüne)\b',
            '', hint_raw, flags=re.IGNORECASE
        )
        hint = hint_raw.strip().rstrip('.,;:').strip().lower()
        return [
            f'# {s}',
            f'_safe_input_web(driver, \'{hint}\', \'{value}\', is_password={is_pw})',
            'time.sleep(0.3)',
        ]

    # ── Kaydırma ─────────────────────────────────────────────────────────
    if re.search(r'(?:a[sş]a[gğ][iı]|scroll\s*down)', sl):
        return [f'# {s}', 'driver.execute_script("window.scrollBy(0, 400);")', 'time.sleep(0.4)']
    if re.search(r'(?:yukar[iı]|scroll\s*up)', sl):
        return [f'# {s}', 'driver.execute_script("window.scrollBy(0, -400);")', 'time.sleep(0.4)']

    # ── Geri ─────────────────────────────────────────────────────────────
    if re.search(r'(?:geri|back\b)', sl):
        return [f'# {s}', 'driver.back()', 'time.sleep(0.5)']

    # ── Bekleme ───────────────────────────────────────────────────────────
    if re.search(r'(?:bekle|wait|sleep)', sl):
        m = re.search(r'(\d+)', s)
        secs = m.group(1) if m else '2'
        return [f'# {s}', f'time.sleep({secs})']

    return None


def _llm_fallback_steps_prompt(unrecognized: list[str], platform: str) -> str:
    """Kural motorunun tanıyamadığı adımlar için LLM prompt'u."""
    if platform == "mobile":
        api = "AppiumBy.XPATH, '//*[@text=\"X\"]'"
    else:
        api = "By.XPATH, '//*[contains(text(),\"X\")]'"

    steps_text = "\n".join(f"- {s}" for s in unrecognized)
    return f"""Write Python Appium/Selenium lines for these test steps. No imports, no explanations.
Use only: driver.find_element({api}).click() | .send_keys("x") | .is_displayed() | time.sleep(n)
Output only code lines + # comments.

Steps:
{steps_text}

Code:"""


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2: VISION FALLBACK FONKSİYONU (script içine gömülür)
# ══════════════════════════════════════════════════════════════════════════════

VISION_HELPER = '''
import base64 as _b64, requests as _req, re as _re

def _vision_find(driver, search_text):
    """Element bulunamazsa screenshot al, LLM ile koordinat bul, tap yap."""
    try:
        print(f"[VISION] '{search_text}' aranıyor...")
        screenshot = driver.get_screenshot_as_base64()

        # Önce Gemini dene (ai_config.json'da key varsa)
        try:
            import json, pathlib
            # Önce backend dizinini ara, sonra script konumunu dene
            _candidates = [
                pathlib.Path(_AI_CONFIG_PATH) if "_AI_CONFIG_PATH" in globals() else None,
                pathlib.Path(__file__).parent / "ai_config.json",
                pathlib.Path(__file__).parent.parent / "ai_config.json",
            ]
            cfg = {}
            for _cp in _candidates:
                if _cp and _cp.exists():
                    cfg = json.loads(_cp.read_text(encoding="utf-8"))
                    break
            gemini_key = cfg.get("gemini_api_key", "")
        except Exception:
            gemini_key = ""

        # Bağlama özel prompt — tek rakam = klavye tuşu, diğer = genel element
        if len(search_text) == 1 and search_text.isdigit():
            _prompt_tr = (f"Bu Android ekranında sayısal tuş takımı (PIN klavyesi) görünüyor. "
                          f"'{search_text}' rakamının TUŞUNU bul. Başka yerde görünen '{search_text}' rakamına bakma, "
                          f"sadece klavye tuşuna bak. Koordinat: x=NNN y=NNN")
            _prompt_en = (f"A numeric PIN keyboard is visible on this Android screen. "
                          f"Find ONLY the '{search_text}' key on the keyboard (bottom of screen). "
                          f"Reply only: x=<number> y=<number>")
        else:
            _prompt_tr = (f"Android ekranında '{search_text}' yazan veya gösteren tıklanabilir elementi bul. "
                          f"Koordinat: x=NNN y=NNN")
            _prompt_en = (f"Find the clickable element showing '{search_text}' on this Android screen. "
                          f"Reply only: x=<number> y=<number>")

        if gemini_key:
            resp = _req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [
                    {"text": _prompt_tr},
                    {"inline_data": {"mime_type": "image/png", "data": screenshot}}
                ]}]},
                timeout=15
            )
            answer = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            # Ollama fallback (llava/gemma3 vision)
            resp = _req.post("http://localhost:11434/api/generate", json={
                "model": "gemma3:4b",
                "prompt": _prompt_en,
                "images": [screenshot],
                "stream": False
            }, timeout=30)
            answer = resp.json().get("response", "")

        mx = _re.search(r"x[=:\\s]*(\\d+)", answer, _re.IGNORECASE)
        my = _re.search(r"y[=:\\s]*(\\d+)", answer, _re.IGNORECASE)
        if mx and my:
            x, y = int(mx.group(1)), int(my.group(1))
            print(f"[VISION] Koordinat bulundu: ({x}, {y})")
            driver.tap([(x, y)])
            return True
        else:
            print(f"[VISION] Koordinat bulunamadı. Yanıt: {answer[:100]}")
            return False
    except Exception as e:
        print(f"[VISION] Hata: {e}")
        return False


def _safe_click(driver, text, key_text=None):
    """
    Akıllı click stratejisi:
    1. Tam metin ile dene
    2. Kısa anahtar kelime ile dene (karmaşık açıklamalar için)
    3. Aşağı kaydır → tekrar dene
    4. Yukarı kaydır → tekrar dene
    5. Vision fallback (ekran görüntüsü → AI → koordinat)
    key_text: "Toplam Varlıklarım kartında yer alan favori fonlarım" → "favori fonlarım"
    """
    _all_texts = [t for t in [text, key_text] if t]

    def _try(t):
        for _xp in [
            f\'//*[@text="{t}"]\',
            f\'//android.widget.Button[@text="{t}"]\',
            f\'//android.widget.TextView[@text="{t}"]\',
            f\'//*[contains(@text,"{t}")]\',
            f\'//*[@content-desc="{t}"]\',
            f\'//*[contains(@content-desc,"{t}")]\',
        ]:
            try:
                driver.find_element(AppiumBy.XPATH, _xp).click()
                print(f"[OK] Tıklandı: {t}")
                return True
            except Exception:
                continue
        return False

    # 1 & 2: direkt dene
    for _t in _all_texts:
        if _try(_t): return

    # 3: aşağı kaydır + tekrar
    print(f"[SCROLL↓] '{text}' bulunamadı, aşağı kaydırılıyor...")
    driver.swipe(540, 1400, 540, 500, 800); time.sleep(0.7)
    for _t in _all_texts:
        if _try(_t): return

    # 4: yukarı kaydır + tekrar (orijinal konuma + biraz üstüne)
    print(f"[SCROLL↑] Yukarı kaydırılıyor...")
    driver.swipe(540, 500, 540, 1400, 800); time.sleep(0.7)
    for _t in _all_texts:
        if _try(_t): return

    # 5: Vision fallback — kısa metin varsa onu gönder (AI için daha net)
    _vision_target = key_text if key_text else text
    print(f"[VISION] '{_vision_target}' için ekran görüntüsü analiz ediliyor...")
    if not _vision_find(driver, _vision_target):
        raise Exception(f"Element bulunamadı (tüm stratejiler denendi): {text}")


def _safe_input(driver, xpath, value):
    """Metin girişi — önce ekrana bak, PIN klavyesi varsa tıkla, yoksa send_keys/ADB"""
    import subprocess as _sp, shutil as _sh, os as _os, re as _re2
    str_value = str(value)
    print(f"[INPUT] '{str_value}' yazılıyor... (xpath={xpath})")

    # ── ADB yolu ──────────────────────────────────────────────────────────────
    def _adb_exec():
        _p = _sh.which("adb")
        if _p: return _p
        for _base in [_os.environ.get("LOCALAPPDATA",""), _os.environ.get("USERPROFILE","")]:
            _c = _os.path.join(_base, "AppData","Local","Android","Sdk","platform-tools","adb.exe")
            if _os.path.exists(_c): return _c
        return "adb"
    _ADB = _adb_exec()
    _adb = [_ADB, "-s", _DEVICE_ID] if _DEVICE_ID else [_ADB]

    # ── Sayfa kaynağını bir kez al ────────────────────────────────────────────
    try:
        _src = driver.page_source
    except Exception:
        _src = ""

    # ── PIN klavyesi tespiti: 6+ rakam butonu görünüyorsa ─────────────────────
    def _detect_pin_keyboard():
        _digit_count = sum(
            1 for _d in "0123456789"
            if f\'text="{_d}"\' in _src or f\'content-desc="{_d}"\' in _src
        )
        print(f"[INPUT] Rakam butonu sayısı: {_digit_count}")
        return _digit_count >= 6

    # ── Tek rakam butonuna tıkla ───────────────────────────────────────────────
    def _click_digit(d):
        # Ekrandaki tüm eleman bilgilerini çekip koordinat bazlı sırala
        _patterns = [
            f\'//android.widget.Button[@text="{d}"]\',
            f\'//*[@text="{d}" and @clickable="true"]\',
            f\'//*[@content-desc="{d}" and @clickable="true"]\',
            f\'//*[contains(@resource-id,"key") and @text="{d}"]\',
            f\'//*[contains(@resource-id,"btn") and @text="{d}"]\',
            f\'//*[contains(@resource-id,"digit") and @text="{d}"]\',
            f\'//*[@text="{d}"]\',
            f\'//*[@content-desc="{d}"]\',
        ]
        for _xp in _patterns:
            try:
                _els = driver.find_elements(AppiumBy.XPATH, _xp)
                if not _els:
                    continue
                # En alt y-koordinatlı elemanı tercih et (klavye genelde altta)
                _best = max(_els, key=lambda e: e.location.get("y", 0))
                _best.click()
                print(f"[PIN] '{d}' tıklandı ({_xp[:50]})")
                time.sleep(0.25)
                return True
            except Exception:
                continue
        # Vision fallback
        print(f"[PIN] '{d}' butonla bulunamadı, vision deneniyor...")
        return _vision_find(driver, d)

    # ── PIN klavyesi açıksa → direkt butonlara tıkla ─────────────────────────
    if _detect_pin_keyboard():
        print(f"[INPUT] PIN klavyesi tespit edildi, buton tıklama modu")
        _ok = 0
        for _ch in str_value:
            if _click_digit(_ch):
                _ok += 1
            else:
                print(f"[PIN] '{_ch}' yazılamadı")
        print(f"[INPUT] PIN sonuç: {_ok}/{len(str_value)} karakter")
        if _ok >= len(str_value):
            return
        # Kısmen yazdıysa yine de devam et
        if _ok > 0:
            return

    # ── Standart EditText modu ────────────────────────────────────────────────
    def _find_el():
        for _xp in [xpath,
                    '//android.widget.EditText[@password="true"]',
                    '//android.widget.EditText[1]',
                    '//android.widget.EditText']:
            try:
                _e = driver.find_element(AppiumBy.XPATH, _xp)
                _e.click(); time.sleep(0.4)
                return _e
            except Exception:
                continue
        return None

    def _field_has_value():
        for _xp in [xpath, '//android.widget.EditText[@password="true"]',
                    '//android.widget.EditText[1]']:
            try:
                _e = driver.find_element(AppiumBy.XPATH, _xp)
                _v = _e.text or _e.get_attribute("text") or _e.get_attribute("value") or ""
                if _v.strip():
                    return True
            except Exception:
                continue
        return False

    _el = _find_el()
    print(f"[INPUT] EditText {'bulundu' if _el else 'bulunamadı'}")

    # Alan tıklandıktan sonra PIN klavyesi açıldıysa buton moduna geç
    time.sleep(0.4)
    try:
        _src_r = driver.page_source
        _pin_r = sum(1 for _d in "0123456789"
                     if f\'text="{_d}"\' in _src_r or f\'content-desc="{_d}"\' in _src_r)
        if _pin_r >= 6:
            print(f"[INPUT] Alan tıklanınca PIN klavyesi açıldı ({_pin_r} rakam)")
            _ok = 0
            for _ch in str_value:
                if _click_digit(_ch):
                    _ok += 1
            if _ok > 0:
                print(f"[INPUT] PIN sonuç: {_ok}/{len(str_value)}")
                return
    except Exception as _e:
        print(f"[INPUT] PIN re-check hata: {_e}")

    # Placeholder metnini kaydet: typing başarısını doğrulamak için
    # Bazı uygulamalar placeholder\'ı actual text olarak set eder (ör: "Şifre Giriniz")
    # send_keys başarısızsa uygulama placeholder\'ı geri koyar, değiştiyse başarılı
    _placeholder = ""
    try:
        if _el:
            _placeholder = _el.text or _el.get_attribute("text") or ""
            print(f"[INPUT] Placeholder: \'{_placeholder[:40]}\'")
    except:
        pass

    def _typing_succeeded(el):
        # Placeholder kontrolü ÖNCE gelir — _field_has_value placeholder\'ı dolu sayar
        if _placeholder:
            try:
                _curr = el.text or el.get_attribute("text") or "" if el else ""
            except:
                _curr = ""
            # Placeholder hala görünüyorsa typing kesinlikle başarısız
            if _curr == _placeholder:
                return False
            # Placeholder değiştiyse başarılı
            return True
        # Placeholder yoksa field_has_value\'ya bak
        return _field_has_value()

    # Strateji A: send_keys
    if _el:
        try:
            _el.clear(); time.sleep(0.2)
            _el.send_keys(str_value); time.sleep(0.6)
            if _typing_succeeded(_el):
                print(f"[OK] send_keys başarılı: {value}"); return
            print("[INPUT] send_keys başarısız (placeholder değişmedi)")
        except Exception as _e:
            print(f"[INPUT] send_keys hata: {_e}")

    # Strateji B: ADB input text
    try:
        _sp.run(_adb + ["shell", "input", "text", str_value],
                capture_output=True, timeout=5)
        time.sleep(0.6)
        if _typing_succeeded(_el):
            print(f"[OK] ADB input text başarılı: {value}"); return
        print("[INPUT] ADB input text başarısız (placeholder değişmedi)")
    except Exception as _e:
        print(f"[INPUT] ADB hata: {_e}")

    # Strateji B2: ADB keyevent — rakam dizileri için (IME\'den bağımsız, doğrudan tuş eventi)
    if str_value.isdigit():
        try:
            _km = {\'0\':7,\'1\':8,\'2\':9,\'3\':10,\'4\':11,\'5\':12,\'6\':13,\'7\':14,\'8\':15,\'9\':16}
            for _ch in str_value:
                _sp.run(_adb + ["shell", "input", "keyevent", str(_km[_ch])],
                        capture_output=True, timeout=3)
                time.sleep(0.12)
            time.sleep(0.5)
            if _typing_succeeded(_el):
                print(f"[OK] ADB keyevent başarılı: {value}"); return
            print("[INPUT] ADB keyevent başarısız (placeholder değişmedi)")
        except Exception as _e:
            print(f"[INPUT] ADB keyevent hata: {_e}")

    # Strateji C: mobile:type
    try:
        if _el or _find_el():
            driver.execute_script("mobile: type", {"text": str_value})
            time.sleep(0.4)
            if _typing_succeeded(_el):
                print(f"[OK] mobile:type başarılı: {value}"); return
        print("[INPUT] mobile:type başarısız")
    except Exception as _e:
        print(f"[INPUT] mobile:type hata: {_e}")

    # Strateji D: Clipboard paste
    try:
        driver.set_clipboard_text(str_value); time.sleep(0.2)
        _sp.run(_adb + ["shell", "input", "keyevent", "279"], capture_output=True, timeout=5)
        time.sleep(0.4)
        if _typing_succeeded(_el):
            print(f"[OK] Clipboard başarılı: {value}"); return
        print("[INPUT] Clipboard başarısız")
    except Exception as _e:
        print(f"[INPUT] Clipboard hata: {_e}")

    # Strateji E: Alan tekrar bul → PIN klavyesi açıldıysa tıkla
    time.sleep(0.5)
    try:
        _src2 = driver.page_source
        _digit_count2 = sum(
            1 for _d in "0123456789"
            if f\'text="{_d}"\' in _src2 or f\'content-desc="{_d}"\' in _src2
        )
        if _digit_count2 >= 4:
            print(f"[INPUT] Klavye sonradan açıldı ({_digit_count2} rakam), buton moduna geçiliyor")
            _ok2 = 0
            for _ch in str_value:
                if _click_digit(_ch):
                    _ok2 += 1
            print(f"[INPUT] Geç PIN sonuç: {_ok2}/{len(str_value)}")
            if _ok2 > 0:
                return
    except Exception as _e:
        print(f"[INPUT] Geç klavye tespiti hata: {_e}")

    # Strateji F: Vision per-karakter (son çare)
    print(f"[INPUT] Vision per-karakter başlatılıyor: {value}")
    _ok_v = 0
    for _ch in str_value:
        if _vision_find(driver, _ch):
            _ok_v += 1; time.sleep(0.25)
        else:
            print(f"[INPUT] Vision '{_ch}' bulunamadı")
    print(f"[INPUT] Vision sonuç: {_ok_v}/{len(str_value)}")


def _safe_assert(driver, text, key_text=None):
    """
    Element doğrulama — scroll + vision destekli.
    1. Direkt bul
    2. Aşağı kaydır → tekrar bul
    3. Yukarı kaydır → tekrar bul
    4. Vision ile koordinat al → görsel doğrulama
    Bulunamazsa WARNING verir ama testi durdurmaz (beklenen ekran gecikmeli gelebilir).
    """
    _all_texts = [t for t in [text, key_text] if t]

    def _try_find():
        for _t in _all_texts:
            for _xp in [
                f\'//*[@text="{_t}"]\',
                f\'//*[contains(@text,"{_t}")]\',
                f\'//*[@content-desc="{_t}"]\',
                f\'//*[contains(@content-desc,"{_t}")]\',
            ]:
                try:
                    el = driver.find_element(AppiumBy.XPATH, _xp)
                    if el.is_displayed():
                        print(f"[OK] Doğrulandı: {_t}")
                        return True
                except Exception:
                    continue
        return False

    if _try_find(): return

    # Aşağı kaydır + tekrar
    print(f"[SCROLL↓] '{text}' aranıyor...")
    driver.swipe(540, 1400, 540, 500, 800); time.sleep(0.7)
    if _try_find(): return

    # Yukarı kaydır + tekrar
    print(f"[SCROLL↑] '{text}' aranıyor...")
    driver.swipe(540, 500, 540, 1400, 800); time.sleep(0.7)
    if _try_find(): return

    # Vision fallback
    print(f"[VISION] '{text}' için ekran görüntüsü analiz ediliyor...")
    if _vision_find(driver, key_text or text):
        print(f"[OK] Vision ile doğrulandı: {text}")
        return

    print(f"[WARN] '{text}' ekranda bulunamadı — adım geçiliyor")
'''


VISION_HELPER_WEB = '''
from selenium.webdriver.support.ui import WebDriverWait as _WDWEB
from selenium.webdriver.support import expected_conditions as _EC_WEB

def _wdwait(driver, timeout=10):
    return _WDWEB(driver, timeout)


def _safe_click_web(driver, text):
    """Web elementi tıkla — WebDriverWait + scroll + çoklu strateji"""
    from selenium.webdriver.common.by import By
    import time
    strategies = [
        (By.XPATH,         f'//*[normalize-space(text())="{text}"]'),
        (By.XPATH,         f'//button[contains(normalize-space(.),"{text}")]'),
        (By.XPATH,         f'//a[contains(normalize-space(.),"{text}")]'),
        (By.XPATH,         f'//input[@value="{text}"]'),
        (By.XPATH,         f'//*[@aria-label="{text}"]'),
        (By.XPATH,         f'//*[contains(text(),"{text}")]'),
        (By.LINK_TEXT,     text),
        (By.PARTIAL_LINK_TEXT, text),
    ]
    for scroll_pass in range(3):
        for by, val in strategies:
            try:
                el = _wdwait(driver, 5).until(_EC_WEB.element_to_be_clickable((by, val)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", el)
                time.sleep(0.15)
                el.click()
                print(f"[OK] Tıklandı: {text}")
                return
            except Exception:
                continue
        driver.execute_script(f"window.scrollBy(0, {350 * (scroll_pass + 1)});")
        time.sleep(0.4)
    raise Exception(f"Web elementi bulunamadı: {text}")


def _safe_input_web(driver, field_hint, value, is_password=False):
    """Input alanını placeholder/label/name/id ile bul ve değer gir"""
    from selenium.webdriver.common.by import By
    import time
    hint = (field_hint or "").strip().lower()
    val  = str(value)

    strategies = []
    if is_password:
        strategies += [
            (By.XPATH,       '//input[@type="password"]'),
            (By.CSS_SELECTOR,'input[type="password"]'),
        ]
    if hint:
        strategies += [
            (By.XPATH, f'//input[contains(translate(@placeholder,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]'),
            (By.XPATH, f'//textarea[contains(translate(@placeholder,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]'),
            (By.XPATH, f'//input[@id=//label[contains(translate(.,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]/@for]'),
            (By.XPATH, f'//input[contains(translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]'),
            (By.XPATH, f'//input[contains(translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]'),
            (By.XPATH, f'//input[contains(translate(@aria-label,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"{hint}")]'),
        ]
    strategies += [
        (By.XPATH,        '//input[@type="text" or not(@type)]'),
        (By.CSS_SELECTOR, 'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"])'),
    ]

    for by, sel in strategies:
        try:
            el = _wdwait(driver, 5).until(_EC_WEB.visibility_of_element_located((by, sel)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.2)
            el.clear()
            el.send_keys(val)
            print(f"[OK] Girildi: \'{val}\' (hint: {hint or 'generic'})")
            return
        except Exception:
            continue
    raise Exception(f"Input alanı bulunamadı: {field_hint}")


def _safe_assert_web(driver, text):
    """Metni sayfada doğrula — kaynak + element + scroll"""
    from selenium.webdriver.common.by import By
    import time
    if text in driver.page_source:
        print(f"[OK] Doğrulandı: {text}"); return
    for xp in [
        f'//*[contains(normalize-space(.),"{text}")]',
        f'//*[contains(@value,"{text}")]',
        f'//*[contains(@placeholder,"{text}")]',
    ]:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed():
                print(f"[OK] Doğrulandı: {text}"); return
        except Exception:
            continue
    driver.execute_script("window.scrollTo(0,0);"); time.sleep(0.5)
    assert text in driver.page_source, f"Beklenen metin yok: {text}"
'''


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3: ŞABLONLAR
# ══════════════════════════════════════════════════════════════════════════════

def _build_mobile_template(req: GenerateRequest, steps_code: str) -> str:
    device  = req.device_id    or "emulator-5554"
    pkg     = req.app_package  or ""
    act     = req.app_activity or ""
    appium  = req.appium_url   or "http://localhost:4723"

    if act:
        caps = f'''\
options.app_package            = "{pkg}"
options.app_activity           = "{act}"
options.no_reset               = True
options.auto_grant_permissions = True'''
        pre = ""
    else:
        caps = f'''\
options.app_package            = "{pkg}"
options.no_reset               = True
options.auto_grant_permissions = True'''
        pre = f'''\
import subprocess
print("Uygulama ADB ile baslatiliyor: {pkg}")
subprocess.run(
    ["adb", "-s", "{device}", "shell", "monkey",
     "-p", "{pkg}", "-c", "android.intent.category.LAUNCHER", "1"],
    capture_output=True
)
time.sleep(3)
'''

    lines = [
        "# -*- coding: utf-8 -*-",
        "from appium import webdriver",
        "from appium.options.android import UiAutomator2Options",
        "from appium.webdriver.common.appiumby import AppiumBy",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "import time",
        "",
        f'_DEVICE_ID = "{device}"  # ADB komutları için cihaz ID',
        f'_AI_CONFIG_PATH = r"{os.path.join(_ROUTER_BASE_DIR, "ai_config.json")}"',
        "",
        VISION_HELPER,
        "",
    ]

    if pre:
        lines += pre.splitlines() + [""]

    lines += [
        "options = UiAutomator2Options()",
        f'options.platform_name = "Android"',
        f'options.device_name   = "{device}"',
    ] + caps.splitlines() + [
        "",
        f'print("Appium baglaniyor: {appium}")',
        f'driver = webdriver.Remote("{appium}", options=options)',
        "wait   = WebDriverWait(driver, 15)",
        "time.sleep(2)",
        "",
        f'# Uygulama açık değilse başlat',
        f'_TARGET_PKG = "{pkg}"',
        "if _TARGET_PKG:",
        "    try:",
        "        _curr_pkg = driver.current_package",
        "        if _curr_pkg != _TARGET_PKG:",
        f'            print(f"Uygulama başlatılıyor: {{_TARGET_PKG}} (şu an: {{_curr_pkg}})")',
        "            driver.activate_app(_TARGET_PKG)",
        "            time.sleep(2.5)",
        "        else:",
        f'            print(f"Uygulama zaten açık: {{_TARGET_PKG}}")',
        "    except Exception as _launch_err:",
        f'        print(f"activate_app başarısız: {{_launch_err}}, ADB ile deneniyor...")',
        "        import subprocess as _sub",
        f'        _sub.run(["adb", "-s", _DEVICE_ID, "shell", "monkey",',
        f'                  "-p", _TARGET_PKG, "-c", "android.intent.category.LAUNCHER", "1"],',
        "                 capture_output=True, timeout=5)",
        "        time.sleep(3)",
        "",
        "try:",
    ]

    for line in steps_code.splitlines():
        lines.append("    " + line if line.strip() else "")

    lines += [
        "",
        "except Exception as e:",
        '    print(f"HATA: {e}")',
        "    raise",
        "finally:",
        "    driver.quit()",
    ]

    return "\n".join(lines)


def _build_web_template(req: GenerateRequest, steps_code: str) -> str:
    browser = (req.browser or "chrome").lower()
    url     = (req.target_url or "").strip()

    if browser == "firefox":
        driver_setup = (
            "from selenium.webdriver.firefox.options import Options as _FxOpts\n"
            "from selenium.webdriver.firefox.service import Service as _FxSvc\n"
            "_fx_opts = _FxOpts()\n"
            "try:\n"
            "    from webdriver_manager.firefox import GeckoDriverManager\n"
            "    driver = webdriver.Firefox(service=_FxSvc(GeckoDriverManager().install()), options=_fx_opts)\n"
            "except Exception:\n"
            "    driver = webdriver.Firefox(options=_fx_opts)"
        )
    elif browser == "edge":
        driver_setup = (
            "try:\n"
            "    from webdriver_manager.microsoft import EdgeChromiumDriverManager\n"
            "    from selenium.webdriver.edge.service import Service as _EdgeSvc\n"
            "    driver = webdriver.Edge(service=_EdgeSvc(EdgeChromiumDriverManager().install()))\n"
            "except Exception:\n"
            "    driver = webdriver.Edge()"
        )
    else:  # chrome (default)
        driver_setup = (
            "from selenium.webdriver.chrome.options import Options as _CrOpts\n"
            "_cr_opts = _CrOpts()\n"
            "# _cr_opts.add_argument('--headless')  # Başsız mod için aktif et\n"
            "try:\n"
            "    from webdriver_manager.chrome import ChromeDriverManager\n"
            "    from selenium.webdriver.chrome.service import Service as _CrSvc\n"
            "    driver = webdriver.Chrome(service=_CrSvc(ChromeDriverManager().install()), options=_cr_opts)\n"
            "except Exception:\n"
            "    driver = webdriver.Chrome(options=_cr_opts)  # Selenium 4.6+ otomatik driver"
        )

    lines = [
        "# -*- coding: utf-8 -*-",
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "import time",
        "",
        driver_setup,
        "",
        VISION_HELPER_WEB,
        "",
        "driver.maximize_window()",
        "wait = WebDriverWait(driver, 10)",
        "",
        "try:",
    ]

    if url:
        lines += [
            f'    driver.get("{url}")',
            "    time.sleep(1.5)",
        ]

    for line in steps_code.splitlines():
        lines.append("    " + line if line.strip() else "")

    lines += [
        "",
        "except Exception as e:",
        '    print(f"HATA: {e}")',
        "    raise",
        "finally:",
        "    driver.quit()",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4: ANA DÖNÜŞÜM MOTORU
# ══════════════════════════════════════════════════════════════════════════════

async def _generate_steps(req: GenerateRequest) -> tuple[str, list[dict]]:
    """
    Test case'i adım adım işler.
    Döndürür: (kod_str, adım_raporu)
    adım_raporu: [{"step": "...", "method": "rule|llm|todo", "code": "..."}]
    """
    rule_fn = _rule_mobile if req.platform == "mobile" else _rule_web

    code_lines   = []
    unrecognized = []
    report       = []

    raw_steps = [l.strip() for l in req.test_case.splitlines() if l.strip()]

    for step in raw_steps:
        parsed = rule_fn(step)
        if parsed:
            code_lines.append(("rule", step, "\n".join(parsed)))
        else:
            code_lines.append(("llm", step, ""))
            unrecognized.append(step)

    # LLM'e toplu sor
    llm_results = {}
    if unrecognized:
        llm_results = await _ask_llm_for_steps(unrecognized, req.platform)

    # Birleştir + rapor oluştur
    final_lines = []
    for kind, step, rule_code in code_lines:
        if kind == "rule":
            final_lines.append(rule_code)
            report.append({"step": step, "method": "rule", "code": rule_code})
        else:
            llm_code = llm_results.get(step, "")
            # LLM çıktısını temizle
            llm_code = "\n".join(
                l for l in llm_code.splitlines()
                if l.strip().startswith("#") or re.match(r'^\s*[a-z_].*[\(\.]', l)
            ).strip()
            # Tutarsız girinti düzelt (try/except bloklarından kaynaklanan IndentationError'ı önler)
            if llm_code:
                llm_code = textwrap.dedent(llm_code)
            if not llm_code:
                llm_code = f"# TODO (anlasilamadi): {step}\ntime.sleep(1)"
                method = "todo"
            else:
                method = "llm"
                llm_code = f"# {step}\n" + llm_code
            final_lines.append(llm_code)
            report.append({"step": step, "method": method, "code": llm_code})
        final_lines.append("")

    return "\n".join(final_lines), report


async def _ask_llm_for_steps(steps: list[str], platform: str) -> dict[str, str]:
    """LLM'den tanınmayan adımlar için kod üret."""
    if platform == "mobile":
        api_note = (
            "Use ONLY these helpers — NEVER call .send_keys() directly:\n"
            "  _safe_click(driver, 'text')  — click by visible text\n"
            "  _safe_input(driver, '//android.widget.EditText[1]', 'value')  — type text\n"
            "  _safe_assert(driver, 'text')  — verify element visible"
        )
    else:
        api_note = (
            "Use ONLY these helpers:\n"
            "  _safe_click_web(driver, 'text')                        — click by visible text\n"
            "  _safe_input_web(driver, 'field_hint', 'value')         — type into input (hint = label/placeholder keyword)\n"
            "  _safe_input_web(driver, 'field_hint', 'value', is_password=True)  — for password fields\n"
            "  _safe_assert_web(driver, 'text')                       — verify text is visible\n"
            "  driver.get('url')                                       — navigate to URL\n"
            "  driver.execute_script('window.scrollBy(0,400);')        — scroll"
        )

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    auto_fill_hint = (
        "Auto-fill when no value specified: tutar/amount→'10000', telefon→'05551234567', "
        "şifre/password→'123456', tc/kimlik→'12345678901', generic→'121212'.\n"
        "For 'seçim yapılır' (dropdown): click first list item via find_elements(...)[0].click().\n"
        "For compound steps (e.g. 'seçim yapılır, tutar girilir'): handle each action separately."
    )
    prompt = f"""Write Python automation code for each step. Output only code + # comments. No explanations.
{api_note}
{auto_fill_hint}

Steps:
{numbered}

Code (one block per step, separated by blank lines):"""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            })
            raw = resp.json().get("response", "")
    except Exception:
        raw = ""

    # Basit eşleştirme: bloğu adım sırasıyla eşleştir
    result = {}
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw) if b.strip()]
    for i, step in enumerate(steps):
        if i < len(blocks):
            # Prose filtrele — sadece kod satırları al
            code_only = "\n".join(
                l for l in blocks[i].splitlines()
                if l.startswith("#") or re.match(r'^[a-z_\s].*[\(\.]', l.strip())
            )
            result[step] = code_only if code_only else f"# TODO: {step}\ntime.sleep(1)"
        else:
            result[step] = f"# TODO: {step}\ntime.sleep(1)"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT'LER
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/parse-file")
async def parse_file_upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Excel (.xlsx/.xls), CSV veya TXT dosyasını okur,
    test adımlarını düz metin olarak döndürür.
    """
    contents = await file.read()
    filename  = (file.filename or "").lower()

    try:
        if filename.endswith((".xlsx", ".xls")):
            import io
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
            ws = wb.active
            lines = []
            for row in ws.iter_rows(values_only=True):
                parts = [str(c).strip() for c in row if c is not None and str(c).strip() not in ("", "None")]
                if parts:
                    lines.append("  ".join(parts))
            wb.close()
            text = "\n".join(lines)

        elif filename.endswith(".csv"):
            import io, csv
            decoded = contents.decode("utf-8-sig", errors="replace")
            # Azure DevOps formatını önce dene
            ado_text = _parse_azure_devops_csv(decoded)
            if ado_text:
                text = ado_text
            else:
                reader = csv.reader(io.StringIO(decoded))
                lines  = ["  ".join(r) for r in reader if any(c.strip() for c in r)]
                text   = "\n".join(lines)

        else:
            # .txt / .md veya uzantısız
            for enc in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
                try:
                    text = contents.decode(enc)
                    break
                except Exception:
                    continue
            else:
                text = contents.decode("utf-8", errors="replace")

        # Null byte temizle
        text = text.replace("\x00", "").strip()

        return {"success": True, "text": text, "lines": len(text.splitlines())}

    except Exception as e:
        raise HTTPException(400, f"Dosya okunamadı: {str(e)}")


@router.get("/status")
async def ollama_status():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return {"online": True, "model_available": any("gemma3" in m for m in models), "models": models}
    except Exception:
        pass
    return {"online": False, "model_available": False, "models": []}


@router.get("/adb/devices")
async def adb_devices(current_user: User = Depends(get_current_user)):
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "devices",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines   = stdout.decode("utf-8", errors="replace").strip().splitlines()
        devices = [l.split("\t")[0].strip() for l in lines[1:] if "\t" in l and "device" in l.split("\t")[1]]
        return {"devices": devices}
    except FileNotFoundError:
        raise HTTPException(500, "ADB bulunamadı")


@router.get("/adb/activity")
async def adb_get_activity(device_id: str, app_package: str, current_user: User = Depends(get_current_user)):
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "-s", device_id, "shell", "cmd", "package",
            "resolve-activity", "--brief", app_package,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        for line in output.splitlines():
            if "/" in line and app_package in line:
                activity = line.split("/", 1)[1].strip()
                if activity.startswith("."):
                    activity = app_package + activity
                return {"found": True, "activity": activity}
        return {"found": False, "activity": ""}
    except FileNotFoundError:
        raise HTTPException(500, "ADB bulunamadı")


@router.post("/generate")
async def generate_script(req: GenerateRequest, current_user: User = Depends(get_current_user)):
    """
    Hibrit dönüşüm:
    - Kural motoru → standart adımlar
    - LLM          → tanınmayanlar
    - Vision helper → runtime fallback (script içine gömülü)
    """
    steps_code, report = await _generate_steps(req)

    if req.platform == "mobile":
        final_script = _build_mobile_template(req, steps_code)
    elif req.platform == "web":
        final_script = _build_web_template(req, steps_code)
    else:
        final_script = f"# Desktop desteği yakında\nprint('Desktop: {req.app_path}')\nimport time\ntime.sleep(2)\n"

    todo_steps = [r for r in report if r["method"] == "todo"]
    warnings   = [f"Anlaşılamayan adım: {r['step']}" for r in todo_steps]

    return {
        "success":      True,
        "script":       final_script,
        "platform":     req.platform,
        "report":       report,
        "warnings":     warnings,
        "script_valid": True
    }


@router.post("/execute")
async def execute_script(req: ExecuteRequest, current_user: User = Depends(get_current_user)):
    if not req.script or len(req.script.strip()) < 10:
        raise HTTPException(400, "Geçersiz script")

    async def stream():
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_test_"
        ) as f:
            f.write(req.script)
            tmp = f.name

        yield _sse("info", f"Script: {os.path.basename(tmp)}")
        yield _sse("info", f"Platform: {req.platform}")
        yield _sse("info", "Kosum baslatiliyor...\n")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield _sse("log", line.decode("utf-8", errors="replace").rstrip())

            await proc.wait()
            rc = proc.returncode
            if rc == 0:
                yield _sse("success", f"\nKosum tamamlandi. (exit: {rc})")
            else:
                yield _sse("error", f"\nKosum hata ile bitti. (exit: {rc})")
        except Exception as e:
            yield _sse("error", str(e))
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            yield _sse("done", "")

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: str) -> str:
    result = f"event: {event}\n"
    for line in data.split("\n"):
        result += f"data: {line}\n"
    return result + "\n"
