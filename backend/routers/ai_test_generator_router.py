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
import subprocess
import sys
import tempfile
import textwrap
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pathlib import Path
from database import get_db
from sqlalchemy.orm import Session
from routers.auth import get_current_user
from models.db_models import User, UserWorkspace
from services import git_service
import json as _json
import datetime as _datetime

router = APIRouter(prefix="/api/ai-gen", tags=["ai-generator"])

_running_processes: dict[str, subprocess.Popen] = {}
_stop_files:        dict[str, str]               = {}   # run_id → stop flag dosyası
_desktop_lock:      asyncio.Lock                 = None # tek seferlik desktop kilidi (startup'ta init edilir)

def _get_desktop_lock() -> asyncio.Lock:
    global _desktop_lock
    if _desktop_lock is None:
        _desktop_lock = asyncio.Lock()
    return _desktop_lock

# ── Stop flag helper (her platforma gömülür) ─────────────────────────────────
STOP_HELPER = '''\
import os as _os_s, sys as _sys_s
_STOP_FILE = _os_s.environ.get("_AI_STOP_FILE", "")
def _check_stop():
    if _STOP_FILE and _os_s.path.exists(_STOP_FILE):
        try: _os_s.unlink(_STOP_FILE)
        except: pass
        raise SystemExit(0)
'''

from services.ai_service import get_ollama_config as _get_ollama_cfg

def _ollama_url():   return _get_ollama_cfg()["url"]
def _ollama_model(): return _get_ollama_cfg()["model"]

OLLAMA_URL   = "http://localhost:11434/api/generate"  # geriye dönük compat
OLLAMA_MODEL = "gemma3:4b"

# Backend kök dizini (ai_config.json burada)
_ROUTER_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class StepItem(BaseModel):
    type:          str = "text"   # "text" | "image" | "sql" | "api"
    content:       str = ""
    image_b64:     str = ""
    action:        str = "click"  # image: click/double_click/right_click/assert | sql: query_print/execute | api: print/execute/store
    # SQL adımı
    db_connection: str = ""       # sqlite:///path.db  veya  mysql+pymysql://user:pass@host/db
    sql_query:     str = ""
    # API adımı
    api_url:       str = ""
    api_method:    str = "GET"
    api_headers:   str = ""       # JSON string
    api_body:      str = ""       # JSON string
    # Değişken sistemi
    var_name:      str = ""       # dolu ise sonuç _VARS["var_name"]'e kaydedilir
    json_field:    str = ""       # API yanıtından çekilecek alan yolu: "id" veya "user.name"

class GenerateRequest(BaseModel):
    test_case:    str         = ""   # geriye dönük uyumluluk
    steps_list:   list[StepItem] = []   # yeni yapılandırılmış adım listesi
    platform:     str
    browser:      Optional[str] = "chrome"
    target_url:   Optional[str] = ""
    device_id:    Optional[str] = ""
    app_package:  Optional[str] = ""
    app_activity: Optional[str] = ""
    appium_url:   Optional[str] = "http://localhost:4723"
    app_path:       Optional[str]  = ""
    window_title:   Optional[str]  = ""
    reuse_instance: Optional[bool] = True

class ExecuteRequest(BaseModel):
    script:          str
    platform:        str
    scenario_name:   str       = "Adsız Senaryo"
    scenario_folder: str       = ""
    step_labels:     list[str] = []   # adım etiketleri (log için)


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

    # ── {{varname}} "//xpath" yaz ─────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, xpath = _vm.group(1), (_vm.group(2) or '//android.widget.EditText[1]')
        return [f'# {{{{ {vn} }}}} yaz', f"_safe_input(driver, {repr(xpath)}, str(_VARS.get({repr(vn)}, '')))"]

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
            return [f'# {s}', f"_safe_click(driver, {repr(full_t)}, {repr(key_t)})", 'time.sleep(0.8)']
        return [f'# {s}', f"_safe_click(driver, {repr(full_t)})", 'time.sleep(0.8)']

    # ── "X açılır" - bileşen/ekran açılır (click to open) ────────────────────
    _AC = re.search(r'^(.+?)\s+a[çc][ıi]l[ıi]r\.?\s*$', s, re.IGNORECASE)
    if _AC:
        full_t = _AC.group(1).strip()
        key_t  = _extract_key_target(full_t)
        if key_t:
            return [f'# {s}', f"_safe_click(driver, {repr(full_t)}, {repr(key_t)})", 'time.sleep(1.0)']
        return [f'# {s}', f"_safe_click(driver, {repr(full_t)})", 'time.sleep(1.0)']

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
            f'_safe_click(driver, {repr(text)})',
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

    # ── Klavye kapat ──────────────────────────────────────────────────────────
    if re.search(r'(?:klavye\s*kapat|klavyeyi\s*kapat|kapat\s*klavye|hide\s*keyboard|dismiss\s*keyboard)', sl):
        return [
            f'# {s}',
            'try:',
            '    driver.hide_keyboard()',
            'except Exception:',
            '    driver.back()',
            'time.sleep(0.5)',
        ]

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

    # ── {{varname}} "alanHint" yaz ────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, hint = _vm.group(1), (_vm.group(2) or "")
        if hint:
            return [f'# {{{{ {vn} }}}} yaz', f"_safe_input_web(driver, {repr(hint)}, str(_VARS.get({repr(vn)}, '')))"]
        return [f'# {{{{ {vn} }}}} yaz', f"import pyperclip as _pc; _pc.copy(str(_VARS.get({repr(vn)}, ''))); import pyautogui as _pa; _pa.hotkey('ctrl','v')"]

    _WEB_KEY_MAP = {
        'ctrl': 'Keys.CONTROL', 'control': 'Keys.CONTROL',
        'alt': 'Keys.ALT', 'shift': 'Keys.SHIFT',
        'delete': 'Keys.DELETE', 'del': 'Keys.DELETE',
        'backspace': 'Keys.BACK_SPACE', 'bs': 'Keys.BACK_SPACE',
        'enter': 'Keys.ENTER', 'return': 'Keys.RETURN',
        'tab': 'Keys.TAB',
        'escape': 'Keys.ESCAPE', 'esc': 'Keys.ESCAPE',
        'home': 'Keys.HOME', 'end': 'Keys.END',
        'pageup': 'Keys.PAGE_UP', 'pagedown': 'Keys.PAGE_DOWN',
        'f1': 'Keys.F1', 'f2': 'Keys.F2', 'f3': 'Keys.F3', 'f4': 'Keys.F4',
        'f5': 'Keys.F5', 'f6': 'Keys.F6', 'f7': 'Keys.F7', 'f8': 'Keys.F8',
        'f9': 'Keys.F9', 'f10': 'Keys.F10', 'f11': 'Keys.F11', 'f12': 'Keys.F12',
        'space': 'Keys.SPACE',
        'up': 'Keys.ARROW_UP', 'down': 'Keys.ARROW_DOWN',
        'left': 'Keys.ARROW_LEFT', 'right': 'Keys.ARROW_RIGHT',
    }
    _WEB_MODS = {'ctrl', 'control', 'alt', 'shift'}

    def _web_key_lines(key_str):
        parts = [p.strip().lower().replace(' ', '') for p in key_str.split('+')]
        mods  = [p for p in parts if p in _WEB_MODS]
        keys  = [p for p in parts if p not in _WEB_MODS]
        ln = [
            'from selenium.webdriver.common.keys import Keys',
            'from selenium.webdriver.common.action_chains import ActionChains',
            '_ac_web = ActionChains(driver)',
        ]
        for m in mods:
            ln.append(f'_ac_web.key_down({_WEB_KEY_MAP[m]})')
        for k in keys:
            mapped = _WEB_KEY_MAP.get(k)
            ln.append(f'_ac_web.send_keys({mapped})' if mapped else f'_ac_web.send_keys({repr(k)})')
        for m in reversed(mods):
            ln.append(f'_ac_web.key_up({_WEB_KEY_MAP[m]})')
        ln.append('_ac_web.perform()')
        return ln

    # ── Kısayol tuşu: "Ctrl+A" bas / "Delete" bas ────────────────────────
    hk = re.match(r'^["\']([^"\']+)["\']\s*(?:bas|kısayol|hotkey|tu[sş])$', s, re.IGNORECASE)
    if hk:
        return [f'# {s}'] + _web_key_lines(hk.group(1).strip()) + ['time.sleep(0.2)']

    # ── Tekil tuş (tırnaksız) ─────────────────────────────────────────────
    if re.search(r'\benter\s*bas\b', sl):
        return [f'# {s}'] + _web_key_lines('enter') + ['time.sleep(0.3)']
    if re.search(r'\btab\s*bas\b', sl):
        return [f'# {s}'] + _web_key_lines('tab')   + ['time.sleep(0.2)']
    if re.search(r'(?:escape|esc)\s*bas\b', sl):
        return [f'# {s}'] + _web_key_lines('escape') + ['time.sleep(0.2)']
    if re.search(r'(?:delete|sil)\s*bas\b', sl):
        return [f'# {s}'] + _web_key_lines('delete') + ['time.sleep(0.2)']
    if re.search(r'backspace\s*bas\b', sl):
        return [f'# {s}'] + _web_key_lines('backspace') + ['time.sleep(0.2)']

    CLICK_WORDS  = r'(?:t[iı]kla|tikla|click|tap)'
    INPUT_WORDS  = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type\b)'
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

    # ── Element görünene kadar bekle ──────────────────────────────────────
    if re.search(r'g[oö]r[uü]n[eien]+.*kadar\s*bekle|appear.*wait', sl) and quoted:
        text = quoted[0]
        return [
            f'# {s}',
            f"WebDriverWait(driver, 15).until(lambda d: len(d.find_elements(By.XPATH, '//*[contains(.,\"{text}\")]')) > 0)",
            'time.sleep(0.3)',
        ]

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

    # ── Sayfa işlemleri ───────────────────────────────────────────────────
    if re.search(r'(?:yenile|refresh|f5)', sl):
        return [f'# {s}', 'driver.refresh()', 'time.sleep(1.5)']
    if re.search(r'(?:geri|back\b)', sl):
        return [f'# {s}', 'driver.back()', 'time.sleep(0.5)']
    if re.search(r'(?:ileri|forward\b)', sl):
        return [f'# {s}', 'driver.forward()', 'time.sleep(0.5)']
    if re.search(r'(?:ekran\s*g[oö]r[uü]nt[uü]s[uü]|screenshot)', sl):
        return [f'# {s}', 'driver.save_screenshot(f"screenshot_{int(time.time())}.png")', 'time.sleep(0.3)']

    # ── Bekleme ───────────────────────────────────────────────────────────
    if re.search(r'(?:bekle|wait|sleep)', sl):
        m = re.search(r'(\d+)', s)
        secs = m.group(1) if m else '2'
        return [f'# {s}', f'time.sleep({secs})']

    return None


def _rule_desktop(step: str) -> list[str] | None:
    """Türkçe / İngilizce desktop adımını pyautogui helper çağrılarına çevirir."""
    s  = _clean_step(step)
    if not s:
        return None
    sl     = s.lower()
    quoted = _extract_quoted(s)

    # ── {{varname}} yaz — değişkenden değer yaz ──────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn = _vm.group(1)
        return [f'# {{{{ {vn} }}}} yaz', f"_safe_type_desktop(str(_VARS.get({repr(vn)}, '')))"]

    CLICK_WORDS        = r'(?:t[iı]kla|tikla|bas|click|tap|se[çc]|dokun)'
    DOUBLE_CLICK_WORDS = r'(?:çift\s*t[iı]kla|double[\s_]click)'
    RIGHT_CLICK_WORDS  = r'(?:sağ\s*t[iı]kla|right[\s_]click)'
    INPUT_WORDS        = r'(?:yaz\b|(?<![a-zğışöüçA-ZĞİŞÖÜÇ])gir(?!iş|iyor)|doldur|type\b)'
    ASSERT_WORDS       = r'(?:g[oö]r\b|do[gğ]rula|kontrol|assert|verify|var m[iı]|görünmeli|bekleniyor)'

    # ── Kısayol tuşu: "Ctrl+S" bas ───────────────────────────────────────────
    hk = re.match(r'^["\']([^"\']+)["\']\s*(?:bas|kısayol|hotkey|tu[sş])$', s, re.IGNORECASE)
    if hk:
        keys = "', '".join(hk.group(1).lower().replace(' ', '').split('+'))
        return [f'# {s}', f"_pag.hotkey('{keys}')", 'time.sleep(0.3)']

    # ── Enter / Tab / Escape ──────────────────────────────────────────────────
    if re.search(r'\benter\b', sl):
        return [f'# {s}', '_pag.press("enter")', 'time.sleep(0.3)']
    if re.search(r'\btab\b', sl):
        return [f'# {s}', '_pag.press("tab")',   'time.sleep(0.2)']
    if re.search(r'\bescape|esc\b', sl):
        return [f'# {s}', '_pag.press("esc")',   'time.sleep(0.2)']

    # ── Kopyala / Yapıştır ────────────────────────────────────────────────────
    if re.search(r'(?:kopyala|copy)', sl) and quoted:
        text = quoted[0]
        return [f'# {s}', '_refocus_window()', f"_safe_click_desktop('{text}', _WINDOW_TITLE)", '_pag.hotkey("ctrl", "c")', 'time.sleep(0.3)']
    if re.search(r'(?:yapıştır|paste)', sl):
        return [f'# {s}', '_refocus_window()', '_pag.hotkey("ctrl", "v")', 'time.sleep(0.3)']

    # ── Çift tıklama (CLICK_WORDS'ten önce kontrol edilmeli) ──────────────────
    if re.search(DOUBLE_CLICK_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', '_refocus_window()', f"_safe_double_click_desktop('{text}', _WINDOW_TITLE)", 'time.sleep(0.5)']

    # ── Sağ tıklama ───────────────────────────────────────────────────────────
    if re.search(RIGHT_CLICK_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', '_refocus_window()', f"_safe_right_click_desktop('{text}', _WINDOW_TITLE)", 'time.sleep(0.5)']

    # ── Menü navigasyonu: "Dosya > Yeni" tıkla ───────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted and '>' in quoted[0]:
        items = [i.strip() for i in quoted[0].split('>')]
        return [f'# {s}', '_refocus_window()', f"_safe_menu_click_desktop({items!r}, _WINDOW_TITLE)", 'time.sleep(0.5)']

    # ── Tıklama ───────────────────────────────────────────────────────────────
    if re.search(CLICK_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', '_refocus_window()', f"_safe_click_desktop('{text}', _WINDOW_TITLE)", 'time.sleep(0.5)']

    # ── Doğrulama ─────────────────────────────────────────────────────────────
    if re.search(ASSERT_WORDS, sl) and quoted:
        text = quoted[0]
        return [f'# {s}', '_refocus_window()', f"_safe_assert_desktop('{text}')"]

    # ── Metin girişi ──────────────────────────────────────────────────────────
    if re.search(INPUT_WORDS, sl) and quoted:
        value = quoted[-1]
        return [f'# {s}', '_refocus_window()', f"_safe_type_desktop('{value}')", 'time.sleep(0.3)']

    # ── Element görünene kadar bekle (genel bekle'den önce) ───────────────────
    if re.search(r'g[oö]r[uü]n[eu]ne\s*kadar\s*bekle|wait.*(?:appear|visible)', sl) and quoted:
        text = quoted[0]
        m = re.search(r'(\d+)', s)
        timeout = m.group(1) if m else '10'
        return [f'# {s}', f"_safe_wait_for_desktop('{text}', timeout={timeout})"]

    # ── Bekleme ───────────────────────────────────────────────────────────────
    if re.search(r'(?:bekle|wait|sleep)', sl):
        m = re.search(r'(\d+)', s)
        return [f'# {s}', f'time.sleep({m.group(1) if m else "1"})']

    # ── Kaydırma ─────────────────────────────────────────────────────────────
    if re.search(r'(?:a[sş]a[gğ]|scroll\s*down|swipe\s*down)', sl):
        return [f'# {s}', '_pag.scroll(-5)', 'time.sleep(0.3)']
    if re.search(r'(?:yukar[iı]|scroll\s*up|swipe\s*up)', sl):
        return [f'# {s}', '_pag.scroll(5)',  'time.sleep(0.3)']

    # ── Ekran görüntüsü ───────────────────────────────────────────────────────
    if re.search(r'ekran\s*g[oö]r[uü]nt[uü]s[uü]|screenshot', sl):
        return [f'# {s}', f'_pag.screenshot(f"screenshot_{{int(time.time())}}.png")', 'print("[OK] Ekran görüntüsü alındı")']

    # ── Pencere odakla ────────────────────────────────────────────────────────
    if re.search(r'(?:pencere|window|odakla|focus|aktif)', sl) and quoted:
        title = quoted[0]
        return [
            f'# {s}',
            f'if _PW_OK:',
            f'    try:',
            f'        _PwApp(backend="uia").connect(title_re=".*{title}.*", timeout=5).top_window().set_focus()',
            f'        print("[OK] Pencere odaklandı: {title}")',
            f'    except Exception as _fe: print(f"[WARN] Pencere bulunamadı: {{_fe}}")',
        ]

    return None


def _llm_fallback_steps_prompt(unrecognized: list[str], platform: str) -> str:
    """Kural motorunun tanıyamadığı adımlar için LLM prompt'u."""
    if platform == "mobile":
        api = "AppiumBy.XPATH, '//*[@text=\"X\"]'"
    elif platform == "desktop":
        api = "_safe_click_desktop('X') | _safe_type_desktop('X') | _safe_assert_desktop('X') | _pag.hotkey('ctrl','x')"
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
            resp = _req.post(_ollama_url(), json={
                "model": _ollama_model(),
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
    # Ham XPath/resource-id ise direkt kullan, scroll/vision'a gerek yok
    if text.startswith("//") or text.startswith("//*"):
        try:
            driver.find_element(AppiumBy.XPATH, text).click()
            print(f"[OK] XPath tıklandı: {text}")
            return
        except Exception as _xe:
            raise Exception(f"XPath bulunamadı: {text} → {_xe}")
    if text.startswith("id/") or text.startswith("@id/"):
        _rid = text.lstrip("@")
        try:
            driver.find_element(AppiumBy.ID, _rid).click()
            print(f"[OK] resource-id tıklandı: {_rid}")
            return
        except Exception as _xe:
            raise Exception(f"resource-id bulunamadı: {_rid} → {_xe}")

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

    # ── iOS: send_keys yeterli, ADB/mobile:type desteklenmiyor ───────────────
    try:
        _platform = driver.capabilities.get("platformName", "").lower()
    except Exception:
        _platform = ""
    if _platform == "ios":
        try:
            _ios_el = driver.find_element(AppiumBy.XPATH, xpath) if xpath else None
        except Exception:
            _ios_el = None
        try:
            if _ios_el:
                _ios_el.click()
                import time as _t; _t.sleep(0.3)
                _ios_el.send_keys(str_value)
            else:
                driver.switch_to.active_element.send_keys(str_value)
            print(f"[INPUT] ✅ iOS send_keys: {str_value}")
        except Exception as _e:
            print(f"[INPUT] iOS send_keys hatası: {_e}")
            try:
                driver.switch_to.active_element.send_keys(str_value)
                print(f"[INPUT] ✅ iOS active_element send_keys: {str_value}")
            except Exception as _e2:
                print(f"[INPUT] iOS yazma başarısız: {_e2}")
        return

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
    """Input alanini placeholder/label/name/id ile bul ve deger gir"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    import time
    hint = (field_hint or "").strip().lower()
    val  = str(value)

    def _type_into(el):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
        el.clear()
        el.send_keys(val)

    # 1) Her durumda once aktif (odaktaki) elemana yaz
    #    Gorsel tiklamadan sonra oraya gelir, hint olmasa da calisir
    try:
        _ae = driver.switch_to.active_element
        if _ae and _ae.tag_name.lower() in ("input", "textarea"):
            _type_into(_ae)
            print(f"[OK] Aktif elemana girildi: '{val}'")
            return
    except Exception:
        pass

    # 2) Password
    if is_password:
        for _by, _sel in [
            (By.XPATH,        '//input[@type="password"]'),
            (By.CSS_SELECTOR, 'input[type="password"]'),
        ]:
            try:
                _e = _wdwait(driver, 4).until(_EC_WEB.visibility_of_element_located((_by, _sel)))
                _type_into(_e)
                print(f"[OK] Sifre girildi")
                return
            except Exception:
                continue

    # 3) Hint ile ara
    if hint:
        _UC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        _LC = "abcdefghijklmnopqrstuvwxyz"
        for _by, _sel in [
            (By.XPATH, f'//input[contains(translate(@placeholder,"{_UC}","{_LC}"),"{hint}")]'),
            (By.XPATH, f'//textarea[contains(translate(@placeholder,"{_UC}","{_LC}"),"{hint}")]'),
            (By.XPATH, f'//input[contains(translate(@name,"{_UC}","{_LC}"),"{hint}")]'),
            (By.XPATH, f'//input[contains(translate(@id,"{_UC}","{_LC}"),"{hint}")]'),
            (By.XPATH, f'//input[contains(translate(@aria-label,"{_UC}","{_LC}"),"{hint}")]'),
            (By.XPATH, f'//*[contains(translate(.,"{_UC}","{_LC}"),"{hint}")]//following-sibling::input[1]'),
            (By.XPATH, f'//*[contains(translate(.,"{_UC}","{_LC}"),"{hint}")]/..//input[1]'),
        ]:
            try:
                _e = _wdwait(driver, 3).until(_EC_WEB.visibility_of_element_located((_by, _sel)))
                _type_into(_e)
                print(f"[OK] Girildi: '{val}' (hint: {hint})")
                return
            except Exception:
                continue

    # 4) Sayfadaki ilk gorunur input/textarea
    for _by, _sel in [
        (By.CSS_SELECTOR, 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]):not([type=file])'),
        (By.TAG_NAME,     'textarea'),
    ]:
        try:
            _e = _wdwait(driver, 3).until(_EC_WEB.visibility_of_element_located((_by, _sel)))
            _type_into(_e)
            print(f"[OK] Girildi: '{val}' (ilk input)")
            return
        except Exception:
            continue

    # 5) Son care: ActionChains ile mevcut odaga gonder
    try:
        ActionChains(driver).send_keys(val).perform()
        print(f"[OK] ActionChains ile girildi: '{val}'")
    except Exception as _ex:
        raise Exception(f"Input girilemiyor: {_ex}")


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


IMAGE_HELPER = '''
import base64 as _ib64, tempfile as _itmp, os as _ios, time as _itime

def _get_window_region():
    """_WINDOW_TITLE penceresinin ekran bölgesini (x,y,w,h) döndürür. Bulamazsa None."""
    try:
        _wt = _WINDOW_TITLE  # generated script globals'ta tanımlı
    except NameError:
        return None
    if not _wt:
        return None
    # pywinauto ile pencere dikdörtgeni al
    try:
        import pywinauto as _pwr
        _app = _pwr.Application(backend="uia").connect(title_re=f".*{_wt}.*", timeout=2)
        _rect = _app.top_window().rectangle()
        _x, _y = max(0, _rect.left), max(0, _rect.top)
        _w, _h = _rect.width(), _rect.height()
        if _w > 10 and _h > 10:
            return (_x, _y, _w, _h)
    except Exception:
        pass
    # win32gui fallback
    try:
        import win32gui as _wg
        def _cb(h, acc):
            if _wt.lower() in _wg.GetWindowText(h).lower():
                acc.append(h)
        _hs = []; _wg.EnumWindows(_cb, _hs)
        if _hs:
            _x1,_y1,_x2,_y2 = _wg.GetWindowRect(_hs[0])
            _w, _h = _x2-_x1, _y2-_y1
            if _w > 10 and _h > 10:
                return (max(0,_x1), max(0,_y1), _w, _h)
    except Exception:
        pass
    return None

def _find_b64_on_screen(b64_data, threshold=0.80, timeout=10):
    """Base64 gorsel arar — _WINDOW_TITLE varsa yalnizca o pencere icinde."""
    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_find_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))
        # Pencere bolgesi — _WINDOW_TITLE varsa tam ekran aramaz
        _region = _get_window_region()
        if _WINDOW_TITLE and _region is None:
            _wt_end = _itime.time() + 3
            while _itime.time() < _wt_end:
                _itime.sleep(0.3)
                _region = _get_window_region()
                if _region: break
            if _region is None:
                print(f"[HATA] '{_WINDOW_TITLE}' penceresi bulunamadi — gorsel aranamaz.")
                return None
        _start = _itime.time()
        while _itime.time() - _start < timeout:
            if _WINDOW_TITLE:
                _upd = _get_window_region()
                if _upd: _region = _upd
            _elapsed = _itime.time() - _start
            _conf = max(0.50, threshold - (_elapsed / timeout) * 0.30)
            _coords = _find_image_on_screen(_tmp_path, threshold=_conf, region=_region)
            if _coords:
                return _coords
            _itime.sleep(0.3)
        print(f"[DEBUG] Gorsel {timeout}s icinde bulunamadi. Farkli bir bolgeyi kroplayip tekrar deneyin.")
        return None
    finally:
        try: _ios.unlink(_tmp_path)
        except Exception: pass

def _find_image_on_screen(target_path, threshold=0.80, region=None):
    """OpenCV multi-scale template matching. region=(x,y,w,h) ile kısıtlı arama yapar."""
    try:
        import cv2 as _cv2, numpy as _np
        import pyautogui as _pag_sc
        # Windows DPI ölçeğini tespit et — template farklı DPI'da alınmış olabilir
        _dpi_scale = 1.0
        try:
            import ctypes as _ct
            _dpi_scale = _ct.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            pass
        _screenshot = _pag_sc.screenshot(region=region) if region else _pag_sc.screenshot()
        _screen      = _np.array(_screenshot)
        _ox, _oy     = (region[0], region[1]) if region else (0, 0)
        _screen_bgr  = _cv2.cvtColor(_screen, _cv2.COLOR_RGB2BGR)
        _screen_gray = _cv2.cvtColor(_screen_bgr, _cv2.COLOR_BGR2GRAY)
        _screen_gray = _cv2.GaussianBlur(_screen_gray, (3,3), 0)
        _tmpl_bgr  = _cv2.imread(target_path)
        if _tmpl_bgr is None: return None
        _tmpl_gray = _cv2.cvtColor(_tmpl_bgr, _cv2.COLOR_BGR2GRAY)
        _tmpl_gray = _cv2.GaussianBlur(_tmpl_gray, (3,3), 0)
        _h, _w = _tmpl_gray.shape[:2]
        _best = None; _best_val = -1
        # DPI farklılıklarını (125%/150%/200%) karşılamak için geniş scale aralığı
        # Merkez: 1/dpi_scale (fiziksel px template → mantıksal px ekran)
        _center = 1.0 / _dpi_scale
        _lo = max(0.3, _center * 0.6)
        _hi = min(2.5, _center * 1.7)
        for _sc in _np.linspace(_lo, _hi, 25):
            _rw, _rh = int(_w*_sc), int(_h*_sc)
            if _rw < 8 or _rh < 8: continue
            if _rw > _screen_gray.shape[1] or _rh > _screen_gray.shape[0]: continue
            _res = _cv2.matchTemplate(_screen_gray, _cv2.resize(_tmpl_gray,(_rw,_rh)), _cv2.TM_CCOEFF_NORMED)
            _, _val, _, _loc = _cv2.minMaxLoc(_res)
            if _val > _best_val: _best_val = _val; _best = (_loc, _rw, _rh)
        if _best_val >= threshold and _best:
            _loc, _rw, _rh = _best
            return (_loc[0] + _rw//2 + _ox, _loc[1] + _rh//2 + _oy)
    except ImportError:
        try:
            import pyautogui as _pag2
            _loc2 = _pag2.locateOnScreen(target_path, grayscale=True,
                                          confidence=min(0.8, threshold), region=region)
            if _loc2: return (_pag2.center(_loc2).x, _pag2.center(_loc2).y)
        except Exception: pass
    except Exception: pass
    return None

def _do_robust_click(x, y, button="left"):
    import pyautogui as _pag3
    _pag3.moveTo(x, y, duration=0.2)
    _itime.sleep(0.3)
    _pag3.mouseDown(button=button)
    _itime.sleep(0.05)
    _pag3.mouseUp(button=button)

def _find_b64_on_screen_web(b64_data, threshold=0.80, timeout=10):
    """Web için: görseli ekranda ara (pencere kısıtlaması olmadan)."""
    return _find_b64_on_screen(b64_data, threshold=threshold, timeout=timeout)
'''


DESKTOP_HELPER = '''
import pyautogui as _pag
import subprocess as _dsproc
import time, base64 as _b64, requests as _req, re as _re3, io as _io

_pag.FAILSAFE = True
_pag.PAUSE    = 0.25

# ── Opsiyonel bağımlılıklar ───────────────────────────────────────────────────
try:
    import pytesseract as _tess
    from PIL import Image as _PILImg
    _TESS_OK = True
except Exception:
    _TESS_OK = False
    print("[DESKTOP] pytesseract kullanılamıyor — OCR devre dışı")

try:
    from pywinauto import Application as _PwApp
    from pywinauto.findwindows import ElementNotFoundError as _PwNotFound
    _PW_OK = True
except Exception:
    _PW_OK = False
    print("[DESKTOP] pywinauto kullanılamıyor — pencere kontrolü devre dışı")


def _ollama_url():
    try:
        import json as _js2, pathlib as _pl2
        _cp2 = _pl2.Path(_AI_CONFIG_PATH) if "_AI_CONFIG_PATH" in globals() else None
        if _cp2 and _cp2.exists():
            return _js2.loads(_cp2.read_text(encoding="utf-8")).get("ollama_url", "http://localhost:11434/api/generate")
    except Exception:
        pass
    return "http://localhost:11434/api/generate"

def _ollama_model():
    try:
        import json as _js2, pathlib as _pl2
        _cp2 = _pl2.Path(_AI_CONFIG_PATH) if "_AI_CONFIG_PATH" in globals() else None
        if _cp2 and _cp2.exists():
            return _js2.loads(_cp2.read_text(encoding="utf-8")).get("ollama_model", "gemma3:4b")
    except Exception:
        pass
    return "gemma3:4b"


def _screenshot_b64():
    shot = _pag.screenshot()
    buf  = _io.BytesIO()
    shot.save(buf, format="PNG")
    return _b64.b64encode(buf.getvalue()).decode()


def _vision_find_desktop(search_text):
    """Gemini veya Ollama ile ekranda koordinat bul. (x, y) veya (None, None) döner."""
    try:
        shot_b64 = _screenshot_b64()
        try:
            import json as _js, pathlib as _pl
            cfg = {}
            _cp = _pl.Path(_AI_CONFIG_PATH) if "_AI_CONFIG_PATH" in dir() else None
            if _cp and _cp.exists():
                cfg = _js.loads(_cp.read_text(encoding="utf-8"))
            gemini_key = cfg.get("gemini_api_key", "")
        except Exception:
            gemini_key = ""

        _prompt = (f"Windows masaüstü ekranında \'{search_text}\' yazan veya "
                   f"gösteren tıklanabilir elementi bul. Yanıtı sadece: x=NNN y=NNN")

        if gemini_key:
            resp = _req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [
                    {"text": _prompt},
                    {"inline_data": {"mime_type": "image/png", "data": shot_b64}}
                ]}]},
                timeout=15
            )
            answer = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            resp = _req.post(_ollama_url(), json={
                "model": _ollama_model(), "prompt": _prompt,
                "images": [shot_b64], "stream": False
            }, timeout=60)
            answer = resp.json().get("response", "")

        mx = _re3.search(r"x[=:\s]*(\d+)", answer, _re3.IGNORECASE)
        my = _re3.search(r"y[=:\s]*(\d+)", answer, _re3.IGNORECASE)
        if mx and my:
            x, y = int(mx.group(1)), int(my.group(1))
            print(f"[VISION] Koordinat: ({x}, {y})")
            return x, y
        print(f"[VISION] Koordinat bulunamadı — yanıt: {answer[:80]}")
    except Exception as _ve:
        print(f"[VISION] Hata: {_ve}")
    return None, None


def _get_active_window():
    """Aktif pencereyi pywinauto ile döndür."""
    if not _PW_OK:
        return None
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return _PwApp(backend="uia").connect(handle=hwnd).top_window()
    except Exception:
        return None


def _safe_click_desktop(target, window_title=""):
    """
    Desktop tıklama — 4 strateji:
    1. pywinauto uia backend
    2. pywinauto win32 backend (Java/Delphi/özel UI için)
    3. pytesseract OCR (kuruluysa)
    4. Vision AI / locateOnScreen
    """
    print(f"[CLICK] '{target}' aranıyor...")

    def _pw_try(backend):
        try:
            if window_title:
                _win = _PwApp(backend=backend).connect(title_re=f".*{window_title}.*", timeout=3).top_window()
            else:
                _win = _get_active_window()
            if not _win:
                return False
            for _ctrl in [
                lambda: _win.child_window(title=target, found_index=0),
                lambda: _win.child_window(title_re=f".*{target}.*", found_index=0),
            ]:
                try:
                    _el = _ctrl()
                    if _el.exists(timeout=1):
                        _el.set_focus()
                        _el.click_input()
                        print(f"[OK] pywinauto({backend}): '{target}'")
                        return True
                except Exception:
                    continue
        except Exception as _e:
            print(f"[CLICK] pywinauto({backend}) başarısız: {_e}")
        return False

    # 1. pywinauto uia ─────────────────────────────────────────────────────────
    if _PW_OK and _pw_try("uia"):
        return True

    # 2. pywinauto win32 ───────────────────────────────────────────────────────
    if _PW_OK and _pw_try("win32"):
        return True

    # 3. pytesseract OCR ───────────────────────────────────────────────────────
    if _TESS_OK:
        try:
            shot = _pag.screenshot()
            data = _tess.image_to_data(shot, lang="tur+eng", output_type=_tess.Output.DICT)
            _tl  = target.lower()
            for _i, _w in enumerate(data["text"]):
                if _w and _tl in _w.lower() and data["conf"][_i] > 30:
                    _cx = data["left"][_i] + data["width"][_i] // 2
                    _cy = data["top"][_i]  + data["height"][_i] // 2
                    _pag.click(_cx, _cy)
                    print(f"[OK] OCR: '{_w}' @ ({_cx},{_cy})")
                    return True
        except Exception as _e:
            print(f"[CLICK] OCR başarısız: {_e}")

    # 4. locateOnScreen / Vision AI ────────────────────────────────────────────
    import os as _os2
    if _os2.path.isfile(target):
        try:
            loc = _pag.locateCenterOnScreen(target, confidence=0.8)
            if loc:
                _pag.click(loc)
                print(f"[OK] locateOnScreen: {target}")
                return True
        except Exception: pass

    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        _pag.click(_vx, _vy)
        print(f"[OK] Vision AI: '{target}' @ ({_vx},{_vy})")
        return True

    raise Exception(f"Element bulunamadı: '{target}'")


def _safe_type_desktop(text):
    """Aktif alana metin yaz — clipboard ile (Türkçe karakter desteği), fallback pyautogui."""
    print(f"[TYPE] \'{text}\'")
    try:
        import pyperclip as _clip
        _clip.copy(str(text))
        _pag.hotkey("ctrl", "v")
        print(f"[OK] Clipboard paste: \'{text}\'")
    except Exception:
        _pag.write(str(text), interval=0.04)
    time.sleep(0.2)


def _safe_double_click_desktop(target, window_title=""):
    """Desktop çift tıklama — uia → win32 → OCR → vision."""
    print(f"[DBLCLICK] '{target}' aranıyor...")

    def _pw_dbl(backend):
        try:
            _win = _PwApp(backend=backend).connect(title_re=f".*{window_title}.*", timeout=3).top_window() if window_title else _get_active_window()
            if not _win: return False
            for _ctrl in [lambda: _win.child_window(title=target, found_index=0), lambda: _win.child_window(title_re=f".*{target}.*", found_index=0)]:
                try:
                    _el = _ctrl()
                    if _el.exists(timeout=1):
                        _el.set_focus(); _el.double_click_input()
                        print(f"[OK] pywinauto({backend}) çift tıkla: '{target}'"); return True
                except Exception: continue
        except Exception as _e:
            print(f"[DBLCLICK] pywinauto({backend}) başarısız: {_e}")
        return False

    if _PW_OK and _pw_dbl("uia"): return True
    if _PW_OK and _pw_dbl("win32"): return True

    if _TESS_OK:
        try:
            shot = _pag.screenshot()
            data = _tess.image_to_data(shot, lang="tur+eng", output_type=_tess.Output.DICT)
            for _i, _w in enumerate(data["text"]):
                if _w and target.lower() in _w.lower() and data["conf"][_i] > 30:
                    _cx = data["left"][_i] + data["width"][_i] // 2
                    _cy = data["top"][_i]  + data["height"][_i] // 2
                    _pag.doubleClick(_cx, _cy)
                    print(f"[OK] OCR çift tıkla: '{_w}' @ ({_cx},{_cy})"); return True
        except Exception as _e:
            print(f"[DBLCLICK] OCR başarısız: {_e}")

    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        _pag.doubleClick(_vx, _vy); print(f"[OK] Vision çift tıkla: '{target}' @ ({_vx},{_vy})"); return True
    raise Exception(f"Element bulunamadı (çift tıkla): '{target}'")


def _safe_right_click_desktop(target, window_title=""):
    """Desktop sağ tıklama — uia → win32 → OCR → vision."""
    print(f"[RCLICK] '{target}' aranıyor...")

    def _pw_right(backend):
        try:
            _win = _PwApp(backend=backend).connect(title_re=f".*{window_title}.*", timeout=3).top_window() if window_title else _get_active_window()
            if not _win: return False
            for _ctrl in [lambda: _win.child_window(title=target, found_index=0), lambda: _win.child_window(title_re=f".*{target}.*", found_index=0)]:
                try:
                    _el = _ctrl()
                    if _el.exists(timeout=1):
                        _el.set_focus(); _el.right_click_input()
                        print(f"[OK] pywinauto({backend}) sağ tıkla: '{target}'"); return True
                except Exception: continue
        except Exception as _e:
            print(f"[RCLICK] pywinauto({backend}) başarısız: {_e}")
        return False

    if _PW_OK and _pw_right("uia"): return True
    if _PW_OK and _pw_right("win32"): return True

    if _TESS_OK:
        try:
            shot = _pag.screenshot()
            data = _tess.image_to_data(shot, lang="tur+eng", output_type=_tess.Output.DICT)
            for _i, _w in enumerate(data["text"]):
                if _w and target.lower() in _w.lower() and data["conf"][_i] > 30:
                    _cx = data["left"][_i] + data["width"][_i] // 2
                    _cy = data["top"][_i]  + data["height"][_i] // 2
                    _pag.rightClick(_cx, _cy)
                    print(f"[OK] OCR sağ tıkla: '{_w}' @ ({_cx},{_cy})"); return True
        except Exception as _e:
            print(f"[RCLICK] OCR başarısız: {_e}")

    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        _pag.rightClick(_vx, _vy); print(f"[OK] Vision sağ tıkla: '{target}' @ ({_vx},{_vy})"); return True
    raise Exception(f"Element bulunamadı (sağ tıkla): '{target}'")


def _safe_menu_click_desktop(items, window_title=""):
    """Menü zinciri tıkla: [\'Dosya\', \'Yeni\'] sırayla tıklar."""
    print(f"[MENU] {' > '.join(items)}")
    for _item in items:
        _safe_click_desktop(_item, window_title)
        time.sleep(0.4)
    print(f"[OK] Menü tamamlandı: {' > '.join(items)}")


def _safe_wait_for_desktop(target, timeout=10):
    """Element ekranda görünene kadar bekle (polling)."""
    import time as _tw
    print(f"[WAIT] \'{target}\' bekleniyor (max {timeout}s)...")
    _start = _tw.time()
    while _tw.time() - _start < timeout:
        if _PW_OK:
            try:
                _win = _get_active_window()
                if _win:
                    _el = _win.child_window(title_re=f".*{target}.*", found_index=0)
                    if _el.exists(timeout=1):
                        print(f"[OK] pywinauto görüldü: \'{target}\'")
                        return True
            except Exception:
                pass
        if _TESS_OK:
            try:
                _txt = _tess.image_to_string(_pag.screenshot(), lang="tur+eng")
                if target.lower() in _txt.lower():
                    print(f"[OK] OCR görüldü: \'{target}\'")
                    return True
            except Exception:
                pass
        _tw.sleep(1)
    print(f"[WARN] \'{target}\' {timeout}s içinde görünmedi")
    return False


def _safe_assert_desktop(target):
    """Ekranda element / metin doğrula. Bulamazsa AssertionError fırlatır."""
    print(f"[ASSERT] \'{target}\' kontrol ediliyor...")

    # pywinauto
    if _PW_OK:
        try:
            _win = _get_active_window()
            if _win:
                _el = _win.child_window(title_re=f".*{target}.*", found_index=0)
                if _el.exists(timeout=1):
                    print(f"[OK] pywinauto: \'{target}\'"); return
        except Exception:
            pass

    # OCR — sadece uygulama penceresiyle sınırlı
    if _TESS_OK:
        try:
            _region = _get_window_region()
            shot = _pag.screenshot(region=_region) if _region else _pag.screenshot()
            _txt = _tess.image_to_string(shot, lang="tur+eng")
            if target.lower() in _txt.lower():
                print(f"[OK] OCR: \'{target}\'"); return
        except Exception:
            pass

    # Vision
    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        print(f"[OK] Vision: \'{target}\'"); return

    raise AssertionError(f"[FAIL] \'{target}\' ekranda bulunamadi")

def _refocus_window():
    """Her adım öncesi pencereyi öne getirir — başlık veya süreç adıyla bulur."""
    import os as _os_rf
    _exe_name = _os_rf.path.basename(_APP_PATH).lower() if "_APP_PATH" in globals() and _APP_PATH else ""

    def _bring_hwnd(hwnd):
        try:
            import win32gui as _wg_r, win32con as _wc_r
            _wg_r.ShowWindow(hwnd, _wc_r.SW_RESTORE)
            _wg_r.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

    # 1. Pencere başlığıyla bul ──────────────────────────────────────────────
    if _WINDOW_TITLE:
        try:
            import win32gui as _wg, win32con as _wc
            _found_hwnd = None
            def _cb(hwnd, _):
                nonlocal _found_hwnd
                t = _wg.GetWindowText(hwnd)
                if _WINDOW_TITLE.lower() in t.lower() and _wg.IsWindowVisible(hwnd):
                    _found_hwnd = hwnd
                    return False
                return True
            _wg.EnumWindows(_cb, None)
            if _found_hwnd:
                _wg.ShowWindow(_found_hwnd, _wc.SW_RESTORE)
                _wg.SetForegroundWindow(_found_hwnd)
                return
        except Exception:
            pass
        if _PW_OK:
            try:
                _PwApp(backend="uia").connect(title_re=".*" + _WINDOW_TITLE + ".*", timeout=3).top_window().set_focus()
                return
            except Exception:
                pass

    # 2. Süreç adıyla pencere bul (window_title boşsa) ──────────────────────
    if _exe_name:
        try:
            import win32gui as _wg2, win32process as _wp2, win32con as _wc2
            import psutil as _psu_rf
            _pids = {p.pid for p in _psu_rf.process_iter(["name"]) if p.info["name"].lower() == _exe_name}
            _wins = []
            def _cb2(hwnd, _):
                if _wg2.IsWindowVisible(hwnd) and _wg2.GetWindowText(hwnd):
                    _, _pid = _wp2.GetWindowThreadProcessId(hwnd)
                    if _pid in _pids:
                        _wins.append(hwnd)
                return True
            _wg2.EnumWindows(_cb2, None)
            if _wins:
                _wg2.ShowWindow(_wins[0], _wc2.SW_RESTORE)
                _wg2.SetForegroundWindow(_wins[0])
                return
        except Exception:
            pass
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
        "import time, socket",
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        STOP_HELPER,
        f'_DEVICE_ID = "{device}"  # ADB komutları için cihaz ID',
        f'_AI_CONFIG_PATH = r"{os.path.join(_ROUTER_BASE_DIR, "ai_config.json")}"',
        "",
        "# ── Appium bağlantı kontrolü ─────────────────────────────────",
        f'_appium_host = "{appium.split("//")[-1].split("/")[0]}"',
        f'_appium_port = {appium.rstrip("/").split(":")[-1] if ":" in appium.split("//")[-1] else 4723}',
        "try:",
        "    _s = socket.create_connection((_appium_host.split(':')[0], _appium_port), timeout=3)",
        "    _s.close()",
        "except OSError:",
        f'    print(f"[HATA] Appium sunucusu {appium} adresinde çalışmıyor!")',
        '    print("[HATA] Lütfen terminalde \\"appium\\" komutunu çalıştırın.")',
        "    raise SystemExit(1)",
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
            "_fx_opts.add_argument('--headless')\n"
            "_fx_opts.add_argument('--width=1920')\n"
            "_fx_opts.add_argument('--height=1080')\n"
            "try:\n"
            "    from webdriver_manager.firefox import GeckoDriverManager\n"
            "    driver = webdriver.Firefox(service=_FxSvc(GeckoDriverManager().install()), options=_fx_opts)\n"
            "except Exception:\n"
            "    driver = webdriver.Firefox(options=_fx_opts)"
        )
    elif browser == "edge":
        driver_setup = (
            "from selenium.webdriver.edge.options import Options as _EdgeOpts\n"
            "_edge_opts = _EdgeOpts()\n"
            "_edge_opts.add_argument('--headless')\n"
            "_edge_opts.add_argument('--window-size=1920,1080')\n"
            "_edge_opts.add_argument('--disable-gpu')\n"
            "try:\n"
            "    from webdriver_manager.microsoft import EdgeChromiumDriverManager\n"
            "    from selenium.webdriver.edge.service import Service as _EdgeSvc\n"
            "    driver = webdriver.Edge(service=_EdgeSvc(EdgeChromiumDriverManager().install()), options=_edge_opts)\n"
            "except Exception:\n"
            "    driver = webdriver.Edge(options=_edge_opts)"
        )
    else:  # chrome (default)
        driver_setup = (
            "from selenium.webdriver.chrome.options import Options as _CrOpts\n"
            "_cr_opts = _CrOpts()\n"
            "_cr_opts.add_argument('--headless=new')\n"
            "_cr_opts.add_argument('--window-size=1920,1080')\n"
            "_cr_opts.add_argument('--disable-gpu')\n"
            "_cr_opts.add_argument('--no-sandbox')\n"
            "_cr_opts.add_argument('--disable-dev-shm-usage')\n"
            "try:\n"
            "    from webdriver_manager.chrome import ChromeDriverManager\n"
            "    from selenium.webdriver.chrome.service import Service as _CrSvc\n"
            "    driver = webdriver.Chrome(service=_CrSvc(ChromeDriverManager().install()), options=_cr_opts)\n"
            "except Exception:\n"
            "    driver = webdriver.Chrome(options=_cr_opts)"
        )

    lines = [
        "# -*- coding: utf-8 -*-",
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "import time",
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        driver_setup,
        "",
        "# ── Tarayıcı başlatılamadıysa net hata ver ───────────────────",
        "if 'driver' not in dir():",
        '    print("[HATA] Tarayıcı sürücüsü başlatılamadı. Chrome/Firefox kurulu mu?")',
        "    raise SystemExit(1)",
        "",
        STOP_HELPER,
        IMAGE_HELPER,
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


def _build_desktop_template(req: GenerateRequest, steps_code: str) -> str:
    app_path      = (req.app_path     or "").strip()
    window_title  = (req.window_title or "").strip()
    reuse_instance = getattr(req, "reuse_instance", True)

    # Escape backslashes so Windows paths don't cause unicode escape SyntaxError
    app_path_esc     = app_path.replace('\\', '\\\\')
    window_title_esc = window_title.replace('\\', '\\\\')

    # _POPEN_KW: uygulama başlatırken stdout/stderr/stdin devralmasın, pipe kapanmasın
    _POPEN_DEVNULL = (
        "_dsproc.Popen(r\"{}\", shell=True, "
        "stdout=_dsproc.DEVNULL, stderr=_dsproc.DEVNULL, stdin=_dsproc.DEVNULL)"
    )

    lines = [
        "# -*- coding: utf-8 -*-",
        "import pyautogui as _pag",
        "import subprocess as _dsproc",
        "import sys",
        "import time",
        "",
        f'_AI_CONFIG_PATH = r"{os.path.join(_ROUTER_BASE_DIR, "ai_config.json")}"',
        f'_WINDOW_TITLE   = "{window_title_esc}"',
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        STOP_HELPER,
        IMAGE_HELPER,
        DESKTOP_HELPER,
        "",
    ]

    # Uygulama başlat
    if app_path:
        popen_line = _POPEN_DEVNULL.format(app_path_esc)
        if reuse_instance:
            lines += [
                '# ── Uygulama başlat (zaten açıksa geç + öne getir) ──────────',
                'def _is_app_running():',
                '    """Uygulama çalışıyorsa True döner ve penceresini öne getirir."""',
                '    # 1) Pencere başlığıyla kontrol (win32gui) ─────────────────',
                f'    _wtitle = "{window_title_esc}"',
                '    if _wtitle:',
                '        try:',
                '            import win32gui as _wg2',
                '            _fnd = []',
                '            def _cb2(hwnd, _):',
                '                t = _wg2.GetWindowText(hwnd)',
                '                if _wtitle.lower() in t.lower() and _wg2.IsWindowVisible(hwnd):',
                '                    _fnd.append(hwnd)',
                '                return True',
                '            _wg2.EnumWindows(_cb2, None)',
                '            if _fnd:',
                '                try: _wg2.SetForegroundWindow(_fnd[0])',
                '                except Exception: pass',
                '                return True',
                '        except Exception: pass',
                '        # pywinauto fallback ─────────────────────────────────',
                '        if _PW_OK:',
                '            try:',
                f'                _PwApp(backend="uia").connect(title_re=".*{window_title_esc}.*", timeout=2).top_window().set_focus()',
                '                return True',
                '            except Exception: pass',
                '    # 2) Surec adiyla kontrol + PID bazli pencere odakla ───────',
                '    try:',
                '        import os as _os2, subprocess as _sp2',
                f'        _exe2 = _os2.path.basename(r"{app_path_esc}")',
                '        if not _exe2: return False',
                '        _proc_found = False',
                '        _boa_pids: set = set()',
                '        # psutil varsa kullan (daha güvenilir) ─────────────────',
                '        try:',
                '            import psutil as _psu2',
                '            for _p2 in _psu2.process_iter(["name", "pid"]):',
                '                if _exe2.lower() == _p2.info["name"].lower():',
                '                    _boa_pids.add(_p2.info["pid"]); _proc_found = True',
                '        except ImportError:',
                '            # tasklist fallback ──────────────────────────────',
                '            _r2 = _sp2.run(["tasklist", "/FI", f"IMAGENAME eq {_exe2}", "/NH"],',
                '                           capture_output=True, text=True, timeout=3)',
                '            _proc_found = _exe2.lower() in _r2.stdout.lower()',
                '        if not _proc_found: return False',
                '        # Sürece ait pencereyi bul ve öne getir ─────────────────',
                '        try:',
                '            import win32gui as _wg3, win32process as _wp3',
                '            _boa_wins = []',
                '            def _cb3(hwnd, _):',
                '                if _wg3.IsWindowVisible(hwnd) and _wg3.GetWindowText(hwnd):',
                '                    _tid, _pid = _wp3.GetWindowThreadProcessId(hwnd)',
                '                    if not _boa_pids or _pid in _boa_pids:',
                '                        _boa_wins.append(hwnd)',
                '                return True',
                '            _wg3.EnumWindows(_cb3, None)',
                '            if _boa_wins: _wg3.SetForegroundWindow(_boa_wins[0])',
                '        except Exception: pass',
                '        return True',
                '    except Exception: pass',
                '    return False',
                'if _is_app_running():',
                '    print("[OK] Uygulama zaten açık — mevcut pencere öne getirildi")',
                'else:',
                f'    print("Başlatılıyor: {app_path_esc}")',
                f'    {popen_line}',
                '    # BOA penceresini bekle (max 30 saniye)',
                '    _wait_start = time.time()',
                '    _win_found = False',
                f'    _wait_exe = "{os.path.basename(app_path_esc).lower()}"',
                f'    _wait_title = "{window_title_esc}"',
                '    while time.time() - _wait_start < 30:',
                '        try:',
                '            import win32gui as _wg_w, win32process as _wp_w, win32con as _wc_w',
                '            # Süreç PID\'lerini bul',
                '            _pids_w = set()',
                '            try:',
                '                import psutil as _psu_w',
                '                _pids_w = {p.pid for p in _psu_w.process_iter(["name"]) if p.info["name"].lower() == _wait_exe}',
                '            except ImportError:',
                '                import subprocess as _sp_w',
                '                _r_w = _sp_w.run(["tasklist", "/FI", f"IMAGENAME eq {_wait_exe}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5)',
                '                for _ln_w in _r_w.stdout.splitlines():',
                '                    _parts_w = _ln_w.strip(\'"\').split(\'","\')',
                '                    if len(_parts_w) > 1:',
                '                        try: _pids_w.add(int(_parts_w[1]))',
                '                        except: pass',
                '            if not _pids_w:',
                '                time.sleep(1); continue',
                '            _wins_w = []',
                '            def _cb_w(hwnd, _):',
                '                if _wg_w.IsWindowVisible(hwnd) and _wg_w.GetWindowText(hwnd):',
                '                    _, _pid_w = _wp_w.GetWindowThreadProcessId(hwnd)',
                '                    if _pid_w in _pids_w:',
                '                        _t_w = _wg_w.GetWindowText(hwnd)',
                '                        if not _wait_title or _wait_title.lower() in _t_w.lower():',
                '                            _wins_w.append(hwnd)',
                '                return True',
                '            _wg_w.EnumWindows(_cb_w, None)',
                '            if _wins_w:',
                '                _wg_w.ShowWindow(_wins_w[0], _wc_w.SW_RESTORE)',
                '                _wg_w.SetForegroundWindow(_wins_w[0])',
                '                _win_found = True',
                '                print(f"[OK] Pencere {time.time()-_wait_start:.1f}s sonra görüldü")',
                '                break',
                '        except Exception: pass',
                '        time.sleep(1)',
                '    if not _win_found: print("[WARN] Uygulama penceresi 30s içinde görünmedi, devam ediliyor")',
                '    time.sleep(2)',
                '',
            ]
        else:
            lines += [
                '# ── Uygulama başlat ─────────────────────────────────────────',
                f'print("Başlatılıyor: {app_path_esc}")',
                popen_line,
                'time.sleep(2)',
                '',
            ]

    # Pencereyi öne getir
    if window_title:
        lines += [
            '# ── Pencereyi öne getir ─────────────────────────────────────',
            'if _PW_OK:',
            '    try:',
            f'        _PwApp(backend="uia").connect(title_re=".*{window_title_esc}.*", timeout=10).top_window().set_focus()',
            f'        print("[OK] Pencere: {window_title_esc}")',
            '    except Exception as _we:',
            '        print(f"[WARN] Pencere bulunamadı: {{_we}}")',
            '',
        ]

    lines += ["try:"]
    for line in steps_code.splitlines():
        lines.append("    " + line if line.strip() else "")

    lines += [
        "",
        "except Exception as e:",
        '    print(f"HATA: {e}")',
        "    raise",
        "",
        "sys.exit(0)",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4: ANA DÖNÜŞÜM MOTORU
# ══════════════════════════════════════════════════════════════════════════════

def _image_step_code(item: "StepItem", platform: str, idx: int) -> str:
    """Görsel adımı için Python kodu üretir. base64 scripte gömülür."""
    b64  = item.image_b64
    desc = item.content or f"Görsel adım {idx+1}"
    if platform == "desktop":
        if item.action == "assert":
            return (
                f"# [GÖRSEL DOĞRULA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"try:\n"
                f"    _refocus_window()\n"
                f"    _img_b64_{idx} = '{b64}'\n"
                f"    _res_{idx} = _find_b64_on_screen(_img_b64_{idx}, timeout=8)\n"
                f"    if not _res_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
                f"    print('[OK] Gorsel dogrulandi: {desc}')\n"
                f"    print('STEP_DONE:{idx}')\n"
                f"except Exception as _e_{idx}:\n"
                f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                f"    print('STEP_FAIL:{idx}')\n"
                f"    raise"
            )
        else:
            click_line = {
                "double_click": f"    import pyautogui as _pag_d; _pag_d.doubleClick(_coords_{idx}[0], _coords_{idx}[1])",
                "right_click":  f"    import pyautogui as _pag_d; _pag_d.rightClick(_coords_{idx}[0], _coords_{idx}[1])",
            }.get(item.action, f"    _do_robust_click(_coords_{idx}[0], _coords_{idx}[1])")
            return (
                f"# [GÖRSEL TIKLAMA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"try:\n"
                f"    _refocus_window()\n"
                f"    _img_b64_{idx} = '{b64}'\n"
                f"    _coords_{idx} = _find_b64_on_screen(_img_b64_{idx}, timeout=10)\n"
                f"    if not _coords_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
                f"{click_line}\n"
                f"    print('[OK] Gorsel tiklandi: {desc}')\n"
                f"    time.sleep(0.5)\n"
                f"    print('STEP_DONE:{idx}')\n"
                f"except Exception as _e_{idx}:\n"
                f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                f"    print('STEP_FAIL:{idx}')\n"
                f"    raise"
            )
    else:  # web
        if item.action == "assert":
            return (
                f"# [GÖRSEL DOĞRULA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"try:\n"
                f"    _img_b64_{idx} = '{b64}'\n"
                f"    _res_{idx} = _find_b64_on_screen_web(_img_b64_{idx}, timeout=8)\n"
                f"    if not _res_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
                f"    print('[OK] Gorsel dogrulandi: {desc}')\n"
                f"    print('STEP_DONE:{idx}')\n"
                f"except Exception as _e_{idx}:\n"
                f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                f"    print('STEP_FAIL:{idx}')\n"
                f"    raise"
            )
        else:
            click_line = {
                "double_click": f"    import pyautogui as _pag_web; _pag_web.doubleClick(_coords_{idx}[0], _coords_{idx}[1])",
                "right_click":  f"    import pyautogui as _pag_web; _pag_web.rightClick(_coords_{idx}[0], _coords_{idx}[1])",
            }.get(item.action, f"    import pyautogui as _pag_web; _pag_web.click(_coords_{idx}[0], _coords_{idx}[1])")
            return (
                f"# [GÖRSEL TIKLAMA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"try:\n"
                f"    _img_b64_{idx} = '{b64}'\n"
                f"    _coords_{idx} = _find_b64_on_screen_web(_img_b64_{idx}, timeout=10)\n"
                f"    if not _coords_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
                f"{click_line}\n"
                f"    print('[OK] Gorsel tiklandi: {desc}')\n"
                f"    time.sleep(0.5)\n"
                f"    print('STEP_DONE:{idx}')\n"
                f"except Exception as _e_{idx}:\n"
                f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                f"    print('STEP_FAIL:{idx}')\n"
                f"    raise"
            )


def _sql_step_code(item: "StepItem", idx: int) -> str:
    """SQL adımı için Python kodu üretir."""
    desc  = item.content or f"SQL {idx+1}"
    conn  = item.db_connection or "sqlite:///test.db"
    query = item.sql_query or "SELECT 1"
    is_print  = item.action != "execute"
    is_sqlite = conn.strip().lower().startswith("sqlite:///")
    # DRIVER= içeriyorsa doğrudan pyodbc — SQLAlchemy URL parsing sorununu önler
    is_odbc   = "DRIVER=" in conn.upper()

    conn_r  = repr(conn)
    query_r = repr(query)

    if is_sqlite:
        db_path = conn.strip()[len("sqlite:///"):]
        var_store = ""
        if item.var_name:
            var_store = (
                f"\n    _VARS[{repr(item.var_name)}] = str(_rows_{idx}[0][0] if _rows_{idx} else '')"
                f"\n    print(f'[SQL→_VARS] {item.var_name} = {{_VARS[{repr(item.var_name)}]}}')"
            )
        if is_print:
            result_code = (
                f"    _rows_{idx} = _cur_{idx}.fetchall()\n"
                f"    print(f'[SQL] {{len(_rows_{idx})}} kayit:')\n"
                f"    for _r in _rows_{idx}: print('  ', _r)"
                f"{var_store}"
            )
        else:
            result_code = (
                f"    _db_{idx}.commit()\n"
                f"    print(f'[SQL] {{_cur_{idx}.rowcount}} satir etkilendi')"
                f"{var_store}"
            )
        return (
            f"# [SQL] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"    import sqlite3 as _sq_{idx}\n"
            f"    _db_{idx} = _sq_{idx}.connect({repr(db_path)})\n"
            f"    _cur_{idx} = _db_{idx}.cursor()\n"
            f"    _cur_{idx}.execute({query_r})\n"
            f"{result_code}\n"
            f"    _db_{idx}.close()\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )
    elif is_odbc:
        # pyodbc doğrudan bağlantı (ODBC connection string — {DRIVER} parantezleri güvenli)
        var_store = ""
        if item.var_name:
            var_store = (
                f"\n    _VARS[{repr(item.var_name)}] = str(_rows_{idx}[0][0] if _rows_{idx} else '')"
                f"\n    print(f'[SQL→_VARS] {item.var_name} = {{_VARS[{repr(item.var_name)}]}}')"
            )
        if is_print:
            result_code = (
                f"    _rows_{idx} = _cur_{idx}.fetchall()\n"
                f"    print(f'[SQL] {{len(_rows_{idx})}} kayit:')\n"
                f"    for _r in _rows_{idx}: print('  ', list(_r))"
                f"{var_store}"
            )
        else:
            result_code = (
                f"    _db_{idx}.commit()\n"
                f"    print(f'[SQL] {{_cur_{idx}.rowcount}} satir etkilendi')"
                f"{var_store}"
            )
        return (
            f"# [SQL] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"    import pyodbc as _pyodbc_{idx}\n"
            f"    _db_{idx} = _pyodbc_{idx}.connect({conn_r})\n"
            f"    _cur_{idx} = _db_{idx}.cursor()\n"
            f"    _cur_{idx}.execute({query_r})\n"
            f"{result_code}\n"
            f"    _db_{idx}.close()\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )
    else:
        var_store = ""
        if item.var_name:
            var_store = (
                f"\n        _VARS[{repr(item.var_name)}] = str(_rows_{idx}[0][0] if _rows_{idx} else '')"
                f"\n        print(f'[SQL→_VARS] {item.var_name} = {{_VARS[{repr(item.var_name)}]}}')"
            )
        if is_print:
            result_code = (
                f"        _rows_{idx} = list(_res_{idx})\n"
                f"        print(f'[SQL] {{len(_rows_{idx})}} kayit:')\n"
                f"        for _r in _rows_{idx}: print('  ', dict(_r._mapping))"
                f"{var_store}"
            )
        else:
            result_code = (
                f"        _conn_{idx}.commit()\n"
                f"        print(f'[SQL] {{_res_{idx}.rowcount}} satir etkilendi')"
                f"{var_store}"
            )
        return (
            f"# [SQL] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"    from sqlalchemy import create_engine as _ce_{idx}, text as _st_{idx}\n"
            f"    _eng_{idx} = _ce_{idx}({conn_r})\n"
            f"    with _eng_{idx}.connect() as _conn_{idx}:\n"
            f"        _res_{idx} = _conn_{idx}.execute(_st_{idx}({query_r}))\n"
            f"{result_code}\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except ImportError:\n"
            f"    print('[FAIL] sqlalchemy kurulu degil: pip install sqlalchemy pymysql')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )


def _api_step_code(item: "StepItem", idx: int) -> str:
    """API adımı için Python kodu üretir."""
    desc    = item.content or f"API {idx+1}"
    url     = item.api_url or ""
    method  = (item.api_method or "GET").lower()
    headers = item.api_headers.strip() if item.api_headers else ""
    body    = item.api_body.strip()    if item.api_body    else ""
    action  = item.action or "print"

    headers_line = f"    _hdrs_{idx} = {headers}" if headers and headers.startswith("{") else f"    _hdrs_{idx} = {{}}"
    body_arg = ""
    if method in ("post", "put", "patch") and body and body.startswith("{"):
        body_line = f"    _body_{idx} = {body}\n"
        body_arg  = f", json=_body_{idx}"
    else:
        body_line = ""

    # json_field ve var_name için yardımcı kod
    json_field  = item.json_field.strip() if item.json_field else ""
    var_name    = item.var_name.strip()   if item.var_name   else ""

    extract_code = ""
    if json_field or var_name:
        extract_code = (
            f"    _api_json_{idx} = _resp_{idx}.json()\n"
        )
        if json_field:
            extract_code += (
                f"    def _jpath_{idx}(d, p):\n"
                f"        for k in p.split('.'):\n"
                f"            if isinstance(d, dict): d = d.get(k)\n"
                f"            elif isinstance(d, list):\n"
                f"                try: d = d[int(k)]\n"
                f"                except: return None\n"
                f"            else: return None\n"
                f"        return d\n"
                f"    _extracted_{idx} = _jpath_{idx}(_api_json_{idx}, {repr(json_field)})\n"
                f"    print(f'[API.{json_field}] {{_extracted_{idx}}}')\n"
            )
            if var_name:
                extract_code += (
                    f"    _VARS[{repr(var_name)}] = str(_extracted_{idx} if _extracted_{idx} is not None else '')\n"
                    f"    print(f'[API→_VARS] {var_name} = {{_VARS[{repr(var_name)}]}}')\n"
                )
        elif var_name:
            extract_code += (
                f"    _VARS[{repr(var_name)}] = str(_api_json_{idx})[:500]\n"
                f"    print(f'[API→_VARS] {var_name} = {{_VARS[{repr(var_name)}][:100]}}')\n"
            )

    if action == "print":
        resp_code = (
            f"    _resp_{idx}.raise_for_status()\n"
            f"    print(f'[API] Status: {{_resp_{idx}.status_code}}')\n"
            f"    print(f'[API] Yanit: {{_resp_{idx}.text[:500]}}')\n"
            f"{extract_code}"
        )
    elif action == "store":
        resp_code = (
            f"    _resp_{idx}.raise_for_status()\n"
            f"{extract_code}"
            f"    print(f'[API] Degisken: _api_result = {{str(_resp_{idx}.json())[:300]}}')"
        )
    else:
        resp_code = (
            f"    print(f'[API] Status: {{_resp_{idx}.status_code}}')  \n"
            f"{extract_code}"
        )

    return (
        f"# [API] {method.upper()} {url} — {desc}\n"
        f"print('STEP_START:{idx}')\n"
        f"try:\n"
        f"    import requests as _rm\n"
        f"{headers_line}\n"
        f"{body_line}"
        f"    _resp_{idx} = _rm.{method}({repr(url)}, headers=_hdrs_{idx}{body_arg}, timeout=30)\n"
        f"{resp_code}"
        f"    print('STEP_DONE:{idx}')\n"
        f"except Exception as _e_{idx}:\n"
        f"    print(f'[FAIL] {{_e_{idx}}}')\n"
        f"    print('STEP_FAIL:{idx}')\n"
        f"    raise"
    )


async def _generate_steps(req: GenerateRequest) -> tuple[str, list[dict]]:
    """
    Test case'i adım adım işler (metin + görsel karma destekli).
    Döndürür: (kod_str, adım_raporu)
    """
    rule_fn = (
        _rule_mobile  if req.platform == "mobile"  else
        _rule_desktop if req.platform == "desktop" else
        _rule_web
    )

    # steps_list varsa onu kullan, yoksa test_case textarea'dan oku (geriye dönük)
    if req.steps_list:
        structured = req.steps_list
    else:
        structured = [
            StepItem(type="text", content=l.strip())
            for l in req.test_case.splitlines() if l.strip()
        ]

    code_lines   = []
    unrecognized = []
    report       = []

    for idx, item in enumerate(structured):
        if item.type == "image":
            code = "_check_stop()\n" + _image_step_code(item, req.platform, idx)
            code_lines.append(("image", item.content or f"Görsel {idx+1}", code))
        elif item.type == "sql":
            code = "_check_stop()\n" + _sql_step_code(item, idx)
            code_lines.append(("rule", item.content or f"SQL {idx+1}", code))
        elif item.type == "api":
            code = "_check_stop()\n" + _api_step_code(item, idx)
            code_lines.append(("rule", item.content or f"API {idx+1}", code))
        else:
            step = item.content
            parsed = rule_fn(step)
            if parsed:
                _inner = "\n    ".join(parsed)
                wrapped = (
                    f"_check_stop()\n"
                    f"print('STEP_START:{idx}')\n"
                    f"try:\n"
                    f"    {_inner}\n"
                    f"    print('STEP_DONE:{idx}')\n"
                    f"except Exception as _e_{idx}:\n"
                    f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                    f"    print('STEP_FAIL:{idx}')\n"
                    f"    raise"
                )
                code_lines.append(("rule", step, wrapped))
            else:
                code_lines.append(("llm", step, ""))
                unrecognized.append(step)

    # LLM'e toplu sor
    llm_results = {}
    if unrecognized:
        llm_results = await _ask_llm_for_steps(unrecognized, req.platform)

    # Birleştir + rapor oluştur
    final_lines = []
    for idx, (kind, step, rule_code) in enumerate(code_lines):
        if kind in ("rule", "image"):
            final_lines.append(rule_code)
            report.append({"step": step, "method": kind, "code": rule_code, "index": idx})
        else:
            llm_code = llm_results.get(step, "")
            llm_code = "\n".join(
                l for l in llm_code.splitlines()
                if l.strip().startswith("#") or re.match(r'^\s*[a-z_].*[\(\.]', l)
            ).strip()
            if llm_code:
                llm_code = textwrap.dedent(llm_code)
            if not llm_code:
                llm_code = f"# TODO (anlasilamadi): {step}\ntime.sleep(1)"
                method = "todo"
            else:
                method = "llm"
                _llm_inner = "\n    ".join(llm_code.splitlines())
                llm_code = (
                    f"_check_stop()\n"
                    f"print('STEP_START:{idx}')\n"
                    f"# {step}\n"
                    f"try:\n"
                    f"    {_llm_inner}\n"
                    f"    print('STEP_DONE:{idx}')\n"
                    f"except Exception as _e_{idx}:\n"
                    f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                    f"    print('STEP_FAIL:{idx}')\n"
                    f"    raise"
                )
            final_lines.append(llm_code)
            report.append({"step": step, "method": method, "code": llm_code, "index": idx})
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
    elif platform == "desktop":
        api_note = (
            "Use ONLY these helpers (pyautogui-based desktop automation):\n"
            "  _safe_click_desktop('text', _WINDOW_TITLE)  — click element by visible text (pywinauto → OCR → vision)\n"
            "  _safe_type_desktop('value')                 — type text into active field\n"
            "  _safe_assert_desktop('text')                — verify text/element on screen\n"
            "  _pag.hotkey('ctrl', 's')                    — keyboard shortcut\n"
            "  _pag.press('enter')                         — press a key\n"
            "  _pag.scroll(-3)                             — scroll down\n"
            "  time.sleep(1)                               — wait"
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
            resp = await client.post(_ollama_url(), json={
                "model": _ollama_model(),
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
        result = await asyncio.to_thread(
            subprocess.run, ["adb", "devices"],
            capture_output=True, timeout=10
        )
        lines   = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
        devices = [l.split("\t")[0].strip() for l in lines[1:] if "\t" in l and "device" in l.split("\t")[1]]
        return {"devices": devices}
    except FileNotFoundError:
        raise HTTPException(500, "ADB bulunamadı")


@router.get("/adb/activity")
async def adb_get_activity(device_id: str, app_package: str, current_user: User = Depends(get_current_user)):
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["adb", "-s", device_id, "shell", "cmd", "package", "resolve-activity", "--brief", app_package],
            capture_output=True, timeout=10
        )
        output = result.stdout.decode("utf-8", errors="replace").strip()
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
        final_script = _build_desktop_template(req, steps_code)

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


def _run_log_dir(user_id: int, db) -> Path:
    """Kullanıcının run log klasörünü döndürür (workspace > local fallback)."""
    try:
        ws = _get_user_workspace(user_id, db)
        if ws:
            d = Path(ws.local_path) / "ai_run_logs"
            d.mkdir(parents=True, exist_ok=True)
            return d
    except Exception:
        pass
    d = Path(__file__).parent.parent / "local_run_logs" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/execute")
async def execute_script(
    req: ExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not req.script or len(req.script.strip()) < 10:
        raise HTTPException(400, "Geçersiz script")

    is_desktop = req.platform == "desktop"
    if is_desktop:
        lock = _get_desktop_lock()
        if lock.locked():
            raise HTTPException(423, "Şu an başka bir desktop testi çalışıyor. Lütfen bekleyin.")

    run_id     = str(uuid.uuid4())[:8]
    log_dir    = _run_log_dir(current_user.id, db)
    started_at = _datetime.datetime.utcnow().isoformat()
    step_outcomes: dict[int, str] = {}   # idx -> "pass" | "fail"
    terminal_lines: list[str] = []        # tam terminal çıktısı
    _stop_fd, stop_file = tempfile.mkstemp(suffix=".stop", prefix=f"ai_stop_{run_id}_")
    os.close(_stop_fd)
    os.unlink(stop_file)  # Dosya yokluğu = devam; varlığı = dur sinyali
    _stop_files[run_id] = stop_file

    async def stream():
        nonlocal step_outcomes
        exit_code = -1
        ended_at  = None

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_test_"
        ) as f:
            f.write(req.script)
            tmp = f.name

        yield _sse("run_id", run_id)
        yield _sse("info", f"Script: {os.path.basename(tmp)}")
        yield _sse("info", f"Platform: {req.platform}")
        yield _sse("info", "Kosum baslatiliyor...\n")

        if is_desktop:
            await _get_desktop_lock().acquire()

        proc = None
        try:
            _popen_kw: dict = dict(
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                     "_AI_STOP_FILE": stop_file},
            )
            if sys.platform == "win32":
                _popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen([sys.executable, tmp], **_popen_kw)
            _running_processes[run_id] = proc
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, proc.stdout.readline)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text.startswith("STEP_START:"):
                    idx_s = text.split(":", 1)[1].strip()
                    n_label = req.step_labels[int(idx_s)] if idx_s.isdigit() and int(idx_s) < len(req.step_labels) else f"Adım {idx_s}"
                    terminal_lines.append(f"▶ [{idx_s}] {n_label}")
                    yield _sse("step_start", idx_s)
                elif text.startswith("STEP_DONE:"):
                    idx_s = text.split(":", 1)[1].strip()
                    try: step_outcomes[int(idx_s)] = "pass"
                    except ValueError: pass
                    terminal_lines.append(f"✓ [{idx_s}] PASS")
                    yield _sse("step_done", idx_s)
                elif text.startswith("STEP_FAIL:"):
                    idx_s = text.split(":", 1)[1].strip()
                    try: step_outcomes[int(idx_s)] = "fail"
                    except ValueError: pass
                    terminal_lines.append(f"✗ [{idx_s}] FAIL")
                    yield _sse("step_fail", idx_s)
                else:
                    terminal_lines.append(text)
                    yield _sse("log", text)

            await loop.run_in_executor(None, proc.wait)
            exit_code = proc.returncode
            ended_at  = _datetime.datetime.utcnow().isoformat()
            if exit_code == 0:
                yield _sse("success", f"\nKosum tamamlandi. (exit: {exit_code})")
            else:
                yield _sse("error", f"\nKosum hata ile bitti. (exit: {exit_code})")
        except Exception as e:
            yield _sse("error", str(e))
        finally:
            _running_processes.pop(run_id, None)
            if proc and proc.poll() is None:
                proc.terminate()
            try:
                os.unlink(tmp)
            except Exception:
                pass

            # Stop dosyasını temizle
            _stop_files.pop(run_id, None)
            try:
                if os.path.exists(stop_file):
                    os.unlink(stop_file)
            except Exception:
                pass

            # ── Run log kaydet ───────────────────────────────────────────────
            try:
                n = len(req.step_labels)
                log_entry = {
                    "run_id":          run_id,
                    "scenario_name":   req.scenario_name,
                    "scenario_folder": req.scenario_folder,
                    "platform":        req.platform,
                    "started_at":      started_at,
                    "ended_at":        ended_at or _datetime.datetime.utcnow().isoformat(),
                    "exit_code":       exit_code,
                    "total_steps":     n,
                    "passed":          sum(1 for v in step_outcomes.values() if v == "pass"),
                    "failed":          sum(1 for v in step_outcomes.values() if v == "fail"),
                    "steps": [
                        {
                            "index":  i,
                            "label":  req.step_labels[i] if i < n else f"Adım {i+1}",
                            "status": step_outcomes.get(i, "unknown"),
                        }
                        for i in range(n)
                    ],
                    "terminal_log": "\n".join(terminal_lines),
                }
                (log_dir / f"{run_id}.json").write_text(
                    _json.dumps(log_entry, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

            if is_desktop:
                try:
                    _get_desktop_lock().release()
                except RuntimeError:
                    pass

            yield _sse("done", "")

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/run-logs")
async def list_run_logs(
    platform: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kullanıcının tüm koşum loglarını listeler (platform filtresi opsiyonel)."""
    log_dir = _run_log_dir(current_user.id, db)
    logs = []
    if log_dir.exists():
        for f in sorted(log_dir.glob("*.json"), reverse=True):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                if platform and data.get("platform") != platform:
                    continue
                # Hesaplanan süre
                try:
                    s = _datetime.datetime.fromisoformat(data.get("started_at", ""))
                    e = _datetime.datetime.fromisoformat(data.get("ended_at", ""))
                    dur = round((e - s).total_seconds())
                except Exception:
                    dur = None
                logs.append({
                    "run_id":        data.get("run_id", f.stem),
                    "scenario_name": data.get("scenario_name", "?"),
                    "platform":      data.get("platform", ""),
                    "started_at":    data.get("started_at", ""),
                    "duration_sec":  dur,
                    "total_steps":   data.get("total_steps", 0),
                    "passed":        data.get("passed", 0),
                    "failed":        data.get("failed", 0),
                    "exit_code":     data.get("exit_code", -1),
                })
            except Exception:
                pass
    return {"logs": logs}


@router.get("/run-logs/{run_id}")
async def get_run_log(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tek bir koşumun detaylı logunu döndürür."""
    log_dir  = _run_log_dir(current_user.id, db)
    log_file = log_dir / f"{run_id}.json"
    if not log_file.exists():
        raise HTTPException(404, "Log bulunamadı")
    return _json.loads(log_file.read_text(encoding="utf-8"))


@router.post("/run-logs/push")
async def push_run_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ai_run_logs/ klasörünü Git'e commit edip push eder."""
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadı. Önce bir repo clone edin.")
    repo = Path(ws.local_path)
    subprocess.run(["git", "add", "ai_run_logs/"], cwd=repo, capture_output=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "chore: AI test run logları güncellendi"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    if "nothing to commit" in commit.stdout or "nothing to commit" in commit.stderr:
        return {"ok": True, "message": "Yeni log yok, push yapılmadı"}
    push = subprocess.run(
        ["git", "push"], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    if push.returncode != 0:
        raise HTTPException(500, f"Push hatası: {push.stderr.strip()}")
    return {"ok": True, "message": "Loglar başarıyla push edildi ✓"}


@router.post("/stop/{run_id}")
async def stop_execution(run_id: str, current_user: User = Depends(get_current_user)):
    import signal as _sig
    proc = _running_processes.get(run_id)
    if not proc:
        raise HTTPException(404, "Koşum bulunamadı veya zaten bitti")

    # 1. Stop flag dosyası yaz — adımlar arası _check_stop() yakalar, hızlı çıkar
    sf = _stop_files.get(run_id)
    if sf:
        try:
            open(sf, "w").close()
        except Exception:
            pass

    # 2. Kısa bekle — adımlar arasındaysa graceful çıkış yeterli
    for _ in range(6):          # 3 saniye, 0.5s aralıklarla
        if proc.poll() is not None:
            return {"ok": True, "run_id": run_id}
        await asyncio.sleep(0.5)

    # 3. Hâlâ çalışıyor → CTRL_C_EVENT / SIGINT ile KeyboardInterrupt gönder
    #    Bu, script içindeki `finally: driver.quit()` bloğunu tetikler
    if proc.poll() is None:
        try:
            if sys.platform == "win32":
                proc.send_signal(_sig.CTRL_C_EVENT)
            else:
                proc.send_signal(_sig.SIGINT)
        except Exception:
            pass

    # 4. finally bloğunun çalışması için 3 saniye daha bekle
    for _ in range(6):
        if proc.poll() is not None:
            return {"ok": True, "run_id": run_id}
        await asyncio.sleep(0.5)

    # 5. Son çare: zorla öldür
    if proc.poll() is None:
        proc.terminate()

    return {"ok": True, "run_id": run_id}


def _sse(event: str, data: str) -> str:
    result = f"event: {event}\n"
    for line in data.split("\n"):
        result += f"data: {line}\n"
    return result + "\n"


# ─── Senaryo Kaydetme (Git Workspace) ─────────────────────────────────────────

class SaveScenarioRequest(BaseModel):
    name:       str
    steps:      list[dict]
    script:     str
    folder:     str | None  = None   # dolu → mevcut üzerine yaz
    platform:   str | None  = None   # "web" | "mobile" | "desktop"
    params:     dict | None = None   # platform-spesifik ayarlar


def _sanitize_folder_name(name: str) -> str:
    """Senaryo adını güvenli klasör adına çevirir."""
    clean = re.sub(r'[^\w\s-]', '', name, flags=re.UNICODE)
    clean = re.sub(r'[\s]+', '_', clean.strip())
    return clean[:64] or "senaryo"


def _get_user_workspace(user_id: int, db: Session):
    """Kullanıcının en son clone'lanmış workspace'ini döndürür."""
    ws = (
        db.query(UserWorkspace)
        .filter(UserWorkspace.user_id == user_id, UserWorkspace.is_cloned == True)
        .order_by(UserWorkspace.id.desc())
        .first()
    )
    return ws


@router.post("/scenarios")
async def save_scenario(
    req: SaveScenarioRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadı. Önce Workspace sayfasından bir repo clone edin.")

    folder_name = req.folder if req.folder else _sanitize_folder_name(req.name)
    scenario_dir = Path(ws.local_path) / "ai_scenarios" / folder_name
    try:
        scenario_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(500, f"Klasör oluşturulamadı: {e}")

    # steps.json — b64 alanını koru (büyük veri)
    try:
        (scenario_dir / "steps.json").write_text(
            _json.dumps({
                "name":     req.name,
                "steps":    req.steps,
                "platform": req.platform,
                "params":   req.params or {},
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (scenario_dir / "script.py").write_text(req.script, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Dosya yazılamadı: {e}")

    # Git commit + push
    author_email = getattr(current_user, "email", None) or f"{current_user.username}@localhost"
    git_author = f"{current_user.username} <{author_email}>"
    committed = False
    try:
        committed = git_service.commit_changes(
            Path(ws.local_path),
            f"ai-gen: senaryo kaydet '{req.name}'",
            author=git_author,
        )
    except Exception as e:
        # Git hatası olsa bile local kayıt yapıldı — uyarı ver ama başarısız sayma
        print(f"[WARN] Git commit başarısız ({folder_name}): {e}")

    push_ok = False
    if committed:
        repo = ws.repository
        try:
            git_service.push_branch(
                Path(ws.local_path),
                ws.branch_name,
                username=repo.git_username if repo else None,
                token=repo.git_token if repo else None,
            )
            push_ok = True
        except Exception:
            pass  # push opsiyonel — local kayıt yeterli

    return {"ok": True, "folder": folder_name, "committed": committed, "pushed": push_ok}


@router.get("/scenarios")
async def list_scenarios(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        return {"scenarios": []}

    base = Path(ws.local_path) / "ai_scenarios"
    if not base.exists():
        return {"scenarios": []}

    result = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        meta_file = folder / "steps.json"
        name      = folder.name
        platform  = ""
        if meta_file.exists():
            try:
                meta     = _json.loads(meta_file.read_text(encoding="utf-8"))
                name     = meta.get("name",     folder.name)
                platform = meta.get("platform", "")
            except Exception:
                pass
        result.append({"folder": folder.name, "name": name, "platform": platform})

    return {"scenarios": result}


@router.get("/scenarios/{folder_name}")
async def load_scenario(
    folder_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadı.")

    scenario_dir = Path(ws.local_path) / "ai_scenarios" / folder_name
    if not scenario_dir.exists():
        raise HTTPException(404, "Senaryo bulunamadı.")

    steps_file  = scenario_dir / "steps.json"
    script_file = scenario_dir / "script.py"

    steps_data = _json.loads(steps_file.read_text(encoding="utf-8")) if steps_file.exists() else {}
    script     = script_file.read_text(encoding="utf-8") if script_file.exists() else ""

    return {
        "name":     steps_data.get("name", folder_name),
        "steps":    steps_data.get("steps", []),
        "script":   script,
        "platform": steps_data.get("platform"),
        "params":   steps_data.get("params", {}),
    }


@router.delete("/scenarios/{folder_name}")
async def delete_scenario(
    folder_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadı.")

    scenario_dir = Path(ws.local_path) / "ai_scenarios" / folder_name
    if not scenario_dir.exists():
        raise HTTPException(404, "Senaryo bulunamadı.")

    import shutil
    shutil.rmtree(scenario_dir)

    _del_author_email = getattr(current_user, "email", None) or f"{current_user.username}@localhost"
    committed = git_service.commit_changes(
        Path(ws.local_path),
        f"ai-gen: senaryo sil '{folder_name}'",
        author=f"{current_user.username} <{_del_author_email}>",
    )
    push_ok = False
    if committed:
        repo = ws.repository
        try:
            git_service.push_branch(
                Path(ws.local_path),
                ws.branch_name,
                username=repo.git_username if repo else None,
                token=repo.git_token if repo else None,
            )
            push_ok = True
        except Exception:
            pass

    return {"ok": True, "committed": committed, "pushed": push_ok}


# ── Git Pull / Push ────────────────────────────────────────────────────────────

@router.post("/git-pull")
async def git_pull(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remote'tan en son degisiklikleri cek (fetch + merge origin/main)."""
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadi. Once workspace klonlayin.")

    local_path = Path(ws.local_path)
    if not local_path.exists():
        raise HTTPException(400, "Workspace klasoru bulunamadi.")

    # Once remote credential guncelle
    repo = ws.repository
    if repo and repo.git_username and repo.git_token:
        try:
            git_service.push_branch.__wrapped__ if False else None  # dummy
            from services import git_service as _gs
            _gs._run_git_command(
                ["git", "remote", "set-url", "origin",
                 repo.repo_url.replace("https://", f"https://{repo.git_username}:{repo.git_token}@")],
                cwd=local_path
            )
        except Exception:
            pass

    result = git_service.pull_from_main(local_path)

    from datetime import datetime, timezone
    ws.last_pulled = datetime.now(timezone.utc)
    db.commit()

    return {
        "ok":            result["success"],
        "message":       result["message"],
        "has_conflicts": result.get("has_conflicts", False),
    }


@router.post("/git-push")
async def git_push(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ai_scenarios klasorunu commit edip remote branch'e push et."""
    ws = _get_user_workspace(current_user.id, db)
    if not ws:
        raise HTTPException(400, "Git workspace bulunamadi. Once workspace klonlayin.")

    local_path = Path(ws.local_path)
    if not local_path.exists():
        raise HTTPException(400, "Workspace klasoru bulunamadi.")

    repo = ws.repository

    commit_msg = f"ai-gen: senaryo guncelleme {_datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    try:
        committed = git_service.commit_changes(
            local_path,
            commit_msg,
            author=f"{current_user.full_name or current_user.username} <{current_user.email}>",
        )
    except Exception as e:
        raise HTTPException(500, f"Commit hatasi: {e}")

    push_ok = False
    push_msg = "Commit basarili, push atlanamadi"
    if committed:
        try:
            git_service.push_branch(
                local_path,
                ws.branch_name,
                username=repo.git_username if repo else None,
                token=repo.git_token if repo else None,
            )
            push_ok = True
            push_msg = f"'{ws.branch_name}' branch'ine push edildi"
            from datetime import datetime, timezone
            ws.last_pushed = datetime.now(timezone.utc)
            ws.has_changes = False
            db.commit()
        except Exception as e:
            push_msg = f"Push hatasi: {e}"
    else:
        push_msg = "Commit edilecek degisiklik yok"

    return {
        "ok":       push_ok or not committed,
        "committed": committed,
        "pushed":   push_ok,
        "message":  push_msg,
    }
