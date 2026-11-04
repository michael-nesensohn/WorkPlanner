import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import time
from datetime import date, datetime

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from test_excel_timesheet import FakeBook, FakeSheet
from test_service import Clock
from workplanner.db import Database
from workplanner.excel_timesheet import ExcelError
from workplanner.service import TimeService
from workplanner.timeline import Entry
from workplanner.ui.excel_dialog import ExcelExportDialog
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait(qapp, cond, seconds=3):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


class FakeWorkbookCM:
    """Ersatz für ExcelWorkbook: merkt sich, wie er geöffnet wurde."""
    opened: list = []

    def __init__(self, book, error=None):
        self.book, self.error = book, error

    def factory(self, path, save=True):
        FakeWorkbookCM.opened.append((path, save))
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self.book

    def __exit__(self, *exc):
        return False


def setup(tmp_path=None, excel_path=r"C:\Zeiten\nem_2026.xlsx", save=True):
    db = Database()
    clock = Clock(18, 0)
    clock.t = datetime(2026, 11, 2, 18, 0)                         # Montag 02.11.2026
    svc = TimeService(db, clock)
    numbered = db.add_project("X1 - Farbvarianten", number="E24005-20")
    plain = db.add_project("Interne Doku")
    db.save_day(date(2026, 11, 2), [
        Entry(datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 10), project_id=numbered, note="a"),
        Entry(datetime(2026, 11, 2, 10), datetime(2026, 11, 2, 11, 30), project_id=plain, note="b"),
        Entry(datetime(2026, 11, 2, 13), datetime(2026, 11, 2, 14), project_id=numbered, note="c")])
    svc.set_excel(excel_path, save)
    return svc


# --- Einstellung ------------------------------------------------------------------------------

def test_settings_are_saved_and_shown(qapp):
    svc = setup(excel_path="", save=True)
    w = MainWindow(svc)
    page = w.master
    assert page.excel_path.text() == "" and page.excel_save.isChecked()
    page.excel_path.setText(r"C:\x\zettel.xlsx")
    page.excel_path.editingFinished.emit()
    page.excel_save.click()
    assert svc.excel_path == r"C:\x\zettel.xlsx" and svc.excel_save is False
    page.reload()
    assert page.excel_path.text() == r"C:\x\zettel.xlsx" and not page.excel_save.isChecked()


def test_report_button_follows_the_setting(qapp):
    svc = setup(excel_path="")
    w = MainWindow(svc)
    assert not w.report.to_excel.isEnabled() and "Stammdaten" in w.report.to_excel.toolTip()
    w.master.excel_path.setText(r"C:\x\zettel.xlsx")
    w.master.excel_path.editingFinished.emit()
    assert w.report.to_excel.isEnabled()
    w.master.excel_path.setText("")
    w.master.excel_path.editingFinished.emit()
    assert not w.report.to_excel.isEnabled()


def test_check_finds_month_sheets_without_starting_excel(qapp, tmp_path):
    from openpyxl import Workbook
    from workplanner.excel_timesheet import MONTH_NAMES
    full, partial = Workbook(), Workbook()
    full.active.title = "Januar"
    for n in MONTH_NAMES[1:11]:
        full.create_sheet(n)
    full.create_sheet("Dezember ")                              # Leerzeichen am Ende wie in der Vorlage
    full.save(tmp_path / "voll.xlsx")
    partial.active.title = "Januar"
    partial.create_sheet("Februar")
    partial.save(tmp_path / "teil.xlsx")
    w = MainWindow(setup(excel_path=""))
    page = w.master
    page.excel_path.setText(str(tmp_path / "voll.xlsx"))
    page._check_excel()
    assert "Alle 12 Monatsblätter" in page.excel_status.text()
    page.excel_path.setText(str(tmp_path / "teil.xlsx"))
    page._check_excel()
    assert "Es fehlen Blätter" in page.excel_status.text() and "März" in page.excel_status.text()
    page.excel_path.setText(str(tmp_path / "gibtsnicht.xlsx"))
    page._check_excel()
    assert "nicht lesbar" in page.excel_status.text()


# --- Dialog ---------------------------------------------------------------------------------------

def test_preview_lists_summed_hours_per_project_and_then_writes(qapp):
    svc = setup()
    sheet = FakeSheet("November")
    cm = FakeWorkbookCM(FakeBook(sheet))
    FakeWorkbookCM.opened = []
    dlg = ExcelExportDialog(svc, workbook_factory=cm.factory)
    assert (dlg.first.date().toPython(), dlg.last.date().toPython()) == (date(2026, 11, 2), date(2026, 11, 2))
    dlg._preview()
    assert wait(qapp, lambda: dlg.table.rowCount() == 2)
    rows = [[dlg.table.item(r, c).text() for c in range(6)] for r in range(2)]
    # E24005-20: 2 h + 1 h = 3 h in Zeile 8 (vorhanden); „Interne Doku“ ohne Nummer: 1,5 h in neuer Zeile 10 (Name)
    assert rows[0][:5] == ["02.11.2026", "E24005-20  X1 - Farbvarianten", "3.00", "November  T8", "vorhanden"]
    assert rows[1][:5] == ["02.11.2026", "Interne Doku", "1.50", "November  T10", "neue Zeile (Name)"]
    assert FakeWorkbookCM.opened == [(r"C:\Zeiten\nem_2026.xlsx", False)]       # Vorschau speichert nie
    assert dlg.ok.isEnabled() and dlg.ok.text() == "2 Wert(e) in Excel eintragen" and sheet.writes == []
    dlg._write()
    assert wait(qapp, lambda: "✓" in dlg.status.text())
    assert sheet.writes == [(10, 1, "Interne Doku"), (8, 20, 3.0), (10, 20, 1.5)]   # erst neue Zeile, dann Stunden
    assert "2 Wert(e) in Excel eingetragen und gespeichert" in dlg.status.text()
    assert FakeWorkbookCM.opened[-1] == (r"C:\Zeiten\nem_2026.xlsx", True)         # Schreiben speichert (Einstellung)
    assert not dlg.ok.isEnabled()


def test_save_setting_off_is_respected_and_reported(qapp):
    svc = setup(save=False)
    cm = FakeWorkbookCM(FakeBook(FakeSheet("November")))
    FakeWorkbookCM.opened = []
    dlg = ExcelExportDialog(svc, workbook_factory=cm.factory)
    dlg._preview()
    assert wait(qapp, lambda: dlg.ok.isEnabled())
    dlg._write()
    assert wait(qapp, lambda: "✓" in dlg.status.text())
    assert FakeWorkbookCM.opened[-1][1] is False and "noch nicht gespeichert" in dlg.status.text()


def test_existing_values_are_marked_and_counted(qapp):
    svc = setup()
    sheet = FakeSheet("November")
    sheet.v[8, 20] = 5.0                                          # T8 hat schon 5 h (Montag 02.11.)
    dlg = ExcelExportDialog(svc, workbook_factory=FakeWorkbookCM(FakeBook(sheet)).factory)
    dlg._preview()
    assert wait(qapp, lambda: dlg.table.rowCount() == 2)
    row = next(r for r in range(2) if dlg.table.item(r, 3).text().endswith("T8"))
    assert "5" in dlg.table.item(row, 5).text() and "ersetzt" in dlg.table.item(row, 5).text()
    assert "1 vorhandene Werte werden ersetzt" in dlg.status.text()


def test_warnings_are_listed_and_unwritable_items_do_not_enable_writing(qapp):
    svc = setup()
    svc.db.save_day(date(2026, 11, 1), [Entry(datetime(2026, 11, 1, 9), datetime(2026, 11, 1, 10),
                                              project_id=svc.projects()[0]["id"])])        # Sonntag
    dlg = ExcelExportDialog(svc, workbook_factory=FakeWorkbookCM(FakeBook(FakeSheet("November"))).factory)
    dlg.first.setDate(dlg.first.date().addDays(-1))
    dlg._preview()
    assert wait(qapp, lambda: dlg.table.rowCount() == 2)
    assert "Sonntag" in dlg.warnings.text()


def test_missing_month_sheet_is_a_warning_not_a_crash(qapp):
    svc = setup()
    dlg = ExcelExportDialog(svc, workbook_factory=FakeWorkbookCM(FakeBook(FakeSheet("Oktober"))).factory)
    dlg._preview()
    assert wait(qapp, lambda: "Kein Blatt" in dlg.warnings.text())
    assert not dlg.ok.isEnabled() and dlg.table.rowCount() == 0


def test_excel_errors_are_shown_and_nothing_breaks(qapp):
    svc = setup()
    cm = FakeWorkbookCM(FakeBook(FakeSheet("November")), error=ExcelError("Die Datei ist schreibgeschützt."))
    dlg = ExcelExportDialog(svc, workbook_factory=cm.factory)
    dlg._preview()
    assert wait(qapp, lambda: "schreibgeschützt" in dlg.status.text())
    assert not dlg.ok.isEnabled() and dlg.preview_btn.isEnabled()


def test_no_hours_in_range_says_so_without_opening_excel(qapp):
    svc = setup()
    FakeWorkbookCM.opened = []
    dlg = ExcelExportDialog(svc, workbook_factory=FakeWorkbookCM(FakeBook(FakeSheet("November"))).factory)
    dlg.first.setDate(dlg.first.date().addDays(-14))
    dlg.last.setDate(dlg.last.date().addDays(-10))
    dlg._preview()
    assert "keine Stunden gebucht" in dlg.status.text() and FakeWorkbookCM.opened == []


def test_second_write_changes_nothing_new(qapp):
    svc = setup()
    sheet = FakeSheet("November")
    cm = FakeWorkbookCM(FakeBook(sheet))
    for _ in range(2):
        dlg = ExcelExportDialog(svc, workbook_factory=cm.factory)
        dlg._preview()
        assert wait(qapp, lambda: dlg.ok.isEnabled())
        dlg._write()
        assert wait(qapp, lambda: "✓" in dlg.status.text())
    assert sheet.v[8, 20] == 3.0 and sheet.v[10, 20] == 1.5 and sheet.v[10, 1] == "Interne Doku"
    assert len([w for w in sheet.writes if w[:2] == (10, 1)]) == 1             # die Zeile wurde nur einmal angelegt


# --- Echtes Excel (nur auf Wunsch: WORKPLANNER_EXCEL_SAMPLE=<Pfad zu einer Muster-Datei>) --------------------

@pytest.mark.skipif(not os.environ.get("WORKPLANNER_EXCEL_SAMPLE"), reason="braucht Excel und eine Musterdatei")
def test_real_excel_roundtrip_on_a_copy(tmp_path):
    from workplanner.excel_timesheet import DayHours, ExcelWorkbook, apply_plan, plan_all
    copy = tmp_path / "kopie.xlsx"
    shutil.copy2(os.environ["WORKPLANNER_EXCEL_SAMPLE"], copy)
    items = [DayHours(date(2026, 11, 2), "E99999-01", "Neu", 1.5), DayHours(date(2026, 11, 4), "", "Interne Doku", 2.0)]
    with ExcelWorkbook(str(copy), save=True) as book:
        assert apply_plan(book, plan_all(book, items)) == 2
    with ExcelWorkbook(str(copy), save=False) as book:
        ws = book.sheet("November")._ws
        assert ws.Range("T10").Value2 == 1.5 and ws.Range("E10").Value2 == "E99999-01"
        assert ws.Range("A11").Value2 == "Interne Doku" and ws.Range("V11").Value2 == 2.0
        assert ws.ChartObjects().Count == 1
        del ws                                  # COM-Verweis vor dem Schließen freigeben, sonst läuft Excel nicht aus
