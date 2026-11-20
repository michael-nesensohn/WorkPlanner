# Änderungen

Neueste Version zuerst. `dev-release.ps1` übernimmt den Abschnitt der neuen Version als Release-Text auf GitHub
(`## <Version>`); er erscheint auch im Programm unter „Über WorkPlanner“, wenn ein Update bereitsteht.

## 0.1.28
- **Notiz-Spalte und Tagesplan breiter ziehen**: Zieht man den rechten Rand der Notiz-Spalte (Liste) oder den schmalen
  Griff am rechten Rand des Tagesplans, wird die linke Seite breiter und die rechten Spalten rücken mit: zuerst Outlook,
  dann DevOps (beide dürfen ganz zugehen), zuletzt die Schnellauswahl (bleibt lesbar). Das Fenster muss dafür nicht
  größer werden. Schmaler ziehen gibt den Platz zurück (auch an eine zugegangene Outlook-Spalte). Der Trenner ist
  zusätzlich besser sichtbar. Die Notiz-Spalte füllt weiter immer den Rest der Tabelle.

## 0.1.27
- **Löschen verschiebt nichts mehr**: Wird ein Eintrag (oder mehrere) gelöscht, bleiben alle anderen Einträge genau,
  wo sie sind. Es entsteht eine Lücke statt dass die Folgeeinträge nachrutschen.
- **Lücken sichtbar**: Fehlt zwischen zwei Einträgen Zeit, steht dort in „Heute“ eine hellblaue Zeile „Lücke – nichts
  erfasst“ (ab 1 Minute). Doppelklick auf die Lücke öffnet „Eintrag hinzufügen“ mit genau dieser Zeit.
- Verlängert man das Ende eines Eintrags in eine Lücke hinein, wird die Lücke kleiner bzw. verschwindet; Folgeeinträge
  rücken nur so weit, wie es nötig ist. Ein neu eingefügter Eintrag nimmt zuerst die Lücke ein. Wird ein Eintrag kürzer,
  rücken die Folgeeinträge wie bisher mit (eine vorhandene Lücke bleibt gleich groß).
- Neuer Knopf **Hintereinander …**: Markierte Einträge werden in der Reihenfolge ihres Starts lückenlos
  hintereinander gelegt. Die Dauern bleiben, Start und Ende ändern sich (mit Vorschau); andere Einträge bleiben.
- **Tagesplan** (Umschalter **Liste | Tagesplan** in „Heute“, die Wahl bleibt gespeichert): Die Einträge des Tages als
  farbige Blöcke auf einer Zeitachse, Lücken gestrichelt hellblau, Pausen grau, die laufende Aufgabe grün mit
  „Jetzt“-Linie. Mit der Maus: Block ziehen verschiebt ihn, die obere oder untere Kante ändert Start bzw. Ende, alles
  rastet auf 15 Minuten ein und bleibt innerhalb der Nachbarn (andere Einträge werden nie verschoben). Klick markiert
  (Strg = mehrere, die Knöpfe darunter wirken wie in der Liste), Doppelklick auf einen Block bearbeitet ihn, Doppelklick
  auf eine Lücke legt dort einen Eintrag an.
- Tagesplan: Die Notiz steht im Block, so viele Zeilen wie hineinpassen (umgebrochen); ist sie länger, endet sie mit „…“.
  Fährt man mit der Maus über einen Block, zeigt ein Hinweis alle Angaben samt ganzer Notiz.
- **Dunkles Design**: Einstellungen → Stammdaten → Einstellungen → **Darstellung**: Hell, Dunkel oder Wie Windows. Die
  Umstellung gilt sofort in allen Fenstern (Heute, Tagesplan, Berichte, Dialoge); „Wie Windows“ wird beim Start
  übernommen. Standard bleibt Hell.
- Handbuch: neue Abschnitte zu Lücken, Hintereinander legen und Tagesplan (mit Bildern), zur Änderung von Projektnummer/-name ab einem Datum, zum dunklen Design und zur Sicherung des Excel-Stundenzettels.
- Liste in „Heute“: Die **Notiz-Spalte** lässt sich per Maus breiter oder schmaler ziehen (die Breite wird gemerkt);
  Doppelklick auf den Spaltenrand stellt wieder „füllt den Rest“ ein.
- Liste in „Heute“: Die Spalten Start, Ende, Dauer und Verr. sind schmaler, der Platz geht an Projekt und Notiz.

## 0.1.26
- Projektnummer oder Projektname ändern (Einstellungen → Stammdaten → Projekt bearbeiten): Es wird gefragt, **ab wann**
  die Änderung gilt – ab heute (Standard), ab einem Datum oder für alle Tage. Bereits erfasste Tage davor behalten ihre
  bisherige Nummer und ihren Namen (Heute, Berichte, Excel- und PDF-Export). Wer die Änderung rückwirkend braucht,
  wählt „Ab Datum …“ oder „Für alle Tage“.
- Eintrag bearbeiten: Die Projektauswahl zeigt jetzt „Nummer  Name“, und neben ihr steht ein Stift-Symbol-Knopf (Projekt bearbeiten), mit dem sich
  Projektnummer und Name des gewählten Projekts ändern lassen – auch bei Projekten, die nicht in der Schnellauswahl stehen
  (mit der Frage, ab wann die Änderung gilt).
- Stammdaten → Projekte: Projektnummer und Name stehen jetzt in Spalten untereinander. Neue Sortierung der Liste nach
  Projektnummer A–Z oder Name A–Z (nur die Anzeige; die Reihenfolge der Schnellauswahl bleibt die eigene).

## 0.1.25
- Excel-Stundenzettel (Einstellungen → Stammdaten): neue Option **Vor dem Eintragen eine Sicherung der Datei anlegen**
  mit wählbarem Ordner (Standard `C:\temp\Stundenzettel`). Die Sicherung heißt wie die Excel-Datei und wird bei jedem
  Eintragen **überschrieben**. Ist die Sicherung nicht möglich, wird nichts eingetragen.

## 0.1.24
- Excel-Stundenzettel: Trägt WorkPlanner bei einem neuen Projekt die Projektnummer ein und Excel zeigt dazu von selbst
  keinen Projektnamen an (die Nachschlageformel der Vorlage kennt die Nummer nicht), wird der Projektname von
  WorkPlanner in die Namenszelle geschrieben. Zeigt Excel einen Namen, bleibt er unverändert.
- Excel-Stundenzettel: Die Projektnummer wird immer als **Text** eingetragen (Zellformat „Text“); Excel machte aus
  „4711“ sonst eine Zahl, und Nachschlageformeln fanden das Projekt nicht.

## 0.1.23
- Outlook-Panel: Über der Terminliste wählt man das Projekt (**Buchen auf**), vorgegeben ist „Meeting“; ein Klick auf
  einen Termin bucht darauf.
- Berichte, Vorschau Export: **Doppelklick** ändert Projekt, Tätigkeit und Notiz des Eintrags (die Zeiten sind
  gesperrt); **Rechtsklick → Springe zu diesem Tag** öffnet den Tag unter „Heute“.
- Schnellauswahl: **Rechtsklick** auf ein Projekt → **Umhängen auf …** (laufende Zeit wechselt) oder **Neu starten**.
- Kalender „Datum wählen“: Monat und Jahr sind jetzt auch im aktiven Fenster zu sehen (waren weiß auf weiß).
- Tests: Fenster werden nach jedem Test geschlossen (behebt einen sporadischen Absturz der Testläufe).

## 0.1.22
- Update: Meldet GitHub „Fehler 403“ (Abfragegrenze der Schnittstelle: 60 Abfragen je Stunde und Internetadresse, in
  Firmennetzen mit gemeinsamer Adresse schnell erreicht), fragt WorkPlanner jetzt die normalen Release-Seiten von
  github.com ab. Dort gilt das Limit nicht; die Prüfsumme des Installers wird weiterhin geprüft. Die
  Änderungsliste fehlt in diesem Fall in der Anzeige. Ohne Ausweg kommt eine verständliche Meldung statt „Fehler 403“.

## 0.1.21
- Läuft eine Aufgabe über Mitternacht, wird sie um 00:00 beendet und am neuen Tag ab 00:00 mit denselben Angaben
  fortgesetzt (war es mehr als eine Nacht, endet sie nur). Ganz oben rechts erscheint ein **roter Hinweis**, bis du
  den Tag bestätigst („Passt“) oder dir ansiehst und die Zeiten korrigierst. Auch Einträge der letzten Tage, die genau
  um 00:00 enden, werden so gemeldet.
- Handbuch: neuer Teil „Einträge zusammensetzen“, „aufteilen und wieder zusammenfügen“, „Zurück“ und „Aufgabe über
  Mitternacht“ mit gezeichneten Zeitleisten-Bildern.
- Neuer Knopf **Zusammensetzen …** (unter der Tabelle): nebeneinander liegende Einträge markieren, im Dialog das
  Projekt (und die Tätigkeit) wählen; die Notizen werden zusammengefasst (ohne Wiederholungen, bearbeitbar). Start
  vom ersten, Ende vom letzten Eintrag. Liegt eine Pause oder Mittagspause dazwischen, bleibt sie, wo sie ist; die
  Aufgabe teilt sich um sie herum auf. Eine Vorschau zeigt das Ergebnis.

## 0.1.20
- Eintrag bearbeiten: Die Vorschau im Dialog meldete weiter „Zeiten dürfen nicht in der Zukunft liegen“, wenn der
  frühere Start eine Pause überdeckt, und sperrte „Save“. Jetzt zeigt sie die Aufteilung um die Pause; bei überdeckten
  Aufgaben den ersten Weg, der geht (die Rückfrage beim Speichern lässt wählen).

## 0.1.19
- Eintrag bearbeiten: Überdeckt ein früherer Start andere Einträge (z. B. eine Mittagspause), gibt es in der Rückfrage
  neu **Aufteilen (Pause bleibt)**: die Pause bleibt, wo sie ist, der Eintrag teilt sich um sie herum auf (Aufgabe –
  Pause – Aufgabe) und nichts rückt nach hinten.
  Überdeckt der Start nur Pausen, wird ohne Rückfrage so aufgeteilt (eine Pause schneidet eine Aufgabe immer).

## 0.1.18
- Mittagspause: neue Einstellung „Kein Pausenabzug“ (Mittagspause ganz abgeschaltet). „Nur abziehen“ gibt es nicht
  mehr; wer es eingestellt hatte, bekommt jetzt „Nachfragen“ (bis zur Antwort wird die Pause abgezogen).
- Im Modus „Nachfragen“ gibt es **Pause nachtragen**: trägt die Mittagspause nachträglich ein (falls die Nachfrage
  verpasst wurde); die Aufgabe, die dort lief, wird aufgetrennt und läuft danach weiter.
- Der Knopf „Heute nicht abziehen / Wieder abziehen“ heißt jetzt „Keine Mittagspause“ / „Mittagspause“. Der Status
  daneben ist zweizeilig und wird nicht mehr abgeschnitten.
- „Pause starten?“: „Pause einfügen …“ trennt die Aufgabe, trägt die Pause ein (Beginn und Länge änderbar) und lässt
  die Aufgabe weiterlaufen. Dasselbe gilt für „Pause nachtragen“.
- Der Knopf „Mittagspause“ (wenn der Abzug für den Tag aus war) trägt die Pause auch als Eintrag ein (Beginn und Länge
  wählbar). Die Mittagspause heißt in Listen und Anzeige „Mittagspause“. Eine Pause, die erst später endet, läuft weiter
  und setzt die Aufgabe selbst fort.
- „Pause nachtragen“ ist für eine normale Pause (Eintrag „Pause“, Vorschlag 15 min bis jetzt, Beginn und Länge
  wählbar); die Mittagspause (Dialog zur Mittagszeit, Knopf „Mittagspause“) heißt „Mittagspause“.
- „Keine Mittagspause“ entfernt nur Einträge „Mittagspause“; normale Pausen bleiben. Löscht man eine normale Pause,
  bleibt der Mittagsabzug unberührt und die Aufgabe läuft durch.
- Neuer Knopf **↶ Zurück** (bei Verklicken): die laufende Aufgabe wird verworfen, die vorherige läuft weiter und
  bekommt die Zeit dazwischen. Erscheint nur, wenn davor eine Aufgabe lief.
- Die Anzeige „Arbeitszeit …“ springt nicht mehr, wenn der Zusatz „(Pause … abgezogen)“ erscheint oder verschwindet.

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
