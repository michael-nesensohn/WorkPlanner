import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from test_service import DAY, Clock
from workplanner import timeline as tl
from workplanner.db import Database
from workplanner.devops_sync import hours_by_item
from workplanner.export import ALL_COLUMNS, export_excel
from workplanner.service import TimeService
from workplanner.timeline import Entry
from workplanner.app import seed
from workplanner.ui.dialogs import EntryDialog
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def t(h, m=0):
    return datetime(2026, 11, 2, h, m)


def test_hours_follow_the_link_not_the_note():
    entries = [Entry(t(8), t(9), note="Schnittstelle gebaut, Tests laufen", devops_id=21),
               Entry(t(9), t(9, 30), note="#21 alt (Notiz-Schreibweise)"),      # ältere Einträge zählen weiter
               Entry(t(9, 30), t(10), note="#99 Notiz", devops_id=21),           # Verknüpfung gewinnt
               Entry(t(10), t(11), note="ohne Verknüpfung")]
    assert hours_by_item(entries, t(12)) == {21: 2.0}


def test_link_survives_save_and_meeting_resume():
    db = Database()
    clock = Clock(8)
    svc = TimeService(db, clock)
    pid = db.add_project("P")
    svc.start_task(pid, None, "freie Beschreibung", devops_id=21)
    assert svc.current().devops_id == 21 and svc.current().note == "freie Beschreibung"
    clock.set(13)
    svc.tick()
    assert [e.devops_id for e in svc.day_entries(DAY)] == [21]                  # bleibt ein Eintrag
    resumed = tl.resume_after_meeting(
        tl.interrupt([Entry(t(9), None, devops_id=7, note="x")],
                     Entry(t(10), t(11), note="Termin"), t(10, 20)), t(11, 1))
    assert resumed[-1].devops_id == 7                                           # nach dem Termin weiter verknüpft


def test_old_database_gets_devops_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'work', "
                    "project_id INTEGER, activity_id INTEGER, note TEXT NOT NULL DEFAULT '', "
                    "start_ts TEXT NOT NULL, end_ts TEXT, auto_pause INTEGER NOT NULL DEFAULT 0);"
                    "INSERT INTO entries (start_ts) VALUES ('2026-11-02T08:00:00');")
    c.commit()
    c.close()
    (e,) = Database(path).load_day(DAY)
    assert e.devops_id is None


def test_titles_are_remembered(qapp):
    db = Database()
    svc = TimeService(db, Clock())
    svc.remember_devops_title(21, "Waagen-Anbindung")
    assert svc.devops_title(21) == "Waagen-Anbindung" and svc.devops_title(5) == "" and svc.devops_title(None) == ""
    svc.set_devops_features_cache([{"id": 22, "title": "Export", "epic": "", "start": "", "url": ""}])
    assert svc.devops_title(22) == "Export"


def test_card_shows_link_when_project_differs_and_unlink_button(qapp):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    w = MainWindow(svc)
    svc.start_task(svc.default_project_id(), None, "", devops_id=4411)     # z. B. per „DevOps-ID“ im Eintrag verknüpft
    w.refresh()
    assert not w.devops_box.isHidden() and "#4411" in w.devops_label.text()
    w.unlink_btn.click()
    assert svc.current().devops_id is None and w.devops_box.isHidden()
    assert w.table.item(0, 6).text() == ""


def test_entry_dialog_edits_the_link(qapp):
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.start_task(svc.projects()[0]["id"], None, "Beschreibung")
    clock.set(9)
    svc.stop()
    entry = svc.day_entries(DAY)[0]
    dlg = EntryDialog(svc, DAY, entry)
    assert dlg.devops_id.currentText() == "– keine Verknüpfung –" and dlg._changes() == {}
    dlg.devops_id.setCurrentText("4411")                             # eine ID lässt sich auch eintippen
    assert dlg._changes() == {"devops_id": 4411}
    dlg._save()
    assert svc.day_entries(DAY)[0].devops_id == 4411 and svc.day_entries(DAY)[0].note == "Beschreibung"
    dlg = EntryDialog(svc, DAY, svc.day_entries(DAY)[0])
    assert dlg.devops_id.currentText() == "#4411"                    # nicht in der Liste, aber trotzdem angezeigt
    dlg.devops_id.setCurrentText("")
    dlg._save()
    assert svc.day_entries(DAY)[0].devops_id is None


def test_excel_has_devops_column(tmp_path):
    db = Database()
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.start_task(db.add_project("P"), None, "x", devops_id=4411)
    clock.set(9)
    svc.stop()
    path = tmp_path / "e.xlsx"
    export_excel(path, svc.report_rows(DAY, DAY), svc.daily_target, ALL_COLUMNS)
    ws = load_workbook(path)["Einträge"]
    assert ws["J1"].value == "DevOps" and ws["J2"].value == 4411


# --- Notiz als Task nach DevOps (nur auf Wunsch) ---------------------------------------------------

def test_task_title_is_first_line_shortened():
    from workplanner.devops_sync import task_title
    assert task_title("Schnittstelle gebaut\nTests laufen noch") == "Schnittstelle gebaut"
    assert task_title("\n\n  Erste echte Zeile  \nzweite") == "Erste echte Zeile"
    assert task_title("") == "" and len(task_title("x" * 300)) == 120 and task_title("x" * 300).endswith("…")


def test_old_database_gets_task_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'work', "
                    "project_id INTEGER, activity_id INTEGER, note TEXT NOT NULL DEFAULT '', "
                    "start_ts TEXT NOT NULL, end_ts TEXT, auto_pause INTEGER NOT NULL DEFAULT 0);"
                    "INSERT INTO entries (start_ts) VALUES ('2026-11-02T08:00:00');")
    c.commit()
    c.close()
    (e,) = Database(path).load_day(DAY)
    assert e.devops_task_id is None


def test_mark_entry_task_is_saved_and_shown_in_the_table(qapp):
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.start_task(svc.projects()[0]["id"], None, "Schnittstelle gebaut", devops_id=211)
    clock.set(9)
    svc.stop()
    (e,) = svc.day_entries(DAY)
    svc.mark_entry_task(e.id, 5001)
    assert svc.day_entries(DAY)[0].devops_task_id == 5001
    w = MainWindow(svc)
    assert w.table.item(0, 6).text() == "#211 → Task #5001"


def test_devops_client_reports_missing_setup(qapp):
    from workplanner.devops import DevOpsError
    db = Database()
    svc = TimeService(db, Clock())
    with pytest.raises(DevOpsError, match="nicht eingerichtet"):      # ohne Voreinstellung: erst Adresse eintragen
        svc.devops_client()
    svc.set_devops_config("o", "p", "t", True)
    with pytest.raises(DevOpsError, match="Kein Token"):
        svc.devops_client()
    svc.set_devops_config("o", "p", "t", True, "geheim")
    client = svc.devops_client(lambda *a: a)
    assert client == ("o", "p", "t", "geheim")


class FakeTaskClient:
    created = []

    def __init__(self, *args):
        pass

    def create_task(self, parent_id, title, description):
        from workplanner.devops import WorkItem
        if "kaputt" in description:
            from workplanner.devops import DevOpsError
            raise DevOpsError("Berechtigung fehlt")
        FakeTaskClient.created.append((parent_id, title, description))
        return WorkItem(9000 + len(FakeTaskClient.created), title, "Task", "New", "", parent_id, "", "u")


def make_entries(svc, clock):
    pid = svc.projects()[0]["id"]
    clock.set(8)
    svc.start_task(pid, None, "Schnittstelle gebaut\nTests laufen noch", devops_id=211)
    clock.set(9)
    svc.start_task(pid, None, "ohne Verknüpfung")
    svc.edit_entry(svc.current().id, {"devops_id": None})
    clock.set(10)
    svc.start_task(pid, None, "", devops_id=211)                                 # keine Notiz
    clock.set(11)
    svc.start_task(pid, None, "das ist kaputt", devops_id=212)
    clock.set(12)
    svc.stop()
    return svc.day_entries(DAY)


def test_note_task_dialog_lists_only_possible_entries_and_creates_tasks(qapp):
    import time as _time
    from PySide6.QtCore import Qt
    from workplanner.ui.note_task_dialog import NoteTaskDialog
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.set_devops_config("o", "p", "t", True, "geheim")
    entries = make_entries(svc, clock)
    dlg = NoteTaskDialog(svc, entries, client_factory=FakeTaskClient)
    t = dlg.table
    reasons = [t.item(r, 4).text() for r in range(4)]
    assert reasons == ["", "nicht mit einer Story verknüpft", "keine Notiz", ""]
    assert [t.item(r, 0).checkState() == Qt.Checked for r in range(4)] == [True, False, False, True]
    assert t.item(0, 3).text() == "Schnittstelle gebaut"                      # Titel = erste Zeile
    assert dlg.ok.text() == "2 Task(s) in DevOps anlegen" and dlg.ok.isEnabled()
    t.item(3, 0).setCheckState(Qt.Unchecked)
    assert dlg.ok.text() == "1 Task(s) in DevOps anlegen"
    FakeTaskClient.created = []
    dlg._create()
    end = _time.time() + 3
    while "✓" not in dlg.status.text() and _time.time() < end:                # fertig, wenn der Haken da ist
        qapp.processEvents()
        _time.sleep(0.01)
    assert FakeTaskClient.created == [(211, "Schnittstelle gebaut", "Schnittstelle gebaut\nTests laufen noch")]
    assert svc.day_entries(DAY)[0].devops_task_id == 9001                      # gemerkt
    assert "1 Task(s) in DevOps angelegt" in dlg.status.text()
    again = NoteTaskDialog(svc, svc.day_entries(DAY), client_factory=FakeTaskClient)
    assert again.table.item(0, 4).text() == "schon als Task #9001 gesendet" and again.selected()[0].devops_id == 212


def test_note_task_dialog_reports_failures_and_keeps_going(qapp):
    import time as _time
    from workplanner.ui.note_task_dialog import NoteTaskDialog
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.set_devops_config("o", "p", "t", True, "geheim")
    entries = make_entries(svc, clock)
    dlg = NoteTaskDialog(svc, entries, client_factory=FakeTaskClient)       # beide möglichen Einträge angehakt
    FakeTaskClient.created = []
    dlg._create()
    end = _time.time() + 3
    while "Fehlgeschlagen" not in dlg.status.text() and _time.time() < end:
        qapp.processEvents()
        _time.sleep(0.01)
    assert "1 Task(s) in DevOps angelegt" in dlg.status.text() and "Berechtigung fehlt" in dlg.status.text()
    day = svc.day_entries(DAY)
    assert day[0].devops_task_id and day[3].devops_task_id is None          # nur der erfolgreiche ist markiert


def test_note_task_dialog_without_token_shows_hint(qapp):
    from workplanner.ui.note_task_dialog import NoteTaskDialog
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    entries = make_entries(svc, clock)
    svc.set_devops_config("o", "p", "t", True)                      # Adresse da, Token fehlt
    dlg = NoteTaskDialog(svc, entries, client_factory=FakeTaskClient)
    dlg._create()
    assert "Kein Token" in dlg.status.text() and dlg.ok.isEnabled()


def test_main_window_button_needs_a_selection(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    w._note_to_task()
    assert shown and "markieren" in shown[0]


# --- DevOps-ID im Bearbeiten-Dialog aus einer Liste wählen -----------------------------------------------

CACHE = [{"id": 21, "title": "Waagen-Anbindung", "type": "feature", "epic": "", "start": "", "url": ""},
         {"id": 211, "title": "Waage lesen", "type": "story", "parent_id": 21, "parent_title": "Waagen-Anbindung",
          "epic": "", "start": "", "url": ""},
         {"id": 22, "title": "Export nach Excel", "type": "feature", "epic": "", "start": "", "url": ""}]


def entry_dialog(cache=CACHE):
    db = Database()
    seed(db)
    clock = Clock(8)
    svc = TimeService(db, clock)
    svc.set_devops_features_cache(cache)
    svc.start_task(svc.projects()[0]["id"], None, "Beschreibung")
    clock.set(9)
    svc.stop()
    return svc, EntryDialog(svc, DAY, svc.day_entries(DAY)[0])


def test_devops_combo_lists_features_with_their_stories(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    svc, dlg = entry_dialog()
    box = dlg.devops_id
    assert [box.itemText(i) for i in range(box.count())] == [
        "– keine Verknüpfung –", "#21  Waagen-Anbindung", "↳ #211  Waage lesen", "#22  Export nach Excel"]
    assert [box.itemData(i) for i in range(box.count())] == [None, 21, 211, 22]
    assert box.isEditable() and box.completer().filterMode().name == "MatchContains"       # Teilsuche im Titel
    box.setCurrentIndex(2)
    assert dlg._changes() == {"devops_id": 211}
    dlg._save()
    assert svc.day_entries(DAY)[0].devops_id == 211
    again = EntryDialog(svc, DAY, svc.day_entries(DAY)[0])
    assert again.devops_id.currentText() == "↳ #211  Waage lesen"                        # gewählter Eintrag steht da


def test_selecting_an_item_adopts_the_existing_feature_project(qapp):
    svc, dlg = entry_dialog()
    feature_project = svc.add_project("Waagen-Anbindung", "21")
    dlg = EntryDialog(svc, DAY, svc.day_entries(DAY)[0])
    assert dlg.project.currentData() != feature_project
    dlg.devops_id.setCurrentIndex(2)                       # Story 211 -> Projekt ihres Features
    dlg._devops_selected(2)
    assert dlg.project.currentData() == feature_project and dlg._changes()["project_id"] == feature_project
    dlg.devops_id.setCurrentIndex(3)                       # Feature 22 ohne Projekt: Projekt bleibt
    dlg._devops_selected(3)
    assert dlg.project.currentData() == feature_project


def test_a_typed_title_that_matches_no_item_blocks_saving(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    svc, dlg = entry_dialog()
    save = dlg.buttons.button(QDialogButtonBox.Save)
    dlg.devops_id.setCurrentText("Waag")                   # nur angefangen, nichts gewählt
    assert not save.isEnabled() and "aus der Liste wählen" in dlg.preview.text()
    dlg.devops_id.setCurrentText("#4411")
    assert save.isEnabled() and dlg._devops_id() == 4411
    dlg.devops_id.setCurrentText("waage lesen".upper())    # Groß-/Kleinschreibung egal, wenn der ganze Text stimmt
    dlg.devops_id.setCurrentText("↳ #211  Waage lesen")
    assert dlg._devops_id() == 211 and save.isEnabled()
    dlg.devops_id.setCurrentIndex(0)
    assert dlg._devops_id() is None and save.isEnabled()


def test_combo_also_works_without_any_cached_items(qapp):
    svc, dlg = entry_dialog(cache=[])
    assert dlg.devops_id.count() == 1 and dlg._devops_id() is None
    dlg.devops_id.setCurrentText("99")
    assert dlg._devops_id() == 99


def test_insert_dialog_can_pick_the_link_too(qapp):
    from datetime import datetime
    svc, _ = entry_dialog()
    svc._clock.set(12, 0)                                    # „jetzt“ liegt nach dem neuen Eintrag
    dlg = EntryDialog(svc, DAY, None, default_start=datetime(2026, 11, 2, 10))
    dlg.devops_id.setCurrentIndex(1)
    dlg._save()
    assert [e.devops_id for e in svc.day_entries(DAY)] == [None, 21]
