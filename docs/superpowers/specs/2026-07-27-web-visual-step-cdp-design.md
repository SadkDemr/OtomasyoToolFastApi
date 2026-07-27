# Web Görsel Adımlar — Headless Chrome/Edge için CDP Tabanlı Eşleme/Tıklama

**Tarih:** 2026-07-27
**Kapsam:** Hibrit Adım Editörü'nün Web platformundaki görsel/OpenCV adımlarını (assert, nokta tıklama, sürükleme, `image_exists` koşulu) headless Chrome/Edge'de çalışır hale getirmek. Firefox kapsam dışı (net hata verir).

## Problem

AI Job sistemi Faz 2 (Web Job) doğrulaması sırasında bulundu: Web scriptleri her zaman headless çalışıyor (`_build_web_template`), ama görsel adımlar `IMAGE_HELPER`'daki `_find_image_on_screen` üzerinden `pyautogui.screenshot()` ile **gerçek OS ekranını** yakalıyor. Headless tarayıcı ekrana hiç çizilmediği için bu adımlar hem manuel "Test Et" hem Job motorunda **her zaman** başarısız olur ("Görsel bulunamadı"). Kullanıcı doğruladı: bu senaryolardaki görsel adım gerçekten gerekli (DOM/xpath ile seçilemeyen bir canvas/iframe içeriği) — kaldırılamaz, çalışır hale getirilmeli.

## Neden yeni bir helper bloğu (mevcut IMAGE_HELPER değil)

`IMAGE_HELPER` hem Desktop hem Web şablonuna gömülüyor ve Desktop'ın ekran-tabanlı modelini bozmadan değiştirilemez. Bunun yerine, sadece **Web şablonuna ek olarak** gömülecek yeni bir blok (`IMAGE_HELPER_WEB_CDP`) ekleniyor — `IMAGE_HELPER`'ın zaten tanımladığı ortak yardımcıları (`_bbox_click_point`, `_ib64`/`_itmp`/`_ios`/`_itime` import'ları) yeniden kullanır. Desktop şablonu hiç değişmiyor.

## Çözüm

### Arama: `_find_image_in_page(driver, target_path, threshold=0.80, return_bbox=False)`
`IMAGE_HELPER`'daki `_find_image_on_screen`'in bir varyasyonu: `pyautogui.screenshot(region=...)` yerine `driver.get_screenshot_as_png()` kullanır (tarayıcının kendi render'ı — headless'ta da doğru çalışır, DPI/OS ekran kavramı yok). Aynı OpenCV multi-scale template matching (`cv2.matchTemplate`, `TM_CCOEFF_NORMED`, scale aralığı taraması) — DPI-scale düzeltmesi (ctypes/`GetDpiForSystem`) kaldırılır çünkü bir sayfa screenshot'unun mantıksal CSS piksel boyutu zaten sabittir.

### Tıklama/Sürükleme: Chrome DevTools Protocol
- `_cdp_click(driver, x, y, button="left", click_count=1)` — `driver.execute_cdp_cmd("Input.dispatchMouseEvent", {...})` ile `mouseMoved` → `mousePressed` → `mouseReleased` event'leri gönderir. Gerçek OS faresine dokunmaz, tarayıcı içine doğrudan basar.
- `_cdp_drag(driver, x1, y1, x2, y2, steps=10)` — `mousePressed` at (x1,y1), ara `mouseMoved` adımları (`buttons: 1` ile basılı sürükleme simülasyonu), `mouseReleased` at (x2,y2).
- Chrome ve Edge (ikisi de Chromium tabanlı) `execute_cdp_cmd`'i destekler — Selenium 4.15.2 (mevcut bağımlılık) üzerinden ek paket gerekmez.

### Birleşik "bul + tıkla/sürükle" fonksiyonları
`IMAGE_HELPER`'daki `_find_b64_and_click_point`/`_find_b64_and_drag` desenini birebir izleyen, `driver` parametresi alan ve `_find_image_in_page`+`_cdp_click`/`_cdp_drag` kullanan yeni fonksiyonlar: `_find_b64_and_click_point_web(driver, b64_data, click_x, click_y, action, threshold, timeout)`, `_find_b64_and_drag_web(driver, b64_data, x1, y1, x2, y2, ...)`, ve basit arama için `_find_b64_in_page_web(driver, b64_data, threshold, timeout)` (assert/`image_exists` koşulu için).

### Kod üretimi tarafındaki dallanma
`ai_test_generator_router.py`'de üç yer aynı deseni kullanıyor: `find_fn = "_find_b64_on_screen" if platform == "desktop" else "_find_b64_on_screen_web"` (satır ~2771, 2819, 3189 — `_image_step_code`, `_condition_expr` içinde). Bu fonksiyonlar şu an sadece `platform` alıyor; **`browser` parametresi de eklenecek** (çağıranlarda zaten `req.browser` mevcut, `_generate_steps` içindeki tüm çağrı noktalarına — ana döngü + if/else dallarının recursive işlendiği yer — taşınacak). Yeni dallanma:

```
if platform == "desktop":
    find_fn = "_find_b64_on_screen"              # mevcut, degismedi
    click/drag: pyautogui (mevcut, degismedi)
elif platform == "web" and browser in ("chrome", "edge"):
    find_fn = "_find_b64_in_page_web(driver, ...)"     # yeni, CDP tabanli
    click/drag: _find_b64_and_click_point_web / _find_b64_and_drag_web
else:  # platform == "web" and browser == "firefox"
    # Gorsel adim varsa script aninda net bir Turkce hata ile durur —
    # 10 saniyelik bosuna bekleme yerine.
    raise Exception("Görsel adımlar şu anda Firefox'ta desteklenmiyor. Chrome veya Edge kullanın.")
```

`_build_web_template`, Chrome/Edge için `IMAGE_HELPER_WEB_CDP` bloğunu `IMAGE_HELPER`'dan hemen sonra script'e gömer (Firefox için gömülmez — gerek yok, o dalda hiç çağrılmıyor).

## Hata Yönetimi
- Firefox + görsel adım: script üretimi sırasında (`_generate_steps`), o adım için normal STEP_START/STEP_FAIL akışına giren bir `raise Exception(...)` üretilir — mevcut hata yakalama/step-fail mekanizması (zaten var, değişmiyor) bunu STEP_FAIL olarak raporlar.
- Chrome/Edge + `execute_cdp_cmd` başarısız olursa (ör. çok eski bir driver sürümü): mevcut `try/except` + `[FAIL]`/STEP_FAIL deseni (zaten var) hatayı yakalar, script çökmez.
- Görsel eşleşme zaman aşımına uğrarsa: aynı mevcut mesaj deseni (`[DEBUG] Gorsel {timeout}s icinde bulunamadi`), sadece "(sayfa görüntüsü)" notu eklenerek OS-ekran aramasından ayırt edilir.

## Test Planı
Otomatik test yok. Manuel: "Finansman_Hesapla" senaryosunu (veya görsel adım içeren başka bir Web senaryosunu) Chrome ile hem manuel "Test Et" hem AI Job üzerinden tekrar çalıştırıp görsel adımın artık geçtiğini doğrulamak. Ayrıca aynı senaryoyu Firefox seçerek çalıştırıp net "desteklenmiyor" hatası aldığını doğrulamak.
