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
# node: portable Node.js + Appium (global npm prefix) + uiautomator2 driver
# ---------------------------------------------------------------------------
function Get-NodeAndAppium {
    param([string]$NodeDest, [string]$AppiumDest)
    New-Item -ItemType Directory -Force -Path $NodeDest | Out-Null

    # Not: v20.15.0 (ilk secilen surum) 'require(esm)' destegini icermiyor
    # (bu destek Node 20.19.0+ ile geldi). Appium 3.x'in bagimliligi olan
    # asyncbox@6.3.0, p-limit@^7 (sadece ESM, CJS exportu yok) paketini
    # require() ile yukledigi icin v20.15.0'da "ERR_REQUIRE_ESM" hatasiyla
    # cakisir. v20.20.2 (guncel 20.x LTS) bu destegi icerdiginden kullanildi.
    $nodeUrl = "https://nodejs.org/dist/v20.20.2/node-v20.20.2-win-x64.zip"
    $nodeZip = Join-Path $env:TEMP "node-v20.20.2-win-x64.zip"
    Write-Host "[node] Node.js indiriliyor..."
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip
    Expand-Archive -Path $nodeZip -DestinationPath $env:TEMP -Force
    Copy-Item -Path (Join-Path $env:TEMP "node-v20.20.2-win-x64\*") -Destination $NodeDest -Recurse -Force
    Remove-Item $nodeZip -Force
    Remove-Item (Join-Path $env:TEMP "node-v20.20.2-win-x64") -Recurse -Force

    $npmCmd = Join-Path $NodeDest "npm.cmd"

    Write-Host "[node] Appium global olarak kuruluyor..."
    New-Item -ItemType Directory -Force -Path $AppiumDest | Out-Null
    # -g (global) onemli: -g olmadan --prefix bir "local" proje kurulumu gibi
    # davranir ve appium.cmd shim'i $AppiumDest\node_modules\.bin altina konur.
    # -g ile birlikte --prefix, $AppiumDest'i npm'in global prefix'i gibi
    # kullanir ve appium.cmd shim'ini dogrudan $AppiumDest koku altina koyar
    # (asagidaki $appiumCmd yolunun bekledigi yer).
    & $npmCmd install -g --prefix $AppiumDest appium --loglevel=error
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

if ($Only -contains "node") {
    Get-NodeAndAppium -NodeDest (Join-Path $OutputDir "node-portable") -AppiumDest (Join-Path $OutputDir "appium-global")
}

Copy-Item -Path (Join-Path $DeployDir "install_offline.bat") -Destination (Join-Path $OutputDir "install_offline.bat") -Force
Copy-Item -Path (Join-Path $DeployDir "offline-requirements.txt") -Destination (Join-Path $OutputDir "offline-requirements.txt") -Force

Write-Host ""
Write-Host "Bundle hazir (kismi): $OutputDir"
