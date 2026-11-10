"""Gebuchte Stunden nach Azure DevOps übertragen („Completed Work“).

* Eine Zeitbuchung gehört zu einem DevOps-Item, wenn sie damit verknüpft ist (Klick auf ein Feature oder
  „Aufgabe starten“ im DevOps-Tab; per Hand über „DevOps-ID“ im Eintrag). Ältere Einträge, deren Notiz
  mit „#<ID>“ beginnt, zählen ebenfalls.
* Übertragen wird nur die **Differenz** zum letzten Mal. So bleiben Stunden anderer Personen
  in DevOps erhalten, und mehrfaches Übertragen bucht nichts doppelt.
* Hat der Typ der Story kein Feld „Completed Work“ (bei Agile/Scrum/CMMI ist das so, das Feld
  gehört zu Tasks), landet die Zeit in einem Task „WorkPlanner Zeiterfassung“ unter der Story.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .devops import COMPLETED, TASK_TITLE, DevOpsClient, DevOpsError
from .timeline import WORK, Entry

REF = re.compile(r"^\s*#(\d+)")
MIN_DELTA = 0.01  # Stunden


def item_id_from_note(note: str) -> int | None:
    m = REF.match(note or "")
    return int(m.group(1)) if m else None


def task_title(note: str, limit: int = 120) -> str:
    """Titel eines Tasks aus der Notiz: die erste nicht leere Zeile, bei Bedarf gekürzt."""
    first = next((line.strip() for line in (note or "").splitlines() if line.strip()), "")
    return first if len(first) <= limit else first[:limit - 1].rstrip() + "…"


def hours_by_item(entries: list[Entry], now: datetime, duration=None) -> dict[int, float]:
    """Stunden je DevOps-Item; `duration(entry)` kann z. B. die Mittagspause abziehen."""
    totals: dict[int, float] = {}
    for e in entries:
        if e.kind != WORK:
            continue
        # Die Verknüpfung steht im eigenen Feld; ältere Einträge hatten nur „#ID“ am Anfang der Notiz
        item = e.devops_id if e.devops_id is not None else item_id_from_note(e.note)
        if item is not None:
            totals[item] = totals.get(item, 0.0) + (duration(e) if duration else e.duration(now)).total_seconds() / 3600
    return {i: round(h, 2) for i, h in totals.items()}


@dataclass
class PlanItem:
    item_id: int
    title: str = ""
    type: str = ""
    total_h: float = 0.0        # in WorkPlanner insgesamt gebucht
    synced_h: float = 0.0       # davon bereits übertragen
    mode: str = "story"         # "story": Feld an der Story, "task": Task unter der Story
    task_id: int | None = None  # vorhandener Zeit-Task
    current_h: float = 0.0      # aktueller Wert in DevOps (Story bzw. Task)
    skip_reason: str = ""

    @property
    def delta_h(self) -> float:
        return round(self.total_h - self.synced_h, 2)

    @property
    def new_h(self) -> float:
        return round(self.current_h + self.delta_h, 2)

    @property
    def target(self) -> str:
        if self.mode == "story":
            return "Story"
        return f"Task „{TASK_TITLE}“" + ("" if self.task_id else " (wird angelegt)")


def build_plan(client: DevOpsClient, totals: dict[int, float], synced: dict[int, float]) -> list[PlanItem]:
    """Liest den Stand in DevOps und bestimmt, was übertragen würde (schreibt nichts)."""
    todo = {i: h for i, h in totals.items() if abs(round(h - synced.get(i, 0.0), 2)) >= MIN_DELTA}
    if not todo:
        return []
    info = client.completed_info(sorted(todo))
    has_field: dict[str, bool] = {}
    requirement_types: set[str] | None = None
    plan = []
    for item_id in sorted(todo):
        p = PlanItem(item_id, total_h=todo[item_id], synced_h=synced.get(item_id, 0.0))
        plan.append(p)
        f = info.get(item_id)
        if not f:
            p.skip_reason = "in DevOps nicht gefunden"
            continue
        p.title, p.type = f.get("System.Title", ""), f.get("System.WorkItemType", "")
        if p.type not in has_field:
            has_field[p.type] = client.type_has_completed_work(p.type)
        if has_field[p.type]:
            p.mode, p.current_h = "story", float(f.get(COMPLETED) or 0)
            continue
        if requirement_types is None:
            requirement_types = client.requirement_types()
        if p.type not in requirement_types:
            p.skip_reason = f"Typ „{p.type}“ kann keine Zeit aufnehmen"
            continue
        p.mode = "task"
        p.task_id, p.current_h = client.find_time_task(item_id)
        if p.task_id is None and p.delta_h < 0:
            p.skip_reason = "kein Zeit-Task vorhanden, Stunden lassen sich nicht verringern"
    return plan


def apply_plan(client: DevOpsClient, plan: list[PlanItem]) -> list[tuple[PlanItem, str | None]]:
    """Überträgt die Einträge ohne Hinderungsgrund. Ergebnis je Eintrag: None = ok, sonst Fehlertext."""
    results: list[tuple[PlanItem, str | None]] = []
    for p in plan:
        if p.skip_reason:
            continue
        try:
            if p.mode == "story":
                client.set_completed_work(p.item_id, max(p.new_h, 0.0))
            elif p.task_id:
                client.set_completed_work(p.task_id, max(p.new_h, 0.0))
            else:
                client.create_time_task(p.item_id, p.delta_h)
            results.append((p, None))
        except DevOpsError as ex:
            results.append((p, str(ex)))
    return results
