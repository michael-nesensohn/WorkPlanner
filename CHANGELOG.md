# Änderungen

Neueste Version zuerst. `dev-release.ps1` übernimmt den Abschnitt der neuen Version als Release-Text auf GitHub
(`## <Version>`); er erscheint auch im Programm unter „Über WorkPlanner“, wenn ein Update bereitsteht.

## 0.1.12
- Eintrag bearbeiten: neuer Knopf „⇤ Ende des Vorgängers“ setzt den Start lückenlos auf das Ende des vorherigen Eintrags.
- Eintrag bearbeiten: Start-, Ende- und Dauer-Felder sind schmaler.
- Wird der Start früher gesetzt, entfällt nie mehr ein Eintrag. Reicht der neue Start in andere Einträge hinein, fragt das
  Programm: „Dauer beibehalten“ oder „Kürzen“. Eine laufende Aufgabe stoppt dabei vor dem vorhandenen Eintrag und
  läuft danach weiter.

## 0.1.11
- Früherer Start der laufenden Aufgabe löscht keine eingetragenen Einträge mehr: die Aufgabe stoppt davor und läuft danach weiter.

## 0.1.10
- Excel-Stundenzettel: eigene Vorlage per Profil beschreiben („Excel-Vorlage zuordnen“ mit Assistent und Vorschau wie in
  Excel), Profile exportieren/importieren, bereits vorhandene Projektnummern werden gefunden, Tage Mo–Sa oder Mo–So
  automatisch.
- Export: die Spalten „Start“ und „Ende“ sind standardmäßig ausgeblendet (einblendbar über `workplanner.ini`).
- Stabilität: Hintergrundarbeit in den Dialogen (Über/Updates, Notizen als Task, Outlook-Import, Excel) läuft jetzt ohne
  Absturzrisiko beim Schließen mitten im Laden.
