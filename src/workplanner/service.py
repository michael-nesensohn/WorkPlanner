"""Anwendungslogik: verbindet Zeitleiste, Datenbank und Uhr."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Callable

from . import devops_sync, secret
from .devops import DevOpsClient, DevOpsError
from . import timeline as tl
from .db import Database
from .timeline import PAUSE, WORK, Entry, TimelineError

Op = Callable[[list[Entry], datetime], list[Entry]]


def _system_now() -> datetime:
    return datetime.now().replace(microsecond=0)


@dataclass(frozen=True)
class _Booking:
    start: datetime
    end: datetime
    subject: str


class TimeService:
    def __init__(self, db: Database, clock: Callable[[], datetime] = _system_now):
        self.db = db
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()

    # --- Einstellungen ---------------------------------------------------
    @property
    def pause_start(self) -> time:
        h, m = self.db.get_setting("pause_start").split(":")
        return time(int(h), int(m))

    @property
    def pause_length(self) -> timedelta:
        return timedelta(minutes=int(self.db.get_setting("pause_minutes")))

    @property
    def daily_target(self) -> timedelta:
        return timedelta(minutes=int(self.db.get_setting("daily_target_minutes")))

    def set_pause(self, start: time, minutes: int) -> None:
        self.db.set_setting("pause_start", start.strftime("%H:%M"))
        self.db.set_setting("pause_minutes", str(minutes))

    def default_project_id(self, create: bool = True) -> int | None:
        """Projekt für Zeit ohne Auswahl. „Allgemein“ wird erst angelegt, wenn es gebraucht wird (`create=True`);
        mit `create=False` (z. B. beim bloßen Anzeigen der Stammdaten) bleibt eine neue Datenbank leer."""
        raw = self.db.get_setting("default_project_id")
        ids = {p["id"] for p in self.db.list_projects()}
        if raw.isdigit() and int(raw) in ids:
            return int(raw)
        if not create:
            return None
        existing = next((p["id"] for p in self.db.list_projects() if p["name"] == "Allgemein"), None)
        pid = existing or self.db.add_project("Allgemein", "#8a94a6", favorite=False)
        self.db.set_setting("default_project_id", str(pid))
        return pid

    def set_default_project(self, project_id: int) -> None:
        self.db.set_setting("default_project_id", str(project_id))

    @property
    def devops_enabled(self) -> bool:
        """Alle DevOps-Funktionen (Reiter, Kacheln, Verknüpfungen, Spalten) ein- bzw. ausschalten."""
        return self.db.get_setting("devops_enabled") != "0"

    def set_devops_enabled(self, on: bool) -> None:
        self.db.set_setting("devops_enabled", "1" if on else "0")

    def devops_config(self) -> dict:
        return {"org": self.db.get_setting("devops_org"), "project": self.db.get_setting("devops_project"),
                "team": self.db.get_setting("devops_team"),
                "only_mine": self.db.get_setting("devops_only_mine") == "1",
                "has_pat": bool(self.db.get_setting("devops_pat"))}

    def devops_pat(self) -> str:
        return secret.unprotect(self.db.get_setting("devops_pat"))

    def set_devops_config(self, org: str, project: str, team: str, only_mine: bool,
                          pat: str | None = None) -> None:
        """`pat=None` lässt das gespeicherte Token unverändert."""
        self.db.set_setting("devops_org", org)
        self.db.set_setting("devops_project", project)
        self.db.set_setting("devops_team", team)
        self.db.set_setting("devops_only_mine", "1" if only_mine else "0")
        if pat is not None:
            self.db.set_setting("devops_pat", secret.protect(pat))

    def devops_hours(self) -> dict[int, float]:
        """Gebuchte Stunden je DevOps-Item (Notiz beginnt mit „#ID“), über alle Tage."""
        entries = self.db.load_range(datetime(2000, 1, 1), datetime(2100, 1, 1))
        now = self.now()
        windows = self.lunch_windows(entries)
        return devops_sync.hours_by_item(
            entries, now, lambda e: e.duration(now) - self.lunch_overlap(e, windows[e.start.date()], now))

    def devops_synced(self) -> dict[int, float]:
        return self.db.devops_synced()

    def devops_mark_synced(self, item_id: int, hours: float) -> None:
        self.db.set_devops_synced(item_id, hours)

    @property
    def excel_path(self) -> str:
        """Excel-Stundenzettel, in den die Stunden eingetragen werden (leer = nicht eingestellt)."""
        return self.db.get_setting("excel_path")

    @property
    def excel_save(self) -> bool:
        """Die Datei nach dem Eintragen speichern (sonst bleibt die Änderung nur in Excel offen)."""
        return self.db.get_setting("excel_save") == "1"

    def set_excel(self, path: str, save: bool) -> None:
        self.db.set_setting("excel_path", path.strip())
        self.db.set_setting("excel_save", "1" if save else "0")

    @property
    def excel_profile(self):
        """Aufbau der Excel-Vorlage (ohne gespeichertes oder bei ungültigem Profil: das Standardprofil)."""
        from .excel_timesheet import DEFAULT_PROFILE, ExcelError, profile_from_json
        text = self.db.get_setting("excel_profile")
        if not text:
            return DEFAULT_PROFILE
        try:
            return profile_from_json(text)
        except ExcelError:
            return DEFAULT_PROFILE

    def set_excel_profile(self, profile) -> None:
        from .excel_timesheet import profile_to_json
        self.db.set_setting("excel_profile", profile_to_json(profile.validate()))

    @property
    def export_columns(self) -> list[str]:
        """Spalten des Excel-Exports (Blatt „Einträge“) in Reihenfolge; leer gespeichert = Standard."""
        from .export import DEFAULT_COLUMNS
        allowed = self.available_export_columns
        saved = [c for c in self.db.get_setting("export_columns").split(",") if c in allowed]
        columns = saved or list(DEFAULT_COLUMNS)
        return columns if self.devops_enabled else [c for c in columns if c != "devops"]

    @property
    def available_export_columns(self) -> list[str]:
        """Wählbare Export-Spalten. „Start“ und „Ende“ nur, wenn workplanner.ini sie freischaltet."""
        from .config import export_start_end_enabled
        from .export import ALL_COLUMNS, HIDDEN_COLUMNS
        show = export_start_end_enabled()
        return [c for c in ALL_COLUMNS if show or c not in HIDDEN_COLUMNS]

    def set_export_columns(self, columns: list[str]) -> None:
        self.db.set_setting("export_columns", ",".join(columns))

    def split_widths(self) -> tuple[int, int, int]:
        """Breite von Outlook-Termine, DevOps-Features und Schnellauswahl auf „Heute“ (Standard 250 / 270 / 340).
        Früher wurden nur die letzten beiden gespeichert."""
        try:
            values = [int(v) for v in json.loads(self.db.get_setting("split_widths"))]
            if len(values) == 2:
                values = [250] + values
            o, f, t = values
            return max(180, o), max(180, f), max(150, t)
        except (ValueError, TypeError):
            return 250, 270, 340

    def set_split_widths(self, widths: list[int]) -> None:
        self.db.set_setting("split_widths", json.dumps([int(w) for w in widths]))

    @property
    def db_warn_mb(self) -> int:
        """Ab dieser Dateigröße der Datenbank (in MB) kommt beim Start ein Hinweis; 0 = nie."""
        try:
            return max(0, int(self.db.get_setting("db_warn_mb")))
        except ValueError:
            return 50

    def set_db_warn_mb(self, mb: int) -> None:
        self.db.set_setting("db_warn_mb", str(max(0, int(mb))))

    def db_size_warning(self) -> str | None:
        """Hinweistext, wenn die Datenbank über der Grenze liegt, sonst None."""
        limit = self.db_warn_mb
        size = self.db.size_bytes()
        if not limit or size <= limit * 1024 * 1024:
            return None
        return (f"Die Datenbank ist {size / 1024 / 1024:.0f} MB groß (Hinweisgrenze: {limit} MB).\n\n"
                f"Datei: {self.db.path}\n\n"
                "Das kann den Start und die Auswertungen verlangsamen. „Komprimieren“ gibt ungenutzten Platz frei; "
                "ist sie danach immer noch groß, bitte die Datei sichern und mit der Entwicklung klären, was "
                "darin so viel Platz braucht. Die Grenze lässt sich unter Einstellungen → Stammdaten ändern.")

    def save_window(self, window) -> None:
        """Größe, Position und „maximiert“ des Hauptfensters merken (Qt-Format, base64)."""
        self.db.set_setting("main_geometry", bytes(window.saveGeometry().toBase64()).decode("ascii"))

    def restore_window(self, window) -> None:
        """Stellt das gemerkte Fenster wieder her; Qt holt es auf einen vorhandenen Bildschirm zurück."""
        from PySide6.QtCore import QByteArray
        data = self.db.get_setting("main_geometry")
        if data:
            window.restoreGeometry(QByteArray.fromBase64(data.encode("ascii")))

    def manual_geometry(self) -> bytes | None:
        """Gemerkte Größe/Position des Handbuch-Fensters (Qt-Format)."""
        from PySide6.QtCore import QByteArray
        data = self.db.get_setting("manual_geometry")
        return bytes(QByteArray.fromBase64(data.encode("ascii"))) if data else None

    def set_manual_geometry(self, geometry: bytes) -> None:
        from PySide6.QtCore import QByteArray
        self.db.set_setting("manual_geometry", bytes(QByteArray(geometry).toBase64()).decode("ascii"))

    def master_size(self) -> tuple[int, int]:
        """Größe des Stammdaten-Fensters (Standard 940 × 760)."""
        try:
            w, h = json.loads(self.db.get_setting("master_size"))
            return max(500, int(w)), max(400, int(h))
        except (ValueError, TypeError):
            return 940, 760

    def set_master_size(self, width: int, height: int) -> None:
        self.db.set_setting("master_size", json.dumps([int(width), int(height)]))

    OUTLOOK_PROJECTS = ("meeting", "besprechung", "termine")
    OUTLOOK_ACTIVITIES = ("besprechung", "meeting")

    def outlook_defaults(self) -> tuple[int | None, int | None]:
        """Projekt und Tätigkeit für übernommene Outlook-Termine: ein Projekt „Meeting/Besprechung/Termine“, sonst das
        Standardprojekt; als Tätigkeit „Besprechung/Meeting“, falls es sie gibt."""
        pid = next((p["id"] for p in self.projects() if p["name"].casefold() in self.OUTLOOK_PROJECTS), None)
        if pid is None:
            pid = self.default_project_id(create=False)
        aid = next((a["id"] for a in self.activities_for(pid) if a["name"].casefold() in self.OUTLOOK_ACTIVITIES), None)
        return pid, aid

    @property
    def call_monitor(self) -> bool:
        """Teams-Anrufe erkennen und nach dem Ende fragen, ob sie eingetragen werden sollen."""
        return self.db.get_setting("call_monitor") == "1"

    def set_call_monitor(self, on: bool) -> None:
        self.db.set_setting("call_monitor", "1" if on else "0")

    CALL_ACTIVITY = "Telefonat"

    def call_defaults(self) -> tuple[int | None, int]:
        """Projekt des zuletzt eingetragenen Anrufs (sonst Standardprojekt) und die Tätigkeit „Telefonat“."""
        v = self.db.get_setting("call_project_id")
        pid = int(v) if v else None
        if pid is None or pid not in {p["id"] for p in self.projects()}:
            pid = self.default_project_id(create=False)
        return pid, self.call_activity_id(pid)

    def call_activity_id(self, project_id: int | None = None) -> int:
        """Die Tätigkeit „Telefonat“ (für das Projekt oder global); wird beim ersten Bedarf angelegt."""
        for a in self.activities_for(project_id):
            if a["name"].strip().lower() == self.CALL_ACTIVITY.lower():
                return a["id"]
        return self.db.add_activity(self.CALL_ACTIVITY)

    def add_booking(self, start: datetime, end: datetime, note: str, project_id: int | None,
                    activity_id: int | None) -> None:
        """Trägt einen bereits beendeten Zeitraum ein (überlappende Einträge werden gekürzt)."""
        end = min(end, self.now())
        item = _Booking(start, end, note)
        ops = self._import_ops([item], project_id, activity_id)
        for day, op in ops.items():  # erst alles prüfen, dann schreiben
            self._run(day, op, save=False)
        for day, op in ops.items():
            self._run(day, op, save=True)

    def remember_call_choice(self, project_id: int | None) -> None:
        self.db.set_setting("call_project_id", project_id or "")

    @property
    def duration_anchor(self) -> str:
        """„start“: eine neue Dauer verschiebt das Ende; „end“: sie verschiebt den Start (Wahl im Bearbeiten-Dialog)."""
        return "end" if self.db.get_setting("duration_anchor") == "end" else "start"

    def set_duration_anchor(self, anchor: str) -> None:
        self.db.set_setting("duration_anchor", "end" if anchor == "end" else "start")

    @property
    def tray_mode(self) -> bool:
        """Schließen und Minimieren schicken das Fenster in den Tray statt in die Taskleiste."""
        return self.db.get_setting("tray_mode") == "1"

    def set_tray_mode(self, on: bool) -> None:
        self.db.set_setting("tray_mode", "1" if on else "0")

    @property
    def start_in_tray(self) -> bool:
        """Beim Start mit Windows bleibt das Fenster zu."""
        return self.db.get_setting("start_in_tray") == "1"

    def set_start_in_tray(self, on: bool) -> None:
        self.db.set_setting("start_in_tray", "1" if on else "0")

    @property
    def hotkey(self) -> str:
        return self.db.get_setting("hotkey")

    def set_hotkey(self, text: str) -> None:
        self.db.set_setting("hotkey", text)

    def set_daily_target(self, minutes: int) -> None:
        self.db.set_setting("daily_target_minutes", str(minutes))

    # --- Stammdaten ------------------------------------------------------
    def projects(self, favorites_only: bool = False):
        rows = self.db.list_projects()
        return [r for r in rows if r["favorite"]] if favorites_only else rows

    def activities_for(self, project_id: int | None):
        """Globale Tätigkeiten plus die des Projekts."""
        return [a for a in self.db.list_activities()
                if a["project_id"] is None or a["project_id"] == project_id]

    def project_name(self, project_id: int | None) -> str:
        for p in self.db.list_projects(include_archived=True):
            if p["id"] == project_id:
                return p["name"]
        return ""

    def project_number(self, project_id: int | None) -> str:
        for p in self.db.list_projects(include_archived=True):
            if p["id"] == project_id:
                return p["number"]
        return ""

    def find_project(self, name: str = "", number: str = "") -> int | None:
        """Vorhandenes Projekt (auch ausgeblendet) mit gleichem Namen oder gleicher Nummer."""
        for p in self.db.list_projects(include_archived=True):
            if (name and p["name"].casefold() == name.casefold()) or (number and p["number"] == number):
                return p["id"]
        return None

    def add_project(self, name: str, number: str = "", billable: bool = False) -> int | None:
        """Legt ein Projekt an; None, wenn es Name oder Nummer schon gibt."""
        if self.find_project(name, number) is not None:
            return None
        return self.db.add_project(name, number=number, billable=billable)

    def project_color(self, project_id: int | None) -> str | None:
        for p in self.db.list_projects(include_archived=True):
            if p["id"] == project_id:
                return p["color"]
        return None

    def devops_features_cache(self) -> list[dict]:
        """Zuletzt geladene DevOps-Features (damit die Kacheln auch offline und sofort da sind)."""
        try:
            data = json.loads(self.db.get_setting("devops_features_cache") or "[]")
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def set_devops_features_cache(self, items: list[dict]) -> None:
        self.db.set_setting("devops_features_cache", json.dumps(items, ensure_ascii=False))
        for f in items:
            self.remember_devops_title(f["id"], f["title"])

    def _devops_titles(self) -> dict[str, str]:
        try:
            data = json.loads(self.db.get_setting("devops_titles") or "{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def remember_devops_title(self, item_id: int, title: str) -> None:
        """Merkt sich den Titel zu einer DevOps-ID, damit die Anzeige „#21 Waagen-Anbindung“ auch offline geht."""
        titles = self._devops_titles()
        if titles.get(str(item_id)) != title:
            titles[str(item_id)] = title
            self.db.set_setting("devops_titles", json.dumps(titles, ensure_ascii=False))

    def devops_title(self, item_id: int | None) -> str:
        return self._devops_titles().get(str(item_id), "") if item_id is not None else ""

    def devops_client(self, factory=DevOpsClient) -> DevOpsClient:
        """Client aus den gespeicherten Einstellungen; DevOpsError mit lesbarer Meldung, falls etwas fehlt."""
        cfg, pat = self.devops_config(), self.devops_pat()
        if not (cfg["org"] and cfg["project"]):
            raise DevOpsError("DevOps ist nicht eingerichtet (Tab „DevOps“).")
        if not pat:
            raise DevOpsError("Kein Token – im Tab „DevOps“ eintragen.")
        return factory(cfg["org"], cfg["project"], cfg["team"], pat)

    def mark_entry_task(self, entry_id: int, task_id: int) -> None:
        """Merkt, dass aus der Notiz des Eintrags der DevOps-Task `task_id` angelegt wurde."""
        entry = self.db.get_entry(entry_id)
        self.db.save_day(entry.start.date(), [replace(e, devops_task_id=task_id) if e.id == entry_id else e
                                              for e in self.db.load_day(entry.start.date())])

    def ensure_devops_project(self, feature_id: int, title: str) -> tuple[int, bool]:
        """Das Projekt zu einem DevOps-Feature oder einer Story (Nummer = ID); wird bei Bedarf angelegt.

        Rückgabe: (Projekt-ID, neu angelegt). Ein gleichnamiges Projekt ohne Nummer wird übernommen und
        bekommt die Nummer; trägt der Name schon eine andere Nummer, entsteht „Titel (ID)“. Neue Projekte
        stehen nicht in der Projekt-Schnellauswahl (die DevOps-Einträge haben ihre eigene Spalte)."""
        number = str(feature_id)
        pid = self.find_project(number=number)
        if pid is not None:
            return pid, False
        by_name = self.find_project(name=title)
        if by_name is not None and not self.project_number(by_name):
            self.db.update_project(by_name, number=number)
            return by_name, False
        name = title if by_name is None else f"{title} ({feature_id})"
        return self.db.add_project(name, number=number, favorite=False), True

    def project_billable(self, project_id: int | None) -> bool:
        for p in self.db.list_projects(include_archived=True):
            if p["id"] == project_id:
                return bool(p["billable"])
        return False

    def project_display(self, project_id: int | None) -> str:
        """„Nummer  Name“ bzw. nur der Name, wenn keine Nummer vergeben ist."""
        name = self.project_name(project_id)
        number = self.project_number(project_id)
        return f"{number}  {name}" if number and name else name

    def activity_name(self, activity_id: int | None) -> str:
        for a in self.db.list_activities(include_archived=True):
            if a["id"] == activity_id:
                return a["name"]
        return ""

    def entry_label(self, e: Entry) -> str:
        return "Pause" if e.kind == PAUSE else (self.project_name(e.project_id) or "–")

    # --- Kern: Operation auf einem Tag ausführen ------------------------------
    def _finalize(self, day: date, entries: list[Entry], now: datetime) -> list[Entry]:
        entries = tl.resume_after_meeting(entries, now)  # ist ein Termin zu Ende, läuft die Aufgabe weiter
        tl.validate(entries, now)
        return entries

    def _run(self, day: date, op: Op, save: bool) -> tuple[list[Entry], list[Entry]]:
        now = self.now()
        old = self.db.load_day(day)
        new = self._finalize(day, op(old, now), now)
        if save:
            new = self.db.save_day(day, new)
        return old, new

    # --- Abfragen ----------------------------------------------------------------
    def day_entries(self, day: date) -> list[Entry]:
        return self.db.load_day(day)

    def current(self) -> Entry | None:
        return self.db.running_entry()

    # --- Mittagspause: wird am Tagesende abgezogen, nicht als Eintrag eingefügt --------------------
    def lunch_window(self, day: date) -> tuple[datetime, datetime] | None:
        """Zeitfenster der Mittagspause (None, wenn sie für den Tag abgeschaltet ist oder 0 min dauert)."""
        if self.pause_length <= timedelta(0) or self.db.pause_disabled(day):
            return None
        start = datetime.combine(day, self.pause_start)
        return start, start + self.pause_length

    def lunch_windows(self, entries: list[Entry]) -> dict[date, tuple[datetime, datetime] | None]:
        return {d: self.lunch_window(d) for d in {e.start.date() for e in entries}}

    @staticmethod
    def lunch_overlap(e: Entry, window, now: datetime) -> timedelta:
        """Wie viel der Arbeitszeit in das Pausenfenster fällt – das wird abgezogen (höchstens die Pausendauer)."""
        if window is None or e.kind != WORK:
            return timedelta(0)
        return max(min(e.end or now, window[1]) - max(e.start, window[0]), timedelta(0))

    def net_duration(self, e: Entry, now: datetime | None = None) -> timedelta:
        """Dauer des Eintrags ohne den Anteil der Mittagspause."""
        now = now or self.now()
        return e.duration(now) - self.lunch_overlap(e, self.lunch_window(e.start.date()), now)

    def work_total(self, entries: list[Entry], now: datetime | None = None) -> timedelta:
        """Arbeitszeit der Einträge abzüglich Mittagspause."""
        now = now or self.now()
        windows = self.lunch_windows(entries)
        return sum((e.duration(now) - self.lunch_overlap(e, windows[e.start.date()], now)
                    for e in entries if e.kind == WORK), timedelta())

    def target_end(self, entries: list[Entry], now: datetime | None = None) -> datetime | None:
        """Uhrzeit, zu der das Tages-Soll erreicht ist, wenn ab jetzt durchgehend gearbeitet wird.

        Eine noch bevorstehende Mittagspause wird eingerechnet (sie verschiebt das Ende um ihre Dauer).
        None, wenn das Soll schon erreicht ist."""
        now = now or self.now()
        remaining = self.daily_target - self.work_total(entries, now)
        if remaining <= timedelta(0):
            return None
        window = self.lunch_window(now.date())
        end = now + remaining
        if window:  # das Ende verschiebt sich um den Teil der Pause, der noch vor ihm liegt
            for _ in range(3):
                overlap = max(min(end, window[1]) - max(now, window[0]), timedelta(0))
                end = now + remaining + overlap
        return end

    def lunch_total(self, entries: list[Entry], now: datetime | None = None) -> timedelta:
        now = now or self.now()
        windows = self.lunch_windows(entries)
        return sum((self.lunch_overlap(e, windows[e.start.date()], now) for e in entries), timedelta())

    def pause_disabled(self, day: date) -> bool:
        return self.db.pause_disabled(day)

    # --- Start / Stopp / Tick ------------------------------------------------------
    def close_stale(self) -> None:
        """Ein über Mitternacht laufender Eintrag wird um 24:00 beendet."""
        run = self.db.running_entry()
        today = self.now().date()
        if run and run.start.date() < today:
            midnight = datetime.combine(run.start.date() + timedelta(days=1), time.min)
            day = run.start.date()
            entries = self.db.load_day(day)
            self.db.save_day(day, tl.stop(entries, midnight))

    def start_task(self, project_id: int | None, activity_id: int | None, note: str = "",
                   devops_id: int | None = None) -> None:
        self.close_stale()
        template = Entry(self.now(), project_id=project_id, activity_id=activity_id, note=note,
                         billable=self.project_billable(project_id), devops_id=devops_id)
        self._run(self.now().date(), lambda es, now: tl.start_new(es, template, now), save=True)

    def stop(self) -> None:
        self.close_stale()
        self._run(self.now().date(), tl.stop, save=True)

    def set_running_note(self, note: str) -> None:
        run = self.db.running_entry()
        if run and run.note != note:
            self.db.save_day(run.start.date(), [
                e if e.id != run.id else replace(e, note=note)
                for e in self.db.load_day(run.start.date())])

    def set_running_billable(self, billable: bool) -> None:
        run = self.db.running_entry()
        if run and run.billable != billable:
            self.db.save_day(run.start.date(), [
                e if e.id != run.id else replace(e, billable=billable)
                for e in self.db.load_day(run.start.date())])

    def tick(self) -> bool:
        """Wendet die Pausenautomatik auf heute an; True wenn sich etwas geändert hat."""
        self.close_stale()
        today = self.now().date()
        old, new = self._run(today, lambda es, now: es, save=False)
        if old == new:
            return False
        self.db.save_day(today, new)
        return True

    # --- Bearbeiten (mit Vorschau) ----------------------------------------------------
    def _edit_op(self, entry_id: int, changes: dict, overlap: str = tl.PUSH) -> Op:
        changes = dict(changes)
        if "project_id" in changes and "billable" not in changes:
            changes["billable"] = self.project_billable(changes["project_id"])

        def op(entries: list[Entry], now: datetime) -> list[Entry]:
            idx = next(i for i, e in enumerate(entries) if e.id == entry_id)
            e = entries[idx]
            attrs = {k: changes[k] for k in ("project_id", "activity_id", "note", "billable", "devops_id")
                     if k in changes}
            if attrs:
                entries = list(entries)
                entries[idx] = replace(e, **attrs)
            new_start, new_end = changes.get("start", e.start), changes.get("end", e.end)
            steps = []
            if new_start != e.start:
                steps.append(("start", new_start))
            if new_end != e.end:
                steps.append(("end", new_end))
            # Wird der ganze Eintrag nach hinten verschoben, muss das Ende zuerst kommen – sonst entstünde
            # nach dem ersten Schritt ein Eintrag mit Start nach Ende. In allen anderen Fällen ist der Start zuerst gültig.
            if len(steps) == 2 and e.end is not None and new_start >= e.end:
                steps.reverse()
            for what, value in steps:
                # Position neu bestimmen: ein früherer Start kann Vorgänger entfernen und die Liste verschieben
                idx = next(i for i, x in enumerate(entries) if x.id == entry_id)
                entries = (tl.set_start(entries, idx, value, now, overlap) if what == "start"
                           else tl.set_end(entries, idx, value, now))
            return entries
        return op

    def preview_edit(self, entry_id: int, changes: dict, overlap: str = tl.PUSH):
        day = self.db.get_entry(entry_id).start.date()
        return self._run(day, self._edit_op(entry_id, changes, overlap), save=False)

    def edit_entry(self, entry_id: int, changes: dict, overlap: str = tl.PUSH) -> None:
        day = self.db.get_entry(entry_id).start.date()
        self._run(day, self._edit_op(entry_id, changes, overlap), save=True)

    def start_overlaps(self, entry_id: int, changes: dict) -> bool:
        """Reicht der neue Start in davor liegende Einträge hinein? Dann muss der Nutzer wählen, wie sie angepasst werden."""
        start = changes.get("start")
        if start is None:
            return False
        entries = self.day_entries(self.db.get_entry(entry_id).start.date())
        idx = next((i for i, x in enumerate(entries) if x.id == entry_id), None)
        return idx is not None and bool(tl.earlier_overlap(entries, idx, start))

    @staticmethod
    def _insert_op(new: Entry):
        """Spätere Einträge rücken nach hinten, nichts geht dabei in die Zukunft (die laufende Aufgabe beginnt dann
        spätestens jetzt). Hat die laufende Aufgabe schon vor dem neuen Eintrag begonnen, wird sie dort beendet
        und läuft danach mit derselben Aufgabe weiter."""
        def op(entries: list[Entry], now: datetime) -> list[Entry]:
            run = entries[-1] if entries and entries[-1].running and entries[-1].kind == WORK else None
            if run and new.end is not None and run.start < new.start < now:
                return tl.place(entries, new, now) if new.end <= now else tl.interrupt(entries, new, now)
            return tl.insert_fit(entries, new, now)
        return op

    def preview_insert(self, new: Entry):
        return self._run(new.start.date(), self._insert_op(new), save=False)

    def insert_entry(self, new: Entry) -> None:
        self._run(new.start.date(), self._insert_op(new), save=True)

    def delete_entry(self, entry_id: int) -> None:
        entry = self.db.get_entry(entry_id)
        if entry.kind == PAUSE:
            self.remove_pause(entry.start.date())
            return

        def op(entries: list[Entry], now: datetime) -> list[Entry]:
            idx = next(i for i, e in enumerate(entries) if e.id == entry_id)
            return tl.delete(entries, idx, now)
        self._run(entry.start.date(), op, save=True)

    def delete_entries(self, entry_ids: list[int]) -> None:
        """Löscht mehrere Einträge in einem Schritt; die Folgeeinträge rücken um die Summe nach vorn.
        Eine dabei mitgelöschte Pause wird wie „Pause löschen“ behandelt (für den Tag abgeschaltet)."""
        by_day: dict[date, list[int]] = {}
        for eid in entry_ids:
            entry = self.db.get_entry(eid)
            if entry:
                by_day.setdefault(entry.start.date(), []).append(eid)
        for day, ids in by_day.items():
            def op(entries: list[Entry], now: datetime, ids=ids) -> list[Entry]:
                for eid in sorted(ids, key=lambda i: next(e.start for e in entries if e.id == i), reverse=True):
                    idx = next((i for i, e in enumerate(entries) if e.id == eid), None)
                    if idx is None:  # schon durch eine Pausen-Vereinigung verschwunden
                        continue
                    entries = (tl.remove_pause(entries, idx, now) if entries[idx].kind == PAUSE
                               else tl.delete(entries, idx, now))
                return entries
            if any(e.kind == PAUSE and e.id in ids for e in self.db.load_day(day)):
                self.db.set_pause_disabled(day, True)
            self._run(day, op, save=True)

    # --- Import von Terminen (z. B. aus Outlook) ---------------------------------------------
    def _import_ops(self, items, project_id: int | None, activity_id: int | None) -> dict[date, Op]:
        """Je Tag eine Operation, die die Termine der Reihe nach in die Zeitleiste setzt."""
        billable, now = self.project_billable(project_id), self.now()
        by_day: dict[date, list[Entry]] = {}
        ongoing: dict[date, Entry] = {}
        for it in sorted(items, key=lambda a: (a.start, a.end)):
            day = it.start.date()
            midnight = datetime.combine(day + timedelta(days=1), time.min)
            entry = Entry(it.start, min(it.end, midnight), project_id=project_id, activity_id=activity_id,
                          note=it.subject, billable=billable)
            if entry.end > now:  # läuft gerade: unterbricht die aktuelle Aufgabe, die danach weiterläuft
                if ongoing:
                    raise TimelineError("Es kann nur ein noch laufender Termin auf einmal übernommen werden.")
                ongoing[day] = entry
            else:
                by_day.setdefault(day, []).append(entry)

        def make(new_entries: list[Entry], current: Entry | None) -> Op:
            def op(entries: list[Entry], now: datetime) -> list[Entry]:
                for e in new_entries:
                    entries = tl.place(entries, e, now)
                return tl.interrupt(entries, current, now) if current else entries
            return op
        return {day: make(by_day.get(day, []), ongoing.get(day)) for day in sorted(set(by_day) | set(ongoing))}

    def preview_import(self, items, project_id: int | None, activity_id: int | None):
        """{Tag: (alt, neu)} ohne zu speichern; wirft TimelineError, wenn etwas nicht geht."""
        return {day: self._run(day, op, save=False)
                for day, op in self._import_ops(items, project_id, activity_id).items()}

    def apply_import(self, items, project_id: int | None, activity_id: int | None) -> None:
        """Legt die Termine als Zeiteinträge an und merkt sie sich gegen Doppelimport."""
        ops = self._import_ops(items, project_id, activity_id)
        for day, op in ops.items():  # erst alles prüfen, dann schreiben
            self._run(day, op, save=False)
        for day, op in ops.items():
            self._run(day, op, save=True)
        self.db.mark_outlook_imported([it.key for it in items])

    def outlook_imported(self) -> set[str]:
        return self.db.outlook_imported()

    # --- Pause pro Tag ----------------------------------------------------------------------
    def remove_pause(self, day: date) -> None:
        """Zieht für diesen Tag keine Mittagspause ab. Früher automatisch eingefügte Pausen-Einträge des
        Tages werden dabei entfernt (der Eintrag davor reicht dann bis zum nächsten)."""
        def op(entries: list[Entry], now: datetime) -> list[Entry]:
            for i, e in enumerate(entries):
                if e.kind == PAUSE:
                    return op(tl.remove_pause(entries, i, now), now)
            return entries
        self.db.set_pause_disabled(day, True)
        self._run(day, op, save=True)

    def restore_pause(self, day: date) -> None:
        """Zieht für diesen Tag wieder die Mittagspause ab."""
        self.db.set_pause_disabled(day, False)

    # --- Auswertung ----------------------------------------------------------------------------
    def report_rows(self, first: date, last: date, project_id: int | None = None) -> list[dict]:
        now = self.now()
        entries = self.db.load_range(datetime.combine(first, time.min),
                                     datetime.combine(last + timedelta(days=1), time.min))
        rows = []
        windows = self.lunch_windows(entries)
        for e in entries:
            if project_id is not None and e.project_id != project_id:
                continue
            lunch = self.lunch_overlap(e, windows[e.start.date()], now)
            rows.append({
                "date": e.start.date(), "start": e.start, "end": e.end or now,
                "running": e.running, "kind": e.kind,
                "project": self.entry_label(e), "project_number": self.project_number(e.project_id),
                "activity": self.activity_name(e.activity_id), "note": e.note,
                "billable": e.billable and e.kind == WORK, "devops_id": e.devops_id,
                "duration": e.duration(now) - lunch,   # ohne den Anteil der Mittagspause
                "lunch": lunch,
            })
        return rows
