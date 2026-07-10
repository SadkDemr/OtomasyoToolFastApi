# Tamamen İnternetsiz Sunucuya Offline Paketleme — Tasarım

**Tarih:** 2026-07-10
**Kapsam:** OtomasyoTool backend'inin (FastAPI + Selenium/Web + Appium/Mobil (fiziksel cihaz,
USB/ADB) + Desktop otomasyon) internete hiçbir şekilde çıkamayan bir Windows x64 sunucuya, tüm
bağımlılıklarıyla (Python, Node.js, Appium, Java, ADB, Chrome uyumlu chromedriver) kurulacak şekilde
paketlenmesi. Git workspace (`workspace_router`) ve AI generator (`ai_test_generator_router`,
Ollama/Gemini) bu round'a **dahil değil** — sunucuda hiç kullanılmayacaklar.

## Problem

Mevcut `setup.bat` ve `run.bat` tamamen internete bağımlı:

- `setup.bat`: Git/Node.js/JDK/ADB'yi internetten indirir, repo'yu GitHub'dan SSH ile clone'lar,
  Python paketlerini PyPI'dan `pip install` ile kurar, Appium'u `npm install -g` ile kurar.
- `run.bat`: her başlangıçta `git pull` çalıştırır (satır 14) ve eksik paket varsa sessizce
  `pip install` dener (satır 22-41) — hata durumunda script durmuyor, sadece uyarı basıyor.
- `backend/services/selenium_service.py` (satır ~52, ~160): her Chrome test çalıştırmasında
  `ChromeDriverManager().install()` çağırıyor; bu her seferinde chromedriver'ın en güncel sürümünü
  kontrol etmek için internete çıkıyor.
- `backend/routers/ai_test_generator_router.py`: `pyodbc` üzerinden SQL Server'a bağlanıyor — bu
  round'da kullanılmayacağı için offline pakete dahil edilmeyecek.

Hedef sunucu **hiçbir şekilde** internete çıkamıyor (ne kurulumda ne çalışırken). Bu yüzden yukarıdaki
tüm ağ bağımlılıkları, kurulumdan önce internetli bir "build makinesi"nde önceden çözülüp yerel
dosyalar haline getirilmeli.

## Kapsam Netleştirmeleri (kullanıcı onayı ile)

- Hedef OS: **Windows x64**, mevcut geliştirme ortamıyla aynı.
- Sunucuda gerekli özellikler: **sadece test çalıştırma** (Web/Selenium, Mobil/Appium, Desktop). Git
  workspace ve AI generator (Ollama/Gemini) kullanılmayacak, dolayısıyla pakete dahil edilmeyecek.
- Mobil hedef: **sadece fiziksel Android cihazlar (USB/ADB)** — emulator/AVD/system image kurulumu
  gerekmiyor, kapsam dışı.
- Tarayıcı: **sadece Chrome**, sunucuda zaten kurulu (sürüm ~136.0.7103.x). Chromedriver bu sürüme
  eşlenecek.
- Paket, internetli bu geliştirme makinesinde (veya başka internetli bir Windows x64 makinede)
  hazırlanacak; sunucuya **USB/harici disk** ile taşınacak.

## Çözüm

### 1. Mimari

İki taraflı akış:

- **Build tarafı** (internetli makine): tüm bağımlılıkları indirir, tek bir
  `OtomasyoTool-Offline-Bundle` klasörü üretir.
- **Sunucu tarafı** (internetsiz): bundle'dan `install_offline.bat` çalıştırılır. Bu script
  **hiçbir ağ isteği atmaz** — sadece yerel dosyaları kopyalar/kurar.

### 2. Bundle içeriği

```
OtomasyoTool-Offline-Bundle/
├── app/                    # backend kaynak kodu (.git, venv, logs, __pycache__ haric)
├── wheels/                 # tum Python paketleri (.whl), pip freeze'den pinlenmis
├── python-installer/       # Python 3.11.9 offline installer (.exe)
├── node-portable/          # Node.js zip dagitimi (kurulum gerektirmez)
├── appium-global/          # appium + appium-uiautomator2-driver, build makinesinde
│                           #   `npm install --prefix appium-global` ile hazirlanmis klasor
├── jdk/                    # Temurin JDK zip dagitimi (portable, installer degil)
├── platform-tools/         # adb.exe ve araclari (zaten zip - degismiyor)
├── chromedriver/           # Chrome 136 ile eslesen chromedriver.exe
├── install_offline.bat     # sunucuda calistirilacak kurulum scripti
└── run_offline.bat         # git pull YOK, sadece baslatir
```

### 3. Build scripti (`build_offline_bundle.ps1`, build makinesinde çalışır)

- Temiz bir venv'de kurulan tüm paketleri (`setup.bat` + `run.bat` içindeki **tüm** `pip install`
  satırlarının birleşimi: fastapi, uvicorn, python-multipart, pydantic, sqlalchemy, python-jose,
  passlib, bcrypt, selenium, webdriver-manager, Appium-Python-Client, requests, httpx, openpyxl,
  pandas, Pillow, opencv-python, pyperclip, pyautogui, pywinauto — pywin32 pywinauto'nun transitive
  bağımlılığı olarak gelir) `pip freeze` ile pinler.
- `pip download --platform win_amd64 --python-version 311 --only-binary=:all: -r frozen-requirements.txt -d wheels/`
  ile tüm wheel'leri toplar (derleme gerektiren sdist yok, sadece hazır binary wheel).
- Python 3.11.9 offline installer'ını indirir (`python-installer/`).
- Node.js zip dağıtımını indirir, `node-portable/` altına açar; o Node ile
  `npm install --prefix appium-global appium appium-uiautomator2-driver` çalıştırır. Aynı OS/mimari
  hedefte kullanılacağı için bu klasör olduğu gibi taşınabilir (npm'in ürettiği `.cmd` shim'leri
  `%~dp0` göreli path kullanır, absolute path'e bağımlı değildir).
- Temurin JDK zip dağıtımını indirir (msi değil, **zip** — kurulum/registry gerektirmez, sadece
  `JAVA_HOME` ayarlanır).
- ADB `platform-tools` zip'ini indirir.
- Chrome for Testing JSON API'sinden (`googlechromelabs.github.io/chrome-for-testing`) Chrome 136.x
  ile eşleşen `chromedriver.exe`'yi indirir.
- `app/` altına backend kaynağını (`.git`, `venv`, `logs`, `__pycache__` hariç) kopyalar.

### 4. Sunucu kurulum scripti (`install_offline.bat`)

- Python kurulu değilse `python-installer\python-3.11.9-amd64.exe /quiet InstallAllUsers=1 PrependPath=1`
  ile sessiz kurar.
- `venv` oluşturur, `pip install --no-index --find-links=wheels -r requirements.txt` çalıştırır
  (tamamen yerel dosyalardan, internet indexi olmadan — `--no-index` bayrağı PyPI'a hiç
  gitmeyeceğini garanti eder).
- `python venv\Lib\site-packages\pywin32_postinstall.py -install` çalıştırır (COM DLL kaydı —
  makineye özgü bir adım, internet gerektirmez, sadece yerel dosyalarla registry'ye yazar).
- `jdk/`, `node-portable/`, `appium-global/`, `platform-tools/`, `chromedriver/` klasörlerini hedef
  kurulum dizinine kopyalar.
- `run_offline.bat` içine `JAVA_HOME`, `PATH` (jdk/bin, node-portable, appium-global) ayarlarını
  yazar/gömer.
- Script boyunca `git`, index'li `pip`, registry'li `npm` veya doğrudan `curl`/indirme çağrısı
  **yapılmaz**.

### 5. Kod değişiklikleri (bu repoda)

- **`backend/services/selenium_service.py`**: Chrome driver init edilirken önce proje kökünde
  `chromedriver/chromedriver.exe` (veya bir ortam değişkeni, örn. `CHROMEDRIVER_PATH`) var mı diye
  bakılır; varsa doğrudan o path `Service(...)` ile kullanılır ve `ChromeDriverManager().install()`
  hiç çağrılmaz (internete çıkılmaz). Yoksa (geliştirme makinesinde olduğu gibi) mevcut
  webdriver-manager davranışına aynen düşülür — geliştirme ortamındaki davranış değişmez.
- **`backend/run_offline.bat`** (yeni dosya): mevcut `run.bat`'ın git pull (satır 11-16) ve
  internet bağımlı otomatik `pip install` bloğu (satır 21-41) çıkarılmış, `JAVA_HOME`/`PATH`
  ayarlarının eklendiği sürümü. Mevcut `run.bat` geliştirme ortamı için aynen kalır, dokunulmaz.
- **`backend/deploy/build_offline_bundle.ps1`** (yeni dosya) ve
  **`backend/deploy/install_offline.bat`** (yeni dosya): yukarıda tarif edilen build ve kurulum
  scriptleri.

### 6. Güncelleme stratejisi

İleride kod/paket güncellemesi gerektiğinde: build makinesinde bundle yeniden üretilir (kod-only
değişiklikte sadece `app/` klasörü; bağımlılık değişikliğinde `wheels/` da yeniden indirilir), USB
ile taşınır, sunucuda ilgili klasör(ler) üzerine kopyalanır. Sunucu hiçbir zaman `git pull` ya da
`pip`/`npm` ile internete çıkmaz.

### 7. Doğrulama planı

- Build makinesinde bundle üretildikten sonra, `wheels/` klasöründeki dosyalarla ağ erişimi
  **kapatılmış** bir test ortamında (veya sunucunun kendisinde) `install_offline.bat` çalıştırılıp
  hatasız tamamlandığı doğrulanır.
- Kurulum sonrası sunucuda `run_offline.bat` ile sunucu ayağa kaldırılır; `/docs` (Swagger) ve `/ui`
  açılabildiği, `adb devices` ile bağlı fiziksel cihazın göründüğü, örnek bir Web (Chrome) ve Mobil
  (Appium) senaryosunun uçtan uca çalıştığı manuel olarak kontrol edilir.
- Ağ izleme (örn. Kaynak Monitörü / netstat) ile kurulum ve çalışma sırasında dışa giden bağlantı
  denemesi olmadığı teyit edilir.
