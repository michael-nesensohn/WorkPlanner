"""Reine Zeitleisten-Logik (ohne UI und Datenbank).

Alle Funktionen arbeiten auf der Eintragsliste *eines Tages*, sortiert nach Start,
und geben eine neue Liste zurück. Die Eingabe wird nie verändert, so lassen sich
Änderungen vorab als Vorschau berechnen.

Regeln:
* Einträge überschneiden sich nie, nur der letzte darf laufen (end is None).
* Wird ein Ende/eine Dauer geändert, verschieben sich alle Folgeeinträge.
* Zeiten dürfen nicht in der Zukunft liegen und den Tag nicht verlassen.
* Die Mittagspause ist kein Eintrag: Sie wird erst in den Summen abgezogen (siehe TimeService).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

WORK = "work"
PAUSE = "pause"


class TimelineError(ValueError):
    """Eine Änderung würde eine ungültige Zeitleiste ergeben."""


@dataclass(frozen=True)
class Entry:
    start: datetime
    end: datetime | None = None
    kind: str = WORK
    project_id: int | None = None
    activity_id: int | None = None
    note: str = ""
    auto_pause: bool = False
    billable: bool = False
    devops_id: int | None = None        # verknüpftes DevOps-Item (Feature/Story), unabhängig von der Notiz
    devops_task_id: int | None = None   # Task, der aus der Notiz in DevOps angelegt wurde (nur auf Wunsch)
    auto_until: datetime | None = None  # läuft bis dahin, danach geht die vorherige Aufgabe weiter
    resume: str = ""                    # JSON: Aufgabe, die nach `auto_until` fortgesetzt wird
    id: int | None = None

    @property
    def running(self) -> bool:
        return self.end is None

    def duration(self, now: datetime) -> timedelta:
        return (self.end or now) - self.start

    def same_task(self, other: "Entry") -> bool:
        return (self.kind, self.project_id, self.activity_id, self.note, self.billable, self.devops_id) == (
            other.kind, other.project_id, other.activity_id, other.note, other.billable, other.devops_id)


def validate(entries: list[Entry], now: datetime | None = None) -> None:
    if not entries:
        return
    day = entries[0].start.date()
    midnight = datetime.combine(day + timedelta(days=1), time.min)
    for i, e in enumerate(entries):
        if e.start.date() != day or (e.end is not None and e.end > midnight):
            raise TimelineError("Einträge dürfen den Tag nicht verlassen.")
        if e.end is None and i != len(entries) - 1:
            raise TimelineError("Nur der letzte Eintrag darf laufen.")
        if e.end is not None and e.end <= e.start:
            raise TimelineError("Das Ende muss nach dem Start liegen.")
        if i and e.start < entries[i - 1].end:
            raise TimelineError("Einträge dürfen sich nicht überschneiden.")
        if now is not None and (e.start > now or (e.end is not None and e.end > now)):
            raise TimelineError("Zeiten dürfen nicht in der Zukunft liegen.")


def changed_times(old: list[Entry], new: list[Entry]) -> list[tuple[Entry, Entry]]:
    """Bestehende Einträge, deren Start oder Ende sich geändert hat."""
    by_id = {e.id: e for e in new if e.id is not None}
    return [(o, by_id[o.id]) for o in old
            if o.id in by_id and (o.start, o.end) != (by_id[o.id].start, by_id[o.id].end)]


def removed_entries(old: list[Entry], new: list[Entry]) -> list[Entry]:
    """Bestehende Einträge, die es nach der Änderung nicht mehr gibt."""
    kept = {e.id for e in new if e.id is not None}
    return [o for o in old if o.id is not None and o.id not in kept]


def _shift(entries: list[Entry], from_idx: int, delta: timedelta) -> list[Entry]:
    out = list(entries)
    for i in range(from_idx, len(out)):
        e = out[i]
        out[i] = replace(e, start=e.start + delta,
                         end=None if e.end is None else e.end + delta)
    return out


def _checked(entries: list[Entry], now: datetime) -> list[Entry]:
    validate(entries, now)
    return entries


def set_end(entries: list[Entry], idx: int, new_end: datetime, now: datetime) -> list[Entry]:
    """Neues Ende; alle Folgeeinträge werden um die Differenz verschoben."""
    e = entries[idx]
    if e.end is None:  # laufender Eintrag: Ende setzen = beenden
        out = list(entries)
    else:
        out = _shift(entries, idx + 1, new_end - e.end)
    out[idx] = replace(e, end=new_end)
    return _checked(out, now)


def set_duration(entries: list[Entry], idx: int, duration: timedelta, now: datetime) -> list[Entry]:
    return set_end(entries, idx, entries[idx].start + duration, now)


def set_start(entries: list[Entry], idx: int, new_start: datetime, now: datetime) -> list[Entry]:
    """Neuer Start des Eintrags.

    * später: schloss der Vorgänger bündig an, wandert sein Ende mit
    * früher: der Eintrag übernimmt die Zeit der davor liegenden Einträge. Wer vom neuen Start
      teilweise überdeckt wird, endet dort, wer ganz überdeckt wird, entfällt.
    """
    e = entries[idx]
    if new_start < e.start:
        before: list[Entry] = []
        for prev in entries[:idx]:
            if prev.end is not None and prev.end <= new_start:
                before.append(prev)                          # liegt davor, bleibt unberührt
            elif prev.start < new_start:
                before.append(replace(prev, end=new_start))  # wird gekürzt
            # sonst ganz überdeckt: entfällt
        out = before + [replace(e, start=new_start)] + entries[idx + 1:]
        return _checked(out, now)
    out = list(entries)
    if idx > 0 and entries[idx - 1].end == e.start:
        out[idx - 1] = replace(entries[idx - 1], end=new_start)
    out[idx] = replace(e, start=new_start)
    return _checked(out, now)


def _snap(entries: list[Entry], new: Entry) -> Entry:
    """Eingaben gelten nur auf die Minute, gebuchte Zeiten tragen Sekunden (z. B. Ende 09:15:42). Liegt der Start
    des neuen Eintrags in derselben Minute wie das Ende des Vorgängers (aber davor), schließt er bündig an
    (Dauer bleibt) – sonst gäbe es eine „Überschneidung“ um wenige Sekunden."""
    for e in entries:
        if e.end is not None and new.start < e.end and e.end.replace(second=0, microsecond=0) == new.start:
            delta = e.end - new.start
            return replace(new, start=e.end, end=None if new.end is None else new.end + delta)
    return new


def insert(entries: list[Entry], new: Entry, now: datetime) -> list[Entry]:
    """Fügt einen abgeschlossenen Eintrag ein; spätere Einträge rücken nach hinten."""
    if new.end is None:
        raise TimelineError("Ein eingefügter Eintrag braucht ein Ende.")
    new = _snap(entries, new)
    pos = sum(1 for e in entries if e.start < new.start)
    out = _shift(entries, pos, new.end - new.start)
    out.insert(pos, new)
    return _checked(out, now)


def insert_fit(entries: list[Entry], new: Entry, now: datetime) -> list[Entry]:
    """Wie `insert` (spätere Einträge rücken nach hinten), aber nichts wandert in die Zukunft: Was dadurch über
    „jetzt“ hinausginge, wird bei „jetzt“ gekürzt bzw. entfällt; die laufende Aufgabe beginnt dann spätestens jetzt."""
    if new.end is None:
        raise TimelineError("Ein eingefügter Eintrag braucht ein Ende.")
    new = _snap(entries, new)
    pos = sum(1 for e in entries if e.start < new.start)
    out = _shift(entries, pos, new.end - new.start)
    out.insert(pos, new)
    fitted = out[:pos + 1]
    for e in out[pos + 1:]:
        if e.running:
            fitted.append(replace(e, start=min(e.start, now)))
        elif e.start < now:
            fitted.append(replace(e, end=min(e.end, now)))
        # sonst: läge ganz in der Zukunft und entfällt
    return _checked(fitted, now)


def delete(entries: list[Entry], idx: int, now: datetime, close_gap: bool = True) -> list[Entry]:
    """Löscht einen Eintrag; Folgeeinträge rücken um seine Dauer nach vorn."""
    e = entries[idx]
    out = entries[:idx] + entries[idx + 1:]
    if close_gap and e.end is not None:
        out = _shift(out, idx, -(e.end - e.start))
    return _checked(out, now)


def start_new(entries: list[Entry], template: Entry, now: datetime) -> list[Entry]:
    """Startet eine Aufgabe jetzt und beendet die laufende im selben Moment."""
    out = list(entries)
    if out and out[-1].running:
        last = out[-1]
        if last.start >= now:
            out.pop()
        else:
            out[-1] = replace(last, end=now)
    out.append(replace(template, start=now, end=None, id=None))
    return _checked(out, now)


def place(entries: list[Entry], new: Entry, now: datetime) -> list[Entry]:
    """Setzt einen abgeschlossenen Eintrag (z. B. einen Termin) an seine Uhrzeit, ohne andere zu
    verschieben: überlappende Einträge werden gekürzt, ganz überdeckte entfallen, ein Eintrag, der
    den neuen umschließt, wird geteilt (der Rest danach läuft mit gleicher Aufgabe weiter)."""
    if new.end is None or new.end <= new.start:
        raise TimelineError("Der Termin hat keine gültige Dauer.")
    out: list[Entry] = []
    for e in entries:
        if (e.end is not None and e.end <= new.start) or e.start >= new.end:
            out.append(e)  # liegt davor oder danach
            continue
        if e.start < new.start:
            out.append(replace(e, end=new.start))                     # Anfang bleibt
        if e.end is None or e.end > new.end:
            keep_id = None if e.start < new.start else e.id           # Rest hinter dem Termin
            out.append(replace(e, start=new.end, id=keep_id))
        # sonst: ganz überdeckt -> entfällt
    out.append(new)
    out.sort(key=lambda x: x.start)
    return _checked(out, now)


def interrupt(entries: list[Entry], meeting: Entry, now: datetime) -> list[Entry]:
    """Ein Termin läuft gerade (Start ≤ jetzt < Ende): Er unterbricht die laufende Aufgabe.

    Was ab dem Terminbeginn schon gebucht wurde, wird gekürzt bzw. vom Termin übernommen. Der Termin
    läuft als laufender Eintrag; zu seinem Ende (`auto_until`) setzt sich die unterbrochene Aufgabe
    automatisch fort (siehe `resume_after_meeting`)."""
    if meeting.end is None or meeting.start > now or meeting.end <= now:
        raise TimelineError("Der Termin läuft gerade nicht.")
    resume = ""
    out: list[Entry] = []
    for e in entries:
        if e.end is not None and e.end <= meeting.start:
            out.append(e)
            continue
        if e.end is None and e.kind == WORK:
            resume = json.dumps({"project_id": e.project_id, "activity_id": e.activity_id,
                                 "note": e.note, "billable": e.billable,
                                 "devops_id": e.devops_id})
        if e.start < meeting.start:
            out.append(replace(e, end=meeting.start, auto_until=None, resume=""))
        # sonst: liegt ganz im Termin und entfällt
    out.append(replace(meeting, end=None, auto_until=meeting.end, resume=resume))
    return _checked(out, now)


def resume_after_meeting(entries: list[Entry], now: datetime) -> list[Entry]:
    """Ist ein laufender Termin zu Ende, wird er geschlossen und die unterbrochene Aufgabe läuft weiter."""
    if not entries or not entries[-1].running:
        return entries
    m = entries[-1]
    if m.auto_until is None or m.auto_until <= m.start or now < m.auto_until:
        return entries
    out = entries[:-1] + [replace(m, end=m.auto_until, auto_until=None, resume="")]
    if m.resume:
        out.append(Entry(m.auto_until, None, WORK, **json.loads(m.resume)))
    return out


def stop(entries: list[Entry], now: datetime) -> list[Entry]:
    if not entries or not entries[-1].running:
        return list(entries)
    last = entries[-1]
    out = list(entries[:-1])
    if last.start < now:
        out.append(replace(last, end=now))
    return _checked(out, now)


# --- Pause (nur noch Altbestand) --------------------------------------------
# Die Mittagspause wird nicht mehr als Eintrag eingefügt, sondern am Tagesende in der Summe abgezogen
# (siehe TimeService.work_total). Früher automatisch angelegte Pausen-Einträge lassen sich so löschen:


def remove_pause(entries: list[Entry], idx: int, now: datetime) -> list[Entry]:
    """Löscht eine Pause: der Eintrag davor reicht bis zum Folgeeintrag.

    Sind Eintrag davor und danach dieselbe Aufgabe, werden sie wieder vereint.
    """
    pause = entries[idx]
    out = entries[:idx] + entries[idx + 1:]
    if idx > 0:
        prev = out[idx - 1]
        out[idx - 1] = replace(prev, end=pause.end)
        if idx < len(out) and prev.same_task(out[idx]):
            out[idx - 1] = replace(prev, end=out[idx].end)
            del out[idx]
    return _checked(out, now)
