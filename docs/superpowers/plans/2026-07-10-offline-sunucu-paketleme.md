# Offline Sunucu Paketleme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OtomasyoTool backend'ini, internete hiçbir şekilde çıkamayan bir Windows x64 sunucuya, tüm bağımlılıklarıyla (Python, Selenium/Chrome, Appium, Node.js, JDK, ADB) tam offline kurulabilecek şekilde paketlemek.

**Architecture:** İki taraflı akış — internetli bir "build makinesi"nde `build_offline_bundle.ps1` tüm bağımlılıkları indirip tek bir bundle klasörü üretir; bu bundle USB/harici disk ile internetsiz sunucuya taşınır ve orada `install_offline.bat` çalıştırılarak (hiçbir ağ isteği atmadan) kurulum tamamlanır. Selenium'un çalışma anında chromedriver indirme davranışı, yerel bir dosya varsa devre dışı bırakılır.

**Tech Stack:** Python 3.11 (FastAPI, Selenium, Appium-Python-Client, pywinauto/pywin32), PowerShell (build script), Windows Batch (install/run scripts), Node.js 20 + Appium 2.x + uiautomator2 driver, Temurin JDK 11, Android platform-tools, Chrome for Testing (chromedriver).

## Global Constraints

- Hedef sunucu **Windows x64**, hiçbir zaman internete çıkamaz — ne kurulum sırasında ne çalışırken. Her adım bu kısıtla test edilmeli.
- Kapsam **sadece** Web (Selenium/Chrome), Mobil (Appium, fiziksel Android cihaz/USB — emulator yok) ve Desktop otomasyon. Git workspace (`workspace_router`) ve AI generator (`ai_test_generator_router`, Ollama/Gemini, pyodbc) bu pakete **dahil değil**.
- Sunucuda Chrome zaten kurulu, sürüm **~136.0.7103.x** — sadece bu sürüme uygun chromedriver eşlenecek.
- Build makinesi (bu depo) internete çıkabiliyor; bundle transferi **USB/harici disk** ile yapılacak, gelecekte kod/paket güncellemesi de aynı şekilde.
- Bu depoda pytest veya başka bir otomatik test altyapısı **yok**. Her görevin doğrulama adımı, ilgili script/fonksiyonu doğrudan çalıştırıp beklenen çıktıyı/dosya durumunu gözlemleyerek yapılır — pytest dosyası eklenmeyecek.
- DRY, YAGNI: mevcut `setup.bat`/`run.bat` (geliştirme ortamı) değiştirilmeyecek, offline sürümleri ayrı dosyalar olarak eklenecek.
- Her görev sonunda commit atılır.

---

### Task 1: Selenium — yerel chromedriver override (offline mod)

**Files:**
- Modify: `backend/services/selenium_service.py:56-58` (yeni fonksiyon eklenecek), `backend/services/selenium_service.py:158-177` (create_driver içindeki driver seçim bloğu)

**Interfaces:**
- Produces: `_resolve_local_chromedriver() -> Optional[str]` — modül seviyesinde fonksiyon. `CHROMEDRIVER_PATH` ortam değişkeni veya `backend/chromedriver/chromedriver.exe` varsa yolunu döner, yoksa `None`.
- Consumes (Task 2'de kurulacak): `CHROMEDRIVER_PATH` ortam değişkeni, `run_offline.bat` tarafından ayarlanacak.

- [ ] **Step 1: `_resolve_local_chromedriver()` fonksiyonunu ekle**

`backend/services/selenium_service.py` içinde, satır 56 (`print("[SELENIUM] webdriver-manager yüklü değil...")`) ile satır 58 (`# PDF oluşturma için (opsiyonel)`) arasına ekle:

```python

def _resolve_local_chromedriver() -> Optional[str]:
    """Offline modda kullanilacak yerel chromedriver.exe yolunu dondurur, yoksa None.

    CHROMEDRIVER_PATH ortam degiskeni varsa onceliklidir; yoksa backend kok
    dizinindeki chromedriver/chromedriver.exe dosyasina bakilir. Ikisi de yoksa
    (gelistirme ortami) None doner ve mevcut webdriver-manager davranisina dusulur.
    """
    env_path = os.environ.get("CHROMEDRIVER_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_path = os.path.join(backend_root, "chromedriver", "chromedriver.exe")
    if os.path.isfile(default_path):
        return default_path
    return None
```

- [ ] **Step 2: Fonksiyonu doğrudan çalıştırarak doğrula (henüz create_driver'a bağlanmadan)**

Bu depoda pytest yok; doğrulama `venv` içindeki Python ile inline çalıştırılarak yapılır.

Run (repo kökünden):
```bash
cd backend
venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from services.selenium_service import _resolve_local_chromedriver
p = _resolve_local_chromedriver()
assert p is None, f'beklenen None, gelen: {p}'
print('OK: yerel driver yokken None donuyor')
"
```
Expected: `OK: yerel driver yokken None donuyor`

- [ ] **Step 3: Env var ve varsayılan yol senaryolarını doğrula**

Run:
```bash
mkdir -p backend/chromedriver && touch backend/chromedriver/chromedriver.exe
cd backend
venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from services.selenium_service import _resolve_local_chromedriver
p = _resolve_local_chromedriver()
assert p and p.endswith('chromedriver.exe'), f'beklenen default path, gelen: {p}'
print('OK (default path):', p)
"
cd ..
rm -rf backend/chromedriver
```
Expected: `OK (default path): .../backend/chromedriver/chromedriver.exe` çıktısı, sonra dummy dosya temizlenir.

- [ ] **Step 4: `create_driver` içinde local override'ı bağla**

`backend/services/selenium_service.py:158-177` şu anki hali:

```python
        try:
            if WEBDRIVER_MANAGER:
                driver_path = ChromeDriverManager().install()
                if os.name == 'nt' and not driver_path.endswith('.exe'):
                    driver_dir = os.path.dirname(driver_path)
                    for f in os.listdir(driver_dir):
                        if f == 'chromedriver.exe':
                            driver_path = os.path.join(driver_dir, f)
                            break
                    if not driver_path.endswith('.exe'):
                        parent_dir = os.path.dirname(driver_dir)
                        for root, dirs, files in os.walk(parent_dir):
                            for f in files:
                                if f == 'chromedriver.exe':
                                    driver_path = os.path.join(root, f)
                                    break
                print(f"[SELENIUM] ChromeDriver: {driver_path}")
                service = Service(executable_path=driver_path)
            else:
                service = Service()
```

Şuna değiştir:

```python
        try:
            local_driver = _resolve_local_chromedriver()
            if local_driver:
                print(f"[SELENIUM] Yerel ChromeDriver kullaniliyor (offline mod): {local_driver}")
                service = Service(executable_path=local_driver)
            elif WEBDRIVER_MANAGER:
                driver_path = ChromeDriverManager().install()
                if os.name == 'nt' and not driver_path.endswith('.exe'):
                    driver_dir = os.path.dirname(driver_path)
                    for f in os.listdir(driver_dir):
                        if f == 'chromedriver.exe':
                            driver_path = os.path.join(driver_dir, f)
                            break
                    if not driver_path.endswith('.exe'):
                        parent_dir = os.path.dirname(driver_dir)
                        for root, dirs, files in os.walk(parent_dir):
                            for f in files:
                                if f == 'chromedriver.exe':
                                    driver_path = os.path.join(root, f)
                                    break
                print(f"[SELENIUM] ChromeDriver: {driver_path}")
                service = Service(executable_path=driver_path)
            else:
                service = Service()
```

- [ ] **Step 5: Geliştirme ortamında davranışın bozulmadığını doğrula**

Run:
```bash
cd backend
venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from services.selenium_service import SeleniumService
s = SeleniumService()
s.create_driver(headless=True)
print('OK: driver olusturuldu (webdriver-manager fallback calisiyor)')
s.close_driver()
"
```
Expected: `[SELENIUM] ChromeDriver: ...` ardından `OK: driver olusturuldu ...` — `CHROMEDRIVER_PATH` set edilmediği ve `backend/chromedriver/` olmadığı için mevcut webdriver-manager yoluna düştüğünü kanıtlar.

- [ ] **Step 6: Commit**

```bash
git add backend/services/selenium_service.py
git commit -m "Selenium: offline mod icin yerel chromedriver override ekle"
```

---

### Task 2: `run_offline.bat` — internetsiz başlatma scripti

**Files:**
- Create: `backend/run_offline.bat`

**Interfaces:**
- Consumes: `backend/venv`, `backend/jdk`, `backend/node-portable`, `backend/appium-global`, `backend/platform-tools`, `backend/chromedriver` (Task 3/install_offline.bat tarafından yerleştirilir).
- Produces: `CHROMEDRIVER_PATH` ortam değişkeni (Task 1'in `_resolve_local_chromedriver()` fonksiyonu tarafından okunur), `JAVA_HOME`, `APPIUM_HOME`, `PATH`.

- [ ] **Step 1: Dosyayı oluştur**

```bat
@echo off
cd /d "%~dp0"

if not exist "venv" (
    echo HATA: Once install_offline.bat ile kurulum yapin!
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

REM --- Offline bagimliliklar icin ortam degiskenleri (internet KULLANILMAZ) ---
set "JAVA_HOME=%~dp0jdk"
set "PATH=%~dp0node-portable;%~dp0appium-global;%JAVA_HOME%\bin;%PATH%"
set "APPIUM_HOME=%~dp0appium-global\.appium-home"
set "CHROMEDRIVER_PATH=%~dp0chromedriver\chromedriver.exe"

echo.
echo ========================================
echo    Test Otomasyon Platformu v2.1 (OFFLINE)
echo ========================================
echo.
echo Bagli Cihazlar:
if exist "platform-tools\adb.exe" (
    "platform-tools\adb.exe" devices
)
echo.
echo Swagger UI:  http://localhost:8000/docs
echo Web Arayuz:  http://localhost:8000/ui
echo.
echo Durdurmak icin Ctrl+C
echo ========================================
echo.

if not exist "logs" mkdir logs

for /f %%i in ('powershell -NoProfile -NonInteractive -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set DT=%%i
set LOGFILE=logs\server_%DT%.log

echo Loglar: %LOGFILE%
echo.

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Port 8000 kullanimda, eski surec sonlandiriliyor ^(PID %%p^)...
    taskkill /F /PID %%p >nul 2>&1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

powershell -NoProfile -NonInteractive -Command "python main.py | Tee-Object -FilePath '%LOGFILE%' -Append"

pause
```

- [ ] **Step 2: git pull ve internet bağımlı pip install bloklarının olmadığını doğrula**

Run:
```bash
grep -c "git pull" backend/run_offline.bat
grep -c "pip install" backend/run_offline.bat
grep -c "JAVA_HOME" backend/run_offline.bat
```
Expected: ilk iki komut `0` döner (git pull ve pip install YOK), üçüncü komut `1` veya fazlası döner (JAVA_HOME ayarı var).

- [ ] **Step 3: Mevcut `run.bat`'ın dokunulmadığını doğrula**

Run:
```bash
git diff --stat backend/run.bat
```
Expected: boş çıktı (değişiklik yok).

- [ ] **Step 4: Commit**

```bash
git add backend/run_offline.bat
git commit -m "Offline sunucu icin run_offline.bat ekle (git pull ve internet bagimli pip install yok)"
```

---

### Task 3: Sunucu tarafı kurulum scripti + birleşik paket listesi

**Files:**
- Create: `backend/deploy/offline-requirements.txt`
- Create: `backend/deploy/install_offline.bat`

**Interfaces:**
- Consumes (bundle kökünde bulunmalı — Task 4-9'da `build_offline_bundle.ps1` tarafından üretilir): `wheels/`, `python-installer/`, `app/`, `jdk/`, `node-portable/`, `appium-global/`, `platform-tools/`, `chromedriver/`, `offline-requirements.txt`.
- Produces: `%INSTALL_DIR%\backend` altında çalışmaya hazır bir kurulum (varsayılan `%INSTALL_DIR%` = `C:\OtomasyoTool`).

- [ ] **Step 1: `offline-requirements.txt` oluştur**

`setup.bat`/`run.bat`'ın kurduğu tüm paketlerin (requirements.txt + Desktop otomasyon ekleri) birleşimi:

```
fastapi>=0.104.1
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
pydantic[email]>=2.5.2
sqlalchemy>=2.0.23
python-jose[cryptography]>=3.3.0
passlib[bcrypt]==1.7.4
bcrypt>=4.0.0
selenium>=4.15.2
webdriver-manager>=4.0.1
Appium-Python-Client>=3.1.0
requests>=2.31.0
httpx>=0.24.0
defusedxml>=0.7.1
openpyxl>=3.1.2
pandas>=2.2.0
Pillow
opencv-python
pyperclip
pyautogui
pywinauto
```

- [ ] **Step 2: `install_offline.bat` oluştur**

```bat
@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM OtomasyoTool - Offline Kurulum Scripti
REM Bu script INTERNET GEREKTIRMEZ. Tum dosyalar bu bundle icinde yerel olarak
REM bulunur (wheels\, python-installer\, node-portable\, appium-global\, jdk\,
REM platform-tools\, chromedriver\, app\, offline-requirements.txt).
REM Kullanim: install_offline.bat [KURULUM_DIZINI]   (varsayilan: C:\OtomasyoTool)
REM ============================================================================

set "BUNDLE_DIR=%~dp0"
set "INSTALL_DIR=%~1"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=C:\OtomasyoTool"
set "BACKEND_DIR=%INSTALL_DIR%\backend"

echo ========================================
echo   OtomasyoTool Offline Kurulum
echo   Hedef: %INSTALL_DIR%
echo ========================================
echo.

REM --- 1. Python ---------------------------------------------------------------
echo [1/6] Python kontrol ediliyor...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Python bulunamadi, yerel installer ile kuruluyor...
    "%BUNDLE_DIR%python-installer\python-3.11.9-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1
    if %errorlevel% neq 0 (
        echo   HATA: Python kurulumu basarisiz!
        pause
        exit /b 1
    )
) else (
    echo   Python zaten kurulu - OK
)
echo.

REM --- 2. Backend kaynak kodu ----------------------------------------------------
echo [2/6] Backend kaynak kodu kopyalaniyor...
if not exist "%BACKEND_DIR%" mkdir "%BACKEND_DIR%"
xcopy "%BUNDLE_DIR%app" "%BACKEND_DIR%" /E /I /Y /Q >nul
echo   Tamamlandi - OK
echo.

REM --- 3. Python venv + paketler (tamamen yerel, internet YOK) -------------------
echo [3/6] Python sanal ortami olusturuluyor...
cd /d "%BACKEND_DIR%"
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat
echo   Paketler yerel wheels'tan kuruluyor (--no-index, internet kullanilmiyor)...
pip install --no-index --find-links="%BUNDLE_DIR%wheels" -r "%BUNDLE_DIR%offline-requirements.txt"
if %errorlevel% neq 0 (
    echo   HATA: Paketler kurulamadi! wheels\ klasorunu kontrol edin.
    pause
    exit /b 1
)
echo   Tamamlandi - OK
echo.

REM --- 4. pywin32 postinstall (COM DLL kaydi, internet gerektirmez) --------------
echo [4/6] pywin32 kaydediliyor...
for /f "delims=" %%p in ('where /r venv pywin32_postinstall.py 2^>nul') do set "PYWIN32_POST=%%p"
if defined PYWIN32_POST (
    python "!PYWIN32_POST!" -install
    echo   Tamamlandi - OK
) else (
    echo   UYARI: pywin32_postinstall.py bulunamadi, pywinauto calismayabilir.
)
echo.

REM --- 5. JDK / Node / Appium / ADB / chromedriver kopyalama ---------------------
echo [5/6] Java, Node, Appium, ADB, chromedriver kopyalaniyor...
xcopy "%BUNDLE_DIR%jdk" "%BACKEND_DIR%\jdk" /E /I /Y /Q >nul
xcopy "%BUNDLE_DIR%node-portable" "%BACKEND_DIR%\node-portable" /E /I /Y /Q >nul
xcopy "%BUNDLE_DIR%appium-global" "%BACKEND_DIR%\appium-global" /E /I /Y /Q >nul
xcopy "%BUNDLE_DIR%platform-tools" "%BACKEND_DIR%\platform-tools" /E /I /Y /Q >nul
xcopy "%BUNDLE_DIR%chromedriver" "%BACKEND_DIR%\chromedriver" /E /I /Y /Q >nul
echo   Tamamlandi - OK
echo.

REM --- 6. Dogrulama + bitis --------------------------------------------------------
echo [6/6] Kurulum dogrulaniyor...
if not exist "%BACKEND_DIR%\jdk\bin\java.exe" echo   UYARI: jdk\bin\java.exe bulunamadi.
if not exist "%BACKEND_DIR%\node-portable\node.exe" echo   UYARI: node-portable\node.exe bulunamadi.
if not exist "%BACKEND_DIR%\appium-global\appium.cmd" echo   UYARI: appium-global\appium.cmd bulunamadi.
if not exist "%BACKEND_DIR%\platform-tools\adb.exe" echo   UYARI: platform-tools\adb.exe bulunamadi.
if not exist "%BACKEND_DIR%\chromedriver\chromedriver.exe" echo   UYARI: chromedriver\chromedriver.exe bulunamadi.

echo.
echo ========================================
echo   KURULUM TAMAMLANDI
echo ========================================
echo.
echo Sonraki adimlar:
echo   1. cd /d "%BACKEND_DIR%"
echo   2. venv\Scripts\python.exe make_admin.py   (admin kullanici olustur)
echo   3. run_offline.bat                          (sunucuyu baslat)
echo.
pause
```

- [ ] **Step 3: Sahte (fake) bir bundle ile kuru çalıştırma testi**

Gerçek wheels/jdk/node henüz yok (Task 4-9'da üretilecek); script'in dosya kopyalama/atlama mantığının hatasız aktığını doğrulamak için boş placeholder'larla sahte bir bundle kur:

```bash
SCRATCH="/c/Users/Sadik Demir/Documents/GitHub/OtomasyoToolFastApi/.scratch-bundle-test"
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/app" "$SCRATCH/jdk/bin" "$SCRATCH/node-portable" "$SCRATCH/appium-global" "$SCRATCH/platform-tools" "$SCRATCH/chromedriver" "$SCRATCH/wheels" "$SCRATCH/python-installer"
cp -r backend/routers backend/services backend/models backend/main.py backend/requirements.txt "$SCRATCH/app/" 2>/dev/null
touch "$SCRATCH/jdk/bin/java.exe" "$SCRATCH/node-portable/node.exe" "$SCRATCH/appium-global/appium.cmd" "$SCRATCH/platform-tools/adb.exe" "$SCRATCH/chromedriver/chromedriver.exe"
cp backend/deploy/offline-requirements.txt "$SCRATCH/offline-requirements.txt"
cp backend/deploy/install_offline.bat "$SCRATCH/install_offline.bat"
```

Ardından (gerçek pip install adımı yerel wheels boş olduğu için başarısız olacak ve script `exit /b 1` ile duracak — bu adımda amaç sadece 1-2. adımların ve dosya kopyalama akışının çalıştığını görmek):

```bash
cmd.exe /c "\"$SCRATCH\install_offline.bat\" \"$SCRATCH\target\""
```
Expected: `[1/6] Python zaten kurulu - OK`, `[2/6] ... Tamamlandi - OK`, `[3/6]` adımında wheels boş olduğu için `HATA: Paketler kurulamadi!` ile duracak — bu beklenen bir sonuçtur (gerçek wheels Task 5'te üretilecek). `$SCRATCH/target/backend` altında `app` dosyalarının kopyalandığını doğrula:
```bash
ls "$SCRATCH/target/backend/main.py"
rm -rf "$SCRATCH"
```

- [ ] **Step 4: Commit**

```bash
git add backend/deploy/offline-requirements.txt backend/deploy/install_offline.bat
git commit -m "Offline sunucu kurulum scripti (install_offline.bat) ve birlesik paket listesi ekle"
```

---

### Task 4: Build script iskeleti — `build_offline_bundle.ps1` (app kopyalama)

**Files:**
- Create: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Produces: `$OutputDir/app/` (backend kaynak kodu, `.git`/`venv`/`logs`/`__pycache__` hariç), `$OutputDir/install_offline.bat`, `$OutputDir/offline-requirements.txt`.
- Sonraki görevler (5-9) bu dosyaya yeni fonksiyonlar ve `if ($Only -contains ...)` blokları ekleyecek.

- [ ] **Step 1: Dosyayı oluştur**

```powershell
<#
.SYNOPSIS
    OtomasyoTool icin internetsiz (offline) sunucu dagitim bundle'i olusturur.
.DESCRIPTION
    Bu script INTERNETLI bir Windows x64 makinede calistirilir. Uretilen
    OtomasyoTool-Offline-Bundle klasoru, internete hic cikamayan bir sunucuya
    USB/harici disk ile tasinir ve orada install_offline.bat ile kurulur.
    Sunucu tarafinda hicbir asamada internet erisimi gerekmez.
.PARAMETER OutputDir
    Bundle'in olusturulacagi klasor.
.PARAMETER ChromeMajorVersion
    Sunucuda kurulu Chrome'un ana surum numarasi (orn. 136). Chromedriver bu
    surume gore secilir.
.PARAMETER Only
    Sadece belirtilen asamalari calistirir: app, python, node, jdk, adb, chromedriver.
    Test/gelistirme sirasinda tek bir asamayi izole calistirmak icin kullanilir.
#>
param(
    [string]$OutputDir = ".\OtomasyoTool-Offline-Bundle",
    [string]$ChromeMajorVersion = "136",
    [string[]]$Only = @("app", "python", "node", "jdk", "adb", "chromedriver")
)

$ErrorActionPreference = "Stop"
$DeployDir = $PSScriptRoot                   # backend\deploy
$BackendDir = Split-Path -Parent $DeployDir  # backend

# ---------------------------------------------------------------------------
# app: backend kaynak kodunu kopyala
# ---------------------------------------------------------------------------
function Copy-AppSource {
    param([string]$Dest)
    Write-Host "[app] Backend kaynak kodu kopyalaniyor -> $Dest"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $exclude = @('venv', 'logs', '__pycache__', '.git', 'node-portable', 'appium-global', 'jdk', 'chromedriver', 'wheels', 'test_platform.db', 'test_platform.db-shm', 'test_platform.db-wal')
    Get-ChildItem -Path $BackendDir -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $Dest $_.Name) -Recurse -Force
    }
    Write-Host "[app] Tamamlandi."
}

# ---------------------------------------------------------------------------
# Calistir
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if ($Only -contains "app") {
    Copy-AppSource -Dest (Join-Path $OutputDir "app")
}

Copy-Item -Path (Join-Path $DeployDir "install_offline.bat") -Destination (Join-Path $OutputDir "install_offline.bat") -Force
Copy-Item -Path (Join-Path $DeployDir "offline-requirements.txt") -Destination (Join-Path $OutputDir "offline-requirements.txt") -Force

Write-Host ""
Write-Host "Bundle hazir (kismi): $OutputDir"
```

- [ ] **Step 2: `-Only app` ile çalıştır ve doğrula**

Run (PowerShell, repo kökünden):
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only app -OutputDir .\.scratch-bundle
```
Expected: `[app] Tamamlandi.` ve `Bundle hazir (kismi): .\.scratch-bundle` çıktısı.

Doğrula:
```bash
ls .scratch-bundle/app/main.py
ls .scratch-bundle/install_offline.bat
test -d .scratch-bundle/app/venv && echo "HATA: venv kopyalanmis" || echo "OK: venv haric tutuldu"
rm -rf .scratch-bundle
```
Expected: `main.py` ve `install_offline.bat` mevcut; `OK: venv haric tutuldu` yazdırılır.

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Offline bundle build scripti iskeleti (app kopyalama) ekle"
```

---

### Task 5: Build script — Python offline installer + wheel deposu

**Files:**
- Modify: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Produces: `$OutputDir/python-installer/python-3.11.9-amd64.exe`, `$OutputDir/wheels/*.whl`.
- Consumes: `backend/deploy/offline-requirements.txt` (Task 3).

- [ ] **Step 1: `Get-PythonAndWheels` fonksiyonunu ekle**

`backend/deploy/build_offline_bundle.ps1` içinde, `# Calistir` yorum bloğundan (satır: `# Calistir` başlığı) hemen önce ekle:

```powershell
# ---------------------------------------------------------------------------
# python: Python offline installer + wheelhouse
# ---------------------------------------------------------------------------
function Get-PythonAndWheels {
    param([string]$Dest, [string]$WheelsDest)
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    New-Item -ItemType Directory -Force -Path $WheelsDest | Out-Null

    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyExe = Join-Path $Dest "python-3.11.9-amd64.exe"
    Write-Host "[python] Python 3.11.9 installer indiriliyor..."
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe

    $reqFile = Join-Path $DeployDir "offline-requirements.txt"
    Write-Host "[python] Wheel'ler indiriliyor (pip download)..."
    python -m pip download -r $reqFile -d $WheelsDest --only-binary=:all: --python-version 311 --platform win_amd64 --implementation cp
    if ($LASTEXITCODE -ne 0) { throw "pip download basarisiz (exit $LASTEXITCODE)" }
    Write-Host "[python] Tamamlandi."
}

```

Ve `# Calistir` bloğundaki `if ($Only -contains "app") { ... }` satırından hemen sonra ekle:

```powershell
if ($Only -contains "python") {
    Get-PythonAndWheels -Dest (Join-Path $OutputDir "python-installer") -WheelsDest (Join-Path $OutputDir "wheels")
}
```

- [ ] **Step 2: `-Only python` ile çalıştır ve doğrula**

Bu adım gerçek internet indirmesi yapar (Python installer ~25MB + onlarca wheel dosyası), birkaç dakika sürebilir.

Run:
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only python -OutputDir .\.scratch-bundle
```
Expected: `[python] Tamamlandi.` çıktısı, hata yok.

Doğrula:
```bash
ls .scratch-bundle/python-installer/python-3.11.9-amd64.exe
ls .scratch-bundle/wheels/*.whl | wc -l
```
Expected: installer dosyası mevcut; wheel sayısı 20'den fazla (fastapi, selenium, pandas, opencv-python, pywinauto, pywin32 vb. transitive bağımlılıklarıyla).

```bash
rm -rf .scratch-bundle
```

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Build script: Python offline installer ve wheel deposu indirme adimi ekle"
```

---

### Task 6: Build script — portable Node.js + Appium + uiautomator2 driver

**Files:**
- Modify: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Produces: `$OutputDir/node-portable/node.exe`, `$OutputDir/appium-global/appium.cmd`, `$OutputDir/appium-global/.appium-home` (uiautomator2 driver kayıtlı).

- [ ] **Step 1: `Get-NodeAndAppium` fonksiyonunu ekle**

`Get-PythonAndWheels` fonksiyonunun kapanışından (yukarıdaki boş satırdan) sonra, `# Calistir` bloğundan önce ekle:

```powershell
# ---------------------------------------------------------------------------
# node: portable Node.js + Appium (global npm prefix) + uiautomator2 driver
# ---------------------------------------------------------------------------
function Get-NodeAndAppium {
    param([string]$NodeDest, [string]$AppiumDest)
    New-Item -ItemType Directory -Force -Path $NodeDest | Out-Null

    $nodeUrl = "https://nodejs.org/dist/v20.15.0/node-v20.15.0-win-x64.zip"
    $nodeZip = Join-Path $env:TEMP "node-v20.15.0-win-x64.zip"
    Write-Host "[node] Node.js indiriliyor..."
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip
    Expand-Archive -Path $nodeZip -DestinationPath $env:TEMP -Force
    Copy-Item -Path (Join-Path $env:TEMP "node-v20.15.0-win-x64\*") -Destination $NodeDest -Recurse -Force
    Remove-Item $nodeZip -Force
    Remove-Item (Join-Path $env:TEMP "node-v20.15.0-win-x64") -Recurse -Force

    $npmCmd = Join-Path $NodeDest "npm.cmd"

    Write-Host "[node] Appium global olarak kuruluyor..."
    New-Item -ItemType Directory -Force -Path $AppiumDest | Out-Null
    & $npmCmd install --prefix $AppiumDest appium --loglevel=error
    if ($LASTEXITCODE -ne 0) { throw "npm install appium basarisiz (exit $LASTEXITCODE)" }

    $appiumHome = Join-Path $AppiumDest ".appium-home"
    New-Item -ItemType Directory -Force -Path $appiumHome | Out-Null
    $env:APPIUM_HOME = $appiumHome
    $oldPath = $env:PATH
    $env:PATH = "$NodeDest;$env:PATH"

    $appiumCmd = Join-Path $AppiumDest "appium.cmd"
    Write-Host "[node] uiautomator2 driver kuruluyor (APPIUM_HOME=$appiumHome)..."
    & $appiumCmd driver install uiautomator2
    if ($LASTEXITCODE -ne 0) { throw "appium driver install uiautomator2 basarisiz (exit $LASTEXITCODE)" }

    $env:PATH = $oldPath
    Write-Host "[node] Tamamlandi."
}

```

Ve `# Calistir` bloğunda `python` bloğundan sonra ekle:

```powershell
if ($Only -contains "node") {
    Get-NodeAndAppium -NodeDest (Join-Path $OutputDir "node-portable") -AppiumDest (Join-Path $OutputDir "appium-global")
}
```

- [ ] **Step 2: `-Only node` ile çalıştır ve doğrula**

Run (birkaç dakika sürebilir — Node.js indirme + npm install appium + driver indirme):
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only node -OutputDir .\.scratch-bundle
```
Expected: `[node] Tamamlandi.`

Doğrula:
```
.\.scratch-bundle\node-portable\node.exe --version
.\.scratch-bundle\appium-global\appium.cmd --version
.\.scratch-bundle\appium-global\appium.cmd driver list --installed
```
Expected: Node sürümü (v20.15.0), Appium sürümü basılır; `driver list --installed` çıktısında `uiautomator2` görünür.

**Not (risk):** `.appium-home` klasörünün tamamen `appium-global` altında (kendi kendine yeten) tutulması, bu klasörün farklı bir mutlak path'e taşındığında da (sunucuda) çalışmasını beklenir kılar çünkü Appium extension manifest'i ve `node_modules` aynı klasör ağacı içinde birlikte taşınır. Task 10'daki sunucu doğrulama listesinde bu varsayım açıkça test edilecek; çalışmazsa fallback: `appium-global\appium.cmd driver install --source=local <appium-global icindeki uiautomator2-driver klasoru>` internet gerektirmeden yeniden calistirilabilir.

```bash
rm -rf .scratch-bundle
```

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Build script: portable Node.js + Appium + uiautomator2 driver indirme adimi ekle"
```

---

### Task 7: Build script — portable Temurin JDK

**Files:**
- Modify: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Produces: `$OutputDir/jdk/bin/java.exe`.

- [ ] **Step 1: `Get-JdkPortable` fonksiyonunu ekle**

`Get-NodeAndAppium` fonksiyonundan sonra, `# Calistir` bloğundan önce ekle:

```powershell
# ---------------------------------------------------------------------------
# jdk: portable Temurin JDK 11 (zip - kurulum gerektirmez)
# ---------------------------------------------------------------------------
function Get-JdkPortable {
    param([string]$Dest)
    $jdkUrl = "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.23%2B9/OpenJDK11U-jdk_x64_windows_hotspot_11.0.23_9.zip"
    $jdkZip = Join-Path $env:TEMP "temurin11.zip"
    Write-Host "[jdk] Temurin JDK 11 indiriliyor..."
    Invoke-WebRequest -Uri $jdkUrl -OutFile $jdkZip
    Expand-Archive -Path $jdkZip -DestinationPath $env:TEMP -Force
    $extracted = Get-ChildItem -Path $env:TEMP -Directory -Filter "jdk-11*" | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Path (Join-Path $extracted.FullName "*") -Destination $Dest -Recurse -Force
    Remove-Item $jdkZip -Force
    Remove-Item $extracted.FullName -Recurse -Force
    Write-Host "[jdk] Tamamlandi -> $Dest\bin\java.exe"
}

```

Ve `# Calistir` bloğunda `node` bloğundan sonra ekle:

```powershell
if ($Only -contains "jdk") {
    Get-JdkPortable -Dest (Join-Path $OutputDir "jdk")
}
```

- [ ] **Step 2: `-Only jdk` ile çalıştır ve doğrula**

Run:
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only jdk -OutputDir .\.scratch-bundle
```
Expected: `[jdk] Tamamlandi -> ...\jdk\bin\java.exe`

Doğrula:
```
.\.scratch-bundle\jdk\bin\java.exe -version
```
Expected: `openjdk version "11.0.23" ...` çıktısı.

```bash
rm -rf .scratch-bundle
```

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Build script: portable Temurin JDK 11 indirme adimi ekle"
```

---

### Task 8: Build script — Android platform-tools (ADB)

**Files:**
- Modify: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Produces: `$OutputDir/platform-tools/adb.exe`.

- [ ] **Step 1: `Get-PlatformTools` fonksiyonunu ekle**

`Get-JdkPortable` fonksiyonundan sonra, `# Calistir` bloğundan önce ekle:

```powershell
# ---------------------------------------------------------------------------
# adb: Android platform-tools
# ---------------------------------------------------------------------------
function Get-PlatformTools {
    param([string]$Dest)
    $url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    $zip = Join-Path $env:TEMP "platform-tools.zip"
    Write-Host "[adb] platform-tools indiriliyor..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    $parent = Split-Path -Parent $Dest
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Expand-Archive -Path $zip -DestinationPath $parent -Force
    Remove-Item $zip -Force
    Write-Host "[adb] Tamamlandi -> $Dest\adb.exe"
}

```

Ve `# Calistir` bloğunda `jdk` bloğundan sonra ekle:

```powershell
if ($Only -contains "adb") {
    Get-PlatformTools -Dest (Join-Path $OutputDir "platform-tools")
}
```

- [ ] **Step 2: `-Only adb` ile çalıştır ve doğrula**

Run:
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only adb -OutputDir .\.scratch-bundle
```
Expected: `[adb] Tamamlandi -> ...\platform-tools\adb.exe`

Doğrula:
```
.\.scratch-bundle\platform-tools\adb.exe version
```
Expected: `Android Debug Bridge version ...` çıktısı.

```bash
rm -rf .scratch-bundle
```

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Build script: Android platform-tools (adb) indirme adimi ekle"
```

---

### Task 9: Build script — Chrome for Testing chromedriver eşleme

**Files:**
- Modify: `backend/deploy/build_offline_bundle.ps1`

**Interfaces:**
- Consumes: `-ChromeMajorVersion` parametresi (varsayılan `"136"`, kullanıcı sunucudaki Chrome sürümü olan `136.0.7103.114` ile eşleşiyor).
- Produces: `$OutputDir/chromedriver/chromedriver.exe` (Task 1'in `CHROMEDRIVER_PATH` ile beklediği dosya).

- [ ] **Step 1: `Get-ChromeDriverForTesting` fonksiyonunu ekle**

`Get-PlatformTools` fonksiyonundan sonra, `# Calistir` bloğundan önce ekle:

```powershell
# ---------------------------------------------------------------------------
# chromedriver: Chrome for Testing - kurulu Chrome surumune uygun chromedriver
# ---------------------------------------------------------------------------
function Get-ChromeDriverForTesting {
    param([string]$MajorVersion, [string]$Dest)
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $jsonUrl = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
    Write-Host "[chromedriver] Surum listesi aliniyor..."
    $data = Invoke-RestMethod -Uri $jsonUrl
    $match = $data.versions | Where-Object { $_.version -like "$MajorVersion.*" } | Select-Object -Last 1
    if (-not $match) { throw "Chrome $MajorVersion icin chromedriver bulunamadi" }
    $win64 = $match.downloads.chromedriver | Where-Object { $_.platform -eq 'win64' } | Select-Object -First 1
    if (-not $win64) { throw "win64 chromedriver indirme linki bulunamadi (versiyon $($match.version))" }

    $zipPath = Join-Path $env:TEMP "chromedriver-win64.zip"
    Write-Host "[chromedriver] $($match.version) indiriliyor..."
    Invoke-WebRequest -Uri $win64.url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force
    $exe = Get-ChildItem -Path $env:TEMP -Filter "chromedriver.exe" -Recurse | Select-Object -First 1
    if (-not $exe) { throw "chromedriver.exe zip icinde bulunamadi" }
    Copy-Item $exe.FullName -Destination (Join-Path $Dest "chromedriver.exe") -Force
    Remove-Item $zipPath -Force
    Remove-Item $exe.DirectoryName -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[chromedriver] Tamamlandi ($($match.version)) -> $Dest\chromedriver.exe"
}

```

Ve `# Calistir` bloğunda `adb` bloğundan sonra ekle:

```powershell
if ($Only -contains "chromedriver") {
    Get-ChromeDriverForTesting -MajorVersion $ChromeMajorVersion -Dest (Join-Path $OutputDir "chromedriver")
}
```

Ayrıca en alttaki `Write-Host "Bundle hazir (kismi): $OutputDir"` satırını, tüm aşamalar artık mevcut olduğu için şuna güncelle:

```powershell
Write-Host ""
Write-Host "Bundle hazir: $OutputDir"
```

- [ ] **Step 2: `-Only chromedriver` ile çalıştır ve doğrula**

Run:
```
powershell -File backend\deploy\build_offline_bundle.ps1 -Only chromedriver -ChromeMajorVersion 136 -OutputDir .\.scratch-bundle
```
Expected: `[chromedriver] Tamamlandi (136.x.x.x) -> ...\chromedriver\chromedriver.exe`

Doğrula:
```
.\.scratch-bundle\chromedriver\chromedriver.exe --version
```
Expected: `ChromeDriver 136.x.x.x ...` — sunucudaki Chrome `136.0.7103.114` ile major sürüm eşleşiyor.

```bash
rm -rf .scratch-bundle
```

- [ ] **Step 3: Tam bundle'ı uçtan uca üret (tüm aşamalar birlikte)**

Run:
```
powershell -File backend\deploy\build_offline_bundle.ps1 -OutputDir .\.scratch-bundle-full -ChromeMajorVersion 136
```
Expected: Tüm `[app]`, `[python]`, `[node]`, `[jdk]`, `[adb]`, `[chromedriver]` adımları sırayla tamamlanır, sonda `Bundle hazir: .\.scratch-bundle-full` yazdırılır.

```bash
ls .scratch-bundle-full
rm -rf .scratch-bundle-full
```
Expected: `app`, `wheels`, `python-installer`, `node-portable`, `appium-global`, `jdk`, `platform-tools`, `chromedriver`, `install_offline.bat`, `offline-requirements.txt` klasör/dosyaları listelenir.

- [ ] **Step 4: Commit**

```bash
git add backend/deploy/build_offline_bundle.ps1
git commit -m "Build script: Chrome for Testing chromedriver eslestirme adimi ekle, script'i tamamla"
```

---

### Task 10: Ops runbook — offline deployment README + sunucu doğrulama listesi

**Files:**
- Create: `backend/deploy/README-offline-deploy.md`

**Interfaces:**
- Yok (dokümantasyon dosyası); Task 1-9'da üretilen script/dosya adlarına referans verir.

- [ ] **Step 1: README'yi oluştur**

```markdown
# Offline Sunucu Kurulumu

Bu klasördeki scriptler, internete **hiçbir şekilde** çıkamayan bir Windows x64
sunucuya OtomasyoTool'u kurmak için kullanılır.

## 1. Build makinesinde (internetli) bundle oluştur

```
cd backend
powershell -File deploy\build_offline_bundle.ps1 -OutputDir .\OtomasyoTool-Offline-Bundle -ChromeMajorVersion 136
```

`-ChromeMajorVersion` parametresini sunucuda kurulu Chrome'un ana sürümüyle
eşleştirin (sunucuda `chrome://version` sayfasından kontrol edilebilir).

Çıktı: `OtomasyoTool-Offline-Bundle\` klasörü (birkaç GB, wheels + Node + JDK +
ADB + chromedriver + Python installer + kaynak kod içerir).

## 2. USB/harici disk ile sunucuya taşı

`OtomasyoTool-Offline-Bundle` klasörünü olduğu gibi sunucuya kopyalayın.

## 3. Sunucuda kur (internet YOK, gerekmez)

```
cd OtomasyoTool-Offline-Bundle
install_offline.bat C:\OtomasyoTool
```

Script başarısız olursa (`HATA: ...`), ilgili adımı (Python kurulumu / pip
install / dosya kopyalama) yeniden çalıştırın; script internete çıkmaz, tüm
hata nedenleri yerel dosya eksikliği veya izin sorunudur.

## 4. Admin kullanıcı oluştur ve başlat

```
cd C:\OtomasyoTool\backend
venv\Scripts\python.exe make_admin.py
run_offline.bat
```

## 5. Doğrulama Kontrol Listesi

- [ ] `http://localhost:8000/docs` (Swagger) tarayıcıdan açılıyor.
- [ ] `http://localhost:8000/ui` web arayüzü açılıyor, admin ile giriş yapılabiliyor.
- [ ] `platform-tools\adb.exe devices` bağlı fiziksel Android cihazı listeliyor.
- [ ] Örnek bir Web (Chrome/Selenium) senaryosu uçtan uca çalışıyor — `chromedriver`
      internetten indirilmeye çalışılmıyor (loglarda `Yerel ChromeDriver
      kullaniliyor (offline mod)` satırı görünmeli).
- [ ] Örnek bir Mobil (Appium) senaryosu fiziksel cihazda çalışıyor —
      `appium-global\appium.cmd driver list --installed` çıktısında
      `uiautomator2` görünüyor. Görünmüyorsa: internete çıkmadan
      `appium-global\appium.cmd driver install --source=local <appium-global
      icindeki appium-uiautomator2-driver klasor yolu>` ile yeniden kaydedin.
- [ ] Bir Desktop otomasyon senaryosu (pywinauto) çalışıyor.
- [ ] Kurulum ve çalışma sırasında Kaynak Monitörü / `netstat -ano` ile dışa
      giden bağlantı denemesi olmadığı teyit edildi.

## 6. Gelecekte güncelleme

Kod veya bağımlılık değiştiğinde: build makinesinde bundle'ı yeniden üretin
(`build_offline_bundle.ps1`), USB ile taşıyın, sunucuda `install_offline.bat`'ı
tekrar çalıştırın (mevcut `venv`/klasörlerin üzerine güvenle yazar). Sunucu bu
süreçte de hiçbir zaman `git pull` veya internetten indirme yapmaz.
```

- [ ] **Step 2: Script/dosya adlarının tutarlılığını doğrula**

Run:
```bash
grep -o '[a-zA-Z_.-]*\.bat\|[a-zA-Z_.-]*\.ps1' backend/deploy/README-offline-deploy.md | sort -u
ls backend/deploy/
```
Expected: README'de geçen tüm dosya adları (`build_offline_bundle.ps1`, `install_offline.bat`, `run_offline.bat` — bu backend/ kökünde) gerçekten mevcut/oluşturulmuş olmalı.

- [ ] **Step 3: Commit**

```bash
git add backend/deploy/README-offline-deploy.md
git commit -m "Offline dagitim icin ops runbook ve dogrulama listesi ekle"
```
