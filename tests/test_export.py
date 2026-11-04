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
