"""Industriezeit (1,25 = 1 h 15 min) statt Std:Min: Woche, Berichte (Vorschau, Excel, PDF)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from test_week_entries import cell, week_setup
from workplanner.export import export_excel
from workplanner.export_pdf import build_html
from workplanner.ui.main_window import MainWindow
from workplanner.ui.pages import WeekPage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


# --- Woche ----------------------------------------------------------------------------------------

def test_week_shows_hours_minutes_by_default_and_industrial_on_request(qapp):
    svc, page = week_setup()
    assert not page.industrial.isChecked() and not svc.week_industrial
    assert page.days.item(0, 1).text() == "3:00" and cell(page, 1, 2) == "1:30"
    page.industrial.setChecked(True)
    assert svc.week_industrial                                                    # wird gemerkt
    assert page.days.item(0, 1).text() == "3,00" and page.days.item(0, 4).text() == "8,00"
    assert page.days.item(0, 5).text() == "–5,00"                                 # Differenz
    assert cell(page, 1, 2) == "1,50"                                             # Einträge
    assert "Gearbeitet 3,00 h" in cell(page, 0, 0) and "Soll 8,00 h" in cell(page, 0, 0)
    assert cell(page, page.entries.rowCount() - 1, 0).startswith("Woche gesamt: 4,25 h")


def test_week_choice_is_restored_next_time(qapp):
    svc, _ = week_setup()
    svc.set_week_industrial(True)
    page = WeekPage(svc)
    assert page.industrial.isChecked() and page.days.item(0, 1).text() == "3,00"
    page.industrial.setChecked(False)
    assert page.days.item(0, 1).text() == "3:00" and not svc.week_industrial


# --- Berichte -------------------------------------------------------------------------------------

def report_window():
    svc, _ = week_setup()
    w = MainWindow(svc)
    w.report.first.setDate(QDate(2026, 11, 2))
    w.report.last.setDate(QDate(2026, 11, 2))
    w.report.column_boxes["duration"].setChecked(True)
    w.report._update()
    return w, svc


def duration_texts(report):
    cols = [report.preview.horizontalHeaderItem(c).text() for c in range(report.preview.columnCount())]
    n = cols.index("Dauer")
    return [report.preview.item(r, n).text() for r in range(report.preview.rowCount())]


def test_report_preview_and_summary_switch_to_industrial_next_to_duration(qapp):
    w, svc = report_window()
    r = w.report
    assert not r.industrial.isChecked() and not svc.report_industrial
    assert duration_texts(r) == ["1:30", "1:30"] and "Arbeitszeit gesamt: <b>3:00 h</b>" in r.summary.text()
    r.industrial.setChecked(True)
    assert svc.report_industrial
    assert duration_texts(r) == ["1,50", "1,50"] and "Arbeitszeit gesamt: <b>3,00 h</b>" in r.summary.text()
    layout = r.industrial.parentWidget().layout()                                  # steht gleich neben „Dauer“
    names = [layout.itemAt(i).widget().text() for i in range(layout.count())]
    assert names[names.index("Dauer") + 1] == "Industriezeit"


def rows_for_export(svc):
    return svc.report_rows(date(2026, 11, 2), date(2026, 11, 2))


def test_excel_export_industrial_writes_decimal_hours_with_number_format(tmp_path):
    svc, _ = week_setup()
    path = tmp_path / "i.xlsx"
    export_excel(path, rows_for_export(svc), svc.target_for, ["date", "duration", "project"], industrial=True)
    wb = load_workbook(path)
    ws = wb["Einträge"]
    assert ws["B2"].value == 1.5 and ws["B2"].number_format == "0.00"
    sums = wb["Tagessummen"]
    assert sums["C2"].value == 3.0 and sums["F2"].value == 8.0 and sums["C2"].number_format == "0.00"
    proj = wb["Projektsummen"]
    assert proj["D2"].value == 1.5 and proj["F2"].value == "=D2"                  # dezimale Spalte ohne „*24“


def test_excel_export_default_stays_hours_minutes(tmp_path):
    svc, _ = week_setup()
    path = tmp_path / "d.xlsx"
    export_excel(path, rows_for_export(svc), svc.target_for, ["date", "duration", "project"])
    wb = load_workbook(path)
    assert wb["Einträge"]["B2"].value == timedelta(hours=1, minutes=30) and wb["Einträge"]["B2"].number_format == "[h]:mm"
    assert wb["Projektsummen"]["F2"].value == "=D2*24"


def test_pdf_industrial_and_default_do_not_leak_into_each_other():
    svc, _ = week_setup()
    rows = rows_for_export(svc)
    day = date(2026, 11, 2)
    ind = build_html(rows, timedelta(hours=8), day, day, industrial=True)
    assert "1,50" in ind and "3,00 h" in ind and "1:30" not in ind
    plain = build_html(rows, timedelta(hours=8), day, day)
    assert "1:30" in plain and "1,50" not in plain
