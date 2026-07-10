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
    $exclude = @('venv', 'logs', '__pycache__', '.git', 'node-portable', 'appium-global', 'jdk', 'chromedriver', 'wheels', 'test_platform.db', 'test_platform.db-shm', 'test_platform.db-wal', 'platform-tools', 'workspaces', 'uploads', 'screenshots', 'desktop_data', 'mnt', 'reports')
    Get-ChildItem -Path $BackendDir -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $Dest $_.Name) -Recurse -Force
    }
    Write-Host "[app] Tamamlandi."
}

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

    # pyautogui PyPI'da hicbir surumde wheel yayinlamiyor (sadece sdist) ve bu
    # yuzden --only-binary=:all: ile birlikte indirilemiyor. pip, cross-platform
    # kisitlamalari (--python-version/--platform/--implementation) kullanilirken
    # --no-binary istisnasina izin vermiyor ("either --no-deps must be set, or
    # --only-binary=:all: must be set and --no-binary must not be set"), bu
    # yuzden pyautogui'yi requirements listesinden ayirip ayri bir pip download
    # cagrisiyla indiriyoruz. pyautogui pure-python oldugu (derleyici gerektirmez)
    # ve alt bagimliliklari (pygetwindow, pyscreeze, pytweening, mouseinfo,
    # pymsgbox, pyrect, pyperclip) de platformdan bagimsiz oldugu icin bu guvenli.
    $tmpReqFile = Join-Path $env:TEMP "offline-requirements-no-pyautogui.txt"
    Get-Content $reqFile | Where-Object { $_ -notmatch '^\s*pyautogui\s*$' } | Set-Content $tmpReqFile

    Write-Host "[python] Wheel'ler indiriliyor (pip download)..."
    python -m pip download -r $tmpReqFile -d $WheelsDest --only-binary=:all: --python-version 311 --platform win_amd64 --implementation cp
    if ($LASTEXITCODE -ne 0) { throw "pip download basarisiz (exit $LASTEXITCODE)" }

    Write-Host "[python] pyautogui indiriliyor (wheel yoksa sdist'e dusulur)..."
    python -m pip download pyautogui -d $WheelsDest
    if ($LASTEXITCODE -ne 0) { throw "pip download basarisiz - pyautogui (exit $LASTEXITCODE)" }

    # pyautogui ve alt bagimliliklari sdist oldugundan, sunucuda pip bunlari
    # --no-build-isolation ile mevcut venv'in setuptools/wheel'ini kullanarak
    # derleyecek (bkz. install_offline.bat). Cok minimal bir venv'de bunlar
    # guncel olmayabilir; belirtip-kemer onlemi olarak wheel'lerini de indiriyoruz.
    Write-Host "[python] setuptools/wheel indiriliyor (sdist build icin, internet gerektirmesin diye)..."
    python -m pip download setuptools wheel -d $WheelsDest --only-binary=:all: --python-version 311 --platform win_amd64 --implementation cp
    if ($LASTEXITCODE -ne 0) { throw "pip download (setuptools/wheel) basarisiz (exit $LASTEXITCODE)" }

    Remove-Item -Force $tmpReqFile -ErrorAction SilentlyContinue
    Write-Host "[python] Tamamlandi."
}

# ---------------------------------------------------------------------------
# Calistir
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if ($Only -contains "app") {
    Copy-AppSource -Dest (Join-Path $OutputDir "app")
}

if ($Only -contains "python") {
    Get-PythonAndWheels -Dest (Join-Path $OutputDir "python-installer") -WheelsDest (Join-Path $OutputDir "wheels")
}

Copy-Item -Path (Join-Path $DeployDir "install_offline.bat") -Destination (Join-Path $OutputDir "install_offline.bat") -Force
Copy-Item -Path (Join-Path $DeployDir "offline-requirements.txt") -Destination (Join-Path $OutputDir "offline-requirements.txt") -Force

Write-Host ""
Write-Host "Bundle hazir (kismi): $OutputDir"
