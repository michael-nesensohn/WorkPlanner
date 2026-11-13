from datetime import date, datetime, time, timedelta

import pytest

from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.timeline import PAUSE, WORK, Entry, TimelineError

DAY = date(2026, 11, 2)


class Clock:
    def __init__(self, h=8, m=0):
        self.t = datetime(2026, 11, 2, h, m)

    def __call__(self):
        return self.t

    def set(self, h, m=0):
        self.t = datetime(2026, 11, 2, h, m)


@pytest.fixture
def env():
    db = Database()
    clock = Clock()
    svc = TimeService(db, clock)
    a = db.add_project("A")
    b = db.add_project("B")
    act = db.add_activity("Programmierung")
    return svc, clock, a, b, act


def rows(svc):
    return [(e.start.strftime("%H:%M"), e.end.strftime("%H:%M") if e.end else None,
             e.kind, e.project_id) for e in svc.day_entries(DAY)]


def test_only_one_task_runs(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9, 15)
    svc.start_task(b, act)
    assert rows(svc) == [("08:00", "09:15", WORK, a), ("09:15", None, WORK, b)]
    assert svc.db.conn.execute("SELECT COUNT(*) FROM entries WHERE end_ts IS NULL").fetchone()[0] == 1


def test_edit_shifts_all_followers_and_persists(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9)
    svc.start_task(b, act)
    clock.set(10)
    svc.start_task(a, act)
    clock.set(11)
    first = svc.day_entries(DAY)[0]
    svc.edit_entry(first.id, {"end": datetime(2026, 11, 2, 8, 30)})
    assert rows(svc) == [("08:00", "08:30", WORK, a), ("08:30", "09:30", WORK, b),
                         ("09:30", None, WORK, a)]


def test_preview_does_not_save(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9)
    svc.start_task(b, act)
    first = svc.day_entries(DAY)[0]
    old, new = svc.preview_edit(first.id, {"end": datetime(2026, 11, 2, 8, 30)})
    assert new[1].start.hour == 8 and new[1].start.minute == 30
    assert rows(svc)[0][1] == "09:00"


def test_invalid_edit_raises_and_changes_nothing(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9)
    svc.start_task(b, act)
    clock.set(9, 30)
    first = svc.day_entries(DAY)[0]
    with pytest.raises(TimelineError):
        svc.edit_entry(first.id, {"end": datetime(2026, 11, 2, 9, 40)})  # schiebt in die Zukunft
    assert rows(svc)[0][1] == "09:00"


def test_lunch_is_deducted_in_totals_not_inserted_as_entry(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act, "Waage")
    clock.set(13)
    assert svc.tick() is False                       # keine Automatik mehr: nichts wird eingefügt oder geteilt
    assert rows(svc) == [("08:00", None, WORK, a)]
    e = svc.day_entries(DAY)
    assert svc.work_total(e) == timedelta(hours=4, minutes=30)       # 5 h minus 30 min Mittagspause
    assert svc.lunch_total(e) == timedelta(minutes=30)
    assert svc.net_duration(e[0]) == timedelta(hours=4, minutes=30)
    (row,) = svc.report_rows(DAY, DAY)
    assert row["duration"] == timedelta(hours=4, minutes=30) and row["lunch"] == timedelta(minutes=30)


@pytest.mark.parametrize("start,end,expected_minutes", [
    ((8, 0), (11, 59), 0), ((11, 0), (12, 10), 10), ((12, 10), (13, 0), 20),
    ((12, 0), (12, 30), 30), ((12, 30), (14, 0), 0), ((11, 0), (14, 0), 30)])
def test_lunch_deduction_is_the_overlap_with_the_window(env, start, end, expected_minutes):
    svc, clock, a, b, act = env
    clock.set(15)
    db = svc.db
    db.save_day(DAY, [Entry(datetime(2026, 11, 2, *start), datetime(2026, 11, 2, *end), project_id=a)])
    (e,) = svc.day_entries(DAY)
    assert svc.lunch_total([e]) == timedelta(minutes=expected_minutes)
    assert svc.work_total([e]) == (e.end - e.start) - timedelta(minutes=expected_minutes)


def test_lunch_deduction_is_shared_between_entries_around_the_window(env):
    svc, clock, a, b, act = env
    clock.set(15)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(11), d(12, 15), project_id=a), Entry(d(12, 15), d(14), project_id=b)])
    e = svc.day_entries(DAY)
    assert svc.lunch_total(e) == timedelta(minutes=30)               # 15 + 15, nie mehr als die Pausendauer
    assert svc.work_total(e) == timedelta(hours=3) - timedelta(minutes=30)


def test_running_entry_is_deducted_while_it_passes_the_lunch_window(env):
    svc, clock, a, b, act = env
    clock.set(11)
    svc.start_task(a, act)
    for (h, m), net in (((11, 59), 59), ((12, 10), 60), ((12, 30), 60 + 0), ((13, 0), 90)):
        clock.set(h, m)
        assert svc.work_total(svc.day_entries(DAY)) == timedelta(minutes=net), (h, m)


def test_no_deduction_when_switched_off_for_the_day_or_zero_length(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(13)
    full = timedelta(hours=5)
    assert svc.work_total(svc.day_entries(DAY)) == full - timedelta(minutes=30)
    svc.remove_pause(DAY)                            # „Mittagspause für diesen Tag nicht abziehen“
    assert svc.pause_disabled(DAY) and svc.work_total(svc.day_entries(DAY)) == full
    svc.restore_pause(DAY)
    assert svc.work_total(svc.day_entries(DAY)) == full - timedelta(minutes=30)
    svc.set_pause(time(12, 0), 0)                    # 0 min = nie abziehen
    assert svc.work_total(svc.day_entries(DAY)) == full
    svc.set_pause(time(12, 30), 45)                  # anderes Fenster 12:30-13:15
    assert svc.work_total(svc.day_entries(DAY)) == full - timedelta(minutes=30)


def test_deduction_only_on_the_day_it_belongs_to(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(13)
    svc.stop()
    svc.remove_pause(DAY)
    other = date(2026, 11, 3)
    svc.db.save_day(other, [Entry(datetime(2026, 11, 3, 8), datetime(2026, 11, 3, 13), project_id=a)])
    assert svc.work_total(svc.day_entries(other)) == timedelta(hours=4, minutes=30)   # anderer Tag: weiter abgezogen
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=5)


def test_devops_hours_exclude_the_lunch_break(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act, devops_id=21)
    clock.set(13)
    svc.stop()
    assert svc.devops_hours() == {21: 4.5}


def test_stopping_over_lunch_does_not_create_pause_entries(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(12, 10)
    svc.tick()
    svc.stop()
    clock.set(13)
    svc.tick()
    assert svc.current() is None
    assert rows(svc) == [("08:00", "12:10", WORK, a)]


def test_remove_pause_also_removes_legacy_pause_entries(env):
    """Früher wurde die Pause als Eintrag eingefügt; „nicht abziehen“ räumt solche Altlasten auf."""
    svc, clock, a, b, act = env
    clock.set(15)
    svc.db.save_day(DAY, [Entry(datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 12), project_id=a),
                          Entry(datetime(2026, 11, 2, 12), datetime(2026, 11, 2, 12, 30), kind=PAUSE,
                                auto_pause=True),
                          Entry(datetime(2026, 11, 2, 12, 30), datetime(2026, 11, 2, 14), project_id=a)])
    svc.remove_pause(DAY)
    assert rows(svc) == [("08:00", "14:00", WORK, a)] and svc.pause_disabled(DAY)


def test_delete_entry_pulls_followers_forward(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9)
    svc.start_task(b, act)
    clock.set(10)
    svc.start_task(a, act)
    clock.set(11)
    svc.delete_entry(svc.day_entries(DAY)[1].id)
    assert rows(svc) == [("08:00", "09:00", WORK, a), ("09:00", None, WORK, a)]


def test_report_rows_filter_by_project(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.set(9)
    svc.start_task(b, act)
    clock.set(10)
    assert len(svc.report_rows(DAY, DAY)) == 2
    only_b = svc.report_rows(DAY, DAY, b)
    assert [r["project"] for r in only_b] == ["B"]
    assert only_b[0]["duration"] == timedelta(hours=1)


def test_stale_running_entry_closed_at_midnight(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act)
    clock.t = datetime(2026, 11, 3, 7, 0)
    svc.tick()
    assert svc.current() is None
    assert svc.day_entries(DAY)[-1].end == datetime(2026, 11, 3, 0, 0)


def test_project_number_display_and_migration(tmp_path):
    import sqlite3
    old = tmp_path / "old.db"
    c = sqlite3.connect(old)
    c.executescript("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
                    "color TEXT NOT NULL DEFAULT '#4f8cff', favorite INTEGER NOT NULL DEFAULT 1, "
                    "sort_order INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);"
                    "INSERT INTO projects (name) VALUES ('Alt');")
    c.commit()
    c.close()
    db = Database(old)
    svc = TimeService(db, Clock())
    alt = svc.projects()[0]["id"]
    assert svc.project_display(alt) == "Alt"
    db.update_project(alt, number="4711")
    assert svc.project_display(alt) == "4711  Alt"


def test_add_project_skips_existing_name_or_number(env):
    svc, clock, a, b, act = env
    pid = svc.add_project("Neu", "4711")
    assert pid is not None and svc.project_number(pid) == "4711"
    assert svc.add_project("neu", "") is None       # Name (ohne Beachtung der Schreibweise)
    assert svc.add_project("Anders", "4711") is None  # Nummer
    assert svc.find_project(number="4711") == pid


def test_delete_several_entries_shifts_followers_by_the_sum(env):
    svc, clock, a, b, act = env
    for h, p in ((8, a), (9, b), (10, a), (11, b)):
        clock.set(h)
        svc.start_task(p, act)
    clock.set(12)
    svc.stop()                       # 4 Einträge à 1 h: 8-9, 9-10, 10-11, 11-12
    e = svc.day_entries(DAY)
    svc.delete_entries([e[2].id, e[1].id])   # Reihenfolge der Auswahl egal
    assert rows(svc) == [("08:00", "09:00", WORK, a), ("09:00", "10:00", WORK, b)]


def test_delete_several_with_legacy_pause_and_running_entry(env):
    svc, clock, a, b, act = env
    clock.set(13)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(8), d(12), project_id=a),
                          Entry(d(12), d(12, 30), kind=PAUSE, auto_pause=True),
                          Entry(d(12, 30), None, project_id=a)])
    e = svc.day_entries(DAY)
    assert [x.kind for x in e] == [WORK, PAUSE, WORK]
    svc.delete_entries([e[1].id, e[2].id])
    assert rows(svc) == [("08:00", "12:30", WORK, a)]  # Pause entfernt, Vorgänger verlängert
    assert svc.pause_disabled(DAY)




def test_target_end_counts_the_lunch_break_still_ahead(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act)
    e = lambda: svc.day_entries(DAY)  # noqa: E731
    assert svc.target_end(e()) == datetime(2026, 11, 2, 16, 30)     # 8 h Soll + 30 min Pause davor
    clock.set(10)
    assert svc.target_end(e()) == datetime(2026, 11, 2, 16, 30)
    clock.set(12, 10)                                               # mitten in der Pause: 4:00 gearbeitet
    assert svc.work_total(e()) == timedelta(hours=4)
    assert svc.target_end(e()) == datetime(2026, 11, 2, 16, 30)
    clock.set(13)                                                   # Pause liegt hinter uns
    assert svc.target_end(e()) == datetime(2026, 11, 2, 16, 30)


def test_target_end_without_lunch_and_when_reached(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act)
    svc.remove_pause(DAY)                                            # für den Tag keine Pause abziehen
    assert svc.target_end(svc.day_entries(DAY)) == datetime(2026, 11, 2, 16, 0)
    clock.set(16, 0)
    assert svc.target_end(svc.day_entries(DAY)) is None              # Soll erreicht
    svc.restore_pause(DAY)
    assert svc.target_end(svc.day_entries(DAY)) is not None          # mit Pause fehlen noch 30 min
    assert svc.target_end(svc.day_entries(DAY)) == datetime(2026, 11, 2, 16, 30)


def test_target_end_starts_from_now_when_nothing_runs(env):
    svc, clock, a, b, act = env
    clock.set(9)
    svc.start_task(a, act)
    clock.set(10)
    svc.stop()                                                       # 1 h gearbeitet
    clock.set(14)
    assert svc.target_end(svc.day_entries(DAY)) == datetime(2026, 11, 2, 21, 0)   # 7 h fehlen, Pause schon vorbei


@pytest.mark.parametrize("new_start,new_end,expected", [
    # ganz nach hinten: der bündige Vorgänger füllt die Lücke, die Folgeeinträge rücken mit
    ((10, 0), (11, 0), [("07:00", "10:00"), ("10:00", "11:00"), ("11:00", "12:00")]),
    # ganz nach vorn: überdeckt den Vorgänger, der bleibt erhalten (behält seine Dauer, folgt danach)
    ((6, 0), (7, 0), [("06:00", "07:00"), ("07:00", "08:00"), ("08:00", "09:00")]),
    # überlappend nach hinten
    ((8, 30), (9, 30), [("07:00", "08:30"), ("08:30", "09:30"), ("09:30", "10:30")]),
    # kürzer
    ((8, 15), (8, 45), [("07:00", "08:15"), ("08:15", "08:45"), ("08:45", "09:45")]),
])
def test_moving_an_entry_as_a_whole_changes_start_and_end_in_one_go(env, new_start, new_end, expected):
    svc, clock, a, b, act = env
    clock.set(15)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(7), d(8), project_id=a, note="vor"), Entry(d(8), d(9), project_id=a, note="x"),
                          Entry(d(9), d(10), project_id=b, note="nach")])
    x = svc.day_entries(DAY)[1]
    svc.edit_entry(x.id, {"start": d(*new_start), "end": d(*new_end)})
    assert [(r[0], r[1]) for r in rows(svc)] == expected


def test_manual_entry_while_a_task_runs_stops_it_and_it_runs_on_afterwards(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act, "Arbeit")           # 08:00 läuft
    clock.set(11)
    svc.insert_entry(Entry(datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 10), project_id=b, note="Termin"))
    assert rows(svc) == [("08:00", "09:00", WORK, a), ("09:00", "10:00", WORK, b), ("10:00", None, WORK, a)]
    assert svc.current().note == "Arbeit"      # läuft mit derselben Aufgabe weiter


def test_manual_entry_that_is_happening_now_resumes_the_running_task_afterwards(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act, "Arbeit")
    clock.set(10)
    svc.insert_entry(Entry(datetime(2026, 11, 2, 9, 30), datetime(2026, 11, 2, 10, 30), project_id=b, note="Call"))
    assert rows(svc) == [("08:00", "09:30", WORK, a), ("09:30", None, WORK, b)]
    clock.set(10, 31)
    svc.tick()
    assert rows(svc) == [("08:00", "09:30", WORK, a), ("09:30", "10:30", WORK, b), ("10:30", None, WORK, a)]


def test_manual_entry_shifts_followers_and_running_start_never_goes_into_the_future(env):
    svc, clock, a, b, act = env
    svc.start_task(a, act, "A")                # 08:00
    clock.set(9)
    svc.start_task(b, act, "B")                # 09:00, läuft
    clock.set(10)
    # 30 Minuten um 09:00 einfügen: B (läuft) rückt auf 09:30, das liegt vor „jetzt“ 10:00
    svc.insert_entry(Entry(datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 9, 30), project_id=a, note="neu"))
    assert rows(svc) == [("08:00", "09:00", WORK, a), ("09:00", "09:30", WORK, a), ("09:30", None, WORK, b)]
    # Eintrag, der B über „jetzt“ hinausschieben würde: Start von B wird auf jetzt begrenzt
    svc.insert_entry(Entry(datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 10), project_id=b, note="lang"))
    got = rows(svc)
    assert got[-1] == ("10:00", None, WORK, b) and all(r[1] is None or r[1] <= "10:00" for r in got)


def test_manual_entry_starting_at_a_minute_boundary_fits_after_an_entry_ending_with_seconds(env):
    svc, clock, a, b, act = env
    clock.t = datetime(2026, 11, 2, 7, 18, 20)
    svc.start_task(a, act, "früh")
    clock.t = datetime(2026, 11, 2, 9, 15, 42)       # Ende des ersten und Start des zweiten mit Sekunden
    svc.start_task(b, act, "läuft")
    clock.set(11, 15)
    svc.insert_entry(Entry(datetime(2026, 11, 2, 9, 15), datetime(2026, 11, 2, 10, 15), project_id=a, note="neu"))
    got = svc.day_entries(DAY)
    assert [(e.note, e.start.strftime("%H:%M:%S")) for e in got] == [
        ("früh", "07:18:20"), ("neu", "09:15:42"), ("läuft", "10:15:42")]
    assert got[1].end - got[1].start == timedelta(hours=1)


def test_pause_entry_replaces_the_lunch_deduction_and_ends_with_the_task_running(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(12, 0)
    assert svc.lunch_state(DAY) == "auto"
    svc.start_pause()
    clock.set(12, 40)
    svc.end_pause()
    run = svc.current()
    assert run.kind == WORK and run.note == "Arbeit"
    assert svc.lunch_state(DAY) == "paused" and svc.lunch_window(DAY) is None   # 40 min Pause ≥ 30 min: kein Abzug mehr
    clock.set(13, 0)
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=4) + timedelta(minutes=20)   # 8–12 + 12:40–13:00


def test_partial_pause_only_deducts_the_rest_of_the_lunch_time(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(12, 0)
    svc.start_pause()
    clock.set(12, 10)
    svc.end_pause()
    clock.set(13, 0)
    assert svc.paused_total(DAY) == timedelta(minutes=10)
    # Arbeit 8–12 (4 h) + 12:10–13:00 (50 min), davon 20 min Rest der Mittagspause abgezogen
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=4, minutes=30)


def test_lunch_prompt_only_in_ask_mode_while_a_task_runs_and_without_a_pause(env):
    svc, clock, a, b, act = env
    clock.set(11, 0)
    svc.start_task(a, act, "Arbeit")
    clock.set(12, 5)
    assert svc.lunch_mode == "ask" and svc.lunch_prompt_due()   # Standard: nachfragen
    svc.set_lunch_mode("off")
    assert not svc.lunch_prompt_due()                     # Kein Pausenabzug: keine Nachfrage
    svc.db.set_setting("lunch_mode", "deduct")            # alter Wert „nur abziehen“ gilt als „nachfragen“
    assert svc.lunch_mode == "ask" and svc.lunch_prompt_due()
    clock.set(11, 59)
    assert not svc.lunch_prompt_due()
    clock.set(12, 5)
    svc.start_pause(30)
    assert not svc.lunch_prompt_due()                     # es gibt schon eine Pause


def test_edit_start_and_end_earlier_in_one_go_does_not_trip_over_the_future(env):
    """Früherer Start UND früheres Ende: der Zwischenstand (Eintrag bis zum alten Ende, überdeckte dahinter) läge
    kurz in der Zukunft, das Endergebnis ist gültig."""
    svc, clock, a, b, act = env
    clock.set(12, 45)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(8), d(12), project_id=a, note="A"), Entry(d(12), d(12, 10), project_id=a, note="B"),
                          Entry(d(12, 10), d(12, 40), kind=PAUSE), Entry(d(12, 40), None, project_id=a, note="R")])
    pause = svc.day_entries(DAY)[2]
    svc.edit_entry(pause.id, {"start": d(11, 46), "end": d(12, 15)})
    assert [(r[0], r[1], r[2]) for r in rows(svc)] == [
        ("08:00", "11:46", "work"), ("11:46", "12:15", "pause"), ("12:15", "12:25", "work"), ("12:25", None, "work")]


def test_moving_an_entry_into_the_middle_of_a_task_splits_that_task(env):
    """Eine Pause in eine lange Aufgabe gelegt: die Aufgabe wird aufgetrennt und läuft danach weiter."""
    svc, clock, a, b, act = env
    clock.set(14, 47)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(9, 30), d(14, 32), project_id=a, note="Elektrik"),
                          Entry(d(14, 32), d(14, 34), project_id=b, note="B"),
                          Entry(d(14, 34), d(14, 46), kind=PAUSE), Entry(d(14, 46), None, project_id=a, note="R")])
    pause = svc.day_entries(DAY)[2]
    svc.edit_entry(pause.id, {"start": d(11, 46), "end": d(12, 15)})
    out = svc.day_entries(DAY)
    assert [(r[0], r[1], r[2]) for r in rows(svc)] == [
        ("09:30", "11:46", "work"), ("11:46", "12:15", "pause"), ("12:15", "14:32", "work"),
        ("14:32", "14:34", "work"), ("14:46", None, "work")]
    assert out[0].note == out[2].note == "Elektrik"


def test_lunch_mode_off_means_no_deduction_at_all(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(13, 0)
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=4, minutes=30)
    svc.set_lunch_mode("off")
    assert svc.lunch_mode == "off" and svc.lunch_state(DAY) == "off" and svc.lunch_window(DAY) is None
    assert not svc.lunch_prompt_due()
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=5)


def test_add_lunch_pause_afterwards_splits_the_task(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(13, 0)
    svc.add_lunch_pause(DAY)
    got = svc.day_entries(DAY)
    assert [(e.start.strftime("%H:%M"), e.end and e.end.strftime("%H:%M"), e.kind) for e in got] == [
        ("08:00", "12:00", "work"), ("12:00", "12:30", "pause"), ("12:30", None, "work")]
    assert got[0].note == got[2].note == "Arbeit" and svc.current().note == "Arbeit"
    assert svc.lunch_state(DAY) == "paused"
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=4, minutes=30)
    with pytest.raises(TimelineError):
        svc.add_lunch_pause(DAY)               # es gibt schon eine Pause


def test_add_lunch_pause_not_before_lunch_time(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(11, 0)
    with pytest.raises(TimelineError):
        svc.add_lunch_pause(DAY)


def test_add_lunch_pause_with_own_start_and_length(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(13, 0)
    svc.add_lunch_pause(DAY, time(12, 15), 45)
    got = svc.day_entries(DAY)
    assert [(e.start.strftime("%H:%M"), e.end and e.end.strftime("%H:%M"), e.kind) for e in got] == [
        ("08:00", "12:15", "work"), ("12:15", "13:00", "pause"), ("13:00", None, "work")]


def test_add_lunch_pause_ending_in_the_future_runs_and_resumes_the_task(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(12, 10)
    svc.add_lunch_pause(DAY, time(12, 0), 30)
    got = svc.day_entries(DAY)
    assert [(e.start.strftime("%H:%M"), e.end and e.end.strftime("%H:%M"), e.kind) for e in got] == [
        ("08:00", "12:00", "work"), ("12:00", None, "pause")]
    assert svc.current_pause() is not None and svc.current_pause().auto_until.strftime("%H:%M") == "12:30"
    clock.set(12, 31)
    svc.tick()
    got = svc.day_entries(DAY)
    assert [(e.start.strftime("%H:%M"), e.end and e.end.strftime("%H:%M"), e.kind) for e in got] == [
        ("08:00", "12:00", "work"), ("12:00", "12:30", "pause"), ("12:30", None, "work")]
    assert svc.current().note == "Arbeit"
    assert svc.work_total(svc.day_entries(DAY)) == timedelta(hours=4, minutes=1)


def test_normal_pause_is_named_pause_and_lunch_pause_mittagspause(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(10, 30)
    svc.add_pause(DAY, time(10, 0), 15)                   # normale Pause nachgetragen
    clock.set(13, 0)
    svc.add_lunch_pause(DAY, time(12, 0), 30)
    names = [svc.entry_label(e) for e in svc.day_entries(DAY) if e.kind == PAUSE]
    assert names == ["Pause", "Mittagspause"]
    assert [r["project"] for r in svc.report_rows(DAY, DAY) if r["kind"] == "pause"] == ["Pause", "Mittagspause"]


def test_no_lunch_break_keeps_normal_pauses(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(15, 0)
    svc.add_pause(DAY, time(10, 0), 15)
    svc.add_lunch_pause(DAY, time(12, 0), 30)
    svc.remove_pause(DAY)                                  # „Keine Mittagspause“
    got = [(e.start.strftime("%H:%M"), e.kind) for e in svc.day_entries(DAY)]
    assert got == [("08:00", "work"), ("10:00", "pause"), ("10:15", "work")] and svc.pause_disabled(DAY)


def test_deleting_a_normal_pause_keeps_lunch_deduction_and_other_entries(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    clock.set(15, 0)
    svc.add_pause(DAY, time(10, 0), 15)
    svc.delete_entry(next(e.id for e in svc.day_entries(DAY) if e.kind == PAUSE))
    assert [e.kind for e in svc.day_entries(DAY)] == ["work"] and not svc.pause_disabled(DAY)


def test_revert_to_previous_task_continues_it(env):
    svc, clock, a, b, act = env
    clock.set(8)
    svc.start_task(a, act, "Erste")
    clock.set(9, 30)
    svc.start_task(b, act, "Verklickt")
    clock.set(9, 35)
    assert svc.previous_task().note == "Erste"
    svc.revert_to_previous()
    got = svc.day_entries(DAY)
    assert len(got) == 1 and got[0].note == "Erste" and got[0].running and got[0].start.strftime("%H:%M") == "08:00"
    assert svc.previous_task() is None
    with pytest.raises(TimelineError):
        svc.revert_to_previous()                            # nichts mehr davor


def test_edit_start_over_a_pause_splits_with_the_split_mode(env):
    svc, clock, a, b, act = env
    clock.set(16, 5)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(8), d(9), project_id=a, note="A"), Entry(d(11, 40), d(12, 10), kind=PAUSE),
                          Entry(d(12, 52), d(13, 30), project_id=a, note="B"),
                          Entry(d(13, 30), None, project_id=b, note="läuft")])
    target = svc.day_entries(DAY)[2]
    assert [x.kind for x in svc.overlapped_entries(target.id, {"start": d(9, 6)})] == [PAUSE]
    svc.edit_entry(target.id, {"start": d(9, 6)}, "split")
    assert [(e.start.strftime("%H:%M"), e.kind) for e in svc.day_entries(DAY)] == [
        ("08:00", "work"), ("09:06", "work"), ("11:40", "pause"), ("12:10", "work"), ("13:30", "work")]


def test_deleting_a_pause_joins_the_split_task_again(env):
    svc, clock, a, b, act = env
    svc.set_lunch_mode("ask")
    clock.set(8)
    svc.start_task(a, act, "Arbeit")
    first_id = svc.day_entries(DAY)[0].id
    clock.set(14, 0)
    svc.add_pause(DAY, time(12, 0), 30)
    assert len(svc.day_entries(DAY)) == 3
    svc.delete_entry(next(e.id for e in svc.day_entries(DAY) if e.kind == PAUSE))
    got = svc.day_entries(DAY)
    assert len(got) == 1 and got[0].id == first_id and got[0].running and got[0].start.strftime("%H:%M") == "08:00"


def test_deleting_a_pause_between_different_tasks_closes_the_gap(env):
    svc, clock, a, b, act = env
    clock.set(15, 0)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(8), d(12), project_id=a), Entry(d(12), d(12, 30), kind=PAUSE),
                          Entry(d(12, 30), d(14), project_id=b)])
    svc.delete_entries([svc.day_entries(DAY)[1].id])
    assert [(e.start.strftime("%H:%M"), e.end.strftime("%H:%M")) for e in svc.day_entries(DAY)] == [
        ("08:00", "12:30"), ("12:30", "14:00")]


def test_preview_and_edit_without_mode_split_around_a_pause(env):
    """Der Bearbeiten-Dialog zeigt die Vorschau ohne gewählten Modus: eine überdeckte Pause darf nicht scheitern."""
    svc, clock, a, b, act = env
    clock.set(16, 5)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(8), d(9), project_id=a), Entry(d(11, 40), d(12, 10), kind=PAUSE),
                          Entry(d(12, 52), d(13, 30), project_id=a), Entry(d(13, 30), None, project_id=b)])
    target = svc.day_entries(DAY)[2]
    old, new = svc.preview_edit(target.id, {"start": d(9, 6)})
    assert [(e.start.strftime("%H:%M"), e.kind) for e in new] == [
        ("08:00", "work"), ("09:06", "work"), ("11:40", "pause"), ("12:10", "work"), ("13:30", "work")]
    svc.edit_entry(target.id, {"start": d(9, 6)})
    assert len(svc.day_entries(DAY)) == 5


def test_preview_over_tasks_falls_back_when_push_would_reach_the_future(env):
    svc, clock, a, b, act = env
    clock.set(16, 5)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    svc.db.save_day(DAY, [Entry(d(9), d(12), project_id=a), Entry(d(12), d(14), project_id=a, note="x"),
                          Entry(d(14), None, project_id=b)])
    target = svc.day_entries(DAY)[1]
    with pytest.raises(TimelineError):
        svc.preview_edit(target.id, {"start": d(8)}, "push")         # Verschieben allein ginge in die Zukunft
    old, new = svc.preview_edit(target.id, {"start": d(8)})      # irgendein Weg geht (Kürzen), Nutzer wählt beim Speichern
    assert new
