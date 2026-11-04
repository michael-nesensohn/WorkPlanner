from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from test_service import DAY, Clock
from workplanner.call_monitor import CallMonitor
from workplanner.db import Database
from workplanner.service import TimeService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def at(h, m=0):
    return datetime(2026, 11, 2, h, m)


class Mic:
    """Ersetzt die Registry: (Beginn, offen?) und die Uhrzeit."""
    def __init__(self):
        self.state, self.now = (None, False), at(9)

    def monitor(self):
        return CallMonitor(lambda: self.state, lambda: self.now)


def test_call_is_reported_when_the_microphone_closes():
    mic = Mic()
    m = mic.monitor()
    assert m.poll() is None
    mic.state, mic.now = (at(9, 5), True), at(9, 6)
    assert m.poll() is None and m.active
    mic.state, mic.now = (at(9, 5), False), at(9, 40)
    call = m.poll()
    assert (call.start, call.end) == (at(9, 5), at(9, 40)) and not m.active
    assert m.poll() is None  # nur einmal melden


def test_very_short_calls_are_ignored():
    mic = Mic()
    m = mic.monitor()
    mic.state, mic.now = (at(9, 5), True), at(9, 5)
    m.poll()
    mic.state, mic.now = (at(9, 5), False), at(9, 5) + timedelta(seconds=2)
    assert m.poll() is None


def test_call_already_running_at_start_uses_registry_start():
    mic = Mic()
    mic.state, mic.now = (at(9, 0), True), at(9, 30)
    m = mic.monitor()
    m.poll()
    mic.state, mic.now = (at(9, 0), False), at(9, 45)
    assert m.poll().start == at(9, 0)


def test_add_booking_overrides_running_task_and_keeps_it_running():
    db = Database()
    clock = Clock(8)
    svc = TimeService(db, clock)
    p = db.add_project("A")
    svc.start_task(p, None, "Arbeit")
    clock.set(10)
    svc.add_booking(at(9), at(9, 30), "Anruf Kunde", p, None)
    got = [(e.start.strftime("%H:%M"), e.end.strftime("%H:%M") if e.end else None, e.note)
           for e in svc.day_entries(DAY)]
    assert got == [("08:00", "09:00", "Arbeit"), ("09:00", "09:30", "Anruf Kunde"), ("09:30", None, "Arbeit")]


def test_call_dialog_books_telefonat_with_note_and_remembers_project(qapp):
    from workplanner.call_monitor import Call
    from workplanner.ui.call_dialog import CallDialog
    db = Database()
    clock = Clock(10)
    svc = TimeService(db, clock)
    p = db.add_project("Kunde")
    db.add_activity("Besprechung")
    d = CallDialog(svc, Call(at(9, 0), at(9, 0)), None)   # 0 Sekunden: wird eine Minute
    assert d.activity.currentText() == "Telefonat"        # wird bei Bedarf angelegt
    assert (d.start.time().minute(), d.end.time().minute()) == (0, 1)
    d.project.setCurrentIndex(d.project.findData(p))
    assert d.activity.currentText() == "Telefonat"
    d.note.setPlainText("Abstimmung Schnittstelle")
    d._accept()
    e = svc.day_entries(DAY)[0]
    assert (e.note, e.project_id, e.activity_id) == ("Abstimmung Schnittstelle", p, d.activity.currentData())
    assert e.end - e.start == timedelta(minutes=1)
    assert svc.call_defaults()[0] == p
    assert len([a for a in db.list_activities() if a["name"] == "Telefonat"]) == 1   # nicht doppelt angelegt
