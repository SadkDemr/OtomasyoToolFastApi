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
    $exclude = @('venv', 'logs', '__pycache__', '.git', 'node-portable', 'appium-global', 'jdk', 'chromedriver', 'wheels', 'test_platform.db', 'test_platform.db-shm', 'test_platform.db-wal')
    Get-ChildItem -Path $BackendDir -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $Dest $_.Name) -Recurse -Force
    }
    Write-Host "[app] Tamamlandi."
}

# ---------------------------------------------------------------------------
# Calistir
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if ($Only -contains "app") {
    Copy-AppSource -Dest (Join-Path $OutputDir "app")
}

Copy-Item -Path (Join-Path $DeployDir "install_offline.bat") -Destination (Join-Path $OutputDir "install_offline.bat") -Force
Copy-Item -Path (Join-Path $DeployDir "offline-requirements.txt") -Destination (Join-Path $OutputDir "offline-requirements.txt") -Force

Write-Host ""
Write-Host "Bundle hazir (kismi): $OutputDir"
