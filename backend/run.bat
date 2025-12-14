@echo off
cd /d "%~dp0"

echo ============================================
echo    Test Otomasyon Platformu API v2.0
echo ============================================

if not exist "venv" (
    echo Venv olusturuluyor...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Bagimliliklar yukleniyor...
pip install -r requirements.txt -q

echo.
echo Swagger UI: http://localhost:8000/docs
echo.

python main.py

pause
