"""Erzeugt ein Muster des PDF-Berichts aus neutralen Beispieldaten: docs/Bericht_Muster_*.pdf (steht in .gitignore)."""
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from workplanner.export_pdf import export_pdf  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication([])


def row(day, sh, sm, eh, em, project, number, activity, note, billable=True, kind="work", lunch=0):
    s, e = datetime(day.year, day.month, day.day, sh, sm), datetime(day.year, day.month, day.day, eh, em)
    return {"date": day, "start": s, "end": e, "running": False, "kind": kind, "project": project,
            "project_number": number, "activity": activity, "note": note, "billable": billable and kind == "work",
            "devops_id": None, "duration": e - s - timedelta(minutes=lunch), "lunch": timedelta(minutes=lunch)}


d1, d2 = date(2026, 11, 9), date(2026, 11, 10)
rows = [
    row(d1, 8, 0, 9, 30, "Kunde A – Portal", "1001", "Entwicklung", "Login-Maske überarbeitet"),
    row(d1, 9, 30, 10, 15, "Kunde B – Wartung", "1002", "Support", "Fehler im Export analysiert"),
    row(d1, 10, 15, 12, 0, "Kunde A – Portal", "1001", "Entwicklung", "Benutzerverwaltung; Rollenprüfung"),
    row(d1, 12, 0, 12, 30, "", "", "", "", kind="pause"),
    row(d1, 12, 30, 14, 0, "Kunde A – Portal", "1001", "Besprechung", "Abstimmung Anforderungen", billable=False),
    row(d1, 14, 0, 16, 30, "Kunde A – Portal", "1001", "Entwicklung", "Login-Maske überarbeitet"),
    row(d1, 16, 30, 17, 0, "Allgemein", "", "Verwaltung", "Zeiten nachgetragen", billable=False),
    row(d2, 8, 0, 10, 0, "Kunde B – Wartung", "1002", "Support", "Rückfragen beantwortet"),
    row(d2, 10, 0, 12, 0, "Demo-Plattform", "2001", "Test", "Regressionstests; Fehlerberichte geschrieben"),
    row(d2, 12, 0, 12, 30, "", "", "", "", kind="pause"),
    row(d2, 12, 30, 16, 0, "Demo-Plattform", "2001", "Entwicklung", "Schnittstelle zur Auswertung"),
]
for mode, name in (("summary", "Bericht_Muster_zusammengefasst.pdf"), ("detail", "Bericht_Muster_einzeln.pdf")):
    out = ROOT / "docs" / name
    export_pdf(out, rows, timedelta(hours=8), d1, d2, mode=mode, show_pauses=True)
    print(out)
