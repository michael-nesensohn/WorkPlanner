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


# --- Profile: andere Vorlagen, Nummer/Name, Export/Import -------------------------------------------------

from dataclasses import replace  # noqa: E402

from workplanner.excel_timesheet import (DEFAULT_PROFILE, ExcelProfile, ProfileError, load_profile,  # noqa: E402
                                         profile_from_json, profile_to_json, save_profile)


def test_default_profile_is_the_built_in_standard_and_valid():
    assert DEFAULT_PROFILE.validate() is DEFAULT_PROFILE
    assert DEFAULT_PROFILE.sheet_name_for(11, 2026) == "November"


def test_existing_number_is_found_in_the_number_column_with_odd_formatting():
    sheet = FakeSheet()
    sheet.v[12, 5] = 12345.0                                                 # Nummer als Zahl in Excel
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "12345", "x")])
    assert plan.lines[0].row == 12 and plan.setups == []


def test_existing_number_is_found_inside_the_name_column_text():
    sheet = FakeSheet()
    sheet.v[12, 1] = "E77777-01 Wartung Linie 3"                             # Nummer steht nur im Namenstext
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E77777-01", "Wartung")])
    assert plan.lines[0].row == 12 and plan.lines[0].action == "vorhanden" and plan.setups == []


def test_number_in_name_text_does_not_match_a_longer_number():
    sheet = FakeSheet()
    sheet.v[12, 1] = "E77777-012 anderes Projekt"
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E77777-01", "Wartung")])
    assert plan.lines[0].action.startswith("neue Zeile")


BOTH = replace(DEFAULT_PROFILE, name="Nr + Name", identify="both")


def test_both_mode_writes_number_and_name_into_their_columns():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(D, 2, "E99999-01", "Neues Projekt")], BOTH)
    assert [(s.row, s.col, s.value) for s in plan.setups] == [(10, 5, "E99999-01"), (10, 1, "Neues Projekt")]
    assert plan.lines[0].action == "neue Zeile (Nr. + Name)"


def test_both_mode_is_idempotent_and_finds_a_row_by_name_when_number_is_missing():
    sheet = FakeSheet()
    book = FakeBook(sheet)
    items = [hours(D, 2, "E99999-01", "Neu"), hours(D, 1, "", "Intern")]
    apply_plan(book, plan_all(book, items, BOTH))
    again = plan_all(book, items, BOTH)
    assert again.setups == [] and [ln.action for ln in again.lines] == ["vorhanden", "vorhanden"]
    named = plan_month(FakeSheet(), 11, 2026, [hours(D, 1, "E1", "X1 - Farbvarianten")], BOTH)   # Zeile 8 hat andere Nr.
    assert named.lines[0].row == 8 and named.setups == []


NAME_ONLY = replace(DEFAULT_PROFILE, name="Nur Name", identify="name")


def test_name_mode_needs_no_number_column_and_always_uses_the_name():
    sheet = FakeSheet()
    for r in range(6, 29):
        sheet.v.pop((r, 5), None)                                           # keine Spalte „Proj-Nr.“ in dieser Vorlage
    items = [hours(D, 2, "E5", "Waage"), hours(date(2026, 11, 3), 1, "", "waage"), hours(D, 3, "", "X1 - Farbvarianten")]
    plan = plan_month(sheet, 11, 2026, items, NAME_ONLY)
    assert [(s.row, s.col, s.value) for s in plan.setups] == [(10, 1, "Waage")]
    assert len(plan.setups) == 1                                            # Nummer und Name des gleichen Projekts = eine Zeile
    assert {ln.row for ln in plan.lines if ln.project.endswith("Waage")} == {plan.setups[0].row}
    assert any(ln.row == 8 and ln.action == "vorhanden" for ln in plan.lines)


def test_profile_with_other_headers_sections_and_sheet_pattern():
    sheet = FakeSheet("2026-11")
    sheet.v[6, 1], sheet.v[6, 5] = "Auftrag", "Nr."
    sheet.v[7, 1], sheet.v[29, 1], sheet.v[49, 1] = "Verrechenbar", "Intern", "Summe"
    prof = replace(DEFAULT_PROFILE, sheet_pattern="{jahr}-{MM}", header_number="Nr.", header_name="Auftrag",
                   section_start="Verrechenbar", section_next="Intern", section_total="Summe")
    plan = plan_all(FakeBook(sheet), [hours(D, 1, "E24005-20", "x")], prof)
    assert plan.lines[0].row == 8 and plan.lines[0].sheet == "2026-11"
    with pytest.raises(ExcelError, match="Auftrag|Nr"):
        detect_layout(FakeSheet().grid(80, 60), 11, 2026, prof)


def test_profile_json_round_trip_and_file(tmp_path):
    prof = replace(BOTH, sheet_pattern="{jahr}-{MM}", header_number="Nr")
    assert profile_from_json(profile_to_json(prof)) == prof
    path = tmp_path / "p.json"
    save_profile(prof, str(path))
    assert load_profile(str(path)) == prof
    assert "Pfad" not in path.read_text(encoding="utf-8")


def test_profile_import_rejects_bad_files_with_readable_messages():
    import json
    good = json.loads(profile_to_json(DEFAULT_PROFILE))
    for bad, text in [("kein JSON", "{x"), ("falsches Format", json.dumps({**good, "format": "x"})),
                      ("Version", json.dumps({**good, "version": 2})), ("Zuordnung", json.dumps({**good, "identify": "?"})),
                      ("leer", json.dumps({**good, "header_name": " "})), ("Muster", json.dumps({**good, "sheet_pattern": "Blatt"})),
                      ("Typ", json.dumps({**good, "identify": 5}))]:
        with pytest.raises(ProfileError):
            profile_from_json(text)
    assert profile_from_json(json.dumps({**good, "zukunft": 1})) == DEFAULT_PROFILE   # unbekannte Felder egal


# --- Tage in Spalten: Mo–Sa oder Mo–So ---------------------------------------------------------------

SEVEN = replace(DEFAULT_PROFILE, name="Mo-So", days_per_block=7)


def seven_day_sheet():
    """Wochenblöcke mit 7 Spalten (Mo … So): Blockstart alle 8 Spalten."""
    sheet = FakeSheet()
    starts = [6 + 8 * i for i in range(6)]
    sheet.v = {k: v for k, v in sheet.v.items() if k[0] not in (4, 5)}          # Kopf der 6-Tage-Blöcke entfernen
    for i, c0 in enumerate(starts):
        sheet.v[4, c0] = 43 + i
        for k, label in enumerate(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]):
            sheet.v[5, c0 + k] = label
    return sheet, starts


def test_seven_day_blocks_give_sunday_a_column():
    sheet, starts = seven_day_sheet()
    lay = detect_layout(sheet.grid(80, 60), 11, 2026, SEVEN)
    assert lay.days == 7 and len(lay.day_cols) == 7 * len(starts)
    sunday = lay.column_for(date(2026, 11, 1))                       # So KW 44 = 7. Spalte des zweiten Blocks
    assert sunday == starts[1] + 6
    assert lay.column_for(date(2026, 11, 2)) == starts[2]            # Mo KW 45 = Blockanfang
    plan = plan_month(sheet, 11, 2026, [hours(date(2026, 11, 1), 2, "E24005-20", "x")], SEVEN)
    assert plan.lines[0].col == sunday and not plan.warnings


def test_six_day_profile_still_skips_sunday_with_a_warning():
    plan = plan_month(FakeSheet(), 11, 2026, [hours(date(2026, 11, 1), 2, "E24005-20", "x")])
    assert plan.lines == [] and any("Sonntag" in w for w in plan.warnings)


def test_days_per_block_must_be_six_or_seven():
    with pytest.raises(ProfileError):
        replace(DEFAULT_PROFILE, days_per_block=5).validate()


# --- Tag nicht im Blatt des Monats: Nachbarblatt / optionale Grenzen --------------------------------------

def test_day_missing_in_its_month_sheet_goes_to_the_neighbour_sheet():
    nov, dec = FakeSheet("November"), FakeSheet("Dezember", kw0=48)        # 30.11. = Mo KW 49 steht nur im Dezemberblatt
    book = FakeBook(nov, dec)
    plan = plan_all(book, [hours(date(2026, 11, 30), 2, "E24005-20", "x"), hours(date(2026, 11, 3), 1, "E24005-20", "x")])
    assert sorted((ln.sheet, ln.day.day) for ln in plan.lines) == [("Dezember", 30), ("November", 3)]
    assert plan.warnings == []


def test_neighbour_fallback_shares_free_rows_with_the_sheets_own_days():
    nov, dec = FakeSheet("November"), FakeSheet("Dezember", kw0=48)
    items = [hours(date(2026, 12, 1), 1, "E11111-01", "Dez"), hours(date(2026, 11, 30), 2, "E22222-02", "Spill")]
    plan = plan_all(FakeBook(nov, dec), items)
    assert sorted((s.sheet, s.row, s.value) for s in plan.setups) == [("Dezember", 10, "E11111-01"),
                                                                       ("Dezember", 11, "E22222-02")]


def test_day_found_in_no_sheet_gives_a_warning_and_no_orphan_row():
    plan = plan_all(FakeBook(FakeSheet("November")), [hours(date(2026, 11, 30), 2, "E77777-01", "Neu")])
    assert plan.lines == [] and plan.setups == []
    assert any("Nachbarblatts" in w and "30.11.2026" in w for w in plan.warnings)


def test_section_end_and_total_row_are_optional():
    sheet = FakeSheet()
    del sheet.v[49, 1]                                              # keine Summenzeile
    prof = replace(DEFAULT_PROFILE, section_next="", section_total="")
    lay = detect_layout(sheet.grid(80, 60), 11, 2026, prof)
    assert (lay.row_first, lay.row_last_billable, lay.row_scan_end) == (8, 80, 80)
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E_Supp_AM", "x")], prof)          # steht im Bereich darunter: gefunden
    assert plan.lines[0].row == 35 and plan.setups == []
    only_total = replace(DEFAULT_PROFILE, section_next="")
    sheet2 = FakeSheet()
    assert detect_layout(sheet2.grid(80, 60), 11, 2026, only_total).row_last_billable == 48
    prof.validate()


# --- Anzeige wie in Excel: Formatierung aus der Datei lesen -----------------------------------------------

def _styled_workbook(path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.styles.colors import Color
    wb = Workbook()
    ws = wb.active
    ws.title = "November"
    ws["A1"], ws["B1"], ws["C1"] = "Titel", 7.5, date(2026, 11, 2)
    ws["A1"].font = Font(bold=True, italic=True, color="FFFF0000")
    ws["A1"].fill = PatternFill("solid", fgColor="FF2F5597")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws["A2"] = "Theme"
    ws["A2"].fill = PatternFill("solid", fgColor=Color(theme=4))              # Akzentfarbe 1 des Designs
    ws.merge_cells("A3:C3")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].hidden = True
    ws.row_dimensions[2].height = 30
    wb.save(path)


def test_sheet_view_reads_values_colors_widths_and_merges(tmp_path):
    from workplanner.excel_timesheet import CellStyle, read_sheet_view
    path = str(tmp_path / "s.xlsx")
    _styled_workbook(path)
    view = read_sheet_view(path, "November", rows=10, cols=5)
    assert view.grid[0][1] == 7.5 and view.grid[0][0] == "Titel" and view.grid[0][2].date() == date(2026, 11, 2)
    assert view.styles[1, 1] == CellStyle("#2F5597", "#FF0000", True, True, "center")
    assert view.styles[2, 1].bg is not None and view.styles[2, 1].bg.startswith("#")      # Theme-Farbe aufgelöst
    assert view.col_px[1] == 30 * 7 + 5 and view.col_px[2] == 0                           # versteckte Spalte
    assert view.row_px[2] == 40                                                            # 30 pt = 40 px
    assert view.merges == [(3, 1, 3, 3)]


def test_display_text_formats_like_excel():
    from datetime import datetime, time

    from workplanner.excel_timesheet import display_text
    assert display_text(datetime(2026, 11, 2)) == "02.11.2026"
    assert display_text(datetime(2026, 11, 2, 8, 30)) == "02.11.2026 08:30"
    assert display_text(time(8, 5)) == "08:05" and display_text(7.5) == "7.5" and display_text(8.0) == "8"
    assert display_text(None) == "" and display_text(0.123456) == "0.12"


# --- Grenzen wahlweise als feste Zeile ------------------------------------------------------------------

def test_section_boundaries_can_be_fixed_rows_instead_of_texts():
    sheet = FakeSheet()
    for key in ((7, 1), (29, 1), (49, 1)):
        sheet.v[key] = ""                                           # keine Beschriftungen mehr im Blatt
    prof = replace(DEFAULT_PROFILE, section_start="", section_next="", section_total="",
                   section_start_row=7, section_next_row=29, section_total_row=49).validate()
    lay = detect_layout(sheet.grid(80, 60), 11, 2026, prof)
    assert (lay.row_first, lay.row_last_billable, lay.row_scan_end) == (8, 28, 48)
    plan = plan_month(sheet, 11, 2026, [hours(D, 1, "E24005-20", "x"), hours(D, 1, "E5", "neu")], prof)
    assert [ln.row for ln in plan.lines] == [8, 10]


def test_text_and_fixed_row_can_be_mixed_and_are_checked():
    prof = replace(DEFAULT_PROFILE, section_next="", section_next_row=29)         # Beginn per Text, Ende per Zeile
    assert detect_layout(FakeSheet().grid(80, 60), 11, 2026, prof).row_last_billable == 28
    with pytest.raises(ExcelError, match="passen nicht zusammen"):
        detect_layout(FakeSheet().grid(80, 60), 11, 2026, replace(DEFAULT_PROFILE, section_next_row=5))
    with pytest.raises(ProfileError):
        replace(DEFAULT_PROFILE, section_total_row=500).validate()
    replace(DEFAULT_PROFILE, section_start="", section_start_row=7).validate()    # Text darf bei fester Zeile leer sein


def test_days_per_block_is_detected_automatically_by_default():
    assert DEFAULT_PROFILE.days_per_block == 0
    six = detect_layout(FakeSheet().grid(80, 60), 11, 2026)                       # nach „Sa“ kein „So“
    assert six.days == 6
    sheet, _ = seven_day_sheet()
    seven = detect_layout(sheet.grid(80, 60), 11, 2026)                           # nach „Sa“ folgt „So“
    assert seven.days == 7
    plan = plan_month(sheet, 11, 2026, [hours(date(2026, 11, 1), 1, "E24005-20", "x")])
    assert len(plan.lines) == 1 and plan.warnings == []                           # Sonntag wird eingetragen
    forced = detect_layout(sheet.grid(80, 60), 11, 2026, replace(DEFAULT_PROFILE, days_per_block=6))
    assert forced.days == 6                                                       # fest eingestellt hat Vorrang


def test_aggregate_takes_pauses_only_when_asked():
    from datetime import date, timedelta
    rows = [{"kind": "work", "date": date(2026, 11, 2), "project": "Kunde A", "project_number": "1",
             "duration": timedelta(hours=2)},
            {"kind": "pause", "date": date(2026, 11, 2), "project": "Pause", "project_number": "",
             "duration": timedelta(minutes=30)}]
    assert len(aggregate(rows)) == 1
    with_pause = aggregate(rows, include_pause=True)
    assert len(with_pause) == 2 and any(d.name == "Pause" and d.hours == 0.5 for d in with_pause)
