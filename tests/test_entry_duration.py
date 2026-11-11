import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from test_service import DAY, Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.timeline import Entry
from workplanner.ui.dialogs import EntryDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def d(h, m=0):
    return datetime(2026, 11, 2, h, m)


def setup(entries, clock_hm=(18, 0)):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(*clock_hm))
    pid = svc.projects()[0]["id"]
    db.save_day(DAY, [Entry(s, e, project_id=pid, note=n) for s, e, n in entries])
    return svc, svc.day_entries(DAY)


def save_enabled(dlg):
    return dlg.buttons.button(QDialogButtonBox.Save).isEnabled()


def test_duration_shows_the_length_and_follows_start_and_end(qapp):
    svc, (first, second) = setup([(d(8), d(9), "a"), (d(9), d(10), "b")])
    dlg = EntryDialog(svc, DAY, first)
    assert dlg.duration.time() == QTime(1, 0)
    dlg.end.setTime(QTime(9, 45))
    assert dlg.duration.time() == QTime(1, 45)
    dlg.start.setTime(QTime(8, 15))                         # Start später, Ende bleibt
    assert dlg.duration.time() == QTime(1, 30) and dlg.end.time() == QTime(9, 45)


def test_changing_the_duration_moves_the_end_and_shifts_followers(qapp):
    svc, (first, second) = setup([(d(8), d(9), "a"), (d(9), d(10), "b")])
    dlg = EntryDialog(svc, DAY, first)
    assert dlg._changes() == {}                             # unverändert
    dlg.duration.setTime(QTime(1, 30))
    assert dlg.end.time() == QTime(9, 30) and dlg.start.time() == QTime(8, 0)
    assert "Einträge werden angepasst" in dlg.preview.text() and "09:30–10:30" in dlg.preview.text()
    assert save_enabled(dlg)
    dlg._save()
    a, b = svc.day_entries(DAY)
    assert (a.end.hour, a.end.minute) == (9, 30)
    assert (b.start.hour, b.start.minute, b.end.hour, b.end.minute) == (9, 30, 10, 30)   # Folgeeintrag verschoben


def test_shorter_duration_pulls_followers_forward(qapp):
    svc, (first, second) = setup([(d(8), d(10), "a"), (d(10), d(11), "b")])
    dlg = EntryDialog(svc, DAY, first)
    dlg.duration.setTime(QTime(1, 15))
    assert dlg.end.time() == QTime(9, 15)
    dlg._save()
    a, b = svc.day_entries(DAY)
    assert (a.end.hour, a.end.minute) == (9, 15) and (b.start.hour, b.start.minute) == (9, 15)


def test_duration_in_the_future_is_rejected_by_the_preview(qapp):
    svc, (first, second) = setup([(d(8), d(9), "a"), (d(9), d(17, 30), "b")], clock_hm=(18, 0))
    dlg = EntryDialog(svc, DAY, first)
    dlg.duration.setTime(QTime(2, 0))                       # schiebt den Folgeeintrag hinter „jetzt“ (18:00)
    assert not save_enabled(dlg) and "Zukunft" in dlg.preview.text()


def test_zero_duration_disables_save(qapp):
    svc, (first,) = setup([(d(8), d(9), "a")])
    dlg = EntryDialog(svc, DAY, first)
    dlg.duration.setTime(QTime(0, 0))
    assert not save_enabled(dlg)


def test_duration_cannot_push_the_end_past_midnight(qapp):
    svc, (first,) = setup([(d(22), d(23), "a")], clock_hm=(23, 59))
    dlg = EntryDialog(svc, DAY, first)
    dlg.start.setTime(QTime(23, 0))
    dlg.duration.setTime(QTime(2, 0))
    assert dlg.end.time() == QTime(23, 59) and dlg.duration.time() == QTime(0, 59)   # auf den Tag begrenzt
    assert save_enabled(dlg)


def test_running_entry_duration_changes_the_start(qapp):
    svc, (first, run) = setup([(d(8), d(9), "a"), (d(9), None, "läuft")], clock_hm=(10, 0))
    dlg = EntryDialog(svc, DAY, run)
    assert dlg.duration.time() == QTime(1, 0) and not dlg.end.isEnabled() and dlg._changes() == {}
    dlg.duration.setTime(QTime(0, 30))                      # nur 30 min angefallen -> Start 09:30
    assert dlg.start.time() == QTime(9, 30)
    assert "→ 08:00–09:30" in dlg.preview.text()            # der bündige Vorgänger wird bis 09:30 verlängert
    dlg._save()
    a, b = svc.day_entries(DAY)
    assert (a.end.hour, a.end.minute) == (9, 30)
    assert svc.current().start == d(9, 30)
    dlg = EntryDialog(svc, DAY, svc.current())
    dlg.duration.setTime(QTime(2, 0))                       # 2 h angefallen -> Start 08:00, übernimmt den Vorgänger
    assert dlg.start.time() == QTime(8, 0) and "Entfällt" not in dlg.preview.text()   # Einträge bleiben erhalten


def test_new_entry_has_a_default_duration_that_can_be_changed(qapp):
    svc, entries = setup([(d(8), d(9), "a")])
    dlg = EntryDialog(svc, DAY, None, default_start=d(9))
    assert dlg.duration.time() == QTime(0, 30) and dlg.end.time() == QTime(9, 30)
    dlg.duration.setTime(QTime(1, 15))
    assert dlg.end.time() == QTime(10, 15)
    dlg._save()
    assert [(e.start.hour, e.start.minute, e.end.hour, e.end.minute) for e in svc.day_entries(DAY)] == [
        (8, 0, 9, 0), (9, 0, 10, 15)]


def test_lunch_hint_is_shown_for_entries_over_noon(qapp):
    svc, (e,) = setup([(d(11), d(13), "a")])
    dlg = EntryDialog(svc, DAY, e)
    assert "0:30 Mittagspause" in dlg.preview.text() and "zählt 1:30 h" in dlg.preview.text()
    dlg.duration.setTime(QTime(0, 45))                       # 11:00-11:45: keine Pause mehr betroffen
    assert "Mittagspause" not in dlg.preview.text()


# --- Markierung: Dauer ab Start oder bis Ende rechnen ---------------------------------------------

def test_default_anchor_is_start_and_radios_are_exclusive(qapp):
    svc, (e,) = setup([(d(8), d(9), "a")])
    dlg = EntryDialog(svc, DAY, e)
    assert dlg.anchor_start.isChecked() and not dlg.anchor_end.isChecked()
    dlg.anchor_end.setChecked(True)
    assert not dlg.anchor_start.isChecked()


def test_duration_counted_back_from_the_end_moves_the_start(qapp):
    svc, (first, second) = setup([(d(7), d(8), "vor"), (d(8), d(10), "x")])
    dlg = EntryDialog(svc, DAY, second)
    dlg.anchor_end.setChecked(True)
    dlg.duration.setTime(QTime(1, 30))                       # bis 10:00 gerechnet -> Start 08:30
    assert dlg.start.time() == QTime(8, 30) and dlg.end.time() == QTime(10, 0)
    assert "→ 07:00–08:30" in dlg.preview.text()             # der bündige Vorgänger wird bis 08:30 verlängert
    dlg._save()
    a, b = svc.day_entries(DAY)
    assert (a.end.hour, a.end.minute, b.start.hour, b.start.minute, b.end.hour) == (8, 30, 8, 30, 10)


def test_longer_duration_from_the_end_keeps_earlier_entries(qapp):
    svc, (first, second) = setup([(d(7), d(8), "vor"), (d(8), d(10), "x")])
    dlg = EntryDialog(svc, DAY, second)
    dlg.anchor_end.setChecked(True)
    dlg.duration.setTime(QTime(3, 30))                       # Start 06:30: überdeckt den Vorgänger ganz
    assert dlg.start.time() == QTime(6, 30) and "Entfällt" not in dlg.preview.text()
    dlg._save()                                              # der überdeckte Eintrag bleibt, folgt hinter dem Eintrag
    x, vor = svc.day_entries(DAY)
    assert (x.start.hour, x.start.minute, x.end.hour) == (6, 30, 10)
    assert (vor.start.hour, vor.end.hour) == (10, 11)


def test_anchor_start_still_moves_the_end_and_followers(qapp):
    svc, (first, second) = setup([(d(8), d(9), "a"), (d(9), d(10), "b")])
    dlg = EntryDialog(svc, DAY, first)
    dlg.anchor_end.setChecked(True)
    dlg.anchor_start.setChecked(True)
    dlg.duration.setTime(QTime(1, 30))
    assert dlg.start.time() == QTime(8, 0) and dlg.end.time() == QTime(9, 30)


def test_duration_from_the_end_cannot_go_before_midnight(qapp):
    svc, (e,) = setup([(d(1), d(2), "a")])
    dlg = EntryDialog(svc, DAY, e)
    dlg.anchor_end.setChecked(True)
    dlg.duration.setTime(QTime(5, 0))
    assert dlg.start.time() == QTime(0, 0) and dlg.duration.time() == QTime(2, 0)      # auf den Tagesanfang begrenzt
    assert save_enabled(dlg)


def test_anchor_choice_is_remembered_only_when_the_user_clicks(qapp):
    svc, (e,) = setup([(d(8), d(9), "a")])
    dlg = EntryDialog(svc, DAY, e)
    dlg.anchor_end.setChecked(True)                          # programmatisch: wird nicht gemerkt
    assert svc.duration_anchor == "start"
    dlg.anchor_start.click()
    dlg.anchor_end.click()                                   # echter Klick: wird gemerkt
    assert svc.duration_anchor == "end"
    again = EntryDialog(svc, DAY, e)
    assert again.anchor_end.isChecked() and not again.anchor_start.isChecked()
    again.anchor_start.click()
    assert svc.duration_anchor == "start" and EntryDialog(svc, DAY, e).anchor_start.isChecked()


def test_running_entry_has_no_anchor_choice(qapp):
    svc, (first, run) = setup([(d(8), d(9), "a"), (d(9), None, "läuft")], clock_hm=(10, 0))
    dlg = EntryDialog(svc, DAY, run)
    assert not dlg.anchor_start.isEnabled() and not dlg.anchor_end.isEnabled()
    dlg.duration.setTime(QTime(0, 30))
    assert dlg.start.time() == QTime(9, 30)                  # wie bisher: die Dauer reicht bis „jetzt“
    assert svc.duration_anchor == "start"                    # und die gemerkte Wahl bleibt unberührt


def test_new_entry_follows_the_anchor_too(qapp):
    svc, entries = setup([(d(8), d(9), "a")])
    dlg = EntryDialog(svc, DAY, None, default_start=d(9))
    dlg.anchor_end.setChecked(True)
    dlg.duration.setTime(QTime(1, 0))                        # Ende 09:30 bleibt -> Start 08:30 (überlappt „a“)
    assert dlg.end.time() == QTime(9, 30) and dlg.start.time() == QTime(8, 30)


# --- Sekunden: eine eingegebene Dauer muss genau so herauskommen --------------------------------

def test_typed_duration_is_exact_even_if_the_start_has_seconds(qapp):
    """Gemeldet: Dauer 10 min eingegeben, in der Tabelle stand 0:09 (Start war 10:32:58, Ende wurde 10:42:00)."""
    from PySide6.QtWidgets import QApplication
    from workplanner.ui.main_window import MainWindow
    svc, (e,) = setup([(datetime(2026, 11, 2, 10, 32, 58), datetime(2026, 11, 2, 10, 35, 0), "a")])
    dlg = EntryDialog(svc, DAY, e)
    assert dlg.start.time() == QTime(10, 32)                       # die Sekunden sieht man im Feld nicht
    dlg.duration.setTime(QTime(0, 10))
    dlg._save()
    (saved,) = svc.day_entries(DAY)
    assert saved.end - saved.start == timedelta(minutes=10)         # genau 10 Minuten, nicht 9:02
    assert (saved.start.second, saved.end.second) == (0, 0)          # nach einer Zeitänderung minutengenau
    w = MainWindow(svc)
    assert w.table.item(0, 2).text() == "0:10"


def test_changing_only_the_note_keeps_the_seconds(qapp):
    svc, (e,) = setup([(datetime(2026, 11, 2, 10, 32, 58), datetime(2026, 11, 2, 10, 35, 12), "a")])
    dlg = EntryDialog(svc, DAY, e)
    dlg.note.setPlainText("neu")
    assert "start" not in dlg._changes() and "end" not in dlg._changes()
    dlg._save()
    (saved,) = svc.day_entries(DAY)
    assert (saved.start, saved.end) == (e.start, e.end) and saved.note == "neu"


def test_end_from_the_end_anchor_is_exact_too(qapp):
    svc, (e,) = setup([(datetime(2026, 11, 2, 10, 32, 58), datetime(2026, 11, 2, 10, 45, 41), "a")])
    dlg = EntryDialog(svc, DAY, e)
    dlg.anchor_end.setChecked(True)
    dlg.duration.setTime(QTime(0, 10))
    dlg._save()
    (saved,) = svc.day_entries(DAY)
    assert saved.end - saved.start == timedelta(minutes=10) and (saved.start.second, saved.end.second) == (0, 0)


def test_editing_the_end_also_makes_the_start_minute_exact(qapp):
    svc, (e,) = setup([(datetime(2026, 11, 2, 10, 32, 58), datetime(2026, 11, 2, 10, 35, 0), "a")])
    dlg = EntryDialog(svc, DAY, e)
    dlg.end.setTime(QTime(10, 42))                                   # Start steht als 10:32 da -> 10 min
    dlg._save()
    (saved,) = svc.day_entries(DAY)
    assert saved.end - saved.start == timedelta(minutes=10)
