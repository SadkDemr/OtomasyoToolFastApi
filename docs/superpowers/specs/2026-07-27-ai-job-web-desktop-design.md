# AI Test Generator — Job Sistemi: Web + Desktop (Faz 2)

**Tarih:** 2026-07-27
**Kapsam:** Faz 1'de (2026-07-26) yalnızca Mobil için kurulan AI Job sistemini Web (Selenium) ve Desktop (image-based) platformlarına genişletmek. Aynı desen, aynı tablolar — yeni migration yok.

## Problem

Mobil Job sistemi senaryo × cihaz matrisiyle paralel/zamanlanmış koşum sağlıyor. Web ve Desktop senaryoları hâlâ AI Test Generator sayfasında tek tek, manuel çalıştırılıyor. Kullanıcı aynı paket/zamanlama deneyimini Web ve Desktop için de istiyor.

## Neden yeni tablo/migration yok

`AiJob.platform` alanı zaten generic (`default="mobile"` ama herhangi bir string kabul eder). `AiJobDevice.device_id`/`device_name` kolonları da generic string — "bir hücrenin hangi paralel birimde koştuğu" bilgisini tutuyorlar, ADB'ye özel bir kısıtı yok. Bu yüzden şema değişmeden, sadece **servis mantığının platforma göre dallanmasıyla** Web ve Desktop eklenebilir.

`device_id` alanının platforma göre anlamı:
- **mobile** (değişmedi): ADB cihaz serial'i
- **web**: tarayıcı adı — `"chrome"` | `"firefox"` | `"edge"` (sabit liste, ADB gibi keşif gerektirmez)
- **desktop**: kullanılmaz — job'a hiç `AiJobDevice` satırı eklenmez; çalıştırma motoru tek sabit sözde-birim (`device_id="desktop"`, `device_name="Masaüstü"`) ile hücre üretir. Kullanıcıya cihaz/tarayıcı seçim adımı hiç gösterilmez.

## Paralellik Modeli

Faz 1'deki `device_groups` mantığı (`ai_job_service._run_job_cells`) değişmiyor: gruplar birbirine paralel, grup içi hücreler sıralı.
- **Web**: her seçili tarayıcı bir grup → tarayıcılar paralel, aynı tarayıcıdaki senaryolar sıralı (Faz 1'deki "cihazlar paralel" ile birebir aynı kod yolu, sadece `device_id` artık ADB serial değil tarayıcı adı).
- **Desktop**: tek grup (`"desktop"`) → tüm senaryolar tamamen sıralı. Bu, mevcut global `_get_desktop_lock()` kısıtıyla (aynı anda tek desktop testi) zaten tutarlı.

## Servis Katmanı Değişiklikleri (`backend/services/ai_job_service.py`)

- `create_job`/`update_job`: `platform: str` parametresi eklenir, `AiJob.platform`'a yazılır.
  - `platform == "desktop"` ise `device_ids` boş olabilir (validasyon atlanır); dahili olarak tek `AiJobDevice(device_id="desktop", device_name="Masaüstü")` satırı eklenir.
  - `platform == "web"` ise `device_ids` yalnızca `{"chrome", "firefox", "edge"}` alt kümesi olabilir; aksi halde `ValueError`.
  - `platform == "mobile"`: mevcut davranış (ADB serial, boş olamaz) değişmez.
- `_generate_cell_script(steps_data, device_id, system_port)` platform bazlı dallanır (job'ın `platform`'u parametre olarak eklenir):
  - `mobile` (değişmedi): `GenerateRequest(platform="mobile", device_id=..., system_port=..., app_package=params.app_package, app_activity=params.app_activity, appium_url=params.appium_url)` → `_build_mobile_template`
  - `web`: `GenerateRequest(platform="web", browser=device_id, target_url=params.target_url)` → `_build_web_template`
  - `desktop`: `GenerateRequest(platform="desktop", app_path=params.app_path, window_title=params.window_title, reuse_instance=params.get("reuse_instance", True))` → `_build_desktop_template`
  - `system_port` yalnızca mobile'da anlamlı; web/desktop için `_acquire_system_port` hiç çağrılmaz.
- **Desktop kilit entegrasyonu**: `run_job` platform desktop iken, hücreleri kuyruğa almadan önce `ai_test_generator_router._get_desktop_lock()` kontrol edilir — doluysa `JobAlreadyRunningError` ile aynı 409 deseninde reddedilir (manuel bir desktop testiyle veya başka bir desktop job'la çakışmayı engellemek için). Kilit, `_run_job_cells` içinde desktop hücreleri boyunca tutulur, `finally`'de serbest bırakılır (manuel `/execute`'daki acquire/release desenine paralel).
- Web hücrelerinde ek kilit/kısıt yok — birden fazla tarayıcı süreci paralel çalışabilir (bugünkü mobil cihazlar gibi).

## API Değişiklikleri (`backend/routers/ai_job_router.py`)

- `JobIn` şemasına `platform: str` eklenir (`"mobile" | "web" | "desktop"`, sunucu tarafında doğrulanır).
- `GET /api/ai-jobs?platform=` sorgu parametresi eklenir (frontend'deki sekmeye göre filtreleme için); parametre verilmezse tüm platformlar döner.
- Diğer endpoint'ler (run/runs/stop/ws) değişmeden kalır — zaten `job_id`/`run_id` bazlı, platforma duyarsız.

## Frontend (`backend/WebArayuz/ai-jobs-mobile.html` → `ai-jobs.html` olarak birleştirilir)

- Sayfa başına **Mobil / Web / Desktop** sekme çubuğu eklenir. Aktif sekme (`currentPlatform` state) şunları belirler:
  - Senaryo checklist filtresi: `s.platform === currentPlatform`
  - "Çalıştırma birimi" checklist kaynağı: mobile → `GET /ai-gen/adb/devices` (değişmedi); web → sabit `["chrome","firefox","edge"]` listesi; desktop → **checklist adımı tamamen gizlenir**, gönderilen `device_ids` boş dizi.
  - Job listesi: `GET /api/ai-jobs?platform=currentPlatform` ile filtrelenir.
  - Koşum matrisi sütun başlıkları: mobile/web'de `device_id` (cihaz/tarayıcı adı); desktop'ta tek sütun, başlık "Sonuç".
- Job oluşturma modalında platform alanı kullanıcıya gösterilmez — POST/PUT body'sine aktif sekmeden otomatik eklenir.
- Sidebar (`js/sidebar.js`): `item("ai-jobs-mobile", ..., "Mobil Job'lar")` → `item("ai-jobs", "&#128197;", "AI Job'lar")`.
- Dosya yeniden adlandırıldığı için eski `ai-jobs-mobile.html`'e olan tek referans (sidebar) güncellenir; başka sayfa bu dosyaya link vermiyor (doğrulandı).

## Hata Yönetimi

- Desktop job tetiklenirken global kilit doluysa: run hiç oluşturulmadan `ValueError`/409 ile reddedilir — kullanıcı "Başka bir desktop testi çalışıyor, bekleyin" mesajını görür (mevcut manuel `/execute` 423 mesajıyla tutarlı ton).
- Web'de tarayıcı sürücüsü makinede yoksa (ör. geckodriver eksik): hücre `error` statüsüne düşer, `log_json.error` içinde exception metni görünür — Faz 1'deki hücre hata akışıyla birebir aynı, yeni kod gerekmez.
- Geçersiz `device_ids` (web için tanınmayan tarayıcı adı, mobilde/webde boş liste): `create_job`/`update_job` `ValueError` fırlatır → router 400 döner (Faz 1'deki `_validate_scenario_folders` deseniyle aynı yaklaşım).

## Test Planı

Manuel:
1. Web job: 2 senaryo × Chrome+Firefox seç, "Şimdi Çalıştır" → 2 grubun paralel, grup içi 2 senaryonun sıralı koştuğunu; matrisin WS ile canlı güncellendiğini doğrula.
2. Desktop job: 2 senaryo seç (cihaz adımı görünmemeli), çalıştır → tek sütunlu matris, senaryoların sırayla koştuğunu doğrula.
3. Desktop job çalışırken AI Test Generator sayfasından manuel bir desktop testi başlatmayı dene → 423/409 ile reddedildiğini doğrula (ve tersi: manuel test çalışırken job tetiklemeyi dene).
4. Sekmeler arası geçişte senaryo/job listelerinin doğru filtrelendiğini, sidebar linkinin çalıştığını doğrula.
