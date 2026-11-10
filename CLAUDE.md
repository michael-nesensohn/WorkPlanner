# WorkPlanner – Hinweise für Claude Code

Zeiterfassung für Windows (Python, PySide6, SQLite). Einstieg und Funktionsübersicht: `README.md`.
Sprache der Oberfläche, Kommentare, Tests und Commits: **Deutsch**.

## Harte Regeln
- **Keine Arbeitgeber-, Kunden- oder Produktnamen und keine vordefinierte DevOps-Adresse** in Quelltext, Tests, Bildern,
  Texten, Commit-Meldungen und im Git-Verlauf. Beispieldaten neutral halten („Kunde A“, „Demo-Plattform“,
  `dev.azure.com/example-org/...`). Die konkrete Liste der verbotenen Namen steht bewusst **nicht** in dieser Datei
  (das Repo ist öffentlich), sondern in `CLAUDE.local.md` (wird nicht eingecheckt, liegt nur beim Entwickler).
  Vor jedem Veröffentlichen Dateien **und Verlauf** auf diese Namen prüfen (`git grep -i`, `git log --all -S<Name>`).
- **Commits nur unter dem Namen des Entwicklers**, ohne `Co-Authored-By`- oder „Generated with“-Zeile.
- **Nur der Entwickler pusht und veröffentlicht.** Issues von anderen sind erwünscht (Fehler, Wünsche), Pull Requests
  werden nicht angenommen. In Issues und Antworten nie Firmen-/Kundendaten übernehmen oder zitieren.
  Veröffentlicht wird ausschließlich mit `dev-release.ps1`. Nie `git push --force`, nie Tags oder Releases löschen,
  nie Repo-Einstellungen ändern, ohne dass der Entwickler es ausdrücklich verlangt.
- **Neue Oberfläche modern**: abgerundete Felder und Knöpfe, Akzentblau `#2F5597`, keine Standard-Optik von Qt. Textfarben
  in Stilvorlagen immer ausdrücklich setzen (sonst weißer Text auf weißem Grund bei dunklem Windows-Design).

## Befehle (PowerShell, im Projektordner)
- `.\dev-test.ps1 -Tests` – alle automatischen Tests in eigener venv (`QT_QPA_PLATFORM=offscreen`)
- `python -m pytest -q` – Tests direkt (venv `.venv` mit `requirements-dev.txt`)
- `.\dev-test.ps1` – GUI aus dem Quelltext mit eigener Testdatenbank (`testdaten\appdata`, fasst echte Daten nicht an)
- `.\dev-build.ps1` – Installer und Handbuch bauen; `.\dev-release.ps1` – Tests, bauen, Version erhöhen, Tag, GitHub-Release

## Aufbau (`src/workplanner`)
- `timeline.py`, `db.py`, `service.py`, `export.py` – Logik, SQLite, Anwendungsdienst, Excel-Export (siehe README)
- `excel_timesheet.py` – Eintrag in einen vorhandenen Excel-Stundenzettel über Excel selbst (COM), damit Diagramme und
  Formeln erhalten bleiben. **Profil** (`ExcelProfile`) beschreibt den Aufbau der Vorlage (Blattnamen, Projektnummer/-name,
  Grenzen der Projektzeilen per Text oder fester Zeile, Tage Mo–Sa/Mo–So automatisch); Export/Import als
  `.wpprofile.json`. Prüfbar ohne Excel über die Attrappen `FakeSheet`/`FakeBook` in `tests/test_excel_timesheet.py`.
- `config.py` – versteckte Einstellungen aus `workplanner.ini` im Datenordner (z. B. `[export] show_start_end = 1`
  blendet die Export-Spalten Start/Ende ein). Absichtlich nicht in der Oberfläche.
- `ui/` – PySide6. `excel_profile_dialog.py` ist der Assistent „Excel-Vorlage zuordnen“.

## Technische Regeln
- **Hintergrundarbeit nur über `ui/background.py` (`BackgroundRunner`).** Ein Thread darf nie `self`, ein Fenster oder ein
  anderes Qt-Objekt kennen: Qt-Objekte dürfen nur im GUI-Thread zerstört werden, sonst gibt es zufällige Abstürze
  (Heap-Korruption), auch im Testlauf. Ergebnisse kommen über die Warteschlange des Helfers im GUI-Thread an.
  Noch nicht umgestellt (gleiche Gefahr beim Schließen mitten im Laden): `devops_page.py`, `feature_panel.py`,
  `outlook_panel.py`.
- Excel nie mit einer Bibliothek schreiben (würde Bilder, Diagramme, Verknüpfungen verlieren), nur über COM.
- Datenordner: `%APPDATA%\WorkPlanner`, umlenkbar mit der Umgebungsvariable `WORKPLANNER_DATA`.
- Tests mit Oberfläche: `tests/conftest.py` räumt Fenster am Ende auf. Nach Änderungen die **ganze** Suite mehrfach laufen
  lassen: ein Absturz („Fatal Python error“) tritt manchmal erst in der vollen Suite auf, nicht in einzelnen Dateien.
