"""Erzeugt das Handbuch (PDF) mit Bildschirmfotos der echten Oberfläche.

    python tools/make_manual.py [Ausgabedatei]        (Standard: docs/WorkPlanner-Handbuch.pdf)

Die Bildschirmfotos entstehen mit tools/manual_screens.py (Beispieldaten, nie echte). Braucht reportlab und pillow.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, ListFlowable, ListItem, NextPageTemplate,
                                CondPageBreak, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus import Image as RLImage
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from workplanner._version import __version__  # noqa: E402

ACCENT = colors.HexColor("#2F5597")
SOFT = colors.HexColor("#E8EEF7")
GREY = colors.HexColor("#667085")
FONTS = Path(r"C:\Windows\Fonts")
pdfmetrics.registerFont(TTFont("Seg", str(FONTS / "segoeui.ttf")))
pdfmetrics.registerFont(TTFont("Seg-B", str(FONTS / "segoeuib.ttf")))
pdfmetrics.registerFont(TTFont("Seg-I", str(FONTS / "segoeuii.ttf")))
pdfmetrics.registerFont(TTFont("Seg-BI", str(FONTS / "segoeuiz.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONTS / "consola.ttf")))
pdfmetrics.registerFontFamily("Seg", normal="Seg", bold="Seg-B", italic="Seg-I", boldItalic="Seg-BI")

BODY = ParagraphStyle("body", fontName="Seg", fontSize=10, leading=14.5, spaceAfter=6)
H1X = ParagraphStyle("h1x", fontName="Seg-B", fontSize=19, leading=24, textColor=ACCENT, spaceAfter=10)
H1 = ParagraphStyle("h1", parent=BODY, fontName="Seg-B", fontSize=19, leading=24, textColor=ACCENT, spaceBefore=4,
                    spaceAfter=10, keepWithNext=1)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Seg-B", fontSize=12.5, leading=16, textColor=ACCENT, spaceBefore=10,
                    spaceAfter=4, keepWithNext=1)
CAP = ParagraphStyle("cap", parent=BODY, fontSize=8.5, leading=11, textColor=GREY, alignment=TA_CENTER, spaceAfter=10)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=12.5, spaceAfter=0)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.3, leading=12.5, spaceAfter=0)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Seg-B")
TITLE = ParagraphStyle("title", parent=BODY, fontName="Seg-B", fontSize=34, leading=40, textColor=ACCENT, spaceAfter=8)
SUB = ParagraphStyle("sub", parent=BODY, fontSize=14, leading=19, textColor=GREY, spaceAfter=4)
TOC1 = ParagraphStyle("toc1", parent=BODY, fontSize=10.5, leading=17, leftIndent=0, spaceAfter=0)

FRAME_W = A4[0] - 4 * cm


class Manual(BaseDocTemplate):
    def __init__(self, path: str):
        super().__init__(path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm,
                         bottomMargin=2 * cm, title="WorkPlanner – Handbuch", author="Michael Nesensohn",
                         subject="Handbuch zu WorkPlanner")
        body = Frame(self.leftMargin, self.bottomMargin, FRAME_W, A4[1] - self.topMargin - self.bottomMargin,
                     id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("cover", [body], onPage=lambda c, d: None),
                               PageTemplate("page", [body], onPage=self._decorate)])

    def _decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#C9D3E0"))
        canvas.line(2 * cm, 1.55 * cm, A4[0] - 2 * cm, 1.55 * cm)
        canvas.setFont("Seg", 8.5)
        canvas.setFillColor(GREY)
        canvas.drawString(2 * cm, 1.05 * cm, f"WorkPlanner – Handbuch · Version {__version__}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.05 * cm, f"Seite {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            text = flowable.getPlainText()
            key = f"h1-{self.page}-{abs(hash(text))}"
            top = self.frame._y + flowable.height + flowable.style.spaceAfter + 6   # Oberkante der Überschrift
            self.canv.bookmarkHorizontal(key, 0, top)
            self.canv.addOutlineEntry(text, key, 0, 0)
            self.notify("TOCEntry", (0, text, self.page, key))


def P(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str], style=BODY) -> ListFlowable:
    return ListFlowable([ListItem(Paragraph(t, style), leftIndent=14) for t in items], bulletType="bullet",
                        start="•", leftIndent=14, bulletFontName="Seg", bulletFontSize=10)


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(Paragraph(t, BODY), leftIndent=18) for t in items], bulletType="1",
                        bulletFormat="%s.", leftIndent=18, bulletFontName="Seg-B")


def box(text: str, title: str = "Tipp", fill=SOFT) -> Table:
    t = Table([[Paragraph(f"<b>{title}</b><br/>{text}", SMALL)]], colWidths=[FRAME_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill), ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([t, Spacer(1, 8)])


def table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    data = [[Paragraph(c, CELLB if (header and r == 0) else CELL) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3E0")),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
    t.setStyle(TableStyle(style))
    return t


class Screens:
    def __init__(self, folder: Path):
        self.folder = folder

    def parts(self, name: str, caption: str, width: float = FRAME_W, crop_h: int | None = None,
              max_h: float = 12.5 * cm) -> list:
        path = self.folder / f"{name}.png"
        with Image.open(path) as im:
            if crop_h and crop_h < im.height:
                cropped = self.folder / f"{name}_c.png"
                im.crop((0, 0, im.width, crop_h)).save(cropped)
                path = cropped
        with Image.open(path) as im:
            w, h = im.size
        scale = min(width / w, max_h / h)
        img = RLImage(str(path), width=w * scale, height=h * scale)
        frame = Table([[img]], colWidths=[w * scale + 2])
        frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#B8C1CE")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return [frame, Spacer(1, 3), P(caption, CAP)]

    def pic(self, name: str, caption: str, **kw) -> KeepTogether:
        return KeepTogether(self.parts(name, caption, **kw))

    def side(self, name: str, caption: str, right: list, width: float = 5.0 * cm, max_h: float = 9 * cm) -> Table:
        """Bild links, Text oder Tabelle rechts."""
        t = Table([[self.parts(name, caption, width=width, max_h=max_h), right]],
                  colWidths=[width + 14, FRAME_W - width - 14])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0),
                               ("RIGHTPADDING", (0, 0), (0, 0), 12), ("LEFTPADDING", (1, 0), (1, 0), 0),
                               ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        return t


def story(s: Screens) -> list:
    st: list = []
    add = st.append

    # --- Deckblatt ----------------------------------------------------------------------------
    add(Spacer(1, 6 * cm))
    add(P("WorkPlanner", TITLE))
    add(P("Handbuch", ParagraphStyle("t2", parent=TITLE, fontSize=24, leading=30, textColor=colors.HexColor("#1f2937"))))
    add(Spacer(1, 6))
    add(P("Zeiterfassung mit Schnellauswahl, Outlook-Terminen, Teams-Anrufen, DevOps und Excel-Stundenzettel", SUB))
    add(Spacer(1, 7.5 * cm))
    add(P(f"Version {__version__} · Stand {date.today():%d.%m.%Y}", SUB))
    add(P("Copyright (c) 2026 Michael Nesensohn · MIT-Lizenz · keine Gewährleistung, keine Haftung", SMALL))
    add(NextPageTemplate("page"))
    add(PageBreak())

    toc = TableOfContents()
    toc.levelStyles = [TOC1]
    toc.dotsMinLevel = 0
    add(P("Inhalt", H1X))
    add(toc)
    add(PageBreak())

    # --- 1 Einführung -----------------------------------------------------------------------------
    add(P("1&nbsp;&nbsp;Was ist WorkPlanner?", H1))
    add(P("WorkPlanner ist ein Programm für Windows, mit dem Sie Ihre Arbeitszeit erfassen: auf Knopfdruck, ohne "
          "Formulare, mit einer lückenlosen Zeitleiste pro Tag. Es merkt sich Projekte, Tätigkeiten und Notizen, rechnet "
          "Mittagspause und Soll-Arbeitszeit mit und kann die Stunden an andere Stellen weitergeben: in einen "
          "Excel-Stundenzettel, in Azure DevOps (Completed Work) oder als Excel-Bericht."))
    add(bullets([
        "<b>Schnell:</b> ein Klick auf ein Projekt startet die Zeit, ein Klick auf einen Outlook-Termin bucht ihn.",
        "<b>Lückenlos:</b> es läuft immer nur eine Aufgabe; Sie können nichts in die Zukunft buchen und keine Überschneidungen anlegen.",
        "<b>Ihre Daten bleiben bei Ihnen:</b> alles liegt in einer Datei auf Ihrem Rechner (Abschnitt 14).",
        "<b>Optional:</b> Outlook, Teams, DevOps und Excel sind Zusatzfunktionen. Ohne sie funktioniert WorkPlanner trotzdem.",
    ]))
    add(P("Voraussetzungen", H2))
    add(table([
        ["Funktion", "Was dafür gebraucht wird"],
        ["Zeiterfassung, Woche, Berichte, Excel-Export", "Windows 10 oder 11, sonst nichts"],
        ["Outlook-Termine", "klassisches Outlook (Desktop). Das „neue Outlook“ bietet keine Schnittstelle."],
        ["Teams-Anrufe", "Microsoft Teams als Programm (nicht im Browser)"],
        ["Excel-Stundenzettel", "installiertes Microsoft Excel und Ihre Stundenzettel-Datei mit einem Blatt je Monat"],
        ["DevOps", "Azure DevOps und ein persönliches Zugriffstoken (PAT)"],
    ], [5.2 * cm, FRAME_W - 5.2 * cm]))
    add(Spacer(1, 6))

    # --- 2 Installation ---------------------------------------------------------------------------------
    add(P("2&nbsp;&nbsp;Installation und erster Start", H1))
    add(steps([
        "Starten Sie <font name='Mono'>WorkPlanner-Setup-&lt;Version&gt;.exe</font>. Administratorrechte sind nicht nötig.",
        "Bestätigen Sie die Lizenz (MIT) und wählen Sie den Zielordner. Voreingestellt ist "
        "<font name='Mono'>C:\\Projects\\SW-Tools\\WorkPlanner</font>.",
        "Wählen Sie die Verknüpfungen: Startmenü (mit „WorkPlanner deinstallieren“), optional Desktop und optional "
        "„Mit Windows starten“ (dann startet WorkPlanner nur als Symbol im Infobereich).",
        "Starten Sie WorkPlanner. Beim ersten Start ist alles leer.",
    ]))
    add(box("<b>Neuinstallation:</b> eine Datenbank einer früheren Installation wird nicht gelöscht, sondern als "
            "<font name='Mono'>workplanner.db.vorher-&lt;Datum&gt;</font> beiseite gelegt; WorkPlanner startet leer. "
            "<b>Update:</b> einfach den neuen Installer ausführen. Ihre Daten bleiben unverändert, ein laufendes "
            "WorkPlanner wird dafür beendet. <b>Deinstallation:</b> über „Apps &amp; Features“ oder das Startmenü; die Daten "
            "bleiben stehen, außer Sie bestätigen das Löschen.", "Neu, Update, Deinstallation"))
    add(box("Beim allerersten Start fragt WorkPlanner, ob Sie mit <b>Beispieldaten</b> beginnen möchten: einige Projekte, "
            "Tätigkeiten und ein Beispieltag. So sehen Sie in Ruhe, wie alles funktioniert. Die Beispieldaten sind markiert "
            "und lassen sich jederzeit mit <b>Hilfe → Beispieldaten entfernen</b> löschen, ohne eigene Daten anzufassen. "
            "Wer „Leer starten“ wählt, kann sie später mit <b>Hilfe → Beispieldaten einfügen</b> nachholen.",
            "Beispieldaten zum Ausprobieren"))
    add(P("Ersteinrichtung in drei Schritten", H2))
    add(steps([
        "Menü <b>Einstellungen → Stammdaten</b>: Projekte anlegen (Name, optional Projektnummer, Farbe, „verrechenbar“) "
        "und mit dem Stern zu Favoriten machen. Favoriten erscheinen in der Schnellauswahl.",
        "Dort auch <b>Tätigkeiten</b> anlegen (für alle Projekte oder nur für eines).",
        "Menü <b>Einstellungen → Einstellungen</b>: Standardprojekt, Mittagspause und Soll-Arbeitszeit prüfen. "
        "Danach können Sie loslegen.",
    ]))
    add(s.pic("stammdaten", "Stammdaten: Projekte und Tätigkeiten", width=12 * cm, crop_h=330))

    # --- 3 Überblick --------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("3&nbsp;&nbsp;Die Oberfläche im Überblick", H1))
    add(s.pic("uebersicht", "Die Seite „Heute“ mit Beispieldaten", max_h=11.5 * cm))
    add(table([
        ["Nr.", "Bereich", "Wofür"],
        ["1", "Menüleiste", "Datei → Beenden; Einstellungen → Einstellungen und Stammdaten; Hilfe → Handbuch, Lizenz, Über WorkPlanner / Updates"],
        ["2", "Uhrzeit", "aktuelle Tageszeit, auf jedem Reiter sichtbar. Reiter: Heute, Woche, Berichte (und DevOps, wenn aktiv)"],
        ["3", "Start-Karte", "laufende Aufgabe mit Notiz, Laufzeit, Start/Neu/Stopp und den Tätigkeiten"],
        ["4", "Einträge des Tages", "alle Buchungen des gewählten Tages als Tabelle, mit Knöpfen darunter"],
        ["5", "Outlook", "Termine des angezeigten Tages; ein Klick bucht den Termin"],
        ["6", "DevOps", "Features und Stories als Kacheln; ein Klick startet die Zeit mit Verknüpfung"],
        ["7", "Schnellauswahl", "Ihre Favoriten-Projekte; Klick oder Strg+Zahl startet die Zeit"],
        ["8", "Knöpfe", "Bearbeiten, Eintrag hinzufügen, Löschen, Outlook-Import, Notiz → DevOps-Task"],
    ], [1.1 * cm, 3.6 * cm, FRAME_W - 4.7 * cm]))
    add(Spacer(1, 6))
    add(box("Die Breite von Outlook-, DevOps- und Schnellauswahl-Spalte lässt sich an den dünnen Trennern mit der Maus "
            "ziehen. WorkPlanner merkt sich diese Breiten, die Fenstergröße und die Fensterposition."))

    # --- 4 Zeit erfassen -----------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("4&nbsp;&nbsp;Zeit erfassen", H1))
    add(s.pic("startkarte", "Die Start-Karte mit laufender Aufgabe", max_h=6.5 * cm))
    add(P("Starten und wechseln", H2))
    add(bullets([
        "<b>Start</b> startet die Zeit auf dem Standardprojekt. Die Zuordnung zu einem Projekt kann später erfolgen.",
        "<b>Projekt anklicken</b> (Schnellauswahl) startet die Zeit auf diesem Projekt. Läuft gerade eine Zeit ohne "
        "Zuordnung, bekommt <i>diese</i> das Projekt, es entsteht kein neuer Eintrag.",
        "<b>Strg + 1 … 9</b> wählt die Favoriten der Reihe nach, genau wie ein Klick. Die Zahl steht rechts an der Kachel.",
        "<b>Neu</b> beendet die laufende Aufgabe und startet sofort eine neue (Standardprojekt).",
        "<b>⏸ Pause</b> stoppt die Aufgabe und legt einen sichtbaren Pausen-Eintrag an. Während der Pause heißt der "
        "Knopf <b>Weiter: &lt;Aufgabe&gt;</b>: Er beendet die Pause, und die Aufgabe davor läuft weiter.",
        "<b>Stopp</b> beendet die laufende Aufgabe.",
        "<b>Tätigkeit</b> wählen Sie über die Knöpfe in der Start-Karte (blau = gewählt).",
    ]))
    add(P("Notiz und „verrechenbar“", H2))
    add(P("Das Notizfeld gehört zur laufenden Aufgabe, darf mehrere Zeilen haben und wird beim Verlassen des Feldes "
          "gespeichert. Das Kästchen „verrechenbar“ wird vom Projekt vorbelegt und lässt sich pro Eintrag ändern."))
    add(P("Startzeit oder bisherige Zeit ändern", H2))
    add(P("Haben Sie vergessen zu starten? Mit <b>Zeit ändern</b> (oder Doppelklick auf die große Uhr) setzen Sie die "
          "Startzeit oder die bisher angefallene Zeit. Der davorliegende Eintrag passt sich an; die Vorschau zeigt wie."))
    add(s.pic("zeit_aendern", "Laufende Zeit anpassen", width=9 * cm))
    add(box("Es läuft immer nur <b>eine</b> Aufgabe. Zeiten können nicht in der Zukunft liegen, und ein Eintrag darf "
            "den Tag nicht verlassen. Es geht <b>nie ein Eintrag verloren</b>: Reicht ein früherer Start in andere "
            "Einträge hinein, fragt WorkPlanner, ob diese ihre Dauer <b>behalten</b> (sie rücken nach hinten) oder "
            "<b>gekürzt</b> werden. Die Mittagspause wird von der Arbeitszeit abgezogen (Abschnitt 5).", "Regeln der Zeitleiste"))

    # --- 5 Einträge -------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("5&nbsp;&nbsp;Einträge ansehen und bearbeiten", H1))
    add(s.pic("tabelle", "Einträge des Tages: Kästchen vor jeder Zeile, „Alle markieren“ im Tabellenkopf", max_h=9 * cm))
    add(P("Tabelle", H2))
    add(bullets([
        "Spalten: Start, Ende, Dauer, Verrechenbar, Projekt, Tätigkeit, DevOps und Notiz. Lange Notizen und Tätigkeiten "
        "brechen automatisch um.",
        "<b>Kästchen</b> vor jeder Zeile markieren den Eintrag; das Kästchen ganz oben im Kopf markiert alle oder keinen. "
        "Eine Zeile anzuklicken markiert sie ebenfalls.",
        "Oben rechts stehen die Tagessumme, das Soll und das voraussichtliche <b>Soll-Ende</b>, daneben der Fortschrittsbalken.",
        "Mit den Pfeil-Knöpfen, <b>Kalender</b> und <b>Heute</b> wechseln Sie den Tag.",
    ]))
    add(P("Bearbeiten, hinzufügen, löschen", H2))
    add(bullets([
        "<b>Bearbeiten</b> (oder Doppelklick auf die Zeile): bei genau einem markierten Eintrag.",
        "<b>Eintrag hinzufügen</b>: für vergessene Zeiten. Start, Ende und Dauer hängen zusammen; mit „Dauer ab hier“ "
        "bzw. „Dauer bis hier“ legen Sie fest, welcher Zeitpunkt bei einer neuen Dauer stehen bleibt. "
        "<b>Start = Ende des Vorgängers</b> setzt den Start auf das Ende des Eintrags davor. Die Projektliste ist "
        "alphabetisch; ohne Auswahl gilt „Allgemein“.",
        "Liegt ein Eintrag in der Mitte einer längeren Aufgabe, wird diese <b>aufgetrennt</b> und läuft danach weiter.",
        "<b>Löschen</b> (oder Entf): alle markierten Einträge; die späteren rücken nach vorn.",
    ]))
    add(s.pic("eintrag_dialog", "Eintrag hinzufügen – die Vorschau zeigt, was sich verschiebt", width=9.5 * cm))
    add(P("Wie sich andere Einträge anpassen", H2))
    add(bullets([
        "Ein eingefügter Eintrag schiebt die <b>späteren</b> um seine Dauer nach hinten. Nichts darf dabei in die Zukunft "
        "wandern: Eine laufende Aufgabe beginnt dann spätestens <i>jetzt</i>, was darüber hinausginge, wird gekürzt.",
        "Hat die laufende Aufgabe <i>vor</i> dem neuen Eintrag begonnen, wird sie dort beendet und läuft danach mit "
        "derselben Aufgabe weiter.",
        "Beginnt Ihr Eintrag in derselben Minute, in der der vorige endet, schließt er bündig an (die Vorschau zeigt es).",
        "Die Vorschau im Dialog zeigt jede Änderung vor dem Speichern. Das Speichern ist nur möglich, wenn alles "
        "zusammenpasst; sonst steht der Grund in Rot.",
    ]))
    add(P("Pausen und Mittagspause", H2))
    add(P("Die Mittagspause (voreingestellt 12:00, 30 Minuten) wird nicht gebucht, sondern aus der Dauer der Einträge "
          "herausgerechnet, die in dieses Zeitfenster fallen. Ein Hinweis im Tooltip der Dauer zeigt den Abzug. Unter der "
          "Notiz steht, ob der Abzug aktiv ist; für einen einzelnen Tag lässt er sich mit <b>Heute nicht abziehen</b> "
          "abschalten (und mit <b>Wieder abziehen</b> zurückholen)."))
    add(bullets([
        "Mit <b>⏸ Pause</b> legen Sie eine echte Pause als Eintrag an. Sie ersetzt dann den Abzug der Mittagspause; die "
        "Summen heißen „Arbeitszeit (ohne Pausen)“.",
        "In den Einstellungen wählen Sie, ob zur Mittagszeit <b>automatisch abgezogen</b> wird oder WorkPlanner "
        "<b>nachfragt</b> („Pause starten?“: jetzt, später, abziehen oder nicht).",
    ]))

    # --- 6 Outlook --------------------------------------------------------------------------------------------
    add(CondPageBreak(14 * cm))
    add(P("6&nbsp;&nbsp;Outlook-Termine übernehmen", H1))
    add(P("Das Outlook-Panel zeigt die Termine des Tages, den Sie gerade ansehen. WorkPlanner liest Outlook nur "
          "<b>lesend</b> und im Hintergrund; es verändert nichts in Ihrem Kalender."))
    add(s.side("outlook_panel", "Outlook-Panel", [table([
        ["Anzeige", "Bedeutung"],
        ["Kachel ohne Zusatz", "Termin ist vorbei: ein Klick legt den Eintrag an"],
        ["„läuft“", "Termin läuft gerade: ein Klick unterbricht die laufende Aufgabe, die danach automatisch weiterläuft"],
        ["„eingetragen“ (mit Haken)", "bereits übernommen; wird kein zweites Mal gebucht"],
        ["„noch nicht begonnen“", "liegt in der Zukunft; nicht anklickbar"],
    ], [3.6 * cm, FRAME_W - 5.0 * cm - 14 - 3.6 * cm])], width=5.0 * cm, max_h=7.6 * cm))
    add(Spacer(1, 6))
    add(bullets([
        "Der Eintrag bekommt den Betreff als Notiz, Projekt und Tätigkeit aus der Voreinstellung: ein Projekt „Meeting“, "
        "„Besprechung“ oder „Termine“ (falls vorhanden, sonst das Standardprojekt) und die Tätigkeit „Besprechung“ oder "
        "„Meeting“.",
        "Würde ein Termin bestehende Einträge vollständig überdecken, fragt WorkPlanner vorher nach.",
        "Ganztägige und abgesagte Termine werden ausgeblendet. Der Kreispfeil-Knopf liest die Termine neu; sonst "
        "geschieht das beim Tageswechsel und alle 10 Minuten.",
    ]))
    add(P("Mehrere Termine auf einmal", H2))
    add(P("Der Knopf <b>Outlook-Termine importieren …</b> öffnet eine Liste für einen Zeitraum. Dort wählen Sie Termine "
          "per Kästchen aus, wählen Projekt und Tätigkeit und sehen vor dem Import, welche Einträge gekürzt werden."))
    add(s.pic("outlook_import", "Import-Dialog für mehrere Termine", width=13.5 * cm, max_h=9 * cm))

    # --- 7 Teams --------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("7&nbsp;&nbsp;Teams-Anrufe", H1))
    add(P("WorkPlanner erkennt Anrufe und Besprechungen in Teams daran, dass Teams das Mikrofon öffnet. Dazu wird "
          "nur die von Windows geführte Information „Mikrofon in Benutzung“ gelesen; es wird nichts aufgezeichnet und "
          "nichts übertragen."))
    add(steps([
        "Sobald der Anruf beginnt, erscheint unten rechts ein rotes Banner „Teams-Anruf läuft seit …“.",
        "Wenn der Anruf endet, öffnet sich ein Fenster: Sie können Zeit, Projekt, Tätigkeit und Notiz anpassen und "
        "wählen <b>Eintragen</b> oder <b>Nicht eintragen</b>.",
    ]))
    add(s.pic("call_banner", "Hinweis während des Anrufs", width=8.5 * cm))
    add(s.pic("call_dialog", "Nachfrage nach dem Anruf", width=9.5 * cm))
    add(bullets([
        "Die Tätigkeit ist immer „Telefonat“ (wird beim ersten Mal angelegt). Das Projekt vom letzten Anruf wird "
        "vorgeschlagen.",
        "Ein Anruf wird mindestens als <b>eine Minute</b> gebucht. Kürzere Mikrofon-Zugriffe als 5 Sekunden werden ignoriert.",
        "Eine laufende Aufgabe wird für die Anrufzeit unterbrochen und läuft danach weiter.",
        "Es werden nur Anrufe in der Teams-<i>Anwendung</i> erkannt, nicht in einem Browser.",
        "Abschalten: Einstellungen → Einstellungen → „Nach einem Teams-Anruf fragen …“.",
    ]))

    # --- 8 DevOps ----------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("8&nbsp;&nbsp;Azure DevOps (optional)", H1))
    add(P("Mit DevOps verknüpft WorkPlanner Ihre Zeiten mit Features und Stories und kann die Stunden in das Feld "
          "„Completed Work“ übertragen. Alles lässt sich in den Einstellungen abschalten (siehe unten)."))
    add(P("Einrichten", H2))
    add(steps([
        "Öffnen Sie den Reiter <b>DevOps</b>.",
        "<b>Adresse:</b> Öffnen Sie in Ihrem Browser den Backlog Ihres Teams und kopieren Sie die Adresse aus der "
        "Adresszeile in das Feld. WorkPlanner liest daraus Organisation, Projekt und Team. Es gibt <b>keine "
        "vordefinierte Adresse</b>.",
        "<b>Token (PAT):</b> Erzeugen Sie in DevOps ein persönliches Zugriffstoken und fügen Sie es ein. Zum Anzeigen "
        "reicht „Work Items: Read“, zum Übertragen von Stunden und zum Anlegen von Stories oder Tasks braucht es "
        "Schreibrechte („Read &amp; write“).",
        "<b>Speichern</b>, dann <b>Verbindung testen</b>.",
    ]))
    add(s.pic("devops_seite", "Reiter DevOps vor der Einrichtung", crop_h=330, max_h=7 * cm))
    add(box("Das Token wird mit der Windows-Benutzerverschlüsselung abgelegt: Nur Ihr Windows-Konto kann es wieder "
            "lesen, die Datenbankdatei allein verrät es nicht. Behandeln Sie das Token trotzdem wie ein Passwort. "
            "Nach einer Neuinstallation (leere Datenbank) müssen Adresse und Token neu eingetragen werden.", "Sicherheit"))
    add(P("Arbeiten mit Features und Stories", H2))
    add(s.side("devops_panel", "DevOps-Panel auf „Heute“", [bullets([
        "Das <b>DevOps-Panel</b> zeigt Ihre Features (fett) mit ihren Stories, zuerst die dieser Woche. Es lädt sich "
        "automatisch (alle 15 Minuten) und ist auch offline aus dem Zwischenspeicher da.",
        "<b>Klick auf eine Kachel</b> startet die Zeit und verknüpft sie: in der Start-Karte erscheint die Zeile "
        "„DevOps: #4413“ (mit <b>lösen</b>, um die Verknüpfung zu entfernen). Die Notiz bleibt frei für die Beschreibung.",
        "Hat ein Feature noch kein Projekt, legt WorkPlanner eines an (Nummer = ID des Features).",
        "Auf der DevOps-Seite: <b>Laden</b>, <b>Projekt aus Feature anlegen</b>, <b>Aufgabe starten</b>, <b>Story in "
        "DevOps anlegen</b> und <b>Im Browser öffnen</b>.",
        "<b>Stunden nach DevOps übertragen</b> zeigt zuerst eine Vorschau. Es wird nur die <b>Differenz</b> zum letzten "
        "Mal in „Completed Work“ geschrieben; Stunden anderer Personen bleiben erhalten.",
        "<b>Notiz → DevOps-Task</b> (Knopf unter der Tabelle): legt aus der Notiz markierter Einträge einen Task in DevOps an.",
    ], SMALL)], width=5.0 * cm, max_h=8.5 * cm))
    add(P("DevOps abschalten", H2))
    add(P("Unter <b>Einstellungen → Einstellungen → DevOps-Funktionen verwenden</b> lässt sich alles zu DevOps "
          "ausblenden: der Reiter, das Panel auf „Heute“, die DevOps-Spalten, die Verknüpfungszeile, das Feld im "
          "Eintrag-Dialog und die Export-Spalte. Ihre Daten bleiben erhalten; beim Wiedereinschalten ist alles zurück."))

    # --- 9 Woche ------------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("9&nbsp;&nbsp;Woche", H1))
    add(P("Der Reiter <b>Woche</b> zeigt Montag bis Sonntag. Mit den Pfeil-Knöpfen neben dem Datum blättern Sie durch "
          "die Wochen. Das Kästchen <b>Pausen anzeigen</b> (standardmäßig aus) blendet die Pausen-Einträge und die "
          "Spalte „Pausen“ mit den Summen ein."))
    add(P("Übersicht", H2))
    add(P("Pro Tag: gearbeitet, davon verrechenbar, Soll und Differenz (+ oder –); darunter die Stunden je Projekt."))
    add(s.pic("woche_uebersicht", "Wochenübersicht", crop_h=330, max_h=8 * cm))
    add(P("Einträge", H2))
    add(P("Jeder Tag mit allen seinen Buchungen und vollständigen Notizen. Die Tageszeile zeigt gearbeitet, verrechenbar, "
          "Soll und Differenz; die letzte Zeile die Wochenstunden-Differenz. Ein <b>Doppelklick</b> öffnet den Tag auf "
          "„Heute“, dort lässt er sich bearbeiten."))
    add(s.pic("woche_eintraege", "Wocheneinträge mit Tages- und Wochensumme", crop_h=360, max_h=8 * cm))
    add(box("Die Wochen-Differenz rechnet gegen das Soll der <b>ganzen</b> Woche (Montag bis Freitag). In einer "
            "laufenden Woche steht sie deshalb zunächst im Minus."))

    # --- 10 Berichte -------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("10&nbsp;&nbsp;Berichte und Export", H1))
    add(s.pic("berichte", "Berichte: Zeitraum, Spalten und Vorschau", max_h=10 * cm))
    add(steps([
        "Wählen Sie <b>Von</b>, <b>Bis</b> und optional ein <b>Projekt</b>. Die Zeile darunter zeigt die Summe.",
        "Haken Sie bei <b>Spalten im Export</b> an, was exportiert werden soll. Standard sind Datum, Dauer, "
        "Verrechenbar, Projektnr., Projekt, Tätigkeit, Notiz und DevOps. Ihre Auswahl wird gespeichert und gilt für "
        "Excel <b>und</b> PDF.",
        "<b>Pausen-Einträge anzeigen und exportieren</b> (standardmäßig aus) nimmt die Pausen in Vorschau und Export auf.",
        "Die <b>Vorschau</b> darunter zeigt genau diese Spalten.",
        "<b>Nach Excel exportieren …</b> speichert eine .xlsx-Datei.",
        "<b>Als PDF exportieren …</b> speichert einen Bericht (siehe unten).",
    ]))
    add(P("PDF-Bericht", H2))
    add(P("Neben dem Knopf wählen Sie die Art. Es erscheinen nur die oben angehakten Spalten; vorn steht eine "
          "<b>Summe je Projekt</b> (A–Z), dann folgt jeder Tag. Titel, Name, Firma/Abteilung und eine Zusatzzeile oben auf "
          "dem Bericht legen Sie unter <b>Einstellungen → Einstellungen → PDF-Bericht: Kopfdaten</b> fest."))
    add(table([
        ["Art", "Inhalt"],
        ["zusammengefasst", "je Tag steht jedes Projekt <b>einmal</b> mit der Gesamtdauer; darunter je Tätigkeit die "
                            "verbundenen Notizen und ihre Dauer"],
        ["einzeln", "je Tag alle Einträge als Zeilen mit den gewählten Spalten (Uhrzeit nur, wenn Start oder Ende "
                    "angehakt ist)"],
    ], [3.4 * cm, FRAME_W - 3.4 * cm]))
    add(P("Die Excel-Datei enthält drei Blätter", H2))
    add(table([
        ["Blatt", "Inhalt"],
        ["Einträge", "eine Zeile je Eintrag mit den gewählten Spalten, mit Filter und fixierter Kopfzeile"],
        ["Tagessummen", "Datum, Wochentag, Arbeitszeit, davon verrechenbar, Pausen, Soll und Differenz, mit Summenzeile"],
        ["Projektsummen", "je Projekt und Tätigkeit die Dauer, davon verrechenbar und die Stunden als Dezimalzahl"],
    ], [3.4 * cm, FRAME_W - 3.4 * cm]))
    add(P("In den Excel-Stundenzettel eintragen", H2))
    add(P("Mit <b>In Excel-Stundenzettel eintragen …</b> übernimmt WorkPlanner die Stunden je Projekt und Tag in Ihre "
          "vorhandene Stundenzettel-Datei (ein Blatt je Monat; die Stunden stehen ohne Mittagspause in der Tagesspalte). "
          "Ob Pausen-Einträge mitgehen, stellen Sie in den Stammdaten ein („Pausen mit in den Stundenzettel eintragen“)."))
    add(P("Eigene Vorlage zuordnen", H2))
    add(P("Unter <b>Einstellungen → Excel-Vorlage zuordnen …</b> beschreiben Sie den Aufbau Ihrer Datei: Laden Sie eine "
          "Beispieldatei, klicken Sie bei jedem Feld auf ◎ und dann in der Tabelle die passende Beschriftung. "
          "<b>Testen</b> färbt die erkannte Struktur ein. Die <b>Summenzeile</b> ist optional: Wenn Sie schon angeben, "
          "bis wohin die Projekte gehen, brauchen Sie sie nicht. <b>Alles prüfen</b> (unten links) testet alle "
          "Monatsblätter der Datei mit Ihren Projekten: Wird die Vorlage erkannt, und ist für jedes Projekt Platz? "
          "Das Profil lässt sich als .wpprofile.json exportieren und importieren."))
    add(steps([
        "Stellen Sie die Datei unter <b>Einstellungen → Einstellungen → Excel-Stundenzettel</b> ein und prüfen Sie "
        "sie mit „Prüfen“.",
        "Wählen Sie im Dialog den Zeitraum und klicken Sie <b>Vorschau</b>. Excel startet dazu unsichtbar im Hintergrund.",
        "Prüfen Sie die Liste: orange Zeilen ersetzen vorhandene Werte. Unter „Nicht eingetragen“ stehen Gründe.",
        "<b>In Excel eintragen</b> schreibt die Werte. Ist „Datei nach dem Eintragen speichern“ aus, bleibt die Änderung "
        "in Excel offen, und Sie speichern selbst.",
    ]))
    add(s.pic("excel_dialog", "Dialog „In Excel-Stundenzettel eintragen“", width=12 * cm, max_h=7 * cm))

    # --- 11 Einstellungen --------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("11&nbsp;&nbsp;Einstellungen und Stammdaten", H1))
    add(s.pic("menue", "Menü „Einstellungen“", width=8.2 * cm))
    add(P("Zwei Reiter in einem Fenster; das Fenster merkt sich seine Größe.", BODY))
    add(P("Stammdaten", H2))
    add(bullets([
        "<b>Projekte:</b> Neu, Bearbeiten (Name, Nummer, „verrechenbar“), Favorit-Stern (erscheint in der Schnellauswahl), "
        "Farbe, Pfeile hoch/runter (Reihenfolge) und Löschen. Die Reihenfolge entspricht Strg+1 … 9.",
        "<b>Tätigkeiten:</b> Neu, Ändern, Löschen. Eine Tätigkeit gilt für alle Projekte oder nur für eines.",
    ]))
    add(P("Einstellungen", H2))
    add(s.pic("einstellungen", "Reiter „Einstellungen“", width=12.3 * cm, crop_h=480))
    add(table([
        ["Einstellung", "Bedeutung"],
        ["Standardprojekt", "Projekt für „Start“ ohne Auswahl. Ist keines gewählt, entsteht beim ersten Start „Allgemein“."],
        ["Tastenkombination", "öffnet/minimiert WorkPlanner von überall (Standard Strg+Alt+W). Ist sie belegt, meldet "
                              "WorkPlanner das."],
        ["Mit Windows starten", "startet WorkPlanner nach der Anmeldung, auf Wunsch nur als Symbol im Infobereich"],
        ["Schließen/Minimieren → Tray", "das Fenster verschwindet in den Infobereich, WorkPlanner läuft weiter"],
        ["DevOps-Funktionen", "alle DevOps-Teile ein- oder ausblenden"],
        ["Teams-Anrufe", "Nachfrage nach Anrufen ein/aus"],
        ["Hinweis bei Datenbank größer als", "Grenze in MB für die Warnung beim Start (0 = nie); zeigt die aktuelle Größe"],
        ["Mittagspause ab / Pausendauer", "Zeitfenster, das von der Arbeitszeit abgezogen wird (0 min = keine Pause)"],
        ["Mittagspause", "automatisch abziehen oder zur Mittagszeit nachfragen („Pause starten?“)"],
        ["Pausen in Excel", "Pausen-Einträge als Zeile „Pause“ in den Excel-Stundenzettel eintragen (Standard: aus)"],
        ["Soll-Arbeitszeit pro Tag", "Grundlage für Soll, Soll-Ende und alle Differenzen (Montag bis Freitag)"],
        ["Excel-Stundenzettel", "Datei für den Eintrag der Stunden; „Datei nach dem Eintragen speichern“"],
    ], [5.2 * cm, FRAME_W - 5.2 * cm]))

    # --- 12 Tray ------------------------------------------------------------------------------------------------
    add(Spacer(1, 10))
    add(P("12&nbsp;&nbsp;Infobereich, Tastenkombination, Beenden", H1))
    add(bullets([
        "<b>Infobereich (Tray):</b> Das Symbol öffnet das Fenster. Im Rechtsklick-Menü stehen der Zustand der Aufgabe, "
        "„Fenster öffnen“, „Start/Stopp“ und „Beenden“. Der Tooltip zeigt Aufgabe und Laufzeit.",
        "<b>Schließen</b> des Fensters und <b>Minimieren</b> schicken WorkPlanner in den Infobereich (abschaltbar). "
        "Eine laufende Aufgabe läuft weiter.",
        "<b>Beenden</b> geht über <b>Datei → Beenden</b> (Strg+Q) oder den Eintrag im Tray-Menü. Eine laufende Aufgabe wird dabei "
        "nicht gestoppt, ihre Zeit läuft weiter (über Mitternacht hinaus endet sie um 24:00).",
        "<b>Nur eine Instanz:</b> Starten Sie WorkPlanner ein zweites Mal, zeigt sich das bereits laufende Fenster.",
    ]))

    # --- 13 Hilfe / Lizenz --------------------------------------------------------------------------------------
    add(P("13&nbsp;&nbsp;Hilfe, Lizenz und Haftung", H1))
    add(P("Das Menü <b>Hilfe</b> enthält:"))
    add(bullets([
        "<b>Handbuch</b> (Taste <b>F1</b>): dieses Handbuch in einem eigenen Fenster mit Inhaltsverzeichnis, Suche (Strg+F) "
        "und Zoom. Mit F1 springt es zum Kapitel passend zu dem, womit Sie gerade arbeiten: zum Beispiel zu Outlook, wenn "
        "Sie im Outlook-Panel sind, oder zur Woche auf dem Reiter „Woche“. In den Stammdaten öffnet F1 das Kapitel "
        "„Einstellungen und Stammdaten“.",
        "<b>Handbuch im PDF-Programm öffnen</b>: öffnet die PDF-Datei in Ihrem Standard-PDF-Programm, zum Drucken oder "
        "Weitergeben.",
        "<b>Beispieldaten einfügen / entfernen</b>: legt Beispiel-Projekte, -Tätigkeiten und einen Beispieltag an bzw. "
        "entfernt genau diese wieder. Einträge, die Sie selbst auf einem Beispielprojekt gebucht haben, bleiben erhalten; "
        "das Projekt wird dann nur archiviert.",
        "<b>Lizenz …</b> (vollständiger Text).",
        "<b>Über WorkPlanner / Updates …</b>: Version, Autor, Link zum Projekt auf GitHub und die Update-Prüfung (unten).",
    ]))
    add(P("Updates", H2))
    add(P("WorkPlanner sucht <b>nie von allein</b> nach Updates und installiert nie ungefragt. Öffnen Sie "
          "<b>Hilfe → Über WorkPlanner / Updates …</b> und klicken Sie auf <b>Nach Updates suchen</b>. Gibt es eine neuere "
          "Version, sehen Sie die Änderungen und können mit einem weiteren Klick aktualisieren."))
    add(s.pic("ueber", "Über WorkPlanner / Updates (Beispiel mit einer neueren Version)", width=9 * cm))
    add(bullets([
        "Der Installer wird nur von <font name='Mono'>github.com/michael-nesensohn/WorkPlanner</font> geladen und nur "
        "gestartet, wenn seine Prüfsumme (SHA-256) mit der von GitHub gemeldeten übereinstimmt.",
        "Beim Aktualisieren schließt sich WorkPlanner, der Installer ersetzt das Programm und startet es danach neu. "
        "Ihre Daten bleiben unverändert; eine laufende Aufgabe läuft in der Datenbank weiter.",
        "Dazu muss der Rechner GitHub erreichen. Ohne Internet meldet das Fenster das und tut sonst nichts. Dabei "
        "sieht GitHub die IP-Adresse Ihres Rechners; sonst werden keine Daten gesendet.",
    ]))
    add(s.pic("lizenz", "Hilfe → Lizenz", width=9 * cm))
    add(P("WorkPlanner steht unter der <b>MIT-Lizenz</b>, Copyright (c) 2026 Michael Nesensohn. Kurz gesagt: Jeder darf "
          "das Programm nutzen, kopieren, verändern, weitergeben und auch verkaufen; der Lizenzhinweis muss "
          "mitgeliefert werden. Das Programm wird <b>ohne jede Gewährleistung</b> bereitgestellt, und der Autor haftet "
          "nicht für Schäden oder Folgen aus der Nutzung. Maßgeblich ist der englische Lizenztext; diese Zusammenfassung "
          "ist keine Rechtsberatung. Verwendete Bibliotheken (Qt for Python/PySide6, openpyxl, pywin32, Python) haben "
          "eigene Lizenzen."))

    # --- 14 Daten --------------------------------------------------------------------------------------------------
    add(CondPageBreak(9 * cm))
    add(P("14&nbsp;&nbsp;Ihre Daten, Sicherung und Datenbank", H1))
    add(bullets([
        "Alle Daten (Einträge, Projekte, Einstellungen) liegen in einer Datei: "
        "<font name='Mono'>%APPDATA%\\WorkPlanner\\workplanner.db</font>. Es gibt keinen Server und keine Cloud.",
        "<b>Sicherung:</b> Beenden Sie WorkPlanner und kopieren Sie diese Datei. Zum Zurückspielen oder für einen "
        "neuen Rechner kopieren Sie sie an dieselbe Stelle zurück.",
        "<b>Zu groß?</b> Überschreitet die Datei die eingestellte Grenze (Standard 50 MB), erscheint beim Start ein "
        "Hinweis. <b>Komprimieren</b> gibt ungenutzten Platz frei; der Inhalt bleibt unverändert.",
        "Das DevOps-Token ist in der Datei mit der Windows-Benutzerverschlüsselung geschützt und nur in Ihrem "
        "Windows-Konto lesbar; auf einem anderen Rechner oder Konto muss es neu eingetragen werden.",
    ]))
    add(s.pic("db_hinweis", "Hinweis bei zu großer Datenbank", width=11 * cm))

    # --- 15 Kürzel -------------------------------------------------------------------------------------------------
    add(P("15&nbsp;&nbsp;Tastenkürzel und Bedienhinweise", H1))
    add(table([
        ["Aktion", "Bedienung"],
        ["Projekt der Schnellauswahl starten", "Klick auf die Kachel oder Strg + 1 … 9"],
        ["WorkPlanner öffnen/minimieren", "Strg + Alt + W (einstellbar)"],
        ["Handbuch öffnen (zum passenden Kapitel)", "F1"],
        ["Programm beenden", "Strg + Q"],
        ["Einstellungen öffnen", "Strg + ,"],
        ["Eintrag bearbeiten", "Doppelklick auf die Zeile"],
        ["Markierte Einträge löschen", "Entf"],
        ["Laufende Zeit ändern", "Doppelklick auf die große Uhr oder „Zeit ändern“"],
        ["Alle Einträge markieren", "Kästchen im Tabellenkopf (oder Strg + A in der Tabelle)"],
    ], [7 * cm, FRAME_W - 7 * cm]))

    # --- 16 Fehler --------------------------------------------------------------------------------------------------
    add(Spacer(1, 10))
    add(P("16&nbsp;&nbsp;Wenn etwas nicht klappt", H1))
    add(table([
        ["Problem", "Mögliche Ursache und Lösung"],
        ["Outlook-Panel zeigt eine Fehlermeldung",
         "Es braucht das klassische Outlook. Starten Sie Outlook einmal selbst und klicken Sie auf den Kreispfeil. Das "
         "„neue Outlook“ wird nicht unterstützt."],
        ["Teams-Anruf wird nicht erkannt",
         "Wird Teams im Browser genutzt, ist keine Erkennung möglich. Prüfen Sie die Einstellung „Teams-Anrufe“. Sehr "
         "kurze Zugriffe (&lt; 5 s) werden ignoriert."],
        ["„DevOps ist nicht eingerichtet“", "Adresse im Reiter DevOps eintragen und speichern."],
        ["„Kein Token“ / Anmeldung fehlgeschlagen",
         "Token eintragen bzw. erneuern; es braucht die Rechte „Work Items: Read“ (zum Übertragen „Read &amp; write“)."],
        ["Tastenkombination wirkt nicht", "Sie wird von einem anderen Programm benutzt; wählen Sie eine andere unter Einstellungen."],
        ["„Zeiten dürfen nicht in der Zukunft liegen“", "Ende bzw. Start liegt nach der aktuellen Uhrzeit."],
        ["„Einträge dürfen sich nicht überschneiden“", "Passen Sie Start/Ende an; die Vorschau zeigt, wo es kollidiert."],
        ["Excel-Eintrag nicht möglich", "Excel muss installiert sein, die Datei darf nicht schreibgeschützt oder in einem "
                                        "anderen Programm gesperrt sein; „Prüfen“ in den Einstellungen testet die Monatsblätter."],
        ["Fenster nicht zu sehen", "WorkPlanner läuft im Infobereich: Symbol anklicken oder Strg + Alt + W."],
    ], [5.2 * cm, FRAME_W - 5.2 * cm]))
    return st


class TocDoc(Manual):
    pass


def build(out: Path, screens: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = Manual(str(out))
    doc.multiBuild(story(Screens(screens)))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "WorkPlanner-Handbuch.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        shots = Path(tmp)
        subprocess.run([sys.executable, str(ROOT / "tools" / "manual_screens.py"), str(shots)], check=True)
        build(target, shots)
    print("Handbuch:", target, f"({target.stat().st_size // 1024} KB)")
