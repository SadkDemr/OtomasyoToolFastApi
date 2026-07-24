# AI Test Generator: Adım Bazlı If/Else Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI Test Generator'ın adım listesine, metin/görsel/sql/api adımlarını "eğer X varsa/eşitse A yap, yoksa B yap" şeklinde dallandırabilen, 1 seviye nested `condition` adım tipi eklemek — Mobile/Web/Desktop'ın üçünde birden.

**Architecture:** `StepItem` Pydantic modeli self-referential hale gelir (`then_steps`/`else_steps: list["StepItem"]`). Backend'de tek ortak `_generate_steps` fonksiyonu, paylaşılan bir `idx` sayacıyla recursive çalışan `_steps_to_code()` yardımcısına dönüştürülür — üretilen Python kodu düzgün girintiyle if/else üretir. 3 platform şablonu (`_build_mobile/web/desktop_template`) **değişmez** çünkü zaten üretilen `steps_code` string'ini olduğu gibi 4-boşluk indent'leyip tek bir üst `try:` bloğuna sarıyorlar. Frontend'de `steps` dizisi düz kalır; `condition` tipi bir adım kendi içinde iki mini-liste (`then_steps`/`else_steps`) tutar, mevcut ekle/sil/güncelle/sürükle fonksiyonları geriye-uyumlu opsiyonel `branch`/`bIdx` parametreleriyle genişletilir.

**Tech Stack:** FastAPI + Pydantic v2 (backend), vanilla JS tek-dosya SPA (frontend), üretilen script'ler saf Python (Appium/Selenium/pyautogui helper'ları metin olarak gömülü).

**Referans spec:** `docs/superpowers/specs/2026-07-24-ai-generator-if-else-design.md`

## Global Constraints

- Nesting derinliği **tam olarak 1 seviye** — `then_steps`/`else_steps` içine `type == "condition"` eklenemez (backend reddeder, frontend zaten teklif etmez).
- `compare_op` yalnızca `eq` / `neq` / `contains` (büyük/küçük karşılaştırma kapsam dışı).
- Dallar arası sürükle-bırak (bir adımı "Eğer"den "Değilse"ye taşımak) kapsam dışı — YAGNI.
- Geriye dönük uyumluluk zorunlu: `condition` alanı olmayan eski kaydedilmiş senaryolar (`steps.json`) ve mevcut tek-parametreli `onclick="deleteStep(${i})"` gibi çağrılar **hiç değişmeden** çalışmaya devam etmeli.
- Bu proje otomatik test suite'i (pytest vb.) kullanmıyor — mevcut spec'lerdeki gibi doğrulama adımları `python -c` betikleri ve manuel uçtan-uca kontrol şeklinde yazılır.

---

### Task 1: Backend — `StepItem` modeline condition alanları ekle

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py:138-160` (`StepItem` sınıfı)

**Interfaces:**
- Produces: `StepItem.type` yeni değer alabilir: `"condition"`. Yeni alanlar: `condition_type: str`, `compare_var: str`, `compare_op: str`, `compare_value: str`, `then_steps: list["StepItem"]`, `else_steps: list["StepItem"]`.

- [ ] **Step 1: Mevcut `StepItem` sınıfını güncelle**

`ai_test_generator_router.py:138-160` mevcut hali:
```python
class StepItem(BaseModel):
    type:          str = "text"   # "text" | "image" | "sql" | "api" | "comment"
    disabled:      bool = False   # True ise adım çalıştırılmaz, "# [DEVRE DIŞI]" yorumuna döner
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
    # Koordinat tıklama (nokta işaretle modu)
    click_x:       int = -1       # >= 0 ise kırpılan/tam görsele göre nokta tıklaması kullanılır
    click_y:       int = -1       # (coklu-olcek eslestirme + normalize nokta, bkz. _find_b64_and_click_point)
    # Fare ile sürükleme (action="drag"): click_x/click_y = başlangıç, drag_x/drag_y = bitiş noktası
    drag_x:        int = -1
    drag_y:        int = -1
```

Yerine şunu yaz (sadece sona ekleme + sınıfın hemen altına `model_rebuild()` çağrısı):

```python
class StepItem(BaseModel):
    type:          str = "text"   # "text" | "image" | "sql" | "api" | "comment" | "condition"
    disabled:      bool = False   # True ise adım çalıştırılmaz, "# [DEVRE DIŞI]" yorumuna döner
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
    # Koordinat tıklama (nokta işaretle modu)
    click_x:       int = -1       # >= 0 ise kırpılan/tam görsele göre nokta tıklaması kullanılır
    click_y:       int = -1       # (coklu-olcek eslestirme + normalize nokta, bkz. _find_b64_and_click_point)
    # Fare ile sürükleme (action="drag"): click_x/click_y = başlangıç, drag_x/drag_y = bitiş noktası
    drag_x:        int = -1
    drag_y:        int = -1
    # ── Koşullu dallanma (type == "condition") ────────────────────────────
    condition_type: str = ""      # "" | "image_exists" | "element_exists" | "variable_compare"
    compare_var:    str = ""      # variable_compare: {{degisken}} adı (_VARS anahtarı)
    compare_op:     str = ""      # variable_compare: "eq" | "neq" | "contains"
    compare_value:  str = ""      # variable_compare: karşılaştırılacak sabit değer
    then_steps:     list["StepItem"] = []
    else_steps:     list["StepItem"] = []

StepItem.model_rebuild()   # self-referential model — forward ref ("StepItem") çözümü için gerekli
```

- [ ] **Step 2: Import edilebildiğini ve self-reference çalıştığını doğrula**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys; sys.path.insert(0, '.')
from routers.ai_test_generator_router import StepItem
s = StepItem(type='condition', condition_type='variable_compare', compare_var='x', compare_op='eq', compare_value='1',
             then_steps=[StepItem(type='text', content='then')],
             else_steps=[StepItem(type='text', content='else')])
assert s.then_steps[0].content == 'then'
assert s.else_steps[0].content == 'else'
print('OK')
"
```
Expected: `OK` (hata yoksa model_rebuild doğru çalışıyor demektir).

- [ ] **Step 3: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "AI Test Generator: StepItem'a condition/then_steps/else_steps alanlari ekle"
```

---

### Task 2: Backend — `_safe_assert` (mobile) bool dönsün

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py:1260-1278` (`VISION_HELPER` string sabiti içinde, `_safe_assert` fonksiyonunun gövdesi)

**Interfaces:**
- Consumes: yok (mevcut fonksiyonun içi)
- Produces: `_safe_assert(driver, text, key_text=None)` artık `True`/`False` döner (önceden hep `None` dönüyordu — raise etmiyordu, bu davranış AYNEN korunuyor, sadece dönüş değeri ekleniyor).

**Not:** Bu fonksiyon normal bir Python fonksiyonu değil, `VISION_HELPER = '''...'''` (satır 819) string sabitinin İÇİNDEKİ metin — üretilen script'e olduğu gibi gömülüyor. Değişiklik string içeriğini değiştirmek.

- [ ] **Step 1: Mevcut gövdeyi bul ve `return`/dönüşsüz satırları değiştir**

`ai_test_generator_router.py:1260-1278` mevcut hali (fonksiyonun ilk yarısı — `_try_find()` iç fonksiyonu — değişmiyor, sadece bundan sonrası):
```python
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
```

Yerine:
```python
    if _try_find(): return True

    # Aşağı kaydır + tekrar
    print(f"[SCROLL↓] '{text}' aranıyor...")
    driver.swipe(540, 1400, 540, 500, 800); time.sleep(0.7)
    if _try_find(): return True

    # Yukarı kaydır + tekrar
    print(f"[SCROLL↑] '{text}' aranıyor...")
    driver.swipe(540, 500, 540, 1400, 800); time.sleep(0.7)
    if _try_find(): return True

    # Vision fallback
    print(f"[VISION] '{text}' için ekran görüntüsü analiz ediliyor...")
    if _vision_find(driver, key_text or text):
        print(f"[OK] Vision ile doğrulandı: {text}")
        return True

    print(f"[WARN] '{text}' ekranda bulunamadı — adım geçiliyor")
    return False
```

- [ ] **Step 2: `VISION_HELPER` metninin hâlâ geçerli Python olduğunu doğrula**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys; sys.path.insert(0, '.')
from routers.ai_test_generator_router import VISION_HELPER
compile(VISION_HELPER, '<VISION_HELPER>', 'exec')
assert 'return True' in VISION_HELPER
assert 'return False' in VISION_HELPER
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "AI Test Generator: mobile _safe_assert bool dondursun (condition icin gerekli)"
```

---

### Task 3: Backend — `_safe_assert_web` / `_safe_assert_desktop`'a `raise_on_fail` ekle

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py:1441-1459` (`VISION_HELPER_WEB` içinde `_safe_assert_web`)
- Modify: `backend/routers/ai_test_generator_router.py:2079-2110` (`DESKTOP_HELPER` içinde `_safe_assert_desktop`)

**Interfaces:**
- Produces: `_safe_assert_web(driver, text, raise_on_fail=True)`, `_safe_assert_desktop(target, raise_on_fail=True)`. Varsayılan `True` ile **mevcut çağıran kodun davranışı birebir korunuyor** (hâlâ raise ediyor); `raise_on_fail=False` ile bool döner.

- [ ] **Step 1: `_safe_assert_web` — mevcut hali**

`ai_test_generator_router.py:1441-1459`:
```python
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
```

Yerine:
```python
def _safe_assert_web(driver, text, raise_on_fail=True):
    """Metni sayfada doğrula — kaynak + element + scroll"""
    from selenium.webdriver.common.by import By
    import time
    if text in driver.page_source:
        print(f"[OK] Doğrulandı: {text}"); return True
    for xp in [
        f'//*[contains(normalize-space(.),"{text}")]',
        f'//*[contains(@value,"{text}")]',
        f'//*[contains(@placeholder,"{text}")]',
    ]:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed():
                print(f"[OK] Doğrulandı: {text}"); return True
        except Exception:
            continue
    driver.execute_script("window.scrollTo(0,0);"); time.sleep(0.5)
    _found = text in driver.page_source
    if _found:
        print(f"[OK] Doğrulandı: {text}")
        return True
    if raise_on_fail:
        assert _found, f"Beklenen metin yok: {text}"
    return False
```

- [ ] **Step 2: `_safe_assert_desktop` — mevcut hali**

`ai_test_generator_router.py:2079-2110`:
```python
def _safe_assert_desktop(target):
    """Ekranda element / metin doğrula. Bulamazsa AssertionError fırlatır."""
    print(f"[ASSERT] '{target}' kontrol ediliyor...")

    # pywinauto
    if _PW_OK:
        try:
            _win = _get_active_window()
            if _win:
                _el = _win.child_window(title_re=f".*{target}.*", found_index=0)
                if _el.exists(timeout=1):
                    print(f"[OK] pywinauto: '{target}'"); return
        except Exception:
            pass

    # OCR — sadece uygulama penceresiyle sınırlı
    if _TESS_OK:
        try:
            _region = _get_window_region()
            shot = _pag.screenshot(region=_region) if _region else _pag.screenshot()
            _txt = _tess.image_to_string(shot, lang="tur+eng")
            if target.lower() in _txt.lower():
                print(f"[OK] OCR: '{target}'"); return
        except Exception:
            pass

    # Vision
    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        print(f"[OK] Vision: '{target}'"); return

    raise AssertionError(f"[FAIL] '{target}' ekranda bulunamadi")
```

Yerine:
```python
def _safe_assert_desktop(target, raise_on_fail=True):
    """Ekranda element / metin doğrula. raise_on_fail=True (varsayılan) ise bulamazsa
    AssertionError fırlatır, False ise sessizce bool döner."""
    print(f"[ASSERT] '{target}' kontrol ediliyor...")

    # pywinauto
    if _PW_OK:
        try:
            _win = _get_active_window()
            if _win:
                _el = _win.child_window(title_re=f".*{target}.*", found_index=0)
                if _el.exists(timeout=1):
                    print(f"[OK] pywinauto: '{target}'"); return True
        except Exception:
            pass

    # OCR — sadece uygulama penceresiyle sınırlı
    if _TESS_OK:
        try:
            _region = _get_window_region()
            shot = _pag.screenshot(region=_region) if _region else _pag.screenshot()
            _txt = _tess.image_to_string(shot, lang="tur+eng")
            if target.lower() in _txt.lower():
                print(f"[OK] OCR: '{target}'"); return True
        except Exception:
            pass

    # Vision
    _vx, _vy = _vision_find_desktop(target)
    if _vx and _vy:
        print(f"[OK] Vision: '{target}'"); return True

    if raise_on_fail:
        raise AssertionError(f"[FAIL] '{target}' ekranda bulunamadi")
    return False
```

Not: (`_safe_assert_desktop` string içinde tek tırnaklar `\'` şeklinde escape edilmiş biçimde bulunuyor olabilir — dosyayı Edit etmeden önce Read ile açıp güncel/gerçek escape biçimini birebir görüp ona göre `old_string` oluştur, yukarıdaki bloklar mantığı ve eklenecek satırları göstermek içindir.)

- [ ] **Step 3: Her iki `HELPER` string'inin hâlâ derlenebildiğini doğrula**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys; sys.path.insert(0, '.')
from routers.ai_test_generator_router import VISION_HELPER_WEB, DESKTOP_HELPER
compile(VISION_HELPER_WEB, '<VISION_HELPER_WEB>', 'exec')
compile(DESKTOP_HELPER, '<DESKTOP_HELPER>', 'exec')
assert 'raise_on_fail=True' in VISION_HELPER_WEB
assert 'raise_on_fail=True' in DESKTOP_HELPER
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "AI Test Generator: web/desktop assert helper'larina raise_on_fail parametresi ekle"
```

---

### Task 4: Backend — `_condition_expr()` ve recursive `_steps_to_code()` ile `_generate_steps`'i değiştir

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py:3133-3235` (`_generate_steps` fonksiyonu — tamamen recursive yardımcıya devrediliyor)

**Interfaces:**
- Consumes: Task 1'deki `StepItem` (condition alanları), Task 2/3'teki bool-dönen assert helper'lar, mevcut `_image_step_code(item, platform, idx)`, `_sql_step_code(item, idx)`, `_api_step_code(item, idx)`, `rule_fn(step)` (mobile/web/desktop kural motoru).
- Produces: `_generate_steps(req) -> tuple[str, list[dict]]` imzası **değişmiyor** (`generate_script` endpoint'i hiç dokunulmadan çalışmaya devam eder).

- [ ] **Step 1: `_indent_code` yardımcı fonksiyonunu ekle**

`_generate_steps` fonksiyonunun HEMEN ÜSTÜNE (satır 3133'ten önce) ekle:

```python
def _indent_code(code: str, prefix: str = "    ") -> str:
    """Çok satırlı bir kod bloğunun her satırının başına prefix ekler (boş satırlar hariç).
    _build_mobile/web/desktop_template'in steps_code'u indent'leme şeklinin aynısı (bkz. :2329-2330)."""
    return "\n".join((prefix + line if line.strip() else "") for line in code.splitlines())


def _condition_expr(item: "StepItem", platform: str, idx: int) -> str:
    """Bir condition StepItem'ı, raise etmeyen bool döndüren tek satırlık bir Python ifadesine çevirir."""
    ctype = item.condition_type
    if ctype == "image_exists":
        find_fn = "_find_b64_on_screen" if platform == "desktop" else "_find_b64_on_screen_web"
        return f"bool({find_fn}('{item.image_b64}', timeout=8))"
    if ctype == "element_exists":
        hint = item.content.replace("'", "\\'")
        if platform == "mobile":
            return f"_safe_assert(driver, '{hint}')"
        if platform == "web":
            return f"_safe_assert_web(driver, '{hint}', raise_on_fail=False)"
        return f"_safe_assert_desktop('{hint}', raise_on_fail=False)"
    if ctype == "variable_compare":
        var   = item.compare_var.replace("'", "\\'")
        value = item.compare_value.replace("'", "\\'")
        left  = f"str(_VARS.get('{var}', ''))"
        if item.compare_op == "neq":
            return f"{left} != '{value}'"
        if item.compare_op == "contains":
            return f"'{value}' in {left}"
        return f"{left} == '{value}'"   # "eq" varsayılan
    return "False"  # condition_type boş/bilinmeyen — güvenli varsayılan
```

- [ ] **Step 2: `_steps_to_code()` recursive üretim fonksiyonunu ekle**

`_condition_expr`'in hemen altına ekle:

```python
def _steps_to_code(items: list, platform: str, counter: list, rule_fn, indent: str = "") -> tuple[str, list, list]:
    """items (üst seviye ya da bir then/else dalı) için Python kodu üretir.
    counter=[n] paylaşılan/mutable sayaç — dal içindeki adımlar da aynı artan idx'i kullanır.
    Returns: (indent'li kod string'i, code_lines rapor listesi, unrecognized metin listesi)
    code_lines elemanları: (kind, step_label, code_or_empty) — mevcut _generate_steps sözleşmesiyle aynı."""
    blocks = []
    code_lines = []
    unrecognized = []

    for item in items:
        idx = counter[0]; counter[0] += 1

        if item.disabled:
            label = item.content or f"Adım {idx+1}"
            code_lines.append(("comment", label, f"{indent}# [DEVRE DIŞI] {label}"))
            blocks.append(f"{indent}# [DEVRE DIŞI] {label}")
            continue

        if item.type == "condition":
            cond_expr = _condition_expr(item, platform, idx)
            then_code, then_lines, then_unrec = _steps_to_code(
                item.then_steps, platform, counter, rule_fn, indent + "    ")
            else_code, else_lines, else_unrec = _steps_to_code(
                item.else_steps, platform, counter, rule_fn, indent + "    ")
            then_code = then_code or f"{indent}    pass"
            else_code = else_code or f"{indent}    pass"
            label = item.content or f"Koşul {idx+1}"
            block = (
                f"{indent}_check_stop()\n"
                f"{indent}print('STEP_START:{idx}')\n"
                f"{indent}_cond_{idx} = {cond_expr}\n"
                f"{indent}if _cond_{idx}:\n{then_code}\n"
                f"{indent}else:\n{else_code}\n"
                f"{indent}print('STEP_DONE:{idx}')"
            )
            blocks.append(block)
            code_lines.append(("condition", label, block))
            code_lines.extend(then_lines)
            code_lines.extend(else_lines)
            unrecognized.extend(then_unrec)
            unrecognized.extend(else_unrec)
            continue

        if item.type == "image":
            code = _indent_code("_check_stop()\n" + _image_step_code(item, platform, idx), indent)
            blocks.append(code)
            code_lines.append(("image", item.content or f"Görsel {idx+1}", code))
        elif item.type == "sql":
            code = _indent_code("_check_stop()\n" + _sql_step_code(item, idx), indent)
            blocks.append(code)
            code_lines.append(("rule", item.content or f"SQL {idx+1}", code))
        elif item.type == "api":
            code = _indent_code("_check_stop()\n" + _api_step_code(item, idx), indent)
            blocks.append(code)
            code_lines.append(("rule", item.content or f"API {idx+1}", code))
        elif item.type == "comment":
            code = f"{indent}# [YORUM] {item.content}"
            blocks.append(code)
            code_lines.append(("comment", item.content or f"Yorum {idx+1}", code))
        else:
            step = item.content
            parsed = rule_fn(step)
            if parsed:
                _inner = ("\n" + indent + "    ").join(parsed)
                wrapped = (
                    f"{indent}_check_stop()\n"
                    f"{indent}print('STEP_START:{idx}')\n"
                    f"{indent}try:\n"
                    f"{indent}    {_inner}\n"
                    f"{indent}    print('STEP_DONE:{idx}')\n"
                    f"{indent}except Exception as _e_{idx}:\n"
                    f"{indent}    print(f'[FAIL] {{_e_{idx}}}')\n"
                    f"{indent}    print('STEP_FAIL:{idx}')\n"
                    f"{indent}    raise"
                )
                blocks.append(wrapped)
                code_lines.append(("rule", step, wrapped))
            else:
                blocks.append(None)   # LLM sonucu ikinci geçişte doldurulacak — yer tutucu
                code_lines.append(("llm", step, ""))
                unrecognized.append(step)

    return "\n\n".join(b for b in blocks if b is not None), code_lines, unrecognized
```

**Not:** LLM-fallback (unrecognized) adımlar için `blocks` listesine `None` konuluyor çünkü LLM sonucu ASENKRON toplu sorgudan sonra ikinci geçişte gelir — bu yüzden Step 3'te `_generate_steps`'in son montaj mantığı da güncelleniyor (üst seviye + dal içi adımların LLM koduyla doğru sırada birleştirilmesi gerekiyor). Basitlik için: **1-seviye nesting kararı gereği**, `then_steps`/`else_steps` içindeki tanınmayan metin adımları da LLM'e gönderilir ama üretilen kod, `code_lines` raporundaki sıraya göre değil, her `_steps_to_code` çağrısının kendi `blocks` listesindeki pozisyona göre yerleştirilir — bu yüzden LLM doldurma adımı da recursive hale getirilmeli. Bunu Step 3'te ele alıyoruz.

- [ ] **Step 3: `_generate_steps`'i yeni yardımcıları kullanacak şekilde yeniden yaz**

`ai_test_generator_router.py:3133-3235` TÜMÜNÜ şununla değiştir:

```python
async def _generate_steps(req: GenerateRequest) -> tuple[str, list[dict]]:
    """
    Test case'i adım adım işler (metin + görsel + condition karma destekli).
    Döndürür: (kod_str, adım_raporu)
    """
    rule_fn = (
        _rule_mobile  if req.platform == "mobile"  else
        _rule_desktop if req.platform == "desktop" else
        _rule_web
    )

    if req.steps_list:
        structured = req.steps_list
    else:
        structured = [
            StepItem(type="text", content=l.strip())
            for l in req.test_case.splitlines() if l.strip()
        ]

    counter = [0]
    steps_code, code_lines, unrecognized = _steps_to_code(structured, req.platform, counter, rule_fn)

    # LLM'e toplu sor (üst seviye + dal içi tüm tanınmayan metin adımları)
    llm_results = {}
    if unrecognized:
        llm_results = await _ask_llm_for_steps(unrecognized, req.platform)

    # LLM kodu üretilen ana string'e enjekte edilmeli — placeholder yaklaşımı yerine,
    # basitlik için LLM adımlarını üst seviyede yeniden üret (nested LLM adımı nadir durum,
    # 1-seviye sınırı ile dal içi LLM adımları da düz metinle aynı formatta üretilir).
    def _fill_llm(items: list, counter2: list, indent: str = "") -> str:
        blocks = []
        for item in items:
            idx = counter2[0]; counter2[0] += 1
            if item.disabled:
                blocks.append(f"{indent}# [DEVRE DIŞI] {item.content or f'Adım {idx+1}'}")
                continue
            if item.type == "condition":
                cond_expr = _condition_expr(item, req.platform, idx)
                then_code = _fill_llm(item.then_steps, counter2, indent + "    ") or f"{indent}    pass"
                else_code = _fill_llm(item.else_steps, counter2, indent + "    ") or f"{indent}    pass"
                blocks.append(
                    f"{indent}_check_stop()\n"
                    f"{indent}print('STEP_START:{idx}')\n"
                    f"{indent}_cond_{idx} = {cond_expr}\n"
                    f"{indent}if _cond_{idx}:\n{then_code}\n"
                    f"{indent}else:\n{else_code}\n"
                    f"{indent}print('STEP_DONE:{idx}')"
                )
                continue
            if item.type in ("image", "sql", "api", "comment"):
                # Bu tipler zaten _steps_to_code içinde tam üretildi (LLM'e hiç düşmezler),
                # burada sadece idx senkronizasyonu için tekrar üretiyoruz.
                if item.type == "image":
                    blocks.append(_indent_code("_check_stop()\n" + _image_step_code(item, req.platform, idx), indent))
                elif item.type == "sql":
                    blocks.append(_indent_code("_check_stop()\n" + _sql_step_code(item, idx), indent))
                elif item.type == "api":
                    blocks.append(_indent_code("_check_stop()\n" + _api_step_code(item, idx), indent))
                else:
                    blocks.append(f"{indent}# [YORUM] {item.content}")
                continue
            step = item.content
            parsed = rule_fn(step)
            if parsed:
                _inner = ("\n" + indent + "    ").join(parsed)
                blocks.append(
                    f"{indent}_check_stop()\n"
                    f"{indent}print('STEP_START:{idx}')\n"
                    f"{indent}try:\n"
                    f"{indent}    {_inner}\n"
                    f"{indent}    print('STEP_DONE:{idx}')\n"
                    f"{indent}except Exception as _e_{idx}:\n"
                    f"{indent}    print(f'[FAIL] {{_e_{idx}}}')\n"
                    f"{indent}    print('STEP_FAIL:{idx}')\n"
                    f"{indent}    raise"
                )
            else:
                llm_code = llm_results.get(step, "")
                llm_code = "\n".join(
                    l for l in llm_code.splitlines()
                    if l.strip().startswith("#") or re.match(r'^\s*[a-z_].*[\(\.]', l)
                ).strip()
                if llm_code:
                    llm_code = textwrap.dedent(llm_code)
                if not llm_code:
                    llm_code = f"# TODO (anlasilamadi): {step}\n{indent}time.sleep(1)"
                    _inner = llm_code
                    blocks.append(f"{indent}{_inner}")
                else:
                    _llm_inner = ("\n" + indent + "    ").join(llm_code.splitlines())
                    blocks.append(
                        f"{indent}_check_stop()\n"
                        f"{indent}print('STEP_START:{idx}')\n"
                        f"{indent}# {step}\n"
                        f"{indent}try:\n"
                        f"{indent}    {_llm_inner}\n"
                        f"{indent}    print('STEP_DONE:{idx}')\n"
                        f"{indent}except Exception as _e_{idx}:\n"
                        f"{indent}    print(f'[FAIL] {{_e_{idx}}}')\n"
                        f"{indent}    print('STEP_FAIL:{idx}')\n"
                        f"{indent}    raise"
                    )
        return "\n\n".join(blocks)

    if unrecognized:
        # LLM sonucu varsa tüm kodu (idx sayacını sıfırlayıp) yeniden, bu sefer LLM
        # sonuçlarıyla üret — iki geçişli tasarım mevcut _generate_steps ile aynı prensip.
        steps_code = _fill_llm(structured, [0])

    # Rapor: kind == "llm"/"todo" olanları code_lines'tan _fill_llm sonrası tekrar türetmek yerine,
    # mevcut basit rapor sözleşmesini koru — üst seviye rapor code_lines'tan gelir (condition dahil).
    report = [
        {"step": step, "method": kind, "code": code, "index": i}
        for i, (kind, step, code) in enumerate(code_lines)
    ]

    return steps_code, report
```

**Not (idx senkronizasyon riski):** `_steps_to_code` ve `_fill_llm` AYNI ağaç üzerinde AYNI sırayla gezindiği için `counter`/`counter2` her ikisinde de aynı `idx` değerlerini üretir — bu yüzden `STEP_START:{idx}` numaraları iki geçiş arasında tutarlı kalır. Step 5'te bunu somut bir testle doğrula.

- [ ] **Step 4: Sözdizimi ve temel içe aktarma kontrolü**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys; sys.path.insert(0, '.')
import py_compile
py_compile.compile('routers/ai_test_generator_router.py', doraise=True)
print('OK')
"
```
Expected: `OK`

- [ ] **Step 5: Nested condition kod üretimini uçtan uca doğrula (görsel yok, sadece variable_compare)**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys, asyncio; sys.path.insert(0, '.')
from routers.ai_test_generator_router import _generate_steps, GenerateRequest, StepItem

req = GenerateRequest(
    platform='web',
    steps_list=[
        StepItem(type='sql', sql_query='SELECT 1', db_connection='sqlite:///:memory:', var_name='x'),
        StepItem(type='condition', condition_type='variable_compare',
                 compare_var='x', compare_op='eq', compare_value='1',
                 then_steps=[StepItem(type='text', content='\"Basarili\" gorunmeli')],
                 else_steps=[StepItem(type='text', content='\"Basarisiz\" gorunmeli')]),
        StepItem(type='text', content='\"Devam\" tikla'),
    ],
)
code, report = asyncio.run(_generate_steps(req))
print(code)
print('---REPORT---')
for r in report: print(r['index'], r['method'], r['step'])
compile(code, '<generated>', 'exec')
print('SYNTAX OK')
# idx sürekliliği: condition disinda kalan son 'text' adiminin STEP_START numarasi
# then/else dallarindaki adimlardan SONRA gelmeli (çakışma olmamalı)
import re
ids = [int(m) for m in re.findall(r\"STEP_START:(\d+)\", code)]
assert ids == sorted(set(ids)) and len(ids) == len(set(ids)), f'idx cakismasi: {ids}'
print('IDX OK', ids)
"
```
Expected: `SYNTAX OK` ve `IDX OK [...]` (çakışmasız, artan bir idx listesi) yazdırır; `code` çıktısında `if _cond_1:` / `else:` bloklarının 4-boşluk girintili olduğunu gözle de doğrula.

- [ ] **Step 6: Boş dal + disabled condition davranışını doğrula**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys, asyncio; sys.path.insert(0, '.')
from routers.ai_test_generator_router import _generate_steps, GenerateRequest, StepItem

# Boş else_steps
req1 = GenerateRequest(platform='desktop', steps_list=[
    StepItem(type='condition', condition_type='image_exists', image_b64='AAAA',
             then_steps=[StepItem(type='text', content='\"X\" tikla')], else_steps=[]),
])
code1, _ = asyncio.run(_generate_steps(req1))
compile(code1, '<t1>', 'exec')
assert 'pass' in code1
print('EMPTY BRANCH OK')

# Disabled condition — hic kod uretilmemeli (sadece yorum)
req2 = GenerateRequest(platform='mobile', steps_list=[
    StepItem(type='condition', disabled=True, content='devre disi kosul', condition_type='element_exists'),
])
code2, report2 = asyncio.run(_generate_steps(req2))
assert 'DEVRE DIŞI' in code2
assert '_cond_' not in code2
print('DISABLED OK')
"
```
Expected: `EMPTY BRANCH OK` ve `DISABLED OK` (ikinci senaryoda `_cond_` hiç üretilmemeli — condition disabled'sa şart hiç değerlendirilmiyor).

- [ ] **Step 7: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "AI Test Generator: _generate_steps recursive condition (if/else) uretimi destekliyor"
```

---

### Task 5: Frontend — Veri modeli, `TYPE_META`, `addConditionStep()`

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html:1998-2004` (`TYPE_META`)
- Modify: `backend/WebArayuz/ai-generator.html:1933-1937` civarı (yeni `addConditionStep` fonksiyonu `addCommentStep`'in hemen altına)
- Modify: `backend/WebArayuz/ai-generator.html:1678-1686` (`updateGenerateBtn`)

**Interfaces:**
- Produces: `window.addConditionStep()`; step objesi şekli: `{ type:"condition", condition_type:"image_exists", content:"", b64:"", compare_var:"", compare_op:"eq", compare_value:"", then_steps:[], else_steps:[], status:null }`.

- [ ] **Step 1: `TYPE_META`'ya condition ekle**

`ai-generator.html:1998-2004` mevcut:
```js
        const TYPE_META = {
            text:    { label: "Metin",  cls: "text" },
            image:   { label: "Görsel", cls: "image" },
            sql:     { label: "SQL",    cls: "sql" },
            api:     { label: "API",    cls: "api" },
            comment: { label: "Yorum",  cls: "comment" },
        };
```
Yerine:
```js
        const TYPE_META = {
            text:      { label: "Metin",   cls: "text" },
            image:     { label: "Görsel",  cls: "image" },
            sql:       { label: "SQL",     cls: "sql" },
            api:       { label: "API",     cls: "api" },
            comment:   { label: "Yorum",   cls: "comment" },
            condition: { label: "If/Else", cls: "condition" },
        };
```

- [ ] **Step 2: `addConditionStep` ekle**

`ai-generator.html:1933-1937` (`addCommentStep`'in tanımı) hemen altına ekle:
```js
    window.addConditionStep = function() {
        steps.push({
            type: "condition", condition_type: "image_exists",
            content: "", b64: "",
            compare_var: "", compare_op: "eq", compare_value: "",
            then_steps: [], else_steps: [],
            status: null,
        });
        renderStepList();
        updateGenerateBtn();
    };
```

- [ ] **Step 3: `updateGenerateBtn` condition'ı geçerli adım sayımına dahil et**

`ai-generator.html:1678-1686` mevcut:
```js
    function updateGenerateBtn() {
        const hasValidStep = steps.some(s =>
            (s.type === "text"  && s.content.trim().length > 0) ||
            (s.type === "image" && s.b64.length > 0) ||
            (s.type === "sql"   && (s.sql_query  || "").trim().length > 0) ||
            (s.type === "api"   && (s.api_url    || "").trim().length > 0)
        );
        document.getElementById("btnGenerate").disabled = !(hasValidStep && selectedPlatform) || isGenerating;
    }
```
Yerine:
```js
    function _isValidLeafStep(s) {
        return (s.type === "text"  && s.content.trim().length > 0) ||
               (s.type === "image" && (s.b64 || "").length > 0) ||
               (s.type === "sql"   && (s.sql_query  || "").trim().length > 0) ||
               (s.type === "api"   && (s.api_url    || "").trim().length > 0);
    }
    function _hasValidStepIn(list) {
        return list.some(s =>
            _isValidLeafStep(s) ||
            (s.type === "condition" && (
                _hasValidStepIn(s.then_steps || []) || _hasValidStepIn(s.else_steps || [])
            ))
        );
    }
    function updateGenerateBtn() {
        const hasValidStep = _hasValidStepIn(steps);
        document.getElementById("btnGenerate").disabled = !(hasValidStep && selectedPlatform) || isGenerating;
    }
```

- [ ] **Step 4: Tarayıcıda manuel doğrula**

Dev sunucusunu başlat (`backend` dizininde `venv\Scripts\python.exe main.py`), `http://localhost:8000/ui/ai-generator.html` aç, tarayıcı konsolunda:
```js
addConditionStep();
console.log(steps[steps.length-1]);
```
Expected: `{type:"condition", condition_type:"image_exists", ..., then_steps:[], else_steps:[]}` içeren obje konsola yazılır, hata fırlamaz (henüz `renderStepRow`'da condition dalı olmadığı için satır görsel olarak boş/eksik render olabilir — bu normal, Task 6'da düzelecek).

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "AI Test Generator (frontend): condition step veri modeli + addConditionStep"
```

---

### Task 6: Frontend — `renderStepRow` condition dalı + nested mini-listeler

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html:2009-2101` (`renderStepRow` içindeki `if/else if` zinciri — yeni bir `else if (s.type === "condition")` dalı eklenir)
- Modify: `backend/WebArayuz/ai-generator.html:1985-1992` (`renderStepList`)

**Interfaces:**
- Consumes: Task 5'teki step şekli.
- Produces: `renderStepRow(s, i)` artık `condition` tipini render eder; her dal için `renderStepRow`'u branch-scoped çağıran bir `renderBranchList(parentIdx, branch, list)` yardımcısı.

- [ ] **Step 1: `renderStepRow`'a condition dalı ekle**

`ai-generator.html:2062-2101` (`api` dalının bittiği `}` — mevcut zincirin SONU) hemen sonrasına, `}` kapanışından ÖNCE yeni bir `else if` ekle. Mevcut yapı:
```js
        } else if (s.type === "api") {
            ...
            </div>`;
        }

        const disabledClass = s.disabled ? " disabled" : "";
```
Yerine (yeni dal `api` ile `const disabledClass` arasına girer):
```js
        } else if (s.type === "api") {
            ...
            </div>`;
        } else if (s.type === "condition") {
            extraClass = " extended";
            const condOpts = [
                { v: "image_exists",     l: "🖼️ Görsel Var mı" },
                { v: "element_exists",   l: "🔎 Element/Metin Var mı" },
                { v: "variable_compare", l: "🔢 Değişken Karşılaştır" },
            ];
            const condSel = `<select class="step-action-select" onchange="updateStepField(${i}, 'condition_type', this.value)">
                ${condOpts.map(o => `<option value="${o.v}"${(s.condition_type||"image_exists") === o.v ? " selected" : ""}>${o.l}</option>`).join("")}
            </select>`;

            let condFieldsHtml = "";
            if (s.condition_type === "image_exists") {
                condFieldsHtml = s.b64
                    ? `<img class="step-img-thumb" src="data:image/png;base64,${s.b64}" onclick="previewStepImage(${i})" title="Tıkla → Büyüt">`
                    : `<span class="step-img-placeholder" onclick="retakeImage(${i})">📁 Tıkla → Görsel Yükle</span>`;
            } else if (s.condition_type === "element_exists") {
                condFieldsHtml = `<input class="step-content-input" type="text" value="${escHtml(s.content)}"
                    placeholder='Aranacak metin/element ipucu' oninput="updateStepContent(${i}, this.value)" style="flex:1">`;
            } else if (s.condition_type === "variable_compare") {
                const opSel = `<select class="step-action-select" onchange="updateStepField(${i}, 'compare_op', this.value)">
                    <option value="eq"${(s.compare_op||"eq") === "eq" ? " selected" : ""}>Eşit</option>
                    <option value="neq"${s.compare_op === "neq" ? " selected" : ""}>Eşit Değil</option>
                    <option value="contains"${s.compare_op === "contains" ? " selected" : ""}>İçerir</option>
                </select>`;
                condFieldsHtml = `
                    <input class="step-ext-input" type="text" value="${escHtml(s.compare_var||'')}"
                        placeholder="{{degisken}}" oninput="updateStepField(${i}, 'compare_var', this.value)" style="max-width:140px;">
                    ${opSel}
                    <input class="step-ext-input" type="text" value="${escHtml(s.compare_value||'')}"
                        placeholder="değer" oninput="updateStepField(${i}, 'compare_value', this.value)" style="max-width:140px;">`;
            }

            contentHtml = `<div class="step-ext-body">
                <div class="step-ext-row">
                    ${condSel}
                    ${condFieldsHtml}
                </div>
                <div class="step-branch">
                    <div class="step-branch-label">✅ Eğer</div>
                    <div class="step-branch-list" id="branch-${i}-then" ondragover="stepListDragOver(event)" ondrop="stepListDrop(event)">${renderBranchList(i, "then", s.then_steps || [])}</div>
                    <div class="step-branch-add-row">
                        <button class="btn-reset" onclick="addTextStep(${i}, 'then')">+ Metin</button>
                        <button class="btn-reset" onclick="addImageStep(${i}, 'then')">+ Görsel</button>
                        <button class="btn-reset" onclick="addSqlStep(${i}, 'then')">+ SQL</button>
                        <button class="btn-reset" onclick="addApiStep(${i}, 'then')">+ API</button>
                    </div>
                </div>
                <div class="step-branch">
                    <div class="step-branch-label">❌ Değilse</div>
                    <div class="step-branch-list" id="branch-${i}-else" ondragover="stepListDragOver(event)" ondrop="stepListDrop(event)">${renderBranchList(i, "else", s.else_steps || [])}</div>
                    <div class="step-branch-add-row">
                        <button class="btn-reset" onclick="addTextStep(${i}, 'else')">+ Metin</button>
                        <button class="btn-reset" onclick="addImageStep(${i}, 'else')">+ Görsel</button>
                        <button class="btn-reset" onclick="addSqlStep(${i}, 'else')">+ SQL</button>
                        <button class="btn-reset" onclick="addApiStep(${i}, 'else')">+ API</button>
                    </div>
                </div>
            </div>`;
        }

        const disabledClass = s.disabled ? " disabled" : "";
```

(`ondragover`/`ondrop` attribute'ları Task 8 Step 2 için önden eklendi — o task'a geldiğinde tekrar dokunmaya gerek yok.)

- [ ] **Step 2: `renderBranchList` yardımcısını ekle (nested, tek seviye — condition'ı render ETMEZ)**

`renderStepRow` fonksiyonunun HEMEN ÜSTÜNE (`function renderStepRow(s, i) {` satırından önce) ekle:

```js
    function renderBranchList(parentIdx, branch, list) {
        if (!list.length) {
            return '<div class="step-branch-empty">Adım yok.</div>';
        }
        return list.map((s, bIdx) => renderStepRow(s, parentIdx, branch, bIdx)).join("");
    }
```

- [ ] **Step 3: `renderStepRow` imzasını ve içindeki tüm `${i}` referanslarını branch-aware yap**

`ai-generator.html:1994` mevcut imza:
```js
    function renderStepRow(s, i) {
```
Yerine:
```js
    function renderStepRow(s, i, branch, bIdx) {
        // Üst seviye adım: branch=undefined → wire fonksiyonlarına (i, undefined, undefined) geçilir,
        // bu da Task 7'de eklenen "branch yoksa üst seviye" varsayılanına düşer.
        // Dal içi adım: branch="then"|"else", bIdx = dal içindeki index; onclick'lerde (i, branch, bIdx) kullanılır.
        const _a = branch !== undefined ? `${i}, '${branch}', ${bIdx}` : `${i}`;
        const _rowId = branch !== undefined ? `step-row-${i}-${branch}-${bIdx}` : `step-row-${i}`;
```
Sonra fonksiyon gövdesindeki TÜM `onclick="...(${i})"` / `oninput="...(${i}, ...)"` çağrılarında `${i}` yerine `${_a}` kullan (ör. `onclick="deleteStep(${i})"` → `onclick="deleteStep(${_a})"`, `oninput="updateStepContent(${i}, this.value)"` → `oninput="updateStepContent(${_a}, this.value)"`), ve en sondaki dönen HTML'de `id="step-row-${i}"` → `id="${_rowId}"`, `ondragstart="stepDragStart(event, ${i})"` → `ondragstart="stepDragStart(event, ${_a})"`.

**Dikkat:** Dal içi adımlarda (`branch !== undefined`) sürükle-bırak SADECE kendi dalı içinde anlamlı — Task 8'de `stepDragStart`/`stepListDrop` bu bilgiyi kullanacak şekilde güncellenecek.

- [ ] **Step 4: `renderStepList` değişmiyor ama çağrı imzasını kontrol et**

`ai-generator.html:1991`: `steps.map((s, i) => renderStepRow(s, i))` — üst seviye çağrı `branch`/`bIdx` vermediği için `undefined` olarak geçer, Step 3'teki `_a = branch !== undefined ? ... : \`${i}\`` mantığı bunu doğru ele alır. **Bu satırda değişiklik gerekmez.**

- [ ] **Step 5: Tarayıcıda manuel doğrula**

`http://localhost:8000/ui/ai-generator.html` sert yenile, "If/Else" adımı ekleyen bir buton varsa (Step 6/HTML güncellemesi — bkz. Step 6 not) tıkla; condition satırının açılır menü + "✅ Eğer"/"❌ Değilse" mini listeleriyle render olduğunu, içine "+ Metin" ile bir adım eklenip görünür şekilde listelendiğini gözle doğrula.

**Not (HTML toolbar):** Adım ekleme butonlarının olduğu toolbar'a (muhtemelen `id="btnAddImage"` civarında, `ai-generator.html:1673`'ün yakınındaki HTML) `<button onclick="addConditionStep()">➕ If/Else</button>` benzeri bir buton eklenmesi gerekiyor — implementasyon sırasında mevcut "Metin/Görsel/SQL/API/Yorum ekle" butonlarının HTML'sini bulup aynı deseni takip ederek ekle.

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "AI Test Generator (frontend): condition adiminin render'i + nested then/else mini-listeler"
```

---

### Task 7: Frontend — Mutasyon fonksiyonlarını branch-aware yap

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html:1820-1937` (tüm `add*Step`, `deleteStep`, `toggleStepDisabled`, `updateStepContent`, `updateStepAction`, `updateStepField`)

**Interfaces:**
- Produces: Her fonksiyon artık `(idx, branch, bIdx)` imzasına sahip — `branch` `undefined`/`null` ise üst seviye `steps` dizisi, değilse `steps[idx][branch + "_steps"]` kullanılır. **Tüm mevcut tek-parametreli çağrılar değişmeden çalışır.**

- [ ] **Step 1: Ortak `_container(idx, branch)` yardımcısını ekle**

`ai-generator.html:1820`'den (`window.addTextStep = function() {`) HEMEN ÖNCE ekle:
```js
    function _container(idx, branch) {
        return branch ? steps[idx][branch + "_steps"] : steps;
    }
```

- [ ] **Step 2: `addTextStep` / `addImageStep` / `addSqlStep` / `addApiStep` / `addCommentStep`'i güncelle**

`ai-generator.html:1820-1836` mevcut:
```js
    window.addTextStep = function() {
        steps.push({ type: "text", content: "", b64: "", action: "click", status: null });
        renderStepList();
        updateGenerateBtn();
        // Son input'u odakla
        const inputs = document.querySelectorAll(".step-content-input");
        if (inputs.length) inputs[inputs.length - 1].focus();
    };

    window.addImageStep = function() {
        const idx = steps.length;
        steps.push({ type: "image", content: "", b64: "", action: "click", status: null });
        renderStepList();
        updateGenerateBtn();
        startImageCapture(idx);
    };
```
Yerine:
```js
    window.addTextStep = function(parentIdx, branch) {
        const arr = _container(parentIdx, branch);
        arr.push({ type: "text", content: "", b64: "", action: "click", status: null });
        renderStepList();
        updateGenerateBtn();
        // Son input'u odakla
        const inputs = document.querySelectorAll(".step-content-input");
        if (inputs.length) inputs[inputs.length - 1].focus();
    };

    window.addImageStep = function(parentIdx, branch) {
        const arr = _container(parentIdx, branch);
        const localIdx = arr.length;
        arr.push({ type: "image", content: "", b64: "", action: "click", status: null });
        renderStepList();
        updateGenerateBtn();
        // Görsel yakalama akışı düz index bekliyor — dal içi adımlar için bu adım
        // manuel "Tıkla → Görsel Yükle" ile de doldurulabildiğinden burada sadece
        // üst seviye (branch yok) durumda otomatik yakalamayı tetikliyoruz.
        if (!branch) startImageCapture(localIdx);
    };
```

`ai-generator.html:1918-1937` mevcut (`addSqlStep`/`addApiStep`/`addCommentStep`):
```js
    window.addSqlStep = function() {
        steps.push({ type: "sql", content: "", b64: "", action: "query_print",
            db_connection: "", sql_query: "", var_name: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };

    window.addApiStep = function() {
        steps.push({ type: "api", content: "", b64: "", action: "print",
            api_url: "", api_method: "GET", api_headers: "", api_body: "",
            json_field: "", var_name: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };

    window.addCommentStep = function() {
        steps.push({ type: "comment", content: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };
```
Yerine:
```js
    window.addSqlStep = function(parentIdx, branch) {
        const arr = _container(parentIdx, branch);
        arr.push({ type: "sql", content: "", b64: "", action: "query_print",
            db_connection: "", sql_query: "", var_name: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };

    window.addApiStep = function(parentIdx, branch) {
        const arr = _container(parentIdx, branch);
        arr.push({ type: "api", content: "", b64: "", action: "print",
            api_url: "", api_method: "GET", api_headers: "", api_body: "",
            json_field: "", var_name: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };

    window.addCommentStep = function(parentIdx, branch) {
        const arr = _container(parentIdx, branch);
        arr.push({ type: "comment", content: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };
```

**Not:** Task 5 Step 2'de eklenen `addConditionStep` üst-seviye-only kalır (1-seviye sınırı — dal içinden çağrılmaz, HTML'de dal içi "+" butonlarında `addConditionStep` hiç yer almıyor zaten, bkz. Task 6 Step 1).

- [ ] **Step 3: `deleteStep` / `toggleStepDisabled` / `updateStepContent` / `updateStepAction` / `updateStepField`'i güncelle**

`ai-generator.html:1837-1848` ve `1904-1916` mevcut:
```js
    window.deleteStep = function(idx) {
        steps.splice(idx, 1);
        renderStepList();
        updateGenerateBtn();
    };

    window.toggleStepDisabled = function(idx) {
        if (!steps[idx]) return;
        steps[idx].disabled = !steps[idx].disabled;
        renderStepList();
        updateGenerateBtn();
    };
```
```js
    window.updateStepContent = function(idx, value) {
        if (steps[idx]) steps[idx].content = value;
        updateGenerateBtn();
    };

    window.updateStepAction = function(idx, value) {
        if (steps[idx]) steps[idx].action = value;
    };

    window.updateStepField = function(idx, field, value) {
        if (steps[idx]) steps[idx][field] = value;
        updateGenerateBtn();
    };
```
Yerine:
```js
    window.deleteStep = function(idx, branch, bIdx) {
        const arr = _container(idx, branch);
        arr.splice(branch ? bIdx : idx, 1);
        renderStepList();
        updateGenerateBtn();
    };

    window.toggleStepDisabled = function(idx, branch, bIdx) {
        const arr = _container(idx, branch);
        const target = branch ? arr[bIdx] : arr[idx];
        if (!target) return;
        target.disabled = !target.disabled;
        renderStepList();
        updateGenerateBtn();
    };
```
```js
    window.updateStepContent = function(idx, a, b, c) {
        // Eski çağrı: updateStepContent(idx, value) → arguments.length === 2
        // Yeni çağrı: updateStepContent(idx, branch, bIdx, value) → arguments.length === 4
        let branch, bIdx, value;
        if (arguments.length <= 2) { value = a; }
        else { branch = a; bIdx = b; value = c; }
        const arr = _container(idx, branch);
        const target = branch ? arr[bIdx] : arr[idx];
        if (target) target.content = value;
        updateGenerateBtn();
    };

    window.updateStepAction = function(idx, a, b, c) {
        let branch, bIdx, value;
        if (arguments.length <= 2) { value = a; }
        else { branch = a; bIdx = b; value = c; }
        const arr = _container(idx, branch);
        const target = branch ? arr[bIdx] : arr[idx];
        if (target) target.action = value;
    };

    window.updateStepField = function(idx, a, b, c, d) {
        // Eski çağrı: updateStepField(idx, field, value) → arguments.length === 3
        // Yeni çağrı: updateStepField(idx, branch, bIdx, field, value) → arguments.length === 5
        let branch, bIdx, field, value;
        if (arguments.length <= 3) { field = a; value = b; }
        else { branch = a; bIdx = b; field = c; value = d; }
        const arr = _container(idx, branch);
        const target = branch ? arr[bIdx] : arr[idx];
        if (target) target[field] = value;
        updateGenerateBtn();
    };
```

**Neden `arguments.length` ile ayırt ediliyor (tip ile değil):** İlk yazımda "ikinci argüman string değilse eski çağrıdır" mantığı kullanılmıştı, ama bu YANLIŞ — üst seviye çağrıda da ikinci argüman (`this.value`, gerçek değer) zaten bir string olduğu için tip kontrolü iki çağrı şeklini ASLA ayırt edemezdi (ikisi de string). Task 6 Step 3'teki `_a` değişkeni üst seviyede `${i}` (tek token), dal içinde `${i}, '${branch}', ${bIdx}` (üç token) ürettiği için, üst seviye çağrılar hep 2/3 argümanla (`updateStepContent(idx, value)`, `updateStepField(idx, field, value)`), dal içi çağrılar hep 4/5 argümanla gelir — bu yüzden doğru ayırt edici `arguments.length`.

- [ ] **Step 4: Tarayıcıda regresyon doğrulaması**

`http://localhost:8000/ui/ai-generator.html` sert yenile:
1. Eski davranış: "Metin" adımı ekle, içine bir şey yaz (`updateStepContent(idx, value)` eski 2-argüman yolu) — değerin `steps[idx].content`'e yazıldığını konsolda `console.log(steps)` ile doğrula.
2. Yeni davranış: "If/Else" ekle, "✅ Eğer" altına "+ Metin" ile bir adım ekle, içine yaz — `steps[condIdx].then_steps[0].content` doğru güncellenmeli.
3. Sil: hem üst seviye bir adımı hem dal içi bir adımı sil, doğru elemanın kaybolduğunu doğrula.

Expected: Üçü de hatasız çalışır, konsolda exception yok.

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "AI Test Generator (frontend): ekle/sil/guncelle fonksiyonlari branch-aware (geriye uyumlu)"
```

---

### Task 8: Frontend — Sürükle-bırak dal içine hapsetme

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html:1622-1623` (drag state)
- Modify: `backend/WebArayuz/ai-generator.html:1851-1902` (`stepDragStart`, `stepDragEnd`, `stepListDragOver`, `stepListDrop`)

**Interfaces:**
- Produces: `stepDragStart(e, idx, branch, bIdx)`; sürükleme sadece aynı `(parentIdx, branch)` kapsamı içinde geçerli (dal içi ↔ üst seviye veya farklı dallar arası sürükleme YOK — Global Constraints).

- [ ] **Step 1: Sürükle-bırak state'ine kapsam bilgisi ekle**

`ai-generator.html:1622-1623` mevcut:
```js
    // Sürükle-bırak state
    let _dragSrcIdx    = -1;
    let _dragTargetIdx = -1;
```
Yerine:
```js
    // Sürükle-bırak state — kapsam (parentIdx, branch) ile birlikte tutulur;
    // farklı kapsamlar arası sürükleme engellenir (dallar arası taşıma kapsam dışı)
    let _dragSrcIdx    = -1;
    let _dragTargetIdx = -1;
    let _dragScope     = null;   // null (üst seviye) | {parentIdx, branch}
```

- [ ] **Step 2: `stepDragStart`/`stepDragEnd`/`stepListDragOver`/`stepListDrop`'u güncelle**

`ai-generator.html:1851-1902` mevcut hali (Task 5-7 tam metninde gösterildi) yerine:
```js
    window.stepDragStart = function(e, idx, branch, bIdx) {
        _dragSrcIdx = branch ? bIdx : idx;
        _dragScope  = branch ? { parentIdx: idx, branch } : null;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(_dragSrcIdx));
        const rowId = branch ? `step-row-${idx}-${branch}-${bIdx}` : `step-row-${idx}`;
        setTimeout(() => {
            const row = document.getElementById(rowId);
            if (row) row.classList.add("dragging");
        }, 0);
    };

    window.stepDragEnd = function() {
        _dragSrcIdx    = -1;
        _dragTargetIdx = -1;
        _dragScope     = null;
        document.querySelectorAll(".step-item").forEach(el =>
            el.classList.remove("dragging", "drag-over"));
    };

    function _scopeMatches(rowId) {
        // rowId ya "step-row-{idx}" (üst seviye) ya "step-row-{idx}-{branch}-{bIdx}" (dal içi).
        const parts = rowId.replace("step-row-", "").split("-");
        if (parts.length === 1) return _dragScope === null;
        const [parentIdx, branch] = parts;
        return _dragScope !== null && String(_dragScope.parentIdx) === parentIdx && _dragScope.branch === branch;
    }

    window.stepListDragOver = function(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const items = document.querySelectorAll(".step-item[id^='step-row-']");
        let targetIdx = -1, targetRowId = null;
        for (const item of items) {
            if (!_scopeMatches(item.id)) continue;   // farklı kapsam — sürükleme hedefi olamaz
            const rect = item.getBoundingClientRect();
            if (e.clientY >= rect.top && e.clientY <= rect.bottom) {
                const parts = item.id.replace("step-row-", "").split("-");
                targetIdx   = parseInt(parts[parts.length - 1], 10);
                targetRowId = item.id;
                break;
            }
        }
        if (targetIdx !== _dragTargetIdx) {
            _dragTargetIdx = targetIdx;
            document.querySelectorAll(".step-item").forEach(el => el.classList.remove("drag-over"));
            if (targetIdx >= 0 && targetIdx !== _dragSrcIdx && targetRowId) {
                const row = document.getElementById(targetRowId);
                if (row) row.classList.add("drag-over");
            }
        }
    };

    window.stepListDrop = function(e) {
        e.preventDefault();
        if (_dragSrcIdx < 0 || _dragTargetIdx < 0 || _dragSrcIdx === _dragTargetIdx) {
            stepDragEnd();
            return;
        }
        const arr = _dragScope ? steps[_dragScope.parentIdx][_dragScope.branch + "_steps"] : steps;
        const moved = arr.splice(_dragSrcIdx, 1)[0];
        arr.splice(_dragTargetIdx, 0, moved);
        stepDragEnd();
        renderStepList();
        updateGenerateBtn();
    };
```

**Not:** `stepListDragOver` artık `#stepList` içindeki TÜM `.step-item`'ları tarıyor (üst seviye + her iki dal), `_scopeMatches` ile geçersiz kapsamdaki adayları eliyor — Task 6 Step 1'de `step-branch-list` div'lerine zaten `ondragover="stepListDragOver(event)"` / `ondrop="stepListDrop(event)"` eklenmişti, bu task'ta HTML tarafında ek değişiklik gerekmiyor.

- [ ] **Step 3: Tarayıcıda regresyon doğrulaması**

1. Üst seviyede 3 adım ekle, birini sürükleyip sırasını değiştir — eski davranış aynen çalışmalı.
2. Bir "If/Else" içine "✅ Eğer" dalına 2 metin adımı ekle, aralarında sürükle-bırak yap — sadece o dal içinde sıralanmalı.
3. Bir dal içi adımı üst seviyeye veya diğer dala sürüklemeye ÇALIŞ — `_scopeMatches` farklı kapsamları hedef olarak kabul etmediği için hiçbir şey olmamalı (drop no-op).

Expected: Üçü de tanımlandığı gibi davranır, konsol hatası yok.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "AI Test Generator (frontend): surukle-birak dal icine hapsedildi (dallar arasi tasima yok)"
```

---

### Task 9: Frontend — `_stepToApiItem` recursion + backend'e gönderim

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html:2603-2623` (`_stepToApiItem`)
- Modify: `backend/WebArayuz/ai-generator.html:2625-2645` (`buildPayload` — text-only özet filtresi)

**Interfaces:**
- Consumes: Task 1'deki backend `StepItem` şeması (`condition_type`, `compare_var`, `compare_op`, `compare_value`, `then_steps`, `else_steps`).
- Produces: `_stepToApiItem(s)` artık `condition` tipi için backend'in beklediği tam şekli üretir.

- [ ] **Step 1: `_stepToApiItem`'ı güncelle**

`ai-generator.html:2603-2623` mevcut:
```js
    function _stepToApiItem(s) {
        return {
            type:          s.type,
            disabled:      !!s.disabled,
            content:       s.content,
            image_b64:     s.b64          || "",
            action:        s.action       || "click",
            db_connection: s.db_connection || "",
            sql_query:     s.sql_query    || "",
            api_url:       s.api_url      || "",
            api_method:    s.api_method   || "GET",
            api_headers:   s.api_headers  || "",
            api_body:      s.api_body     || "",
            var_name:      s.var_name     || "",
            json_field:    s.json_field   || "",
            click_x:       (s.click_x >= 0) ? s.click_x : -1,
            click_y:       (s.click_y >= 0) ? s.click_y : -1,
            drag_x:        (s.drag_x  >= 0) ? s.drag_x  : -1,
            drag_y:        (s.drag_y  >= 0) ? s.drag_y  : -1,
        };
    }
```
Yerine:
```js
    function _stepToApiItem(s) {
        return {
            type:           s.type,
            disabled:       !!s.disabled,
            content:        s.content,
            image_b64:      s.b64          || "",
            action:         s.action       || "click",
            db_connection:  s.db_connection || "",
            sql_query:      s.sql_query    || "",
            api_url:        s.api_url      || "",
            api_method:     s.api_method   || "GET",
            api_headers:    s.api_headers  || "",
            api_body:       s.api_body     || "",
            var_name:       s.var_name     || "",
            json_field:     s.json_field   || "",
            click_x:        (s.click_x >= 0) ? s.click_x : -1,
            click_y:        (s.click_y >= 0) ? s.click_y : -1,
            drag_x:         (s.drag_x  >= 0) ? s.drag_x  : -1,
            drag_y:         (s.drag_y  >= 0) ? s.drag_y  : -1,
            condition_type: s.condition_type || "",
            compare_var:    s.compare_var    || "",
            compare_op:     s.compare_op     || "",
            compare_value:  s.compare_value  || "",
            then_steps:     (s.then_steps || []).map(_stepToApiItem),
            else_steps:     (s.else_steps || []).map(_stepToApiItem),
        };
    }
```

- [ ] **Step 2: `buildPayload`'daki text-only özetin condition dallarına da bakmasını sağla**

`ai-generator.html:2625-2630` mevcut:
```js
    function buildPayload() {
        const stepsList = steps.map(_stepToApiItem);
        // test_case geriye uyumluluk için (mobile fallback)
        const testCase = steps.filter(s => s.type === "text").map(s => s.content).join("\n");

        const base = { test_case: testCase, steps_list: stepsList, platform: selectedPlatform };
```
Yerine:
```js
    function _flattenTextContent(list) {
        let out = [];
        for (const s of list) {
            if (s.type === "text") out.push(s.content);
            else if (s.type === "condition") {
                out = out.concat(_flattenTextContent(s.then_steps || []));
                out = out.concat(_flattenTextContent(s.else_steps || []));
            }
        }
        return out;
    }

    function buildPayload() {
        const stepsList = steps.map(_stepToApiItem);
        // test_case geriye uyumluluk için (mobile fallback) — condition dallarındaki metin adımları da dahil
        const testCase = _flattenTextContent(steps).join("\n");

        const base = { test_case: testCase, steps_list: stepsList, platform: selectedPlatform };
```

- [ ] **Step 3: Uçtan uca doğrula — tarayıcıdan gerçek `/generate` çağrısı**

Sunucu çalışırken (`http://localhost:8000`), `ai-generator.html` sayfasında:
1. Web platformu seç, bir "SQL" adımı ekle (`sqlite:///:memory:`, `SELECT 1`, `var_name=x`).
2. Bir "If/Else" ekle: `variable_compare`, `compare_var=x`, `compare_op=eq`, `compare_value=1`; "Eğer" dalına bir metin adımı, "Değilse" dalına başka bir metin adımı ekle.
3. "🚀 Script Üret" butonuna bas.
4. Üretilen script panelinde `if _cond_1:` / `else:` bloklarının doğru girintiyle göründüğünü, tarayıcı konsolunda hiçbir hata olmadığını doğrula.

Expected: Script üretilir, konsol hatasız, `if`/`else` görünür.

- [ ] **Step 4: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "AI Test Generator (frontend): _stepToApiItem ve testCase ozeti condition dallarini kapsiyor"
```

---

### Task 10: Uçtan uca 3-platform doğrulama ve son temizlik

**Files:** Yok (sadece manuel/script doğrulama — kod değişikliği beklenmiyor, bulgu çıkarsa ilgili task'a geri dönülür)

- [ ] **Step 1: Backend script derlemesi — 3 platform**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys, asyncio; sys.path.insert(0, '.')
from routers.ai_test_generator_router import (
    _generate_steps, GenerateRequest, StepItem,
    _build_mobile_template, _build_web_template, _build_desktop_template,
)

steps_list = [
    StepItem(type='condition', condition_type='element_exists', content='Devam',
             then_steps=[StepItem(type='text', content='\"Devam\" tikla')],
             else_steps=[StepItem(type='comment', content='Devam gorunmedi, atlaniyor')]),
]

for platform, builder in [
    ('mobile',  lambda code: _build_mobile_template(GenerateRequest(platform='mobile', steps_list=steps_list, device_id='x', app_package='com.x'), code)),
    ('web',     lambda code: _build_web_template(GenerateRequest(platform='web', steps_list=steps_list, target_url='http://example.com'), code)),
    ('desktop', lambda code: _build_desktop_template(GenerateRequest(platform='desktop', steps_list=steps_list, app_path='notepad.exe'), code)),
]:
    req = GenerateRequest(platform=platform, steps_list=steps_list)
    code, report = asyncio.run(_generate_steps(req))
    full_script = builder(code)
    compile(full_script, f'<{platform}>', 'exec')
    print(platform, 'FULL SCRIPT SYNTAX OK', len(full_script.splitlines()), 'satir')
"
```
Expected: Üç platform için de `FULL SCRIPT SYNTAX OK ... satir` — hiçbiri `SyntaxError`/`IndentationError` fırlatmamalı. **Bu, tüm planın en kritik doğrulaması** — indentation hatası olsaydı burada patlardı. (Not: `_build_*_template` fonksiyonlarının gerçek imzaları/zorunlu parametreleri implementasyon sırasında Read ile teyit edilip bu çağrı örnekleri ona göre uyarlanmalı — bu plan yazılırken tam imzaları okunmadı, sadece `_generate_steps` çağrıldıktan sonra "steps_code, session_mode, vars_seed" gibi ek parametreler alabilecekleri agent raporunda not edilmişti.)

- [ ] **Step 2: Geriye dönük uyumluluk — condition'sız eski bir senaryo**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend" && python -c "
import sys, asyncio; sys.path.insert(0, '.')
from routers.ai_test_generator_router import _generate_steps, GenerateRequest, StepItem

# condition alani hic olmayan eski tip StepItem (default degerlerle)
req = GenerateRequest(platform='web', steps_list=[
    StepItem(type='text', content='\"Giris\" tikla'),
    StepItem(type='text', content='\"Basarili\" gorunmeli'),
])
code, report = asyncio.run(_generate_steps(req))
compile(code, '<legacy>', 'exec')
assert '_cond_' not in code
print('LEGACY OK')
"
```
Expected: `LEGACY OK`.

- [ ] **Step 3: Manuel uçtan uca — gerçek bir platformda çalıştır**

Elinizde çalışan bir Appium (mobile) ya da tarayıcı (web) hedefi varsa: `ai-generator.html` üzerinde gerçek bir `image_exists` veya `element_exists` condition senaryosu kurup **"▶ Çalıştır"** ile gerçekten koşturun; SSE log akışında `STEP_START`/`STEP_DONE` sıralamasının IF/ELSE dalına göre doğru göründüğünü ve script'in hatasız bittiğini doğrulayın.

- [ ] **Step 4: Spec'teki Test Planı maddelerini tek tek işaretle**

`docs/superpowers/specs/2026-07-24-ai-generator-if-else-design.md` içindeki "Test Planı" bölümünün 1-9 maddelerini bu plan boyunca yapılan doğrulamalarla eşleştir, karşılığı olmayan varsa (ör. madde 3 "element_exists hem mobile hem web'de") o platform için Step 1-3'ü tekrarla.

- [ ] **Step 5: Son commit**

```bash
cd "C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi" && git add -A && git status
```
(Sadece `backend/routers/ai_test_generator_router.py`, `backend/WebArayuz/ai-generator.html` ve bu plan/spec dosyalarının değiştiğini doğrulayıp commit et.)
```bash
git commit -m "AI Test Generator: if/else ozelligi ucbir platformda dogrulandi"
```
