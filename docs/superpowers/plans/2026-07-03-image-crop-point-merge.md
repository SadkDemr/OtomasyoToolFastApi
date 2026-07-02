# Görsel Adımı: Kırpma + Nokta Seçme Birleştirmesi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Görsel adım eklerken "Bölge Kırp" ve "Nokta İşaretle" modlarını tek bir sıralı akışta
birleştirmek — önce ayırt edici bir alan kırpılır, sonra o kırpılmış alan üzerinde tıklanacak
nokta(lar) işaretlenir; çalışma zamanında kırpılan alan çoklu-ölçek eşleştirmeyle ekranda bulunur
ve işaretlenen nokta bu alana göre mutlak koordinata çevrilip tıklanır.

**Architecture:** Backend'de `_find_image_on_screen`'e `return_bbox` parametresi eklenip eşleşen
alanın dikdörtgenini (merkez yerine) döndürmesi sağlanır; bunun üzerine kurulan yeni
`_find_b64_and_click_point` fonksiyonu hem yeni kırp+nokta adımlarını hem de (geriye dönük
uyumluluk için) eski tam-sayfa-nokta adımlarını aynı formülle çalıştırır. `_image_step_code()`,
Desktop/Web için ayrı yazılmış tıklama mantığını `_image_click_code()` adlı tek bir paylaşılan
fonksiyona indirger. Frontend'de mevcut "Kırp"/"Nokta" sekmeleri kaldırılıp modal 2 aşamalı bir
akışa (Alan Seç → Nokta İşaretle) çevrilir; her iki aşamanın canvas çizim/nokta işaretleme mantığı
büyük ölçüde yeniden kullanılır.

**Tech Stack:** Python (backend, `ai_test_generator_router.py`), OpenCV (`cv2`), `pyautogui`, `PIL`;
düz HTML/JS (`ai-generator.html`, canvas tabanlı kırpma/nokta UI). Test framework yok (proje
genelinde pytest kullanılmıyor); backend doğrulamaları `backend/venv/Scripts/python.exe` ile
çalıştırılan bağımsız kontrol scriptleriyle, frontend doğrulaması manuel tarayıcı testiyle yapılır.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-image-crop-point-merge-design.md` — bu plan o
  tasarımın uygulamasıdır.
- Kapsam sadece **Web + Desktop** platformları — Mobil'de görsel adım UI'da zaten gizli, dokunma.
- Geriye dönük uyumluluk ZORUNLU: eski "sadece kırp" (`click_x=-1`) adımları merkeze tıklamaya
  devam etmeli, eski "tam sayfa nokta" (`click_x>=0`, büyük b64) adımları yeni
  `_find_b64_and_click_point` yoluna düşüp çalışmaya devam etmeli — hiçbiri için ayrı özel-durum
  kodu YAZILMAYACAK, tek bir genel formül ikisini de kapsıyor.
- Proje kökünde boşluk içeren yol var (`C:\Users\Sadik Demir\...`) — tüm komutlarda çift tırnak.
- `_image_step_code()`'un `assert` action dalı DEĞİŞMİYOR (zaten `click_x/y` kullanmıyor).
- Frontend'de yeni CSS kuralı GEREKMİYOR — mevcut `.crop-mode-tab`/`.btn-reset`/`.btn-generate`
  sınıfları yeniden kullanılıyor.

---

### Task 1: Backend — Bölge-eşleşmeli nokta tıklama (`_find_b64_and_click_point`) + WINDOW_TITLE bug fix

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `_find_image_on_screen()` (satır ~1472-1519) — `return_bbox` parametresi
  - `_find_b64_on_screen()` (satır ~1438-1470) — `_WINDOW_TITLE` NameError bug fix
  - IMAGE_HELPER string sonu, `_find_b64_on_screen_web()`'in hemen altı (satır ~1529-1531) — yeni
    `_bbox_click_point` + `_find_b64_and_click_point` fonksiyonları
  - `_find_b64_and_click_at()` (satır ~1652-1710, `DESKTOP_HELPER` içinde) — SİLİNİYOR (artık
    kullanılmıyor)

**Interfaces:**
- Produces: `_find_image_on_screen(target_path, threshold=0.80, region=None, return_bbox=False)`
  — `return_bbox=True` iken `(x, y, w, h)` döner (merkez nokta yerine). `_bbox_click_point(bbox,
  click_x, click_y, orig_w, orig_h) -> (abs_x, abs_y)` — saf koordinat matematiği, ekran erişimi
  yok. `_find_b64_and_click_point(b64_data, click_x, click_y, action="click", threshold=0.80,
  timeout=10) -> bool` — bulur + tıklar.
- Consumes: yok (bağımsız, en alt seviye katman).

**Not:** Bu fonksiyonlar gerçek Python fonksiyonu olarak router modülünde DEĞİL, `IMAGE_HELPER` /
`DESKTOP_HELPER` adlı üçlü-tırnaklı string sabitlerinin İÇİNDE tanımlı — çalışma zamanında
üretilen script'lere metin olarak gömülüyorlar. Bu yüzden doğrudan import edilemezler; kontrol
scriptleri `exec(IMAGE_HELPER, ns)` ile bir namespace'e yükleyip oradan çağıracak.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_bbox_click.py`:

```python
import sys, base64, io
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import IMAGE_HELPER
from PIL import Image

ns = {}
exec(IMAGE_HELPER, ns)

# 1. Saf koordinat matematigi: bbox + orijinal-piksel nokta -> mutlak ekran noktasi
assert ns["_bbox_click_point"]((100, 200, 50, 40), 25, 20, 50, 40) == (125, 220), \
    "FAIL: 1:1 olcekte bbox+point hesaplamasi yanlis"
assert ns["_bbox_click_point"]((0, 0, 100, 80), 25, 20, 50, 40) == (50, 40), \
    "FAIL: 2x buyutulmus bbox'ta normalize nokta hesaplamasi yanlis"

# 2. WINDOW_TITLE bug fix: _WINDOW_TITLE hic tanimli degilken (Web script'i simule eder)
#    _find_b64_on_screen NameError firlatmamali.
buf = io.BytesIO()
Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="PNG")
tiny_b64 = base64.b64encode(buf.getvalue()).decode()

try:
    ns["_find_b64_on_screen"](tiny_b64, threshold=0.9, timeout=1)
except NameError as e:
    raise AssertionError(f"FAIL: _WINDOW_TITLE tanimsizken NameError firladi (bug hala var): {e}")

# 3. _find_b64_and_click_point fonksiyonu namespace'te tanimli ve cagrilabilir olmali
assert callable(ns.get("_find_b64_and_click_point")), "FAIL: _find_b64_and_click_point tanimli degil"

print("OK")
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_bbox_click.py yolu>`
Expected: `KeyError: '_bbox_click_point'` (henüz tanımlı değil) — veya `_find_b64_on_screen`
çağrısında `NameError: name '_WINDOW_TITLE' is not defined` (bug fix'ten önce).

- [ ] **Step 3: `_find_image_on_screen`'e `return_bbox` parametresi ekle**

Öncesi (satır ~1472-1519, imza + dönüş satırları):
```python
def _find_image_on_screen(target_path, threshold=0.80, region=None):
    """OpenCV multi-scale template matching. region=(x,y,w,h) ile kısıtlı arama yapar."""
```
Sonrası:
```python
def _find_image_on_screen(target_path, threshold=0.80, region=None, return_bbox=False):
    """OpenCV multi-scale template matching. region=(x,y,w,h) ile kısıtlı arama yapar.
    return_bbox=True ise merkez nokta yerine eslesen alanin (x,y,w,h) dikdortgenini dondurur."""
```

Öncesi (dönüş satırları, `try` bloğunun sonu):
```python
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
```
Sonrası:
```python
        if _best_val >= threshold and _best:
            _loc, _rw, _rh = _best
            if return_bbox:
                return (_loc[0] + _ox, _loc[1] + _oy, _rw, _rh)
            return (_loc[0] + _rw//2 + _ox, _loc[1] + _rh//2 + _oy)
    except ImportError:
        try:
            import pyautogui as _pag2
            _loc2 = _pag2.locateOnScreen(target_path, grayscale=True,
                                          confidence=min(0.8, threshold), region=region)
            if _loc2:
                if return_bbox:
                    return (_loc2.left, _loc2.top, _loc2.width, _loc2.height)
                return (_pag2.center(_loc2).x, _pag2.center(_loc2).y)
        except Exception: pass
    except Exception: pass
    return None
```

- [ ] **Step 4: `_find_b64_on_screen`'deki çıplak `_WINDOW_TITLE` referanslarını güvenli hale getir**

Öncesi (satır ~1438-1470):
```python
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
```
Sonrası (`_WINDOW_TITLE` erişimleri `_wt_set` değişkenine taşınıyor — Web script'lerinde bu
değişken hiç tanımlı olmadığı için `globals()` üzerinden güvenli kontrol ediliyor):
```python
def _find_b64_on_screen(b64_data, threshold=0.80, timeout=10):
    """Base64 gorsel arar — _WINDOW_TITLE varsa yalnizca o pencere icinde."""
    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_find_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))
        # Pencere bolgesi — _WINDOW_TITLE varsa (Desktop) tam ekran aramaz. Web script'lerinde
        # _WINDOW_TITLE hic tanimli olmadigi icin globals() ile guvenli kontrol edilir.
        _wt_set = '_WINDOW_TITLE' in globals() and bool(_WINDOW_TITLE)
        _region = _get_window_region()
        if _wt_set and _region is None:
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
            if _wt_set:
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
```

- [ ] **Step 5: `_bbox_click_point` + `_find_b64_and_click_point`'i `_find_b64_on_screen_web`'in altına ekle**

Öncesi (satır ~1529-1532, IMAGE_HELPER'ın sonu):
```python
def _find_b64_on_screen_web(b64_data, threshold=0.80, timeout=10):
    """Web için: görseli ekranda ara (pencere kısıtlaması olmadan)."""
    return _find_b64_on_screen(b64_data, threshold=threshold, timeout=timeout)
'''
```
Sonrası:
```python
def _find_b64_on_screen_web(b64_data, threshold=0.80, timeout=10):
    """Web için: görseli ekranda ara (pencere kısıtlaması olmadan)."""
    return _find_b64_on_screen(b64_data, threshold=threshold, timeout=timeout)

def _bbox_click_point(bbox, click_x, click_y, orig_w, orig_h):
    """bbox=(x,y,w,h) eslesen ekran alani; click_x/click_y kirpilan/tam gorseldeki orijinal
    piksel nokta; orig_w/orig_h o gorselin boyutu. Mutlak ekran (x,y) dondurur."""
    _norm_x = click_x / orig_w
    _norm_y = click_y / orig_h
    _bx, _by, _bw, _bh = bbox
    return (int(_bx + _norm_x * _bw), int(_by + _norm_y * _bh))

def _find_b64_and_click_point(b64_data, click_x, click_y, action="click", threshold=0.80, timeout=10):
    """Base64 gorseli (kirpilmis alan veya eski tam sayfa) ekranda coklu-olcek eslestirmeyle
    bulur, gorsel icindeki (click_x, click_y) orijinal piksel noktasini eslesen alana gore
    mutlak ekran koordinatina cevirip tiklar."""
    import io as _iio3
    try:
        from PIL import Image as _PILY
        _pil = _PILY.open(_iio3.BytesIO(_ib64.b64decode(b64_data)))
        _orig_w, _orig_h = _pil.size
    except Exception as _pe:
        print(f"[WARN] Gorsel boyutu alinamiyor: {_pe}")
        return False

    _tmp_path = _ios.path.join(_itmp.gettempdir(), f"_img_click_{id(b64_data)}.png")
    try:
        with open(_tmp_path, "wb") as _f:
            _f.write(_ib64.b64decode(b64_data))

        _wt_set = '_WINDOW_TITLE' in globals() and bool(_WINDOW_TITLE)
        _region = _get_window_region() if _wt_set else None

        _start = _itime.time()
        while _itime.time() - _start < timeout:
            _elapsed = _itime.time() - _start
            _conf = max(0.50, threshold - (_elapsed / timeout) * 0.30)
            _bbox = _find_image_on_screen(_tmp_path, threshold=_conf, region=_region, return_bbox=True)
            if _bbox:
                _abs_x, _abs_y = _bbox_click_point(_bbox, click_x, click_y, _orig_w, _orig_h)
                import pyautogui as _pag4
                if action == "double_click":
                    _pag4.doubleClick(_abs_x, _abs_y)
                elif action == "right_click":
                    _pag4.rightClick(_abs_x, _abs_y)
                else:
                    _pag4.click(_abs_x, _abs_y)
                print(f"[OK] Nokta tiklandi (bolge esleme): ({_abs_x}, {_abs_y})")
                return True
            _itime.sleep(0.3)
        print(f"[DEBUG] Gorsel {timeout}s icinde bulunamadi — nokta tiklanamadi.")
        return False
    finally:
        try: _ios.unlink(_tmp_path)
        except Exception: pass
'''
```

- [ ] **Step 6: Eski `_find_b64_and_click_at`'i sil**

`_in_window()` fonksiyonunun hemen altında (satır ~1652-1712). Öncesi:
```python
def _find_b64_and_click_at(b64, click_x, click_y, action="click"):
    """Tam ekran gorsel + orijinal piksel koordinati ile tiklama.
    - Gorseli locateOnScreen ile ekranda bul; koordinati normalize edip uygula.
    - Bulamazsa pencere bolgesi + normalize koordinat ile dogrudan tikla.
    Bu sayede ayni toggle/butondan birden fazla varsa tam ekran bağlamı dogru olanı secer.
    """
    import tempfile as _itmp2, os as _ios2, io as _iio2
    try:
        from PIL import Image as _PILX
        _pil = _PILX.open(_iio2.BytesIO(_b64.b64decode(b64)))
        _orig_w, _orig_h = _pil.size
    except Exception as _pe:
        print(f"[WARN] Gorsel boyutu alinamiyor: {_pe}")
        return False

    _norm_x = click_x / _orig_w
    _norm_y = click_y / _orig_h
    _wr = _get_window_region()

    def _do_click(ax, ay):
        if action == "double_click":
            _pag.doubleClick(ax, ay)
        elif action == "right_click":
            _pag.rightClick(ax, ay)
        else:
            _pag.click(ax, ay)

    # 1. locateOnScreen ile tam ekranı bul
    _tmp_path = None
    try:
        _fd, _tmp_path = _itmp2.mkstemp(suffix=".png")
        with _ios2.fdopen(_fd, "wb") as _f:
            _f.write(_b64.b64decode(b64))
        _loc = _pag.locateOnScreen(_tmp_path, confidence=0.6, region=_wr)
        if _loc:
            _abs_x = int(_loc.left + _norm_x * _loc.width)
            _abs_y = int(_loc.top  + _norm_y * _loc.height)
            if _in_window(_abs_x, _abs_y):
                _do_click(_abs_x, _abs_y)
                print(f"[OK] Nokta tiklandi (tam ekran esleme): ({_abs_x}, {_abs_y})")
                return True
    except Exception as _le:
        print(f"[WARN] locateOnScreen hatasi: {_le}")
    finally:
        if _tmp_path:
            try: _ios2.unlink(_tmp_path)
            except: pass

    # 2. Fallback: pencere bolgesi + normalize koordinat
    if _wr:
        _abs_x = int(_wr[0] + _norm_x * _wr[2])
        _abs_y = int(_wr[1] + _norm_y * _wr[3])
        if _in_window(_abs_x, _abs_y):
            _do_click(_abs_x, _abs_y)
            print(f"[OK] Nokta tiklandi (pencere orani): ({_abs_x}, {_abs_y})")
            return True

    print(f"[FAIL] Nokta tiklanamiyor — norm ({_norm_x:.3f}, {_norm_y:.3f})")
    return False


def _get_active_window():
```
Sonrası:
```python
def _get_active_window():
```

- [ ] **Step 7: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: bolge-eslesmeli nokta tiklama + Web WINDOW_TITLE NameError bug fix"
```

---

### Task 2: Backend — `_image_step_code()` Desktop/Web birleştirmesi

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `StepItem.click_x`/`click_y` docstring (satır ~134-135)
  - `_image_step_code()` (satır ~2590-2691) — tamamen yeniden yazılıyor, yeni yardımcı
    `_image_click_code()` fonksiyonu ekleniyor

**Interfaces:**
- Consumes: Task 1'in `_find_b64_and_click_point` (IMAGE_HELPER içinde, üretilen script'e gömülü
  olarak çağrılır — bu task import ETMEZ, sadece string kod üretir).
- Produces: `_image_click_code(idx: int, desc: str, b64: str, click_x: int, click_y: int,
  action: str, platform: str) -> str` — hem Desktop hem Web için ortak tıklama kodu üretir.
  `_image_step_code()` imzası DEĞİŞMİYOR (`item, platform, idx` aynı kalır), sadece iç
  implementasyonu sadeleşiyor.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_image_step_unify.py`:

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _image_step_code, StepItem

# 1. Nokta modu (click_x/y >= 0) - hem Desktop hem Web AYNI yeni fonksiyonu kullanmali
item = StepItem(type="image", content="Test nokta", image_b64="AAAA", action="click", click_x=12, click_y=34)
code_desktop = _image_step_code(item, "desktop", 0)
code_web     = _image_step_code(item, "web", 0)
assert "_find_b64_and_click_point(_img_b64_0, 12, 34, action='click')" in code_desktop, code_desktop
assert "_find_b64_and_click_point(_img_b64_0, 12, 34, action='click')" in code_web, code_web
assert "_refocus_window()" in code_desktop, "FAIL: Desktop dalinda _refocus_window() olmali"
assert "_refocus_window()" not in code_web, "FAIL: Web dalinda _refocus_window() OLMAMALI"

# 2. Kirp-only mod (click_x=-1) - geriye donuk uyumluluk, merkeze tiklama, HER IKI platformda da
item2 = StepItem(type="image", content="Test kirp", image_b64="AAAA", action="click", click_x=-1, click_y=-1)
code_d2 = _image_step_code(item2, "desktop", 1)
code_w2 = _image_step_code(item2, "web", 1)
assert "_find_b64_on_screen(_img_b64_1" in code_d2 and "_find_b64_and_click_point" not in code_d2, code_d2
assert "_find_b64_on_screen_web(_img_b64_1" in code_w2 and "_find_b64_and_click_point" not in code_w2, code_w2

# 3. Assert modu degismemeli
item3 = StepItem(type="image", content="Test assert", image_b64="AAAA", action="assert")
code_d3 = _image_step_code(item3, "desktop", 2)
code_w3 = _image_step_code(item3, "web", 2)
assert "_find_b64_on_screen(_img_b64_2" in code_d3 and "GÖRSEL DOĞRULA" in code_d3, code_d3
assert "_find_b64_on_screen_web(_img_b64_2" in code_w3 and "GÖRSEL DOĞRULA" in code_w3, code_w3

print("OK")
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_image_step_unify.py yolu>`
Expected: `AssertionError` (Web dalı şu an `click_x` hiç kontrol etmiyor, `_find_b64_and_click_point`
hiçbir dalda çağrılmıyor).

- [ ] **Step 3: `StepItem.click_x`/`click_y` docstring'ini güncelle**

Öncesi (satır ~134-135):
```python
    click_x:       int = -1       # >= 0 ise locateOnScreen yerine doğrudan koordinat kullanılır
    click_y:       int = -1
```
Sonrası:
```python
    click_x:       int = -1       # >= 0 ise kırpılan/tam görsele göre nokta tıklaması kullanılır
    click_y:       int = -1       # (coklu-olcek eslestirme + normalize nokta, bkz. _find_b64_and_click_point)
```

- [ ] **Step 4: `_image_click_code()` yardımcı fonksiyonunu `_image_step_code()`'un hemen üstüne ekle**

`_image_step_code` fonksiyonunun (satır ~2590) hemen ÜSTÜNE ekle:

```python
def _image_click_code(idx: int, desc: str, b64: str, click_x: int, click_y: int, action: str, platform: str) -> str:
    """Görsel tıklama adımı için Desktop+Web ortak kod üretir."""
    refocus_line = "    _refocus_window()\n" if platform == "desktop" else ""
    action_str = {"double_click": "double_click", "right_click": "right_click"}.get(action, "click")

    if click_x >= 0 and click_y >= 0:
        return (
            f"# [NOKTA TIKLAMA] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"{refocus_line}"
            f"    _img_b64_{idx} = '{b64}'\n"
            f"    _ok_{idx} = _find_b64_and_click_point(_img_b64_{idx}, {click_x}, {click_y}, action='{action_str}')\n"
            f"    if not _ok_{idx}: raise Exception('Nokta tiklanamiyor: {desc}')\n"
            f"    time.sleep(0.5)\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )

    find_fn = "_find_b64_on_screen" if platform == "desktop" else "_find_b64_on_screen_web"
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
        f"    _coords_{idx} = {find_fn}(_img_b64_{idx}, timeout=10)\n"
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

- [ ] **Step 5: `_image_step_code()`'u sadeleştir**

Öncesi (satır ~2590-2691, tüm fonksiyon gövdesi — Desktop/Web için ayrı ayrı assert+tıklama
dalları):
```python
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
            cx, cy = item.click_x, item.click_y
            if cx >= 0 and cy >= 0:
                # Nokta İşaretle modu: tam ekran + orijinal piksel koordinatı
                action_str = {"double_click": "double_click", "right_click": "right_click"}.get(item.action, "click")
                return (
                    f"# [NOKTA TIKLAMA] {desc}\n"
                    f"print('STEP_START:{idx}')\n"
                    f"try:\n"
                    f"    _refocus_window()\n"
                    f"    _img_b64_{idx} = '{b64}'\n"
                    f"    _ok_{idx} = _find_b64_and_click_at(_img_b64_{idx}, {cx}, {cy}, action='{action_str}')\n"
                    f"    if not _ok_{idx}: raise Exception('Nokta tiklanamiyor: {desc}')\n"
                    f"    time.sleep(0.5)\n"
                    f"    print('STEP_DONE:{idx}')\n"
                    f"except Exception as _e_{idx}:\n"
                    f"    print(f'[FAIL] {{_e_{idx}}}')\n"
                    f"    print('STEP_FAIL:{idx}')\n"
                    f"    raise"
                )
            else:
                # Bölge Kırp modu: kırpılmış görsel → locateOnScreen ile ekranda bul
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
```
Sonrası:
```python
def _image_step_code(item: "StepItem", platform: str, idx: int) -> str:
    """Görsel adımı için Python kodu üretir. base64 scripte gömülür."""
    b64  = item.image_b64
    desc = item.content or f"Görsel adım {idx+1}"

    if item.action == "assert":
        find_fn = "_find_b64_on_screen" if platform == "desktop" else "_find_b64_on_screen_web"
        refocus_line = "    _refocus_window()\n" if platform == "desktop" else ""
        return (
            f"# [GÖRSEL DOĞRULA] {desc}\n"
            f"print('STEP_START:{idx}')\n"
            f"try:\n"
            f"{refocus_line}"
            f"    _img_b64_{idx} = '{b64}'\n"
            f"    _res_{idx} = {find_fn}(_img_b64_{idx}, timeout=8)\n"
            f"    if not _res_{idx}: raise Exception('Gorsel bulunamadi: {desc}')\n"
            f"    print('[OK] Gorsel dogrulandi: {desc}')\n"
            f"    print('STEP_DONE:{idx}')\n"
            f"except Exception as _e_{idx}:\n"
            f"    print(f'[FAIL] {{_e_{idx}}}')\n"
            f"    print('STEP_FAIL:{idx}')\n"
            f"    raise"
        )

    return _image_click_code(idx, desc, b64, item.click_x, item.click_y, item.action, platform)
```

- [ ] **Step 6: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "refactor: _image_step_code Desktop/Web tiklama mantigini birlestir"
```

---

### Task 3: Frontend — Birleşik kırp+nokta modalı

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html`
  - Modal HTML (satır ~1468-1491) — sekmeler kaldırılıyor, "Geri" butonu ekleniyor
  - State değişkenleri (satır ~1603-1604)
  - `showCropModal`, `setModalMode` (satır ~2226-2302) — `_setStage`/`_renderCropStageCanvas` ile
    değiştiriliyor
  - `_drawAllPoints` (satır ~2364-2390) — `_screenImg` → `_croppedImg`
  - `confirmCrop`/`confirmPoints`/`cancelCrop` (satır ~2416-2477) — yeni `goToPointStage`/
    `backToCropStage` + `confirmPoints`/`cancelCrop` güncellemeleri

**Interfaces:**
- Consumes: Task 1/2'nin ürettiği backend davranışı (bu task backend'e HTTP çağrısı yapmıyor,
  sadece `StepItem` şeklinde JSON üretiyor — `click_x/y` artık kırpılan görsele göre).
- Produces: yok (UI-only, script üretimi zaten mevcut `buildPayload()`/`_stepToApiItem()` akışını
  değişmeden kullanıyor).

- [ ] **Step 1: Modal HTML'ini güncelle — sekmeleri kaldır, aşama göstergesi + Geri butonu ekle**

Öncesi (satır ~1468-1473):
```html
        <!-- Mod sekmeleri -->
        <div style="display:flex; gap:6px; align-items:center;">
            <button id="tabCrop" class="crop-mode-tab active" onclick="setModalMode('crop')">✂ Bölge Kırp</button>
            <button id="tabPoint" class="crop-mode-tab" onclick="setModalMode('point')">📍 Nokta İşaretle</button>
            <span id="cropModeHint" style="font-size:0.76rem; color:var(--text-muted); margin-left:6px;">Tıkla ve sürükle → hedef alanı seç</span>
        </div>
```
Sonrası:
```html
        <!-- Aşama göstergesi -->
        <div style="display:flex; gap:6px; align-items:center;">
            <span id="stageLabel" class="crop-mode-tab active">1/2: Alan Seç</span>
            <span id="cropModeHint" style="font-size:0.76rem; color:var(--text-muted); margin-left:6px;">Tıkla ve sürükle → hedef alanı seç</span>
        </div>
```

Öncesi (satır ~1481-1491, footer):
```html
        <div style="display:flex; gap:10px; justify-content:flex-end; align-items:center;">
            <span id="cropSelectionInfo" style="font-size:0.78rem; color:var(--text-muted); flex:1;"></span>
            <button class="btn-reset" onclick="cancelCrop()">İptal</button>
            <button class="btn-generate" id="btnCropConfirm" onclick="confirmCrop()" disabled style="flex:none; padding:10px 20px; display:flex; align-items:center; gap:6px;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                Kırp ve Ekle
            </button>
            <button class="btn-generate" id="btnPointConfirm" onclick="confirmPoints()" disabled style="display:none; flex:none; padding:10px 20px;">
                📍 Noktaları Ekle (0)
            </button>
        </div>
```
Sonrası:
```html
        <div style="display:flex; gap:10px; justify-content:flex-end; align-items:center;">
            <span id="cropSelectionInfo" style="font-size:0.78rem; color:var(--text-muted); flex:1;"></span>
            <button class="btn-reset" onclick="cancelCrop()">İptal</button>
            <button class="btn-reset" id="btnBackToCrop" onclick="backToCropStage()" style="display:none;">← Geri</button>
            <button class="btn-generate" id="btnCropConfirm" onclick="goToPointStage()" disabled style="flex:none; padding:10px 20px; display:flex; align-items:center; gap:6px;">
                İleri: Nokta Seç →
            </button>
            <button class="btn-generate" id="btnPointConfirm" onclick="confirmPoints()" disabled style="display:none; flex:none; padding:10px 20px;">
                📍 Noktaları Ekle (0)
            </button>
        </div>
```

- [ ] **Step 2: State değişkenlerini güncelle**

Öncesi (satır ~1602-1604):
```javascript
    // Nokta işaretle modu
    let _modalMode   = "crop";    // "crop" | "point"
    let _clickPoints = [];        // [{cx, cy, ox, oy}] — canvas + orijinal görsel koordinatları
```
Sonrası:
```javascript
    // Kırp + Nokta akışı (2 aşamalı: "crop" → "point")
    let _stage       = "crop";    // "crop" | "point"
    let _croppedB64  = null;      // Aşama 1'de kırpılan küçük görsel (base64, data: öneki yok)
    let _croppedImg  = null;      // Aynı görselin Image nesnesi (Aşama 2 canvas'ında gösterilir)
    let _clickPoints = [];        // [{cx, cy, ox, oy}] — canvas + kırpılan görsel koordinatları
```

- [ ] **Step 3: `showCropModal`'ı sadeleştir, `_setStage` + `_renderCropStageCanvas` ekle, `setModalMode`'u sil**

Öncesi (satır ~2226-2257, `showCropModal`):
```javascript
    function showCropModal(b64) {
        _cropRect    = null;
        _isDrawing   = false;
        _clickPoints = [];
        _modalMode   = "crop";
        document.getElementById("btnCropConfirm").disabled = true;
        document.getElementById("cropSelectionInfo").textContent = "";
        document.getElementById("cropModal").style.display = "flex";
        // Mod sıfırla
        document.getElementById("tabCrop").classList.add("active");
        document.getElementById("tabPoint").classList.remove("active");
        document.getElementById("btnCropConfirm").style.display = "";
        document.getElementById("btnPointConfirm").style.display = "none";
        document.getElementById("pointsList").style.display = "none";
        document.getElementById("cropModeHint").textContent = "Tıkla ve sürükle → hedef alanı seç";

        const canvas = document.getElementById("cropCanvas");
        const ctx    = canvas.getContext("2d");

        _screenImg = new Image();
        _screenImg.onload = function() {
            const maxW  = Math.min(820, window.innerWidth - 80);
            const maxH  = Math.min(480, window.innerHeight - 280);
            const scale = Math.min(maxW / _screenImg.width, maxH / _screenImg.height, 1);
            canvas.width  = Math.round(_screenImg.width  * scale);
            canvas.height = Math.round(_screenImg.height * scale);
            canvas._imgScale = scale;
            ctx.drawImage(_screenImg, 0, 0, canvas.width, canvas.height);
            _applyCropHandlers();
        };
        _screenImg.src = "data:image/png;base64," + b64;
    }
```
Sonrası:
```javascript
    function showCropModal(b64) {
        _cropRect    = null;
        _isDrawing   = false;
        _clickPoints = [];
        _croppedB64  = null;
        _croppedImg  = null;
        document.getElementById("cropModal").style.display = "flex";
        _setStage("crop");

        _screenImg = new Image();
        _screenImg.onload = function() {
            _renderCropStageCanvas();
            _applyCropHandlers();
        };
        _screenImg.src = "data:image/png;base64," + b64;
    }

    function _setStage(stage) {
        _stage = stage;
        document.getElementById("stageLabel").textContent = stage === "crop" ? "1/2: Alan Seç" : "2/2: Nokta İşaretle";
        document.getElementById("cropModeHint").textContent = stage === "crop"
            ? "Tıkla ve sürükle → hedef alanı seç"
            : "Kırpılan alan üzerinde tıklanacak noktaları işaretle.";
        document.getElementById("btnCropConfirm").style.display  = stage === "crop"  ? "" : "none";
        document.getElementById("btnPointConfirm").style.display = stage === "point" ? "" : "none";
        document.getElementById("btnBackToCrop").style.display   = stage === "point" ? "" : "none";
        document.getElementById("pointsList").style.display      = stage === "point" ? "flex" : "none";
    }

    function _renderCropStageCanvas() {
        const canvas = document.getElementById("cropCanvas");
        const ctx    = canvas.getContext("2d");
        const maxW   = Math.min(820, window.innerWidth - 80);
        const maxH   = Math.min(480, window.innerHeight - 280);
        const scale  = Math.min(maxW / _screenImg.width, maxH / _screenImg.height, 1);
        canvas.width  = Math.round(_screenImg.width  * scale);
        canvas.height = Math.round(_screenImg.height * scale);
        canvas._imgScale = scale;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(_screenImg, 0, 0, canvas.width, canvas.height);
        if (_cropRect) {
            ctx.strokeStyle = "#3b82f6";
            ctx.lineWidth   = 2;
            ctx.strokeRect(_cropRect.x, _cropRect.y, _cropRect.w, _cropRect.h);
            ctx.fillStyle   = "rgba(59,130,246,0.12)";
            ctx.fillRect(_cropRect.x, _cropRect.y, _cropRect.w, _cropRect.h);
        }
        document.getElementById("cropSelectionInfo").textContent = _cropRect
            ? `Seçim: ${Math.round(_cropRect.w / scale)}×${Math.round(_cropRect.h / scale)} px` : "";
        document.getElementById("btnCropConfirm").disabled = !_cropRect;
    }
```

Ayrıca `window.setModalMode = function(mode) { ... };` bloğunun TAMAMINI (satır ~2275-2302) sil —
artık kullanılmıyor.

- [ ] **Step 4: `goToPointStage` + `backToCropStage` fonksiyonlarını ekle**

`confirmCrop`'un bulunduğu yere (satır ~2423, henüz silinmemiş haliyle) ekle — bu adımda henüz
`confirmCrop`'a dokunma, sadece bu iki yeni fonksiyonu `_applyPointHandlers()`'ın hemen altına ekle:

```javascript
    window.goToPointStage = function() {
        if (!_cropRect || !_screenImg) return;
        const canvas = document.getElementById("cropCanvas");
        const scale  = canvas._imgScale || 1;
        const sx = Math.round(_cropRect.x / scale);
        const sy = Math.round(_cropRect.y / scale);
        const sw = Math.round(_cropRect.w / scale);
        const sh = Math.round(_cropRect.h / scale);

        const tmp = document.createElement("canvas");
        tmp.width  = sw;
        tmp.height = sh;
        tmp.getContext("2d").drawImage(_screenImg, sx, sy, sw, sh, 0, 0, sw, sh);
        _croppedB64 = tmp.toDataURL("image/png").replace("data:image/png;base64,", "");

        _clickPoints = [];
        _croppedImg = new Image();
        _croppedImg.onload = function() {
            const maxW = Math.min(820, window.innerWidth - 80);
            const maxH = Math.min(480, window.innerHeight - 280);
            const zoom = Math.min(maxW / _croppedImg.width, maxH / _croppedImg.height, 4);
            canvas.width  = Math.round(_croppedImg.width  * zoom);
            canvas.height = Math.round(_croppedImg.height * zoom);
            canvas._imgScale = zoom;
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(_croppedImg, 0, 0, canvas.width, canvas.height);
            _setStage("point");
            _applyPointHandlers();
            _updatePointsUI();
        };
        _croppedImg.src = "data:image/png;base64," + _croppedB64;
    };

    window.backToCropStage = function() {
        if (!_screenImg) return;
        _clickPoints = [];
        _croppedB64  = null;
        _croppedImg  = null;
        _renderCropStageCanvas();
        _setStage("crop");
        _applyCropHandlers();
    };
```

- [ ] **Step 5: `_drawAllPoints`'te `_screenImg` yerine `_croppedImg` kullan**

Öncesi (satır ~2364-2368):
```javascript
    function _drawAllPoints() {
        const canvas = document.getElementById("cropCanvas");
        const ctx    = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(_screenImg, 0, 0, canvas.width, canvas.height);
```
Sonrası:
```javascript
    function _drawAllPoints() {
        const canvas = document.getElementById("cropCanvas");
        const ctx    = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(_croppedImg, 0, 0, canvas.width, canvas.height);
```

- [ ] **Step 6: `confirmCrop`'u sil, `confirmPoints`'i kırpılmış görsele göre güncelle, `cancelCrop`'a temizlik ekle**

Öncesi (satır ~2416-2477, `cancelCrop` + `confirmCrop` + `confirmPoints`):
```javascript
    window.cancelCrop = function() {
        document.getElementById("cropModal").style.display = "none";
        _clickPoints = [];
        removeEmptyImageStep();
        _captureTargetStepIdx = -1;
    };

    window.confirmCrop = function() {
        if (!_cropRect || _captureTargetStepIdx < 0 || !_screenImg) return;
        const canvas = document.getElementById("cropCanvas");
        const scale  = canvas._imgScale || 1;
        const sx = Math.round(_cropRect.x / scale);
        const sy = Math.round(_cropRect.y / scale);
        const sw = Math.round(_cropRect.w / scale);
        const sh = Math.round(_cropRect.h / scale);

        const tmp = document.createElement("canvas");
        tmp.width  = sw;
        tmp.height = sh;
        tmp.getContext("2d").drawImage(_screenImg, sx, sy, sw, sh, 0, 0, sw, sh);
        const croppedB64 = tmp.toDataURL("image/png").replace("data:image/png;base64,", "");

        const step = steps[_captureTargetStepIdx];
        if (step) {
            step.b64     = croppedB64;
            step.content = step.content || "Görsel element";
        }

        document.getElementById("cropModal").style.display = "none";
        _captureTargetStepIdx = -1;
        renderStepList();
        updateGenerateBtn();
        Toast.success("Görsel adım eklendi ✓");
    };

    window.confirmPoints = function() {
        if (_clickPoints.length === 0 || _captureTargetStepIdx < 0 || !_screenImg) return;
        // Tam ekranı sakla — kırpma yok.
        // click_x/click_y: orijinal görseldeki piksel koordinatı (normalize runtime'da hesaplanır).
        const fullCanvas = document.createElement("canvas");
        fullCanvas.width  = _screenImg.width;
        fullCanvas.height = _screenImg.height;
        fullCanvas.getContext("2d").drawImage(_screenImg, 0, 0);
        const fullB64 = fullCanvas.toDataURL("image/png").replace("data:image/png;base64,", "");

        const newSteps = _clickPoints.map((pt, i) => ({
            type:    "image",
            content: `Nokta ${i + 1} tıkla`,
            b64:     fullB64,   // tam ekran — bağlam zenginliği sayesinde 5 aynı toggle'ı ayırt eder
            action:  "click",
            click_x: pt.ox,    // orijinal görsel piksel X
            click_y: pt.oy,    // orijinal görsel piksel Y
            status:  null,
        }));
        steps.splice(_captureTargetStepIdx, 1, ...newSteps);
        document.getElementById("cropModal").style.display = "none";
        _captureTargetStepIdx = -1;
        _clickPoints = [];
        renderStepList();
        updateGenerateBtn();
        Toast.success(`${newSteps.length} nokta adım olarak eklendi ✓`);
    };
```
Sonrası:
```javascript
    window.cancelCrop = function() {
        document.getElementById("cropModal").style.display = "none";
        _clickPoints = [];
        _croppedB64  = null;
        _croppedImg  = null;
        removeEmptyImageStep();
        _captureTargetStepIdx = -1;
    };

    window.confirmPoints = function() {
        if (_clickPoints.length === 0 || _captureTargetStepIdx < 0 || !_croppedB64) return;
        // click_x/click_y: KIRPILAN gorseldeki orijinal piksel koordinati (tam sayfaya gore DEGIL).
        const newSteps = _clickPoints.map((pt, i) => ({
            type:    "image",
            content: `Nokta ${i + 1} tıkla`,
            b64:     _croppedB64,   // kırpılmış, ayırt edici, küçük görsel — sağlam eşleşir
            action:  "click",
            click_x: pt.ox,    // kırpılan görseldeki piksel X
            click_y: pt.oy,    // kırpılan görseldeki piksel Y
            status:  null,
        }));
        steps.splice(_captureTargetStepIdx, 1, ...newSteps);
        document.getElementById("cropModal").style.display = "none";
        _captureTargetStepIdx = -1;
        _clickPoints = [];
        _croppedB64  = null;
        _croppedImg  = null;
        renderStepList();
        updateGenerateBtn();
        Toast.success(`${newSteps.length} nokta adım olarak eklendi ✓`);
    };
```

**Not:** `confirmCrop` tamamen kaldırıldı (işlevi `goToPointStage`'e taşındı — Step 4'te zaten
eklendi). `onCropUp`'ın `document.getElementById("btnCropConfirm").disabled = false;` ataması
DEĞİŞMEDEN kalıyor (dikdörtgen çizilince buton hâlâ aktif olmalı, artık "İleri" anlamına geliyor).

- [ ] **Step 7: Manuel doğrulama**

Sunucuyu başlat (`cd backend && python main.py`), `/ui/ai-generator.html` sayfasını aç.

*Web platformunda:*
1. Web platformunu seç, "Görsel Ekle" ile bir ekran görüntüsü yükle/çek.
2. "1/2: Alan Seç" aşamasında bir alan çiz, "İleri: Nokta Seç →" tıkla.
3. "2/2: Nokta İşaretle" aşamasında büyütülmüş kırpılmış görsel görünmeli; 2-3 nokta işaretle.
4. "← Geri" ile Aşama 1'e dön, alanı biraz değiştirip tekrar "İleri" tıkla — önceki noktaların
   sıfırlandığını (yeni kırpma ile tutarlı) doğrula.
5. "Noktaları Ekle" ile onayla — her nokta için ayrı bir adım oluştuğunu, her adımın küçük
   (tam sayfa değil) bir görsel taşıdığını (adım thumbnail'ından gözle) doğrula.
6. "Script Üret" + "Tümünü Çalıştır" — script'in `NameError` almadan çalıştığını, doğru noktalara
   tıklandığını doğrula (bu senaryo daha önce Web'de hiç çalışmıyordu).

*Desktop platformunda:* Aynı akışı tekrarla, mevcut davranışın bozulmadığını doğrula.

*Modal kapatma:* Herhangi bir aşamada "İptal" ile modalı kapat, boş adımın step listesinden
kaldırıldığını doğrula.

- [ ] **Step 8: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "feat(ui): kirp+nokta secme tek akiste birlestirildi"
```

---

### Task 4: Uçtan uca doğrulama (spec Test Planı + geriye dönük uyumluluk)

**Files:** Yok (sadece çalıştırma/doğrulama)

- [ ] **Step 1: Geriye dönük uyumluluk — eski "sadece kırp" adımı**

Scratchpad'e `check_backcompat_crop_only.py`:

```python
import sys, asyncio
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _generate_steps, StepItem, GenerateRequest

req = GenerateRequest(platform="web", steps_list=[
    StepItem(type="image", content="Eski kirp adimi", image_b64="AAAA", action="click", click_x=-1, click_y=-1),
])
steps_code, report = asyncio.run(_generate_steps(req))
assert "_find_b64_on_screen_web(_img_b64_0" in steps_code, "FAIL: eski kirp-only adimi merkez-tiklama yoluna dusmuyor"
assert "_find_b64_and_click_point" not in steps_code, "FAIL: kirp-only adiminda yeni nokta fonksiyonu cagrilmamali"
print("OK")
```

Run: `"backend/venv/Scripts/python.exe" <check_backcompat_crop_only.py yolu>` — Expected: `OK`.

- [ ] **Step 2: Geriye dönük uyumluluk — eski "tam sayfa nokta" adımı**

Scratchpad'e `check_backcompat_full_page_point.py`:

```python
import sys, asyncio
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _generate_steps, StepItem, GenerateRequest

req = GenerateRequest(platform="desktop", steps_list=[
    StepItem(type="image", content="Eski tam sayfa nokta", image_b64="AAAA", action="click", click_x=500, click_y=300),
])
steps_code, report = asyncio.run(_generate_steps(req))
assert "_find_b64_and_click_point(_img_b64_0, 500, 300, action='click')" in steps_code, \
    "FAIL: eski tam-sayfa-nokta adimi yeni fonksiyona yonlenmiyor"
print("OK")
```

Run: aynı yöntemle — Expected: `OK`.

- [ ] **Step 3: Web bug-fix + çoklu nokta + Desktop regresyonu (manuel, spec Test Planı 1-3)**

Task 3 Step 7'de zaten çalıştırıldı — burada sonucu teyit et: Web'de `NameError` almadan tıklama
çalıştı mı, Desktop'ta davranış bozulmadı mı, tek kırpmada birden fazla nokta doğru sırayla ayrı
adım oldu mu. Sorun varsa ilgili task'a dönüp düzelt.

- [ ] **Step 4: Modal navigasyonu (manuel, spec Test Planı 5)**

"← Geri" ile Aşama 1'e dönüp alanı yeniden seçmenin ve modalı kapatıp boş adımı temizlemenin
(`cancelCrop`) çalıştığını doğrula (Task 3 Step 7'de zaten kapsandı, burada sonucu teyit et).

- [ ] **Step 5: Kontrol scriptlerini temizle**

Scratchpad'deki `check_bbox_click.py`, `check_image_step_unify.py`,
`check_backcompat_crop_only.py`, `check_backcompat_full_page_point.py` kalıcı repo dosyası
DEĞİL — silmene gerek yok (scratchpad zaten geçici), ama istersen temizleyebilirsin.

---

## Self-Review Notları

- **Spec kapsaması:** Spec'in "Frontend akışı" bölümü → Task 3. "Backend eşleştirme mantığı" +
  "Bug fix" → Task 1. "`_image_step_code()` birleştirmesi" → Task 2. "Veri modeli" (docstring
  güncellemesi) → Task 2 Step 3. "Geriye dönük uyumluluk" → Task 4 Step 1-2 (otomatik kontrol
  scriptleriyle). "Test Planı" (1-5) → Task 3 Step 7 (manuel) + Task 4 (özetle teyit + geriye
  dönük uyumluluk otomasyonu).
- **Placeholder taraması:** Yok — her adımda tam kod veya tam komut var, "TODO"/"benzer şekilde"
  gibi ifade kullanılmadı.
- **Tip/isim tutarlılığı:** `_find_b64_and_click_point` imzası Task 1'de tanımlandığı gibi Task 2
  (`_image_click_code` içinde) birebir aynı parametre sırasıyla çağrılıyor. `_stage`/`_croppedB64`/
  `_croppedImg` Task 3'te tek yerde tanımlanıp tüm fonksiyonlarda aynı isimle kullanılıyor.
  `_setStage`/`_renderCropStageCanvas` Task 3 Step 3'te tanımlanıp Step 4/6'da aynı isimle
  çağrılıyor.
- **Bağımlılık sırası:** Task 2, Task 1'in ürettiği `_find_b64_and_click_point` fonksiyon adına
  (string olarak) referans veriyor ama Task 1 tamamlanmadan Task 2'nin kontrol scripti YİNE DE
  çalışır (çünkü `_image_step_code` sadece metin üretir, üretilen metnin içindeki fonksiyonu
  gerçekten ÇAĞIRMAZ) — yine de mantıksal sıra Task 1 → Task 2 → Task 3 → Task 4 şeklinde
  izlenmeli, zira Task 3'ün manuel tarayıcı testi gerçek script çalıştırıyor ve Task 1/2'nin
  tamamlanmış olmasını gerektiriyor.
