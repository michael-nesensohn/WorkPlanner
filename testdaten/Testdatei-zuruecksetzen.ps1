# Setzt die Test-Excel-Datei auf den Ausgangszustand zurück (Kopie des Musters aus dem Download-Ordner).
# Das Original in Downloads wird nur gelesen, nie verändert.
$quelle = Join-Path $env:USERPROFILE "Downloads\nem_2026.xlsx"
$ziel   = Join-Path $PSScriptRoot "nem_2026_TEST.xlsx"
if (-not (Test-Path $quelle)) { throw "Muster nicht gefunden: $quelle" }
$offen = Get-Process EXCEL -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "*nem_2026_TEST*" }
if ($offen) { throw "Die Testdatei ist in Excel geöffnet. Bitte zuerst schließen (ohne Speichern)." }
Copy-Item $quelle $ziel -Force
Write-Host "Testdatei zurückgesetzt: $ziel" -ForegroundColor Green
