# Änderungen

Neueste Version zuerst. `dev-release.ps1` übernimmt den Abschnitt der neuen Version als Release-Text auf GitHub
(`## <Version>`); er erscheint auch im Programm unter „Über WorkPlanner“, wenn ein Update bereitsteht.

## 0.1.14
- Eintrag bearbeiten/hinzufügen: die Projektliste ist alphabetisch sortiert und hat kein „–“ mehr; ohne Angabe gilt
  „Allgemein“.
- Excel-Vorlage zuordnen: die Summenzeile ist optional. Ist „Hier dürfen keine neuen Projekte mehr …“ angegeben, braucht
  die Vorlage keine Summenzeile (sie wird ohnehin nie beschrieben).

## 0.1.13
- Neuer Knopf „⏸ Pause“ bei der laufenden Aufgabe: die Aufgabe wird angehalten, die Pause erscheint als Eintrag unter
  „Heute“. In der Pause heißt der Knopf neben der Uhr „▶ Weiter: <Aufgabe>“ (statt „Neu“); er beendet die Pause und
  setzt dieselbe Aufgabe fort.
- Unter der Notiz (neben „verrechenbar“) steht, ob die Mittagspause automatisch abgezogen wird (aktiv / aus / als
  Pause eingetragen), mit dem Schalter „Heute nicht abziehen“. Eine eingetragene Pause ersetzt den automatischen
  Abzug, nichts wird doppelt abgezogen.
- Neue Einstellung „Mittagspause“: „Nur abziehen“ (wie bisher) oder „Nachfragen“. Bei „Nachfragen“ erscheint zur
  Mittagszeit „Pause starten?“ (Pause starten, in 10 Minuten erinnern, nur abziehen, heute keine Pause); die Pause endet
  nach der eingestellten Dauer von selbst und die Aufgabe läuft weiter.
- Die Tagesanzeige heißt „Arbeitszeit (ohne Pausen)“.
- Woche: Pausen sind standardmäßig ausgeblendet (Kästchen „Pausen anzeigen“), die Übersicht hat eine Spalte „Pausen“
  mit Summe; die Pfeile stehen direkt neben dem Datum.
- Berichte: Kästchen „Pausen-Einträge anzeigen und exportieren“ (Standard aus); die Export-Spalte „Mittagspause“ entfällt.
- Excel-Stundenzettel: Einstellung „Pausen mit in den Stundenzettel eintragen“ (Standard aus; an: als Zeile „Pause“).
- Der Dialog bei überdeckten Einträgen ist verständlicher (listet die betroffenen Einträge; „Behalten“ oder „Kürzen“).
- Doppelklick auf „Schnellauswahl“ öffnet die Stammdaten. Knöpfe und Notizfeld springen bei Pause/Weiter nicht mehr.

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
