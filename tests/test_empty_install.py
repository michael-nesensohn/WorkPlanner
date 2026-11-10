import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from test_service import Clock
from workplanner.app import open_database, seed
from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_a_new_database_is_really_empty(tmp_path):
    db = open_database(tmp_path / "neu.db")
    assert db.list_projects(include_archived=True) == [] and db.list_activities(include_archived=True) == []
    assert db.load_range(__import__("datetime").datetime(2000, 1, 1), __import__("datetime").datetime(2100, 1, 1)) == []
    assert db.devops_synced() == {} and db.outlook_imported() == set()


def test_existing_database_is_kept_on_start_as_it_is(tmp_path):
    path = tmp_path / "vorhanden.db"
    first = open_database(path)
    pid = first.add_project("Mein Projekt", number="4711")
    first.add_activity("Meine Tätigkeit")
    first.close()
    again = open_database(path)                         # z. B. nach einem Programm-Update
    assert [p["id"] for p in again.list_projects()] == [pid]
    assert [p["name"] for p in again.list_projects()] == ["Mein Projekt"]
    assert [a["name"] for a in again.list_activities()] == ["Meine Tätigkeit"]


def test_window_works_with_an_empty_database_and_shows_a_hint(qapp, tmp_path):
    svc = TimeService(open_database(tmp_path / "leer.db"), Clock(9))
    w = MainWindow(svc)
    w.master.reload()
    w.report.reload_projects()
    assert svc.db.list_projects(include_archived=True) == []          # schon das Öffnen legt nichts an, auch nicht „Allgemein“
    assert w.master.default_project.currentText().startswith("Allgemein (wird beim ersten Start")
    assert w._tile_buttons() == []
    texts = [w.tiles.itemAt(i).widget().text() for i in range(w.tiles.count())
             if isinstance(w.tiles.itemAt(i).widget(), QLabel)]
    assert any("Noch keine Projekte" in t for t in texts)
    w._start_blank()                                    # Start funktioniert trotzdem (Standardprojekt „Allgemein“)
    assert svc.project_name(svc.current().project_id) == "Allgemein"      # erst jetzt wird es angelegt
    assert [p["name"] for p in svc.db.list_projects()] == ["Allgemein"]
    w.refresh()
    w.week.refresh()
    w.report._update()
    w.master.reload()


def test_hint_disappears_as_soon_as_a_favorite_project_exists(qapp, tmp_path):
    svc = TimeService(open_database(tmp_path / "x.db"), Clock(9))
    w = MainWindow(svc)
    svc.db.add_project("Neu")
    w._rebuild_tiles()
    assert len(w._tile_buttons()) == 1
    assert not any(isinstance(w.tiles.itemAt(i).widget(), QLabel) for i in range(w.tiles.count()))


def test_saving_other_settings_does_not_create_or_pick_a_default_project(qapp, tmp_path):
    svc = TimeService(open_database(tmp_path / "e.db"), Clock(9))
    w = MainWindow(svc)
    svc.db.add_project("Erstes echtes Projekt")
    w.master.reload()
    from PySide6.QtCore import QTime
    w.master.target.setTime(QTime(7, 30))                     # löst „Einstellungen speichern“ aus
    assert svc.daily_target.total_seconds() == 7.5 * 3600
    assert svc.db.get_setting("default_project_id") == ""      # das erste Projekt wurde NICHT stillschweigend zum Standard


def test_outlook_dialog_with_empty_database_creates_nothing(qapp, tmp_path):
    from datetime import date
    from workplanner.ui.outlook_dialog import OutlookImportDialog
    svc = TimeService(open_database(tmp_path / "o.db"), Clock(9))
    OutlookImportDialog(svc, date(2026, 11, 2), reader=lambda a, b: [])
    assert svc.db.list_projects(include_archived=True) == []


def test_data_folder_can_be_redirected_for_test_runs(tmp_path, monkeypatch):
    from workplanner.db import default_db_path
    monkeypatch.setenv("WORKPLANNER_DATA", str(tmp_path / "eigene-daten"))
    assert default_db_path() == tmp_path / "eigene-daten" / "workplanner.db"
    assert (tmp_path / "eigene-daten").is_dir()
    monkeypatch.delenv("WORKPLANNER_DATA")
    assert default_db_path().parent.name == "WorkPlanner"             # sonst wie immer %APPDATA%


def test_isolated_mode_flag(monkeypatch):
    from workplanner.app import isolated_mode
    monkeypatch.delenv("WORKPLANNER_ISOLATED", raising=False)
    assert isolated_mode() is False
    for value, expected in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv("WORKPLANNER_ISOLATED", value)
        assert isolated_mode() is expected


def test_big_database_gives_a_hint_at_startup(tmp_path):
    from workplanner.db import Database
    from workplanner.service import TimeService
    path = tmp_path / "w.db"
    svc = TimeService(Database(path))
    assert svc.db_size_warning() is None                 # klein: kein Hinweis
    svc.set_db_warn_mb(1)
    svc.db.set_setting("blob", "x" * (2 * 1024 * 1024))  # Datei wächst über 1 MB
    text = svc.db_size_warning()
    assert text and "MB groß" in text and str(path) in text
    svc.set_db_warn_mb(0)                                # 0 = nie
    assert svc.db_size_warning() is None
    svc.set_db_warn_mb(1)
    svc.db.conn.execute("DELETE FROM settings WHERE key = 'blob'")
    svc.db.conn.commit()
    svc.db.vacuum()                                      # Komprimieren gibt den Platz frei
    assert svc.db_size_warning() is None
