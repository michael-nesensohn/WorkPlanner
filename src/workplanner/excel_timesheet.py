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

import os
import time as _time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
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


def aggregate(rows: list[dict]) -> list[DayHours]:
    """Fasst `TimeService.report_rows` je Projekt und Tag zusammen (nur Arbeitszeit, Dauer ohne Mittagspause)."""
    sums: dict[tuple, float] = defaultdict(float)
    meta: dict[tuple, tuple[str, str]] = {}
    order: list[tuple] = []
    for r in rows:
        if r["kind"] != "work":
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

    def column_for(self, d: date) -> int | None:
        if d.weekday() > 5:
            return None
        for i, start in enumerate(self.block_starts):
            monday = self.first_monday + timedelta(days=7 * i)
            if monday <= d <= monday + timedelta(days=5):
                return start + (d - monday).days
        return None


def detect_layout(grid: list[list], sheet_month: int, year: int) -> Layout:
    def cell(r, c):
        return grid[r - 1][c - 1] if 0 < r <= len(grid) and 0 < c <= len(grid[0]) else None

    # Spalten „Projekt“ / „Proj-Nr.“ in der Kopfzeile
    header = next((r for r in range(1, 12) if any(_text(cell(r, c)).casefold().startswith("proj-nr")
                                                  for c in range(1, 12))), None)
    if header is None:
        raise ExcelError("Spalte „Proj-Nr.“ nicht gefunden (Kopfzeile des Blatts).")
    col_nr = next(c for c in range(1, 12) if _text(cell(header, c)).casefold().startswith("proj-nr"))
    col_name = next((c for c in range(1, col_nr) if _text(cell(header, c)).casefold().startswith("projekt")), 1)

    # Abschnitte in der Spalte „Projekt“
    texts = {r: _text(cell(r, col_name)).casefold() for r in range(header + 1, GRID_ROWS + 1)}
    row_billable = next((r for r, t in texts.items() if t.startswith("projekt verrechenbar")), None)
    row_not = next((r for r, t in texts.items() if t.startswith("projekte nicht verrechenbar")), None)
    row_total = next((r for r, t in texts.items() if t.startswith("tagestotal")), None)
    if row_billable is None or row_not is None or row_total is None:
        raise ExcelError("Abschnitte „Projekt verrechenbar / aktivierbar“, „Projekte nicht verrechenbar“ "
                         "oder „Tagestotal“ nicht gefunden.")

    # Wochenblöcke: Spalten mit „Mo“ in der Wochentag-Zeile; die Kalenderwoche des ersten Blocks steht darüber
    weekday_row = next((r for r in range(2, 9) if sum(_text(cell(r, c)) == "Mo" for c in range(1, GRID_COLS)) >= 4), None)
    if weekday_row is None:
        raise ExcelError("Wochentag-Zeile („Mo“, „Di“ …) nicht gefunden.")
    starts = [c for c in range(1, GRID_COLS) if _text(cell(weekday_row, c)) == "Mo"]
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
                  [s + i for s in starts for i in range(6)])


# ------------------------------------------------------------------ Plan

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
        n, letters = self.col, ""
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        return f"{letters}{self.row}"

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

    @property
    def writable(self) -> bool:
        return bool(self.lines)


def plan_month(sheet: SheetAccess, month: int, year: int, items: list[DayHours]) -> Plan:
    plan = Plan()
    grid = sheet.grid(GRID_ROWS, GRID_COLS)
    layout = detect_layout(grid, month, year)

    def cell(r, c):
        return grid[r - 1][c - 1]

    def row_has_hours(r):
        return any(not _is_zero(cell(r, c)) for c in layout.day_cols)

    existing_nr: dict[str, int] = {}
    existing_name: dict[str, int] = {}
    for r in range(layout.row_first, layout.row_scan_end + 1):
        nr, name = _text(cell(r, layout.col_nr)).casefold(), _text(cell(r, layout.col_name)).casefold()
        if nr and nr != "0":
            existing_nr.setdefault(nr, r)
        if name and name != "0":
            existing_name.setdefault(name, r)
    taken: set[int] = set()

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
        kind, ident = it.key
        if it.key not in rows_by_key:
            row = (existing_nr if kind == "nr" else existing_name).get(ident)
            if row is not None:
                rows_by_key[it.key] = (row, "vorhanden", False)
            else:
                row = free_row()
                if row is None:
                    rows_by_key[it.key] = (0, "", False)
                    plan.warnings.append(f"{sheet.name}: Kein freier Platz im Block „Projekt verrechenbar“ für "
                                         f"„{it.label}“ – nicht eingetragen.")
                else:
                    taken.add(row)
                    action = "neue Zeile (Nr.)" if kind == "nr" else "neue Zeile (Name)"
                    rows_by_key[it.key] = (row, action, True)
                    plan.setups.append(RowSetup(sheet.name, row, layout.col_nr if kind == "nr" else layout.col_name,
                                                it.number.strip() if kind == "nr" else it.name.strip()))
        row, action, new = rows_by_key[it.key]
        if not row:
            continue
        col = layout.column_for(it.day)
        if col is None:
            why = "Sonntag hat keine Spalte" if it.day.weekday() == 6 else "liegt nicht in den Wochenblöcken des Blatts"
            plan.warnings.append(f"{it.day:%d.%m.%Y} „{it.label}“ ({it.hours:g} h): {why} – nicht eingetragen.")
            continue
        if sheet.formula(row, col).startswith("="):
            plan.warnings.append(f"{sheet.name}!{PlanLine(sheet.name, it.day, '', 0, row, col, None, '').address} "
                                 "enthält eine Formel – nicht überschrieben.")
            continue
        old = cell(row, col)
        plan.lines.append(PlanLine(sheet.name, it.day, it.label, it.hours, row, col,
                                   None if _is_zero(old) else old, action, new))
    return plan


def plan_all(workbook: "WorkbookAccess", items: list[DayHours]) -> Plan:
    """Ein Blatt je Monat (Name = Monatsname); die Daten kommen aus allen Monaten der Eingabe."""
    total = Plan()
    by_month: "OrderedDict[tuple[int, int], list[DayHours]]" = OrderedDict()
    for it in items:
        by_month.setdefault((it.day.year, it.day.month), []).append(it)
    names = {n.strip().casefold(): n for n in workbook.sheet_names()}
    for (year, month), month_items in by_month.items():
        real = names.get(MONTHS[month - 1])
        if real is None:
            total.warnings.append(f"Kein Blatt „{MONTH_NAMES[month - 1]}“ in der Datei – {len(month_items)} Einträge "
                                  "nicht eingetragen.")
            continue
        part = plan_month(workbook.sheet(real), month, year, month_items)
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
