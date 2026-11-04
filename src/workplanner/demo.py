"""Beispieldaten zum Kennenlernen: ein paar Projekte, Tätigkeiten und ein Beispieltag. Alles, was hier angelegt wird, ist
vermerkt (Einstellung „demo_data“) und lässt sich genau so wieder entfernen, ohne eigene Daten anzufassen."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from .service import TimeService
from .timeline import Entry

DEMO_KEY = "demo_data"
OFFERED_KEY = "demo_offered"

PROJECTS = [  # (Name, Nummer, Farbe, verrechenbar)
    ("Beispiel Kundenprojekt", "9001", "#4f8cff", True),
    ("Beispiel Abnahmetests", "9002", "#2ea36b", True),
    ("Beispiel Meeting", "", "#d9534f", False),
    ("Beispiel Support", "9099", "#c05cc0", False),
]
ACTIVITIES = ["Programmierung", "Test", "Dokumentation", "Besprechung", "Fehlersuche", "Telefonat"]
# (Start, Ende, Projekt-Index, Tätigkeit, Notiz)
DAY = [
    ((7, 30), (9, 15), 0, "Programmierung", "Schnittstelle zur Waage umgesetzt"),
    ((9, 15), (10, 30), 1, "Test", "Testfälle für die Abnahme erstellt\nPrüfplan mit dem Kunden abgestimmt"),
    ((10, 30), (11, 15), 2, "Besprechung", "Wöchentliche Abstimmung im Team"),
    ((11, 15), (13, 0), 0, "Fehlersuche", "Fehler beim Tara-Abgleich eingegrenzt"),
    ((13, 0), (13, 40), 3, "Telefonat", "Kundenanruf: Rückfrage zur Firmware"),
    ((13, 40), (14, 22), 0, "Dokumentation", "Beschreibung der Schnittstelle"),
]


def _load(svc: TimeService) -> dict:
    try:
        data = json.loads(svc.db.get_setting(DEMO_KEY) or "{}")
    except ValueError:
        data = {}
    return {k: list(data.get(k, [])) for k in ("projects", "activities", "entries")}


def has_demo(svc: TimeService) -> bool:
    return any(_load(svc).values())


def needs_offer(svc: TimeService) -> bool:
    """Nur beim allerersten Start einer leeren Datenbank und nur einmal anbieten."""
    if svc.db.get_setting(OFFERED_KEY):
        return False
    c = svc.db.conn
    empty = not any(c.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in ("projects", "activities", "entries"))
    return empty


def mark_offered(svc: TimeService) -> None:
    svc.db.set_setting(OFFERED_KEY, "1")


def _free_day(svc: TimeService) -> date | None:
    """Heute (am Nachmittag) bzw. der letzte Tag davor ohne eigene Einträge: der Beispieltag überlagert nichts."""
    now = svc.now()
    day = now.date() if now.hour >= 15 else now.date() - timedelta(days=1)
    for _ in range(14):
        if not svc.db.day_ids(day):
            return day
        day -= timedelta(days=1)
    return None


def add_demo(svc: TimeService) -> date | None:
    """Legt Projekte, Tätigkeiten und einen Beispieltag an. Gibt den Beispieltag zurück (None: kein freier Tag in den
    letzten zwei Wochen, dann gibt es nur Projekte und Tätigkeiten)."""
    if has_demo(svc):
        raise ValueError("Beispieldaten sind schon vorhanden.")
    db = svc.db
    taken = {p["name"] for p in db.list_projects(include_archived=True)}
    created = {"projects": [], "activities": [], "entries": []}
    project_ids = []
    for name, number, color, billable in PROJECTS:
        unique = name if name not in taken else f"{name} (2)"
        pid = db.add_project(unique, color, favorite=True, number=number, billable=billable)
        project_ids.append(pid)
        created["projects"].append(pid)
        taken.add(unique)
    activity_ids = {}
    existing = {a["name"].casefold(): a["id"] for a in db.list_activities(include_archived=True)}
    for name in ACTIVITIES:
        if name.casefold() in existing:   # gibt es schon (eigene Tätigkeit): mitbenutzen, nicht anlegen und nicht löschen
            activity_ids[name] = existing[name.casefold()]
        else:
            aid = db.add_activity(name)
            activity_ids[name] = aid
            created["activities"].append(aid)
    day = _free_day(svc)
    if day is not None:
        entries = [Entry(datetime.combine(day, time(*start)), datetime.combine(day, time(*end)),
                         project_id=project_ids[p], activity_id=activity_ids[act], note=note,
                         billable=PROJECTS[p][3])
                   for start, end, p, act, note in DAY]
        created["entries"] = [e.id for e in db.save_day(day, entries)]
    db.set_setting(DEMO_KEY, json.dumps(created))
    return day


def remove_demo(svc: TimeService) -> dict[str, int]:
    """Entfernt genau die Beispieldaten. Projekte oder Tätigkeiten, auf die inzwischen eigene Einträge zeigen, werden
    nicht gelöscht, sondern archiviert (die Einträge bleiben unverändert)."""
    data = _load(svc)
    db, c = svc.db, svc.db.conn
    result = {"entries": 0, "projects": 0, "activities": 0, "archived": 0}
    for eid in data["entries"]:
        result["entries"] += c.execute("DELETE FROM entries WHERE id = ?", (eid,)).rowcount
    for table, column, key in (("activities", "activity_id", "activities"), ("projects", "project_id", "projects")):
        for rid in data[key]:
            if c.execute(f"SELECT 1 FROM entries WHERE {column} = ? LIMIT 1", (rid,)).fetchone():
                c.execute(f"UPDATE {table} SET archived = 1 WHERE id = ?", (rid,))
                result["archived"] += 1
            else:
                result[key] += c.execute(f"DELETE FROM {table} WHERE id = ?", (rid,)).rowcount
    c.commit()
    db.set_setting(DEMO_KEY, "")
    return result
