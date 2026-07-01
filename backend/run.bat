@echo off
cd /d "%~dp0"

if not exist "venv" (
    echo HATA: Once setup.bat calistirin!
    pause
    exit /b 1
)

echo.
echo GitHub'dan guncelleme cekiliyor...
cd /d "%~dp0.."
git remote set-url origin https://github.com/SadkDemr/OtomasyoToolFastApi.git
git pull
cd /d "%~dp0"
echo Guncelleme tamamlandi.
echo.

call venv\Scripts\activate.bat

REM Paketler yuklu mu kontrol et, yoksa yukle
python -c "import fastapi" >nul 2>&1
if %errorlevel% neq 0 (
    echo   Paketler eksik, yukleniyor...
    python -m pip install --upgrade pip setuptools wheel --timeout 120 --retries 5 -q

    REM 1. Kritik paketler (hata olursa dur)
    pip install fastapi==0.104.1 "uvicorn[standard]==0.24.0" python-multipart==0.0.6 "pydantic[email]==2.5.2" sqlalchemy==2.0.23 "python-jose[cryptography]>=3.3.0" "passlib[bcrypt]==1.7.4" "bcrypt>=4.0.0" selenium==4.15.2 webdriver-manager==4.0.1 Appium-Python-Client==3.1.0 requests==2.31.0 httpx==0.27.0 --prefer-binary --timeout 120 --retries 5
    if %errorlevel% neq 0 (
        echo HATA: Kritik paketler yuklenemedi!
        pause
        exit /b 1
    )

    REM 2. Opsiyonel paketler (hata olursa devam et)
    pip install "openpyxl>=3.1.2" "pandas>=2.2.0" --prefer-binary --timeout 120 --retries 5 -q
    if %errorlevel% neq 0 echo   UYARI: pandas/openpyxl yuklenemedi - Excel ozelligi calismaYabilir.

    pip install Pillow opencv-python pyperclip --prefer-binary --timeout 120 -q
    pip install pyautogui pywinauto --prefer-binary --timeout 120 -q
    if %errorlevel% neq 0 echo   UYARI: pyautogui/pywinauto yuklenemedi - Desktop otomasyon ozelligi calismaYabilir.
)

echo.
echo ========================================
echo    Test Otomasyon Platformu v2.1
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

REM Log klasoru olustur
if not exist "logs" mkdir logs

REM Timestamp ile log dosyasi adi (PowerShell ile - wmic bazi sunucularda yok)
for /f %%i in ('powershell -NoProfile -NonInteractive -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set DT=%%i
set LOGFILE=logs\server_%DT%.log

echo Loglar: %LOGFILE%
echo.

REM Port 8000'de takili kalmis eski surec varsa sonlandir
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Port 8000 kullanimda, eski surec sonlandiriliyor ^(PID %%p^)...
    taskkill /F /PID %%p >nul 2>&1
)

REM UTF-8 encoding ayarla (emoji ve Turkce karakter icin)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Konsola VE log dosyasina yaz (PowerShell Tee-Object)
powershell -NoProfile -NonInteractive -Command "python main.py | Tee-Object -FilePath '%LOGFILE%' -Append"

pause
