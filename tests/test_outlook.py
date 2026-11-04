from datetime import date, datetime

import pytest

from test_service import DAY, Clock
from test_timeline import D, NOW, e, t, times
from workplanner import timeline as tl
from workplanner.db import Database
from workplanner.outlook import Appointment, OutlookError, read_appointments
from workplanner.service import TimeService
from workplanner.timeline import PAUSE, TimelineError, Entry


# --- timeline.place ---------------------------------------------------------------------

def meeting(sh, sm, eh, em):
    return Entry(t(sh, sm), t(eh, em), project_id=9, note="Termin")


def test_place_into_free_time_keeps_everything_else():
    out = tl.place([e(8, 0, 9, 0), e(11, 0, 12, 0)], meeting(9, 30, 10, 30), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:30", "10:30"), ("11:00", "12:00")]


def test_place_trims_overlaps_and_removes_covered_entries():
    day = [e(8, 0, 9, 30, id=1), e(9, 30, 10, 0, id=2), e(10, 0, 11, 30, id=3)]
    out = tl.place(day, meeting(9, 0, 11, 0), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:00", "11:00"), ("11:00", "11:30")]
    assert [x.id for x in out] == [1, None, 3]          # 2 entfällt, 3 behält seine ID (nur Anfang gekürzt)
    assert [x.id for x in tl.removed_entries(day, out)] == [2]


def test_place_inside_an_entry_splits_it_and_keeps_task():
    day = [e(8, 0, 12, 0, id=1, note="Arbeit")]
    out = tl.place(day, meeting(9, 0, 10, 0), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:00", "10:00"), ("10:00", "12:00")]
    assert [x.note for x in out] == ["Arbeit", "Termin", "Arbeit"]
    assert out[0].id == 1 and out[2].id is None


def test_place_inside_running_entry_resumes_it_afterwards():
    out = tl.place([e(8, 0, None, note="Arbeit")], meeting(9, 0, 10, 0), t(11))
    assert times(out) == [("08:00", "09:00"), ("09:00", "10:00"), ("10:00", None)]
    assert out[2].running and out[2].note == "Arbeit"


def test_place_rejects_future_and_empty_meetings():
    with pytest.raises(TimelineError, match="Zukunft"):
        tl.place([], meeting(17, 0, 19, 0), NOW)
    with pytest.raises(TimelineError, match="Dauer"):
        tl.place([], Entry(t(9), t(9)), NOW)


# --- Outlook lesen (COM nachgebaut) -----------------------------------------------------

class FakeItem:
    def __init__(self, subject, start, end, entry_id="E1", **kw):
        self.Subject, self.Start, self.End, self.EntryID = subject, start, end, entry_id
        self.Class, self.AllDayEvent, self.Location = 26, kw.get("all_day", False), kw.get("location", "")
        self.BusyStatus, self.ResponseStatus = kw.get("busy", 2), kw.get("response", 3)
        self.MeetingStatus = kw.get("meeting", 1)


class FakeItems:
    def __init__(self, items, restrict_fails=False, restrict_empty=False):
        self.items, self.restrict_fails, self.restrict_empty = items, restrict_fails, restrict_empty
        self.IncludeRecurrences, self.sorted_by, self.filter = False, None, None

    def Sort(self, field):
        self.sorted_by = field

    def Restrict(self, flt):
        self.filter = flt
        if self.restrict_fails:
            raise RuntimeError("Datumsformat")
        return FakeItems([] if self.restrict_empty else self.items)

    def __iter__(self):
        return iter(self.items)


class FakeOutlook:
    def __init__(self, items):
        self.cal = items

    def GetNamespace(self, _):
        outer = self

        class Ns:
            def GetDefaultFolder(self, n):
                assert n == 9

                class Folder:
                    Items = outer.cal
                return Folder()
        return Ns()


def dt(h, m=0, day=2):
    return datetime(2026, 11, day, h, m)


def test_read_filters_range_sorts_and_flags():
    cal = FakeItems([
        FakeItem("Gestern", dt(9, day=1), dt(10, day=1), "A"),
        FakeItem("Daily", dt(9), dt(9, 15), "B", location="Teams"),
        FakeItem("Frei", dt(10), dt(11), "C", busy=0),
        FakeItem("Abgesagt", dt(12), dt(13), "D", response=4),
        FakeItem("Storniert", dt(13), dt(14), "G", meeting=5),
        FakeItem("Urlaub", dt(0), dt(0, day=3), "E", all_day=True),
        FakeItem("Morgen", dt(9, day=4), dt(10, day=4), "F"),
    ])
    got = read_appointments(date(2026, 11, 2), date(2026, 11, 3), app=FakeOutlook(cal))
    assert [a.subject for a in got] == ["Urlaub", "Daily", "Frei", "Abgesagt", "Storniert"]
    assert cal.IncludeRecurrences is True and cal.sorted_by == "[Start]"
    by = {a.subject: a for a in got}
    assert by["Daily"].location == "Teams" and not by["Daily"].free
    assert by["Frei"].free and by["Abgesagt"].declined and by["Storniert"].declined
    assert by["Urlaub"].all_day
    assert by["Daily"].key == "B|20261102T0900"


def test_read_falls_back_when_restrict_fails_or_returns_nothing():
    for kw in ({"restrict_fails": True}, {"restrict_empty": True}):
        cal = FakeItems([FakeItem("Daily", dt(9), dt(9, 15), "B")], **kw)
        got = read_appointments(date(2026, 11, 2), date(2026, 11, 2), app=FakeOutlook(cal))
        assert [a.subject for a in got] == ["Daily"]


def test_read_error_is_readable():
    class Broken:
        def GetNamespace(self, _):
            raise RuntimeError("RPC nicht verfügbar")
    with pytest.raises(OutlookError, match="nicht gelesen"):
        read_appointments(DAY, DAY, app=Broken())


# --- Service: Import ------------------------------------------------------------------------

def ap(key, subject, sh, sm, eh, em):
    return Appointment(key, subject, dt(sh, sm), dt(eh, em))


@pytest.fixture
def env():
    db = Database()
    clock = Clock(15, 0)
    svc = TimeService(db, clock)
    return svc, clock, db, db.add_project("Meeting", billable=True)


def rows(svc):
    return [(x.start.strftime("%H:%M"), x.end.strftime("%H:%M") if x.end else None, x.note, x.billable)
            for x in svc.day_entries(DAY)]


def test_import_creates_entries_and_remembers_keys(env):
    svc, clock, db, pid = env
    items = [ap("k1", "Daily", 9, 0, 9, 15), ap("k2", "Review", 14, 0, 14, 45)]
    svc.apply_import(items, pid, None)
    assert rows(svc) == [("09:00", "09:15", "Daily", True), ("14:00", "14:45", "Review", True)]
    assert svc.outlook_imported() == {"k1", "k2"}


def test_import_cuts_existing_entries_and_preview_does_not_write(env):
    svc, clock, db, pid = env
    other = db.add_project("Projekt")
    clock.set(8)
    svc.start_task(other, None, "Arbeit")
    clock.set(15)
    svc.stop()                                   # 08:00-15:00 (die Mittagspause wird nur abgezogen)
    before = rows(svc)
    plan = svc.preview_import([ap("k1", "Workshop", 10, 0, 11, 0)], pid, None)
    assert rows(svc) == before and svc.outlook_imported() == set()
    (old, new), = plan.values()
    assert [x.note for x in new if x.note == "Workshop"] == ["Workshop"]
    svc.apply_import([ap("k1", "Workshop", 10, 0, 11, 0)], pid, None)
    notes = [(r[0], r[1], r[2]) for r in rows(svc)]
    assert notes == [("08:00", "10:00", "Arbeit"), ("10:00", "11:00", "Workshop"), ("11:00", "15:00", "Arbeit")]


def test_import_clips_meeting_at_midnight_and_overlapping_meetings_later_wins(env):
    svc, clock, db, pid = env
    svc.apply_import([ap("a", "Lang", 9, 0, 11, 0), ap("b", "Kurz", 10, 0, 10, 30)], pid, None)
    assert [(r[0], r[1], r[2]) for r in rows(svc)] == [
        ("09:00", "10:00", "Lang"), ("10:00", "10:30", "Kurz"), ("10:30", "11:00", "Lang")]


def test_import_failure_writes_nothing(env):
    svc, clock, db, pid = env
    future = ap("z", "Später", 17, 0, 18, 0)         # liegt nach „jetzt“ (15:00)
    with pytest.raises(TimelineError):
        svc.apply_import([ap("a", "Daily", 9, 0, 9, 15), future], pid, None)
    assert rows(svc) == [] and svc.outlook_imported() == set()


# --- Laufender Termin unterbricht die Aufgabe, danach geht sie weiter -------------------------------

def running(sh, sm, note="Arbeit", project=1, **kw):
    return Entry(t(sh, sm), None, project_id=project, note=note, **kw)


def ongoing_meeting(sh, sm, eh, em):
    return Entry(t(sh, sm), t(eh, em), project_id=9, note="Termin")


def test_interrupt_splits_running_task_and_remembers_it():
    out = tl.interrupt([running(9, 0, id=1)], ongoing_meeting(10, 0, 11, 0), t(10, 20))
    assert times(out) == [("09:00", "10:00"), ("10:00", None)]
    assert out[1].note == "Termin" and out[1].auto_until == t(11) and out[0].id == 1
    assert '"note": "Arbeit"' in out[1].resume


def test_resume_after_meeting_end_closes_meeting_and_continues_task():
    interrupted = tl.interrupt([running(9, 0)], ongoing_meeting(10, 0, 11, 0), t(10, 20))
    assert tl.resume_after_meeting(interrupted, t(10, 59)) == interrupted          # noch nicht zu Ende
    out = tl.resume_after_meeting(interrupted, t(11, 5))
    assert times(out) == [("09:00", "10:00"), ("10:00", "11:00"), ("11:00", None)]
    assert [x.note for x in out] == ["Arbeit", "Termin", "Arbeit"] and out[2].running
    assert out[1].auto_until is None and out[2].auto_until is None


def test_interrupt_when_task_started_inside_the_meeting_still_resumes_it():
    day = [e(8, 0, 9, 30, id=1), running(10, 10, "Später gestartet", id=2)]
    out = tl.interrupt(day, ongoing_meeting(10, 0, 11, 0), t(10, 30))
    assert times(out) == [("08:00", "09:30"), ("10:00", None)]              # 10:10-Aufgabe liegt im Termin
    assert [x.id for x in tl.removed_entries(day, out)] == [2]
    after = tl.resume_after_meeting(out, t(11, 1))
    assert after[-1].note == "Später gestartet" and after[-1].start == t(11)


def test_interrupt_without_running_task_just_runs_the_meeting():
    out = tl.interrupt([e(8, 0, 9, 0)], ongoing_meeting(10, 0, 11, 0), t(10, 5))
    assert times(out) == [("08:00", "09:00"), ("10:00", None)] and out[1].resume == ""
    after = tl.resume_after_meeting(out, t(11, 30))
    assert times(after) == [("08:00", "09:00"), ("10:00", "11:00")]


def test_interrupt_rejects_meetings_that_are_not_running():
    with pytest.raises(TimelineError):
        tl.interrupt([], ongoing_meeting(10, 0, 11, 0), t(9, 30))             # noch nicht begonnen
    with pytest.raises(TimelineError):
        tl.interrupt([], ongoing_meeting(10, 0, 11, 0), t(11, 30))            # schon vorbei


def test_new_task_while_meeting_runs_cancels_the_automatic_resume():
    interrupted = tl.interrupt([running(9, 0)], ongoing_meeting(10, 0, 11, 0), t(10, 20))
    switched = tl.start_new(interrupted, Entry(t(0), project_id=5, note="Anderes"), t(10, 40))
    after = tl.resume_after_meeting(switched, t(11, 30))
    assert after == switched and after[-1].note == "Anderes" and after[-1].running


def test_service_interrupts_current_task_persists_and_resumes_via_tick(env):
    svc, clock, db, pid = env
    work = db.add_project("Projekt")
    clock.set(9)
    svc.start_task(work, None, "Waage lesen")
    clock.set(10, 20)
    meeting_item = Appointment("m1", "Review", dt(10, 0), dt(11, 0))
    plan = svc.preview_import([meeting_item], pid, None)
    assert rows(svc)[0][1] is None                                          # Vorschau schreibt nichts
    svc.apply_import([meeting_item], pid, None)
    cur = svc.current()
    assert cur.note == "Review" and cur.auto_until == dt(11) and svc.outlook_imported() == {"m1"}
    assert [(r[0], r[1], r[2]) for r in rows(svc)] == [("09:00", "10:00", "Waage lesen"), ("10:00", None, "Review")]
    clock.set(10, 59)
    assert svc.tick() is False and svc.current().note == "Review"
    clock.set(11, 2)
    assert svc.tick() is True
    assert [(r[0], r[1], r[2]) for r in rows(svc)] == [
        ("09:00", "10:00", "Waage lesen"), ("10:00", "11:00", "Review"), ("11:00", None, "Waage lesen")]
    assert svc.current().project_id == work and svc.tick() is False


def test_service_rejects_two_running_meetings_at_once(env):
    svc, clock, db, pid = env
    clock.set(10, 20)
    with pytest.raises(TimelineError, match="ein noch laufender"):
        svc.apply_import([ap("a", "A", 10, 0, 11, 0), ap("b", "B", 10, 15, 10, 45)], pid, None)
    assert rows(svc) == []


def test_old_database_gets_the_new_columns(tmp_path):
    import sqlite3
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'work', "
                    "project_id INTEGER, activity_id INTEGER, note TEXT NOT NULL DEFAULT '', "
                    "start_ts TEXT NOT NULL, end_ts TEXT, auto_pause INTEGER NOT NULL DEFAULT 0);"
                    "INSERT INTO entries (start_ts) VALUES ('2026-11-02T08:00:00');")
    c.commit()
    c.close()
    db = Database(old)
    (e,) = db.load_day(date(2026, 11, 2))
    assert e.auto_until is None and e.resume == "" and e.billable is False
