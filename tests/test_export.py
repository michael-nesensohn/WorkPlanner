from datetime import date, datetime, timedelta

from openpyxl import load_workbook

from test_service import DAY, Clock
from workplanner.db import Database
from workplanner.export import ALL_COLUMNS, export_excel
from workplanner.service import TimeService


def test_export_has_three_sheets_with_data(tmp_path):
    db = Database()
    clock = Clock()
    svc = TimeService(db, clock)
    a = db.add_project("Kunde A", number="2026-014")
    act = db.add_activity("Test")
    svc.start_task(a, act, "Waage")
    clock.set(13)
    svc.stop()
    path = tmp_path / "out.xlsx"
    export_excel(path, svc.report_rows(DAY, DAY), svc.daily_target, ALL_COLUMNS)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Einträge", "Tagessummen", "Projektsummen"]
    entries = wb["Einträge"]
    assert entries.max_row == 2  # Kopf + ein Eintrag: die Mittagspause wird nur abgezogen, nicht eingefügt
    from datetime import timedelta
    assert entries["D2"].value == timedelta(hours=4, minutes=30) and entries["K2"].value == timedelta(minutes=30)
    assert entries["K1"].value == "Mittagspause (abgezogen)"
    assert entries["F2"].value == "2026-014" and entries["G2"].value == "Kunde A"
    assert entries["I2"].value == "Waage"
    day = wb["Tagessummen"]
    assert day["C2"].value == timedelta(hours=4, minutes=30) and day["E2"].value == timedelta(minutes=30)
    assert wb["Projektsummen"]["A2"].value == "2026-014" and wb["Projektsummen"]["B2"].value == "Kunde A"


def test_export_columns_default_and_custom(tmp_path):
    from workplanner.export import DEFAULT_COLUMNS
    db = Database()
    clock = Clock()
    svc = TimeService(db, clock)
    a = db.add_project("Kunde A", number="2026-014")
    svc.start_task(a, db.add_activity("Test"), "Waage")
    clock.set(13)
    svc.stop()
    assert svc.export_columns == DEFAULT_COLUMNS
    export_excel(tmp_path / "d.xlsx", svc.report_rows(DAY, DAY), svc.daily_target)
    ws = load_workbook(tmp_path / "d.xlsx")["Einträge"]
    assert [c.value for c in ws[1]] == ["Datum", "Dauer", "Verrechenbar", "Projektnr.", "Projekt",
                                        "Tätigkeit", "Notiz", "DevOps"]
    svc.set_export_columns(["project", "date"])
    assert svc.export_columns == ["project", "date"]
    export_excel(tmp_path / "c.xlsx", svc.report_rows(DAY, DAY), svc.daily_target, ["project", "date"])
    ws = load_workbook(tmp_path / "c.xlsx")["Einträge"]
    assert [c.value for c in ws[1]] == ["Projekt", "Datum"] and ws["A2"].value == "Kunde A"


# --- Start/Ende: nur über die versteckte workplanner.ini wählbar --------------------------------------------

def _svc_with_ini(tmp_path, monkeypatch, text=None):
    monkeypatch.setenv("WORKPLANNER_DATA", str(tmp_path))
    if text is not None:
        (tmp_path / "workplanner.ini").write_text(text, encoding="utf-8")
    return TimeService(Database(), Clock())


def test_start_and_end_columns_are_hidden_by_default(tmp_path, monkeypatch):
    svc = _svc_with_ini(tmp_path, monkeypatch)
    assert "start" not in svc.available_export_columns and "end" not in svc.available_export_columns
    svc.db.set_setting("export_columns", "date,start,end,project")           # z. B. aus einer älteren Auswahl
    assert svc.export_columns == ["date", "project"]


def test_ini_switch_shows_start_and_end(tmp_path, monkeypatch):
    svc = _svc_with_ini(tmp_path, monkeypatch, "[export]\nshow_start_end = 1\n")
    assert {"start", "end"} <= set(svc.available_export_columns)
    svc.set_export_columns(["date", "start", "end", "project"])
    assert svc.export_columns == ["date", "start", "end", "project"]


def test_broken_or_off_ini_keeps_them_hidden(tmp_path, monkeypatch):
    for text in ("show_start_end = 1", "[export]\nshow_start_end = nein", "[export\n???"):
        svc = _svc_with_ini(tmp_path, monkeypatch, text)
        assert "start" not in svc.available_export_columns


def test_report_page_has_no_start_end_boxes_without_the_ini(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from workplanner.ui.pages import ReportPage
    app = QApplication.instance() or QApplication([])
    svc = _svc_with_ini(tmp_path, monkeypatch)
    page = ReportPage(svc)
    assert "start" not in page.column_boxes and "end" not in page.column_boxes and "date" in page.column_boxes
    svc2 = _svc_with_ini(tmp_path, monkeypatch, "[export]\nshow_start_end = true\n")
    assert {"start", "end"} <= set(ReportPage(svc2).column_boxes)
    assert app is not None
