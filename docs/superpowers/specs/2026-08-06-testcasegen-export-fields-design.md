# TestCaseGen — Export Alanları (Area Path / Assigned To / State) + Title Override Tasarımı

**Tarih:** 2026-08-06
**Durum:** Onaylandı (spec aşaması)

## Bağlam ve Amaç

TestCaseGen'in Excel export'u (`backend/services/testcasegen_service.py::build_export_workbook`) zaten kurumsal Azure DevOps (ADO) test case import formatına uyuyor: `ID, Work Item Type, Title, Test Step, Step Action, Step Expected, Area Path, Assigned To, State` kolonları. Ancak şu an **Area Path, Assigned To ve State kolonları her zaman boş** yazılıyor (`ws.append([None, None, None, i, ..., None, None, None])` — Test Case satırında da bu üç alan `None`).

Kullanıcı bu üç alanın gerçek değerlerle dolmasını, ayrıca üretilen **Title**'ın export öncesi elle düzeltilebilmesini istiyor. Kritik kısıt: bu alanlar her sayfa yenilendiğinde sıfırlanmamalı — sisteme zaten login olmuş kullanıcı bilindiği için, değerler o kullanıcının hesabına bağlı kalıcı varsayılan olarak saklanmalı.

**Kapsam dışı:** ADO'nun "Change"/revizyon geçmişi satırları (kullanıcının yapıştırdığı örnek export'ta görülen ikinci satır — bu ADO'nun kendi audit alanı, bizim ürettiğimiz export'un parçası değil). Test Step/Step Action/Step Expected üretim mantığı, wizard adım akışı (4 adım), ekran/başlık/kanban akışları değişmiyor.

## Veri Modeli

`backend/models/db_models.py` — `User` modeline 3 nullable kolon eklenir:

```python
tcg_area_path = Column(String, nullable=True)
tcg_assigned_to = Column(String, nullable=True)
tcg_state = Column(String, nullable=True)  # "Design" | "Ready" | "Closed"
```

`backend/database.py::_run_migrations()` içindeki mevcut `ALTER TABLE` listesine üç satır eklenir (aynı desen — `last_login`/`upload_only` örnekleri gibi):

```python
"ALTER TABLE users ADD COLUMN tcg_area_path TEXT",
"ALTER TABLE users ADD COLUMN tcg_assigned_to TEXT",
"ALTER TABLE users ADD COLUMN tcg_state TEXT",
```

Bu üç alan **kullanıcı profiline bağlı kalıcı varsayılandır** — session'a özel değildir, TestCaseGen'in dosya tabanlı session store'undan (`testcasegen_data/`) bağımsızdır.

## API (`backend/routers/testcasegen_router.py`)

### `GET /api/testcasegen/defaults`

Döner: `{"area_path": str, "assigned_to": str, "state": str}`.

- `area_path`: `current_user.tcg_area_path or ""`
- `assigned_to`: `current_user.tcg_assigned_to or current_user.full_name or current_user.username`
- `state`: `current_user.tcg_state or "Design"`

`assigned_to` hiç ayarlanmamışsa otomatik olarak login kullanıcının adını gösterir — kullanıcı hiçbir şey yazmadan doğru değer gelir (görev tanımındaki "sonuçta login olan kullanıcı biliniyor" isteği).

### `PUT /api/testcasegen/defaults`

Body: `{"area_path": str, "assigned_to": str, "state": str}` (Pydantic model, `state` için `Literal["Design", "Ready", "Closed"]`).

`current_user` satırının 3 kolonunu günceller, DB'ye commit eder. Dönüş: güncellenmiş `{"area_path", "assigned_to", "state"}`.

### Title override — yeni endpoint gerekmiyor

Kod incelemesinde, `session["titles"]` girdisinin `text` alanını güncelleyen bir endpoint **zaten mevcut**: `PUT /api/testcasegen/sessions/{session_id}/titles/{title_id}` (body `{"text": str}`, döner: güncel `session`). Bu endpoint şu an sadece Adım 2/3'ün başlık düzenleme akışlarında kullanılıyor; Adım 4 tablosu bunu hiç çağırmıyor. Title override için yeni bir backend endpoint'i eklenmeyecek — Adım 4 tablosundaki Title hücresi bu mevcut endpoint'e bağlanacak (frontend-only değişiklik).

### `export_testcases` (mevcut endpoint, değişiklik)

İstekten (`ExportIn`) hiçbir yeni alan **almaz** — Area Path/Assigned To/State istemciden gönderilmez, backend doğrudan `current_user.tcg_area_path/tcg_assigned_to/tcg_state` değerlerini okuyup `build_export_workbook`'a parametre olarak geçer. Bu, "değer değiştirilince otomatik profile kaydedilir" davranışıyla tutarlıdır: export anında kullanıcının o anki kayıtlı profilini kullanır, ekstra bir form doldurma adımı gerekmez.

`build_export_workbook(testcases, titles_by_id, area_path, assigned_to, state)` — her "Test Case" satırında (adım satırlarında değil) şu an `None` olan Area Path/Assigned To/State hücrelerine bu üç değer yazılır.

## Frontend (`backend/WebArayuz/testcasegen.html`)

### Adım 4 — Yeni panel

`renderStep4()` içinde "Test Case Oluştur" butonunun üstüne küçük bir `.tcg-card` panel eklenir: 3 alan —
- **Area Path** — `<input type="text">`
- **Assigned To** — `<input type="text">`
- **State** — `<select>` (`Design`/`Ready`/`Closed`)

Panel, Adım 4 ilk render edildiğinde `GET /testcasegen/defaults` ile doldurulur. Her input/select `onchange`'de anında `PUT /testcasegen/defaults` çağırır (mevcut `editTestcaseStep` desenindeki gibi: değişen alan disable edilir, istek biter bitmez enable edilir, hata olursa `Toast.error`). Ayrı bir "Kaydet" butonu yok — değişiklik = kayıt.

### Title inline düzenleme

`renderTestcaseTable()`'daki başlık satırı hücresi:

```html
<td>${escapeHtml(title.text)}</td>
```

yerine step action/expected input'larıyla aynı desende bir `<input type="text">` olur; `onchange` yeni `editTestcaseTitle(tcId, newTitle, this)` fonksiyonunu çağırır — bu fonksiyon `editTestcaseStep`'in aynısı ama yeni title endpoint'ine POST/PUT eder ve dönen `testcases` ile tabloyu yeniden render eder.

## Hata Yönetimi

Mevcut desenle aynı: istek sürerken ilgili input(lar) `disabled`, hata durumunda `Toast.error(e.message)`, `finally` bloğunda tekrar `enabled`. Yeni bir hata sınıfı veya fallback mekanizması eklenmiyor — mevcut `API.put`/`fetch` + `Toast` altyapısı yeniden kullanılıyor.

## Test / Doğrulama

Depoda `backend/tests/test_testcasegen_*.py` altında pytest tabanlı router/service testleri var (bkz. mevcut `test_testcasegen_router_export.py`). Yeni davranış için:

1. `test_testcasegen_router_export.py`'ye: export'un artık `current_user.tcg_*` alanlarını Area Path/Assigned To/State kolonlarına yazdığını doğrulayan bir test eklenir (kullanıcıyı bu alanlarla oluştur → export et → xlsx'i `openpyxl` ile aç → hücreleri kontrol et).
2. Yeni `test_testcasegen_router_defaults.py`: `GET/PUT /testcasegen/defaults` — varsayılan `assigned_to` fallback'i (`full_name`/`username`), `PUT` sonrası `GET`'in güncel değeri döndürdüğü, `state` için geçersiz literal gönderilirse 422.
3. Title override için mevcut `test_testcasegen_router_generate.py`/step-edit testine benzer bir test: title güncellenince hem `testcases` yanıtında hem `session["titles"]` içinde değişikliğin göründüğü.
4. Frontend: bu depoda JS test runner'ı yok (mevcut kısıt). Manuel doğrulama: paneldeki 3 alanı değiştir → sayfayı yenile → değerlerin kalıcı olduğunu gözle doğrula; Title input'unu değiştir → export edilen xlsx'te yeni title'ın göründüğünü doğrula.

## Riskler / Notlar

- SQLite `ALTER TABLE ADD COLUMN` mevcut satırlar için `NULL` bırakır — mevcut kullanıcılar ilk `GET /defaults` çağrısında fallback (`full_name`/`username`, `"Design"`) görür, bu istenen davranıştır.
- `state` alanı sabit 3 değerle sınırlandığından (Design/Ready/Closed), farklı ADO process template'i kullanan bir kurulum farklı state isimleri gerektirirse bu tasarım yetersiz kalır — şu an kapsam dışı, gerekirse ileride serbest metne çevrilebilir.
- Export artık `ExportIn` body'sinde Area Path/Assigned To/State beklemiyor; bu alanları hâlâ gönderen eski bir istemci (yok, ama teorik olarak) sorun yaratmaz çünkü backend bu alanları zaten okumuyor.
