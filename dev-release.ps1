# Veröffentlicht eine neue Version auf GitHub: Tests, Installer bauen, Version einchecken, Tag setzen, Release anlegen.
#
#   .\dev-release.ps1                 baut den Installer und legt ein GitHub-Release mit Installer und Handbuch an
#   .\dev-release.ps1 -Entwurf        legt das Release nur als Entwurf an (erst nach „Veröffentlichen“ auf GitHub sichtbar)
#   .\dev-release.ps1 -OhneTests      überspringt die Python-Tests
#   .\dev-release.ps1 -Notizen "..."  eigener Text statt der automatisch erzeugten Änderungsliste
#
# Ablauf: 1) Arbeitsordner muss sauber sein (alles committet), 2) Tests, 3) dev-build.ps1 (erhöht die Version, baut den
# Installer und das Handbuch), 4) die neue Version wird committet und mit dem Tag v<Version> gepusht, 5) das Release
# bekommt den Installer und das Handbuch als Dateien. Voraussetzung: GitHub CLI (gh), angemeldet mit „gh auth login“.
param([switch]$Entwurf, [switch]$OhneTests, [string]$Notizen = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what ist fehlgeschlagen (Exit-Code $LASTEXITCODE)." } }

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI (gh) fehlt: winget install GitHub.cli" }
gh auth status *> $null; Check "gh auth status (bitte gh auth login ausführen)"
if (git status --porcelain) { throw "Es gibt nicht committete Änderungen. Bitte zuerst committen (und pushen), dann erneut starten." }
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") { throw "Releases werden von main aus gemacht (aktuell: $branch)." }

Write-Host "Abhängigkeiten prüfen (requirements-dev.txt) ..." -ForegroundColor Cyan
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt; Check "pip install"

if (-not $OhneTests) {
    Write-Host "1/4 Tests ..." -ForegroundColor Cyan
    $env:QT_QPA_PLATFORM = "offscreen"
    python -m pytest -q; Check "Tests"
    Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
}

Write-Host "2/4 Installer und Handbuch bauen (erhöht die Version) ..." -ForegroundColor Cyan
& "$PSScriptRoot\dev-build.ps1"
if ($LASTEXITCODE -ne 0) { throw "dev-build.ps1 ist fehlgeschlagen." }
$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
$tag = "v$version"
$setup = "dist\installer\WorkPlanner-Setup-$version.exe"
$manual = "docs\WorkPlanner-Handbuch.pdf"
if (-not (Test-Path $setup)) { throw "Installer nicht gefunden: $setup" }
if (git tag --list $tag) { throw "Den Tag $tag gibt es schon." }

Write-Host "3/4 Version $version einchecken, taggen und pushen ..." -ForegroundColor Cyan
git add pyproject.toml src/workplanner/_version.py; Check "git add"
git commit -m "Release $tag" | Out-Null; Check "git commit"
git tag $tag; Check "git tag"
git push origin $branch; Check "git push"
git push origin $tag; Check "git push (Tag)"

Write-Host "4/4 GitHub-Release anlegen ..." -ForegroundColor Cyan
$ghArgs = @("release", "create", $tag, $setup, "--title", "WorkPlanner $version")
if (Test-Path $manual) { $ghArgs += $manual }
if ($Notizen) { $ghArgs += @("--notes", $Notizen) } else { $ghArgs += "--generate-notes" }
if ($Entwurf) { $ghArgs += "--draft" }
gh @ghArgs; Check "gh release create"
Write-Host "Fertig: Release $tag" -ForegroundColor Green
