"""Erzeugt die Bildschirmfotos für das Handbuch aus der echten Oberfläche – mit Beispieldaten (nie mit echten).

    python tools/manual_screens.py <Zielordner>

Alles läuft in einer Speicher-Datenbank mit fester Uhr (Mittwoch, 04.11.2026, 14:22); Outlook und DevOps sind
nachgestellt. Es werden weder die echte Datenbank noch Outlook, DevOps oder das Dateisystem außerhalb des
Zielordners angefasst.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import os  # noqa: E402

# Bildschirmfotos brauchen die echte Windows-Oberfläche: Qt „offscreen“ (Testmodus) kennt hier keine Schriften, dann
# erscheinen nur Kästchen statt Text. Eine von außen gesetzte Variable (Skripte, IDE) wird deshalb entfernt.
if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
    del os.environ["QT_QPA_PLATFORM"]

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from workplanner.db import Database  # noqa: E402
from workplanner.outlook import Appointment  # noqa: E402
from workplanner.service import TimeService  # noqa: E402
from workplanner.ui.call_dialog import CallBanner, CallDialog  # noqa: E402
from workplanner.call_monitor import Call  # noqa: E402
from workplanner.ui.dialogs import EntryDialog, RunningTimeDialog  # noqa: E402
from workplanner.ui.excel_dialog import ExcelExportDialog  # noqa: E402
from workplanner.ui.main_window import MainWindow  # noqa: E402
from workplanner.ui.outlook_dialog import OutlookImportDialog  # noqa: E402
from workplanner.timeline import Entry  # noqa: E402

DAY = datetime(2026, 11, 4)


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 4, 7, 30)

    def __call__(self):
        return self.t

    def at(self, h, m=0):
        self.t = datetime(2026, 11, 4, h, m)


def at(h, m=0):
    return datetime(2026, 11, 4, h, m)


APPOINTMENTS = [
    Appointment("a1", "Daily Stand-up", at(9, 15), at(9, 30)),
    Appointment("a2", "JourFix technische Abstimmung", at(10, 30), at(11, 15), location="Teams"),
    Appointment("a3", "Demo-Plattform – Planung", at(13, 30), at(14, 0)),
    Appointment("a4", "Ganztägig: Schulung", at(0, 0), datetime(2026, 11, 5), all_day=True),
    Appointment("a5", "Sprint Review", at(15, 0), at(16, 0), location="Raum 2.14"),
]

FEATURES = [
    {"id": 4411, "title": "Waagen-Schnittstelle", "type": "feature", "state": "Active", "parent_id": None,
     "parent_title": "", "epic": "Demo-Plattform", "start": "2026-11-03", "url": ""},
    {"id": 4412, "title": "Tara-Abgleich", "type": "story", "state": "Active", "parent_id": 4411,
     "parent_title": "Waagen-Schnittstelle", "epic": "Demo-Plattform", "start": "", "url": ""},
    {"id": 4413, "title": "Fehlermeldungen vereinheitlichen", "type": "story", "state": "New", "parent_id": 4411,
     "parent_title": "Waagen-Schnittstelle", "epic": "Demo-Plattform", "start": "", "url": ""},
    {"id": 4520, "title": "Abnahmetests Kunde A", "type": "feature", "state": "New", "parent_id": None,
     "parent_title": "", "epic": "Kunde A", "start": "2026-11-05", "url": ""},
    {"id": 4390, "title": "Doku Schnittstellen", "type": "feature", "state": "Active", "parent_id": None,
     "parent_title": "", "epic": "Demo-Plattform", "start": "2026-11-20", "url": ""},
]


def build_service() -> tuple[TimeService, Clock]:
    db = Database()
    clock = Clock()
    svc = TimeService(db, clock)
    waage = db.add_project("Waagen-Schnittstelle", "#4f8cff", number="4411", billable=True)
    abnahme = db.add_project("Abnahmetests Kunde A", "#2ea36b", number="4520", billable=True)
    meeting = db.add_project("Meeting", "#d9534f")
    db.add_project("Intern", "#e8a33d")
    support = db.add_project("Support", "#c05cc0", number="2026-099")
    prog = db.add_activity("Programmierung")
    test = db.add_activity("Test")
    doc = db.add_activity("Dokumentation")
    besp = db.add_activity("Besprechung")
    fehler = db.add_activity("Fehlersuche")
    tel = db.add_activity("Telefonat")
    db.set_setting("excel_path", r"C:\Users\Max\Dokumente\Stunden_2026.xlsx")
    db.set_setting("devops_features_cache", __import__("json").dumps(FEATURES))
    svc.set_default_project(meeting)

    svc.start_task(waage, prog, "Schnittstelle zur Waage umgesetzt")
    svc.edit_entry(svc.current().id, {"devops_id": 4412})
    clock.at(9, 15)
    svc.start_task(abnahme, test, "Testfälle für die Abnahme erstellt\nPrüfplan mit dem Kunden abgestimmt")
    clock.at(10, 30)
    svc.start_task(meeting, besp, "JourFix technische Abstimmung")
    clock.at(11, 15)
    svc.start_task(waage, fehler, "Fehler beim Tara-Abgleich eingegrenzt")
    svc.edit_entry(svc.current().id, {"devops_id": 4412})
    clock.at(13, 0)
    svc.start_task(support, tel, "Kundenanruf: Rückfrage zur Firmware")
    clock.at(13, 40)
    svc.start_task(waage, doc, "Beschreibung der Schnittstelle")
    svc.edit_entry(svc.current().id, {"devops_id": 4413})
    clock.at(14, 22)
    db.mark_outlook_imported(["a2"])
    return svc, clock


def pump(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def shot(widget, path: Path) -> None:
    widget.grab().save(str(path))


def callouts(pixmap_path: Path, spots: list[tuple[int, QPoint]]) -> None:
    from PySide6.QtGui import QPixmap
    pm = QPixmap(str(pixmap_path))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    font = QFont("Segoe UI", 11)
    font.setBold(True)
    p.setFont(font)
    for number, pos in spots:
        p.setBrush(QColor("#c0392b"))
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(pos, 13, 13)
        p.setPen(QColor("white"))
        p.drawText(QRect(pos.x() - 13, pos.y() - 13, 26, 26), Qt.AlignCenter, str(number))
    p.end()
    pm.save(str(pathlib_str(pixmap_path)))


def pathlib_str(p: Path) -> str:
    return str(p)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    svc, clock = build_service()
    w = MainWindow(svc, enable_outlook=True, outlook_reader=lambda a, b: APPOINTMENTS)
    w.resize(1500, 880)
    w.show()
    w.day = DAY.date()
    w.refresh()
    pump(app, 1.5)
    for _ in range(40):  # Outlook-Termine werden im Hintergrund gelesen
        pump(app, 0.1)
        if any(isinstance(b, QPushButton) and b.objectName() == "tile" for b in w.outlook.findChildren(QPushButton)):
            break
    pump(app, 0.5)

    # --- Übersicht mit Nummern ------------------------------------------------------------
    shot(w, out / "heute.png")          # ohne Nummern (für die README)
    full = out / "uebersicht.png"
    shot(w, full)

    def pos(widget, dx=0.0, dy=0.0, ax=0.0, ay=0.0) -> QPoint:
        p = widget.mapTo(w, QPoint(0, 0))
        return QPoint(int(p.x() + widget.width() * ax + dx), int(p.y() + widget.height() * ay + dy))
    card = w.task_label.parentWidget()
    callouts(full, [
        (1, pos(w.menuBar(), 175, 0, 0, 0.5)),
        (2, pos(w.now_label, -90, 0, 0, 0.5)),
        (3, pos(card, -24, 24, 1, 0)),
        (4, pos(w.table, -30, -30, 1, 0.9)),
        (5, pos(w.outlook, 0, 0, 0.5, 0.82)),
        (6, pos(w.features, 0, 0, 0.5, 0.82)),
        (7, pos(w.body.widget(3), 0, 0, 0.5, 0.82)),
        (8, pos(w.note_task_btn, 18, 0, 1, 0.5)),
    ])
    shot(card, out / "startkarte.png")
    shot(w.body.widget(0), out / "tabelle.png")
    shot(w.outlook, out / "outlook_panel.png")
    shot(w.features, out / "devops_panel.png")
    shot(w.body.widget(3), out / "schnellauswahl.png")

    # --- Dialoge ----------------------------------------------------------------------------
    run = svc.current()
    d = RunningTimeDialog(svc, run, w)
    d.show(); pump(app, 0.3); shot(d, out / "zeit_aendern.png"); d.close()
    d = EntryDialog(svc, w.day, None, at(14, 0), w)
    d.start.setTime(d.start.time().fromString("11:15", "HH:mm"))   # vor „Fehlersuche“: die späteren rücken nach hinten
    d.end.setTime(d.end.time().fromString("11:45", "HH:mm"))
    d.note.setPlainText("Rückruf Kunde, Termin vereinbart")
    d.project.setCurrentIndex(d.project.findText("Support"))
    d.show(); pump(app, 0.3); shot(d, out / "eintrag_dialog.png"); d.close()
    d = OutlookImportDialog(svc, w.day, w, reader=lambda a, b: APPOINTMENTS)
    d.show(); pump(app, 1.2); shot(d, out / "outlook_import.png"); d.close()
    d = CallDialog(svc, Call(at(14, 5), at(14, 19)), w)
    d.note.setPlainText("Abstimmung Prüfplan mit dem Kunden")
    d.show(); pump(app, 0.3); shot(d, out / "call_dialog.png"); d.close()
    b = CallBanner()
    b.show_call(at(14, 5), at(14, 19))
    pump(app, 0.2)
    shot(b, out / "call_banner.png"); b.close()
    d = ExcelExportDialog(svc, w)
    d.show(); pump(app, 0.3); shot(d, out / "excel_dialog.png"); d.close()
    svc.db.set_setting("db_warn_mb", "0")
    box = QMessageBox(QMessageBox.Warning, "Datenbank ist groß",
                      "Die Datenbank ist 63 MB groß (Hinweisgrenze: 50 MB).\n\n"
                      r"Datei: C:\Users\Max\AppData\Roaming\WorkPlanner\workplanner.db" "\n\n"
                      "Das kann den Start und die Auswertungen verlangsamen. „Komprimieren“ gibt ungenutzten Platz "
                      "frei; ist sie danach immer noch groß, bitte die Datei sichern.", QMessageBox.NoButton)
    box.addButton("Komprimieren", QMessageBox.AcceptRole)
    box.addButton("OK", QMessageBox.RejectRole)
    box.show(); pump(app, 0.3); shot(box, out / "db_hinweis.png"); box.close()
    from workplanner.ui.license_dialog import LicenseDialog
    d = LicenseDialog(w)
    d.show(); pump(app, 0.3); shot(d, out / "lizenz.png"); d.close()

    # --- Seiten -----------------------------------------------------------------------------
    w.tabs.setCurrentWidget(w.week)
    w.week.views.setCurrentIndex(0)
    w.week.monday = at(0).date().replace(day=2)
    w.week.refresh(); pump(app, 0.3)
    shot(w.week, out / "woche_uebersicht.png")
    w.week.views.setCurrentIndex(1); pump(app, 0.3)
    shot(w.week, out / "woche_eintraege.png")
    w.tabs.setCurrentWidget(w.report)
    w.report.first.setDate(w.report.first.date().addDays(-3)); pump(app, 0.4)
    w.report.grab().copy(0, 0, w.report.width(), 560).save(str(out / "berichte.png"))
    w.tabs.setCurrentWidget(w.devops); pump(app, 0.3)
    shot(w.devops, out / "devops_seite.png")
    w.tabs.setCurrentIndex(0)

    w.show_master(0); pump(app, 0.4)
    shot(w.master_dialog, out / "stammdaten.png")
    w.show_master(1); pump(app, 0.4)
    shot(w.master_dialog, out / "einstellungen.png")
    w.master_dialog.close()

    menu = w.menuBar().actions()[1].menu()
    menu.popup(w.mapToGlobal(QPoint(60, 30))); pump(app, 0.3)
    shot(menu, out / "menue.png"); menu.close()
    w.close()
    print("Bildschirmfotos:", len(list(out.glob("*.png"))), "in", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
