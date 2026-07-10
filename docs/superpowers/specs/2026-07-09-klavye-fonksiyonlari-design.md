# Web ve Desktop: Genişletilmiş Klavye Fonksiyonları — Tasarım

**Tarih:** 2026-07-09
**Kapsam:** Web (Selenium) doğal dil parser'ına ve aksiyon işleyicisine ok tuşları/boşluk/çift
boşluk/kontrol tuşları/kısayollar eklenmesi; Desktop recorder'ının bu tuşları step olarak yakalaması
ve manuel adım editöründeki "Tuş Bas" dropdown'ının genişletilmesi. Mobile (Appium) bu round'a
**dahil değil**.

## Problem

Web tarafında doğal dil senaryo adımlarıyla sadece Enter/Tab/Escape tuşlarına basılabiliyor; ok
tuşları, boşluk, Delete/Backspace/Home/End, Ctrl+A/C/V gibi yaygın klavye etkileşimleri hiç
desteklenmiyor. Desktop tarafında backend zaten generic (`pyautogui.press`/`hotkey`) çalışıyor ve
manuel adım editöründe bu tuşların çoğu zaten seçilebiliyor, ama **Smart Recorder** (kayıt modu) ok
tuşlarını ve diğer kontrol tuşlarını hiç yakalamıyor, boşluk tuşu ise her zaman yazılan metnin
içine karışıyor — hızlı çift boşluk basışı ayrı bir anlamlı adım olarak algılanamıyor.

## Çözüm

### 1. Web — Aksiyon işleyici (`backend/services/selenium_service.py`, L298-306)

Mevcut `elif action in ['press', 'key', 'tus', 'tuş']:` bloğu genişletilir:

```python
elif action in ['press', 'key', 'tus', 'tuş']:
    key = (target or value).lower()
    ae = self.driver.switch_to.active_element
    if key == 'enter':
        ae.send_keys(Keys.ENTER)
    elif key == 'tab':
        ae.send_keys(Keys.TAB)
    elif key in ['escape', 'esc']:
        ae.send_keys(Keys.ESCAPE)
    elif key in ['up', 'down', 'left', 'right']:
        ae.send_keys(getattr(Keys, f'ARROW_{key.upper()}'))
    elif key == 'space':
        ae.send_keys(Keys.SPACE)
    elif key == 'double_space':
        ae.send_keys(Keys.SPACE); ae.send_keys(Keys.SPACE)
    elif key == 'delete':
        ae.send_keys(Keys.DELETE)
    elif key == 'backspace':
        ae.send_keys(Keys.BACK_SPACE)
    elif key == 'home':
        ae.send_keys(Keys.HOME)
    elif key == 'end':
        ae.send_keys(Keys.END)
    elif key in ['pageup', 'page_up']:
        ae.send_keys(Keys.PAGE_UP)
    elif key in ['pagedown', 'page_down']:
        ae.send_keys(Keys.PAGE_DOWN)
    elif '+' in key:
        # ctrl+a, ctrl+c, ctrl+v gibi kısayollar — ActionChains gerekli
        mod_name, letter = key.split('+', 1)
        mod_key = {'ctrl': Keys.CONTROL, 'shift': Keys.SHIFT, 'alt': Keys.ALT}.get(mod_name)
        if mod_key:
            ActionChains(self.driver).key_down(mod_key).send_keys(letter).key_up(mod_key).perform()
        else:
            result["success"] = False
            result["message"] = f"Bilinmeyen kısayol: {key}"
    else:
        result["success"] = False
        result["message"] = f"Bilinmeyen tuş: {key}"
    if result["success"]:
        result["message"] = f"{key.upper()} tuşuna basıldı"
```

`ActionChains` importu dosyanın başına eklenir (`from selenium.webdriver.common.action_chains import
ActionChains`). Modifier tuşları Selenium'da düz `send_keys` ile çalışmaz — `key_down`/`key_up`
çifti gerekir; bu yüzden `+` içeren tuşlar ayrı dalda ele alınıyor.

Bilinmeyen tuş artık **sessizce geçilmiyor**, `success=False` + açıklayıcı mesaj dönüyor (önceki
davranıştaki küçük bir tutarsızlık düzeltmesi).

### 2. Web — Doğal dil parser (`backend/services/selenium_service.py`, ~L407 civarı)

Mevcut `enter\s*(?:bas)?` bloğunun **hemen öncesine** (çift boşluk deseni tekli boşluktan önce
kontrol edilmeli, aksi halde tekli boşluk deseni onu yutar), aynı `re.search(...)/continue` zinciri
desenini izleyen yeni bloklar eklenir:

```python
_ARROW_MAP = {'sağ': 'right', 'sag': 'right', 'sol': 'left', 'yukarı': 'up', 'yukari': 'up',
              'aşağı': 'down', 'asagi': 'down'}

match = re.search(r'(sağ|sag|sol|yukarı|yukari|aşağı|asagi)\s*ok(?:\s*tuşuna?)?\s*bas', line, re.IGNORECASE)
if match:
    step.action = 'press'
    step.target = _ARROW_MAP[match.group(1).lower()]
    commands.append(step); continue

if re.search(r'çift\s*boşluk|cift\s*bosluk', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'double_space'
    commands.append(step); continue

if re.search(r'boşluk(?:\s*tuşuna?)?\s*bas|bosluk\s*tusuna?\s*bas', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'space'
    commands.append(step); continue

if re.search(r'delete\s*tuşuna?\s*bas|sil\s*tuşuna?\s*bas', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'delete'
    commands.append(step); continue

if re.search(r'backspace|geri\s*sil', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'backspace'
    commands.append(step); continue

if re.search(r'home\s*tuşuna?\s*bas', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'home'
    commands.append(step); continue

if re.search(r'end\s*tuşuna?\s*bas', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'end'
    commands.append(step); continue

if re.search(r'page\s*up', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'pageup'
    commands.append(step); continue

if re.search(r'page\s*down', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'pagedown'
    commands.append(step); continue

if re.search(r'tümünü\s*seç|tumunu\s*sec', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'ctrl+a'
    commands.append(step); continue

if re.search(r'kopyala', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'ctrl+c'
    commands.append(step); continue

if re.search(r'yapıştır|yapistir', line, re.IGNORECASE):
    step.action = 'press'; step.target = 'ctrl+v'
    commands.append(step); continue
```

Her blok, dosyadaki mevcut `if re.search(...): ...; continue` tekrarlı desenine birebir uyuyor — yeni
bir soyutlama eklenmiyor.

### 3. Desktop — Recorder (`backend/routers/desktop_router.py`)

`_RecorderState` (L342-350) sınıfına yeni alan:

```python
self.last_space_time = 0.0
```

`_rec_on_key` (L437-473) fonksiyonuna yeni dallar eklenir. **Sıra önemli:** `space` dalı özel mantık
içerir, diğerleri mevcut `enter`/`tab` dallarıyla birebir aynı basit desende:

```python
elif key == kb.Key.space:
    now = time.time()
    if now - _rec.last_space_time < 0.4:
        # Hızlı çift boşluk: buffer'a önceki basışta eklenen boşluğu geri al,
        # kalanı flush et, ayrı bir "double_space" step'i yayınla.
        if _rec.type_buffer.endswith(" "):
            _rec.type_buffer = _rec.type_buffer[:-1]
        _rec_flush_type()
        _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                      "key": "double_space", "description": "Press Key: double_space"})
        _rec.last_space_time = 0.0  # üçlü/dörtlü ardışık basışta tekrar tetiklenmesin
    else:
        _rec.type_buffer += " "
        _rec.last_space_time = now
elif key in (kb.Key.up, kb.Key.down, kb.Key.left, kb.Key.right):
    _rec_flush_type()
    key_name = {kb.Key.up:"up", kb.Key.down:"down", kb.Key.left:"left", kb.Key.right:"right"}[key]
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": key_name, "description": f"Press Key: {key_name}"})
elif key == kb.Key.delete:
    _rec_flush_type()
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": "delete", "description": "Press Key: delete"})
elif key == kb.Key.home:
    _rec_flush_type()
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": "home", "description": "Press Key: home"})
elif key == kb.Key.end:
    _rec_flush_type()
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": "end", "description": "Press Key: end"})
elif key == kb.Key.page_up:
    _rec_flush_type()
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": "pageup", "description": "Press Key: pageup"})
elif key == kb.Key.page_down:
    _rec_flush_type()
    _rec_broadcast({"type": "step", "action_type": "PRESS_KEY",
                  "key": "pagedown", "description": "Press Key: pagedown"})
```

(`kb.Key.esc` zaten fonksiyonun en başında kaydı durdurmak için kullanılıyor — Esc kaydedilebilir bir
step olarak eklenmiyor, bu mevcut davranış korunuyor.)

`time` modülü dosyada zaten import edilmiş durumda (ss timestamp'lerinde kullanılıyor), ek import
gerekmiyor.

**Neden zaman eşiği yaklaşımı:** tekli boşluklar cümle içinde kalmaya devam etsin isteniyor (ör.
"merhaba dünya" tek bir `TYPE` step'i olarak kalır), sadece kasıtlı hızlı çift basış ayrı bir step'e
dönüşsün. 400ms, ortalama insan çift-tıklama/çift-basış hızının üstünde, normal yazım hızının
altında bir eşik.

### 4. Desktop — Playback (`PRESS_KEY` handler, `backend/routers/desktop_router.py` L629-635)

```python
elif stype == "PRESS_KEY":
    key = params.get("key", "enter")
    if key == "double_space":
        _pag().press("space")
        time.sleep(0.05)
        _pag().press("space")
    elif "+" in key:
        _pag().hotkey(*key.split("+"))
    else:
        _pag().press(key)
    result["success"] = True
```

Ok tuşları (`up`/`down`/`left`/`right`), `delete`, `home`, `end`, `pageup`, `pagedown` zaten
pyautogui'nin tanıdığı standart tuş adları olduğu için ayrı bir dal gerekmiyor — mevcut generic
`_pag().press(key)` dalı bunları olduğu gibi çalıştırır. `pageup`/`pagedown` pyautogui'de tire/alt
çizgisiz tek kelime (`pyautogui.KEYBOARD_KEYS` içinde `"pageup"`, `"pagedown"`) — recorder'ın
yayınladığı `key_name` değerleriyle burada birebir eşleşiyor.

### 5. Desktop — Manuel adım editörü (`backend/WebArayuz/advanced_editor.html`, `doKey()` L442-447)

Dropdown listesine `double_space`, `pageup`, `pagedown` eklenir; `dialog()` çağrısına ikinci bir
serbest metin alanı eklenir (doldurulursa dropdown değerinin yerine geçer):

```js
window.doKey = function(){
  dialog("Tuş Bas", [
    {label:"Tuş", type:"select", opts:["enter","tab","esc","backspace","delete","space","double_space",
      "home","end","pageup","pagedown","up","down","left","right",
      "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
      "ctrl+c","ctrl+v","ctrl+a","ctrl+s","ctrl+z","alt+tab","alt+f4"]},
    {label:"Özel Tuş (opsiyonel, doldurulursa yukarıdaki seçimin yerine geçer)", ph:"örn: insert, ctrl+shift+esc"}
  ], function(v){
    var key = (v[1] && v[1].trim()) ? v[1].trim() : v[0];
    S.steps.push({type:"PRESS_KEY", params:{key:key}, description:"Press: "+key});
    render(); log("Tuş: "+key, "ok");
  });
};
```

`dialog()` fonksiyonu zaten çok alanlı formu destekliyor (bkz. mevcut `doOcrRead`/`doType` gibi
diğer dialoglar) — ek altyapı değişikliği gerekmiyor.

## Test Planı

1. **Web — ok tuşları:** senaryoya `"arama kutusuna" alanına aşağı ok tuşuna bas` gibi bir satır
   ekleyip çalıştır, `Keys.ARROW_DOWN` gönderildiğini ve step'in `success=True` döndüğünü doğrula.
2. **Web — çift boşluk vs tekli boşluk:** `boşluk tuşuna bas` ve `çift boşluk bas` içeren iki ayrı
   senaryo satırının doğru `target` (`space` / `double_space`) ile parse edildiğini doğrula (özellikle
   `çift boşluk`'un yanlışlıkla `boşluk` deseniyle eşleşip `double_space` yerine `space`'e
   düşmediğini — desen sırası testi).
3. **Web — kısayol:** `tümünü seç` satırının `ctrl+a`'ya map edildiğini ve `ActionChains` ile
   çalıştırıldığında bir metin alanındaki tüm metnin seçildiğini (manuel/headful test) doğrula.
4. **Web — bilinmeyen tuş:** `target='zzz'` ile `press` action'ı çağrıldığında `success=False` ve
   açıklayıcı hata mesajı döndüğünü doğrula (önceki sessiz geçme davranışının düzeldiğini).
5. **Desktop — recorder ok tuşu:** kayıt başlat, sağ ok tuşuna bas, kaydı durdur; adım listesinde
   `PRESS_KEY {key:"right"}` step'inin oluştuğunu doğrula.
6. **Desktop — recorder tekli boşluk (regresyon):** kayıt başlat, "merhaba dünya" yaz (aralarında tek
   boşluk, normal yazım hızında), kaydı durdur; tek bir `TYPE {text:"merhaba dünya"}` step'i
   oluştuğunu, ayrı bir `PRESS_KEY space` step'i OLUŞMADIĞINI doğrula.
7. **Desktop — recorder çift boşluk:** kayıt başlat, "test" yaz, ardından boşluk tuşuna hızlıca iki
   kez bas (< 400ms arayla), ardından "son" yaz; adım listesinde `TYPE {text:"test"}` →
   `PRESS_KEY {key:"double_space"}` → `TYPE {text:"son"}` sırasının oluştuğunu, ve önceki tekli
   boşluğun `type_buffer`'dan doğru çıkarıldığını (yani "test " değil "test" flush edildiğini)
   doğrula.
8. **Desktop — double_space playback:** bir `PRESS_KEY {key:"double_space"}` step'ini bağımsız
   çalıştırıp iki ayrı space tuş basışının gönderildiğini doğrula.
9. **Desktop — manuel editör:** `advanced_editor.html` üzerinde "Tuş Bas" dialogunu aç, dropdown'dan
   `double_space` seç ve kaydet; ayrıca "Özel Tuş" alanına `ctrl+shift+esc` yazıp kaydettiğinde
   dropdown seçimi yerine bu değerin step'e yazıldığını doğrula.

## Self-Review Notları

- **Kapsam:** Mobile (Appium) bilinçli olarak bu round'a dahil edilmedi — kullanıcı sadece Web ve
  Desktop'ı seçti. İleride mobile için ayrı bir spec/round gerekecek.
- **Geriye dönük uyumluluk:** Web aksiyon işleyicisindeki "bilinmeyen tuş sessizce geçilir" davranışı
  kasıtlı olarak `success=False`'a çevriliyor; bu küçük bir davranış değişikliği ama önceki hâli gerçek
  bir hata durumunu maskeliyordu (kullanıcı yanlış yazılmış bir tuş adıyla senaryo yazsa bile step
  "başarılı" görünüyordu).
- **Zaman eşiği (400ms):** Sabit kodlanmış, konfigüre edilebilir değil — YAGNI, şu an tek kullanım
  senaryosu bunu gerektirmiyor.
- **Tutarlılık:** Yeni recorder dalları (ok tuşları, delete, home/end, pageup/pagedown) mevcut
  `enter`/`tab` dallarıyla birebir aynı üç satırlık desende (`_rec_flush_type()` +
  `_rec_broadcast(...)`) yazılıyor — kod tabanındaki var olan örüntüye sadık kalınıyor, yeni bir
  soyutlama eklenmiyor.
