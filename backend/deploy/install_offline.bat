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
