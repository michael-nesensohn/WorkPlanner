"""Termine aus dem klassischen Outlook lesen (COM-Automation, nur lesend).

Das neue Outlook (Store-App) bietet keine COM-Schnittstelle; dort schlägt `read_appointments`
mit einer verständlichen Meldung fehl.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

OL_FOLDER_CALENDAR = 9
OL_APPOINTMENT_CLASS = 26
OL_RESPONSE_DECLINED = 4
OL_MEETING_CANCELED = (5, 7)
OL_BUSY_FREE = 0
MAX_ITEMS = 50000  # Schutz gegen endlose Serien


class OutlookError(Exception):
    """Outlook ist nicht erreichbar oder liefert keine Termine (mit lesbarer Meldung)."""


@dataclass(frozen=True)
class Appointment:
    key: str            # eindeutig je Termin bzw. Serientermin-Vorkommen (gegen Doppelimport)
    subject: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    free: bool = False      # als „Frei“ markiert
    declined: bool = False  # abgesagt oder abgelehnt


def _dt(value) -> datetime:
    """COM liefert je nach pywin32-Version Zeitzonen-Objekte; die Uhrzeit ist die lokale Anzeigezeit."""
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y %H:%M")  # Format der Restrict-Filter von Outlook


def _collect(items, range_start: datetime, range_end: datetime) -> list[Appointment]:
    out: list[Appointment] = []
    for n, item in enumerate(items):
        if n > MAX_ITEMS:
            break
        try:
            if getattr(item, "Class", OL_APPOINTMENT_CLASS) != OL_APPOINTMENT_CLASS:
                continue
            start, end = _dt(item.Start), _dt(item.End)
            if start >= range_end:
                break  # nach Start sortiert: der Rest liegt dahinter
            if end <= range_start:
                continue
            out.append(Appointment(
                key=f"{item.EntryID}|{start:%Y%m%dT%H%M}",
                subject=(item.Subject or "").strip() or "(ohne Betreff)",
                start=start, end=end, all_day=bool(item.AllDayEvent),
                location=(item.Location or "").strip(),
                free=item.BusyStatus == OL_BUSY_FREE,
                declined=item.ResponseStatus == OL_RESPONSE_DECLINED
                or getattr(item, "MeetingStatus", 0) in OL_MEETING_CANCELED))
        except AttributeError:
            continue  # kein gewöhnlicher Termin
    return out


def _read(app, first: date, last: date) -> list[Appointment]:
    range_start = datetime.combine(first, time.min)
    range_end = datetime.combine(last + timedelta(days=1), time.min)
    items = app.GetNamespace("MAPI").GetDefaultFolder(OL_FOLDER_CALENDAR).Items
    items.IncludeRecurrences = True  # Serientermine als einzelne Vorkommen
    items.Sort("[Start]")
    try:
        restricted = items.Restrict(f"[Start] < '{_fmt(range_end)}' AND [End] > '{_fmt(range_start)}'")
    except Exception:  # noqa: BLE001 – COM wirft hier beliebige Fehler
        restricted = items
    found = _collect(restricted, range_start, range_end)
    if not found and restricted is not items:
        # Der Filter hängt vom Datumsformat des Systems ab; zur Sicherheit einmal ungefiltert prüfen
        found = _collect(items, range_start, range_end)
    return sorted(found, key=lambda a: (a.start, a.end))


def read_appointments(first: date, last: date, app=None) -> list[Appointment]:
    """Alle Termine von `first` bis einschließlich `last` aus dem Standardkalender."""
    com_started = False
    if app is None:
        try:
            import pythoncom
            import win32com.client
        except ImportError as ex:
            raise OutlookError("Das Paket „pywin32“ fehlt (pip install pywin32).") from ex
        pythoncom.CoInitialize()  # nötig, weil der Aufruf in einem Hintergrund-Thread läuft
        com_started = True
        try:
            app = win32com.client.Dispatch("Outlook.Application")
        except Exception as ex:  # noqa: BLE001
            pythoncom.CoUninitialize()
            raise OutlookError("Outlook konnte nicht gestartet werden. Der Import braucht das klassische "
                               "Outlook (das neue Outlook bietet keine Schnittstelle dafür).") from ex
    try:
        return _read(app, first, last)
    except OutlookError:
        raise
    except Exception as ex:  # noqa: BLE001
        raise OutlookError(f"Der Kalender konnte nicht gelesen werden: {ex}") from ex
    finally:
        if com_started:
            app = None
            pythoncom.CoUninitialize()
