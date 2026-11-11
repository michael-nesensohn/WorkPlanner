from datetime import datetime, time, timedelta

import pytest

from workplanner import timeline as tl
from workplanner.timeline import PAUSE, WORK, Entry, TimelineError

D = datetime(2026, 11, 2)


def t(h, m=0):
    return D.replace(hour=h, minute=m)


def e(sh, sm, eh, em=0, project=1, **kw):
    return Entry(t(sh, sm), t(eh, em) if eh is not None else None, project_id=project, **kw)


NOW = t(18)


def times(entries):
    return [(x.start.strftime("%H:%M"), x.end.strftime("%H:%M") if x.end else None)
            for x in entries]


# --- Ende / Dauer / Start ---------------------------------------------------

def test_set_end_shifts_all_following_entries():
    day = [e(8, 0, 9, 0, id=1), e(9, 0, 10, 0, id=2), e(10, 0, None, id=3)]
    out = tl.set_end(day, 0, t(9, 30), NOW)
    assert times(out) == [("08:00", "09:30"), ("09:30", "10:30"), ("10:30", None)]


def test_set_end_shorter_pulls_following_forward():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0)]
    out = tl.set_end(day, 0, t(8, 40), NOW)
    assert times(out) == [("08:00", "08:40"), ("08:40", "09:40")]


def test_input_is_not_mutated():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0)]
    tl.set_end(day, 0, t(9, 30), NOW)
    assert times(day) == [("08:00", "09:00"), ("09:00", "10:00")]


def test_set_duration():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0)]
    out = tl.set_duration(day, 0, timedelta(minutes=90), NOW)
    assert times(out) == [("08:00", "09:30"), ("09:30", "10:30")]


def test_shift_keeps_gap_between_entries():
    day = [e(8, 0, 9, 0), e(9, 30, 10, 0)]
    out = tl.set_end(day, 0, t(9, 15), NOW)
    assert times(out) == [("08:00", "09:15"), ("09:45", "10:15")]


def test_set_end_rejects_end_before_start():
    with pytest.raises(TimelineError):
        tl.set_end([e(8, 0, 9, 0)], 0, t(7, 59), NOW)


def test_shift_into_future_rejected():
    day = [e(8, 0, 9, 0), e(9, 0, None)]
    with pytest.raises(TimelineError, match="Zukunft"):
        tl.set_end(day, 0, t(19), NOW)


def test_shift_beyond_midnight_rejected():
    day = [e(8, 0, 9, 0), e(22, 0, 23, 30)]
    with pytest.raises(TimelineError):
        tl.set_end(day, 0, t(11), datetime(2026, 11, 3, 6))


def test_set_end_on_running_entry_stops_it():
    out = tl.set_end([e(8, 0, None)], 0, t(9), NOW)
    assert times(out) == [("08:00", "09:00")]


def test_set_start_moves_end_of_flush_predecessor():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0)]
    out = tl.set_start(day, 1, t(8, 45), NOW)
    assert times(out) == [("08:00", "08:45"), ("08:45", "10:00")]


def test_set_start_after_gap_does_not_touch_predecessor():
    day = [e(8, 0, 9, 0), e(9, 30, 10, 0)]
    out = tl.set_start(day, 1, t(9, 15), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:15", "10:00")]


def test_earlier_start_trims_overlapped_predecessor_even_after_gap():
    day = [e(8, 0, 9, 0, id=1), e(9, 30, 10, 0, id=2)]
    out = tl.set_start(day, 1, t(8, 30), NOW)
    assert times(out) == [("08:00", "08:30"), ("08:30", "10:00")]


def test_earlier_start_keeps_fully_covered_entries_with_their_duration():
    day = [e(7, 0, 7, 30, id=1), e(8, 0, 9, 0, id=2), e(9, 0, 9, 40, id=3), e(9, 40, 10, 0, id=4)]
    out = tl.set_start(day, 3, t(8, 30), NOW)
    assert times(out) == [("07:00", "07:30"), ("08:00", "08:30"), ("08:30", "10:00"), ("10:00", "10:40")]
    assert tl.removed_entries(day, out) == [] and [x.id for x in out] == [1, 2, 4, 3]


def test_running_task_earlier_start_keeps_entries_and_continues_after_them():
    day = [e(7, 0, 7, 30, id=1), e(8, 0, 9, 0, id=2), e(9, 0, 9, 40, id=3, project=2), e(9, 40, None, id=4)]
    out = tl.set_start(day, 3, t(8, 30), NOW)
    assert times(out) == [("07:00", "07:30"), ("08:00", "08:30"), ("08:30", "09:00"), ("09:00", "09:40"),
                          ("09:40", None)]
    assert [x.id for x in out] == [1, 2, None, 3, 4]
    assert out[2].project_id == out[4].project_id == 1 and out[2].end is not None
    assert tl.removed_entries(day, out) == []


def test_earlier_start_covering_everything_before():
    day = [e(8, 0, 9, 0, id=1), e(9, 0, 10, 0, id=2)]
    out = tl.set_start(day, 1, t(7, 0), NOW)
    assert times(out) == [("07:00", "10:00"), ("10:00", "11:00")] and [x.id for x in out] == [2, 1]


def test_earlier_start_shorten_squeezes_covered_entries_proportionally():
    day = [e(7, 0, 8, 0, id=1), e(8, 0, 10, 0, id=2), e(10, 0, 11, 0, id=3)]
    out = tl.set_start(day, 2, t(7, 30), NOW, overlap=tl.SHORTEN)
    assert times(out) == [("07:00", "07:10"), ("07:10", "07:30"), ("07:30", "11:00")]
    assert [x.id for x in out] == [1, 2, 3]


def test_earlier_start_overlap_detection_ignores_partial_overlap():
    day = [e(8, 0, 9, 0, id=1), e(9, 0, 10, 0, id=2)]
    assert tl.earlier_overlap(day, 1, t(8, 30)) == []
    assert tl.earlier_overlap(day, 1, t(7, 0)) == [0]


def test_earlier_start_cannot_leave_the_day():
    with pytest.raises(TimelineError, match="Tag"):
        tl.set_start([e(8, 0, 9, 0)], 0, D.replace(day=1, hour=23), NOW)


# --- Einfügen / Löschen ---------------------------------------------------------

def test_insert_between_shifts_following():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0)]
    out = tl.insert(day, e(9, 0, 9, 30, project=7), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:00", "09:30"), ("09:30", "10:30")]
    assert out[1].project_id == 7


def test_insert_at_end():
    out = tl.insert([e(8, 0, 9, 0)], e(9, 0, 9, 30), NOW)
    assert times(out) == [("08:00", "09:00"), ("09:00", "09:30")]


def test_insert_into_middle_of_entry_rejected():
    with pytest.raises(TimelineError):
        tl.insert([e(8, 0, 10, 0)], e(9, 0, 9, 30), NOW)


def test_delete_closes_gap():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0), e(10, 0, None)]
    out = tl.delete(day, 1, NOW)
    assert times(out) == [("08:00", "09:00"), ("09:00", None)]


def test_delete_without_closing_gap():
    day = [e(8, 0, 9, 0), e(9, 0, 10, 0), e(10, 0, 11, 0)]
    out = tl.delete(day, 1, NOW, close_gap=False)
    assert times(out) == [("08:00", "09:00"), ("10:00", "11:00")]


# --- Start / Stopp ------------------------------------------------------------------

def test_start_new_stops_running_task_at_same_moment():
    day = [e(8, 0, None)]
    out = tl.start_new(day, Entry(t(0), project_id=2), t(10))
    assert times(out) == [("08:00", "10:00"), ("10:00", None)]
    assert [x.project_id for x in out] == [1, 2]
    assert sum(x.running for x in out) == 1


def test_start_new_drops_zero_length_running_entry():
    out = tl.start_new([e(8, 0, None)], Entry(t(0), project_id=2), t(8))
    assert times(out) == [("08:00", None)]
    assert out[0].project_id == 2


def test_stop():
    out = tl.stop([e(8, 0, None)], t(9))
    assert times(out) == [("08:00", "09:00")]
    assert tl.stop(out, t(10)) == out


def test_validate_only_last_may_run():
    with pytest.raises(TimelineError):
        tl.validate([e(8, 0, None), e(9, 0, 10, 0)])


# --- Mittagspause --------------------------------------------------------------------------

def legacy_pause_day(**kw):
    """Tag mit einer früher automatisch angelegten Pause: 08-12 Arbeit, 12-12:30 Pause, 12:30-13 Arbeit."""
    return [e(8, 0, 12, 0, id=1, **kw), Entry(t(12), t(12, 30), PAUSE, auto_pause=True, id=2),
            e(12, 30, 13, 0, id=3, **kw)]


def test_remove_pause_merges_same_task():
    out = tl.remove_pause(legacy_pause_day(note="x"), 1, NOW)
    assert times(out) == [("08:00", "13:00")]
    assert out[0].id == 1


def test_remove_pause_extends_previous_when_tasks_differ():
    day = [e(8, 0, 12, 0, project=1), Entry(t(12), t(12, 30), PAUSE, auto_pause=True),
           e(12, 30, 14, 0, project=2)]
    out = tl.remove_pause(day, 1, NOW)
    assert times(out) == [("08:00", "12:30"), ("12:30", "14:00")]


def test_remove_running_pause_resumes_previous_task():
    day = [e(8, 0, 12, 0, id=1), Entry(t(12), None, PAUSE, auto_pause=True, id=2)]
    out = tl.remove_pause(day, 1, t(12, 10))
    assert times(out) == [("08:00", None)]


def test_changed_times_reports_shifted_entries():
    day = [e(8, 0, 9, 0, id=1), e(9, 0, 10, 0, id=2)]
    out = tl.set_end(day, 0, t(9, 30), NOW)
    assert [o.id for o, _ in tl.changed_times(day, out)] == [1, 2]
