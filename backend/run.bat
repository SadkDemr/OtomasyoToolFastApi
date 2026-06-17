@echo off
cd /d "%~dp0"

if not exist "venv" (
    echo HATA: Once setup.bat calistirin!
    pause
    exit /b 1
)

echo.
echo GitHub'dan guncelleme cekiliyor...
REM SSH agent baslat ve key yukle
start /b ssh-agent >nul 2>&1
ssh-add "%USERPROFILE%\.ssh\id_ed25519" >nul 2>&1
REM Port 443 uzerinden SSH (port 22 bloklu ortamlar icin)
if not exist "%USERPROFILE%\.ssh\config" (
    (
        echo Host github.com
        echo     Hostname ssh.github.com
        echo     Port 443
        echo     User git
        echo     IdentityFile %USERPROFILE%\.ssh\id_ed25519
        echo     StrictHostKeyChecking no
    ) > "%USERPROFILE%\.ssh\config"
)
REM Remote'u SSH'a cevir (ilk calistirmada HTTPS ise degistir)
cd /d "%~dp0.."
git remote set-url origin git@github.com:SadkDemr/OtomasyoToolFastApi.git
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
    pip install -r requirements.txt --prefer-binary --timeout 120 --retries 5
    pip install Pillow opencv-python pyperclip --prefer-binary --timeout 120 -q
    pip install pyautogui --prefer-binary --timeout 120 -q
    if %errorlevel% neq 0 echo   UYARI: pyautogui yuklenemedi.
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

python main.py

pause
