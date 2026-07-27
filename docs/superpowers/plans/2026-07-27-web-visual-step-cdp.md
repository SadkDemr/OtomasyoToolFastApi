# Web Visual Step CDP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Hibrit Adım Editörü's visual/OpenCV steps (assert, point-click, drag, `image_exists` condition) work for Web scenarios run on headless Chrome/Edge, by matching against the browser's own screenshot and clicking via Chrome DevTools Protocol instead of OS-level screen capture. Firefox gets a clear, immediate error for visual steps instead of a silent 10s timeout.

**Architecture:** All changes live in `backend/routers/ai_test_generator_router.py`. A new helper string block (`IMAGE_HELPER_WEB_CDP`) is embedded only in the Web template for Chrome/Edge, alongside the existing `IMAGE_HELPER`. The four code-generation functions that currently pick `_find_b64_on_screen` vs `_find_b64_on_screen_web` by `platform` alone now also take `browser` and pick a third path (the new CDP helpers) for `platform=="web" and browser in ("chrome","edge")`, and raise immediately for `platform=="web" and browser=="firefox"`.

**Tech Stack:** FastAPI + Selenium 4.15.2 (Python 3.12). No build step, no automated test framework in this repo.

## Global Constraints

- Desktop's code path (`platform == "desktop"`) must not change at all — every one of the four dispatch functions' desktop branch stays byte-identical.
- The new CDP-based helpers must not require any new pip dependency — `driver.execute_cdp_cmd` and `driver.get_screenshot_as_png` are already part of Selenium 4.15.2 (the project's pinned version).
- Firefox + a visual step must fail fast with a clear Turkish message, not attempt OS-screen matching (which is guaranteed to fail silently for ~10s in headless mode).
- No automated test framework exists in this repo — verification is a standalone script that calls the code-generation functions directly with constructed `StepItem`s and asserts on the generated Python source string (e.g. `"_cdp_click" in code`), plus `ast.parse()` to confirm the generated snippets are syntactically valid Python once embedded in a minimal wrapper.
- UI/comment text is Turkish, matching the rest of the file.

---

### Task 1: New `IMAGE_HELPER_WEB_CDP` block + embed in the Web template

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`

**Interfaces:**
- Produces: a new module-level string constant `IMAGE_HELPER_WEB_CDP`, defined right after `IMAGE_HELPER`'s closing `'''` (currently `IMAGE_HELPER` ends at line 1738, `DESKTOP_HELPER` begins at line 1741 — insert the new block between them, before `DESKTOP_HELPER`). Inside the generated script, it defines: `_find_image_in_page(driver, target_path, threshold=0.80, return_bbox=False)`, `_cdp_click(driver, x, y, button="left", click_count=1)`, `_cdp_drag(driver, x1, y1, x2, y2, steps=10)`, `_find_b64_in_page_web(driver, b64_data, threshold=0.80, timeout=10)`, `_find_b64_and_click_point_web(driver, b64_data, click_x, click_y, action="click", threshold=0.80, timeout=10)`, `_find_b64_and_drag_web(driver, b64_data, x1, y1, x2, y2, drag_duration=0.4, threshold=0.80, timeout=10)`. These rely on `_bbox_click_point`, `_ib64`, `_itmp`, `_ios`, `_itime` already defined by the preceding `IMAGE_HELPER` block in the same generated script — do not redefine them.
- Consumes (Task 2): Task 2's code-generation changes call these six function names by name in generated Python source (as f-string text, not direct Python calls — this file generates Python source code as strings).

- [ ] **Step 1: Write the failing verification script**

Create `backend/scripts/verify_web_cdp_helper.py`:

```python
"""Gecici dogrulama scripti — IMAGE_HELPER_WEB_CDP ve _build_web_template embed'i icin.
pytest yok; calistirma: `python scripts/verify_web_cdp_helper.py` (backend/ dizininden)."""
import sys
sys.path.insert(0, ".")

from routers.ai_test_generator_router import IMAGE_HELPER_WEB_CDP, GenerateRequest, _build_web_template

def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)

# ── Blok icerigi ──────────────────────────────────────────────────────────
for fn_name in (
    "_find_image_in_page", "_cdp_click", "_cdp_drag",
    "_find_b64_in_page_web", "_find_b64_and_click_point_web", "_find_b64_and_drag_web",
):
    check(f"IMAGE_HELPER_WEB_CDP tanimliyor: {fn_name}", f"def {fn_name}(" in IMAGE_HELPER_WEB_CDP)

check("get_screenshot_as_png kullaniliyor (OS ekrani degil)",
      "get_screenshot_as_png" in IMAGE_HELPER_WEB_CDP)
check("execute_cdp_cmd kullaniliyor (gercek fareye dokunmuyor)",
      "execute_cdp_cmd" in IMAGE_HELPER_WEB_CDP)
check("pyautogui KULLANILMIYOR (headless-safe olmali)",
      "pyautogui" not in IMAGE_HELPER_WEB_CDP)

# ── _build_web_template embed mantigi ────────────────────────────────────
req_chrome = GenerateRequest(steps_list=[], platform="web", browser="chrome", target_url="https://example.com")
script_chrome = _build_web_template(req_chrome, "pass")
check("Chrome scriptinde IMAGE_HELPER_WEB_CDP gomulu", "_find_image_in_page" in script_chrome)

req_edge = GenerateRequest(steps_list=[], platform="web", browser="edge", target_url="https://example.com")
script_edge = _build_web_template(req_edge, "pass")
check("Edge scriptinde IMAGE_HELPER_WEB_CDP gomulu", "_find_image_in_page" in script_edge)

req_firefox = GenerateRequest(steps_list=[], platform="web", browser="firefox", target_url="https://example.com")
script_firefox = _build_web_template(req_firefox, "pass")
check("Firefox scriptinde IMAGE_HELPER_WEB_CDP GOMULU DEGIL", "_find_image_in_page" not in script_firefox)

print("\nTUM KONTROLLER GECTI")
```

- [ ] **Step 2: Run it, confirm it fails**

Run (from `backend/` directory):
```bash
python scripts/verify_web_cdp_helper.py
```
Expected: `ImportError: cannot import name 'IMAGE_HELPER_WEB_CDP' from 'routers.ai_test_generator_router'`

- [ ] **Step 3: Add the `IMAGE_HELPER_WEB_CDP` block**

In `backend/routers/ai_test_generator_router.py`, insert this new constant immediately after `IMAGE_HELPER`'s closing `'''` (i.e. right before the `DESKTOP_HELPER = '''` line):

```python
IMAGE_HELPER_WEB_CDP = '''
def _find_image_in_page(driver, target_path, threshold=0.80, return_bbox=False):
    """Chrome/Edge (CDP) icin: OS ekrani degil, sayfanin KENDI screenshot'ini kullanir.
    Headless'ta da calisir, paralel tarayicilar birbirini etkilemez (her biri sadece
    kendi render buffer'ini gorur)."""
    try:
        import cv2 as _cv2w, numpy as _npw, io as _iiow
        from PIL import Image as _PILW
        _png = driver.get_screenshot_as_png()
        _img = _PILW.open(_iiow.BytesIO(_png)).convert("RGB")
        _screen = _npw.array(_img)
        _screen_bgr = _cv2w.cvtColor(_screen, _cv2w.COLOR_RGB2BGR)
        _screen_gray = _cv2w.cvtColor(_screen_bgr, _cv2w.COLOR_BGR2GRAY)
        _screen_gray = _cv2w.GaussianBlur(_screen_gray, (3, 3), 0)
        _tmpl_bgr = _cv2w.imread(target_path)
        if _tmpl_bgr is None:
            return None
        _tmpl_gray = _cv2w.cvtColor(_tmpl_bgr, _cv2w.COLOR_BGR2GRAY)
        _tmpl_gray = _cv2w.GaussianBlur(_tmpl_gray, (3, 3), 0)
        _h, _w = _tmpl_gray.shape[:2]
        _best = None
        _best_val = -1
        for _sc in _npw.linspace(0.6, 1.7, 25):
            _rw, _rh = int(_w * _sc), int(_h * _sc)
            if _rw < 8 or _rh < 8:
                continue
            if _rw > _screen_gray.shape[1] or _rh > _screen_gray.shape[0]:
                continue
            _res = _cv2w.matchTemplate(_screen_gray, _cv2w.resize(_tmpl_gray, (_rw, _rh)), _cv2w.TM_CCOEFF_NORMED)
            _, _val, _, _loc = _cv2w.minMaxLoc(_res)
            if _val > _best_val:
                _best_val = _val
                _best = (_loc, _rw, _rh)
        if _best_val >= threshold and _best:
            _loc, _rw, _rh = _best
            if return_bbox:
                return (_loc[0], _loc[1], _rw, _rh)
            return (_loc[0] + _rw // 2, _loc[1] + _rh // 2)
    except Exception as _e:
        print(f"[WARN] Sayfa goruntusunde gorsel arama hatasi: {_e}")
    return None


def _cdp_click(driver, x, y, button="left", click_count=1):
    """Gercek OS faresine dokunmadan, tarayicinin icine dogrudan mouse event basar."""
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": x, "y": y,
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": click_count,
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": click_count,
    })


def _cdp_drag(driver, x1, y1, x2, y2, steps=10):
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1})
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1,
    })
    for _i in range(1, steps + 1):
        _ix = x1 + (x2 - x1) * _i / steps
        _iy = y1 + (y2 - y1) * _i / steps
        driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": _ix, "y": _iy, "buttons": 1,
        })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1,
    })


def _find_b64_in_page_web(driver, b64_data, threshold=0.80, timeout=10):
    """Base64 gorseli sayfa screenshot'unda arar (Chrome/Edge, CDP tabanli)."""
    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_find_web_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))
        _start = _itime.time()
        while _itime.time() - _start < timeout:
            _elapsed = _itime.time() - _start
            _conf = max(0.50, threshold - (_elapsed / timeout) * 0.30)
            _coords = _find_image_in_page(driver, _tmp_path, threshold=_conf)
            if _coords:
                return _coords
            _itime.sleep(0.3)
        print(f"[DEBUG] Gorsel {timeout}s icinde bulunamadi (sayfa goruntusu).")
        return None
    finally:
        try:
            _ios.unlink(_tmp_path)
        except Exception:
            pass


def _find_b64_and_click_point_web(driver, b64_data, click_x, click_y, action="click", threshold=0.80, timeout=10):
    """Kirpilmis referans gorseli sayfa screenshot'unda bulur, gorsel icindeki (click_x, click_y)
    noktasini eslesen alana gore CDP ile tiklar."""
    import io as _iiowc
    try:
        from PIL import Image as _PILWC
        _pil = _PILWC.open(_iiowc.BytesIO(_ib64.b64decode(b64_data)))
        _orig_w, _orig_h = _pil.size
    except Exception as _pe:
        print(f"[WARN] Gorsel boyutu alinamiyor: {_pe}")
        return False

    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_click_web_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))
        _start = _itime.time()
        while _itime.time() - _start < timeout:
            _elapsed = _itime.time() - _start
            _conf = max(0.50, threshold - (_elapsed / timeout) * 0.30)
            _bbox = _find_image_in_page(driver, _tmp_path, threshold=_conf, return_bbox=True)
            if _bbox:
                _abs_x, _abs_y = _bbox_click_point(_bbox, click_x, click_y, _orig_w, _orig_h)
                _btn = "right" if action == "right_click" else "left"
                _cnt = 2 if action == "double_click" else 1
                _cdp_click(driver, _abs_x, _abs_y, button=_btn, click_count=_cnt)
                print(f"[OK] Nokta tiklandi (Selenium CDP): ({_abs_x}, {_abs_y})")
                return True
            _itime.sleep(0.3)
        print(f"[DEBUG] Gorsel {timeout}s icinde bulunamadi (sayfa goruntusu) — nokta tiklanamadi.")
        return False
    finally:
        try:
            _ios.unlink(_tmp_path)
        except Exception:
            pass


def _find_b64_and_drag_web(driver, b64_data, x1, y1, x2, y2, drag_duration=0.4, threshold=0.80, timeout=10):
    import io as _iiowd
    try:
        from PIL import Image as _PILWD
        _pil2 = _PILWD.open(_iiowd.BytesIO(_ib64.b64decode(b64_data)))
        _orig_w, _orig_h = _pil2.size
    except Exception as _pe2:
        print(f"[WARN] Gorsel boyutu alinamiyor: {_pe2}")
        return False

    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_drag_web_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))
        _start = _itime.time()
        while _itime.time() - _start < timeout:
            _elapsed = _itime.time() - _start
            _conf = max(0.50, threshold - (_elapsed / timeout) * 0.30)
            _bbox = _find_image_in_page(driver, _tmp_path, threshold=_conf, return_bbox=True)
            if _bbox:
                _ax1, _ay1 = _bbox_click_point(_bbox, x1, y1, _orig_w, _orig_h)
                _ax2, _ay2 = _bbox_click_point(_bbox, x2, y2, _orig_w, _orig_h)
                _cdp_drag(driver, _ax1, _ay1, _ax2, _ay2)
                print(f"[OK] Suruklendi (sayfa goruntusu): ({_ax1},{_ay1}) -> ({_ax2},{_ay2})")
                return True
            _itime.sleep(0.3)
        print(f"[DEBUG] Gorsel {timeout}s icinde bulunamadi (sayfa goruntusu) — surukleme yapilamadi.")
        return False
    finally:
        try:
            _ios.unlink(_tmp_path)
        except Exception:
            pass
'''
```

- [ ] **Step 4: Embed the block in `_build_web_template` for Chrome/Edge**

`_build_web_template` (starts at line 2386) has TWO places where `STOP_HELPER, IMAGE_HELPER, VISION_HELPER_WEB,` are embedded as a list of lines: inside the `if session_mode in ("attach", "end"):` branch (currently around line 2416-2418) and in the main `fresh`/`start` branch (currently around line 2512-2514). In BOTH places, replace:

```python
        STOP_HELPER,
        IMAGE_HELPER,
        VISION_HELPER_WEB,
```

with:

```python
        STOP_HELPER,
        IMAGE_HELPER,
        (IMAGE_HELPER_WEB_CDP if browser in ("chrome", "edge") else ""),
        VISION_HELPER_WEB,
```

(`browser` is already computed at the top of `_build_web_template`, line 2394: `browser = (req.browser or "chrome").lower()` — it is in scope at both embed points.)

- [ ] **Step 5: Run the verification script again, confirm it passes**

```bash
python scripts/verify_web_cdp_helper.py
```
Expected: every line `[OK] ...`, ending with `TUM KONTROLLER GECTI`.

- [ ] **Step 6: Delete the scratch verification script**

```bash
rm backend/scripts/verify_web_cdp_helper.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "web-visual: Chrome/Edge icin sayfa screenshot + CDP tabanli gorsel yardimci blok"
```

---

### Task 2: Thread `browser` through the visual-step code generators

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`

**Interfaces:**
- Consumes: the six function names Task 1 added to `IMAGE_HELPER_WEB_CDP` (`_find_image_in_page`, `_cdp_click`, `_cdp_drag`, `_find_b64_in_page_web`, `_find_b64_and_click_point_web`, `_find_b64_and_drag_web`) — referenced here only as strings inside generated Python source, never called directly from this Python module.
- Produces: `_image_click_code(idx, desc, b64, click_x, click_y, action, platform, browser="")` — **signature changed**, gains `browser`. `_image_step_code(item, platform, idx, browser="")` — **signature changed**, gains `browser`. `_condition_expr(item, platform, idx, browser="")` — **signature changed**, gains `browser`. `_steps_to_code(items, platform, counter, rule_fn, indent="", browser="")` — **signature changed**, gains `browser`, threads it to its own recursive calls.

- [ ] **Step 1: Replace `_image_click_code`**

Replace the existing function (currently lines 2749-2792):

```python
def _image_click_code(idx: int, desc: str, b64: str, click_x: int, click_y: int, action: str, platform: str, browser: str = "") -> str:
    """Görsel tıklama adımı için Desktop+Web ortak kod üretir."""
    refocus_line = "    _refocus_window()\n" if platform == "desktop" else ""
    action_str = {"double_click": "double_click", "right_click": "right_click"}.get(action, "click")
    is_web_cdp = platform == "web" and browser in ("chrome", "edge")
    is_web_firefox = platform == "web" and browser not in ("chrome", "edge")

    if click_x >= 0 and click_y >= 0:
        if is_web_firefox:
            return (
                f"# [NOKTA TIKLAMA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"print('STEP_FAIL:{idx}')\n"
                f"raise Exception('Görsel adımlar şu anda Firefox\\'ta desteklenmiyor. Chrome veya Edge kullanın.')"
            )
        click_fn = "_find_b64_and_click_point_web(driver," if is_web_cdp else "_find_b64_and_click_point("
        return (
            f"# [NOKTA TIKLAMA] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"{refocus_line}"
            f"    _img_b64_{idx} = '{b64}'\n"
            f"    _ok_{idx} = {click_fn} _img_b64_{idx}, {click_x}, {click_y}, action='{action_str}')\n"
            f"    if not _ok_{idx}: raise Exception('Nokta tiklanamiyor: {desc}')\n"
            f"    time.sleep(0.5)\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )

    if is_web_firefox:
        return (
            f"# [GÖRSEL TIKLAMA] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"print('STEP_FAIL:{idx}')\n"
            f"raise Exception('Görsel adımlar şu anda Firefox\\'ta desteklenmiyor. Chrome veya Edge kullanın.')"
        )

    if is_web_cdp:
        find_fn = "_find_b64_in_page_web(driver, "
        click_line = {
            "double_click": f"    _cdp_click(driver, _coords_{idx}[0], _coords_{idx}[1], click_count=2)",
            "right_click":  f"    _cdp_click(driver, _coords_{idx}[0], _coords_{idx}[1], button='right')",
        }.get(action, f"    _cdp_click(driver, _coords_{idx}[0], _coords_{idx}[1])")
    else:
        find_fn = "_find_b64_on_screen(" if platform == "desktop" else "_find_b64_on_screen_web("
        click_line = {
            "double_click": f"    import pyautogui as _pag_i; _pag_i.doubleClick(_coords_{idx}[0], _coords_{idx}[1])",
            "right_click":  f"    import pyautogui as _pag_i; _pag_i.rightClick(_coords_{idx}[0], _coords_{idx}[1])",
        }.get(action, f"    _do_robust_click(_coords_{idx}[0], _coords_{idx}[1])")
    return (
        f"# [GÖRSEL TIKLAMA] {desc}\n"
        f"print('STEP_START:{idx}')\n"
        f"try:\n"
        f"{refocus_line}"
        f"    _img_b64_{idx} = '{b64}'\n"
        f"    _coords_{idx} = {find_fn}_img_b64_{idx}, timeout=10)\n"
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
```

- [ ] **Step 2: Replace `_image_step_code`**

Replace the existing function (currently lines 2795-2837):

```python
def _image_step_code(item: "StepItem", platform: str, idx: int, browser: str = "") -> str:
    """Görsel adımı için Python kodu üretir. base64 scripte gömülür."""
    b64  = item.image_b64
    desc = item.content or f"Görsel adım {idx+1}"
    is_web_cdp = platform == "web" and browser in ("chrome", "edge")
    is_web_firefox = platform == "web" and browser not in ("chrome", "edge")

    if item.action == "drag":
        if is_web_firefox:
            return (
                f"# [GÖRSEL SÜRÜKLE] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"print('STEP_FAIL:{idx}')\n"
                f"raise Exception('Görsel adımlar şu anda Firefox\\'ta desteklenmiyor. Chrome veya Edge kullanın.')"
            )
        refocus_line = "    _refocus_window()\n" if platform == "desktop" else ""
        drag_fn = "_find_b64_and_drag_web(driver," if is_web_cdp else "_find_b64_and_drag("
        return (
            f"# [GÖRSEL SÜRÜKLE] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"{refocus_line}"
            f"    _img_b64_{idx} = '{b64}'\n"
            f"    _ok_{idx} = {drag_fn} _img_b64_{idx}, {item.click_x}, {item.click_y}, {item.drag_x}, {item.drag_y})\n"
            f"    if not _ok_{idx}: raise Exception('Surukleme yapilamadi: {desc}')\n"
            f"    time.sleep(0.5)\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )

    if item.action == "assert":
        if is_web_firefox:
            return (
                f"# [GÖRSEL DOĞRULA] {desc}\n"
                f"print('STEP_START:{idx}')\n"
                f"print('STEP_FAIL:{idx}')\n"
                f"raise Exception('Görsel adımlar şu anda Firefox\\'ta desteklenmiyor. Chrome veya Edge kullanın.')"
            )
        refocus_line = "    _refocus_window()\n" if platform == "desktop" else ""
        find_fn = (
            "_find_b64_in_page_web(driver, " if is_web_cdp else
            ("_find_b64_on_screen(" if platform == "desktop" else "_find_b64_on_screen_web(")
        )
        return (
            f"# [GÖRSEL DOĞRULA] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"{refocus_line}"
            f"    _img_b64_{idx} = '{b64}'\n"
            f"    _res_{idx} = {find_fn}_img_b64_{idx}, timeout=8)\n"
            f"    if not _res_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
            f"    print('[OK] Gorsel dogrulandi: {desc}')\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )

    return _image_click_code(idx, desc, b64, item.click_x, item.click_y, item.action, platform, browser)
```

- [ ] **Step 3: Replace `_condition_expr`'s `image_exists` branch**

In `_condition_expr` (currently lines 3185-3207), change the signature and the `image_exists` branch only — everything else in the function (`element_exists`, `variable_compare`, the final `return "False"`) stays exactly as-is:

```python
def _condition_expr(item: "StepItem", platform: str, idx: int, browser: str = "") -> str:
    """Bir condition StepItem'ı, raise etmeyen bool döndüren tek satırlık bir Python ifadesine çevirir."""
    ctype = item.condition_type
    if ctype == "image_exists":
        if platform == "web" and browser in ("chrome", "edge"):
            return f"bool(_find_b64_in_page_web(driver, '{item.image_b64}', timeout=8))"
        if platform == "web":
            return "False  # Gorsel kosullar Firefox'ta desteklenmiyor"
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

(Note: a Firefox `image_exists` condition returns `False` rather than raising, since it's used inline as a boolean expression inside an `if _cond_{idx}:` — raising there would be a bigger behavior change than this task's scope; it deterministically takes the `else` branch, which is a reasonable, safe default for an unsupported condition.)

- [ ] **Step 4: Replace `_steps_to_code`'s signature and its two internal call points**

In `_steps_to_code` (currently lines 3210-3292), change the signature and the three lines that call `_condition_expr`/`_image_step_code`/the recursive `_steps_to_code` calls. Replace:

```python
def _steps_to_code(items: list, platform: str, counter: list, rule_fn, indent: str = "") -> tuple[str, list, list]:
```

with:

```python
def _steps_to_code(items: list, platform: str, counter: list, rule_fn, indent: str = "", browser: str = "") -> tuple[str, list, list]:
```

Replace the `if item.type == "condition":` block's body (currently the `cond_expr = ...` line and the two recursive `_steps_to_code` calls):

```python
        if item.type == "condition":
            cond_expr = _condition_expr(item, platform, idx)
            then_code, then_lines, then_unrec = _steps_to_code(
                item.then_steps, platform, counter, rule_fn, indent + "    ")
            else_code, else_lines, else_unrec = _steps_to_code(
                item.else_steps, platform, counter, rule_fn, indent + "    ")
```

with:

```python
        if item.type == "condition":
            cond_expr = _condition_expr(item, platform, idx, browser)
            then_code, then_lines, then_unrec = _steps_to_code(
                item.then_steps, platform, counter, rule_fn, indent + "    ", browser)
            else_code, else_lines, else_unrec = _steps_to_code(
                item.else_steps, platform, counter, rule_fn, indent + "    ", browser)
```

Replace the `if item.type == "image":` line:

```python
        if item.type == "image":
            code = _indent_code("_check_stop()\n" + _image_step_code(item, platform, idx), indent)
```

with:

```python
        if item.type == "image":
            code = _indent_code("_check_stop()\n" + _image_step_code(item, platform, idx, browser), indent)
```

- [ ] **Step 5: Thread `browser` from `_generate_steps` into `_steps_to_code`, and update `_fill_llm`'s two call sites**

In `_generate_steps` (currently starting at line 3295), replace the line:

```python
    steps_code, code_lines, unrecognized = _steps_to_code(structured, req.platform, counter, rule_fn)
```

with:

```python
    steps_code, code_lines, unrecognized = _steps_to_code(structured, req.platform, counter, rule_fn, browser=req.browser or "")
```

Inside the same function's nested `_fill_llm` closure (currently around lines 3328-3364), replace the two lines:

```python
                cond_expr = _condition_expr(item, req.platform, idx)
```

with:

```python
                cond_expr = _condition_expr(item, req.platform, idx, req.browser or "")
```

and:

```python
                    block  = _indent_code("_check_stop()\n" + _image_step_code(item, req.platform, idx), indent)
```

with:

```python
                    block  = _indent_code("_check_stop()\n" + _image_step_code(item, req.platform, idx, req.browser or ""), indent)
```

(`_fill_llm` is a closure defined inside `_generate_steps`, so `req` is already in scope there — no signature change needed for `_fill_llm` itself, only these two call-site edits.)

- [ ] **Step 6: Write and run a verification script covering all three browsers**

Create `backend/scripts/verify_web_cdp_codegen.py`:

```python
"""Gecici dogrulama scripti — browser-farkinda gorsel adim kod uretimi icin.
Calistirma: `python scripts/verify_web_cdp_codegen.py` (backend/ dizininden)."""
import sys
sys.path.insert(0, ".")
import ast

from routers.ai_test_generator_router import _image_step_code, _condition_expr

class _FakeImageItem:
    type = "image"
    action = "assert"
    image_b64 = "AAAA"
    content = "Test gorseli"
    click_x = -1
    click_y = -1
    drag_x = -1
    drag_y = -1

class _FakeCondItem:
    condition_type = "image_exists"
    image_b64 = "AAAA"

def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)

def _valid_python(snippet: str) -> bool:
    try:
        ast.parse("if True:\n" + "\n".join("    " + l if l.strip() else "" for l in snippet.splitlines()))
        return True
    except SyntaxError as e:
        print("SyntaxError:", e)
        return False

# ── assert adimi ─────────────────────────────────────────────────────────
item = _FakeImageItem()

code_chrome = _image_step_code(item, "web", 0, "chrome")
check("Chrome: _find_b64_in_page_web kullaniliyor", "_find_b64_in_page_web(driver," in code_chrome)
check("Chrome: gecerli Python", _valid_python(code_chrome))

code_edge = _image_step_code(item, "web", 0, "edge")
check("Edge: _find_b64_in_page_web kullaniliyor", "_find_b64_in_page_web(driver," in code_edge)

code_firefox = _image_step_code(item, "web", 0, "firefox")
check("Firefox: acikca desteklenmiyor hatasi", "desteklenmiyor" in code_firefox)
check("Firefox: gecerli Python", _valid_python(code_firefox))

code_desktop = _image_step_code(item, "desktop", 0, "")
check("Desktop: eski _find_b64_on_screen davranisi DEGISMEDI", "_find_b64_on_screen(" in code_desktop and "_find_b64_in_page_web" not in code_desktop)

# ── condition (image_exists) ─────────────────────────────────────────────
cond = _FakeCondItem()
expr_chrome = _condition_expr(cond, "web", 0, "chrome")
check("Condition/Chrome: _find_b64_in_page_web kullaniliyor", "_find_b64_in_page_web(driver," in expr_chrome)

expr_firefox = _condition_expr(cond, "web", 0, "firefox")
check("Condition/Firefox: guvenli False donuyor (raise degil, bool ifade)", expr_firefox.strip().startswith("False"))

expr_desktop = _condition_expr(cond, "desktop", 0, "")
check("Condition/Desktop: DEGISMEDI", "_find_b64_on_screen(" in expr_desktop)

print("\nTUM KONTROLLER GECTI")
```

Run it:
```bash
python scripts/verify_web_cdp_codegen.py
```
Expected: every line `[OK] ...`, ending with `TUM KONTROLLER GECTI`.

- [ ] **Step 7: Delete the scratch verification script**

```bash
rm backend/scripts/verify_web_cdp_codegen.py
```

- [ ] **Step 8: Confirm the whole module still imports cleanly**

```bash
cd backend && python -c "import routers.ai_test_generator_router; print('OK')"
```
Expected: `OK`.

- [ ] **Step 9: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "web-visual: gorsel adim kod uretimi tarayiciya gore CDP/firefox-hata dallansin"
```

---

### Task 3: Manual verification

**Files:** none (verification only)

No automated test framework exists in this repo, and this change's real-world correctness (actual pixel matching against a live headless browser, actual CDP mouse clicks landing on the right element) can only be confirmed against a running server and a real scenario.

- [ ] **Step 1: Start the server**

```bash
cd backend && python main.py
```

- [ ] **Step 2: Re-run the "Finansman_Hesapla" Web scenario (or any Web scenario with a visual step) with Chrome**

Via AI Test Generator's manual "Test Et", and via an AI Job (per the earlier session's Job #1). Confirm the visual step now passes (previously failed with "Görsel bulunamadı").

- [ ] **Step 3: Re-run the same scenario with browser set to Firefox**

Confirm it fails immediately with the "Görsel adımlar şu anda Firefox'ta desteklenmiyor..." message, not a 10-second timeout followed by the old "Gorsel bulunamadi" message.

- [ ] **Step 4: Re-run with Edge if available on this machine**

Confirm the same success as Chrome.
