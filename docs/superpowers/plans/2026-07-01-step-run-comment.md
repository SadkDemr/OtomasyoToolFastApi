# Adım Çalıştırma & Yorum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI Test Generator'a (1) senaryodaki tek bir adımı, önceki adımların bıraktığı durumdan
devam ederek (baştan koşmadan) çalıştırma özelliği, (2) çalışmayan, sadece açıklama amaçlı
"yorum" adım tipi ve (3) yazılmış, mevcut bir adımı silmeden "// gibi" devre dışı bırakma
(yorum satırına alma) özelliği eklemek.

**Architecture:** Desktop zaten `reuse_instance` ile tek-adım koşumunu doğal olarak destekliyor —
sadece frontend'den `/generate` (`steps_list=[tek_adim]`) + `/execute` çağrısı yeterli. Web/Mobil
için, script'i "bağımsız subprocess çalıştır" mimarisini koruyarak, Selenium/Appium'un düşük
seviyeli session-reconnect tekniğiyle (`session_id` + `command_executor` URL'i ile var olan
tarayıcı/uygulama session'ına yeniden bağlanma) kalıcı bir "oturum" simüle edilir: `Oturum Başlat`
scripti driver'ı `quit()` etmeden bırakır, `Adımı Çalıştır` scripti aynı session'a bağlanıp tek
adımı çalıştırır, `Oturumu Bitir` son kez bağlanıp kapatır. Yorum adımı, `StepItem.type="comment"`
olarak eklenir; kod üretmez, `STEP_START`/`STEP_DONE` sarmalayıcısı almaz.

**Tech Stack:** Python (backend, `ai_test_generator_router.py` + yeni `services/session_reconnect.py`),
Selenium 4.15.2, Appium-Python-Client 3.1.0, düz HTML/JS (frontend). Test framework yok (proje
genelinde pytest kullanılmıyor); doğrulamalar `backend/venv/Scripts/python.exe` ile çalıştırılan
bağımsız kontrol scriptleriyle yapılır.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-01-step-run-comment-design.md` — bu plan o tasarımın
  uygulamasıdır.
- **Task 1'in sonucu Task 6'yı (Mobil session_mode) şarta bağlar.** Appium reconnect spike
  başarısız olursa, Task 6 ATLANIR ve bu durum insan onayına sunulur (spec'te "Bilinen Risk"
  olarak zaten işaretlenmişti) — plan bu noktada durur, geri kalan task'lar (Desktop + Web +
  Yorum) bağımsız tamamlanabilir.
- Aktif oturum kullanıcı+platform başına TEK'tir (`_active_sessions` anahtarı `(user_id, platform)`).
- İdle timeout: **15 dakika** — bu süre boşta kalan oturumlar arka planda otomatik kapatılır.
- "Oturumu Başlat" modunda tarayıcı **headless DEĞİL** (görünür) — "Tümünü Çalıştır" (mevcut,
  değişmeyen davranış) headless kalmaya devam eder.
- Otomatik oturum başlatma YOK — kullanıcı "Adımı Çalıştır" tıklarken aktif oturum yoksa net bir
  uyarı gösterilir, sessizce oturum açılmaz.
- Proje kökünde boşluk içeren yol var (`C:\Users\Sadik Demir\...`) — tüm komutlarda çift tırnak.

---

### Task 1: Spike — Selenium/Appium session-reconnect doğrulaması

**Files:**
- Create: `backend/services/session_reconnect.py`
- Test: geçici doğrulama scriptleri (scratchpad, kalıcı değil)

**Interfaces:**
- Produces: `attach_selenium_session(command_executor_url: str, session_id: str) -> selenium.webdriver.Remote`
  ve `attach_appium_session(command_executor_url: str, session_id: str) -> appium.webdriver.webdriver.WebDriver`
  — ikisi de YENİ session AÇMADAN, var olan session'a bağlı bir driver nesnesi döndürür.
- Consumes: yok (bağımsız, ilk task).

Bu task'ın amacı: script'i `driver.quit()` çağırmadan bitirip süreç sonlandığında tarayıcının/
uygulamanın açık kalıp kalmadığını, ve sonraki bir Python sürecinden aynı session'a
`session_id`+`command_executor` ile yeniden bağlanıp komut gönderilebildiğini kanıtlamak.

- [ ] **Step 1: `session_reconnect.py`'ı yaz**

```python
"""
Session Reconnect Helpers
--------------------------
Var olan bir Selenium/Appium WebDriver session'ına, session_id + command_executor URL'i
ile YENİ session açmadan yeniden bağlanır. "Oturum Başlat" scripti driver'ı quit() etmeden
bırakır; bu fonksiyonlar sonraki bir Python sürecinden o session'a geri bağlanmak için kullanılır.
"""
from selenium.webdriver import Remote as _SeleniumRemote
from selenium.webdriver.chrome.options import Options as _ChromeOptions


def attach_selenium_session(command_executor_url: str, session_id: str) -> _SeleniumRemote:
    class _AttachedRemote(_SeleniumRemote):
        def start_session(self, capabilities):
            self.session_id = session_id
            self.capabilities = {}

    return _AttachedRemote(command_executor=command_executor_url, options=_ChromeOptions())


def attach_appium_session(command_executor_url: str, session_id: str):
    from appium.webdriver.webdriver import WebDriver as _AppiumRemote
    from appium.options.android import UiAutomator2Options

    class _AttachedAppiumRemote(_AppiumRemote):
        def start_session(self, capabilities):
            self.session_id = session_id
            self.capabilities = {}

    return _AttachedAppiumRemote(command_executor_url, options=UiAutomator2Options())
```

- [ ] **Step 2: Selenium (Web) spike — session'ı başlat, quit() etmeden çık**

Scratchpad'e `spike_web_start.py` yaz (kendi scratchpad dizinini kullan), çalıştır:

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()  # headless YOK - görünür pencere
driver = webdriver.Chrome(options=opts)
driver.get("data:text/html,<div id='x'>spike-web-1</div>")
print("SESSION_ID:", driver.session_id)
print("EXECUTOR_URL:", driver.command_executor._url)
# driver.quit() cagirmiyoruz - bilerek
```

Run: `"backend/venv/Scripts/python.exe" spike_web_start.py` — çıktıdan `SESSION_ID` ve
`EXECUTOR_URL` değerlerini not al. Script bitince (birkaç saniye içinde) görev yöneticisinde
`chromedriver.exe`/`chrome.exe` süreçlerinin hâlâ çalıştığını doğrula (`tasklist | findstr chrome`
komutuyla, ya da PowerShell `Get-Process chrome*`).

- [ ] **Step 3: Selenium (Web) spike — ikinci süreçten yeniden bağlan**

Scratchpad'e `spike_web_attach.py` yaz, Step 2'de aldığın `SESSION_ID`/`EXECUTOR_URL` değerlerini
elle yapıştır:

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from services.session_reconnect import attach_selenium_session

driver = attach_selenium_session("<EXECUTOR_URL_BURAYA>", "<SESSION_ID_BURAYA>")
print("TITLE:", driver.title)
driver.execute_script("document.title = 'attached-ok'")
print("NEW_TITLE:", driver.title)
# yine quit() cagirmiyoruz
```

Run: bekle `NEW_TITLE: attached-ok` çıktısı — bu, İKİNCİ bir Python sürecinin AYNI tarayıcı
session'ına bağlanıp komut çalıştırabildiğini kanıtlar (yeni bir tarayıcı AÇILMADI). Eğer
`SessionNotCreatedException` veya bağlantı hatası alırsan, Selenium 4.15.2'nin `Remote.__init__`
imzasını (`backend/venv/Lib/site-packages/selenium/webdriver/remote/webdriver.py`) incele ve
`start_session` override'ını gerekirse uyarla (ör. `capabilities` parametresi farklı isimli
olabilir) — bu spike'ın asıl amacı bu.

- [ ] **Step 4: Selenium (Web) spike temizliği**

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from services.session_reconnect import attach_selenium_session
driver = attach_selenium_session("<EXECUTOR_URL>", "<SESSION_ID>")
driver.quit()
print("CLOSED")
```

- [ ] **Step 5: Appium spike (fiziksel/emulator Android cihaz + Appium sunucusu gerekli)**

Eğer bağlı bir Android cihaz/emulator ve çalışan bir Appium sunucusu (`appium` komutu) YOKSA bu
adımı atla, raporunda "Appium spike ortam eksikliği nedeniyle atlandı, Task 6 insan onayına
sunulmalı" olarak belirt — bu BLOCKED değil, DONE_WITH_CONCERNS'tür (Web kısmı zaten kanıtlandı).

Ortam varsa: Step 2-4 ile aynı desende, `webdriver.Remote(appium_url, options=UiAutomator2Options())`
ile başlat (bkz. `_build_mobile_template`, `backend/routers/ai_test_generator_router.py:2078`),
`driver.session_id`/`driver.command_executor._url` al, quit() etme; ikinci scriptte
`attach_appium_session(...)` ile bağlanıp `driver.current_package` gibi zararsız bir komut çalıştır,
başarılıysa `driver.quit()` ile kapat.

- [ ] **Step 6: Bulguları kaydet ve commit et**

`docs/superpowers/specs/2026-07-01-step-run-comment-design.md`'deki "Bilinen Risk / Doğrulama
Gereken Varsayım" bölümünü, spike sonucuna göre güncelle (Web ✅/❌, Mobil ✅/❌/atlandı — hangi
sebeple).

```bash
git add backend/services/session_reconnect.py docs/superpowers/specs/2026-07-01-step-run-comment-design.md
git commit -m "spike: selenium/appium session-reconnect dogrulamasi"
```

---

### Task 2: Backend — Yorum (comment) adım tipi

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `StepItem.type` docstring (satır ~71)
  - `_generate_steps()` — adım tipi dağıtımı (satır ~2753-2763) ve birleştirme döngüsü (satır ~2791)

**Interfaces:**
- Produces: `StepItem(type="comment", content="...")` → `_generate_steps()` çıktısında bu adım için
  `report` girdisinde `"method": "comment"`, üretilen kodda sadece `# [YORUM] {content}` satırı
  (STEP_START/STEP_DONE yok).
- Consumes: mevcut `StepItem`, `_generate_steps()` akışı.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_comment_step.py`:

```python
import sys, asyncio
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _generate_steps, StepItem, GenerateRequest

req = GenerateRequest(platform="web", steps_list=[
    StepItem(type="comment", content="Bu bir yorum"),
    StepItem(type="text", content='"data:text/html,<div>x</div>" git'),
])
steps_code, report = asyncio.run(_generate_steps(req))

assert report[0]["method"] == "comment", f"FAIL: beklenen method=comment, gelen={report[0]}"
assert "# [YORUM] Bu bir yorum" in steps_code, "FAIL: yorum satiri script'te yok"
assert "STEP_START:0" not in steps_code, "FAIL: yorum adimi STEP_START uretmemeli"
assert "STEP_START:1" in steps_code, "FAIL: ikinci (text) adim STEP_START:1 uretmeli (index kaymamali)"
print("OK")
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_comment_step.py yolu>`
Expected: `AssertionError: FAIL: beklenen method=comment...` (comment tipi henüz tanınmıyor, `else`
dalına düşüp LLM/TODO işlemi görür)

- [ ] **Step 3: `StepItem.type` docstring'ini güncelle**

Öncesi (satır ~71):
```python
    type:          str = "text"   # "text" | "image" | "sql" | "api"
```
Sonrası:
```python
    type:          str = "text"   # "text" | "image" | "sql" | "api" | "comment"
```

- [ ] **Step 4: `_generate_steps()`'e comment dalı ekle**

Öncesi:
```python
        elif item.type == "api":
            code = "_check_stop()\n" + _api_step_code(item, idx)
            code_lines.append(("rule", item.content or f"API {idx+1}", code))
        else:
```
Sonrası:
```python
        elif item.type == "api":
            code = "_check_stop()\n" + _api_step_code(item, idx)
            code_lines.append(("rule", item.content or f"API {idx+1}", code))
        elif item.type == "comment":
            code_lines.append(("comment", item.content or f"Yorum {idx+1}", f"# [YORUM] {item.content}"))
        else:
```

- [ ] **Step 5: Birleştirme döngüsünde "comment"i rule/image ile aynı yola al**

Öncesi:
```python
    final_lines = []
    for idx, (kind, step, rule_code) in enumerate(code_lines):
        if kind in ("rule", "image"):
            final_lines.append(rule_code)
            report.append({"step": step, "method": kind, "code": rule_code, "index": idx})
```
Sonrası:
```python
    final_lines = []
    for idx, (kind, step, rule_code) in enumerate(code_lines):
        if kind in ("rule", "image", "comment"):
            final_lines.append(rule_code)
            report.append({"step": step, "method": kind, "code": rule_code, "index": idx})
```

**Not:** Bu ikinci değişiklik olmadan comment adımları `else` dalına (LLM/TODO işleme) düşer ve
`# TODO (anlasilamadi): ...` haline gelir — Step 1'in kontrol scripti bunu da yakalar.

- [ ] **Step 6: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: yorum (comment) adim tipi eklendi"
```

---

### Task 3: Frontend — Yorum adımı UI

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html`
  - Step toolbar (satır ~1054-1072) — "💬 Yorum" butonu
  - `renderStepRow()` (satır ~1739 civarı) — `TYPE_META` + yeni `else if (s.type === "comment")` dalı
  - Yeni `window.addCommentStep` fonksiyonu (satır ~1697 `addApiStep` yakınına)

**Interfaces:**
- Consumes: mevcut `steps` dizisi, `renderStepList()`, `updateStepContent()`.
- Produces: yok (UI-only, başka task buna bağımlı değil).

- [ ] **Step 1: `addCommentStep` fonksiyonunu ekle**

`window.addApiStep` fonksiyonunun hemen altına (satır ~1703'ten sonra) ekle:

```javascript
    window.addCommentStep = function() {
        steps.push({ type: "comment", content: "", status: null });
        renderStepList();
        updateGenerateBtn();
    };
```

- [ ] **Step 2: Toolbar'a "💬 Yorum" butonu ekle**

Öncesi (satır ~1068-1071):
```html
                        <button class="btn-add-step api-btn" onclick="addApiStep()">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
                            API
                        </button>
```
Sonrası:
```html
                        <button class="btn-add-step api-btn" onclick="addApiStep()">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
                            API
                        </button>
                        <button class="btn-add-step comment-btn" onclick="addCommentStep()">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                            Yorum
                        </button>
```

- [ ] **Step 3: `TYPE_META`'ya comment ekle**

Öncesi (satır ~1743-1748):
```javascript
        const TYPE_META = {
            text:  { label: "Metin",  cls: "text" },
            image: { label: "Görsel", cls: "image" },
            sql:   { label: "SQL",    cls: "sql" },
            api:   { label: "API",    cls: "api" },
        };
```
Sonrası:
```javascript
        const TYPE_META = {
            text:    { label: "Metin",  cls: "text" },
            image:   { label: "Görsel", cls: "image" },
            sql:     { label: "SQL",    cls: "sql" },
            api:     { label: "API",    cls: "api" },
            comment: { label: "Yorum",  cls: "comment" },
        };
```

- [ ] **Step 4: `renderStepRow()`'a comment dalı ekle**

Öncesi (satır ~1753-1756):
```javascript
        if (s.type === "text") {
            contentHtml = `<input class="step-content-input" type="text" value="${escHtml(s.content)}"
                placeholder='Adım açıklaması...  (değişken: {{ad}} yaz / "hedef" oku {{ad}})' oninput="updateStepContent(${i}, this.value)">`;

        } else if (s.type === "image") {
```
Sonrası:
```javascript
        if (s.type === "text") {
            contentHtml = `<input class="step-content-input" type="text" value="${escHtml(s.content)}"
                placeholder='Adım açıklaması...  (değişken: {{ad}} yaz / "hedef" oku {{ad}})' oninput="updateStepContent(${i}, this.value)">`;

        } else if (s.type === "comment") {
            contentHtml = `<input class="step-content-input" type="text" style="font-style:italic; opacity:0.75;"
                value="${escHtml(s.content)}" placeholder="Yorum metni..." oninput="updateStepContent(${i}, this.value)">`;

        } else if (s.type === "image") {
```

**Not:** Yorum adımı için ayrıca bir "Çalıştır" durumu/ikonu YOK — `setStepStatus`/`STEP_START`
zaten bu adım için hiç tetiklenmeyecek (Task 2'de sağlandı), bu yüzden ek bir UI değişikliği
gerekmiyor; `statusIcon` her zaman "·" (boş) kalacak, bu kabul edilebilir.

- [ ] **Step 5: Manuel doğrulama**

Sunucuyu başlat (`cd backend && python main.py`), `/ui/ai-generator.html` sayfasını aç, "💬 Yorum"
butonuna tıkla, bir yorum adımı eklenip italik/soluk göründüğünü doğrula. Script üret + çalıştır,
yorum adımının koşum sırasında atlandığını (hiç "running" durumuna geçmediğini) gözle doğrula.

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "feat(ui): yorum adimi ekleme arayuzu"
```

---

### Task 4: Backend — `_active_sessions` state + idle-timeout arka plan görevi

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py` (modül seviyesi, `_running_processes` dict'inin
  tanımlandığı yerin yakınına — `Grep "_running_processes: dict" ai_test_generator_router.py` ile bul)

**Interfaces:**
- Produces: `_active_sessions: dict[tuple[int, str], dict]` (anahtar `(user_id, platform)`, değer
  `{"session_id": str, "command_executor_url": str, "started_at": float, "last_used_at": float}`),
  `_touch_session(user_id, platform)` (last_used_at günceller), `_get_session(user_id, platform) ->
  dict | None`, `_remove_session(user_id, platform)`.
- Consumes: yok (bağımsız state).

- [ ] **Step 1: Mevcut `_running_processes` tanımını bul**

```bash
grep -n "_running_processes" "backend/routers/ai_test_generator_router.py" | head -5
```

- [ ] **Step 2: Kontrol scriptini yaz (henüz FAIL vermeli)**

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _active_sessions, _touch_session, _get_session, _remove_session

assert _get_session(1, "web") is None, "FAIL: bos state'te None donmeli"
_active_sessions[(1, "web")] = {"session_id": "s1", "command_executor_url": "http://x", "started_at": 0.0, "last_used_at": 0.0}
sess = _get_session(1, "web")
assert sess["session_id"] == "s1", f"FAIL: {sess}"
_touch_session(1, "web")
assert _active_sessions[(1, "web")]["last_used_at"] > 0.0, "FAIL: last_used_at guncellenmedi"
_remove_session(1, "web")
assert _get_session(1, "web") is None, "FAIL: remove sonrasi hala var"
print("OK")
```

Run: `"backend/venv/Scripts/python.exe" <script yolu>` — Expected: `ImportError` (henüz tanımlı değil)

- [ ] **Step 3: State + yardımcı fonksiyonları ekle**

`_running_processes: dict[str, subprocess.Popen] = {}` tanımının hemen altına ekle:

```python
import time as _time_mod

_active_sessions: dict[tuple[int, str], dict] = {}   # (user_id, platform) -> session info
_SESSION_IDLE_TIMEOUT_SEC = 15 * 60


def _touch_session(user_id: int, platform: str) -> None:
    key = (user_id, platform)
    if key in _active_sessions:
        _active_sessions[key]["last_used_at"] = _time_mod.time()


def _get_session(user_id: int, platform: str) -> dict | None:
    return _active_sessions.get((user_id, platform))


def _remove_session(user_id: int, platform: str) -> None:
    _active_sessions.pop((user_id, platform), None)


async def _session_idle_reaper():
    """15 dakika boşta kalan oturumları otomatik kapatır (driver.quit())."""
    while True:
        await asyncio.sleep(60)
        now = _time_mod.time()
        for key in list(_active_sessions.keys()):
            info = _active_sessions.get(key)
            if not info:
                continue
            if now - info["last_used_at"] > _SESSION_IDLE_TIMEOUT_SEC:
                user_id, platform = key
                try:
                    if platform == "mobile":
                        from services.session_reconnect import attach_appium_session
                        d = attach_appium_session(info["command_executor_url"], info["session_id"])
                    else:
                        from services.session_reconnect import attach_selenium_session
                        d = attach_selenium_session(info["command_executor_url"], info["session_id"])
                    d.quit()
                except Exception as e:
                    print(f"[SESSION-REAPER] Kapatma hatasi ({key}): {e}")
                _remove_session(user_id, platform)
                print(f"[SESSION-REAPER] Idle oturum kapatildi: user={user_id} platform={platform}")
```

- [ ] **Step 4: Reaper görevini `main.py`'da başlat**

`backend/main.py` içinde uygulama başlangıcında (mevcut ADB device monitor loop'un başlatıldığı
yerin yanına — `grep -n "asyncio.create_task\|@app.on_event\|lifespan" backend/main.py` ile bul)
şu satırı ekle (import + task oluşturma):

```python
from routers.ai_test_generator_router import _session_idle_reaper
# ... mevcut startup bloğunda ...
asyncio.create_task(_session_idle_reaper())
```

(Tam entegrasyon noktası mevcut startup mekanizmasına bağlı — bu adımı uygularken `main.py`'daki
ADB monitor loop'un NASIL başlatıldığını [`asyncio.create_task` mi, `@app.on_event("startup")` mu,
yoksa `lifespan` context manager mı] birebir kopyala, aynı desene uy.)

- [ ] **Step 5: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/ai_test_generator_router.py backend/main.py
git commit -m "feat: aktif oturum state ve idle-timeout reaper eklendi"
```

---

### Task 5: Backend — `_build_web_template`'e `session_mode` parametresi

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py` — `_build_web_template()` (satır ~2119)

**Interfaces:**
- Produces: `_build_web_template(req, steps_code, session_mode="fresh", session_id="", command_executor_url="")`
  — `session_mode`: `"fresh"` (mevcut davranış, değişmez), `"start"` (headless kapalı + sonda quit
  yerine session bilgisi print eder), `"attach"` (var olan session'a bağlanır, quit YOK), `"end"`
  (bağlanır + quit).
- Consumes: Task 1'in `services/session_reconnect.py` modülü (sadece `"attach"`/`"end"` modunda,
  script içine gömülecek import olarak).

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli — fonksiyon imzası henüz session_mode almıyor)**

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _build_web_template, GenerateRequest

req = GenerateRequest(platform="web")

script_fresh = _build_web_template(req, "", session_mode="fresh")
assert "driver.quit()" in script_fresh, "FAIL: fresh modda quit olmali"
assert "webdriver.Chrome(" in script_fresh or "webdriver.Firefox(" in script_fresh, "FAIL: fresh modda normal baslatma olmali"

script_start = _build_web_template(req, "", session_mode="start")
assert "driver.quit()" not in script_start, "FAIL: start modda quit OLMAMALI"
assert "SESSION_ID:" in script_start, "FAIL: start modu session bilgisini yazdirmali"
assert "--headless" not in script_start, "FAIL: start modu headless OLMAMALI"

script_attach = _build_web_template(req, "", session_mode="attach", session_id="s1", command_executor_url="http://x")
assert "attach_selenium_session" in script_attach, "FAIL: attach modu reconnect helper'ini kullanmali"
assert "driver.quit()" not in script_attach, "FAIL: attach modda quit OLMAMALI"

script_end = _build_web_template(req, "", session_mode="end", session_id="s1", command_executor_url="http://x")
assert "attach_selenium_session" in script_end, "FAIL: end modu once baglanmali"
assert "driver.quit()" in script_end, "FAIL: end modu quit ETMELI"

print("OK")
```

Run: Expected `TypeError: _build_web_template() got an unexpected keyword argument 'session_mode'`

- [ ] **Step 2: `_build_web_template`'in EN BAŞINA `attach`/`end` erken-dönüş dalını ekle**

Fonksiyon imzasını güncelle. Öncesi:
```python
def _build_web_template(req: GenerateRequest, steps_code: str) -> str:
    browser = (req.browser or "chrome").lower()
    url     = (req.target_url or "").strip()
```
Sonrası (imza + yeni erken-dönüş bloğu, mevcut `browser`/`url` satırlarından SONRA eklenir):
```python
def _build_web_template(
    req: GenerateRequest,
    steps_code: str,
    session_mode: str = "fresh",
    session_id: str = "",
    command_executor_url: str = "",
) -> str:
    browser = (req.browser or "chrome").lower()
    url     = (req.target_url or "").strip()

    if session_mode in ("attach", "end"):
        lines = [
            "# -*- coding: utf-8 -*-",
            "import sys",
            f'sys.path.insert(0, r"{_ROUTER_BASE_DIR}")',
            "from services.session_reconnect import attach_selenium_session",
            "from selenium.webdriver.common.by import By",
            "from selenium.webdriver.support.ui import WebDriverWait",
            "from selenium.webdriver.support import expected_conditions as EC",
            "import time",
            "_VARS = {}  # adımlar arası değişken havuzu",
            "def _sub_vars(_s):",
            "    for _k, _v in _VARS.items():",
            "        _s = _s.replace('{{' + _k + '}}', str(_v))",
            "    return _s",
            "",
            f"driver = attach_selenium_session({command_executor_url!r}, {session_id!r})",
            "wait = WebDriverWait(driver, 10)",
            "",
            STOP_HELPER,
            IMAGE_HELPER,
            VISION_HELPER_WEB,
            "",
            "try:",
        ]
        for line in steps_code.splitlines():
            lines.append("    " + line if line.strip() else "")
        if session_mode == "end":
            lines += [
                "",
                "except Exception as e:",
                '    print(f"HATA: {e}")',
                "finally:",
                "    driver.quit()",
                '    print("SESSION_ENDED")',
            ]
        else:  # attach - quit YOK
            lines += [
                "",
                "except Exception as e:",
                '    print(f"HATA: {e}")',
                "    raise",
            ]
        return "\n".join(lines)

    # session_mode in ("fresh", "start") - asagidaki mevcut kod aynen devam eder
```

- [ ] **Step 3: `"fresh"`/`"start"` dalında headless satırını koşullu yap**

Chrome dalı — öncesi (`grep -n "headless=new" backend/routers/ai_test_generator_router.py` ile bul,
~satır 2155):
```python
        driver_setup = (
            "from selenium.webdriver.chrome.options import Options as _CrOpts\n"
            "_cr_opts = _CrOpts()\n"
            "_cr_opts.add_argument('--headless=new')\n"
```
Sonrası:
```python
        _cr_headless = "" if session_mode == "start" else "_cr_opts.add_argument('--headless=new')\n"
        driver_setup = (
            "from selenium.webdriver.chrome.options import Options as _CrOpts\n"
            "_cr_opts = _CrOpts()\n"
            f"{_cr_headless}"
```
Aynı deseni firefox dalındaki `"_fx_opts.add_argument('--headless')\n"` ve edge dalındaki
`"_edge_opts.add_argument('--headless')\n"` satırları için de uygula (`_fx_headless`,
`_edge_headless` değişkenleriyle, aynı `"" if session_mode == "start" else ...` mantığı).

- [ ] **Step 4: Sondaki `finally` bloğunu koşullu yap + `"start"` modunda session bilgisini yazdır**

Öncesi (`grep -n '"finally:"' backend/routers/ai_test_generator_router.py` ile bul):
```python
        "finally:",
        "    driver.quit()",
    ]

    return "\n".join(lines)
```
Sonrası:
```python
        "finally:",
        ("    pass" if session_mode == "start" else "    driver.quit()"),
    ] + (
        ["", 'print("SESSION_ID:", driver.session_id)', 'print("EXECUTOR_URL:", driver.command_executor._url)']
        if session_mode == "start" else []
    )

    return "\n".join(lines)
```

- [ ] **Step 5: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: _build_web_template'e session_mode (start/attach/end) eklendi"
```

---

### Task 6: Backend — `_build_mobile_template`'e `session_mode` parametresi

**KOŞULLU TASK — sadece Task 1'in Appium spike'ı (Step 5) başarılıysa uygula.** Başarısız/atlandıysa
bu task'ı SKIP et, insan onayına sun (spec'te zaten "Bilinen Risk" olarak işaretlenmişti), Task 7'de
mobil `/session/*` endpoint'lerini eklemeden geç (sadece web+desktop).

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py` — `_build_mobile_template()` (satır ~2006)

**Interfaces:**
- Produces: `_build_mobile_template(req, steps_code, session_mode="fresh", session_id="", command_executor_url="")`
  — Task 5 ile birebir aynı `session_mode` sözleşmesi (`fresh`/`start`/`attach`/`end`).
- Consumes: Task 1'in `attach_appium_session`.

- [ ] **Step 1: Kontrol scriptini yaz (Task 5'teki ile birebir aynı desen, mobile için)**

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _build_mobile_template, GenerateRequest

req = GenerateRequest(platform="mobile", app_package="com.example.app")

script_fresh = _build_mobile_template(req, "", session_mode="fresh")
assert "webdriver.Remote(" in script_fresh and "attach_appium_session" not in script_fresh
assert "driver.quit()" in script_fresh

script_attach = _build_mobile_template(req, "", session_mode="attach", session_id="s1", command_executor_url="http://x:4723")
assert "attach_appium_session" in script_attach
assert "driver.quit()" not in script_attach

print("OK")
```

- [ ] **Step 2: `_build_mobile_template`'in EN BAŞINA `attach`/`end` erken-dönüş dalını ekle**

Task 5 Step 2 ile AYNI desen, imza:
```python
def _build_mobile_template(
    req: GenerateRequest,
    steps_code: str,
    session_mode: str = "fresh",
    session_id: str = "",
    command_executor_url: str = "",
) -> str:
    device  = req.device_id    or "emulator-5554"
    pkg     = req.app_package  or ""
    act     = req.app_activity or ""
    appium  = req.appium_url   or "http://localhost:4723"

    if session_mode in ("attach", "end"):
        lines = [
            "# -*- coding: utf-8 -*-",
            "import sys",
            f'sys.path.insert(0, r"{_ROUTER_BASE_DIR}")',
            "from services.session_reconnect import attach_appium_session",
            "from appium.webdriver.common.appiumby import AppiumBy",
            "from selenium.webdriver.support.ui import WebDriverWait",
            "from selenium.webdriver.support import expected_conditions as EC",
            "import time",
            "_VARS = {}  # adımlar arası değişken havuzu",
            "def _sub_vars(_s):",
            "    for _k, _v in _VARS.items():",
            "        _s = _s.replace('{{' + _k + '}}', str(_v))",
            "    return _s",
            "",
            f"driver = attach_appium_session({command_executor_url!r}, {session_id!r})",
            "wait = WebDriverWait(driver, 15)",
            "",
            VISION_HELPER,
            "",
            "try:",
        ]
        for line in steps_code.splitlines():
            lines.append("    " + line if line.strip() else "")
        if session_mode == "end":
            lines += [
                "", "except Exception as e:", '    print(f"HATA: {e}")',
                "finally:", "    driver.quit()", '    print("SESSION_ENDED")',
            ]
        else:
            lines += ["", "except Exception as e:", '    print(f"HATA: {e}")', "    raise"]
        return "\n".join(lines)

    # session_mode in ("fresh", "start") - asagidaki mevcut kod aynen devam eder
```

Mevcut fonksiyon gövdesinin geri kalanı (satır ~2012'den itibaren, `caps`/`pre` hazırlama +
`lines = [...]` + steps_code ekleme) **aynen kalır**. Sondaki `finally: driver.quit()` bloğunu
(satır ~2112-2113) Task 5 Step 4'teki AYNI koşullu desene çevir (`"start"` modunda `pass` + session
bilgisi print).

- [ ] **Step 3: Kontrol scriptini tekrar çalıştır, PASS beklenir**

- [ ] **Step 4: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: _build_mobile_template'e session_mode (start/attach/end) eklendi"
```

---

### Task 7: Backend — `/session/start`, `/session/run-step`, `/session/end`, `/session/status` endpoint'leri

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py` (yeni endpoint'ler, `/execute` endpoint'inin
  yakınına, satır ~3183 civarı)

**Interfaces:**
- Consumes: Task 4 (`_get_session`, `_touch_session`, `_remove_session`, `_active_sessions`),
  Task 5/6 (`_build_web_template`/`_build_mobile_template` `session_mode` parametresi), mevcut
  `_generate_steps`, `subprocess.Popen` deseni (`/execute` endpoint'inden).
- Produces: 4 yeni HTTP endpoint (aşağıda). **Task 6 SKIP edildiyse**, bu endpoint'lerdeki
  `mobile` dallanması hâlâ yazılır ama `session_start`/`session_run_step` mobil platform için
  `HTTPException(501, "Mobil oturum desteği henüz yok")` döner — `_build_mobile_template`'e
  `session_mode` verilmez.

- [ ] **Step 1: `POST /session/start` endpoint'ini ekle**

`/execute` endpoint'inin hemen üstüne veya altına ekle:

```python
class SessionStartRequest(BaseModel):
    platform:     str
    browser:      Optional[str] = "chrome"
    target_url:   Optional[str] = ""
    device_id:    Optional[str] = ""
    app_package:  Optional[str] = ""
    app_activity: Optional[str] = ""
    appium_url:   Optional[str] = "http://localhost:4723"


@router.post("/session/start")
async def session_start(req: SessionStartRequest, current_user: User = Depends(get_current_user)):
    if req.platform not in ("web", "mobile"):
        raise HTTPException(400, "Oturum sadece web/mobile platformlarında desteklenir.")
    if _get_session(current_user.id, req.platform):
        raise HTTPException(409, "Bu platform için zaten aktif bir oturum var.")

    gen_req = GenerateRequest(
        platform=req.platform, browser=req.browser, target_url=req.target_url,
        device_id=req.device_id, app_package=req.app_package, app_activity=req.app_activity,
        appium_url=req.appium_url,
    )
    build_fn = _build_mobile_template if req.platform == "mobile" else _build_web_template
    script = build_fn(gen_req, "", session_mode="start")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_session_start_") as f:
        f.write(script)
        tmp = f.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp], capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        out = proc.stdout
        sid_m = re.search(r"SESSION_ID:\s*(\S+)", out)
        url_m = re.search(r"EXECUTOR_URL:\s*(\S+)", out)
        if not sid_m or not url_m:
            raise HTTPException(500, f"Oturum başlatılamadı: {out}\n{proc.stderr}")
        _active_sessions[(current_user.id, req.platform)] = {
            "session_id": sid_m.group(1),
            "command_executor_url": url_m.group(1),
            "started_at": _time_mod.time(),
            "last_used_at": _time_mod.time(),
        }
        return {"success": True, "platform": req.platform}
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
```

- [ ] **Step 2: `POST /session/run-step` endpoint'ini ekle**

```python
class SessionRunStepRequest(BaseModel):
    platform:    str
    step:        StepItem
    step_label:  Optional[str] = "Adım"


@router.post("/session/run-step")
async def session_run_step(req: SessionRunStepRequest, current_user: User = Depends(get_current_user)):
    sess = _get_session(current_user.id, req.platform)
    if not sess:
        raise HTTPException(404, "Aktif oturum yok. Önce oturumu başlatın.")

    gen_req = GenerateRequest(platform=req.platform, steps_list=[req.step])
    steps_code, report = await _generate_steps(gen_req)
    build_fn = _build_mobile_template if req.platform == "mobile" else _build_web_template
    script = build_fn(
        gen_req, steps_code, session_mode="attach",
        session_id=sess["session_id"], command_executor_url=sess["command_executor_url"],
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_session_step_") as f:
        f.write(script)
        tmp = f.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp], capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        _touch_session(current_user.id, req.platform)
        passed = proc.returncode == 0
        return {
            "success": passed,
            "output": proc.stdout + proc.stderr,
            "report": report,
        }
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
```

- [ ] **Step 3: `POST /session/end` ve `GET /session/status` endpoint'lerini ekle**

```python
@router.post("/session/end")
async def session_end(platform: str, current_user: User = Depends(get_current_user)):
    sess = _get_session(current_user.id, platform)
    if not sess:
        raise HTTPException(404, "Aktif oturum yok.")

    gen_req = GenerateRequest(platform=platform)
    build_fn = _build_mobile_template if platform == "mobile" else _build_web_template
    script = build_fn(
        gen_req, "", session_mode="end",
        session_id=sess["session_id"], command_executor_url=sess["command_executor_url"],
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_session_end_") as f:
        f.write(script)
        tmp = f.name
    try:
        subprocess.run([sys.executable, tmp], capture_output=True, timeout=30,
                        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        _remove_session(current_user.id, platform)
    return {"success": True}


@router.get("/session/status")
async def session_status(platform: str, current_user: User = Depends(get_current_user)):
    sess = _get_session(current_user.id, platform)
    return {"active": sess is not None, "started_at": sess["started_at"] if sess else None}
```

- [ ] **Step 4: Kontrol scripti — endpoint'lerin router'a kayıtlı olduğunu doğrula**

```python
import sys
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import router
paths = {r.path for r in router.routes}
for p in ["/session/start", "/session/run-step", "/session/end", "/session/status"]:
    assert p in paths, f"FAIL: {p} route'u bulunamadi. Mevcut: {paths}"
print("OK")
```

Run: Expected `OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: /session/start, run-step, end, status endpoint'leri eklendi"
```

---

### Task 8: Frontend — Oturum kontrolleri + "Adımı Çalıştır" butonu

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html`
  - Platform seçim alanının yakınına oturum kontrolleri (Web/Mobil için görünür, Desktop'ta gizli)
  - `renderStepRow()` — her çalıştırılabilir adımın yanına "▶" butonu
  - Yeni `window.startSession`, `window.endSession`, `window.runSingleStep` fonksiyonları

**Interfaces:**
- Consumes: Task 7'nin 4 endpoint'i, mevcut `steps` dizisi, `setStepStatus()`, `Toast` yardımcı
  modülü (mevcut, `Toast.error(...)` zaten `executeScript` içinde kullanılıyor).

**Ön koşul:** Bu task'a başlamadan önce, `ai-generator.html`'de `selectedPlatform` değişkeninin
tanımlandığı yerin etrafında (`grep -n "selectedPlatform\s*=" backend/WebArayuz/ai-generator.html`)
tarayıcı/cihaz/uygulama paketi seçimi için kullanılan GERÇEK değişken adlarını (Selenium için
browser seçimi, mobil için device/app_package/app_activity, desktop için app_path/window_title)
tespit et — aşağıdaki kod parçalarında placeholder isim olarak `selectedBrowser`, `selectedDevice`,
`appPackage`, `appActivity`, `appiumUrl`, `appPath`, `windowTitle` kullanılıyor; bunları gerçek
isimlerle değiştir.

- [ ] **Step 1: Oturum kontrolleri HTML'ini ekle**

Platform seçim bölümünün hemen altına (ör. step-toolbar'ın üstüne, satır ~1054 civarı) ekle:

```html
                    <div id="sessionControls" class="session-controls" style="display:none; margin-bottom:10px;">
                        <span id="sessionStatusText" style="font-size:0.85rem; color:var(--text-secondary);">Oturum: kapalı</span>
                        <button class="btn-add-step" onclick="startSession()" id="btnSessionStart">▶ Oturumu Başlat</button>
                        <button class="btn-add-step" onclick="endSession()" id="btnSessionEnd" style="display:none;">⏹ Oturumu Bitir</button>
                    </div>
```

- [ ] **Step 2: `startSession`/`endSession`/oturum durumu senkronizasyonu**

`window.executeScript`'in yakınına ekle:

```javascript
    let _sessionActive = false;

    window.startSession = async function() {
        try {
            const res = await fetch(`${API_BASE}/ai-gen/session/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${Auth.getToken()}` },
                body: JSON.stringify({
                    platform: selectedPlatform, browser: selectedBrowser || "chrome",
                    target_url: document.getElementById("targetUrl")?.value || "",
                    device_id: selectedDevice || "", app_package: appPackage || "",
                    app_activity: appActivity || "", appium_url: appiumUrl || "http://localhost:4723",
                }),
            });
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Oturum başlatılamadı"); }
            _sessionActive = true;
            updateSessionUI();
            Toast.success("Oturum başlatıldı");
        } catch (e) {
            Toast.error(e.message);
        }
    };

    window.endSession = async function() {
        try {
            await fetch(`${API_BASE}/ai-gen/session/end?platform=${selectedPlatform}`, {
                method: "POST", headers: { "Authorization": `Bearer ${Auth.getToken()}` },
            });
            _sessionActive = false;
            updateSessionUI();
            Toast.success("Oturum kapatıldı");
        } catch (e) {
            Toast.error(e.message);
        }
    };

    function updateSessionUI() {
        const ctrl = document.getElementById("sessionControls");
        const isSessionPlatform = selectedPlatform === "web" || selectedPlatform === "mobile";
        ctrl.style.display = isSessionPlatform ? "flex" : "none";
        document.getElementById("sessionStatusText").textContent = "Oturum: " + (_sessionActive ? "aktif" : "kapalı");
        document.getElementById("btnSessionStart").style.display = _sessionActive ? "none" : "inline-block";
        document.getElementById("btnSessionEnd").style.display   = _sessionActive ? "inline-block" : "none";
    }

    async function syncSessionStatus() {
        if (selectedPlatform !== "web" && selectedPlatform !== "mobile") { updateSessionUI(); return; }
        try {
            const res = await fetch(`${API_BASE}/ai-gen/session/status?platform=${selectedPlatform}`, {
                headers: { "Authorization": `Bearer ${Auth.getToken()}` },
            });
            const data = await res.json();
            _sessionActive = !!data.active;
        } catch (e) { /* sessizce yoksay */ }
        updateSessionUI();
    }
```

`syncSessionStatus()` çağrısını, platformun değiştirildiği mevcut event handler'ın SONUNA ekle
(`grep -n "selectedPlatform =" backend/WebArayuz/ai-generator.html` ile ata yapılan tüm yerleri bul,
platform SEÇİM handler'ı olanına ekle — sayfa ilk yüklendiğinde de bir kez çağrılmalı).

- [ ] **Step 3: `runSingleStep` fonksiyonunu ekle**

```javascript
    window.runSingleStep = async function(idx) {
        const step = steps[idx];
        if (!step) return;

        if (selectedPlatform === "desktop") {
            try {
                const genRes = await fetch(`${API_BASE}/ai-gen/generate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${Auth.getToken()}` },
                    body: JSON.stringify({ platform: "desktop", steps_list: [step], app_path: appPath || "", window_title: windowTitle || "", reuse_instance: true }),
                });
                const genData = await genRes.json();
                if (!genData.success) throw new Error("Script üretilemedi");
                setStepStatus(idx, "running");
                const exRes = await fetch(`${API_BASE}/ai-gen/execute`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${Auth.getToken()}` },
                    body: JSON.stringify({ script: genData.script, platform: "desktop", step_labels: [step.content || "Adım"] }),
                });
                setStepStatus(idx, exRes.ok ? "done" : "fail");
            } catch (e) {
                setStepStatus(idx, "fail");
                Toast.error(e.message);
            }
            return;
        }

        if (!_sessionActive) {
            Toast.error("Önce oturumu başlatın.");
            return;
        }
        setStepStatus(idx, "running");
        try {
            const res = await fetch(`${API_BASE}/ai-gen/session/run-step`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${Auth.getToken()}` },
                body: JSON.stringify({ platform: selectedPlatform, step: step, step_label: step.content || "Adım" }),
            });
            const data = await res.json();
            setStepStatus(idx, data.success ? "done" : "fail");
            if (!data.success) appendLog("error", data.output || "Adım başarısız");
        } catch (e) {
            setStepStatus(idx, "fail");
            Toast.error(e.message);
        }
    };
```

- [ ] **Step 4: Her çalıştırılabilir adım satırına "▶" butonu ekle**

`renderStepRow(s, i)` fonksiyonunun EN SONUNDA (dönen ana HTML template string'inin içinde, mevcut
sil butonu/status ikonunun bulunduğu satır sonu buton grubunda — `grep -n "step-status\b" backend/WebArayuz/ai-generator.html`
ile o bloğu bul), fonksiyonun `contentHtml` hesaplandığı yerin HEMEN ALTINA şu satırı ekle:

```javascript
        const runStepBtn = s.type === "comment" ? "" :
            `<button class="step-run-btn" onclick="runSingleStep(${i})" title="Sadece bu adımı çalıştır">▶</button>`;
```

Sonra fonksiyonun döndürdüğü template literal'ında, mevcut sil butonunun (`onclick="deleteStep(${i})"`
gibi) HEMEN ÖNÜNE `${runStepBtn}` ekle — mevcut template'in tam yapısını `renderStepRow`'u okuyarak
gör, `${runStepBtn}`'i o buton grubuna ekle (yeni bir satır/blok DEĞİL, mevcut buton grubuna katılan
tek bir ek buton).

- [ ] **Step 5: Manuel doğrulama**

Sunucuyu başlat, Web platformunu seç, "Oturumu Başlat" tıkla (görünür bir Chrome penceresi
açılmalı), bir "git" adımı ekleyip "▶" ile tek başına çalıştır (tarayıcı o URL'e gitmeli), ikinci
bir "tıkla" adımını yine "▶" ile çalıştır (İLK adımın bıraktığı sayfada çalışmalı, yeni sekme/
pencere AÇILMAMALI), "Oturumu Bitir" ile kapat (tarayıcı kapanmalı).

- [ ] **Step 6: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "feat(ui): oturum kontrolleri ve tek adim calistirma butonu"
```

---

### Task 9: Uçtan uca doğrulama (spec Test Planı)

**Files:** Yok (sadece çalıştırma/doğrulama)

- [ ] **Step 1: Desktop tek-adım doğrulaması**

3 adımlı bir Desktop senaryosu oluştur (ör. bir Notepad penceresi açıp yazı yazan basit adımlar),
"Tümünü Çalıştır" ile bir kez koş, sonra 2. adımı "▶ Adımı Çalıştır" ile tek başına koş — pencerenin
kapanmadığını ve adımın kaldığı yerden doğru çalıştığını doğrula.

- [ ] **Step 2: Web oturum doğrulaması**

Task 8 Step 5'teki senaryonun aynısını gerçek bir çok-adımlı akışla tekrarla (ör. bir arama motoruna
git → arama kutusuna yaz → ara butonuna tıkla, her adımı TEK TEK "▶" ile), tarayıcının adımlar
arasında AÇIK kaldığını ve her adımın öncekinin bıraktığı durumdan devam ettiğini doğrula.

- [ ] **Step 3: Yorum adımı regresyon kontrolü**

Web senaryosuna bir yorum adımı ekleyip "Tümünü Çalıştır" ile koş — yorum adımının atlandığını,
sonraki adımların index'lerinin bozulmadığını (rapor/log'da doğru sırada göründüğünü) doğrula.

- [ ] **Step 4: Idle timeout gözlemi (opsiyonel, uzun sürer)**

`_SESSION_IDLE_TIMEOUT_SEC`'i geçici olarak 60 saniyeye düşürüp bir oturum başlat, 60+ saniye
bekleyip `/session/status`'un `active: false` döndüğünü ve tarayıcının otomatik kapandığını
doğrula, sonra değeri 15 dakikaya geri al ve commit ETME (geçici test amaçlı bir değişiklik,
kalıcı olmamalı).

---

### Task 10: Backend — Mevcut adımı devre dışı bırakma (`StepItem.disabled`)

**Files:**
- Modify: `backend/routers/ai_test_generator_router.py`
  - `StepItem` (satır ~116-118) — yeni `disabled: bool = False` alanı
  - `_generate_steps()` — adım döngüsünün en başı (satır ~2914)

**Interfaces:**
- Produces: `StepItem(disabled=True)` → `_generate_steps()` çıktısında bu adım için `report`
  girdisinde `"method": "comment"`, üretilen kodda `# [DEVRE DIŞI] {content}` satırı (adımın
  gerçek `type`'ı ne olursa olsun — text/image/sql/api hepsi için geçerli), `STEP_START`/
  `STEP_DONE` yok, sonraki adımların `idx` sırası bozulmuyor.
- Consumes: `_generate_steps()`'in mevcut birleştirme döngüsündeki `kind in ("rule", "image",
  "comment")` kontrolü (Task 2'de eklendi, satır ~2955) — "comment" kind'ı olduğu gibi reuse
  edilir, o döngüde DEĞİŞİKLİK GEREKMEZ.

- [ ] **Step 1: Kontrol scriptini yaz (henüz FAIL vermeli)**

Scratchpad'e `check_disabled_step.py`:

```python
import sys, asyncio
sys.path.insert(0, r"C:\Users\Sadik Demir\Documents\GitHub\OtomasyoToolFastApi\backend")
from routers.ai_test_generator_router import _generate_steps, StepItem, GenerateRequest

req = GenerateRequest(platform="web", steps_list=[
    StepItem(type="text", content='"data:text/html,<div>x</div>" git'),
    StepItem(type="text", content='"buton" tikla', disabled=True),
    StepItem(type="text", content='"sonuc" oku {{deger}}'),
])
steps_code, report = asyncio.run(_generate_steps(req))

assert report[1]["method"] == "comment", f"FAIL: devre disi adim method=comment olmali, gelen={report[1]}"
assert "# [DEVRE DIŞI]" in steps_code, "FAIL: devre disi yorum satiri script'te yok"
assert "STEP_START:1" not in steps_code, "FAIL: devre disi adim STEP_START uretmemeli"
assert "STEP_START:0" in steps_code and "STEP_START:2" in steps_code, "FAIL: index kaymamali (0 ve 2 hala STEP_START uretmeli)"
print("OK")
```

- [ ] **Step 2: Çalıştır, FAIL beklenir**

Run: `"backend/venv/Scripts/python.exe" <check_disabled_step.py yolu>`
Expected: `AssertionError: FAIL: devre disi adim method=comment olmali...` (Pydantic v2 varsayılan
`extra="ignore"` davranışı nedeniyle `disabled=True` şu an sessizce yok sayılır, adım normal
`"buton" tikla` gibi işlenip `STEP_START:1` üretir).

- [ ] **Step 3: `StepItem`'a `disabled` alanını ekle**

Öncesi (satır ~116-118):
```python
class StepItem(BaseModel):
    type:          str = "text"   # "text" | "image" | "sql" | "api" | "comment"
    content:       str = ""
```
Sonrası:
```python
class StepItem(BaseModel):
    type:          str = "text"   # "text" | "image" | "sql" | "api" | "comment"
    disabled:      bool = False   # True ise adım çalıştırılmaz, "# [DEVRE DIŞI]" yorumuna döner
    content:       str = ""
```

- [ ] **Step 4: `_generate_steps()` döngüsünün en başına erken-atlama kontrolü ekle**

Öncesi (satır ~2914):
```python
    for idx, item in enumerate(structured):
        if item.type == "image":
            code = "_check_stop()\n" + _image_step_code(item, req.platform, idx)
            code_lines.append(("image", item.content or f"Görsel {idx+1}", code))
```
Sonrası:
```python
    for idx, item in enumerate(structured):
        if item.disabled:
            label = item.content or f"Adım {idx+1}"
            code_lines.append(("comment", label, f"# [DEVRE DIŞI] {label}"))
            continue
        if item.type == "image":
            code = "_check_stop()\n" + _image_step_code(item, req.platform, idx)
            code_lines.append(("image", item.content or f"Görsel {idx+1}", code))
```

**Not:** `type` ne olursa olsun (text/image/sql/api/comment) `disabled=True` her zaman önce
kontrol edilir — bu yüzden kontrol SQL/API/görsel adımlarını da devre dışı bırakabilir, sadece
diğer `elif` dallarından ÖNCE çalışan bağımsız bir `if` olmalı (yukarıdaki `elif` zincirine
eklenirse SADECE `type != "image"` olan adımlarda çalışır — bu YANLIŞ olur).

- [ ] **Step 5: Kontrol scriptini tekrar çalıştır, PASS beklenir**

Run: aynı komut. Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/ai_test_generator_router.py
git commit -m "feat: mevcut adimi devre disi birakma (StepItem.disabled)"
```

---

### Task 11: Frontend — Devre dışı bırakma toggle butonu + stil

**Files:**
- Modify: `backend/WebArayuz/ai-generator.html`
  - CSS: `.step-del-btn:hover` kuralının hemen altına (satır ~789) `.step-item.disabled` ve
    `.step-toggle-btn` stilleri
  - `renderStepRow()` dönen template literal'ı (satır ~1857-1867) — `disabled` sınıfı + toggle
    butonu
  - Yeni `window.toggleStepDisabled` fonksiyonu (`window.deleteStep`'in hemen altına, satır ~1624)

**Interfaces:**
- Consumes: Task 10'un `disabled` alanı (aynı isim, `steps[i].disabled` olarak frontend state'inde
  tutulur), mevcut `steps` dizisi, `renderStepList()`, `updateGenerateBtn()`.
- Produces: yok (UI-only; script üretimi zaten Task 10'da backend'e `disabled` alanını olduğu
  gibi gönderiyor — `StepItem` Pydantic modeli JSON'daki `disabled` alanını otomatik bağlar, ek
  bir serialize adımı GEREKMEZ).

- [ ] **Step 1: `toggleStepDisabled` fonksiyonunu ekle**

`window.deleteStep`'in hemen altına (satır ~1624'ten sonra) ekle:

```javascript
    window.toggleStepDisabled = function(idx) {
        if (!steps[idx]) return;
        steps[idx].disabled = !steps[idx].disabled;
        renderStepList();
        updateGenerateBtn();
    };
```

- [ ] **Step 2: CSS ekle**

Öncesi (satır ~789-791):
```css
        .step-del-btn:hover { opacity: 1; color: var(--danger); background: rgba(239,68,68,0.08); }

        /* ── Modals ── */
```
Sonrası:
```css
        .step-del-btn:hover { opacity: 1; color: var(--danger); background: rgba(239,68,68,0.08); }
        .step-item.disabled { opacity: 0.5; }
        .step-item.disabled .step-content-input,
        .step-item.disabled textarea { text-decoration: line-through; }
        .step-toggle-btn {
            padding: 2px 5px;
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 0.85rem;
            opacity: 0.5;
            flex-shrink: 0;
            line-height: 1;
            border-radius: 3px;
        }
        .step-toggle-btn:hover { opacity: 1; color: var(--ai-accent); background: rgba(99,102,241,0.08); }
        .step-item.disabled .step-toggle-btn { opacity: 1; color: var(--ai-accent); }

        /* ── Modals ── */
```

**Not:** İçerik `text-decoration: line-through` ile üstü çizili görünür ama `input`/`textarea`
DEVRE DIŞI (`disabled` HTML özniteliği) BIRAKILMAZ — kullanıcı devre dışı bir adımı hâlâ
düzenleyebilmeli (spec'in "içerik düzenlenebilir kalmalı" gereksinimi).

- [ ] **Step 3: `renderStepRow()`'un döndürdüğü template'e toggle butonu + sınıfı ekle**

Öncesi (satır ~1857-1867):
```javascript
        return `<div class="step-item${extraClass}${statusClass ? " " + statusClass : ""}" id="step-row-${i}"
            draggable="true"
            ondragstart="stepDragStart(event, ${i})"
            ondragend="stepDragEnd()">
            <span class="step-drag-handle" title="Sürükle">⠿</span>
            <span class="step-num">${i + 1}</span>
            <span class="step-type-badge ${meta.cls}">${meta.label}</span>
            ${contentHtml}
            <span class="step-status${statusClass ? " " + statusClass : ""}">${statusIcon}</span>
            <button class="step-del-btn" onclick="deleteStep(${i})" title="Sil">✕</button>
        </div>`;
    }
```
Sonrası:
```javascript
        const disabledClass = s.disabled ? " disabled" : "";
        return `<div class="step-item${extraClass}${statusClass ? " " + statusClass : ""}${disabledClass}" id="step-row-${i}"
            draggable="true"
            ondragstart="stepDragStart(event, ${i})"
            ondragend="stepDragEnd()">
            <span class="step-drag-handle" title="Sürükle">⠿</span>
            <span class="step-num">${i + 1}</span>
            <span class="step-type-badge ${meta.cls}">${meta.label}</span>
            ${contentHtml}
            <span class="step-status${statusClass ? " " + statusClass : ""}">${statusIcon}</span>
            <button class="step-toggle-btn" onclick="toggleStepDisabled(${i})"
                title="${s.disabled ? 'Etkinleştir' : 'Devre dışı bırak (yorum satırına al)'}">${s.disabled ? "▶" : "⏸"}</button>
            <button class="step-del-btn" onclick="deleteStep(${i})" title="Sil">✕</button>
        </div>`;
    }
```

- [ ] **Step 4: Manuel doğrulama**

Sunucuyu başlat, bir Web senaryosuna en az 2 metin adımı ekle, ikinci adımın "⏸" butonuna tıkla —
satırın soluklaştığını ve üstü çizili göründüğünü doğrula; "Script Üret"e tıklayıp üretilen kodda
`# [DEVRE DIŞI] ...` satırının yer aldığını ve ORİJİNAL adım metninin KAYBOLMADIĞINI (input'ta hâlâ
düzenlenebilir durduğunu) doğrula; "Tümünü Çalıştır" ile koşup devre dışı adımın hiç "running"
durumuna geçmediğini gözle doğrula; "▶" ile tekrar etkinleştirip normal çalıştığını doğrula.

- [ ] **Step 5: Commit**

```bash
git add backend/WebArayuz/ai-generator.html
git commit -m "feat(ui): mevcut adimi devre disi birakma (yorum satirina alma) toggle'i"
```

---

## Self-Review Notları

- **Spec kapsaması:** Bölüm A (tek adım çalıştırma) → Task 1 (spike) + 4-8. Bölüm B (yorum
  adım tipi) → Task 2-3. Bölüm B2 (mevcut adımı devre dışı bırakma) → Task 10-11. "Test Planı" →
  Task 9.
- **Placeholder taraması:** Task 8'deki `selectedBrowser`/`appPath` gibi birkaç değişken adı,
  mevcut frontend state'iyle birebir eşleşmesi gerektiği için "Ön koşul" notuyla ayrıca
  işaretlendi — bu bir placeholder değil, gerçek bir entegrasyon adımı (implementer mevcut kodu
  okuyup gerçek isimleri kullanacak, mantık/iskelet tamamen verildi, sadece değişken isimleri
  koşullu). Task 6 açıkça "Task 1 spike başarısızsa SKIP" olarak işaretlendi — başarılı durum
  için tam kod verilir, bu writing-plans'ın "no placeholder" kuralına aykırı değildir.
- **Tip/isim tutarlılığı:** `session_mode` parametresi (+ `session_id`/`command_executor_url`)
  Task 5/6/7'de aynı imzayla kullanılıyor; `_get_session`/`_touch_session`/`_remove_session`
  Task 4'te tanımlandığı gibi Task 7'de birebir kullanılıyor; `attach_selenium_session`/
  `attach_appium_session` Task 1'de tanımlandığı gibi Task 4 (reaper) ve Task 5/6 (şablonlar)
  içinde tutarlı çağrılıyor. Task 10'un `disabled` alanı Task 11'de birebir aynı isimle
  (`steps[i].disabled`) frontend state'ine taşınıyor.
- **Task 10/11 diğer task'lara bağımlılığı yok:** Bölüm B2, Bölüm A (oturum/tek-adım çalıştırma,
  Task 1/4-8) ve Bölüm B (yorum tipi, Task 2-3) ile bağımsızdır — Task 7/8'den ÖNCE veya SONRA
  uygulanabilir, sıra önemli değildir (her ikisi de sadece `_generate_steps()`'in mevcut "comment"
  kind mekanizmasını reuse eder).
