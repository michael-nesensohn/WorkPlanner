import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from test_service import Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.ui.dialogs import EntryDialog
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_window_start_stop_edit(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    first, second = [p["id"] for p in svc.projects()][:2]
    w._pick_project(first)
    clock.set(9)
    w._pick_project(second)
    clock.set(9, 30)
    w.refresh()
    assert w.table.rowCount() == 2
    assert w.table.item(0, 1).text() == "09:00"
    assert w.table.item(1, 1).text() == "läuft"

    dlg = EntryDialog(svc, w.day, w._entries[0])
    dlg.end.setTime(dlg.end.time().addSecs(15 * 60))
    assert dlg.buttons.button(QDialogButtonBox.Save).isEnabled()
    assert "Einträge werden angepasst" in dlg.preview.text()
    dlg._save()
    w.refresh()
    assert w.table.item(0, 1).text() == "09:15"
    assert w.table.item(1, 0).text() == "09:15"

    dlg = EntryDialog(svc, w.day, w._entries[0])
    dlg.end.setTime(dlg.end.time().addSecs(2 * 3600))  # schiebt laufenden in die Zukunft
    assert not dlg.buttons.button(QDialogButtonBox.Save).isEnabled()
    w._guard(svc.stop)
    assert w.stop_btn.isHidden() and not w.start_btn.isHidden()


def test_other_pages_build(qapp):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(10))
    w = MainWindow(svc)
    w.week.refresh()
    w.report._update()
    w.master.reload()


def test_start_without_task_then_assign_project(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    w._start_blank()
    run = svc.current()
    default = svc.default_project_id()
    assert run.project_id == default and w.task_label.text() == "Allgemein"
    clock.set(8, 40)
    pid = next(p["id"] for p in svc.projects() if p["id"] != default)
    w._pick_project(pid)  # weist der laufenden Zeit das Projekt zu, kein neuer Eintrag
    entries = svc.day_entries(w.day)
    assert len(entries) == 1 and entries[0].project_id == pid and entries[0].start.minute == 0
    dlg = EntryDialog(svc, w.day, entries[0])
    assert dlg._changes() == {}


def test_switch_button_moves_running_time_instead_of_starting_a_new_entry(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    first, second = [p["id"] for p in svc.projects()][:2]
    w._pick_project(first)
    w.note.setPlainText("Beschreibung")
    w._note_edited()
    clock.set(8, 40)
    w._pick_project(second)               # ohne Schalter: neuer Eintrag
    assert len(svc.day_entries(w.day)) == 2
    clock.set(9, 0)
    w.switch_btn.setChecked(True)
    w._pick_project(first)                # mit Schalter: laufende Zeit wechselt das Projekt
    entries = svc.day_entries(w.day)
    assert len(entries) == 2 and svc.current().project_id == first
    assert svc.current().start.hour == 8 and svc.current().start.minute == 40
    assert not w.switch_btn.isChecked()   # gilt nur für eine Auswahl
    w._pick_project(second)               # danach wieder normal: neuer Eintrag
    assert len(svc.day_entries(w.day)) == 3


def test_multiline_note(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    w._start_blank()
    w.note.setPlainText("Zeile 1\nZeile 2\nZeile 3")
    w._note_edited()
    assert svc.current().note == "Zeile 1\nZeile 2\nZeile 3"
    w.refresh()
    assert w.table.item(0, 7).text() == "Zeile 1 ⏎ Zeile 2 ⏎ Zeile 3"
    dlg = EntryDialog(svc, w.day, svc.current())
    assert dlg.note.toPlainText().count("\n") == 2 and dlg._changes() == {}


def test_new_button_stops_running_and_starts_next(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    pid = svc.projects()[0]["id"]
    w._pick_project(pid)
    clock.set(9)
    assert not w.new_btn.isHidden()
    w.new_btn.click()
    entries = svc.day_entries(w.day)
    assert [(e.start.hour, e.end.hour if e.end else None) for e in entries] == [(8, 9), (9, None)]
    assert entries[0].project_id == pid and entries[1].project_id == svc.default_project_id()


def test_daily_target_hours_and_minutes(qapp):
    from PySide6.QtCore import QTime
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(8, 0))
    w = MainWindow(svc)
    w.master.target.setTime(QTime(7, 45))
    assert svc.daily_target.total_seconds() == (7 * 60 + 45) * 60
    w.master.reload()
    assert w.master.target.time() == QTime(7, 45)


def test_calendar_dialog_selects_day(qapp):
    from datetime import date
    from workplanner.ui.dialogs import CalendarDialog
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    dlg = CalendarDialog(w.day)
    assert dlg.selected() == w.day
    from PySide6.QtCore import QDate
    dlg.calendar.setSelectedDate(QDate(2026, 10, 15))
    assert dlg.selected() == date(2026, 10, 15)
    w._set_day(dlg.selected())
    assert w.day == date(2026, 10, 15) and "15.10.2026" in w.day_label.text()


def test_tiles_show_shortcut_on_the_right(qapp):
    from PySide6.QtWidgets import QLabel
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    hints = [b.findChildren(QLabel)[1].text() for b in w._tile_buttons()]
    assert hints == ["1", "2", "3", "4", "5"]


def test_clock_does_not_resize_layout(qapp):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    w.show()
    w._start_blank()
    qapp.processEvents()
    widths = set()
    for h, m in ((8, 1), (8, 11), (9, 8), (10, 0), (11, 11)):
        clock.set(h, m)
        w._update_live()
        qapp.processEvents()
        widths.add((w.timer_label.width(), w.note.width()))
    assert len(widths) == 1


def test_devops_tab_story_books_on_the_feature_project_and_a_feature_is_the_project(qapp):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    w = MainWindow(svc)
    w.devops.story_chosen.emit({"id": 4411, "title": "Schnittstelle Waage", "type": "story",
                                "parent_id": 21, "parent_title": "Waagen-Anbindung"})
    run = svc.current()
    pid = svc.find_project(number="21")
    assert run.project_id == pid and svc.project_name(pid) == "Waagen-Anbindung"
    assert run.devops_id == 4411 and run.note == ""                      # Notiz bleibt frei
    assert w.task_label.text() == "21  Waagen-Anbindung"                 # das Feature steht als Projekt da
    assert w.table.item(0, 4).text() == "21  Waagen-Anbindung" and w.table.item(0, 6).text() == "#4411"
    assert not w.devops_box.isHidden() and "#4411 Schnittstelle Waage" in w.devops_label.text()
    assert w.tabs.currentIndex() == 0
    w.devops.story_chosen.emit({"id": 22, "title": "Export nach Excel", "type": "feature",
                                "parent_id": 3, "parent_title": "Epic"})  # ein Feature ist selbst das Projekt
    assert svc.current().project_id == svc.find_project(number="22") and svc.current().devops_id == 22
    assert svc.find_project(number="4411") is None and svc.find_project(number="3") is None


def test_devops_config_token_is_stored_encrypted(qapp):
    db = Database()
    svc = TimeService(db, Clock(9))
    assert svc.devops_config()["org"] == "" and svc.devops_config()["project"] == "" and svc.devops_config()["team"] == ""
    assert not svc.devops_config()["has_pat"]
    svc.set_devops_config("o", "p", "t", False, "mein-token")
    assert svc.devops_pat() == "mein-token"
    assert "mein-token" not in db.get_setting("devops_pat")
    svc.set_devops_config("o2", "p", "t", True)  # Token bleibt erhalten
    assert svc.devops_pat() == "mein-token" and svc.devops_config()["only_mine"] is True


def _devops_items():
    from datetime import date
    from workplanner.devops import WorkItem
    base = "https://dev.azure.com/o/p/_workitems/edit/"
    return [
        WorkItem(21, "Waagen-Anbindung", "Feature", "Active", "", 3, "Demo-Plattform", base + "21",
                 start_date=date(2026, 11, 3), parent_start=date(2026, 10, 1)),
        WorkItem(22, "Export nach Excel", "Feature", "New", "", 3, "Demo-Plattform", base + "22"),
        WorkItem(11, "Waage lesen", "User Story", "Active", "Michael", 21, "Waagen-Anbindung",
                 base + "11", 3, "Demo-Plattform"),
    ]


def _texts(item):
    return [item.text(c) for c in range(item.columnCount())]


def test_devops_tree_epic_feature_story(qapp):
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    w.devops._items = _devops_items()
    w.devops._fill()
    tree = w.devops.tree
    assert tree.topLevelItemCount() == 1
    epic = tree.topLevelItem(0)
    assert epic.text(0) == "Demo-Plattform" and epic.text(2) == "Epic" and epic.childCount() == 2
    feature = epic.child(0)
    assert _texts(feature)[:3] == ["Waagen-Anbindung", "21", "Feature"] and feature.childCount() == 1
    assert _texts(feature.child(0))[:6] == ["Waage lesen", "11", "User Story", "Active", "", "Michael"]
    assert feature.text(4) == "03.11.2026" and epic.text(4) == "01.10.2026" and epic.child(1).text(4) == ""
    assert epic.child(1).text(0) == "Export nach Excel" and epic.child(1).childCount() == 0


def test_devops_tree_fills_missing_feature_and_epic_from_story(qapp):
    from workplanner.devops import WorkItem
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    only_story = [WorkItem(11, "Waage lesen", "User Story", "Active", "Michael", 21, "Waagen-Anbindung",
                           "https://dev.azure.com/o/p/_workitems/edit/11", 3, "Demo-Plattform"),
                  WorkItem(12, "Lose Story", "User Story", "New", "", None, "",
                           "https://dev.azure.com/o/p/_workitems/edit/12")]
    w.devops._items = only_story
    w.devops._fill()
    tree = w.devops.tree
    epic, loose = tree.topLevelItem(0), tree.topLevelItem(1)
    assert epic.text(0) == "Demo-Plattform"
    assert epic.child(0).text(0) == "Waagen-Anbindung" and epic.child(0).text(2) == "Feature"
    assert epic.child(0).child(0).text(0) == "Waage lesen"
    assert loose.text(0) == "(ohne Feature)" and loose.child(0).text(0) == "Lose Story"
    assert w.devops._selected() == []


def test_create_projects_from_selected_features(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    w = MainWindow(svc)
    page = w.devops
    page._items = _devops_items()
    page._fill()
    page.tree.selectAll()  # Features und Story: nur die Features zählen
    page._create_projects()
    assert svc.find_project(number="21") and svc.find_project(number="22")
    assert svc.project_display(svc.find_project(number="21")) == "21  Waagen-Anbindung"
    assert svc.find_project(number="11") is None
    assert page.tree.topLevelItem(0).child(0).text(6) == "✓ Waagen-Anbindung"
    assert "2 Projekt(e) angelegt" in page.status.text()
    page.tree.selectAll()  # zweiter Lauf: nichts doppelt
    page._create_projects()
    assert "0 Projekt(e) angelegt, 2 gab es schon" in page.status.text()
    assert len([p for p in svc.projects() if p["number"] in ("21", "22")]) == 2


def test_devops_columns_are_resizable_and_remembered(qapp):
    from PySide6.QtWidgets import QHeaderView
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    w = MainWindow(svc)
    t = w.devops.tree
    hh = t.header()
    assert all(hh.sectionResizeMode(i) == QHeaderView.Interactive for i in range(5))
    assert t.columnWidth(0) == 340
    t.setColumnWidth(0, 260)
    w.devops._store_widths()
    w2 = MainWindow(svc)
    assert w2.devops.tree.columnWidth(0) == 260


def test_story_dialog_needs_title(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from workplanner.ui.devops_page import StoryDialog
    d = StoryDialog("#21 Waagen-Anbindung")
    ok = d.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()
    d.title.setText("  ")
    assert not ok.isEnabled()
    d.title.setText("Neue Story")
    assert ok.isEnabled() and d.assign.isChecked()


def test_sync_dialog_lists_plan_and_skipped(qapp):
    from PySide6.QtWidgets import QDialogButtonBox, QLabel, QTableWidget
    from workplanner.devops_sync import PlanItem
    from workplanner.ui.devops_page import SyncDialog
    plan = [PlanItem(11, "Waage", "User Story", 3.5, 1.0, "task", None, 0.0),
            PlanItem(13, "Epic X", "Epic", 1.0, skip_reason="Typ Epic kann keine Zeit aufnehmen")]
    d = SyncDialog(plan)
    table = d.findChild(QTableWidget)
    assert table.rowCount() == 1
    assert [table.item(0, c).text() for c in (0, 1, 2, 3, 5, 6)] == [
        "#11 Waage", "3.50 h", "1.00 h", "+2.50 h", "0.00 h", "2.50 h"]
    assert "wird angelegt" in table.item(0, 4).text()
    assert any("Typ Epic kann keine Zeit" in lbl.text() for lbl in d.findChildren(QLabel))
    assert d.buttons.button(QDialogButtonBox.Ok).isEnabled()


def test_sync_marks_only_successful_items_as_synced(qapp):
    from workplanner.devops_sync import PlanItem
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    w = MainWindow(svc)
    ok, bad = PlanItem(11, "A", "User Story", 2.0), PlanItem(12, "B", "User Story", 1.0)
    w.devops._on_applied([(ok, None), (bad, "Berechtigung fehlt")], None)
    assert svc.devops_synced() == {11: 2.0}
    assert "1 Eintrag" in w.devops.status.text() and "#12" in w.devops.status.text()


def test_sync_without_new_hours_says_so(qapp):
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    w.devops._sync_hours()
    assert "Keine neuen Stunden" in w.devops.status.text()


def test_running_time_dialog_changes_start_and_elapsed_together(qapp):
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QDialogButtonBox
    from workplanner.ui.dialogs import RunningTimeDialog
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    p1, p2 = [p["id"] for p in svc.projects()][:2]
    svc.start_task(p1, None)
    clock.set(9, 0)
    svc.start_task(p2, None)
    clock.set(10, 0)
    w.refresh()
    assert not w.time_btn.isHidden()
    run = svc.current()
    dlg = RunningTimeDialog(svc, run)
    assert dlg.start.time() == QTime(9, 0) and dlg.elapsed.time() == QTime(1, 0)
    dlg.elapsed.setTime(QTime(1, 30))              # 1:30 angefallen  -> Start 08:30
    assert dlg.start.time() == QTime(8, 30)
    assert "08:00" in dlg.preview.text() and "08:30" in dlg.preview.text()  # Vorgänger endet jetzt 08:30
    dlg.start.setTime(QTime(9, 15))                # Start 09:15      -> 0:45
    assert dlg.elapsed.time() == QTime(0, 45)
    assert dlg.buttons.button(QDialogButtonBox.Save).isEnabled()
    dlg._save()
    first, second = svc.day_entries(w.day)
    assert (first.end.hour, first.end.minute) == (9, 15)
    assert (second.start.hour, second.start.minute) == (9, 15) and second.end is None


def test_running_time_dialog_rejects_impossible_start(qapp):
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QDialogButtonBox
    from workplanner.ui.dialogs import RunningTimeDialog
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    p1, p2 = [p["id"] for p in svc.projects()][:2]
    svc.start_task(p1, None)
    clock.set(9, 0)
    svc.start_task(p2, None)
    clock.set(9, 30)
    dlg = RunningTimeDialog(svc, svc.current())
    dlg.start.setTime(QTime(9, 45))                # Start in der Zukunft
    assert not dlg.buttons.button(QDialogButtonBox.Save).isEnabled() and "Zukunft" in dlg.preview.text()
    dlg.start.setTime(QTime(7, 0))                 # reicht vor den Vorgänger (ab 08:00): der bleibt erhalten
    assert dlg.buttons.button(QDialogButtonBox.Save).isEnabled()
    assert "Entfällt" not in dlg.preview.text()


def test_running_time_dialog_with_second_precise_entries(qapp):
    """Echte Daten: Vorgänger 10:32:12-10:32:17, laufende Aufgabe ab 10:32:58."""
    from datetime import datetime
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QDialogButtonBox
    from workplanner.timeline import Entry
    from workplanner.ui.dialogs import RunningTimeDialog
    db = Database()
    seed(db)
    clock = Clock(10, 40)
    svc = TimeService(db, clock)
    p = svc.projects()[0]["id"]
    d = lambda h, m, s: datetime(2026, 11, 2, h, m, s)  # noqa: E731
    db.save_day(d(10, 0, 0).date(), [Entry(d(10, 32, 12), d(10, 32, 17), project_id=p),
                                     Entry(d(10, 32, 58), None, project_id=p)])
    save = lambda dlg: dlg.buttons.button(QDialogButtonBox.Save)  # noqa: E731
    dlg = RunningTimeDialog(svc, svc.current())
    assert save(dlg).isEnabled() and dlg.preview.text() == ""        # unverändert: speicherbar
    assert dlg._new_start() == d(10, 32, 58)                         # Sekunden bleiben erhalten
    dlg._save()
    assert svc.current().start == d(10, 32, 58)

    # Start in einer späteren Minute -> auf die Minute des Vorgänger-Endes setzen: rastet ein
    db.save_day(d(10, 0, 0).date(), [Entry(d(10, 32, 12), d(10, 32, 17), id=db.day_ids(d(10, 0, 0).date())[0],
                                           project_id=p),
                                     Entry(d(10, 35, 20), None, id=db.day_ids(d(10, 0, 0).date())[1],
                                           project_id=p)])
    dlg = RunningTimeDialog(svc, svc.current())
    dlg.start.setTime(QTime(10, 32))
    assert save(dlg).isEnabled() and dlg._new_start() == d(10, 32, 17)
    dlg._save()
    assert svc.current().start == d(10, 32, 17)
    dlg = RunningTimeDialog(svc, svc.current())
    dlg.elapsed.setTime(QTime(0, 5))                                 # 5 min angefallen -> Start 10:35
    assert dlg.start.time() == QTime(10, 35) and save(dlg).isEnabled()


def test_running_time_longer_elapsed_keeps_earlier_entries(qapp):
    """Screenshot-Fall: 1:16 angefallen -> Start 09:29, eingetragene Einträge bleiben, die Aufgabe stoppt davor und läuft danach weiter."""
    from datetime import datetime
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QDialogButtonBox
    from workplanner.timeline import Entry
    from workplanner.ui.dialogs import RunningTimeDialog
    db = Database()
    seed(db)
    clock = Clock(10, 45)
    svc = TimeService(db, clock)
    p = svc.projects()[0]["id"]
    d = lambda h, m, s=0: datetime(2026, 11, 2, h, m, s)  # noqa: E731
    db.save_day(d(9, 0).date(), [
        Entry(d(9, 26), d(9, 27, 40), project_id=p, note="a"),
        Entry(d(9, 27, 40), d(9, 29, 28), project_id=p, note="b"),
        Entry(d(9, 29, 28), d(9, 38, 28), project_id=p, note="c"),
        Entry(d(9, 38, 28), d(10, 32, 58), project_id=p, note="d"),
        Entry(d(10, 32, 58), None, project_id=p, note="#30 Tests")])
    dlg = RunningTimeDialog(svc, svc.current())
    dlg.elapsed.setTime(QTime(1, 16))
    assert dlg.start.time() == QTime(9, 29)
    assert dlg.buttons.button(QDialogButtonBox.Save).isEnabled()
    assert "Entfällt" not in dlg.preview.text()
    dlg._save()
    notes = [(e.note, e.start.strftime("%H:%M"), e.end.strftime("%H:%M") if e.end else None)
             for e in svc.day_entries(d(9, 0).date())]
    assert notes == [("a", "09:26", "09:27"), ("b", "09:27", "09:29"), ("#30 Tests", "09:29", "09:29"),
                     ("c", "09:29", "09:38"), ("d", "09:38", "10:32"), ("#30 Tests", "10:32", None)]


def test_table_allows_multi_select_delete(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QTableWidget
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    pid = svc.projects()[0]["id"]
    for h in (8, 9, 10, 11):
        clock.set(h)
        w._pick_project(pid)
    clock.set(11, 30)
    w.refresh()
    assert w.table.selectionMode() == QTableWidget.ExtendedSelection and w.table.rowCount() == 4
    w.table.selectRow(0)
    from PySide6.QtCore import QItemSelectionModel
    w.table.selectionModel().select(w.table.model().index(1, 0),
                                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert len(w._selected_entries()) == 2
    w._delete()
    assert w.table.rowCount() == 2
    assert [w.table.item(r, 0).text() for r in range(2)] == ["08:00", "09:00"]
    first, second = svc.day_entries(w.day)
    assert (first.start.hour, first.end.hour) == (8, 9) and second.end is None


def test_devops_scope_choice_applies_to_features_and_stories_and_is_remembered(qapp):
    from workplanner.ui.devops_page import DevOpsPage

    class FakeClient:
        def __init__(self):
            self.calls = []

        def fetch_features(self, only_mine=False):
            self.calls.append(("features", only_mine))
            return []

        def fetch_stories(self, only_mine=True):
            self.calls.append(("stories", only_mine))
            return []

    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    page = MainWindow(svc).devops
    assert page.only_mine is True and page.scope.currentText() == "Nur mir zugewiesene"
    c = FakeClient()
    DevOpsPage.load_items(c, "both", page.only_mine)
    assert c.calls == [("features", True), ("stories", True)]
    page.scope.setCurrentIndex(1)                                   # Alle
    assert page.only_mine is False and svc.devops_config()["only_mine"] is False
    c = FakeClient()
    DevOpsPage.load_items(c, "both", page.only_mine)
    assert c.calls == [("features", False), ("stories", False)]
    DevOpsPage.load_items(c, "features", True)
    assert c.calls[-1] == ("features", True) and len(c.calls) == 3
    assert MainWindow(svc).devops.scope.currentText() == "Alle"      # beim nächsten Start gemerkt


def _outlook_dialog(qapp, clock_hm=(15, 0)):
    from datetime import datetime
    from workplanner.outlook import Appointment
    from workplanner.ui.outlook_dialog import OutlookImportDialog
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(*clock_hm))
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    appts = [Appointment("a", "Daily", d(9), d(9, 15), location="Teams"),
             Appointment("b", "Frei-Termin", d(10), d(11), free=True),
             Appointment("c", "Abgesagt", d(12), d(13), declined=True),
             Appointment("d", "Später", d(16), d(17)),
             Appointment("e", "Urlaub", d(0), d(23, 59), all_day=True)]
    dlg = OutlookImportDialog(svc, d(9).date(), reader=lambda a, b: appts)
    return dlg, svc, appts


def test_outlook_dialog_lists_and_preselects(qapp):
    from PySide6.QtCore import Qt
    dlg, svc, appts = _outlook_dialog(qapp)
    dlg._on_loaded(appts, None)
    t = dlg.table
    assert t.rowCount() == 4                                   # ganztägig ist ausgeblendet
    assert [t.item(r, 4).text() for r in range(4)] == ["Daily", "Frei-Termin", "Abgesagt", "Später"]
    assert [t.item(r, 0).checkState() == Qt.Checked for r in range(4)] == [True, False, False, False]
    assert [t.item(r, 6).text() for r in range(4)] == ["", "als „Frei“ markiert", "abgesagt", "noch nicht begonnen"]
    assert dlg.selected() == [appts[0]] and dlg.ok.isEnabled()
    assert "1 Termin(e)" in dlg.preview.text()
    assert svc.project_name(dlg.project.currentData()) == "Meeting"          # vorbelegt
    assert dlg.activity.currentText() == "Besprechung"


def test_outlook_dialog_imports_selected_and_marks_done(qapp):
    from PySide6.QtCore import Qt
    dlg, svc, appts = _outlook_dialog(qapp)
    dlg._on_loaded(appts, None)
    dlg.table.item(1, 0).setCheckState(Qt.Checked)             # Frei-Termin zusätzlich
    assert len(dlg.selected()) == 2
    dlg._import()
    entries = svc.day_entries(appts[0].start.date())
    assert [(e.note, e.start.hour, e.end.hour) for e in entries] == [("Daily", 9, 9), ("Frei-Termin", 10, 11)]
    assert svc.outlook_imported() == {"a", "b"}
    dlg._on_loaded(appts, None)                                # zweiter Import: nicht noch einmal
    assert dlg.table.item(0, 6).text() == "bereits importiert" and dlg.selected() == []
    assert not dlg.ok.isEnabled()


def test_outlook_dialog_shows_trim_preview_and_errors(qapp):
    dlg, svc, appts = _outlook_dialog(qapp)
    pid = svc.projects()[0]["id"]
    from workplanner.timeline import Entry
    svc.db.save_day(appts[0].start.date(), [Entry(appts[0].start.replace(hour=8),
                                                  appts[0].start.replace(hour=10), project_id=pid, note="Arbeit")])
    dlg._on_loaded(appts, None)
    assert "Bestehende Einträge werden gekürzt: 1" in dlg.preview.text()      # 08:00-10:00 -> 08:00-09:00
    assert "08:00–09:00" in dlg.preview.text() or "08:00–10:00" in dlg.preview.text()
    dlg._on_loaded(None, "Outlook konnte nicht gestartet werden.")
    assert "Outlook konnte nicht gestartet werden" in dlg.status.text()


def test_outlook_dialog_loads_automatically_when_opened(qapp):
    import time as _time
    dlg, svc, appts = _outlook_dialog(qapp)
    assert dlg.table.rowCount() == 0                       # vor dem Anzeigen nichts geladen
    dlg.show()
    deadline = _time.time() + 3
    while dlg.table.rowCount() == 0 and _time.time() < deadline:
        qapp.processEvents()
        _time.sleep(0.01)
    assert dlg.table.rowCount() == 4 and len(dlg.selected()) == 1      # ohne Klick auf „Laden“
    assert "4 Termine gefunden" in dlg.status.text()
    dlg.close()


def test_outlook_dialog_reloads_on_date_change_and_filters_all_day_locally(qapp):
    from PySide6.QtCore import QDate
    calls = []
    dlg, svc, appts = _outlook_dialog(qapp)
    dlg._reader = lambda a, b: (calls.append((a, b)) or appts)
    dlg._on_loaded(appts, None)
    assert dlg.table.rowCount() == 4
    dlg.all_day.setChecked(True)                           # nur anders filtern, nicht neu aus Outlook lesen
    assert dlg.table.rowCount() == 5 and calls == []
    dlg.all_day.setChecked(False)
    assert dlg.table.rowCount() == 4
    dlg.last.setDate(QDate(2026, 11, 5))                   # Zeitraum geändert -> Timer für Neu-Laden läuft
    assert dlg._reload_timer.isActive()
    dlg._reload_timer.stop()


def test_outlook_dialog_offers_running_meeting_and_interrupts_task(qapp):
    from datetime import datetime
    from PySide6.QtCore import Qt
    from workplanner.outlook import Appointment
    from workplanner.ui.outlook_dialog import OutlookImportDialog
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    work = svc.projects()[0]["id"]
    svc.start_task(work, None, "Waage lesen")
    clock.set(10, 20)
    d = lambda h, m=0: datetime(2026, 11, 2, h, m)  # noqa: E731
    appts = [Appointment("run", "Review", d(10), d(11)),             # läuft gerade
             Appointment("fut", "Später", d(14), d(15))]             # noch nicht begonnen
    dlg = OutlookImportDialog(svc, d(10).date(), reader=lambda a, b: appts)
    dlg._on_loaded(appts, None)
    t = dlg.table
    assert t.item(0, 6).text() == "läuft gerade – danach geht die Aufgabe weiter"
    assert t.item(1, 6).text() == "noch nicht begonnen"
    assert t.item(0, 0).checkState() == Qt.Unchecked and dlg._eligible == [True, False]   # nur auf Wunsch
    t.item(0, 0).setCheckState(Qt.Checked)
    assert "läuft gerade" in dlg.preview.text() and "unterbrochen" in dlg.preview.text()
    assert "11:00" in dlg.preview.text() and dlg.ok.isEnabled()
    dlg._import()
    cur = svc.current()
    assert cur.note == "Review" and cur.auto_until == d(11)
    clock.set(11, 5)
    svc.tick()
    notes = [(e.note, e.start.strftime("%H:%M"), e.end.strftime("%H:%M") if e.end else None)
             for e in svc.day_entries(d(10).date())]
    assert ("Waage lesen", "08:00", "10:00") in notes and ("Review", "10:00", "11:00") in notes
    assert notes[-1] == ("Waage lesen", "11:00", None) and svc.current().note == "Waage lesen"


def test_day_view_shows_net_time_and_deduction_note(qapp, monkeypatch):
    from datetime import timedelta
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    pid = svc.projects()[0]["id"]
    w._pick_project(pid)
    clock.set(13, 0)
    svc.tick()
    w.refresh()
    assert w.table.rowCount() == 1                                   # keine Pausenzeile, kein geteilter Eintrag
    assert w.table.item(0, 2).text() == "4:30"                       # 5 h brutto, 30 min Mittagspause abgezogen
    assert "Mittagspause" in w.table.item(0, 2).toolTip() and "5:00 brutto" in w.table.item(0, 2).toolTip()
    assert "4:30 h" in w.total_label.text() and "Pause −0:30 abgezogen" in w.total_label.text()
    assert w.pause_btn.text() == "Keine Mittagspause"
    w.pause_btn.click()
    assert w.pause_btn.text() == "Mittagspause"
    assert w.table.item(0, 2).text() == "5:00" and "abgezogen" not in w.total_label.text()
    from datetime import time as dtime
    monkeypatch.setattr("workplanner.ui.main_window.ask_pause_times", lambda *a: (dtime(12, 0), 30))
    w.pause_btn.click()                                              # „Mittagspause“: trägt die Pause auch als Eintrag ein
    assert [e.kind for e in svc.day_entries(svc.now().date())] == ["work", "pause", "work"]
    assert w.table.rowCount() == 3 and any("Mittagspause" in (w.table.item(1, c).text() if w.table.item(1, c) else "") for c in range(w.table.columnCount()))
    assert w.pause_btn.text() == "Keine Mittagspause"
    clock.set(13, 5)
    w._update_live()
    assert "4:35 h" in w.total_label.text()                          # 8–12 + 12:30–13:05


def test_target_end_label_under_the_target(qapp):
    from datetime import date, timedelta
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    assert "Soll-Ende ca. <b>16:30 Uhr</b>" in w.end_label.text() and "wenn du jetzt startest" in w.end_label.text()
    w._pick_project(svc.projects()[0]["id"])
    w.refresh()
    assert "Soll-Ende ca. <b>16:30 Uhr</b>" in w.end_label.text() and "jetzt startest" not in w.end_label.text()
    w.show()                                                         # die Seitenaufteilung (Splitter) wird erst beim Anzeigen berechnet
    qapp.processEvents()
    assert w.end_label.y() > w.total_label.y()                       # steht unter dem Soll
    clock.set(16, 45)
    w.refresh()
    assert w.end_label.text() == "Soll erreicht (+0:15 h)"           # 8:15 netto, 8:00 Soll
    w._set_day(date(2026, 11, 1))                                    # anderer Tag: nichts anzeigen
    assert w.end_label.text() == ""


def test_today_panel_widths_are_saved_and_restored(qapp):
    db = Database()
    svc = TimeService(db, Clock(8, 0))
    assert svc.split_widths() == (250, 270, 340)
    w = MainWindow(svc)
    w.body.widget(0).setMinimumWidth(100)    # ohne Bildschirm-Schriften ist der Mindestwert der Tabelle sonst riesig
    w.resize(1400, 800)
    w.show()
    qapp.processEvents()
    qapp.processEvents()
    assert w.body.sizes()[1:] == [250, 270, 340]
    w.body.setSizes([700, 230, 350, 260])
    w._save_split()
    assert svc.split_widths() == (230, 350, 260)
    w2 = MainWindow(svc)                      # „Neustart“
    w2.body.widget(0).setMinimumWidth(100)
    w2.resize(1400, 800)
    w2.show()
    qapp.processEvents()
    qapp.processEvents()
    assert w2.body.sizes()[1:] == [230, 350, 260]


def test_entry_checkboxes_and_select_all_header(qapp):
    from PySide6.QtCore import Qt
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    p = svc.projects()[0]["id"]
    svc.start_task(p, None, "a")
    clock.set(9)
    svc.start_task(p, None, "b")
    clock.set(10)
    svc.start_task(p, None, "c")
    w = MainWindow(svc)
    t = w.table
    assert t.rowCount() == 3 and all(t.item(r, 0).checkState() == Qt.Unchecked for r in range(3))
    t.item(0, 0).setCheckState(Qt.Checked)                     # Kästchen -> Zeile markiert
    t.item(2, 0).setCheckState(Qt.Checked)
    assert sorted(e.note for e in w._selected_entries()) == ["a", "c"]
    assert w.check_header._state == Qt.PartiallyChecked
    w.refresh()                                                # Markierung bleibt erhalten
    assert sorted(e.note for e in w._selected_entries()) == ["a", "c"]
    assert t.item(0, 0).checkState() == Qt.Checked and t.item(1, 0).checkState() == Qt.Unchecked
    w.check_header.toggled.emit(True)                          # „Alle markieren“
    assert len(w._selected_entries()) == 3 and w.check_header._state == Qt.Checked
    assert all(t.item(r, 0).checkState() == Qt.Checked for r in range(3))
    t.item(1, 0).setCheckState(Qt.Unchecked)
    assert sorted(e.note for e in w._selected_entries()) == ["a", "c"]
    w.check_header.toggled.emit(False)
    assert w._selected_entries() == [] and w.check_header._state == Qt.Unchecked
    t.selectRow(1)                                             # Zeile anklicken -> Kästchen folgt
    assert t.item(1, 0).checkState() == Qt.Checked and t.item(0, 0).checkState() == Qt.Unchecked


def test_menu_has_quit_and_opens_master_data_without_a_tab(qapp):
    db = Database()
    w = MainWindow(TimeService(db, Clock(8, 0)))
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Heute", "Woche", "Berichte", "DevOps"]
    menus = {a.text().replace("&", ""): a.menu() for a in w.menuBar().actions()}
    assert [a.text().replace("&", "") for a in menus["Datei"].actions()] == ["Beenden"]
    entries = menus["Einstellungen"].actions()
    assert [a.text().split("  ")[0].replace("&", "") for a in entries] == ["Einstellungen …", "Stammdaten …"]
    entries[0].trigger()                                   # Einstellungen: Tastenkombination, Start und Tray, …
    assert w.master_dialog.isVisible() and w.master.sections.currentIndex() == 1
    assert w.master.sections.tabText(1) == "Einstellungen" and w.master.hotkey_edit.isVisibleTo(w.master_dialog)
    entries[1].trigger()                                   # Stammdaten: Projekte, Tätigkeiten
    assert w.master.sections.currentIndex() == 0 and w.master.projects.isVisibleTo(w.master_dialog)
    assert w.master.parent() is w.master_dialog or w.master.parentWidget() is not None
    menus["Datei"].actions()[0].trigger()
    assert w._quitting


def test_master_data_window_remembers_its_size(qapp):
    db = Database()
    svc = TimeService(db, Clock(8, 0))
    assert svc.master_size() == (940, 760)
    w = MainWindow(svc)
    w.show_master()
    w.master_dialog.setMinimumSize(300, 300)             # ohne Bildschirm-Schriften ist der Mindestwert sonst riesig
    w.master_dialog.resize(1000, 700)
    qapp.processEvents()
    w.master_dialog._timer.timeout.emit()                  # das Speichern, das sonst der Zeitgeber auslöst
    assert svc.master_size() == (1000, 700)
    w2 = MainWindow(svc)                                   # „Neustart“
    assert (w2.master_dialog.width(), w2.master_dialog.height()) == (1000, 700)


def test_main_window_remembers_size_and_position(qapp):
    db = Database()
    svc = TimeService(db, Clock(8, 0))
    w = MainWindow(svc)
    w.body.widget(0).setMinimumWidth(100)                 # ohne Bildschirm-Schriften ist der Mindestwert sonst riesig
    w.setMinimumSize(300, 300)
    w.show()
    w.setGeometry(60, 50, 700, 480)
    qapp.processEvents()
    w._save_geometry()
    w2 = MainWindow(svc)                                  # „Neustart“
    w2.setMinimumSize(300, 300)
    w2.show()
    qapp.processEvents()
    g = w2.geometry()
    assert (g.width(), g.height()) == (700, 480) and (g.x(), g.y()) == (60, 50)


def test_outlook_panel_lists_the_days_appointments_and_one_click_books_one(qapp):
    import time as _time
    from datetime import datetime as dt
    from PySide6.QtWidgets import QLabel, QPushButton
    from workplanner.outlook import Appointment
    db = Database()
    meeting = db.add_project("Meeting")
    besprechung = db.add_activity("Besprechung")
    clock = Clock(12, 0)
    svc = TimeService(db, clock)
    appts = [Appointment("k1", "Daily", dt(2026, 11, 2, 9, 0), dt(2026, 11, 2, 9, 30)),
             Appointment("k2", "Ganztags", dt(2026, 11, 2, 0, 0), dt(2026, 11, 3, 0, 0), all_day=True),
             Appointment("k3", "Abgesagt", dt(2026, 11, 2, 10, 0), dt(2026, 11, 2, 11, 0), declined=True),
             Appointment("k4", "Später", dt(2026, 11, 2, 15, 0), dt(2026, 11, 2, 16, 0))]
    w = MainWindow(svc, enable_outlook=True, outlook_reader=lambda a, b: appts)

    def tiles():
        return [b for b in w.outlook.findChildren(QPushButton) if b.objectName() == "tile"]
    for _ in range(100):                                   # das Lesen läuft im Hintergrund
        qapp.processEvents()
        if tiles():
            break
        _time.sleep(0.02)
    got = tiles()
    assert len(got) == 2                                   # ganztägig und abgesagt werden nicht angezeigt
    assert got[0].isEnabled() and not got[1].isEnabled()   # Zukunft lässt sich nicht eintragen
    got[0].click()
    e = svc.day_entries(w.day)[0]
    assert (e.start.hour, e.end.hour, e.end.minute, e.note) == (9, 9, 30, "Daily")
    assert (e.project_id, e.activity_id) == (meeting, besprechung)
    assert "k1" in svc.outlook_imported()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)   # die alten Kacheln wirklich entfernen
    assert not tiles()[0].isEnabled() and "eingetragen" in tiles()[0].findChildren(QLabel)[0].text()


def test_devops_can_be_switched_off_in_the_settings(qapp):
    from workplanner.ui.dialogs import EntryDialog
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9, 0))
    w = MainWindow(svc)
    w.show()
    tab = w.tabs.indexOf(w.devops)
    assert w.tabs.isTabVisible(tab) and w.features.isVisibleTo(w) and not w.table.isColumnHidden(6)
    assert "devops" in svc.export_columns and w.report.column_boxes["devops"].isVisibleTo(w.report)
    w.master.devops_cb.click()                              # Einstellungen: DevOps aus
    assert not svc.devops_enabled
    assert not w.tabs.isTabVisible(tab) and not w.features.isVisibleTo(w)
    assert w.table.isColumnHidden(6) and w.week.entries.isColumnHidden(6) and not w.note_task_btn.isVisibleTo(w)
    assert "devops" not in svc.export_columns and "devops" not in w.report._columns()
    assert not w.report.column_boxes["devops"].isVisibleTo(w.report)
    d = EntryDialog(svc, w.day, None, None, w)               # keine DevOps-ID-Zeile mehr im Dialog
    assert not d.devops_id.isVisibleTo(d)
    w.master.devops_cb.click()                              # wieder an
    assert svc.devops_enabled and w.tabs.isTabVisible(tab) and w.features.isVisibleTo(w)
    assert not w.table.isColumnHidden(6) and "devops" in svc.export_columns


def test_license_matches_the_file_and_help_menu_shows_it(qapp):
    from pathlib import Path
    from workplanner.license_text import LICENSE_TEXT
    root = Path(__file__).resolve().parent.parent
    assert (root / "LICENSE").read_text(encoding="utf-8").strip() == LICENSE_TEXT.strip()      # Programmtext = Datei im Projekt
    assert "MIT License" in LICENSE_TEXT and "WITHOUT WARRANTY" in LICENSE_TEXT and "LIABLE" in LICENSE_TEXT
    w = MainWindow(TimeService(Database(), Clock(8, 0)))
    menus = {a.text().replace("&", ""): a.menu() for a in w.menuBar().actions()}
    assert [a.text().replace("&", "") for a in menus["Hilfe"].actions() if not a.isSeparator()] == ["Handbuch", "Handbuch im PDF-Programm öffnen", "Beispieldaten einfügen …",
                                                                              "Beispieldaten entfernen …", "Lizenz …", "Über WorkPlanner / Updates …"]
    from workplanner.ui.license_dialog import LicenseDialog
    d = LicenseDialog(w)
    assert "MIT License" in d.text.toPlainText() and "openpyxl" in d.text.toPlainText()


def test_manual_is_found_and_help_menu_opens_it(qapp, monkeypatch, tmp_path):
    import os
    import workplanner.manual as manual
    import workplanner.ui.main_window as mw
    from workplanner.ui.main_window import MainWindow
    pdf = tmp_path / manual.NAME
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(manual, "__file__", str(tmp_path / "src" / "workplanner" / "manual.py"))   # docs/ liegt dann tmp_path/docs
    assert manual.manual_path() is None
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / manual.NAME).write_bytes(b"%PDF-1.4")
    assert manual.manual_path() == tmp_path / "docs" / manual.NAME
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(mw, "manual_path", lambda: tmp_path / "docs" / manual.NAME)
    w = MainWindow(TimeService(Database(), Clock(8, 0)))
    w.open_manual_external()
    assert opened == [str(tmp_path / "docs" / manual.NAME)]


def _sample_manual(path):
    """Kleines PDF mit Kapiteln als Lesezeichen (wie das echte Handbuch)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    for number, title, text in (("1", "Was ist WorkPlanner?", "Einleitung"), ("2", "Zeit erfassen", "Start und Stopp"),
                                ("3", "Outlook-Termine", "Ein Klick bucht den Termin")):
        key = f"k{number}"
        c.bookmarkPage(key)
        c.addOutlineEntry(f"{number}\u00a0\u00a0{title}", key, 0, 0)
        c.drawString(72, 700, f"{number} {title}")
        c.drawString(72, 680, text)
        c.showPage()
    c.save()


def test_manual_window_jumps_to_chapters_and_searches(qapp, tmp_path):
    import time as _time
    from workplanner.ui.manual_window import ManualWindow
    pdf = tmp_path / "m.pdf"
    _sample_manual(pdf)
    saved = []
    win = ManualWindow(pdf, None, saved.append)
    win.show()
    assert win.doc.pageCount() == 3
    assert win.chapter_page("2") == 1 and win.chapter_page("3") == 2 and win.chapter_page("9") is None
    win.show_chapter("3")
    qapp.processEvents()
    assert win.view.pageNavigator().currentPage() == 2
    win.search.setText("Klick")
    win._run_search()
    for _ in range(100):                                    # die Suche läuft im Hintergrund
        qapp.processEvents()
        if win.hits_model.rowCount():
            break
        _time.sleep(0.02)
    assert win.hits_model.rowCount() == 1 and "S. 3" in win.hits_model.item(0).text()
    win.close()
    assert saved and isinstance(saved[0], bytes)              # Größe/Position wird weitergereicht


def test_f1_opens_the_manual_at_the_chapter_of_the_current_tab(qapp, monkeypatch, tmp_path):
    import workplanner.ui.main_window as mw
    pdf = tmp_path / "m.pdf"
    _sample_manual(pdf)
    monkeypatch.setattr(mw, "manual_path", lambda: pdf)
    svc = TimeService(Database(), Clock(8, 0))
    w = MainWindow(svc)
    assert w._help_chapter() == "4"                          # „Heute“: Zeit erfassen
    w.tabs.setCurrentWidget(w.week)
    assert w._help_chapter() == "9"
    w.tabs.setCurrentWidget(w.report)
    assert w._help_chapter() == "10"
    w.open_manual("2")
    assert w._manual_win is not None and w._manual_win.isVisible()
    w._manual_win.close()
    assert svc.manual_geometry()                              # gemerkt für das nächste Mal


def test_pause_button_stops_the_task_and_continue_resumes_it(qapp):
    db = Database()
    seed(db)
    clock = Clock(9, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    pid = svc.projects()[0]["id"]
    clock.set(9)
    w._pick_project(pid)
    clock.set(10)
    w.refresh()
    assert w.pause_run_btn.isVisible() or not w.isVisible()
    assert w.pause_run_btn.text() == "⏸ Pause" and "Neu" in w.new_btn.text()
    w.pause_run_btn.click()
    # in der Pause ersetzt „Weiter“ den Knopf „Neu“; „Pause“ ist weg, Stopp bleibt
    assert svc.current().kind == "pause" and w.new_btn.text().startswith("▶  Weiter") and w.pause_run_btn.isHidden()
    assert svc.project_display(pid) in w.new_btn.toolTip()                 # der Knopf nennt die Aufgabe (Text evtl. gekürzt)
    assert w.new_btn.width() == w.new_btn.maximumWidth()                   # feste Breite: Notizfeld springt nicht
    assert not w.stop_btn.isHidden()
    clock.set(10, 20)
    w.new_btn.click()
    run = svc.current()
    assert run.kind == "work" and run.project_id == pid and "Neu" in w.new_btn.text()
    assert [(e.kind, e.start.hour, e.start.minute) for e in svc.day_entries(clock().date())] == [
        ("work", 9, 0), ("pause", 10, 0), ("work", 10, 20)]
    assert "Mittagspause" in w.lunch_label.text()


def test_double_click_on_quick_select_title_opens_the_master_data(qapp):
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9, 0)))
    opened = []
    w.show_master = lambda section=0: opened.append(section)
    w.quick_title.doubleClicked.emit()
    assert opened == [0] and "Doppelklick" in w.quick_title.toolTip()


def test_entry_dialog_project_list_is_sorted_and_defaults_to_general(qapp):
    from workplanner.ui.dialogs import EntryDialog
    db = Database()
    seed(db)
    db.add_project("Zebra")
    db.add_project("Anton")
    svc = TimeService(db, Clock(9, 0))
    dlg = EntryDialog(svc, svc.now().date(), None, default_start=svc.now())
    names = [dlg.project.itemText(i) for i in range(dlg.project.count())]
    assert "–" not in names and names == sorted(names, key=str.casefold)
    assert dlg.project.currentData() == svc.default_project_id() and dlg.project.currentText() == "Allgemein"


def test_lunch_dialog_deduct_inserts_pause_and_task_keeps_running(qapp, monkeypatch):
    db = Database()
    seed(db)
    clock = Clock(8, 0)
    svc = TimeService(db, clock)
    w = MainWindow(svc)
    w._pick_project(svc.projects()[0]["id"])
    clock.set(12, 10)
    monkeypatch.setattr("workplanner.ui.main_window.ask_lunch_pause", lambda *a: "insert")
    from datetime import time as dtime
    monkeypatch.setattr("workplanner.ui.main_window.ask_pause_times", lambda *a: (dtime(12, 0), 10))
    w._check_lunch_prompt()
    entries = svc.day_entries(svc.now().date())
    assert [e.kind for e in entries] == ["work", "pause", "work"]
    assert (entries[1].start.strftime("%H:%M"), entries[1].end.strftime("%H:%M")) == ("12:00", "12:10")   # gewählte Länge
    assert entries[2].running and svc.current().project_id == entries[0].project_id
    assert not svc.lunch_prompt_due()
