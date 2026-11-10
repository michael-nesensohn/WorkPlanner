# Lokaler Tester für den Entwicklungszustand (Gegenstück zu dev-build.ps1).
# Er legt selbst eine EIGENE virtuelle Umgebung (.venv) an, installiert die Abhängigkeiten sauber hinein und testet
# nur damit – unabhängig von dem, was auf diesem Rechner sonst an Python-Paketen liegt. So zeigt sich auch, ob
# requirements.txt vollständig ist.
#
#   .\dev-test.ps1                  STARTET DIE GUI aus dem Quelltext (in der venv) mit EIGENER Datenbank (testdaten\appdata)
#   .\dev-test.ps1 -Zuruecksetzen   dito, aber vorher die Testdaten löschen (leere Datenbank wie bei einer Neuinstallation)
#   .\dev-test.ps1 -Tests           statt der GUI: alle automatischen Python-Tests (ohne Excel/Installer)
#   .\dev-test.ps1 -Excel           statt der GUI: Roundtrip mit ECHTEM Excel an einer Kopie von testdaten\nem_2026_TEST.xlsx
#   .\dev-test.ps1 -Installer       statt der GUI: Installer-Lebenszyklus mit Testvariante (Neu / Update / Deinstallation)
#   .\dev-test.ps1 -Alles           alle drei automatischen Prüfungen zusammen
#   .\dev-test.ps1 -Alles -Start    Prüfungen, danach (wenn alles bestanden hat) die GUI
#   .\dev-test.ps1 -VenvNeu         die virtuelle Umgebung vorher komplett neu aufbauen (wie auf einem frischen Rechner)
#
# Nichts davon berührt deine echte Installation, deren Autostart oder die echte Datenbank in %APPDATA%\WorkPlanner:
#  * Python-Tests und Excel-Test arbeiten mit temporären Dateien bzw. einer Kopie.
#  * Der Installer-Test nutzt eine Testvariante (andere ID und anderer Name, kein Beenden fremder Prozesse, eigener
#    Datenordner) und räumt hinterher alles ab.
#  * Die GUI läuft isoliert (eigene Daten, keine Tastenkombination, kein Tray, keine "nur eine Instanz"-Sperre),
#    also auch dann, wenn die installierte WorkPlanner-Version gerade läuft.
param([switch]$Tests, [switch]$Excel, [switch]$Installer, [switch]$Alles, [switch]$Start, [switch]$Zuruecksetzen, [switch]$VenvNeu)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
if ($Alles) { $Tests = $true; $Excel = $true; $Installer = $true }
$runChecks = $Tests -or $Excel -or $Installer
$startGui = $Start -or (-not $runChecks)        # ohne Prüfungs-Schalter: GUI starten

# ------------------------------------------------------------------ eigene virtuelle Umgebung
$venv = Join-Path $PSScriptRoot ".venv"
$py = Join-Path $venv "Scripts\python.exe"

function Ensure-Venv {
    if ($VenvNeu -and (Test-Path $venv)) {
        Write-Host "Virtuelle Umgebung wird neu aufgebaut ..." -ForegroundColor Cyan
        [IO.Directory]::Delete($venv, $true)
    }
    if (-not (Test-Path $py)) {
        Write-Host "Lege virtuelle Umgebung an: $venv" -ForegroundColor Cyan
        python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "python -m venv ist fehlgeschlagen (ist Python installiert und im PATH?)" }
    }
    # Pakete nur (neu) installieren, wenn sich die Listen geändert haben
    $stamp = Join-Path $venv ".abhaengigkeiten"
    $hash = ((Get-FileHash requirements.txt, requirements-dev.txt -Algorithm SHA256 | ForEach-Object Hash) -join "")
    if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
        Write-Host "Installiere Abhängigkeiten in die virtuelle Umgebung (beim ersten Mal einige Minuten) ..." -ForegroundColor Cyan
        & $py -m pip install --disable-pip-version-check --prefer-binary -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw "pip install ist fehlgeschlagen" }
        $hash | Set-Content $stamp
    }
    $info = & $py -c "import sys, win32com, importlib.metadata as m; print('Python', sys.version.split()[0], '| PySide6', m.version('PySide6'), '| openpyxl', m.version('openpyxl'), '| pywin32', m.version('pywin32'))" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Die virtuelle Umgebung ist unvollständig: $info" }
    Write-Host "Umgebung (.venv, ohne System-Pakete): $info" -ForegroundColor DarkGray
}

Ensure-Venv

# ------------------------------------------------------------------ App isoliert starten
function Start-Gui {
    $data = Join-Path $PSScriptRoot "testdaten\appdata"
    if ($Zuruecksetzen -and (Test-Path $data)) { [IO.Directory]::Delete($data, $true) }
    $env:WORKPLANNER_DATA = $data
    $env:WORKPLANNER_ISOLATED = "1"
    Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue   # echtes Fenster, nicht der Test-Modus ohne Bildschirm
    Write-Host "`nStarte WorkPlanner aus dem Quelltext (venv) mit eigener Datenbank:" -ForegroundColor Cyan
    Write-Host "  $data\workplanner.db  ($(if (Test-Path "$data\workplanner.db") { 'vorhandene Testdaten' } else { 'neu und leer' }))"
    Write-Host "  Das Fenster öffnet sich gleich. Schließen beendet den Testlauf; deine echten Daten bleiben unberührt."
    Write-Host "  (Frische leere Datenbank: .\dev-test.ps1 -Zuruecksetzen)" -ForegroundColor DarkGray
    & $py src\main.py
    if ($LASTEXITCODE -ne 0) { Write-Host "WorkPlanner wurde mit Fehler beendet (Exit $LASTEXITCODE)." -ForegroundColor Red }
    return $LASTEXITCODE
}

if (-not $runChecks) {            # Standard: nur die GUI starten, keine Prüfungsübersicht
    exit (Start-Gui)
}

# ------------------------------------------------------------------ Ergebnisse sammeln
$script:rows = @()
$script:checks = @()
function Add-Result($name, $ok, $detail = "") { $script:rows += [pscustomobject]@{ Test = $name; OK = $ok; Detail = $detail } }
function Check($ok, $text) {  # Einzelprüfung im Installer-Test
    $script:checks += [pscustomobject]@{ OK = [bool]$ok; Text = $text }
    Write-Host ("   {0} {1}" -f $(if ($ok) { "OK   " } else { "FEHLT" }), $text) -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
}

# ------------------------------------------------------------------ 1) Python-Tests
$env:QT_QPA_PLATFORM = "offscreen"          # Qt ohne Bildschirm: die Tests öffnen keine sichtbaren Fenster
if ($Tests) {
    Write-Host "`n== 1) Python-Tests (in der venv) ==" -ForegroundColor Cyan
    $out = & $py -m pytest -q 2>&1
    $code = $LASTEXITCODE
    $out | Select-Object -Last 12 | ForEach-Object { Write-Host "   $_" }
    Add-Result "Python-Tests (pytest, venv)" ($code -eq 0) "$($out | Select-String -Pattern '\d+ (passed|failed|error)' | Select-Object -Last 1)".Trim()
}

# ------------------------------------------------------------------ 2) Echtes Excel
if ($Excel) {
    Write-Host "`n== 2) Excel-Roundtrip mit echtem Excel (an einer Kopie) ==" -ForegroundColor Cyan
    $muster = Join-Path $PSScriptRoot "testdaten\nem_2026_TEST.xlsx"
    $excelExe = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe" -ErrorAction SilentlyContinue
    if (-not (Test-Path $muster)) {
        Add-Result "Excel-Roundtrip" $false "Testdatei fehlt: $muster (testdaten\Testdatei-zuruecksetzen.ps1 ausführen)"
    } elseif (-not $excelExe) {
        Add-Result "Excel-Roundtrip" $false "Excel ist nicht installiert"
    } else {
        $env:WORKPLANNER_EXCEL_SAMPLE = $muster          # der Test kopiert sie vorher, die Testdatei bleibt unverändert
        $out = & $py -m pytest -q tests\test_excel_ui.py -k real_excel 2>&1
        $code = $LASTEXITCODE
        $out | Select-Object -Last 6 | ForEach-Object { Write-Host "   $_" }
        Remove-Item Env:\WORKPLANNER_EXCEL_SAMPLE
        Add-Result "Excel-Roundtrip (echtes Excel)" ($code -eq 0) "$($out | Select-String -Pattern '\d+ (passed|failed|error)' | Select-Object -Last 1)".Trim()
    }
}

# ------------------------------------------------------------------ 3) Installer-Lebenszyklus
if ($Installer) {
    Write-Host "`n== 3) Installer: Neuinstallation / Update / Deinstallation (Testvariante) ==" -ForegroundColor Cyan
    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
              "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        Add-Result "Installer-Test" $false "Inno Setup 6 fehlt (winget install JRSoftware.InnoSetup)"
    } elseif (-not (Test-Path "dist\WorkPlanner\WorkPlanner.exe")) {
        Add-Result "Installer-Test" $false "Programm nicht gebaut – zuerst .\dev-build.ps1 ausführen"
    } else {
        $script:checks = @()
        $version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
        $testName = "WorkPlannerTest"
        $guid = "0F0F0F0F-1111-4222-8333-444455556666"
        $outDir = Join-Path $PSScriptRoot "dist\installer-test"
        $base = Join-Path $env:TEMP ("wp_installtest_" + (Get-Date -Format "HHmmss"))
        $app = "$base\app"; $data = "$base\data"; $db = "$data\workplanner.db"
        $menu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\$testName"
        $unKey = { Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" | Where-Object { $_.PSChildName -like "{$guid*" } }
        $backups = { @(Get-ChildItem $data -Filter "workplanner.db.vorher-*" -ErrorAction SilentlyContinue).Count }
        try {
            & $iscc "/DAppName=$testName" "/DAppGuid=$guid" "/DTestBuild=1" "/DOutDir=$outDir" "/DAppVersion=$version" "/Q" installer\WorkPlanner.iss
            if ($LASTEXITCODE -ne 0) { throw "Kompilieren des Test-Installers fehlgeschlagen" }
            $setup = Join-Path $outDir "$testName-Setup-$version.exe"
            $run = { param($exe, $argList) (Start-Process $exe -ArgumentList $argList -PassThru -Wait).ExitCode }
            $common = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"$app`"", "/DATADIR=`"$data`"")
            New-Item -ItemType Directory -Path $data -Force | Out-Null

            Write-Host " a) Neuinstallation (es liegt noch eine alte Datenbank da)"
            [IO.File]::WriteAllText($db, "ALTE-DATEN")
            Check ((& $run $setup $common) -eq 0) "Installer lief durch (Exit 0)"
            Check (Test-Path "$app\WorkPlanner.exe") "Programm installiert"
            Check ((-not (Test-Path $db)) -and ((& $backups) -eq 1)) "alte Datenbank beiseite gelegt, WorkPlanner startet leer"
            Check ("ALTE-DATEN" -eq [IO.File]::ReadAllText((Get-ChildItem $data -Filter "workplanner.db.vorher-*" | Select-Object -First 1).FullName)) "Inhalt der alten Datenbank ist in der Sicherung erhalten"
            Check ((Test-Path "$menu\$testName.lnk") -and (Test-Path "$menu\$testName deinstallieren.lnk")) "Startmenü: Programm und 'deinstallieren'"
            Check (Test-Path "$app\installiert.json") "installiert.json geschrieben"
            Check ([bool](& $unKey)) "Eintrag in 'Apps & Features'"

            Write-Host " b) Update (die Datenbank enthält jetzt Arbeitsdaten)"
            [IO.File]::WriteAllText($db, "ARBEITSDATEN")
            Check ((& $run $setup $common) -eq 0) "Installer lief durch (Exit 0)"
            Check ("ARBEITSDATEN" -eq [IO.File]::ReadAllText($db)) "Datenbank bleibt unverändert"
            Check ((& $backups) -eq 1) "keine zusätzliche Sicherung angelegt"
            Check (@(& $unKey).Count -eq 1) "weiterhin genau ein Eintrag in 'Apps & Features'"

            Write-Host " c) Deinstallation über den Startmenü-Eintrag"
            $target = (New-Object -ComObject WScript.Shell).CreateShortcut("$menu\$testName deinstallieren.lnk").TargetPath
            Start-Process $target -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DATADIR=`"$data`"" -Wait
            $t = 0; while ((Test-Path "$app\WorkPlanner.exe") -and $t -lt 40) { Start-Sleep 1; $t++ }
            Start-Sleep 3
            Check (-not (Test-Path "$app\WorkPlanner.exe")) "Programmdateien entfernt"
            Check (-not (Test-Path $menu)) "Startmenü-Ordner entfernt"
            Check (-not [bool](& $unKey)) "Eintrag in 'Apps & Features' entfernt"
            Check ("ARBEITSDATEN" -eq [IO.File]::ReadAllText($db)) "Daten bleiben bei der Deinstallation erhalten"

            Write-Host " d) Neuinstallation nach der Deinstallation (Daten liegen noch da)"
            Start-Sleep 2
            Check ((& $run $setup $common) -eq 0) "Installer lief durch (Exit 0)"
            Check ((-not (Test-Path $db)) -and ((& $backups) -eq 2)) "Daten beiseite gelegt, WorkPlanner startet wieder leer"
        } catch {
            Check $false ("Abbruch: " + $_.Exception.Message)
        } finally {
            if (Test-Path "$app\unins000.exe") {   # aufräumen: Testinstallation entfernen
                Start-Process "$app\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DATADIR=`"$data`"" -Wait
                $t = 0; while ((Test-Path "$app\WorkPlanner.exe") -and $t -lt 40) { Start-Sleep 1; $t++ }
                Start-Sleep 3
            }
            foreach ($d in @($base, $outDir)) { if (Test-Path $d) { try { [IO.Directory]::Delete($d, $true) } catch { } } }
        }
        $bad = @($script:checks | Where-Object { -not $_.OK })
        Add-Result "Installer (Neu/Update/Deinstallation)" ($bad.Count -eq 0) "$($script:checks.Count - $bad.Count) von $($script:checks.Count) Prüfungen bestanden"
    }
}

# ------------------------------------------------------------------ Zusammenfassung
Write-Host "`n================ ERGEBNIS ================" -ForegroundColor Cyan
foreach ($r in $script:rows) {
    Write-Host ("  {0,-6} {1,-42} {2}" -f $(if ($r.OK) { "OK" } else { "FEHLER" }), $r.Test, $r.Detail) -ForegroundColor $(if ($r.OK) { "Green" } else { "Red" })
}
if (-not $Alles) {
    Write-Host "  (Weitere Prüfungen: -Excel, -Installer oder -Alles. GUI zum Ausprobieren: .\dev-test.ps1 ohne Schalter)" -ForegroundColor DarkGray
}
if (@($script:rows | Where-Object { -not $_.OK }).Count -gt 0) { exit 1 }
if ($startGui) { exit (Start-Gui) }      # nur mit -Start: nach bestandenen Prüfungen die GUI öffnen
