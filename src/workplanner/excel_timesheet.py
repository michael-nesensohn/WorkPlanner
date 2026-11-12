"""Stunden in einen vorhandenen Excel-Stundenzettel eintragen (ein Blatt je Monat, Wochenblöcke Mo–Sa).

Warum Excel selbst (COM) und keine Bibliothek: Die Vorlage enthält Diagramme, Bilder, externe Verknüpfungen und
Druckeinstellungen. Eine Bibliothek wie openpyxl würde sie beim Speichern verlieren. Über Excel bleibt alles
erhalten, und Excel rechnet die Formeln (Summen, Nachschlagen über die Projektnummer) selbst neu.

Regeln (siehe `plan_month`):
* Pro Projekt und Tag werden die Stunden zusammengezählt und in die Spalte des Tages geschrieben.
* Projekt mit Projektnummer: Steht die Nummer schon in der Spalte „Proj-Nr.“, werden nur Stunden eingetragen.
  Sonst wird die Nummer in einer freien Zeile eingetragen (Projektname, PG usw. holt die Vorlage per Formel).
* Projekt ohne Nummer: Der Projektname kommt in die Spalte „Projekt“. Steht er dort schon, nur Stunden.
* Neue Zeilen entstehen immer im Block „Projekt verrechenbar / aktivierbar“.
"""
from __future__ import annotations

import json
import os
import re
import time as _time
from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from typing import Protocol

MONTHS = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "dezember"]
MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember"]
WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]  # Sonntag hat keine Spalte
GRID_ROWS, GRID_COLS = 80, 60
ROUND_DIGITS = 2


class ExcelError(Exception):
    """Excel-Zugriff oder Layout nicht wie erwartet (mit lesbarer Meldung)."""


# ------------------------------------------------------------------ Profil: Aufbau der Vorlage

class ProfileError(ExcelError):
    """Profil ungültig oder nicht lesbar."""


PROFILE_FORMAT = "workplanner-excel-profile"
IDENTIFY_MODES = {
    "number_or_name": "Projektnummer, ohne Nummer der Name",
    "both": "Projektnummer und Name (getrennte Spalten)",
    "name": "nur Projektname (Text)",
}


@dataclass
class ExcelProfile:
    """Beschreibt, wie eine Stundenzettel-Vorlage aufgebaut ist. Enthält nur Struktur, keine Projekt- oder Pfaddaten,
    damit es sich ohne Bedenken weitergeben lässt (Export/Import)."""
    name: str = "Standard (Monatsblätter, Wochenblöcke)"
    sheet_pattern: str = "{monat}"             # Blattname je Monat: {monat}=Januar, {MM}=01, {M}=1, {jahr}=2026
    identify: str = "number_or_name"           # siehe IDENTIFY_MODES
    header_number: str = "Proj-Nr"             # Kopfzeile: Spalte der Projektnummer (Anfang des Textes genügt)
    header_name: str = "Projekt"               # Kopfzeile: Spalte des Projektnamens
    section_start: str = "Projekt verrechenbar"          # Abschnitt, in dem neue Projektzeilen entstehen
    section_next: str = "Projekte nicht verrechenbar"    # nächster Abschnitt (Ende des ersten)
    section_total: str = "Tagestotal"                    # Zeile unter den Projekten
    weekday_label: str = "Mo"                  # Beschriftung des ersten Wochentags je Wochenblock
    section_start_row: int = 0                 # > 0: feste Zeile statt Text (gilt dann für alle Blätter)
    section_next_row: int = 0
    section_total_row: int = 0
    days_per_block: int = 0                    # Tage je Wochenblock: 0 = automatisch, 6 = Mo–Sa, 7 = Mo–So
    version: int = 1

    def validate(self) -> "ExcelProfile":
        if self.version != 1:
            raise ProfileError(f"Profil-Version {self.version} wird nicht unterstützt (erwartet 1).")
        if self.days_per_block not in (0, 6, 7):
            raise ProfileError("Profil: „days_per_block“ muss 0 (automatisch), 6 (Mo–Sa) oder 7 (Mo–So) sein.")
        if self.identify not in IDENTIFY_MODES:
            raise ProfileError(f"Unbekannte Projekt-Zuordnung „{self.identify}“.")
        for f in ("section_start_row", "section_next_row", "section_total_row"):
            if not 0 <= getattr(self, f) <= GRID_ROWS:
                raise ProfileError(f"Profil: „{f}“ muss 0 (nach Text suchen) oder eine Zeile von 1 bis {GRID_ROWS} sein.")
        required = ["name", "sheet_pattern", "header_name", "weekday_label"] + (
            ["section_start"] if not self.section_start_row else []) + (["header_number"] if self.identify != "name" else [])
        for f in required:
            if not str(getattr(self, f)).strip():
                raise ProfileError(f"Profil: „{f}“ darf nicht leer sein.")
        if not any(t in self.sheet_pattern for t in ("{monat}", "{MM}", "{M}")):
            raise ProfileError("Profil: Das Blattnamen-Muster braucht {monat}, {MM} oder {M} (ein Blatt je Monat).")
        return self

    def sheet_name_for(self, month: int, year: int) -> str:
        return (self.sheet_pattern.replace("{monat}", MONTH_NAMES[month - 1]).replace("{MM}", f"{month:02d}")
                .replace("{M}", str(month)).replace("{jahr}", str(year)))


DEFAULT_PROFILE = ExcelProfile()


def profile_to_json(profile: ExcelProfile) -> str:
    return json.dumps({"format": PROFILE_FORMAT, **asdict(profile)}, ensure_ascii=False, indent=2)


def profile_from_json(text: str) -> ExcelProfile:
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as ex:
        raise ProfileError(f"Das ist keine gültige Profil-Datei (JSON): {ex}") from ex
    if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
        raise ProfileError("Das ist keine WorkPlanner-Excel-Profil-Datei.")
    known = {f.name for f in fields(ExcelProfile)}
    kwargs = {}
    for key, value in data.items():
        if key in known:  # unbekannte Felder (neuere Version) werden ignoriert
            if not isinstance(value, type(getattr(DEFAULT_PROFILE, key))):
                raise ProfileError(f"Profil: „{key}“ hat einen ungültigen Wert.")
            kwargs[key] = value.strip() if isinstance(value, str) else value
    return ExcelProfile(**kwargs).validate()


def save_profile(profile: ExcelProfile, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(profile_to_json(profile.validate()))


def load_profile(path: str) -> ExcelProfile:
    try:
        with open(path, encoding="utf-8") as fh:
            return profile_from_json(fh.read())
    except OSError as ex:
        raise ProfileError(f"Datei nicht lesbar: {ex}") from ex


# ------------------------------------------------------------------ Eingabe: Stunden je Projekt und Tag

@dataclass(frozen=True)
class DayHours:
    day: date
    number: str   # Projektnummer ("" = keine)
    name: str
    hours: float

    @property
    def key(self) -> tuple[str, str]:
        """Projekte mit Nummer zählen über die Nummer, ohne Nummer über den Namen."""
        return ("nr", self.number.strip().casefold()) if self.number.strip() else ("name", self.name.strip().casefold())

    @property
    def label(self) -> str:
        return f"{self.number}  {self.name}" if self.number.strip() else self.name


def aggregate(rows: list[dict], include_pause: bool = False) -> list[DayHours]:
    """Fasst `TimeService.report_rows` je Projekt und Tag zusammen (Arbeitszeit, Dauer ohne Mittagspause; mit
    `include_pause` zusätzlich die als Eintrag angelegten Pausen unter dem Namen „Pause“)."""
    sums: dict[tuple, float] = defaultdict(float)
    meta: dict[tuple, tuple[str, str]] = {}
    order: list[tuple] = []
    for r in rows:
        if r["kind"] != "work" and not (include_pause and r["kind"] == "pause"):
            continue
        number, name = (r.get("project_number") or "").strip(), r["project"]
        key = (r["date"], ("nr", number.casefold()) if number else ("name", name.strip().casefold()))
        if key not in sums:
            order.append(key)
            meta[key] = (number, name)
        sums[key] += r["duration"].total_seconds() / 3600
    out = [DayHours(k[0], *meta[k], round(sums[k], ROUND_DIGITS)) for k in order]
    return sorted([d for d in out if d.hours > 0], key=lambda d: (d.day, d.label.casefold()))


# ------------------------------------------------------------------ Zugriff auf ein Blatt (Excel oder Attrappe)

class SheetAccess(Protocol):
    name: str

    def grid(self, rows: int, cols: int) -> list[list]: ...
    def formula(self, row: int, col: int) -> str: ...
    def set_value(self, row: int, col: int, value) -> None: ...


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _is_zero(v) -> bool:
    return v in (None, "", 0, 0.0, "0")


@dataclass
class Layout:
    """Aus dem Blatt gelesen (nichts ist fest verdrahtet, die Vorlage darf sich verschieben)."""
    col_name: int            # „Projekt“
    col_nr: int              # „Proj-Nr.“
    row_first: int           # erste Projektzeile (unter „Projekt verrechenbar / aktivierbar“)
    row_last_billable: int   # letzte Zeile dieses Blocks
    row_scan_end: int        # bis hier nach vorhandenen Projekten suchen (vor „Tagestotal“)
    block_starts: list[int]  # Spalte von „Mo“ je Wochenblock
    first_monday: date
    day_cols: list[int] = field(default_factory=list)
    days: int = 6            # Tage je Wochenblock (6 = Mo–Sa, 7 = Mo–So)

    def column_for(self, d: date) -> int | None:
        if d.weekday() > self.days - 1:
            return None
        for i, start in enumerate(self.block_starts):
            monday = self.first_monday + timedelta(days=7 * i)
            if monday <= d <= monday + timedelta(days=self.days - 1):
                return start + (d - monday).days
        return None


def detect_layout(grid: list[list], sheet_month: int, year: int, profile: ExcelProfile | None = None) -> Layout:
    profile = profile or DEFAULT_PROFILE

    def cell(r, c):
        return grid[r - 1][c - 1] if 0 < r <= len(grid) and 0 < c <= len(grid[0]) else None

    def starts_with(r, c, label):
        return _text(cell(r, c)).casefold().startswith(label.strip().casefold())

    # Spalten „Projekt“ / „Proj-Nr.“ in der Kopfzeile (nur Name: keine Nummernspalte, col_nr = 0)
    use_nr = profile.identify != "name"
    anchor = profile.header_number if use_nr else profile.header_name
    header = next((r for r in range(1, 12) if any(starts_with(r, c, anchor) for c in range(1, 12))), None)
    if header is None:
        raise ExcelError(f"Spalte „{anchor}“ nicht gefunden (Kopfzeile des Blatts).")
    col_nr = next(c for c in range(1, 12) if starts_with(header, c, profile.header_number)) if use_nr else 0
    col_name = next((c for c in range(1, 12) if c != col_nr and starts_with(header, c, profile.header_name)), 1)

    # Abschnitte in der Spalte „Projekt“
    texts = {r: _text(cell(r, col_name)).casefold() for r in range(header + 1, GRID_ROWS + 1)}

    def find(label):
        return next((r for r, t in texts.items() if t.startswith(label.strip().casefold())), None)

    end = GRID_ROWS + 1   # nicht angegebene Grenze: bis zum Ende des gelesenen Bereichs
    # Jede Grenze: feste Zeile (wenn angegeben), sonst Suche nach dem Text, sonst (nur Ende/Summe) Blattende
    row_billable = profile.section_start_row or find(profile.section_start)
    row_total = profile.section_total_row or (find(profile.section_total) if profile.section_total.strip() else end)
    row_not = profile.section_next_row or (find(profile.section_next) if profile.section_next.strip() else row_total)
    if row_billable is None or row_not is None or row_total is None:
        given = [x for x, fixed in ((profile.section_start, profile.section_start_row),
                                    (profile.section_next, profile.section_next_row),
                                    (profile.section_total, profile.section_total_row)) if x.strip() and not fixed]
        raise ExcelError("Abschnitte " + ", ".join(f"„{x}“" for x in given) + " nicht alle gefunden.")
    if not row_billable < row_not <= row_total:
        raise ExcelError(f"Die Zeilen passen nicht zusammen: Beginn {row_billable}, Ende {row_not}, "
                         f"Summenzeile {row_total} (sie müssen in dieser Reihenfolge aufeinander folgen).")

    # Wochenblöcke: Spalten mit „Mo“ in der Wochentag-Zeile; die Kalenderwoche des ersten Blocks steht darüber
    label = profile.weekday_label.strip()
    weekday_row = next((r for r in range(2, 9) if sum(_text(cell(r, c)) == label for c in range(1, GRID_COLS)) >= 4), None)
    if weekday_row is None:
        raise ExcelError(f"Wochentag-Zeile („{label}“ …) nicht gefunden.")
    starts = [c for c in range(1, GRID_COLS) if _text(cell(weekday_row, c)) == label]
    days = profile.days_per_block or (   # automatisch: steht nach „Sa“ noch ein „So“, hat der Block 7 Tage
        7 if all(_text(cell(weekday_row, s + 6)).casefold().rstrip(".") in ("so", "sonntag") for s in starts) else 6)
    kw_cell = cell(weekday_row - 1, starts[0])
    try:
        kw = int(float(kw_cell))
    except (TypeError, ValueError):
        raise ExcelError("Kalenderwoche des ersten Wochenblocks nicht lesbar.") from None
    month_start = date(year, sheet_month, 1)
    first_monday = None
    for y in (year - 1, year, year + 1):
        try:
            monday = date.fromisocalendar(y, kw, 1)
        except ValueError:
            continue  # KW 53 gibt es nicht in jedem Jahr
        if timedelta(days=-70) <= monday - month_start <= timedelta(days=14):
            first_monday = monday
    if first_monday is None:
        raise ExcelError(f"Kalenderwoche {kw} passt nicht zum Monat {MONTH_NAMES[sheet_month - 1]} {year}.")
    return Layout(col_name, col_nr, row_billable + 1, row_not - 1, row_total - 1, starts, first_monday,
                  [s + i for s in starts for i in range(days)], days)


# ------------------------------------------------------------------ Plan

def col_letter(n: int) -> str:
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


@dataclass
class PlanLine:
    sheet: str
    day: date
    project: str
    hours: float
    row: int
    col: int
    old: object          # bisheriger Wert der Zelle (None = leer)
    action: str          # „vorhanden“ | „neue Zeile (Nr.)“ | „neue Zeile (Name)“
    new_row: bool = False

    @property
    def address(self) -> str:
        return f"{col_letter(self.col)}{self.row}"

    @property
    def overwrites(self) -> bool:
        """Die Zelle enthält schon einen anderen Wert, der ersetzt würde."""
        if _is_zero(self.old):
            return False
        try:
            return abs(float(self.old) - self.hours) > 1e-9
        except (TypeError, ValueError):
            return True


@dataclass
class RowSetup:
    """Eine neue Projektzeile: Nummer bzw. Name eintragen."""
    sheet: str
    row: int
    col: int
    value: str


@dataclass
class Plan:
    lines: list[PlanLine] = field(default_factory=list)
    setups: list[RowSetup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unplaced: list["DayHours"] = field(default_factory=list)   # Tage ohne Spalte in diesem Blatt (siehe plan_month)
    layout: "Layout | None" = None

    @property
    def writable(self) -> bool:
        return bool(self.lines)


def _not_in_blocks(it: DayHours, where: str = "des Blatts") -> str:
    return (f"{it.day:%d.%m.%Y} „{it.label}“ ({it.hours:g} h): liegt nicht in den Wochenblöcken {where} "
            "– nicht eingetragen.")


def plan_month(sheet: SheetAccess, month: int, year: int, items: list[DayHours],
               profile: ExcelProfile | None = None, defer_unplaced: bool = False) -> Plan:
    """Plant ein Blatt. Tage, die in den Wochenblöcken dieses Blatts nicht vorkommen, werden mit einer Warnung
    übersprungen – oder, mit `defer_unplaced`, in `plan.unplaced` gesammelt (plan_all sucht sie im Nachbarblatt)."""
    profile = profile or DEFAULT_PROFILE
    plan = Plan()
    grid = sheet.grid(GRID_ROWS, GRID_COLS)
    layout = detect_layout(grid, month, year, profile)
    plan.layout = layout
    mode = profile.identify

    def cell(r, c):
        return grid[r - 1][c - 1] if c else None   # Spalte 0 = in diesem Profil nicht vorhanden

    def row_has_hours(r):
        return any(not _is_zero(cell(r, c)) for c in layout.day_cols)

    existing_nr: dict[str, int] = {}
    existing_name: dict[str, int] = {}
    name_cells: list[tuple[int, str]] = []
    for r in range(layout.row_first, layout.row_scan_end + 1):
        nr, name = _text(cell(r, layout.col_nr)).casefold(), _text(cell(r, layout.col_name)).casefold()
        if nr and nr != "0":
            existing_nr.setdefault(nr, r)
        if name and name != "0":
            existing_name.setdefault(name, r)
            name_cells.append((r, name))
    taken: set[int] = set()

    def find_existing(it: DayHours) -> int | None:
        """Sucht das Projekt im Blatt: erst über die Nummer (Spalte „Proj-Nr.“, sonst als eigenständiges Wort in der
        Namensspalte), dann – je nach Profil – über den Namen."""
        number, name = it.number.strip().casefold(), it.name.strip().casefold()
        if mode != "name" and number:
            row = existing_nr.get(number)
            if row is None:
                pattern = re.compile(rf"(?<![\w-]){re.escape(number)}(?![\w-])")
                row = next((r for r, text in name_cells if pattern.search(text)), None)
            if row is None and mode == "both":
                row = existing_name.get(name)
            return row
        return existing_name.get(name)

    def free_row() -> int | None:
        for r in range(layout.row_first, layout.row_last_billable + 1):
            if r in taken or not _is_zero(cell(r, layout.col_nr)) or _text(cell(r, layout.col_name)) not in ("", "0"):
                continue
            if row_has_hours(r):
                continue
            return r
        return None

    rows_by_key: dict[tuple, tuple[int, str, bool]] = {}
    for it in items:
        col = layout.column_for(it.day)
        if col is None:   # vor der Zeilensuche: sonst bliebe für einen nicht eintragbaren Tag eine leere neue Zeile
            if it.day.weekday() == 6 and layout.days == 6:
                plan.warnings.append(f"{it.day:%d.%m.%Y} „{it.label}“ ({it.hours:g} h): Sonntag hat keine Spalte – "
                                     "nicht eingetragen.")
            elif defer_unplaced:
                plan.unplaced.append(it)
            else:
                plan.warnings.append(_not_in_blocks(it))
            continue
        key = ("name", it.name.strip().casefold()) if mode == "name" else it.key
        if key not in rows_by_key:
            row = find_existing(it)
            if row is not None:
                rows_by_key[key] = (row, "vorhanden", False)
            else:
                row = free_row()
                if row is None:
                    rows_by_key[key] = (0, "", False)
                    plan.warnings.append(f"{sheet.name}: Kein freier Platz im Block „{profile.section_start}“ für "
                                         f"„{it.label}“ – nicht eingetragen.")
                else:
                    taken.add(row)
                    has_nr = mode != "name" and bool(it.number.strip())
                    action = "neue Zeile (Nr.)" if has_nr and mode != "both" else (
                        "neue Zeile (Nr. + Name)" if has_nr else "neue Zeile (Name)")
                    rows_by_key[key] = (row, action, True)
                    if has_nr:
                        plan.setups.append(RowSetup(sheet.name, row, layout.col_nr, it.number.strip()))
                    if not has_nr or mode == "both":
                        plan.setups.append(RowSetup(sheet.name, row, layout.col_name, it.name.strip()))
        row, action, new = rows_by_key[key]
        if not row:
            continue
        if sheet.formula(row, col).startswith("="):
            plan.warnings.append(f"{sheet.name}!{PlanLine(sheet.name, it.day, '', 0, row, col, None, '').address} "
                                 "enthält eine Formel – nicht überschrieben.")
            continue
        old = cell(row, col)
        plan.lines.append(PlanLine(sheet.name, it.day, it.label, it.hours, row, col,
                                   None if _is_zero(old) else old, action, new))
    return plan


def plan_all(workbook: "WorkbookAccess", items: list[DayHours], profile: ExcelProfile | None = None) -> Plan:
    """Ein Blatt je Monat (Name laut Profil, Standard = Monatsname); die Daten kommen aus allen Monaten der Eingabe.
    Steht ein Tag im Blatt seines Monats nicht (z. B. der 30.11., weil die Woche im Dezemberblatt beginnt), wird er im
    Blatt des Nachbarmonats gesucht."""
    profile = (profile or DEFAULT_PROFILE).validate()
    total = Plan()
    own: "OrderedDict[tuple[int, int], list[DayHours]]" = OrderedDict()
    for it in items:
        own.setdefault((it.day.year, it.day.month), []).append(it)
    names = {n.strip().casefold(): n for n in workbook.sheet_names()}

    def real_name(key):
        return names.get(profile.sheet_name_for(key[1], key[0]).strip().casefold())

    def neighbours(it: DayHours):
        y, m = it.day.year, it.day.month
        nxt, prev = (y + (m == 12), m % 12 + 1), (y - (m == 1), 12 if m == 1 else m - 1)
        return [nxt, prev] if it.day.day > 15 else [prev, nxt]

    # 1. jedes Blatt mit seinen eigenen Tagen planen
    first: dict[tuple[int, int], Plan] = {}
    for key, month_items in own.items():
        real = real_name(key)
        if real is None:
            total.warnings.append(f"Kein Blatt „{profile.sheet_name_for(key[1], key[0])}“ in der Datei – "
                                  f"{len(month_items)} Einträge nicht eingetragen.")
            continue
        first[key] = plan_month(workbook.sheet(real), key[1], key[0], month_items, profile, defer_unplaced=True)

    # 2. Tage ohne Spalte im eigenen Blatt: Nachbarblatt suchen
    extra: dict[tuple[int, int], list[DayHours]] = {}
    layouts: dict[tuple[int, int], Layout | None] = {k: p.layout for k, p in first.items()}

    def layout_of(key):
        if key not in layouts:
            real = real_name(key)
            try:
                layouts[key] = plan_month(workbook.sheet(real), key[1], key[0], [], profile).layout if real else None
            except ExcelError:
                layouts[key] = None   # Nachbarblatt hat einen anderen Aufbau: dann ist der Tag dort nicht eintragbar
        return layouts[key]

    for plan in first.values():
        for it in plan.unplaced:
            target = next((nb for nb in neighbours(it)
                           if (lay := layout_of(nb)) is not None and lay.column_for(it.day) is not None), None)
            if target is None:
                total.warnings.append(_not_in_blocks(it, "dieses und des Nachbarblatts"))
            else:
                extra.setdefault(target, []).append(it)

    # 3. Blätter mit zusätzlichen Tagen gemeinsam neu planen (sonst würden freie Zeilen doppelt vergeben)
    for key in list(first) + [k for k in extra if k not in first]:
        if key in extra:
            placed = [it for it in own.get(key, []) if it not in first[key].unplaced] if key in first else []
            part = plan_month(workbook.sheet(real_name(key)), key[1], key[0], placed + extra[key], profile)
        else:
            part = first[key]
        total.lines += part.lines
        total.setups += part.setups
        total.warnings += part.warnings
    return total


def apply_plan(workbook: "WorkbookAccess", plan: Plan) -> int:
    """Schreibt Nummern/Namen neuer Zeilen und die Stunden; liefert die Anzahl geschriebener Stundenzellen."""
    for s in plan.setups:
        workbook.sheet(s.sheet).set_value(s.row, s.col, s.value)
    for line in plan.lines:
        workbook.sheet(line.sheet).set_value(line.row, line.col, line.hours)
    return len(plan.lines)


class WorkbookAccess(Protocol):
    def sheet_names(self) -> list[str]: ...
    def sheet(self, name: str) -> SheetAccess: ...


# ------------------------------------------------------------------ Für den Assistenten: Datei lesen, Layout prüfen

def file_sheet_names(path: str) -> list[str]:
    """Blattnamen ohne Excel zu starten (schnell, nur lesend)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, keep_links=False)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def read_grid_file(path: str, sheet: str, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> list[list]:
    """Oberer linker Bereich eines Blatts als Raster (zuletzt gespeicherte Werte, ohne Excel zu starten)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        got = [list(r) + [None] * (cols - len(r))
               for r in wb[sheet].iter_rows(min_row=1, max_row=rows, max_col=cols, values_only=True)]
    finally:
        wb.close()
    return got + [[None] * cols for _ in range(rows - len(got))]


@dataclass(frozen=True)
class CellStyle:
    bg: str | None = None        # Füllfarbe "#RRGGBB"
    fg: str | None = None        # Schriftfarbe
    bold: bool = False
    italic: bool = False
    align: str | None = None     # "left" | "center" | "right"


@dataclass
class SheetView:
    """Ein Blatt so, wie Excel es zeigt: Werte plus Formatierung (nur für die Anzeige im Assistenten)."""
    grid: list[list]
    styles: dict[tuple[int, int], CellStyle] = field(default_factory=dict)   # (Zeile, Spalte), 1-basiert
    col_px: dict[int, int] = field(default_factory=dict)
    row_px: dict[int, int] = field(default_factory=dict)
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)    # (Zeile1, Spalte1, Zeile2, Spalte2)


_DEFAULT_THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"]


def _theme_colors(wb) -> list[str]:
    """Farben des Office-Designs der Datei in der Reihenfolge, die Excel für Theme-Indizes verwendet."""
    xml = getattr(wb, "loaded_theme", None)
    if not xml:
        return _DEFAULT_THEME
    text = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else str(xml)
    block = re.search(r"<a:clrScheme.*?</a:clrScheme>", text, re.S)
    found = {}
    for name in ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"):
        m = re.search(rf"<a:{name}>.*?(?:srgbClr val|lastClr)=\"([0-9A-Fa-f]{{6}})\"", block.group(0) if block else "", re.S)
        found[name] = m.group(1) if m else None
    order = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
    return [found[n] or _DEFAULT_THEME[i] for i, n in enumerate(order)]


def _tint(rgb: str, tint: float) -> str:
    import colorsys
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1 + tint) if tint < 0 else l * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), s)
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def _color(color, theme: list[str]) -> str | None:
    """openpyxl-Farbe (rgb / theme / indexed, evtl. mit Tint) → "#RRGGBB"; None = Standard."""
    if color is None:
        return None
    try:
        kind = color.type
        if kind == "rgb":
            value = color.rgb
            if not isinstance(value, str) or len(value) < 6 or value.upper() == "00000000":
                return None
            return "#" + value[-6:].upper()
        if kind == "theme":
            return _tint(theme[color.theme], color.tint or 0.0) if color.theme < len(theme) else None
        if kind == "indexed":
            from openpyxl.styles.colors import COLOR_INDEX
            return "#" + COLOR_INDEX[color.indexed][-6:] if color.indexed < len(COLOR_INDEX) else None
    except (AttributeError, TypeError, ValueError, IndexError):
        return None
    return None


def display_text(v) -> str:
    """Wert so kurz wie in Excel anzeigen (Datum als TT.MM.JJJJ, Zahlen ohne überflüssige Nachkommastellen)."""
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        return f"{v:%d.%m.%Y}" if (v.hour, v.minute) == (0, 0) else f"{v:%d.%m.%Y %H:%M}"
    if isinstance(v, _dt.date):
        return f"{v:%d.%m.%Y}"
    if isinstance(v, _dt.time):
        return f"{v:%H:%M}"
    if isinstance(v, float) and not v.is_integer():
        return f"{round(v, 2):g}"
    return _text(v)


def read_sheet_view(path: str, sheet: str, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> SheetView:
    """Blatt mit Werten (zuletzt gespeichert), Füllfarben, Schrift, Spaltenbreiten, Zeilenhöhen und verbundenen Zellen,
    ohne Excel zu starten. Lädt die Arbeitsmappe vollständig (nicht nur lesend), das dauert bei großen Dateien etwas."""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    wb = load_workbook(path, data_only=True, keep_links=False)
    try:
        ws, theme = wb[sheet], _theme_colors(wb)
        view = SheetView([[None] * cols for _ in range(rows)])
        for r, row in enumerate(ws.iter_rows(min_row=1, max_row=rows, max_col=cols), 1):
            for c, cell in enumerate(row, 1):
                view.grid[r - 1][c - 1] = cell.value
                fill = cell.fill if cell.fill is not None and cell.fill.fill_type == "solid" else None
                style = CellStyle(_color(fill.fgColor, theme) if fill else None, _color(cell.font.color, theme),
                                  bool(cell.font.b), bool(cell.font.i), cell.alignment.horizontal)
                if style != CellStyle():
                    view.styles[r, c] = style
        default_w = ws.sheet_format.defaultColWidth or 8.43
        for c in range(1, cols + 1):
            view.col_px[c] = round(default_w * 7 + 5)
        for dim in list(ws.column_dimensions.values()):   # Spaltengruppen: min..max teilen sich eine Breite
            lo, hi = dim.min or 0, dim.max or 0
            for c in range(max(lo, 1), min(hi, cols) + 1):
                view.col_px[c] = 0 if dim.hidden else round((dim.width or default_w) * 7 + 5)
        for r in range(1, rows + 1):
            dim = ws.row_dimensions.get(r)
            if dim is not None and (dim.hidden or dim.height):
                view.row_px[r] = 0 if dim.hidden else round(dim.height * 96 / 72)
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= rows and rng.min_col <= cols and (rng.max_row > rng.min_row or rng.max_col > rng.min_col):
                view.merges.append((rng.min_row, rng.min_col, min(rng.max_row, rows), min(rng.max_col, cols)))
    finally:
        wb.close()
    return view


def month_of_sheet(profile: ExcelProfile, sheet: str, year: int) -> int | None:
    """Zu welchem Monat gehört der Blattname laut Blattnamen-Muster?"""
    return next((m for m in range(1, 13)
                 if profile.sheet_name_for(m, year).strip().casefold() == sheet.strip().casefold()), None)


def describe_layout(layout: Layout) -> str:
    last_day = layout.first_monday + timedelta(days=7 * len(layout.block_starts) - 1)
    return (f"Projektnummer: {'Spalte ' + col_letter(layout.col_nr) if layout.col_nr else 'keine'}; "
            f"Projektname: Spalte {col_letter(layout.col_name)}; "
            f"Projektzeilen {layout.row_first}–{layout.row_last_billable} (neue Zeilen), "
            f"Suche bis Zeile {layout.row_scan_end}; {len(layout.block_starts)} Wochenblöcke mit je {layout.days} Tagen "
            f"({layout.first_monday:%d.%m.%Y} – {last_day:%d.%m.%Y}).")


# ------------------------------------------------------------------ Excel (COM)

class ComSheet:
    def __init__(self, ws, retry):
        self._ws, self._retry, self.name = ws, retry, ws.Name

    def grid(self, rows: int, cols: int) -> list[list]:
        rng = self._ws.Range(self._ws.Cells(1, 1), self._ws.Cells(rows, cols))
        values = self._retry(lambda: rng.Value2)
        return [list(r) for r in values]

    def formula(self, row: int, col: int) -> str:
        return str(self._retry(lambda: self._ws.Cells(row, col).Formula) or "")

    def set_value(self, row: int, col: int, value) -> None:
        self._retry(lambda: setattr(self._ws.Cells(row, col), "Value2", value))


class ExcelWorkbook:
    """Öffnet die Datei in Excel (oder nutzt die schon dort geöffnete) und gibt sie danach wieder frei."""

    def __init__(self, path: str, save: bool = True):
        self.path, self.save_on_exit = os.path.abspath(path), save
        self._excel = self._wb = None
        self._started_excel = self._opened_wb = False
        self._prev = None

    @staticmethod
    def _retry(fn, tries: int = 20):
        """Excel lehnt Aufrufe ab, solange es noch hochfährt, der Benutzer eine Zelle bearbeitet oder ein Dialog
        offen ist. Dann einige Sekunden lang wiederholen. (pywin32 meldet das je nach Zeitpunkt als com_error mit
        diesen Codes oder als AttributeError, wenn Excel die Eigenschaft noch nicht auflösen kann.)"""
        busy = (-2147418111, -2147417846, -2146777998)  # CALL_REJECTED, SERVERCALL_RETRYLATER, „Anwendung beschäftigt“
        for i in range(tries):
            try:
                return fn()
            except Exception as ex:  # noqa: BLE001 – com_error / AttributeError
                if (getattr(ex, "hresult", None) in busy or isinstance(ex, AttributeError)) and i < tries - 1:
                    _time.sleep(0.5)
                    continue
                raise ExcelError("Excel antwortet nicht (ist gerade eine Zelle oder ein Dialog offen?). "
                                 f"Bitte schließen und noch einmal versuchen. ({ex})") from ex

    def __enter__(self) -> "ExcelWorkbook":
        if not os.path.exists(self.path):
            raise ExcelError(f"Datei nicht gefunden: {self.path}")
        try:
            import pythoncom
            import win32com.client
        except ImportError as ex:
            raise ExcelError("Das Paket „pywin32“ fehlt.") from ex
        pythoncom.CoInitialize()
        self._com = pythoncom
        try:
            retry = self._retry
            try:
                self._excel = win32com.client.GetActiveObject("Excel.Application")
            except Exception:  # noqa: BLE001 – läuft nicht: eigene, unsichtbare Instanz
                self._excel = win32com.client.Dispatch("Excel.Application")
                self._started_excel = True
                retry(lambda: setattr(self._excel, "Visible", False))  # Excel fährt noch hoch: ggf. kurz warten
            ex = self._excel
            self._prev = retry(lambda: (ex.DisplayAlerts, ex.AskToUpdateLinks, ex.EnableEvents))

            def quiet():
                ex.DisplayAlerts, ex.AskToUpdateLinks, ex.EnableEvents = False, False, False
            retry(quiet)
            for wb in retry(lambda: list(ex.Workbooks)):
                if os.path.normcase(retry(lambda wb=wb: wb.FullName)) == os.path.normcase(self.path):
                    self._wb = wb
                    break
            if self._wb is None:
                self._wb = retry(lambda: ex.Workbooks.Open(self.path, UpdateLinks=0))
                self._opened_wb = True
            if retry(lambda: self._wb.ReadOnly):
                raise ExcelError("Die Datei ist schreibgeschützt oder wird von jemand anderem benutzt.")
        except ExcelError:
            self._release()
            raise
        except Exception as ex:  # noqa: BLE001
            self._release()
            raise ExcelError(f"Excel konnte nicht gestartet bzw. die Datei nicht geöffnet werden: {ex}") from ex
        return self

    def sheet_names(self) -> list[str]:
        return [ws.Name for ws in self._wb.Worksheets]

    def sheet(self, name: str) -> ComSheet:
        return ComSheet(self._wb.Worksheets(name), self._retry)

    def _excel_pid(self) -> int | None:
        try:
            import ctypes
            from ctypes import wintypes
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(self._excel.Hwnd, ctypes.byref(pid))
            return pid.value or None
        except Exception:  # noqa: BLE001 – nur eine Hilfe fürs Warten, nie ein Grund abzubrechen
            return None

    @staticmethod
    def _wait_for_exit(pid: int, seconds: float = 10.0) -> None:
        """Wartet, bis der von uns gestartete Excel-Prozess wirklich beendet ist. Sonst hängt sich die nächste
        Sitzung kurz danach an die auslaufende Instanz, und Excel lehnt jeden Zugriff ab."""
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.WaitForSingleObject(handle, int(seconds * 1000))
            kernel32.CloseHandle(handle)

    def _release(self) -> None:
        import gc
        pid = None
        try:
            if self._excel is not None and self._prev is not None:
                self._excel.DisplayAlerts, self._excel.AskToUpdateLinks, self._excel.EnableEvents = self._prev
            if self._wb is not None and self._opened_wb:
                self._wb.Close(SaveChanges=False)
            if self._excel is not None and self._started_excel:
                pid = self._excel_pid()
                self._excel.Quit()
        finally:
            self._wb = self._excel = None
            gc.collect()                 # letzte COM-Verweise freigeben, sonst beendet sich Excel nicht
            self._com.CoUninitialize()
            if pid:
                self._wait_for_exit(pid)

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None and self.save_on_exit and self._wb is not None:
                self._wb.Save()
        finally:
            self._release()
