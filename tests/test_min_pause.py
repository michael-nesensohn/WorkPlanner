"""Wochenarbeitszeit, Beschäftigungsgrad je Tag und Mindestpause (Anzeige und automatischer Pausen-Eintrag)."""
from datetime import date, datetime, timedelta

import pytest

from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.timeline import PAUSE, WORK, Entry

MONDAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 9)


class Clock:
    def __init__(self, day=2, h=8, m=0):
        self.t = datetime(2026, 11, day, h, m)

    def __call__(self):
        return self.t


@pytest.fixture
def svc():
    db = Database()
    s = TimeService(db, Clock())
    s.project = db.add_project("A")
    return s


def work(svc, day, h1, h2, m1=0, m2=0):
    svc.db.save_day(date(2026, 11, day), [Entry(datetime(2026, 11, day, h1, m1), datetime(2026, 11, day, h2, m2),
                                                 project_id=svc.project)])


def test_defaults_are_forty_hours_five_days(svc):
    assert svc.week_full == timedelta(hours=40) and svc.daily_target == timedelta(hours=8)
    assert svc.day_percents == [100, 100, 100, 100, 100, 0, 0]
    assert svc.week_target(MONDAY) == timedelta(hours=40)
    assert svc.target_for(date(2026, 11, 7)) == timedelta(0)             # Samstag


def test_part_time_days_reduce_the_target(svc):
    svc.set_day_percents([100, 100, 50, 100, 0, 0, 0])                   # Mi halb, Fr frei
    assert svc.target_for(date(2026, 11, 4)) == timedelta(hours=4)
    assert svc.target_for(date(2026, 11, 6)) == timedelta(0)
    assert svc.week_target(MONDAY) == timedelta(hours=28)


def test_week_time_changes_the_day_target(svc):
    svc.set_week_full(37 * 60 + 30)
    assert svc.daily_target == timedelta(hours=7, minutes=30)


def test_old_databases_keep_their_daily_target(svc):
    svc.db.set_setting("week_target_minutes", "")
    svc.db.set_setting("daily_target_minutes", "450")
    assert svc.week_full == timedelta(hours=37, minutes=30)


def test_min_pause_tiers_at_the_limit(svc):
    assert svc.min_pause(timedelta(0)) == timedelta(0)
    assert svc.min_pause(timedelta(hours=3)) == timedelta(minutes=15)
    assert svc.min_pause(timedelta(hours=5)) == timedelta(minutes=15)    # „bis 5 h“ schließt 5:00 ein
    assert svc.min_pause(timedelta(hours=5, minutes=1)) == timedelta(minutes=25)
    assert svc.pause_length == timedelta(minutes=25)                     # Standard-Pause 25 min


def test_first_check_only_remembers_the_start_day(svc):
    work(svc, 2, 8, 17)
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is False                              # alte Tage bleiben unberührt
    assert not any(e.kind == PAUSE for e in svc.db.load_day(MONDAY))


def test_lunch_deduction_already_counts_as_pause(svc):
    svc.settle_min_pauses()                                              # Startpunkt: heute (Mo)
    work(svc, 2, 8, 17)                                                  # 9 h über das Mittagsfenster 12:00–12:25: abgezogen
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is False
    assert not any(e.kind == PAUSE for e in svc.db.load_day(MONDAY))


def test_missing_pause_is_added_in_the_middle_of_the_task(svc):
    svc.settle_min_pauses()
    work(svc, 2, 13, 17, 0, 30)                                          # 4:30 h am Nachmittag, keine Pause
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is True
    day = svc.db.load_day(MONDAY)
    pauses = [e for e in day if e.kind == PAUSE]
    assert len(pauses) == 1 and pauses[0].duration(NOW) == timedelta(minutes=15)    # ≤ 5 h: 15 min
    assert sum((e.duration(NOW) for e in day if e.kind == WORK), timedelta()) == timedelta(hours=4, minutes=15)


def test_pause_goes_to_lunch_time_when_worked_through_it(svc):
    svc.settle_min_pauses()
    svc.db.set_setting("pause_minutes", "0")                             # kein Mittagsabzug: fehlende Pause ganz ergänzen
    work(svc, 2, 8, 17)
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is True
    pause = next(e for e in svc.db.load_day(MONDAY) if e.kind == PAUSE)
    assert pause.start == datetime(2026, 11, 2, 12) and pause.duration(NOW) == timedelta(minutes=25)


def test_enough_pause_adds_nothing_and_deleted_one_does_not_return(svc):
    svc.settle_min_pauses()
    svc.db.save_day(MONDAY, [Entry(datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 12), project_id=svc.project),
                             Entry(datetime(2026, 11, 2, 12), datetime(2026, 11, 2, 12, 30), kind=PAUSE),
                             Entry(datetime(2026, 11, 2, 12, 30), datetime(2026, 11, 2, 17), project_id=svc.project)])
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is False
    # Pause lag unter der Mindestpause -> ergänzt, nach dem Löschen nicht noch einmal
    svc.db.save_day(date(2026, 11, 3), [Entry(datetime(2026, 11, 3, 8), datetime(2026, 11, 3, 10), project_id=svc.project)])
    svc._clock.t = datetime(2026, 11, 4, 8)
    assert svc.settle_min_pauses() is True
    day3 = svc.db.load_day(date(2026, 11, 3))
    pause = next(e for e in day3 if e.kind == PAUSE)
    assert pause.duration(NOW) == timedelta(minutes=15)                    # ≤ 5 h Arbeit: 15 min
    svc.db.save_day(date(2026, 11, 3), [e for e in day3 if e.kind != PAUSE])
    svc._clock.t = datetime(2026, 11, 5, 8)
    assert svc.settle_min_pauses() is False
    assert not any(e.kind == PAUSE for e in svc.db.load_day(date(2026, 11, 3)))


def test_no_pause_added_when_lunch_is_switched_off(svc):
    svc.settle_min_pauses()
    svc.set_lunch_mode("off")
    work(svc, 2, 8, 17)
    svc._clock.t = datetime(2026, 11, 3, 8)
    assert svc.settle_min_pauses() is False


def test_target_end_includes_the_missing_minimum_pause(svc):
    svc.set_lunch_mode("off")
    svc.db.set_setting("lunch_mode", "ask")
    svc.db.set_setting("pause_start", "23:00")                           # Mittagsfenster liegt weit nach dem Soll-Ende
    svc.start_task(svc.project, None)
    svc._clock.t = datetime(2026, 11, 2, 8)
    entries = svc.day_entries(MONDAY)
    assert svc.target_end(entries, svc.now()) == datetime(2026, 11, 2, 16, 25)   # 8 h Soll + 25 min Mindestpause
