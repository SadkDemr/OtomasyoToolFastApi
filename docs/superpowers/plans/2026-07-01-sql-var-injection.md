# SQL Adımına Değişken Enjeksiyonu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) AI Test Generator'daki SQL adımlarının `sql_query` metninde `{{degisken}}` yazıldığında, bunun önceki bir adımda `_VARS`'a kaydedilmiş gerçek değerle çalışma anında (runtime) değiştirilmesini sağlamak. (B) Web ve Mobil'de ekranda görüntülenen bir değeri (`"hedef" oku {{ad}}`) okuyup `_VARS`'a kaydedebilmek, böylece (A) mekanizmasıyla SQL sorgusunda kullanılabilsin.

**Architecture:** (A) Üretilen script'in her platform şablonuna (mobile/web/desktop), `_VARS = {}` tanımının hemen yanına, `{{key}}` desenlerini `_VARS` sözlüğündeki değerlerle değiştiren küçük bir `_sub_vars(_s)` runtime yardımcı fonksiyonu eklenir. `_sql_step_code()` içindeki her üç veritabanı sürücüsü dalı (sqlite3 / pyodbc / sqlalchemy), sorgu metnini `.execute()`'a vermeden önce bu fonksiyondan geçirir. (B) `_rule_web`/`_rule_mobile` doğal dil kural motoruna, mevcut `{{varname}} yaz` deseninin aynası olan `"hedef" oku {{varname}}` deseni eklenir; bu adım, `VISION_HELPER`/`VISION_HELPER_WEB` string sabitleri içine eklenen yeni `_safe_read`/`_safe_read_web` runtime helper'larını çağırıp sonucu `_VARS`'a yazar. Desktop okuma bu plan kapsamında YOK (ayrı bir alt projeye bağımlı, spec'te açıklandı).

**Tech Stack:** Python (backend kod üretimi — `ai_test_generator_router.py`), düz HTML/JS (frontend — `ai-generator.html`). Test framework yok (proje genelinde pytest kullanılmıyor); doğrulamalar `backend/venv/Scripts/python.exe` ile çalıştırılan bağımsız kontrol scriptleriyle yapılır.

## Global Constraints

- Spec dosyası: `docs/superpowers/specs/2026-07-01-sql-var-injection-design.md` (Bölüm A + Bölüm B) — bu plan o tasarımın birebir uygulanmasıdır, kapsam genişletilmez (API adımına ve Desktop okumaya dokunulmaz).
- `_sub_vars` düz string-replace kullanır, parametrik bind kullanılmaz (spec'te onaylandı).
- `_safe_read`/`_safe_read_web` Vision AI fallback İÇERMEZ (spec'te bilinçli kapsam dışı bırakıldı — vision API koordinat döndürüyor, metin değil).
- Mevcut kod stiliyle tutarlı: f-string ile üretilen Python kaynak satırları, çift/tek tırnak kullanımı dosyanın geri kalanıyla aynı olmalı.
- Proje kökünde boşluk içeren yol var (`C:\Users\Sadik Demir\...`) — tüm komutlarda çift tırnak kullanılmalı.

---

### Task 1: Backend (Bölüm A) — `_sub_vars` helper'ı ekle ve SQL adımını sarmalayarak çalıştır

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `_build_mobile_template()` — `_VARS = {}` satırı (~line 1962)
  - `_build_web_template()` — `_VARS = {}` satırı (~line 2090)
  - `_build_desktop_template()` — `_VARS = {}` satırı (~line 2154)
  - `_sql_step_code()` — üç `.execute(...)` çağrısı (~line 2465 sqlite, ~line 2502 pyodbc, ~line 2538 sqlalchemy)
- Test: geçici kontrol scripti (repo dışı) — scratchpad'e yazılıp çalıştırılacak, kalıcı dosya değil.

**Interfaces:**
- Produces: her üretilen script'te modül seviyesinde `_sub_vars(_s: str) -> str` fonksiyonu (parametre olarak SQL sorgu metnini alır, `_VARS` sözlüğündeki her `key` için metindeki `{{key}}` deseninin yerine `str(value)` koyar, sonucu döner).
- Consumes: mevcut `_VARS: dict` (her üç şablonda zaten tanımlı), mevcut `StepItem.sql_query` alanı.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad dizinine şu içerikle `check_sub_vars.py` dosyası oluştur (scratchpad path: `C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_sub_vars.py`):

```python
import sys, inspect

sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")

from routers.ai_test_generator_router import (
    _build_mobile_template,
    _build_web_template,
    _build_desktop_template,
    _sql_step_code,
    StepItem,
)

for name, fn in [
    ("mobile", _build_mobile_template),
    ("web", _build_web_template),
    ("desktop", _build_desktop_template),
]:
    src = inspect.getsource(fn)
    assert "def _sub_vars(" in src, f"FAIL: {name} template missing _sub_vars helper"

item = StepItem(
    type="sql",
    db_connection="sqlite:///x.db",
    sql_query="SELECT * FROM t WHERE id = {{foo}}",
    action="query_print",
)
code = _sql_step_code(item, 0)
assert "_sub_vars(" in code, "FAIL: _sql_step_code does not wrap query with _sub_vars"

print("OK")
```

- [ ] **Step 2: Scripti çalıştır, FAIL beklenir**

Run:
```bash
"backend/venv/Scripts/python.exe" "C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_sub_vars.py"
```
Expected: `AssertionError: FAIL: mobile template missing _sub_vars helper` (ilk assert'te patlar, henüz helper eklenmedi)

- [ ] **Step 3: Üç şablona `_sub_vars` helper'ını ekle**

`_build_mobile_template()` içinde (satır ~1962):

Öncesi:
```python
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        STOP_HELPER,
        f'_DEVICE_ID = "{device}"  # ADB komutları için cihaz ID',
```

Sonrası:
```python
        "_VARS = {}  # adımlar arası değişken havuzu",
        "def _sub_vars(_s):",
        "    for _k, _v in _VARS.items():",
        "        _s = _s.replace('{{' + _k + '}}', str(_v))",
        "    return _s",
        "",
        STOP_HELPER,
        f'_DEVICE_ID = "{device}"  # ADB komutları için cihaz ID',
```

`_build_web_template()` içinde (satır ~2090):

Öncesi:
```python
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        driver_setup,
        "",
        "# ── Tarayıcı başlatılamadıysa net hata ver ───────────────────",
```

Sonrası:
```python
        "_VARS = {}  # adımlar arası değişken havuzu",
        "def _sub_vars(_s):",
        "    for _k, _v in _VARS.items():",
        "        _s = _s.replace('{{' + _k + '}}', str(_v))",
        "    return _s",
        "",
        driver_setup,
        "",
        "# ── Tarayıcı başlatılamadıysa net hata ver ───────────────────",
```

`_build_desktop_template()` içinde (satır ~2154):

Öncesi:
```python
        f'_WINDOW_TITLE   = "{window_title_esc}"',
        "_VARS = {}  # adımlar arası değişken havuzu",
        "",
        STOP_HELPER,
        IMAGE_HELPER,
        DESKTOP_HELPER,
```

Sonrası:
```python
        f'_WINDOW_TITLE   = "{window_title_esc}"',
        "_VARS = {}  # adımlar arası değişken havuzu",
        "def _sub_vars(_s):",
        "    for _k, _v in _VARS.items():",
        "        _s = _s.replace('{{' + _k + '}}', str(_v))",
        "    return _s",
        "",
        STOP_HELPER,
        IMAGE_HELPER,
        DESKTOP_HELPER,
```

- [ ] **Step 4: `_sql_step_code()` içindeki üç `.execute()` çağrısını sarmala**

sqlite dalı — öncesi:
```python
            f"    _cur_{idx}.execute({query_r})\n"
```
sonrası:
```python
            f"    _cur_{idx}.execute(_sub_vars({query_r}))\n"
```

pyodbc dalı — öncesi (aynı satır ikinci kez, dosyada farklı `elif is_odbc:` bloğunun içinde):
```python
            f"    _cur_{idx}.execute({query_r})\n"
```
sonrası:
```python
            f"    _cur_{idx}.execute(_sub_vars({query_r}))\n"
```

sqlalchemy dalı — öncesi:
```python
            f"        _res_{idx} = _conn_{idx}.execute(_st_{idx}({query_r}))\n"
```
sonrası:
```python
            f"        _res_{idx} = _conn_{idx}.execute(_st_{idx}(_sub_vars({query_r})))\n"
```

**Not:** sqlite ve pyodbc dallarında birebir aynı `f"    _cur_{idx}.execute({query_r})\n"` satırı iki kez geçiyor — Edit aracı kullanırken her ikisini de değiştirmek için etraflarındaki farklı bağlam satırlarını (örn. bir önceki satırdaki `_cur_{idx}.execute(...)`'dan önceki bağlantı kurulum satırı `_sq_{idx}.connect(...)` vs `_pyodbc_{idx}.connect(...)`) old_string'e dahil et, ya da tek tek sırayla değiştir.

- [ ] **Step 5: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run:
```bash
"backend/venv/Scripts/python.exe" "C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_sub_vars.py"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: SQL adımına {{degisken}} runtime enjeksiyonu ekle"
```

---

### Task 2: Backend (Bölüm B) — Web + Mobil "değer oku" helper'ları ve kural motoru deseni

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `VISION_HELPER` (mobil helper string sabiti, ~line 668-1128) — `_safe_read` eklenmesi
  - `VISION_HELPER_WEB` (web helper string sabiti, ~line 1131-1269) — `_safe_read_web` eklenmesi
  - `_rule_mobile()` (~line 222) — `{{varname}} "//xpath" yaz` bloğunun (~line 234-238) hemen altına yeni desen
  - `_rule_web()` (~line 382) — `{{varname}} "alanHint" yaz` bloğunun (~line 389-395) hemen altına yeni desen
- Test: geçici kontrol scripti (repo dışı) — scratchpad'e yazılıp çalıştırılacak, kalıcı dosya değil.

**Interfaces:**
- Produces: her üretilen mobil script'te `_safe_read(driver, text, key_text=None) -> str`; her üretilen web script'te `_safe_read_web(driver, hint) -> str`. `_rule_web`/`_rule_mobile`, `"hedef" oku {{ad}}` deseniyle eşleşen adımlar için `_VARS[ad] = _safe_read(...)` / `_VARS[ad] = _safe_read_web(...)` satırı üretir.
- Consumes: mevcut `_VARS: dict`, mevcut `AppiumBy`/`By` import'ları (script şablonlarında zaten mevcut).

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad dizinine şu içerikle `check_read_value.py` dosyası oluştur (aynı scratchpad klasörü: `C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_read_value.py`):

```python
import sys

sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")

from routers.ai_test_generator_router import (
    VISION_HELPER,
    VISION_HELPER_WEB,
    _rule_web,
    _rule_mobile,
)

assert "def _safe_read(" in VISION_HELPER, "FAIL: VISION_HELPER missing _safe_read"
assert "def _safe_read_web(" in VISION_HELPER_WEB, "FAIL: VISION_HELPER_WEB missing _safe_read_web"

web_lines = _rule_web('"Kur Degeri" oku {{kur}}')
assert web_lines is not None, "FAIL: _rule_web did not match read pattern"
assert any("_safe_read_web(driver, 'Kur Degeri')" in ln for ln in web_lines), f"FAIL: unexpected web_lines {web_lines}"
assert any("_VARS['kur'] = " in ln for ln in web_lines), f"FAIL: no _VARS assignment in {web_lines}"

mobile_lines = _rule_mobile('"Kur Degeri" oku {{kur}}')
assert mobile_lines is not None, "FAIL: _rule_mobile did not match read pattern"
assert any("_safe_read(driver, 'Kur Degeri')" in ln for ln in mobile_lines), f"FAIL: unexpected mobile_lines {mobile_lines}"
assert any("_VARS['kur'] = " in ln for ln in mobile_lines), f"FAIL: no _VARS assignment in {mobile_lines}"

print("OK")
```

- [ ] **Step 2: Scripti çalıştır, FAIL beklenir**

Run:
```bash
"backend/venv/Scripts/python.exe" "C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_read_value.py"
```
Expected: `AssertionError: FAIL: VISION_HELPER missing _safe_read`

- [ ] **Step 3: `VISION_HELPER`'a `_safe_read` ekle (mobil)**

`_safe_assert`'in son satırı (`print(f"[WARN] '{text}' ekranda bulunamadı — adım geçiliyor")`) ile `VISION_HELPER`'ı kapatan `'''` arasına ekle:

Öncesi:
```python
    print(f"[WARN] '{text}' ekranda bulunamadı — adım geçiliyor")
'''


VISION_HELPER_WEB = '''
```

Sonrası:
```python
    print(f"[WARN] '{text}' ekranda bulunamadı — adım geçiliyor")


def _safe_read(driver, text, key_text=None):
    """Hedef metni/içeriği içeren elementin text/content-desc değerini okur (scroll ile arar)."""
    _all_texts = [t for t in [text, key_text] if t]

    def _try_find():
        for _t in _all_texts:
            for _xp in [
                f'//*[contains(@text,"{_t}")]',
                f'//*[contains(@content-desc,"{_t}")]',
            ]:
                try:
                    el = driver.find_element(AppiumBy.XPATH, _xp)
                    val = (el.get_attribute("text") or el.get_attribute("content-desc") or "").strip()
                    if val:
                        return val
                except Exception:
                    continue
        return None

    val = _try_find()
    if val is not None:
        print(f"[OK] Okundu: {text}")
        return val

    print(f"[SCROLL↓] '{text}' aranıyor...")
    driver.swipe(540, 1400, 540, 500, 800); time.sleep(0.7)
    val = _try_find()
    if val is not None:
        return val

    print(f"[SCROLL↑] '{text}' aranıyor...")
    driver.swipe(540, 500, 540, 1400, 800); time.sleep(0.7)
    val = _try_find()
    if val is not None:
        return val

    print(f"[WARN] '{text}' ekranda bulunamadı — değer okunamadı")
    return ""
'''


VISION_HELPER_WEB = '''
```

- [ ] **Step 4: `VISION_HELPER_WEB`'e `_safe_read_web` ekle (web)**

`_safe_assert_web`'in son satırı (`assert text in driver.page_source, f"Beklenen metin yok: {text}"`) ile `VISION_HELPER_WEB`'i kapatan `'''` arasına ekle:

Öncesi:
```python
    assert text in driver.page_source, f"Beklenen metin yok: {text}"
'''


IMAGE_HELPER = '''
```

Sonrası:
```python
    assert text in driver.page_source, f"Beklenen metin yok: {text}"


def _safe_read_web(driver, hint):
    """Hedef metni içeren elementin görünen değerini okur (contains eşleşmesi)."""
    from selenium.webdriver.common.by import By
    for xp in [
        f'//*[contains(normalize-space(.),"{hint}")]',
        f'//*[contains(@value,"{hint}")]',
        f'//*[contains(@placeholder,"{hint}")]',
    ]:
        try:
            el = driver.find_element(By.XPATH, xp)
            val = (el.text or el.get_attribute("value") or "").strip()
            if val:
                return val
        except Exception:
            continue
    print(f"[WARN] Okunamadı: {hint}")
    return ""
'''


IMAGE_HELPER = '''
```

- [ ] **Step 5: `_rule_mobile()`'a okuma deseni ekle**

`{{varname}} "//xpath" yaz` bloğunun hemen altına ekle:

Öncesi:
```python
    # ── {{varname}} "//xpath" yaz ─────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, xpath = _vm.group(1), (_vm.group(2) or '//android.widget.EditText[1]')
        return [f'# {{{{ {vn} }}}} yaz', f"_safe_input(driver, {repr(xpath)}, str(_VARS.get({repr(vn)}, '')))"]

    # ── Pasif Türkçe: "X [suffix] tıklanır" (tırnaksız) ─────────────────────
```

Sonrası:
```python
    # ── {{varname}} "//xpath" yaz ─────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, xpath = _vm.group(1), (_vm.group(2) or '//android.widget.EditText[1]')
        return [f'# {{{{ {vn} }}}} yaz', f"_safe_input(driver, {repr(xpath)}, str(_VARS.get({repr(vn)}, '')))"]

    # ── "hedef" oku {{varname}} — elementten değer oku ────────────────────────
    _rm = re.match(r'^"([^"]+)"\s*oku\s*\{\{(\w+)\}\}\.?\s*$', s, re.IGNORECASE)
    if _rm:
        hint, vn = _rm.group(1), _rm.group(2)
        return [
            f'# "{hint}" oku {{{{ {vn} }}}}',
            f"_VARS[{repr(vn)}] = _safe_read(driver, {repr(hint)})",
            f"print(f'[OKU→_VARS] {vn} = {{_VARS[{repr(vn)}]}}')",
        ]

    # ── Pasif Türkçe: "X [suffix] tıklanır" (tırnaksız) ─────────────────────
```

- [ ] **Step 6: `_rule_web()`'e okuma deseni ekle**

`{{varname}} "alanHint" yaz` bloğunun hemen altına ekle:

Öncesi:
```python
    # ── {{varname}} "alanHint" yaz ────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, hint = _vm.group(1), (_vm.group(2) or "")
        if hint:
            return [f'# {{{{ {vn} }}}} yaz', f"_safe_input_web(driver, {repr(hint)}, str(_VARS.get({repr(vn)}, '')))"]
        return [f'# {{{{ {vn} }}}} yaz', f"import pyperclip as _pc; _pc.copy(str(_VARS.get({repr(vn)}, ''))); import pyautogui as _pa; _pa.hotkey('ctrl','v')"]

    _WEB_KEY_MAP = {
```

Sonrası:
```python
    # ── {{varname}} "alanHint" yaz ────────────────────────────────────────────
    _vm = re.match(r'^\{\{(\w+)\}\}(?:\s+"([^"]+)")?\s*(?:yaz|gir|doldur|type\b)?\.?\s*$', s, re.IGNORECASE)
    if _vm:
        vn, hint = _vm.group(1), (_vm.group(2) or "")
        if hint:
            return [f'# {{{{ {vn} }}}} yaz', f"_safe_input_web(driver, {repr(hint)}, str(_VARS.get({repr(vn)}, '')))"]
        return [f'# {{{{ {vn} }}}} yaz', f"import pyperclip as _pc; _pc.copy(str(_VARS.get({repr(vn)}, ''))); import pyautogui as _pa; _pa.hotkey('ctrl','v')"]

    # ── "hedef" oku {{varname}} — elementten değer oku ────────────────────────
    _rm = re.match(r'^"([^"]+)"\s*oku\s*\{\{(\w+)\}\}\.?\s*$', s, re.IGNORECASE)
    if _rm:
        hint, vn = _rm.group(1), _rm.group(2)
        return [
            f'# "{hint}" oku {{{{ {vn} }}}}',
            f"_VARS[{repr(vn)}] = _safe_read_web(driver, {repr(hint)})",
            f"print(f'[OKU→_VARS] {vn} = {{_VARS[{repr(vn)}]}}')",
        ]

    _WEB_KEY_MAP = {
```

- [ ] **Step 7: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run:
```bash
"backend/venv/Scripts/python.exe" "C:\Users\SADIKD~1\AppData\Local\Temp\claude\C--Users-Sadik-Demir-Documents-GitHub-OtomasyoToolFastApi\382ddc2f-89ca-4006-b9fb-693db497eaab\scratchpad\check_read_value.py"
```
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: Web ve Mobil'de ekrandan deger oku -> degiskene kaydet"
```

---

### Task 3: Frontend — adım ipuçlarını güncelle (SQL tooltip + metin adımı placeholder)

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html`
  - `sql_query` textarea (~line 1796)
  - Metin adımı content input placeholder (~line 1755)

**Interfaces:**
- Consumes: mevcut `s.sql_query`, `s.content`, `escText()`/`escHtml()` (değişiklik yok)
- Produces: yok (sadece UI ipucu metni — başka hiçbir task buna bağımlı değil)

- [ ] **Step 1: Mevcut satırları doğrula (FAIL durumu = ipuçları yok)**

`backend/WebArayuz/ai-generator.html` dosyasında şu iki satırı bul, `title`/placeholder içeriklerinde "oku" kelimesi geçmediğini gözle doğrula (otomatik test yok, proje frontend'de JS test altyapısı kullanmıyor):
```html
                <textarea class="step-ext-textarea" placeholder="SQL sorgusu..."
                    oninput="updateStepField(${i}, 'sql_query', this.value)">${escText(s.sql_query||'')}</textarea>
```
```html
                placeholder='Adım açıklaması...  (değişken için: {{değişkenAdı}} yaz)' oninput="updateStepContent(${i}, this.value)">`;
```

- [ ] **Step 2: SQL tooltip ekle**

Öncesi:
```html
                <textarea class="step-ext-textarea" placeholder="SQL sorgusu..."
                    oninput="updateStepField(${i}, 'sql_query', this.value)">${escText(s.sql_query||'')}</textarea>
```

Sonrası:
```html
                <textarea class="step-ext-textarea" placeholder="SQL sorgusu..."
                    title="İçinde {{değişken}} kullanabilirsiniz — önceki adımlarda kaydedilen değerlerle değiştirilir."
                    oninput="updateStepField(${i}, 'sql_query', this.value)">${escText(s.sql_query||'')}</textarea>
```

- [ ] **Step 3: Metin adımı placeholder'ını güncelle**

Öncesi:
```html
                placeholder='Adım açıklaması...  (değişken için: {{değişkenAdı}} yaz)' oninput="updateStepContent(${i}, this.value)">`;
```

Sonrası:
```html
                placeholder='Adım açıklaması...  (değişken: {{ad}} yaz / "hedef" oku {{ad}})' oninput="updateStepContent(${i}, this.value)">`;
```

- [ ] **Step 4: Manuel doğrulama**

Sunucuyu başlat (`cd backend && python main.py`), `/ui/ai-generator.html` sayfasını aç:
1. Bir SQL adımı ekle, sorgu textarea'sının üzerine mouse ile gel — tooltip olarak "İçinde {{değişken}} kullanabilirsiniz..." metninin göründüğünü doğrula.
2. Bir metin adımı ekle, içerik alanının placeholder'ında `"hedef" oku {{ad}}` örneğinin göründüğünü doğrula.

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "docs(ui): SQL ve deger okuma adimlari icin kullanim ipucu ekle"
```

---

### Task 4: Uçtan uca doğrulama (spec Test Planı — Bölüm A + Bölüm B)

**Files:** Yok (sadece çalıştırma/doğrulama — kod değişikliği içermez)

**Interfaces:** Yok — bu task Task 1, 2 ve 3'ün birlikte doğru çalıştığını gerçek senaryolarla teyit eder.

**Bölüm A doğrulaması:**

- [ ] **Step 1: Test SQLite veritabanı oluştur**

```bash
"backend/venv/Scripts/python.exe" -c "
import sqlite3
conn = sqlite3.connect('backend/_manual_test.db')
conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)')
conn.execute(\"INSERT INTO users (id, name) VALUES (1, 'Ayse')\")
conn.execute('CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT)')
conn.execute(\"INSERT INTO orders (id, user_id, item) VALUES (1, 1, 'Kitap')\")
conn.execute('CREATE TABLE rates (code TEXT PRIMARY KEY, value TEXT)')
conn.execute(\"INSERT INTO rates (code, value) VALUES ('USD', '32.45')\")
conn.commit()
conn.close()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 2: Desktop platformu için iki adımlı bir `GenerateRequest` ile `/api/ai-generator/generate` çağır ve üretilen scripti çalıştır**

AI Generator arayüzünden (Desktop platformu, herhangi bir `app_path`/`window_title` olmadan) şu iki SQL adımını ekle:
1. `db_connection = sqlite:///_manual_test.db`, `sql_query = SELECT id FROM users LIMIT 1`, `action = query_print`, `var_name = user_id`
2. `db_connection = sqlite:///_manual_test.db`, `sql_query = SELECT item FROM orders WHERE user_id = {{user_id}}`, `action = query_print`

"Script Üret" ile Python kodunu üret, ardından "Çalıştır" ile koş.

- [ ] **Step 3: Log çıktısını doğrula**

Beklenen log satırları arasında:
```
[SQL→_VARS] user_id = 1
[SQL] 1 kayit:
   ('Kitap',)
```
görülmeli — ikinci sorgunun `{{user_id}}` yerine gerçek `1` değeriyle çalıştığının kanıtı.

**Bölüm B doğrulaması (Web):**

- [ ] **Step 4: Web senaryosu — ekrandan oku + SQL'de kullan**

Sayfasında "USD" metnini içeren bir test sayfası (ör. `data:text/html,<div>Kur Kodu: USD</div>`) açan bir Web senaryosu oluştur, şu adımları ekle:
1. `"data:text/html,<div>Kur Kodu: USD</div>" git` (Navigasyon adımı)
2. `"Kur Kodu: USD" oku {{kur}}` (metin adımı)
3. SQL adımı: `db_connection = sqlite:///_manual_test.db`, `sql_query = SELECT value FROM rates WHERE code = 'USD'`, `action = query_print` (not: burada gerçek doğrulama `{{kur}}` değişkeninin `_VARS`'a doğru yazıldığını görmek — okunan değer tam "Kur Kodu: USD" gelecektir çünkü hedef metin tüm elementi kapsıyor, bu beklenen davranış, spec'te açıklandı)

"Script Üret" → "Çalıştır", log çıktısında `[OKU→_VARS] kur = Kur Kodu: USD` satırının göründüğünü doğrula.

- [ ] **Step 5: Temizlik**

```bash
rm "backend/_manual_test.db"
```

---

## Self-Review Notları

- **Spec kapsaması:** Spec Bölüm A "Çözüm" → Task 1. Spec Bölüm A "Frontend" → Task 3 (SQL tooltip kısmı). Spec Bölüm B "Çözüm" → Task 2. Spec Bölüm B "Frontend" → Task 3 (placeholder kısmı). Spec "Test Planı" (A+B) → Task 4. Her iki bölümün "Kapsam Dışı" maddeleri (API adımı, Desktop okuma, Vision fallback, regex extraction) bilinçli olarak hiçbir task'a dahil edilmedi.
- **Placeholder taraması:** Yok — her adımda tam kod/komut var.
- **Tip/isim tutarlılığı:** `_sub_vars(_s)` fonksiyon adı Task 1'in tüm adımlarında birebir aynı; `_safe_read`/`_safe_read_web` isimleri Task 2'nin helper ekleme adımlarıyla kural motoru adımlarında birebir aynı; `_sql_step_code` ve `_rule_web`/`_rule_mobile` çağrıları tutarlı.
