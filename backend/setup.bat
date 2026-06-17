@echo off
echo.
echo ========================================
echo    Test Otomasyon Platformu Kurulum
echo ========================================
echo.

set REPO_SSH=git@github.com:SadkDemr/OtomasyoToolFastApi.git
set INSTALL_DIR=C:\OtomasyoTool

REM ─── 1. PYTHON ────────────────────────────────────────────────────────────────
echo [1/8] Python kontrol ediliyor...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   HATA: Python bulunamadi!
    echo   https://www.python.org/downloads/ adresinden Python 3.11+ kurun.
    echo   Kurulumda "Add Python to PATH" secenegini isaretleyin.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   %%i - OK
echo.

REM ─── 2. GIT ───────────────────────────────────────────────────────────────────
echo [2/8] Git kontrol ediliyor...
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Git bulunamadi. Indiriliyor...
    curl -L -o git-setup.exe "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
    git-setup.exe /VERYSILENT /NORESTART /NOCANCEL
    del git-setup.exe
    set "PATH=%PATH%;C:\Program Files\Git\bin;C:\Program Files\Git\usr\bin"
    echo   Git kuruldu - OK
) else (
    for /f "tokens=*" %%i in ('git --version 2^>^&1') do echo   %%i - OK
)
echo.

REM ─── 3. SSH KEY ───────────────────────────────────────────────────────────────
echo [3/8] GitHub SSH Key kontrol ediliyor...
if not exist "%USERPROFILE%\.ssh\id_ed25519" (
    echo   SSH key olusturuluyor...
    if not exist "%USERPROFILE%\.ssh" mkdir "%USERPROFILE%\.ssh"
    ssh-keygen -t ed25519 -C "otomasyon-tool-server" -f "%USERPROFILE%\.ssh\id_ed25519" -N ""
)
echo.
echo   ╔══════════════════════════════════════════════════════════════╗
echo   ║  GitHub'a eklenecek PUBLIC KEY:                              ║
echo   ║  Repo -^> Settings -^> Deploy Keys -^> Add Key (Allow write)  ║
echo   ╚══════════════════════════════════════════════════════════════╝
echo.
type "%USERPROFILE%\.ssh\id_ed25519.pub"
echo.
echo   Yukaridaki key'i GitHub Deploy Keys'e ekledikten sonra Enter'a basin...
pause >nul
echo.

REM SSH agent baslat ve key ekle (clone icin gerekli)
start /b ssh-agent >nul 2>&1
for /f "tokens=*" %%i in ('ssh-agent -s 2^>^&1') do (
    echo %%i | findstr "SSH_AUTH_SOCK" >nul && set %%i
    echo %%i | findstr "SSH_AGENT_PID" >nul && set %%i
)
ssh-add "%USERPROFILE%\.ssh\id_ed25519" >nul 2>&1

REM Port 22 bloklu olabilir — GitHub'i port 443 uzerinden bagla
REM Bu ayar hem clone hem de run.bat pull icin gecerlidir
(
    echo Host github.com
    echo     Hostname ssh.github.com
    echo     Port 443
    echo     User git
    echo     IdentityFile %USERPROFILE%\.ssh\id_ed25519
    echo     StrictHostKeyChecking no
) > "%USERPROFILE%\.ssh\config"

REM GitHub host key'ini known_hosts'a ekle (ilk baglanmada "yes" sormamak icin)
ssh-keyscan -p 443 ssh.github.com >> "%USERPROFILE%\.ssh\known_hosts" 2>nul

REM ─── 4. REPO CLONE ────────────────────────────────────────────────────────────
echo [4/8] Repo kontrol ediliyor...
if exist "main.py" (
    echo   Zaten repo icindeyiz - clone atlaniyor.
    set "BACKEND_DIR=%~dp0"
) else if exist "%INSTALL_DIR%\backend\main.py" (
    echo   Repo zaten mevcut: %INSTALL_DIR%
    set "BACKEND_DIR=%INSTALL_DIR%\backend"
) else (
    echo   Repo klonlaniyor: %INSTALL_DIR%
    git clone %REPO_SSH% "%INSTALL_DIR%"
    if %errorlevel% neq 0 (
        echo   HATA: Clone basarisiz! SSH key GitHub'a eklendi mi?
        pause
        exit /b 1
    )
    set "BACKEND_DIR=%INSTALL_DIR%\backend"
    echo   Clone tamamlandi - OK
)
cd /d "%BACKEND_DIR%"
echo.

REM ─── 5. NODE.JS ───────────────────────────────────────────────────────────────
echo [5/8] Node.js kontrol ediliyor...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Node.js bulunamadi. Indiriliyor... (~30MB)
    curl -L -o node-setup.msi "https://nodejs.org/dist/v20.15.0/node-v20.15.0-x64.msi"
    msiexec /i node-setup.msi /quiet /norestart
    del node-setup.msi
    set "PATH=%PATH%;C:\Program Files\nodejs"
    echo   Node.js kuruldu - OK
) else (
    for /f "tokens=*" %%i in ('node --version 2^>^&1') do echo   Node.js %%i - OK
)
echo.

REM ─── 6. JAVA ──────────────────────────────────────────────────────────────────
echo [6/8] Java kontrol ediliyor...
java -version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Java bulunamadi. Indiriliyor... (Temurin JDK 11, ~170MB)
    curl -L -o jdk-setup.msi "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.23+9/OpenJDK11U-jdk_x64_windows_hotspot_11.0.23_9.msi"
    msiexec /i jdk-setup.msi /quiet /norestart ADDLOCAL=FeatureMain,FeatureEnvironment,FeatureJarFileRunWith,FeatureJavaHome
    del jdk-setup.msi
    for /d %%d in ("C:\Program Files\Eclipse Adoptium\jdk-11*") do set "PATH=%PATH%;%%d\bin"
    echo   Java kuruldu - OK
) else (
    for /f "tokens=*" %%i in ('java -version 2^>^&1') do echo   %%i - OK & goto :java_done
    :java_done
)
echo.

REM ─── 7. ADB ───────────────────────────────────────────────────────────────────
echo [7/8] ADB kontrol ediliyor...
if exist "platform-tools\adb.exe" (
    echo   ADB zaten mevcut - OK
) else (
    echo   ADB indiriliyor...
    curl -L -o platform-tools.zip "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    if exist "platform-tools.zip" (
        powershell -command "Expand-Archive -Path 'platform-tools.zip' -DestinationPath '.' -Force"
        del platform-tools.zip
        echo   ADB kuruldu - OK
    ) else (
        echo   HATA: ADB indirilemedi
    )
)
echo.

REM ─── 8. PYTHON VENV + PAKETLER + APPIUM ──────────────────────────────────────
echo [8/8] Python ortami ve Appium hazirlaniyor...
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat

REM pip, setuptools ve wheel'i guncelle
echo   pip guncelleniyor...
python -m pip install --upgrade pip setuptools wheel --timeout 120 --retries 5 -q

REM Ana bagimliliklar
echo   Ana paketler yukleniyor...
pip install -r requirements.txt --prefer-binary --timeout 120 --retries 5
if %errorlevel% neq 0 (
    echo   UYARI: Bazi paketler yuklenemedi. Tekrar deneniyor...
    pip install -r requirements.txt --prefer-binary --timeout 180 --retries 10
)

REM Goruntu/otomasyon paketleri (opsiyonel, hata olursa devam et)
echo   Goruntu/otomasyon paketleri yukleniyor...
pip install Pillow opencv-python pyperclip --prefer-binary --timeout 120 --retries 5 -q
pip install pyautogui --prefer-binary --timeout 120 --retries 5 -q
if %errorlevel% neq 0 (
    echo   UYARI: pyautogui yuklenemedi - Desktop otomasyon ozelligi calismaYabilir.
)

echo   Python paketleri yuklendi - OK

appium --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Appium kuruluyor...
    npm install -g appium
    appium driver install uiautomator2
    echo   Appium kuruldu - OK
) else (
    for /f "tokens=*" %%i in ('appium --version 2^>^&1') do echo   Appium %%i - OK
)
echo.

REM ─── TAMAMLANDI ───────────────────────────────────────────────────────────────
echo ========================================
echo    KURULUM TAMAMLANDI
echo ========================================
echo.
echo Sonraki adimlar:
echo   1. Admin kullanici olusturun:  python make_admin.py
echo   2. Uygulamayi baslatin:        run.bat
echo.
pause
