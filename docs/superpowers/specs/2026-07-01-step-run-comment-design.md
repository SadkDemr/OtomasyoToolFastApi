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

Appium-Python-Client'ın (3.1.0) `webdriver.Remote` benzeri bir session-reconnect deseni
destekleyip desteklemediği (Selenium'da kanıtlanmış bir teknik, Appium client'ı Selenium'un
`RemoteWebDriver`'ından türediği için teorik olarak çalışmalı ama doğrulanmadı) — implementasyon
planında ilk adım bunu küçük bir spike ile doğrulamak olmalı. Doğrulanamazsa Mobil için Bölüm A
"sadece Desktop + Web" kapsamına daraltılabilir, Mobil ayrı ele alınır.

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
