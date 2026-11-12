"""Excel-Export (Einträge, Tagessummen, Projektsummen)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DURATION_FMT = "[h]:mm"
HEADER_FILL = PatternFill("solid", fgColor="2F5597")
HEADER_FONT = Font(bold=True, color="FFFFFF")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _header(ws, titles: list[str]) -> None:
    ws.append(titles)
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"


def _sum(items) -> timedelta:
    return sum(items, timedelta())


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


# Schlüssel -> (Titel, Breite, Wert, Zahlenformat, Ausrichtung)
COLUMNS: dict[str, tuple[str, int, object, str | None, str]] = {
    "date": ("Datum", 12, lambda r: r["date"], "DD.MM.YYYY", "top"),
    "start": ("Start", 8, lambda r: r["start"].time(), "HH:MM", "top"),
    "end": ("Ende", 8, lambda r: r["end"].time(), "HH:MM", "top"),
    "duration": ("Dauer", 9, lambda r: r["duration"], DURATION_FMT, "top"),
    "billable": ("Verrechenbar", 13,
                 lambda r: "Ja" if r["billable"] else "Nein" if r["kind"] == "work" else "", None, "center"),
    "project_number": ("Projektnr.", 12, lambda r: r["project_number"], None, "top"),
    "project": ("Projekt", 24, lambda r: r["project"], None, "top"),
    "activity": ("Tätigkeit", 24, lambda r: r["activity"], None, "top"),
    "note": ("Notiz", 60, lambda r: r["note"], None, "wrap"),
    "devops": ("DevOps", 10, lambda r: r["devops_id"] or "", None, "top"),
}
ALL_COLUMNS = list(COLUMNS)
# Nur über die versteckte Einstellung in workplanner.ini wählbar (siehe config.py)
HIDDEN_COLUMNS = ("start", "end")
DEFAULT_COLUMNS = ["date", "duration", "billable", "project_number", "project", "activity", "note", "devops"]


def export_excel(path: str | Path, rows: list[dict], daily_target: timedelta,
                 columns: list[str] | None = None, show_pauses: bool = True) -> None:
    """`rows` kommen aus `TimeService.report_rows`; `columns` sind Schlüssel aus `COLUMNS` (Standard: `DEFAULT_COLUMNS`).
    Ohne `show_pauses` fehlen die Pausen-Einträge im Blatt „Einträge“ (die Tagesübersicht zählt sie weiterhin)."""
    cols = [c for c in (columns or DEFAULT_COLUMNS) if c in COLUMNS] or DEFAULT_COLUMNS
    wb = Workbook()

    ws = wb.active
    ws.title = "Einträge"
    _header(ws, [COLUMNS[c][0] for c in cols])
    for r in (rows if show_pauses else [r for r in rows if r["kind"] != "pause"]):
        ws.append([COLUMNS[c][2](r) for c in cols])
        i = ws.max_row
        for n, c in enumerate(cols, 1):
            _, _, _, fmt, align = COLUMNS[c]
            if fmt:
                ws.cell(i, n).number_format = fmt
            ws.cell(i, n).alignment = (Alignment(horizontal="center", vertical="top") if align == "center" else
                                       Alignment(wrap_text=True, vertical="top") if align == "wrap" else
                                       Alignment(vertical="top"))
    _widths(ws, [COLUMNS[c][1] for c in cols])
    ws.auto_filter.ref = ws.dimensions

    days = sorted({r["date"] for r in rows})
    ws = wb.create_sheet("Tagessummen")
    _header(ws, ["Datum", "Wochentag", "Arbeitszeit", "davon verrechenbar", "Pausen", "Soll", "Differenz"])
    for d in days:
        work = _sum(r["duration"] for r in rows if r["date"] == d and r["kind"] == "work")
        billable = _sum(r["duration"] for r in rows if r["date"] == d and r["billable"])
        pause = (_sum(r["duration"] for r in rows if r["date"] == d and r["kind"] == "pause")
                 + _sum(r["lunch"] for r in rows if r["date"] == d))   # Mittagspause: in der Arbeitszeit abgezogen
        target = daily_target if d.weekday() < 5 else timedelta()
        ws.append([d, WEEKDAYS[d.weekday()], work, billable, pause, target, None])
        i = ws.max_row
        ws.cell(i, 7).value = f"=C{i}-F{i}"
        ws.cell(i, 1).number_format = "DD.MM.YYYY"
        for c in range(3, 8):
            ws.cell(i, c).number_format = DURATION_FMT
    if days:
        n = ws.max_row
        ws.append(["Summe", None] + [f"=SUM({get_column_letter(c)}2:{get_column_letter(c)}{n})"
                                      for c in range(3, 8)])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for c in range(3, 8):
            ws.cell(ws.max_row, c).number_format = DURATION_FMT
    _widths(ws, [12, 14, 13, 19, 10, 10, 12])

    ws = wb.create_sheet("Projektsummen")
    _header(ws, ["Projektnr.", "Projekt", "Tätigkeit", "Dauer", "davon verrechenbar", "Stunden (dezimal)"])
    numbers = {r["project"]: r["project_number"] for r in rows}
    # Projekt -> Tätigkeit -> [gesamt, verrechenbar]
    totals: dict[str, dict[str, list[timedelta]]] = defaultdict(
        lambda: defaultdict(lambda: [timedelta(), timedelta()]))
    for r in rows:
        if r["kind"] == "work":
            t = totals[r["project"]][r["activity"] or "–"]
            t[0] += r["duration"]
            if r["billable"]:
                t[1] += r["duration"]
    for project in sorted(totals):
        acts = totals[project]
        ws.append([numbers.get(project, ""), project, None,
                   _sum(a[0] for a in acts.values()), _sum(a[1] for a in acts.values()), None])
        head_row = ws.max_row
        for c in ws[head_row]:
            c.font = Font(bold=True)
        for activity in sorted(acts):
            ws.append([None, None, activity, acts[activity][0], acts[activity][1], None])
        for i in range(head_row, ws.max_row + 1):
            ws.cell(i, 4).number_format = ws.cell(i, 5).number_format = DURATION_FMT
            ws.cell(i, 6).value = f"=D{i}*24"
            ws.cell(i, 6).number_format = "0.00"
    _widths(ws, [12, 28, 28, 12, 19, 18])

    wb.save(path)
