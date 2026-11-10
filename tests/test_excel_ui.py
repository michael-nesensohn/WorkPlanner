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


def test_service_stores_the_excel_profile_and_dialog_uses_it(qapp):
    from dataclasses import replace

    from workplanner.excel_timesheet import DEFAULT_PROFILE
    svc = TimeService(Database(":memory:"), Clock(8, 0))
    assert svc.excel_profile == DEFAULT_PROFILE                       # nichts gespeichert: Standardprofil
    prof = replace(DEFAULT_PROFILE, name="Meins", identify="both")
    svc.set_excel_profile(prof)
    assert svc.excel_profile == prof
    svc.db.set_setting("excel_profile", "kaputt")
    assert svc.excel_profile == DEFAULT_PROFILE                       # ungültig: sicherer Rückfall


# --- Assistent: Excel-Vorlage zuordnen ---------------------------------------------------------------

def _profile_dialog(qapp, tmp_path, sheet=None):
    from workplanner.ui.excel_profile_dialog import ExcelProfileDialog
    sheet = sheet or FakeSheet("November")
    svc = TimeService(Database(":memory:"), Clock(8, 0))
    svc.set_excel(str(tmp_path / "x.xlsx"), False)
    dlg = ExcelProfileDialog(svc, grid_loader=lambda path, name: sheet.grid(80, 60),
                             sheet_lister=lambda path: ["Oktober", "November"])
    return svc, dlg


def test_assistant_loads_sheet_and_tests_the_default_profile(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    assert dlg.sheets.currentText() == "November" and dlg.table.item(5, 4).text() == "Proj-Nr."
    dlg._test()
    assert "Vorlage erkannt" in dlg.result.text() and "Wochenblöcke" in dlg.result.text()
    assert dlg.table.item(7, 4).background().color().name() == "#e7effd"        # Nummernspalte eingefärbt (Blau halb über Weiß)


def test_assistant_picks_labels_by_clicking_cells_and_saves(qapp, tmp_path):
    sheet = FakeSheet("November")
    sheet.v[6, 1], sheet.v[6, 5] = "Auftrag", "Nr."
    svc, dlg = _profile_dialog(qapp, tmp_path, sheet)
    dlg._start_pick("header_name", True)
    dlg._cell_clicked(5, 0)                                                      # Zelle A6 = „Auftrag“
    dlg._start_pick("header_number", True)
    dlg._cell_clicked(5, 4)                                                      # E6 = „Nr.“
    assert (dlg.edits["header_name"].text(), dlg.edits["header_number"].text()) == ("Auftrag", "Nr.")
    assert not dlg.picks["header_name"].isChecked() and dlg._pick is None
    dlg._start_pick("header_name", True)
    dlg._cell_clicked(40, 40)                                                    # leere Zelle: nichts übernommen
    assert dlg.edits["header_name"].text() == "Auftrag" and "leer" in dlg.status.text()
    dlg.name.setText("Mein Profil")
    dlg.days.setCurrentIndex(dlg.days.findData(7))
    dlg._test()
    assert "Vorlage erkannt" in dlg.result.text() and "je 7 Tagen" in dlg.result.text()
    dlg._save()
    saved = svc.excel_profile
    assert (saved.name, saved.header_name, saved.header_number, saved.days_per_block) == ("Mein Profil", "Auftrag", "Nr.", 7)


def test_assistant_reports_unrecognised_template_and_invalid_input(qapp, tmp_path):
    sheet = FakeSheet("November")
    del sheet.v[49, 1]
    svc, dlg = _profile_dialog(qapp, tmp_path, sheet)
    dlg._test()
    assert "Nicht erkannt" in dlg.result.text() and "Tagestotal" in dlg.result.text()
    dlg.pattern.setText("Blatt")
    dlg._save()
    assert "Blattnamen-Muster" in dlg.status.text() and svc.excel_profile.name == DEFAULT_PROFILE_NAME


DEFAULT_PROFILE_NAME = "Standard (Monatsblätter, Wochenblöcke)"


def test_assistant_export_and_import_round_trip(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.name.setText("Für Kollegen")
    dlg.identify.setCurrentIndex(dlg.identify.findData("both"))
    path = str(tmp_path / "p.wpprofile.json")
    dlg.export_to(path)
    svc2, dlg2 = _profile_dialog(qapp, tmp_path)
    dlg2.import_from(path)
    assert dlg2.name.text() == "Für Kollegen" and dlg2.identify.currentData() == "both"
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    from workplanner.excel_timesheet import ProfileError
    with pytest.raises(ProfileError):
        dlg2.import_from(str(bad))


def test_number_header_is_ignored_in_name_only_mode(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.identify.setCurrentIndex(dlg.identify.findData("name"))
    assert not dlg.edits["header_number"].isEnabled()
    dlg.edits["header_number"].setText("")
    dlg._save()
    assert svc.excel_profile.identify == "name"


def test_assistant_shows_the_sheet_formatted_like_excel(qapp, tmp_path):
    from test_excel_timesheet import _styled_workbook
    from workplanner.ui.excel_profile_dialog import ExcelProfileDialog
    path = str(tmp_path / "s.xlsx")
    _styled_workbook(path)
    svc = TimeService(Database(":memory:"), Clock(8, 0))
    svc.set_excel(path, False)
    dlg = ExcelProfileDialog(svc)                                   # echter Lader (openpyxl)
    assert dlg.sheets.currentText() == "November"
    item = dlg.table.item(0, 0)
    assert item.text() == "Titel" and item.background().color().name() == "#2f5597"
    assert item.foreground().color().name() == "#ff0000" and item.font().bold() and item.font().italic()
    assert dlg.table.columnWidth(0) == 215 and dlg.table.columnWidth(1) == 0 and dlg.table.rowHeight(1) == 40
    assert dlg.table.columnSpan(2, 0) == 3
    assert dlg.table.item(0, 2).text() == "02.11.2026"


def test_assistant_keeps_the_right_side_width_when_resized(qapp, tmp_path):
    from workplanner.ui.excel_profile_dialog import SIDE_WIDTH
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.show()
    widths = []
    for w in (1100, 1700):
        dlg.resize(w, 700)
        qapp.processEvents()
        widths.append((dlg.side.width(), dlg.table.width()))
    assert widths[0][0] == widths[1][0] == SIDE_WIDTH and widths[1][1] > widths[0][1] + 400
    assert dlg.name.width() <= SIDE_WIDTH


def test_assistant_shows_where_each_label_is_found(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    assert dlg.locate("section_start") == "Zeile 7" and dlg.locate("section_next") == "Zeile 29"
    assert dlg.locate("section_total") == "Zeile 49" and dlg.locate("header_number") == "Spalte E (Zeile 6)"
    assert dlg.locate("weekday_label") == "Spalte F (Zeile 5)"
    assert "Zeile 7" in dlg.field_labels["section_start"].text()
    dlg.edits["section_next"].setText("Ferien")                        # gibt es in dieser Vorlage nicht
    assert dlg.locate("section_next") == "nicht gefunden" and "nicht gefunden" in dlg.field_labels["section_next"].text()
    dlg.edits["section_next"].setText("")
    assert dlg.field_labels["section_next"].text() == "Hier dürfen keine neuen Projekte mehr angelegt werden"


def test_assistant_section_fields_can_use_a_fixed_row_and_a_click_in_any_column(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.modes["section_start"].setCurrentIndex(1)                         # Text → Zeile: Wert wird mitgenommen
    assert dlg.edits["section_start"].text() == "7"
    assert "Zeile 7: „Projekt verrechenbar" in dlg.field_labels["section_start"].text()
    dlg.modes["section_next"].setCurrentIndex(1)
    dlg._start_pick("section_next", True)
    dlg._cell_clicked(28, 9)                                              # Zeile 29, beliebige Spalte (J)
    assert dlg.edits["section_next"].text() == "29" and dlg._pick is None
    dlg._test()
    assert "Vorlage erkannt" in dlg.result.text()
    dlg._save()
    saved = svc.excel_profile
    assert (saved.section_start_row, saved.section_next_row, saved.section_total_row) == (7, 29, 0)
    assert saved.section_total == "Tagestotal"                           # Summenzeile weiter per Text
    dlg2 = type(dlg)(svc, grid_loader=lambda p, n: FakeSheet("November").grid(80, 60), sheet_lister=lambda p: ["November"])
    assert dlg2.modes["section_start"].currentData() == "row" and dlg2.edits["section_start"].text() == "7"
    assert dlg2.modes["section_total"].currentData() == "text"
    dlg2.modes["section_start"].setCurrentIndex(0)                       # zurück: Text aus der Zeile
    assert dlg2.edits["section_start"].text().startswith("Projekt verrechenbar")


def test_assistant_rejects_a_non_numeric_fixed_row(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.modes["section_total"].setCurrentIndex(1)
    dlg.edits["section_total"].setText("abc")
    dlg._save()
    from workplanner.excel_timesheet import DEFAULT_PROFILE
    assert "Zeilennummer" in dlg.status.text() and svc.excel_profile == DEFAULT_PROFILE


def test_assistant_show_button_marks_what_a_field_means(qapp, tmp_path):
    from workplanner.ui.excel_profile_dialog import MARK
    svc, dlg = _profile_dialog(qapp, tmp_path)
    mark = MARK.name()
    bg = lambda r, c: dlg.table.item(r - 1, c - 1) and dlg.table.item(r - 1, c - 1).background().color().name()  # noqa: E731

    dlg._show_field("header_name")                                     # Spalte A von der Überschrift bis zu den Projekten
    assert bg(6, 1) == mark and bg(8, 1) == mark and bg(40, 1) == mark and bg(8, 2) != mark
    assert "Orange markiert" in dlg.status.text()

    dlg._show_field("section_start")                                   # ganze Zeile 7, die Spaltenmarkierung ist weg
    assert bg(7, 1) == mark and bg(7, 40) == mark and bg(8, 1) != mark

    dlg._show_field("section_start")                                   # zweiter Klick: Markierung weg
    assert bg(7, 1) != mark and dlg._marks == {}

    dlg._show_field("weekday_label")                                   # alle Wochenblöcke samt Kalenderwoche darüber
    assert bg(5, 6) == mark and bg(4, 6) == mark and bg(5, 13) == mark and bg(5, 7) != mark

    dlg._show_field("section_total")
    dlg.edits["section_total"].setText("Gibt es nicht")                 # Text ändern: Markierung verschwindet
    assert dlg._marks == {}
    dlg._show_field("section_total")
    assert "nicht gefunden" in dlg.status.text() and dlg._marks == {}

    dlg.modes["section_next"].setCurrentIndex(1)                       # auch bei fester Zeile
    dlg._show_field("section_next")
    assert bg(29, 5) == mark


def test_assistant_window_can_be_maximised_but_not_minimised(qapp, tmp_path):
    from PySide6.QtCore import Qt
    svc, dlg = _profile_dialog(qapp, tmp_path)
    flags = dlg.windowFlags()
    assert flags & Qt.WindowMaximizeButtonHint and flags & Qt.WindowCloseButtonHint
    assert not flags & Qt.WindowMinimizeButtonHint


def test_show_button_is_highlighted_only_while_its_marking_is_active(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    checked = lambda: [k for k, b in dlg.shows.items() if b.isChecked()]   # noqa: E731
    assert checked() == []
    dlg.shows["header_name"].click()
    assert checked() == ["header_name"] and dlg._marked_key == "header_name"
    dlg.shows["section_start"].click()                                   # anderes Feld: nur noch dieser Knopf ist orange
    assert checked() == ["section_start"]
    dlg.shows["section_start"].click()                                   # nochmal: Markierung und Farbe weg
    assert checked() == [] and dlg._marks == {}
    dlg.shows["section_total"].click()
    dlg.edits["section_total"].setText("Gibt es nicht")                  # Text geändert: Markierung weg, Knopf nicht mehr orange
    assert checked() == []
    dlg.shows["section_total"].click()                                   # nicht gefunden: Knopf darf nicht orange bleiben
    assert checked() == [] and "nicht gefunden" in dlg.status.text()
    dlg.shows["header_number"].click()
    dlg._load()                                                          # neu laden setzt alles zurück
    assert checked() == []


def test_assistant_labels_use_the_full_width_and_are_not_clipped(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    dlg.show()
    qapp.processEvents()
    for key, lab in dlg.field_labels.items():
        assert lab.width() >= dlg.edits[key].width() - 1, key              # Beschriftung so breit wie das Feld
        assert lab.height() >= lab.heightForWidth(lab.width()), key       # kein abgeschnittener Text


def test_test_button_is_active_while_the_detection_colours_are_shown(qapp, tmp_path):
    svc, dlg = _profile_dialog(qapp, tmp_path)
    tinted = lambda: dlg.table.item(7, 4).background().color().name() == "#e7effd"   # noqa: E731
    assert not dlg.test_btn.isChecked()
    dlg.test_btn.click()                                                # Testen: Farben an, Knopf aktiv
    assert dlg.test_btn.isChecked() and tinted() and "Vorlage erkannt" in dlg.result.text()
    dlg.test_btn.click()                                                # nochmal: Farben und Ergebnis weg
    assert not dlg.test_btn.isChecked() and not tinted() and dlg.result.text() == ""
    dlg.test_btn.click()
    assert tinted()
    dlg.edits["section_total"].setText("Tagestotal ")                  # etwas ändern: Einfärbung veraltet, also weg
    assert not dlg.test_btn.isChecked() and not tinted() and dlg.result.text() == ""
    dlg.test_btn.click()
    dlg.days.setCurrentIndex(2)
    assert not dlg.test_btn.isChecked() and dlg._layout is None
    dlg.edits["header_number"].setText("")                              # Fehler beim Testen: Knopf bleibt aus
    dlg.test_btn.click()
    assert not dlg.test_btn.isChecked() and "darf nicht leer sein" in dlg.status.text()
