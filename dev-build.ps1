# Baut das Installationsprogramm:  dist\installer\WorkPlanner-Setup-<Version>.exe
#   1. Symbol (assets\workplanner.ico) aus dem gezeichneten Uhr-Symbol
#   2. Programmordner dist\WorkPlanner\ mit PyInstaller (ohne Konsolenfenster)
#   3. Installer mit Inno Setup 6
# Voraussetzungen: pip install pyinstaller pillow ; Inno Setup 6 (winget install JRSoftware.InnoSetup)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what ist fehlgeschlagen (Exit-Code $LASTEXITCODE)." } }

Write-Host "Abhängigkeiten prüfen (requirements-dev.txt) ..." -ForegroundColor Cyan
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt; Check "pip install"
python tools\bump_version.py | Out-Null; Check "Version erhöhen"   # jede Version ist neu
$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Write-Host "WorkPlanner $version" -ForegroundColor Cyan

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $cmd = Get-Command iscc -ErrorAction SilentlyContinue; if ($cmd) { $iscc = $cmd.Source } }
if (-not $iscc) { throw "Inno Setup 6 nicht gefunden. Installieren mit:  winget install JRSoftware.InnoSetup" }

Write-Host "1/3 Symbol ..." -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"      # nur für das Symbol; Bildschirmfotos im Handbuch brauchen die echte Oberfläche
python tools\make_icon.py; Check "Symbol erzeugen"
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue

Write-Host "Handbuch (PDF mit Bildschirmfotos) ..." -ForegroundColor Cyan
python tools\make_manual.py; Check "Handbuch erzeugen"

Write-Host "2/3 Programm (PyInstaller) ..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --onedir --windowed --name WorkPlanner `
    --icon assets\workplanner.ico --paths src `
    --exclude-module numpy --exclude-module pandas `
    --hidden-import win32timezone src\main.py; Check "PyInstaller"   # numpy braucht WorkPlanner nicht; ein mitgepacktes, defektes numpy bricht openpyxl

Write-Host "3/3 Installer (Inno Setup) ..." -ForegroundColor Cyan
& $iscc "/DAppVersion=$version" installer\WorkPlanner.iss; Check "Inno Setup"

$setup = Get-ChildItem "dist\installer\WorkPlanner-Setup-$version.exe"
Write-Host ("Fertig: {0} ({1:N1} MB)" -f $setup.FullName, ($setup.Length / 1MB)) -ForegroundColor Green
