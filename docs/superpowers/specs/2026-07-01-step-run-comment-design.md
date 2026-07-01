# Adım Çalıştırma & Yorum — Tasarım

**Tarih:** 2026-07-01
**Kapsam:** AI Test Generator — iki parça, Web/Desktop/Mobil ortak
- **A) Tek Adım Çalıştırma:** Bir senaryodaki tek bir adımı, baştan koşmadan (önceki adımların
  bıraktığı durumdan devam ederek) çalıştırabilme.
- **B) Yorum Adımı:** Senaryoya çalışmayan, sadece açıklama amaçlı bir adım tipi ekleme.

## Bölüm A: Tek Adım Çalıştırma

### Problem

`/generate` zaten `steps_list` üzerinden herhangi bir adım alt kümesi için script üretebiliyor,
`/execute` de bağımsız bir script çalıştırıyor — yani "tek adım üret+çalıştır" mekanizması altyapı
olarak zaten var. Ama gerçek değeri, önceki adımların bıraktığı durumdan (login olunmuş, doğru
sayfada/ekranda) devam edebilmesinde. Bugün:

- **Desktop:** `reuse_instance=True` (varsayılan) sayesinde hedef pencere zaten açıksa yeniden
  başlatılmıyor — tek adım çalıştırma bugün bile doğal olarak çalışır, ek altyapı gerekmez.
- **Web/Mobil:** Her `/execute` çağrısı sıfırdan `webdriver.Chrome()` / Appium session'ı açıyor,
  script sonunda `driver.quit()` ile kapatıyor. Önceki adımların bıraktığı durum kaybolur — tek
  adım çalıştırmak neredeyse her zaman anlamsız/başarısız olur (login olmamış, yanlış sayfada).

### Çözüm

**Teknik mekanizma — Selenium/Appium remote session reconnect:**
Sistemin "script'i bağımsız subprocess olarak çalıştır" mimarisini koruyarak, kalıcılık üç script
varyantıyla sağlanır:

1. **Oturum Başlat** (`session_mode="start"`): Normal script gibi çalışır ama sonunda
   `driver.quit()` YERİNE `driver.session_id` ve `driver.command_executor._url`'i bir session
   dosyasına yazar, subprocess çıkar. Tarayıcı/uygulama süreci açık kalır (WebDriver client
   kapansa da chromedriver/tarayıcı süreci bağımsız yaşar). **Headless DEĞİL** — kullanıcı adım
   adım debug ederken tarayıcıyı görebilsin diye (mevcut "Tümünü Çalıştır" headless kalmaya devam
   eder, sadece interaktif oturum modu görünür).
2. **Adımı Çalıştır** (`session_mode="attach"`): `driver = webdriver.Remote(command_executor=
   kayıtlı_url, ...)` sonra `driver.session_id = kayıtlı_id` ile AYNI tarayıcıya/uygulamaya
   bağlanır (yeni pencere AÇMAZ), sadece o tek adımın kodunu çalıştırır, yine `driver.quit()`
   ÇAĞIRMAZ.
3. **Oturumu Bitir** (`session_mode="end"`): Son kez bağlanıp `driver.quit()` çağırır, session
   dosyasını siler.

**Backend state:** `_active_sessions: dict[tuple[int, str], dict]` — anahtar `(user_id, platform)`,
değer `{"session_id", "command_executor_url", "started_at", "last_used_at"}`. Mevcut
`_running_processes` / Desktop Lock desenleriyle aynı stilde, modül seviyesinde bir dict.
Arka planda `asyncio` periyodik görev, `last_used_at` üzerinden **15 dakika** boşta kalan oturumları
otomatik `driver.quit()` ile kapatır (kaynak sızıntısını önlemek için — Desktop Lock'un "aynı anda
tek test" kısıtına benzer bir disiplin, ama burada "kullanıcı+platform başına tek oturum" ve
zaman aşımı ile).

**Yeni endpoint'ler** (`/api/ai-generator` altında):
| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/session/start` | Web/Mobil oturumu başlatır (mevcut `GenerateRequest` alanları: platform, browser/app_package vb.) |
| POST | `/session/run-step` | Aktif oturuma bağlanıp tek bir `StepItem` çalıştırır (`ExecuteRequest`'e benzer gövde + step) |
| POST | `/session/end` | Aktif oturumu kapatır |
| GET | `/session/status` | Kullanıcının aktif oturumu var mı, hangi platformda (UI göstergesi için) |

**Şablon değişikliği:** `_build_web_template`/`_build_mobile_template` bir `session_mode: str =
"fresh"` parametresi alır (`"fresh"` = mevcut davranış, değişmez). `"start"` → driver_setup aynı
ama headless kapalı + sonda quit yerine session bilgisi yazdırma. `"attach"` → driver_setup yerine
`webdriver.Remote(...)` ile bağlanma + quit yok. `"end"` → sadece bağlan + quit.

**Desktop:** Ek mekanizma YOK — "Adımı Çalıştır" butonu doğrudan mevcut `/generate`
(`steps_list=[o_adim]`) + `/execute` akışını kullanır, `reuse_instance` zaten devam ettiriyor.

**Frontend (`ai-generator.html`):**
- Her çalıştırılabilir adımın (text/image/sql/api) yanına **"▶ Adımı Çalıştır"** butonu eklenir.
- Web/Mobil platformlarda sayfa üstünde **"Oturumu Başlat" / "Oturumu Bitir"** butonları + aktif
  oturum göstergesi (`/session/status` ile senkron). Oturum yokken "Adımı Çalıştır" tıklanırsa
  kullanıcıya "Önce oturum başlatın" uyarısı gösterilir (otomatik başlatma YOK — Bölüm 1'de
  onaylandığı gibi explicit kontrol).
- "Tümünü Çalıştır" (mevcut buton) davranışı **değişmez** — her zaman `session_mode="fresh"`.

### Bilinen Risk / Doğrulama Gereken Varsayım

**Spike sonucu (2026-07-01, Task 1 — `backend/services/session_reconnect.py`):**

- **Web (Selenium 4.15.2): ✅ doğrulandı, ama teknikte kritik bir düzeltme gerekti.**
  Brief'teki ilk taslak kod iki noktada başarısız oldu, ikisi de düzeltildi:
  1. **`driver.quit()` çağrılmasa bile süreç normal şekilde sonlandığında tarayıcı KAPANIYOR.**
     Kök neden: `selenium/webdriver/common/service.py`'deki `Service.__del__` — Python
     interpreter kapanırken `Service` nesnesi GC edildiğinde `self.stop()` tetikleniyor, o da
     chromedriver'ın `/shutdown` endpoint'ine HTTP isteği atıp chromedriver'ı (ve altındaki
     chrome'u) sonlandırıyor. Bu, `driver.quit()` çağrılmasa da normal `sys.exit`/script sonu ile
     otomatik olarak oluyor. **Çözüm:** "Oturum Başlat" script'i normal şekilde bitmemeli, en
     sonda `os._exit(0)` çağırmalı — bu, `__del__` finalizer'larını ve interpreter shutdown
     sırası yapılan temizliği atlar, chromedriver/chrome süreçleri hayatta kalır. Bu, session
     reconnect özelliğinin implementasyonunda "Oturumu Başlat" endpoint'inin arkasındaki
     subprocess/script'in nasıl sonlandırılacağı için bağlayıcı bir tasarım kısıtıdır.
  2. Brief'teki `start_session` override'ı `self.capabilities = {}` atıyordu — Selenium
     4.15.2'de `capabilities` salt-okunur bir property (gerçek depolama `self.caps`), bu satır
     `AttributeError` fırlatıyordu. `self.caps = {}` olarak düzeltildi.
  Kanıt: `spike_web_start3.py` (os._exit ile) session açtı, süreç bitti, `tasklist` çıktısında
  aynı `chromedriver.exe` PID'i ve chrome.exe süreçleri canlı kaldı. İkinci, bağımsız bir Python
  sürecinden `attach_selenium_session(EXECUTOR_URL, SESSION_ID)` ile bağlanıp
  `document.title = 'attached-ok'` çalıştırıldı, `driver.title` geri okununca `attached-ok`
  döndü — `tasklist` çıktısı bağlanma öncesi/sonrası AYNI chromedriver PID'ini ve chrome.exe
  süreç kümesini gösterdi (yeni bir session/pencere AÇILMADI). `driver.quit()` ile üçüncü
  script'ten kapatıldı, chrome.exe süreçleri sonlandı.
- **Mobil (Appium-Python-Client 3.1.0): atlandı — ortam eksikliği.** Bu ortamda bağlı bir
  Android cihaz/emulator (`adb devices` boş liste döndürdü) ve çalışan bir Appium sunucusu
  (4723 portunda yanıt yok) bulunmuyor. `attach_appium_session` fonksiyonu aynı düzeltmeyle
  (`self.caps = {}`) `session_reconnect.py`'a yazıldı ve Appium `WebDriver`'ın da (Selenium'un
  `RemoteWebDriver`'ından türediği için) aynı `self.caps` deposunu kullandığı kaynak kod
  incelemesiyle doğrulandı (`appium/webdriver/webdriver.py:337`), ama uçtan uca ÇALIŞTIRILARAK
  kanıtlanmadı. **Mobil için bu varsayım hâlâ ampirik olarak doğrulanmamış durumda — gerçek
  cihaz/emulator + Appium sunucusu olan bir ortamda Task 6 insan onayı öncesi tekrar
  doğrulanmalı.** Web'de bulunan `os._exit(0)` gereksinimi muhtemelen Appium için de geçerli
  olacaktır (aynı `Service` sınıfı Appium tarafında da kullanılıyor), bu implementasyon
  planında varsayılmalı ama doğrulanmadan kesinleşmiş kabul edilmemeli.

Sonuç: Bölüm A'nın Web kısmı bu teknikle ilerleyebilir, ancak "Oturum Başlat" implementasyonu
`os._exit(0)` kısıtını hesaba katmalı. Mobil kısım için risk kapanmadı; Mobil ayrı ele alınabilir
veya Task 6'da gerçek cihaz ortamında yeniden doğrulanmalıdır.

**Task 1 review'ında bulunan, Task 5/7 implementasyonunu bağlayan iki ek risk (2026-07-01):**

1. **Orphan `chromedriver.exe` sızıntısı — "Oturumu Bitir" chromedriver'ı gerçekten kapatmayabilir.**
   `attach_selenium_session`/`attach_appium_session` ile bağlanan driver nesnesinin bir `Service`
   nesnesi YOK (attach modu `Service` hiç oluşturmuyor). Bu yüzden bu driver'da `driver.quit()`
   sadece `Command.QUIT` gönderip HTTP bağlantısını kapatıyor — `Service.stop()`/chromedriver'ın
   `/shutdown` endpoint'ini ASLA çağırmıyor. Spike sırasında bu gözlemlendi (chromedriver.exe'yi
   elle `Stop-Process` ile kapatmak gerekti). **Task 7'nin `/session/end` endpoint'i sadece
   `session_mode="end"` script'i (attach + `driver.quit()`) çalıştırırsa, chromedriver.exe süreci
   sonsuza kadar orphan kalır.** Task 7 implementasyonunda `/session/end`'in, `driver.quit()`'e ek
   olarak chromedriver'ın `/shutdown` HTTP endpoint'ine de doğrudan istek atması (ya da
   `command_executor_url + "/shutdown"`'a bir GET/POST göndermesi) gerekebilir — bu Task 7'ye
   eklenmesi gereken bir adım, mevcut plandaki `session_end` taslağında YOK.
2. **`os._exit(0)` + `subprocess.run(capture_output=True)` etkileşimi doğrulanmadı.** Spike, "Oturum
   Başlat" script'ini `wmic process call create` ile (pipe yakalamadan, ayrık) başlattı — Task 7'nin
   gerçek mekanizması (`subprocess.run([...], capture_output=True, text=True, ...)` ile
   `SESSION_ID:`/`EXECUTOR_URL:` çıktısını `proc.stdout`'tan parse etme) hiç test edilmedi.
   `os._exit()` stdio flush'ı atlıyor — plan zaten `PYTHONUNBUFFERED=1` kullanıyor (bu riski
   muhtemelen azaltıyor) ama bu kombinasyon ampirik olarak KANITLANMADI. Task 5/7 implementasyonuna
   başlamadan önce (ya da Task 7'nin ilk adımı olarak) `subprocess.run(capture_output=True)` +
   `os._exit(0)` kombinasyonuyla stdout'un gerçekten eksiksiz/flush edilmiş geldiği küçük bir ek
   doğrulama yapılmalı.

## Bölüm B: Yorum Adımı

### Problem

Uzun senaryolarda adımları gruplamak/açıklamak için çalışmayan bir "not" adımı yok.

### Çözüm

Yeni `StepItem.type = "comment"` — mevcut `content` alanı yeniden kullanılır, yeni alan gerekmez.

**Backend (`_generate_steps`):** comment tipi için üretilen kod sadece `f"# [YORUM] {item.content}"`
— `STEP_START`/`STEP_DONE` sarmalayıcısı YOK, hiç SSE event'i tetiklemez, pass/fail sayımına
girmez. `structured`/`code_lines`/`report` listelerindeki index hizası korunur (comment adımı da
bir slot kaplar) ama koşum sırasında "çalıştırılan adım" olarak görünmez.

**Frontend:** "+" adım ekleme menüsüne **"💬 Yorum"** seçeneği eklenir. Yorum adımı listede
soluk/italik gösterilir, aksiyon dropdown'u yok, Bölüm A'daki "Adımı Çalıştır" butonu da yok
(çalıştırılacak bir şey olmadığı için gösterilmez).

## Etkilenen Dosyalar

- `backend/routers/ai_test_generator_router.py`:
  - `_active_sessions` dict + idle-timeout arka plan görevi
  - `/session/start`, `/session/run-step`, `/session/end`, `/session/status` endpoint'leri
  - `_build_web_template`/`_build_mobile_template`'e `session_mode` parametresi
  - `_generate_steps()`'e `type == "comment"` dalı
  - `StepItem.type` docstring'ine `"comment"` eklenmesi
- `backend/WebArayuz/ai-generator.html`:
  - Adım başına "▶ Adımı Çalıştır" butonu
  - "Oturumu Başlat/Bitir" kontrolleri + durum göstergesi (Web/Mobil)
  - "+" menüsüne "💬 Yorum" seçeneği + yorum adımı render stili

## Kapsam Dışı

- Aynı kullanıcı için birden fazla eşzamanlı Web/Mobil oturumu (aynı platformda) — tek oturum
  yeterli, ihtiyaç çıkarsa ayrı bir istek olarak ele alınır.
- Oturum sırasında sekme/pencere manuel kapatılırsa (kullanıcı tarayıcıyı elle kapatırsa) net bir
  "oturum koptu" algılama/otomatik temizleme — sadece 15 dakikalık idle timeout ile örtük olarak
  ele alınıyor, gerçek zamanlı "session dead" tespiti yok.
- Yorum adımlarının senaryo dosyasına (steps.json) kaydedilip kaydedilmeyeceği: kaydedilir (diğer
  adımlar gibi `steps.json`'a yazılır), sadece script'e kod olarak dökülmez — bu davranış değişikliği
  gerektirmiyor çünkü kaydetme zaten tüm `steps_list`'i JSON'a yazıyor.

## Test Planı

- **Desktop:** Mevcut bir senaryoda 3 adım varken, 2. adımı "Adımı Çalıştır" ile tek başına koş,
  pencerenin açık kaldığını ve adımın doğru çalıştığını doğrula.
- **Web:** "Oturumu Başlat" → tarayıcı açılır (görünür/headless değil) → bir "git" + "tıkla" adımı
  "Adımı Çalıştır" ile tek tek koşulur, ikinci adımın ilk adımın bıraktığı sayfada çalıştığı
  doğrulanır → "Oturumu Bitir" → tarayıcı kapanır.
- **Yorum:** Bir senaryoya yorum adımı eklenip "Tümünü Çalıştır" ile koşulduğunda o adımın
  atlandığı (STEP_START/DONE üretmediği) ve sonraki adımların index'lerinin bozulmadığı doğrulanır.
