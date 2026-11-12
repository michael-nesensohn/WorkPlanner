# Änderungen

Neueste Version zuerst. `dev-release.ps1` übernimmt den Abschnitt der neuen Version als Release-Text auf GitHub
(`## <Version>`); er erscheint auch im Programm unter „Über WorkPlanner“, wenn ein Update bereitsteht.

## 0.1.17
- In Excel-Stundenzettel eintragen: Steht an einer Stelle schon ein anderer Wert, wird nachgefragt, wer Vorrang hat
  (WorkPlanner ersetzt, oder Excel behält seinen Wert); die Wahl lässt sich im Dialog auch fest einstellen.
- WorkPlanner merkt sich, was in die Excel-Datei eingetragen wurde, und überspringt unveränderte Tage beim nächsten Mal
  (geänderte Werte kommen wieder; „Merker zurücksetzen“ und ein Schalter heben das auf).
- In Excel-Stundenzettel eintragen: neben der Liste gibt es den Reiter „So sieht es in Excel aus“. Er zeigt das Blatt wie
  in Excel (Farben, Breiten) und legt die geplanten Werte darüber: grün = neu, orange = ersetzt einen vorhandenen Wert
  (der alte steht dahinter), hellgrün = neue Projektzeile. Vorhandene, nicht betroffene Werte bleiben sichtbar.
- PDF-Bericht: Querformat und schmalere Ränder (weniger Seiten). In den Einstellungen („PDF-Bericht“) lassen sich
  Schriftgröße für Überschrift (Standard 12 pt) und Text (Standard 8 pt) sowie das Querformat einstellen.

## 0.1.16
- Berichte: neuer Knopf „Als PDF exportieren …“. Zusammengefasst steht je Tag jedes Projekt einmal mit der Gesamtdauer,
  darunter je Tätigkeit die verbundenen Notizen; alternativ „einzeln“ mit allen Einträgen. Es erscheinen nur die
  angehakten Spalten, vorn steht eine Summe je Projekt (A–Z).
- Einstellungen: „PDF-Bericht: Kopfdaten“ (Titel, Name, Firma/Abteilung, Zusatzzeile) stehen oben auf dem PDF.
- Excel-Vorlage zuordnen: neuer Knopf „Alles prüfen“ testet alle Monatsblätter der Datei mit deinen Projekten (Vorlage
  erkannt? Tage mit Spalte? Platz für jedes Projekt?).
- Handbuch und Bildschirmfotos auf den aktuellen Stand gebracht (Pause, Berichte, Excel-Assistent).

## 0.1.15
- Eintrag bearbeiten: Start und Ende gleichzeitig früher setzen löst nicht mehr die Meldung „Zeiten dürfen nicht in der
  Zukunft liegen“ aus, wenn das Ergebnis gültig ist.
- Wird ein Eintrag (z. B. eine Pause) per Start und Ende mitten in eine längere Aufgabe gelegt, wird diese Aufgabe
  aufgetrennt und läuft danach weiter; die übrigen Einträge verschieben sich nicht.

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
