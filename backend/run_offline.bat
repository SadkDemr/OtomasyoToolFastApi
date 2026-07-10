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
