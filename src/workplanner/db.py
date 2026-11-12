"""SQLite-Persistenz."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .timeline import Entry

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    number TEXT NOT NULL DEFAULT '',
    billable INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#4f8cff',
    favorite INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'work',
    project_id INTEGER REFERENCES projects(id),
    activity_id INTEGER REFERENCES activities(id),
    note TEXT NOT NULL DEFAULT '',
    start_ts TEXT NOT NULL,
    end_ts TEXT,
    auto_pause INTEGER NOT NULL DEFAULT 0,
    billable INTEGER NOT NULL DEFAULT 0,
    auto_until TEXT,
    resume TEXT NOT NULL DEFAULT '',
    devops_id INTEGER,
    devops_task_id INTEGER
);
CREATE INDEX IF NOT EXISTS entries_start ON entries(start_ts);
-- höchstens ein laufender Eintrag
CREATE UNIQUE INDEX IF NOT EXISTS one_running ON entries((1)) WHERE end_ts IS NULL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Stunden, die je DevOps-Item schon übertragen wurden
CREATE TABLE IF NOT EXISTS devops_sync (item_id INTEGER PRIMARY KEY, hours REAL NOT NULL);
-- schon aus Outlook importierte Termine (gegen Doppelimport)
CREATE TABLE IF NOT EXISTS outlook_imported (key TEXT PRIMARY KEY);
-- schon in einen Excel-Stundenzettel eingetragene Stunden je Datei, Tag und Projekt (gegen doppeltes Eintragen)
CREATE TABLE IF NOT EXISTS excel_exported (file TEXT NOT NULL, day TEXT NOT NULL, key TEXT NOT NULL,
                                           hours REAL NOT NULL, PRIMARY KEY (file, day, key));
CREATE TABLE IF NOT EXISTS day_flags (day TEXT PRIMARY KEY, pause_disabled INTEGER NOT NULL DEFAULT 0);
"""

DEFAULT_SETTINGS = {"pause_start": "12:00", "pause_minutes": "30", "daily_target_minutes": "480",
                    "default_project_id": "", "devops_org": "",
                    "devops_project": "", "devops_team": "",
                    "devops_only_mine": "1", "devops_pat": "", "devops_col_widths": "",
                    "hotkey": "Ctrl+Alt+W", "excel_path": "", "excel_save": "1", "excel_profile": "", "duration_anchor": "start", "tray_mode": "1", "start_in_tray": "1",
                    "devops_features_cache": "", "devops_titles": "", "export_columns": "", "call_monitor": "1", "split_widths": "", "db_warn_mb": "50", "master_size": "", "main_geometry": "", "devops_enabled": "1", "manual_geometry": "", "demo_data": "", "demo_offered": "",
                    "call_project_id": "", "call_activity_id": "", "lunch_mode": "deduct", "excel_include_pause": "0", "pdf_header": "", "pdf_layout": "", "excel_conflict": "ask"}
_FMT = "%Y-%m-%dT%H:%M:%S"


def _ts(dt: datetime | None) -> str | None:
    return dt.strftime(_FMT) if dt else None


def _parse(s: str | None) -> datetime | None:
    return datetime.strptime(s, _FMT) if s else None


def _row_to_entry(r: sqlite3.Row) -> Entry:
    return Entry(start=_parse(r["start_ts"]), end=_parse(r["end_ts"]), kind=r["kind"],
                 project_id=r["project_id"], activity_id=r["activity_id"], note=r["note"],
                 auto_pause=bool(r["auto_pause"]), billable=bool(r["billable"]),
                 auto_until=_parse(r["auto_until"]), resume=r["resume"], devops_id=r["devops_id"],
                 devops_task_id=r["devops_task_id"], id=r["id"])


def default_db_path() -> Path:
    """%APPDATA%\\WorkPlanner\\workplanner.db. Zum Entwickeln/Testen lässt sich der Ordner mit der Umgebungsvariable
    WORKPLANNER_DATA umlenken, dann bleiben die echten Daten unberührt (siehe dev-test.ps1 -Start)."""
    import os
    custom = os.environ.get("WORKPLANNER_DATA")
    base = Path(custom) if custom else Path(os.environ.get("APPDATA") or Path.home()) / "WorkPlanner"
    base.mkdir(parents=True, exist_ok=True)
    return base / "workplanner.db"


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
        if "number" not in cols:  # Datenbank aus einer älteren Version
            self.conn.execute("ALTER TABLE projects ADD COLUMN number TEXT NOT NULL DEFAULT ''")
        for table in ("projects", "entries"):
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if "billable" not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN billable INTEGER NOT NULL DEFAULT 0")
        have = {r["name"] for r in self.conn.execute("PRAGMA table_info(entries)")}
        if "auto_until" not in have:
            self.conn.execute("ALTER TABLE entries ADD COLUMN auto_until TEXT")
        if "devops_task_id" not in have:
            self.conn.execute("ALTER TABLE entries ADD COLUMN devops_task_id INTEGER")
        if "devops_id" not in have:
            self.conn.execute("ALTER TABLE entries ADD COLUMN devops_id INTEGER")
        if "resume" not in have:
            self.conn.execute("ALTER TABLE entries ADD COLUMN resume TEXT NOT NULL DEFAULT ''")
        for k, v in DEFAULT_SETTINGS.items():
            self.conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def size_bytes(self) -> int:
        """Größe der Datenbankdatei (0 bei der Speicher-Datenbank der Tests)."""
        try:
            return Path(self.path).stat().st_size
        except OSError:
            return 0

    def vacuum(self) -> None:
        """Gibt ungenutzten Platz in der Datei frei (Inhalt bleibt unverändert)."""
        self.conn.commit()
        self.conn.execute("VACUUM")

    # --- Projekte ---------------------------------------------------------
    def add_project(self, name: str, color: str = "#4f8cff", favorite: bool = True,
                    number: str = "", billable: bool = False) -> int:
        order = self.conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM projects").fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO projects (name, number, billable, color, favorite, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, number, int(billable), color, int(favorite), order))
        self.conn.commit()
        return cur.lastrowid

    def update_project(self, project_id: int, **fields) -> None:
        allowed = {"name", "number", "billable", "color", "favorite", "sort_order", "archived"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sql = ", ".join(f"{c} = ?" for c in cols)
        self.conn.execute(f"UPDATE projects SET {sql} WHERE id = ?",
                          [int(fields[c]) if isinstance(fields[c], bool) else fields[c] for c in cols]
                          + [project_id])
        self.conn.commit()

    def list_projects(self, include_archived: bool = False) -> list[sqlite3.Row]:
        where = "" if include_archived else "WHERE archived = 0"
        return self.conn.execute(f"SELECT * FROM projects {where} ORDER BY sort_order, name").fetchall()

    # --- Tätigkeiten ------------------------------------------------------
    def add_activity(self, name: str, project_id: int | None = None) -> int:
        order = self.conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM activities").fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO activities (name, project_id, sort_order) VALUES (?, ?, ?)",
            (name, project_id, order))
        self.conn.commit()
        return cur.lastrowid

    def update_activity(self, activity_id: int, **fields) -> None:
        allowed = {"name", "project_id", "sort_order", "archived"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sql = ", ".join(f"{c} = ?" for c in cols)
        self.conn.execute(f"UPDATE activities SET {sql} WHERE id = ?",
                          [fields[c] for c in cols] + [activity_id])
        self.conn.commit()

    def list_activities(self, include_archived: bool = False) -> list[sqlite3.Row]:
        where = "" if include_archived else "WHERE archived = 0"
        return self.conn.execute(f"SELECT * FROM activities {where} ORDER BY sort_order, name").fetchall()

    # --- Einstellungen / Tagesflags ----------------------------------------
    def excel_exported(self, file: str, first: str, last: str) -> dict[tuple[str, str], float]:
        """(Tag, Schlüssel) -> Stunden, die schon in diese Datei eingetragen wurden (Tage als ISO-Text)."""
        rows = self.conn.execute("SELECT day, key, hours FROM excel_exported WHERE file = ? AND day BETWEEN ? AND ?",
                                 (file.casefold(), first, last)).fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    def mark_excel_exported(self, file: str, rows: list[tuple[str, str, float]]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO excel_exported (file, day, key, hours) VALUES (?, ?, ?, ?)",
                                  [(file.casefold(), d, k, h) for d, k, h in rows])

    def clear_excel_exported(self, file: str, first: str, last: str) -> int:
        with self.conn:
            return self.conn.execute("DELETE FROM excel_exported WHERE file = ? AND day BETWEEN ? AND ?",
                                     (file.casefold(), first, last)).rowcount

    def get_setting(self, key: str) -> str:
        return self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()[0]

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
        self.conn.commit()

    def pause_disabled(self, day: date) -> bool:
        r = self.conn.execute("SELECT pause_disabled FROM day_flags WHERE day = ?",
                              (day.isoformat(),)).fetchone()
        return bool(r and r[0])

    def set_pause_disabled(self, day: date, disabled: bool) -> None:
        self.conn.execute("INSERT OR REPLACE INTO day_flags VALUES (?, ?)",
                          (day.isoformat(), int(disabled)))
        self.conn.commit()

    def outlook_imported(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT key FROM outlook_imported")}

    def mark_outlook_imported(self, keys: list[str]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO outlook_imported VALUES (?)", [(k,) for k in keys])
        self.conn.commit()

    def devops_synced(self) -> dict[int, float]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT item_id, hours FROM devops_sync")}

    def set_devops_synced(self, item_id: int, hours: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO devops_sync VALUES (?, ?)", (item_id, hours))
        self.conn.commit()

    # --- Einträge -----------------------------------------------------------
    def load_range(self, start: datetime, end: datetime) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE start_ts >= ? AND start_ts < ? ORDER BY start_ts, id",
            (_ts(start), _ts(end))).fetchall()
        return [_row_to_entry(r) for r in rows]

    def load_day(self, day: date) -> list[Entry]:
        s = datetime.combine(day, time.min)
        return self.load_range(s, s + timedelta(days=1))

    def day_ids(self, day: date) -> list[int]:
        return [e.id for e in self.load_day(day)]

    def get_entry(self, entry_id: int) -> Entry | None:
        r = self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return _row_to_entry(r) if r else None

    def running_entry(self) -> Entry | None:
        r = self.conn.execute("SELECT * FROM entries WHERE end_ts IS NULL").fetchone()
        return _row_to_entry(r) if r else None

    def save_day(self, day: date, entries: list[Entry]) -> list[Entry]:
        """Ersetzt die Einträge des Tages durch `entries`; liefert sie mit IDs zurück."""
        s = datetime.combine(day, time.min)
        existing = {r[0] for r in self.conn.execute(
            "SELECT id FROM entries WHERE start_ts >= ? AND start_ts < ?",
            (_ts(s), _ts(s + timedelta(days=1))))}
        keep = {e.id for e in entries if e.id is not None}
        out: list[Entry | None] = [None] * len(entries)
        try:
            for eid in existing - keep:
                self.conn.execute("DELETE FROM entries WHERE id = ?", (eid,))
            # erst abgeschlossene, dann der laufende Eintrag (Unique-Index)
            order = sorted(range(len(entries)), key=lambda i: entries[i].end is None)
            for i in order:
                e = entries[i]
                params = (e.kind, e.project_id, e.activity_id, e.note, _ts(e.start), _ts(e.end),
                          int(e.auto_pause), int(e.billable), _ts(e.auto_until), e.resume,
                          e.devops_id, e.devops_task_id)
                if e.id is None:
                    cur = self.conn.execute(
                        "INSERT INTO entries (kind, project_id, activity_id, note, start_ts, end_ts, "
                        "auto_pause, billable, auto_until, resume, devops_id, devops_task_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", params)
                    out[i] = replace(e, id=cur.lastrowid)
                else:
                    self.conn.execute(
                        "UPDATE entries SET kind=?, project_id=?, activity_id=?, note=?, start_ts=?, "
                        "end_ts=?, auto_pause=?, billable=?, auto_until=?, resume=?, devops_id=?, "
                        "devops_task_id=? WHERE id=?",
                        params + (e.id,))
                    out[i] = e
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return out  # type: ignore[return-value]
