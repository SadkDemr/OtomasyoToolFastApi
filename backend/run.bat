@echo off
cd /d "%~dp0"

if not exist "venv" (
    echo HATA: Once setup.bat calistirin!
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

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

python main.py

pause
