# AI Test Generator — Mobil Job Sistemi (Faz 1)

**Tarih:** 2026-07-26
**Kapsam:** AI Test Generator için Job (test paketi) yapısı — Faz 1: Mobil. Web ve Desktop aynı desene göre ayrı fazlarda eklenecek.

## Problem

AI Test Generator'da senaryolar tek tek, tek cihazda, manuel çalıştırılıyor. Kullanıcı birden çok senaryoyu birden çok telefonda paralel koşturmak ve bunu zamanlamak istiyor (ör. her sabah 09:00'da regresyon paketi).

## Neden yeni tablolar (eski Job/Device/Scenario değil)

`backend/models/db_models.py` içindeki `Job`, `JobScenario`, `JobDevice`, `JobExecution`, `TestResult`, `Device`, `Scenario` modelleri ve `job_service.py` hâlâ kod tabanında duruyor ama hiçbir router onları mount etmiyor (2026-06 temizliğinde `jobs_router`/`devices_router`/`scenarios_router` silindi). Ayrıca `Scenario` eski DB-satırı modeli; AI Generator senaryoları ise git workspace'te `ai_scenarios/{folder}/steps.json` + `script.py` olarak dosya bazlı tutuluyor. Eski modelleri AI Generator'a bağlamak yerine, AI Generator'a özel yeni bir tablo seti açıyoruz. Eski tablolara dokunulmuyor.

## Veri Modeli (yeni, `backend/models/db_models.py`'ye eklenecek)

- **AiJob**: `id, user_id, name, platform='mobile', created_at`
- **AiJobScenario**: `id, job_id (FK), scenario_folder (str)` — `ai_scenarios/{folder}` referansı
- **AiJobDevice**: `id, job_id (FK), device_id (str, ADB udid), device_name (str, snapshot)`
- **AiJobSchedule**: `id, job_id (FK), schedule_type ('once'|'daily'|'weekly'), run_at (datetime), weekday (int, nullable), enabled (bool), last_triggered_at (datetime, nullable)`
- **AiJobRun**: `id, job_id (FK), started_at, ended_at, status ('running'|'completed'|'interrupted'), trigger_type ('manual'|'scheduled'), total_cells, passed_cells, failed_cells`
- **AiJobRunResult**: `id, job_run_id (FK), scenario_folder, scenario_name, device_id, device_name, status ('queued'|'running'|'pass'|'fail'|'error'), started_at, ended_at, log_json` — `log_json` mevcut run-log formatındaki `steps: [{index, label, status}]` yapısıyla aynı.

Job silinirse cascade ile `AiJobScenario`/`AiJobDevice`/`AiJobSchedule` silinir; `AiJobRun`/`AiJobRunResult` geçmiş kaydı olarak kalır (job_id nullable'a çevrilmez, basitlik için job silinince run geçmişi de silinir — YAGNI, ihtiyaç olursa sonra ayrılır).

## Çalıştırma Motoru (`backend/services/ai_job_service.py`, yeni)

- `_generate_cell_script(steps_data, device)`: `ai_test_generator_router._generate_steps()` fonksiyonunu import edip, `steps_data['params']` (app_package, app_activity, appium_url) + hedef `device.device_id` ile yeniden script üretir. Kayıtlı `script.py` kullanılmaz çünkü içine eski cihazın device_id'si gömülü.
- `run_job(job_id, db, trigger_type)`:
  1. Aynı job için zaten "running" bir `AiJobRun` varsa 409 döner (job başına tek aktif koşum).
  2. `AiJobRun(status='running')` oluşturulur; hücre listesi = seçili senaryolar × seçili cihazlar (matris); her hücre için `AiJobRunResult(status='queued')` yazılır.
  3. Tüm hücreler `asyncio.gather` ile paralel başlatılır — her hücre `/execute` ile aynı subprocess+STEP_START/DONE/FAIL parse mantığını kullanır (kod tekrarını önlemek için mevcut `execute_script` içindeki stream mantığı ortak bir yardımcıya çıkarılır ve hem `/execute` hem job motoru onu kullanır).
  4. Her hücrenin durum değişikliği hem DB'ye (`AiJobRunResult` güncellenir) hem de o run'a bağlı WebSocket dinleyicilerine (`_run_subscribers: dict[run_id, list[WebSocket]]`, in-memory) yayınlanır.
  5. Tüm hücreler bitince `AiJobRun.status='completed'`, toplamlar güncellenir.
- Cihaz koşum sırasında koparsa/script patlarsa: sadece o hücre `error` olur, diğer hücreler etkilenmez (bağımsız subprocess'ler).

## Zamanlayıcı

`main.py`'de mevcut `_session_idle_reaper` deseniyle aynı: `asyncio.create_task(_ai_job_scheduler_loop())` uygulama açılışında başlar. 30 saniyede bir `AiJobSchedule` tablosunda `enabled=True` ve zamanı gelmiş kayıtları tarar, `run_job(trigger_type='scheduled')` çağırır, `last_triggered_at`'i günceller; `daily`/`weekly` için bir sonraki `run_at` hesaplanır.

Sunucu açılışında: durumu hâlâ `'running'` olan `AiJobRun`/`AiJobRunResult` kayıtları `'interrupted'` olarak işaretlenir (yarım kalmış koşumlar sonsuza kadar "running" görünmesin diye).

## API (`backend/routers/ai_job_router.py`, yeni, prefix `/api/ai-jobs`)

| Method | Path | Açıklama |
|---|---|---|
| POST | `/` | Job oluştur (name, scenario_folders[], device_ids[], schedule?) |
| GET | `/` | Kullanıcının job'larını listele |
| GET | `/{id}` | Job detay (senaryolar, cihazlar, schedule) |
| PUT | `/{id}` | Job güncelle |
| DELETE | `/{id}` | Job sil |
| POST | `/{id}/run` | Manuel tetikle → `job_run_id` döner |
| GET | `/{id}/runs` | Job'ın koşum geçmişi |
| GET | `/runs/{run_id}` | Koşum detay (tüm hücre sonuçları) |
| POST | `/runs/{run_id}/stop` | O koşumdaki tüm çalışan hücreleri durdur |
| WS | `/ws/{run_id}` | Hücre durumu canlı güncellemeleri |

## Frontend (`backend/WebArayuz/ai-jobs-mobile.html`, yeni sayfa)

- **Job oluştur formu**: isim, senaryo çoklu seçim (`GET /api/ai-generator/scenarios?platform=mobile`), cihaz çoklu seçim (`GET /api/ai-generator/adb/devices`), zamanlama bölümü (Şimdi Çalıştır / Zamanla → Tek seferlik tarih-saat / Tekrarlı gün+saat).
- **Job listesi**: Çalıştır / Düzenle / Sil / Geçmiş aksiyonları.
- **Matris canlı görünüm**: satır=senaryo, sütun=cihaz; hücre renkleri bekliyor(gri)/koşuyor(mavi, animasyonlu)/başarılı(yeşil)/başarısız(kırmızı)/hata(turuncu). Hücreye tıklayınca modal'da adım adım log (mevcut test-history.html'deki log görünümüyle tutarlı stil).
- Sidebar'a "Mobil Job'lar" linki eklenir (AI Test Generator bölümü altına).

## Test Planı

Manuel: 2 senaryo + 2 cihaz (emülatör/fiziksel) ile job oluştur → "Şimdi Çalıştır" → 4 hücrenin paralel koştuğunu, matrisin canlı güncellendiğini doğrula. Sonra "1 dakika sonrası" tek seferlik zamanlama kur, otomatik tetiklendiğini doğrula. Cihazlardan birini koşum sırasında ADB'den kopar, o hücrenin `error` olup diğerlerinin etkilenmediğini doğrula.
