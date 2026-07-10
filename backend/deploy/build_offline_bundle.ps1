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

# OutputDir, backend klasorunun icinde olamaz: Copy-AppSource, $BackendDir'i
# oldugu gibi kopyalar, eger $OutputDir da $BackendDir'in altindaysa script
# kendi ureteceği bundle klasorunu de kopyalamaya calisir ve sonsuz/kendi
# kendini iceren bir kopyalamaya (path uzunlugu asimina) yol acar.
$ResolvedBackendDir = [System.IO.Path]::GetFullPath($BackendDir)
$ResolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDir))
$BackendDirWithSep = $ResolvedBackendDir.TrimEnd('\') + '\'
if ($ResolvedOutputDir -eq $ResolvedBackendDir.TrimEnd('\') -or $ResolvedOutputDir.StartsWith($BackendDirWithSep, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir ('$ResolvedOutputDir') backend klasorunun ('$ResolvedBackendDir') icinde olamaz - script kendi bundle ciktisini da kopyalamaya calisir. Backend disinda bir klasor secin (orn. -OutputDir '..\OtomasyoTool-Offline-Bundle')."
}

# ---------------------------------------------------------------------------
# app: backend kaynak kodunu kopyala
# ---------------------------------------------------------------------------
function Copy-AppSource {
    param([string]$Dest)
    Write-Host "[app] Backend kaynak kodu kopyalaniyor -> $Dest"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $exclude = @('venv', 'logs', '__pycache__', '.git', 'node-portable', 'appium-global', 'jdk', 'chromedriver', 'wheels', 'test_platform.db', 'test_platform.db-shm', 'test_platform.db-wal', 'platform-tools', 'workspaces', 'uploads', 'screenshots', 'desktop_data', 'mnt', 'reports', 'ai_config.json', 'deploy')
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

    # pyautogui ve alt bagimliliklari (pyscreeze, pygetwindow, pytweening,
    # mouseinfo, pyrect) sdist oldugundan, sunucuda pip bunlari PEP 517 build
    # isolation ile (install_offline.bat --no-build-isolation KULLANMIYOR,
    # bilerek) izole bir gecici ortamda derleyecek. pip, bu izole ortam icin
    # kendi ic pip cagrisini disaridaki --no-index/--find-links ayarlarini
    # miras alarak yapar (bkz. pypa/pip#12270), bu yuzden setuptools/wheel
    # burada wheels/ klasorunde bulunursa derleme tamamen yerelde/offline
    # tamamlanir. Bu ampirik olarak dogrulandi: --no-build-isolation ile
    # venv'de wheel paketi olmadigindan "error: invalid command 'bdist_wheel'"
    # ile basarisiz oluyor; --no-build-isolation OLMADAN (varsayilan izole
    # build ile) ise izole ortam wheels/ klasorunden setuptools/wheel'i
    # buluyor ve derleme basariyla tamamlaniyor - internete hic cikilmiyor.
    Write-Host "[python] setuptools/wheel indiriliyor (izole PEP 517 build ortami icin, internet gerektirmesin diye)..."
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
# jdk: portable Temurin JDK 11 (zip - kurulum gerektirmez)
# ---------------------------------------------------------------------------
function Get-JdkPortable {
    param([string]$Dest)
    $jdkUrl = "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.23%2B9/OpenJDK11U-jdk_x64_windows_hotspot_11.0.23_9.zip"
    $jdkZip = Join-Path $env:TEMP "temurin11.zip"
    Write-Host "[jdk] Temurin JDK 11 indiriliyor..."
    Invoke-WebRequest -Uri $jdkUrl -OutFile $jdkZip
    Expand-Archive -Path $jdkZip -DestinationPath $env:TEMP -Force
    $extracted = Get-ChildItem -Path $env:TEMP -Directory -Filter "jdk-11*" | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Path (Join-Path $extracted.FullName "*") -Destination $Dest -Recurse -Force
    Remove-Item $jdkZip -Force
    Remove-Item $extracted.FullName -Recurse -Force
    Write-Host "[jdk] Tamamlandi -> $Dest\bin\java.exe"
}

# ---------------------------------------------------------------------------
# adb: Android platform-tools
# ---------------------------------------------------------------------------
function Get-PlatformTools {
    param([string]$Dest)
    $url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    $zip = Join-Path $env:TEMP "platform-tools.zip"
    Write-Host "[adb] platform-tools indiriliyor..."
    Invoke-WebRequest -Uri $url -OutFile $zip
    $parent = Split-Path -Parent $Dest
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Expand-Archive -Path $zip -DestinationPath $parent -Force
    Remove-Item $zip -Force
    Write-Host "[adb] Tamamlandi -> $Dest\adb.exe"
}

# ---------------------------------------------------------------------------
# chromedriver: Chrome for Testing - kurulu Chrome surumune uygun chromedriver
# ---------------------------------------------------------------------------
function Get-ChromeDriverForTesting {
    param([string]$MajorVersion, [string]$Dest)
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $jsonUrl = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
    Write-Host "[chromedriver] Surum listesi aliniyor..."
    $data = Invoke-RestMethod -Uri $jsonUrl
    $match = $data.versions | Where-Object { $_.version -like "$MajorVersion.*" } | Select-Object -Last 1
    if (-not $match) { throw "Chrome $MajorVersion icin chromedriver bulunamadi" }
    $win64 = $match.downloads.chromedriver | Where-Object { $_.platform -eq 'win64' } | Select-Object -First 1
    if (-not $win64) { throw "win64 chromedriver indirme linki bulunamadi (versiyon $($match.version))" }

    $zipPath = Join-Path $env:TEMP "chromedriver-win64.zip"
    Write-Host "[chromedriver] $($match.version) indiriliyor..."
    Invoke-WebRequest -Uri $win64.url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force
    $exe = Get-ChildItem -Path $env:TEMP -Filter "chromedriver.exe" -Recurse | Select-Object -First 1
    if (-not $exe) { throw "chromedriver.exe zip icinde bulunamadi" }
    Copy-Item $exe.FullName -Destination (Join-Path $Dest "chromedriver.exe") -Force
    Remove-Item $zipPath -Force
    Remove-Item $exe.DirectoryName -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[chromedriver] Tamamlandi ($($match.version)) -> $Dest\chromedriver.exe"
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

if ($Only -contains "jdk") {
    Get-JdkPortable -Dest (Join-Path $OutputDir "jdk")
}

if ($Only -contains "adb") {
    Get-PlatformTools -Dest (Join-Path $OutputDir "platform-tools")
}

if ($Only -contains "chromedriver") {
    Get-ChromeDriverForTesting -MajorVersion $ChromeMajorVersion -Dest (Join-Path $OutputDir "chromedriver")
}

Copy-Item -Path (Join-Path $DeployDir "install_offline.bat") -Destination (Join-Path $OutputDir "install_offline.bat") -Force
Copy-Item -Path (Join-Path $DeployDir "offline-requirements.txt") -Destination (Join-Path $OutputDir "offline-requirements.txt") -Force

Write-Host ""
Write-Host "Bundle hazir: $OutputDir"
