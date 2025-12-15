@echo off
echo.
echo ========================================
echo    Test Otomasyon Platformu Kurulum
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] Python kontrol ediliyor...
python --version
if %errorlevel% neq 0 (
    echo HATA: Python bulunamadi!
    echo https://www.python.org/downloads/ adresinden indirin
    pause
    exit /b 1
)
echo OK
echo.

echo [2/4] ADB kontrol ediliyor...
if exist "platform-tools\adb.exe" (
    echo ADB zaten mevcut
) else (
    echo ADB indiriliyor... Lutfen bekleyin...
    curl -L -o platform-tools.zip "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    if exist "platform-tools.zip" (
        echo Cikartiliyor...
        powershell -command "Expand-Archive -Path 'platform-tools.zip' -DestinationPath '.' -Force"
        del platform-tools.zip
        echo ADB kuruldu
    ) else (
        echo HATA: ADB indirilemedi
    )
)
echo.

echo [3/4] Virtual environment hazirlaniyor...
if not exist "venv" (
    python -m venv venv
)
echo OK
echo.

echo [4/4] Bagimliliklar yukleniyor...
call venv\Scripts\activate.bat
pip install -r requirements.txt
echo.

echo ========================================
echo    KURULUM TAMAMLANDI
echo ========================================
echo.
echo Baslatmak icin: run.bat
echo.
pause
