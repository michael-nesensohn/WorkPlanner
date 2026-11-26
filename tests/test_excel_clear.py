"""„Vorher löschen und neu eintragen“: Zellen samt Notizen leeren, dann eintragen; Merker zurücksetzen."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_excel_timesheet import FakeBook, FakeSheet
from test_excel_ui import FakeWorkbookCM, setup, wait
from workplanner.db import Database
from workplanner.excel_timesheet import (CLEAR_ALL, CLEAR_MARKED, ClearedWorkbook, DayHours, apply_clear, plan_all,
                                         plan_clear)
from workplanner.ui.excel_dialog import ExcelExportDialog

DAY = date(2026, 11, 2)
NUMBER, NAME = "E24005-20", "X1 - Farbvarianten"      # Zeile 8 der Vorlage-Attrappe; Montag 02.11. = Spalte T (20)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


class NoteSheet(FakeSheet):
    """Attrappe mit Zellnotizen (wie ComSheet)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.notes: dict[tuple[int, int], str] = {}

    def note(self, row, col):
        return self.notes.get((row, col), "")

    def set_note(self, row, col, text):
        if text:
            self.notes[row, col] = text
        else:
            self.notes.pop((row, col), None)


def marked(day=DAY, number=NUMBER, name=NAME):
    return DayHours(day, number, name, 0.0)


def test_marked_scope_finds_only_cells_with_value_or_note():
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 3.0
    sheet.notes[9, 20] = "nur Notiz"                                            # Zeile 9: kein Wert, aber eine Notiz
    book = FakeBook(sheet)
    clears = plan_clear(book, CLEAR_MARKED, [marked(), marked(number="E22157-12-001", name="Invest C1 Linienoptimierung"),
                                             marked(number="E-gibt-es-nicht", name="Unbekannt")], DAY, DAY)
    assert [(c.row, c.col, c.old, c.old_note) for c in clears] == [(8, 20, 3.0, ""), (9, 20, None, "nur Notiz")]


def test_marked_scope_ignores_other_cells_and_days():
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 3.0
    sheet.v[8, 21] = 4.0                                                        # Dienstag: nicht markiert
    clears = plan_clear(FakeBook(sheet), CLEAR_MARKED, [marked()], DAY, DAY)
    assert [(c.row, c.col) for c in clears] == [(8, 20)]
    assert plan_clear(FakeBook(sheet), CLEAR_MARKED, [], DAY, DAY) == []


def test_all_scope_clears_every_hour_cell_of_the_period_but_no_formulas_or_totals():
    sheet = NoteSheet("November", formulas={(10, 20): "=SUMME(A1)"})
    sheet.v[8, 20] = 3.0                                                        # Mo 02.11.
    sheet.v[9, 20] = 1.5
    sheet.v[10, 20] = 5.0                                                       # Formel: nie anfassen
    sheet.v[9, 21] = 2.0                                                        # Di 03.11.: außerhalb des Zeitraums
    sheet.v[8, 17] = 10.0                                                       # Fr 30.10.: außerhalb
    sheet.v[49, 20] = 99.0                                                      # Tagestotal-Zeile: nie anfassen
    sheet.notes[11, 20] = "Notiz ohne Wert"
    clears = plan_clear(FakeBook(sheet), CLEAR_ALL, [], DAY, DAY)
    assert sorted((c.row, c.col) for c in clears) == [(8, 20), (9, 20), (11, 20)]


def test_apply_clear_empties_values_and_notes_and_counts_them():
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 3.0
    sheet.notes[8, 20] = "alt"
    sheet.notes[9, 20] = "nur Notiz"
    book = FakeBook(sheet)
    clears = plan_clear(book, CLEAR_MARKED, [marked(), marked(number="E22157-12-001", name="Invest C1 Linienoptimierung")],
                        DAY, DAY)
    assert apply_clear(book, clears) == (1, 2)
    assert sheet.v[8, 20] is None and sheet.notes == {}


def test_planning_after_clearing_sees_the_cells_as_empty_so_nothing_conflicts():
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 5.0
    sheet.notes[8, 20] = "Excel-Notiz"
    book = FakeBook(sheet)
    item = DayHours(DAY, NUMBER, NAME, 3.0, note="neu")
    before = plan_all(book, [item]).lines[0]
    assert before.overwrites and before.note_action == "ersetzt"
    clears = plan_clear(book, CLEAR_MARKED, [marked()], DAY, DAY)
    after = plan_all(ClearedWorkbook(book, clears), [item]).lines[0]
    assert not after.overwrites and after.old is None and after.note_action == "neu"
    assert sheet.v[8, 20] == 5.0                                                # die Planung ändert nichts an der Datei


def test_marks_remember_project_for_later_clearing_and_old_marks_fall_back_to_the_key():
    db = Database()
    db.mark_excel_exported("f.xlsx", [("2026-11-02", "nr|e24005-20", 3.0, NUMBER, NAME),
                                      ("2026-11-03", "nr|e1", 1.0), ("2026-11-04", "name|interne doku", 2.0)])
    got = db.excel_exported_projects("f.xlsx", "2026-11-01", "2026-11-30")
    assert got == [("2026-11-02", NUMBER, NAME), ("2026-11-03", "e1", ""), ("2026-11-04", "", "interne doku")]


# --- Dialog ---------------------------------------------------------------------------------------

def make_dialog(svc, sheet):
    cm = FakeWorkbookCM(FakeBook(sheet))
    FakeWorkbookCM.opened = []
    return ExcelExportDialog(svc, workbook_factory=cm.factory)


def test_dialog_clears_marked_cells_first_then_writes_and_resets_marks(qapp, monkeypatch):
    svc = setup()
    svc.mark_excel_exported([(DAY, f"nr|{NUMBER.casefold()}", 99.0, NUMBER, NAME)])    # früher eingetragen
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 99.0
    sheet.notes[8, 20] = "alte Notiz"
    dlg = make_dialog(svc, sheet)
    dlg.clear_cb.setChecked(True)
    assert dlg.clear_scope.isEnabled() and not dlg.ok.isEnabled()                       # erst die Vorschau drücken
    dlg._preview()
    assert wait(qapp, lambda: dlg.ok.isEnabled())
    assert len(dlg._plan.clears) == 1 and "1 Zelle(n) löschen" in dlg.ok.text()
    assert "1 Notiz" in dlg.clear_info.text()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    dlg._write()
    assert wait(qapp, lambda: "✓" in dlg.status.text())
    assert asked and "1 Zelle(n) und 1 Notiz(en)" in asked[0] and "KEINE Sicherung" in asked[0]
    assert sheet.v[8, 20] == 3.0 and sheet.notes == {}                                   # gelöscht, dann neu (ohne Notiz)
    assert "Vorher gelöscht: 1 Zelle(n), 1 Notiz(en)" in dlg.status.text()
    marks = svc.excel_exported(DAY, DAY)
    assert marks[(DAY.isoformat(), f"nr|{NUMBER.casefold()}")] == 3.0                    # Merker neu gesetzt


def test_dialog_cancelling_the_question_changes_nothing(qapp, monkeypatch):
    svc = setup()
    svc.mark_excel_exported([(DAY, f"nr|{NUMBER.casefold()}", 99.0, NUMBER, NAME)])
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 99.0
    dlg = make_dialog(svc, sheet)
    dlg.clear_cb.setChecked(True)
    dlg._preview()
    assert wait(qapp, lambda: dlg.ok.isEnabled())
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    dlg._write()
    qapp.processEvents()
    assert sheet.v[8, 20] == 99.0 and svc.excel_exported(DAY, DAY) == {(DAY.isoformat(), f"nr|{NUMBER.casefold()}"): 99.0}


def test_clearing_also_rewrites_days_that_were_marked_as_done(qapp, monkeypatch):
    svc = setup()
    svc.mark_excel_exported([(DAY, f"nr|{NUMBER.casefold()}", 3.0, NUMBER, NAME)])   # gleiche Stunden: sonst übersprungen
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 3.0
    dlg = make_dialog(svc, sheet)
    dlg.clear_cb.setChecked(True)
    assert not dlg.skip_done.isEnabled()
    dlg._preview()
    assert wait(qapp, lambda: dlg.ok.isEnabled())
    assert dlg.table.rowCount() == 2 and len(dlg._plan.clears) == 1                      # nichts übersprungen


def test_without_the_checkbox_nothing_is_cleared(qapp):
    svc = setup()
    sheet = NoteSheet("November")
    sheet.v[8, 20] = 99.0
    dlg = make_dialog(svc, sheet)
    dlg._preview()
    assert wait(qapp, lambda: dlg.ok.isEnabled())
    assert dlg._plan.clears == [] and not dlg.clear_scope.isEnabled()
