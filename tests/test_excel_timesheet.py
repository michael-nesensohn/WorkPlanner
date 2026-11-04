from datetime import date, timedelta

import pytest

from workplanner.excel_timesheet import (DayHours, ExcelError, MONTH_NAMES, aggregate, apply_plan, detect_layout,
                                         plan_all, plan_month)

BLOCKS = [6, 13, 20, 27, 34, 41]          # F, M, T, AA, AH, AO


class FakeSheet:
    """Bildet die Struktur der Vorlage nach (Kopf, Wochenblöcke, Projektblock, Tagestotal)."""

    def __init__(self, name="November", kw0=43, billable_rows=range(8, 29), formulas=None):
        self.name = name
        self.v: dict[tuple[int, int], object] = {}
        self.formulas = dict(formulas or {})
        self.writes: list[tuple[int, int, object]] = []
        for i, c0 in enumerate(BLOCKS):
            self.v[4, c0] = kw0 + i
            for k, label in enumerate(["Mo", "Di", "Mi", "Do", "Fr", "Sa"]):
                self.v[5, c0 + k] = label
        for c, t in enumerate(["Projekt", "PG", "Projektmanger", "Verr. / Akt.", "Proj-Nr."], 1):
            self.v[6, c] = t
        self.v[7, 1] = "Projekt verrechenbar / aktivierbar"
        for r in billable_rows:
            self.v[r, 4], self.v[r, 5], self.v[r, 1] = "Ja", 0.0, ""          # freie Zeile: Nr. = 0 (Formel), Name leer
        self.v[8, 1], self.v[8, 5] = "X1 - Farbvarianten", "E24005-20"
        self.v[9, 1], self.v[9, 5] = "Invest C1 Linienoptimierung", "E22157-12-001"
        self.v[8, 17] = 10.0                                                    # Q8: Freitag KW 44 (30.10.) = 10 h
        self.v[29, 1] = "Projekte nicht verrechenbar"
        for r in range(30, 34):
            self.v[r, 4], self.v[r, 5], self.v[r, 1] = "Nein", 0.0, ""
        self.v[35, 1], self.v[35, 5] = "Support Account Management", "E_Supp_AM"
        self.v[49, 1] = "Tagestotal"

    def grid(self, rows, cols):
        return [[self.v.get((r, c)) for c in range(1, cols + 1)] for r in range(1, rows + 1)]

    def formula(self, row, col):
        return self.formulas.get((row, col), "")

    def set_value(self, row, col, value):
        self.v[row, col] = value
        self.writes.append((row, col, value))


class FakeBook:
    def __init__(self, *sheets):
        self.sheets = {s.name: s for s in sheets}

    def sheet_names(self):
        return list(self.sheets)

    def sheet(self, name):
        return self.sheets[name]


def hours(day, hrs, nr="", name="Projekt"):
    return DayHours(day, nr, name, hrs)


# --- Layout -----------------------------------------------------------------------------------

def test_layout_maps_dates_to_columns_via_calendar_week():
    lay = detect_layout(FakeSheet().grid(80, 60), 11, 2026)
    assert (lay.col_name, lay.col_nr) == (1, 5)
    assert (lay.row_first, lay.row_last_billable, lay.row_scan_end) == (8, 28, 48)
    assert lay.first_monday == date(2026, 10, 19)
    assert lay.column_for(date(2026, 11, 2)) == 20          # Mo KW 45 = Spalte T
    assert lay.column_for(date(2026, 11, 3)) == 21
    assert lay.column_for(date(2026, 11, 28)) == 46         # Sa KW 48 = Spalte AT
    assert lay.column_for(date(2026, 10, 30)) == 17         # Fr KW 44 = Spalte Q (Vormonat im Novemberblatt)
    assert lay.column_for(date(2026, 11, 29)) is None       # Sonntag
    assert lay.column_for(date(2026, 11, 30)) is None       # KW 49 hat in diesem Blatt keinen Block


def test_layout_handles_year_boundary_in_january():
    sheet = FakeSheet("Januar", kw0=52)
    for i, c0 in enumerate(BLOCKS[1:], 1):                    # wie in der Vorlage: zweiter Block ist KW 1, dann 2, 3 ...
        sheet.v[4, c0] = i
    lay = detect_layout(sheet.grid(80, 60), 1, 2026)
    assert lay.first_monday == date(2025, 12, 22)               # KW 52 gehört zu 2025
    assert lay.column_for(date(2026, 1, 1)) == 13 + 3           # Do 01.01.2026 = zweiter Block (KW 1), Spalte P
    assert lay.column_for(date(2026, 1, 31)) == 41 + 5          # Sa 31.01.2026 = letzter Block, Spalte AT


def test_layout_errors_are_readable():
    sheet = FakeSheet()
    del sheet.v[6, 5]
    with pytest.raises(ExcelError, match="Proj-Nr"):
        detect_layout(sheet.grid(80, 60), 11, 2026)
    sheet = FakeSheet()
    sheet.v[29, 1] = "Sonstiges"
    with pytest.raises(ExcelError, match="Abschnitte"):
        detect_layout(sheet.grid(80, 60), 11, 2026)
    with pytest.raises(ExcelError, match="passt nicht"):
        detect_layout(FakeSheet(kw0=10).grid(80, 60), 11, 2026)


# --- Aggregation ------------------------------------------------------------------------------

def row(day, project, number, secs, kind="work"):
    return {"date": day, "project": project, "project_number": number, "kind": kind,
            "duration": timedelta(seconds=secs)}


def test_aggregate_sums_per_project_and_day_and_ignores_pauses():
    d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
    rows = [row(d1, "A", "E1", 3600), row(d1, "A", "E1", 5400), row(d1, "Pause", "", 1800, "pause"),
            row(d1, "B", "", 1800), row(d2, "A", "E1", 600), row(d1, "Null", "", 0)]
    got = aggregate(rows)
    assert [(h.day, h.label, h.hours) for h in got] == [(d1, "B", 0.5), (d1, "E1  A", 2.5), (d2, "E1  A", 0.17)]


def test_aggregate_keeps_numbered_and_unnumbered_projects_with_same_name_apart():
    d = date(2026, 11, 2)
    got = aggregate([row(d, "Waage", "E5", 3600), row(d, "Waage", "", 1800), row(d, "waage", "", 1800)])
    assert sorted((h.number, h.hours) for h in got) == [("", 1.0), ("E5", 1.0)]


# --- Planen -------------------------------------------------------------------------------------

D = date(2026, 11, 2)                                          # Montag KW 45 -> Spalte T (20)


def test_existing_project_number_only_gets_hours():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 7.5, "E24005-20", "X1 - Farbvarianten")])
    (line,) = plan.lines
    assert (line.row, line.col, line.address, line.action, line.new_row) == (8, 20, "T8", "vorhanden", False)
    assert plan.setups == [] and line.hours == 7.5 and line.old is None and not line.overwrites


def test_number_matching_ignores_case_and_surrounding_spaces():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 1, " e24005-20 ", "egal")])
    assert plan.lines[0].row == 8 and plan.setups == []


def test_new_numbered_project_gets_its_number_in_the_first_free_row():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 2.0, "E99999-01", "Neues Projekt")])
    (setup,) = plan.setups
    assert (setup.row, setup.col, setup.value) == (10, 5, "E99999-01")      # nur die Nummer, Name/PG kommen per Formel
    (line,) = plan.lines
    assert (line.row, line.action, line.new_row) == (10, "neue Zeile (Nr.)", True)


def test_project_without_number_gets_its_name_in_the_name_column():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 3.0, "", "Interne Doku")])
    (setup,) = plan.setups
    assert (setup.row, setup.col, setup.value) == (10, 1, "Interne Doku")   # Spalte „Projekt“, Block verrechenbar
    assert plan.lines[0].action == "neue Zeile (Name)"


def test_project_without_number_reuses_a_row_with_the_same_name():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 1.0, "", "X1 - Farbvarianten")])
    assert plan.lines[0].row == 8 and plan.setups == []


def test_several_projects_take_consecutive_free_rows_and_share_rows_per_day():
    d2 = date(2026, 11, 3)
    items = [hours(D, 1, "E99999-01", "N1"), hours(D, 2, "", "Ohne Nr"), hours(d2, 3, "E99999-01", "N1"),
             hours(D, 4, "E22157-12-001", "Invest")]
    plan = plan_month(FakeSheet(), 11, 2026, items)
    assert [(s.row, s.col, s.value) for s in plan.setups] == [(10, 5, "E99999-01"), (11, 1, "Ohne Nr")]
    assert [(ln.row, ln.col, ln.hours) for ln in plan.lines] == [(10, 20, 1), (11, 20, 2), (10, 21, 3), (9, 20, 4)]


def test_row_with_hours_but_no_name_is_not_considered_free():
    sheet = FakeSheet()
    sheet.v[10, 22] = 5.0                                                    # Stunden ohne Projekt in Zeile 10
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E1", "x")])
    assert plan.setups[0].row == 11


def test_existing_value_is_reported_as_overwrite():
    friday = date(2026, 10, 30)                                              # Q8 enthält schon 10
    plan = plan_month(FakeSheet(), 11, 2026, [hours(friday, 8.5, "E24005-20", "X1")])
    (line,) = plan.lines
    assert (line.address, line.old, line.overwrites) == ("Q8", 10.0, True)
    same = plan_month(FakeSheet(), 11, 2026, [hours(friday, 10.0, "E24005-20", "X1")])
    assert same.lines[0].overwrites is False                                 # gleicher Wert: nichts zu ersetzen


def test_sunday_and_days_outside_the_sheet_are_skipped_with_a_warning():
    items = [hours(date(2026, 11, 1), 1, "E24005-20", "x"), hours(date(2026, 11, 30), 2, "E24005-20", "x"),
             hours(D, 3, "E24005-20", "x")]
    plan = plan_month(FakeSheet(), 11, 2026, items)
    assert [ln.hours for ln in plan.lines] == [3]
    assert any("Sonntag" in w for w in plan.warnings) and any("nicht in den Wochenblöcken" in w for w in plan.warnings)


def test_cells_with_formulas_are_never_overwritten():
    sheet = FakeSheet(formulas={(8, 20): "=SUMME(X1:X5)"})
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E24005-20", "x"), hours(date(2026, 11, 3), 2, "E24005-20", "x")])
    assert [ln.address for ln in plan.lines] == ["U8"] and any("Formel" in w for w in plan.warnings)


def test_full_block_gives_a_warning_and_writes_nothing_for_that_project():
    sheet = FakeSheet(billable_rows=range(8, 10))                            # Block nur Zeile 8 und 9, beide belegt
    del sheet.v[29, 1]
    sheet.v[10, 1] = "Projekte nicht verrechenbar"                           # der nächste Abschnitt beginnt in Zeile 10
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E1", "Neu"), hours(D, 2, "E24005-20", "X1")])
    assert [ln.row for ln in plan.lines] == [8]
    assert any("Kein freier Platz" in w and "Neu" in w for w in plan.warnings)
    assert plan.setups == []


# --- Mehrere Monate / Arbeitsmappe ---------------------------------------------------------------------

def test_items_are_distributed_to_the_sheet_of_their_month():
    nov = FakeSheet("November")
    dec = FakeSheet("Dezember ", kw0=48)                                       # Blattname mit Leerzeichen wie in der Vorlage
    book = FakeBook(nov, dec)
    items = [hours(date(2026, 11, 3), 1, "E24005-20", "x"), hours(date(2026, 12, 8), 2, "E24005-20", "x"),
             hours(date(2026, 9, 7), 3, "E24005-20", "x")]
    plan = plan_all(book, items)
    assert sorted((ln.sheet, ln.day.month) for ln in plan.lines) == [("Dezember ", 12), ("November", 11)]
    assert any("Kein Blatt „September“" in w for w in plan.warnings)


def test_apply_writes_setups_before_hours_and_counts_cells():
    sheet = FakeSheet()
    book = FakeBook(sheet)
    plan = plan_all(book, [hours(D, 2.5, "E99999-01", "Neu"), hours(date(2026, 11, 3), 1.25, "E99999-01", "Neu")])
    assert apply_plan(book, plan) == 2
    assert sheet.writes == [(10, 5, "E99999-01"), (10, 20, 2.5), (10, 21, 1.25)]


def test_a_second_run_finds_the_rows_it_created_and_only_writes_hours():
    sheet = FakeSheet()
    book = FakeBook(sheet)
    items = [hours(D, 2.0, "E99999-01", "Neu"), hours(D, 1.0, "", "Interne Doku")]
    apply_plan(book, plan_all(book, items))
    again = plan_all(book, items)
    assert again.setups == [] and [ln.action for ln in again.lines] == ["vorhanden", "vorhanden"]
    assert [ln.overwrites for ln in again.lines] == [False, False]             # gleicher Stand: idempotent


def test_month_names_cover_all_twelve_sheets():
    assert len(MONTH_NAMES) == 12 and MONTH_NAMES[2] == "März"
