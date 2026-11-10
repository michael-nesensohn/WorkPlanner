from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_service import Clock
from workplanner import demo
from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make(h=16):
    db = Database()
    clock = Clock(h)
    return TimeService(db, clock), db, clock


def test_offer_only_on_a_completely_empty_database_and_only_once():
    svc, db, _ = make()
    assert demo.needs_offer(svc)
    demo.mark_offered(svc)
    assert not demo.needs_offer(svc)
    svc2, db2, _ = make()
    db2.add_project("Eigenes")
    assert not demo.needs_offer(svc2)                       # es gibt schon eigene Daten


def test_add_creates_marked_projects_activities_and_a_free_example_day():
    svc, db, clock = make(16)                               # Nachmittag: heute
    day = demo.add_demo(svc)
    assert day == clock().date()
    assert len(db.list_projects()) == 4 and len(db.list_activities()) == 6
    entries = svc.day_entries(day)
    assert len(entries) == 6 and all(e.end is not None for e in entries)
    assert entries[0].start.hour == 7 and entries[-1].end.minute == 22
    assert demo.has_demo(svc)
    with pytest.raises(ValueError):
        demo.add_demo(svc)                                  # nicht doppelt


def test_example_day_moves_back_when_today_is_not_free_or_it_is_morning():
    svc, db, clock = make(9)                                # Vormittag: gestern
    assert demo.add_demo(svc) == clock().date() - timedelta(days=1)
    svc2, db2, clock2 = make(16)
    own = db2.add_project("Eigenes")
    svc2.start_task(own, None, "echte Arbeit")              # heute ist belegt
    clock2.set(17)
    svc2.stop()
    assert demo.add_demo(svc2) == clock2().date() - timedelta(days=1)   # überlagert nichts


def test_remove_deletes_only_demo_data_and_keeps_own_entries():
    svc, db, clock = make(16)
    own = db.add_project("Eigenes")
    own_activity = db.add_activity("Programmierung")        # gibt es schon: wird mitbenutzt, nicht gelöscht
    day = demo.add_demo(svc)
    assert len(db.list_activities()) == 6                   # nur 5 neu angelegt
    demo_project = [p["id"] for p in db.list_projects() if p["name"].startswith("Beispiel Kunden")][0]
    # ein eigener Eintrag auf einem Beispielprojekt, an einem anderen Tag
    from workplanner.timeline import Entry
    d2 = day - timedelta(days=3)
    db.save_day(d2, [Entry(datetime.combine(d2, datetime.min.time()).replace(hour=8),
                           datetime.combine(d2, datetime.min.time()).replace(hour=9), project_id=demo_project,
                           note="eigene Notiz")])
    result = demo.remove_demo(svc)
    assert result["entries"] == 6 and result["archived"] == 1       # das Beispielprojekt mit eigenem Eintrag bleibt (archiviert)
    assert svc.day_entries(day) == [] and len(svc.day_entries(d2)) == 1
    names = [p["name"] for p in db.list_projects()]
    assert names == ["Eigenes"]                                      # die anderen drei sind weg, eines archiviert
    assert own_activity in [a["id"] for a in db.list_activities()]   # eigene Tätigkeit bleibt
    assert not demo.has_demo(svc)


def test_window_offer_and_menu(qapp, monkeypatch):
    svc, db, clock = make(16)
    w = MainWindow(svc)
    answers = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: answers.setdefault("asked", self.text()) and 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(
        b for b in self.buttons() if b.text() == "Beispieldaten einfügen"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w.offer_demo()
    assert "Beispieldaten" in answers["asked"] and demo.has_demo(svc)
    assert w.table.rowCount() == 6 and w.day == clock().date()
    w._update_demo_actions()
    assert not w.demo_add_action.isEnabled() and w.demo_remove_action.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w.remove_demo_data()
    assert not demo.has_demo(svc) and w.table.rowCount() == 0 and not db.list_projects()
    w.offer_demo()                                          # nur einmal angeboten
    assert not demo.has_demo(svc)
