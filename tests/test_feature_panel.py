import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from test_service import Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.devops import DevOpsError, WorkItem
from workplanner.service import TimeService
from workplanner.ui.feature_panel import FeatureFeed, to_cache
from workplanner.ui.main_window import MainWindow

FEATURES = [{"id": 21, "title": "Waagen-Anbindung", "epic": "#3 Demo-Plattform", "start": "2026-11-03", "url": "u21"},
            {"id": 22, "title": "Export nach Excel", "epic": "", "start": "", "url": "u22"}]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def make(clock_hm=(9, 0), with_cache=True):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(*clock_hm))
    if with_cache:
        svc.set_devops_features_cache(FEATURES)
    return MainWindow(svc), svc


def wait(qapp, cond, seconds=3):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def test_to_cache_keeps_features_and_stories_with_their_parents():
    f = WorkItem(21, "Waage", "Feature", "Active", "", 3, "Plattform", "u", start_date=date(2026, 11, 3))
    s = WorkItem(11, "Story", "User Story", "New", "", 21, "Waage", "u2", 3, "Plattform")
    cache = to_cache([f, s])
    assert cache[0] == {"id": 21, "title": "Waage", "type": "feature", "state": "Active", "parent_id": 3,
                        "parent_title": "Plattform", "epic": "#3 Plattform", "start": "2026-11-03", "url": "u"}
    assert (cache[1]["type"], cache[1]["parent_id"], cache[1]["parent_title"], cache[1]["epic"]) == (
        "story", 21, "Waage", "#3 Plattform")


def test_tiles_appear_instantly_from_cache_next_to_the_quick_selection(qapp):
    w, svc = make()
    assert sorted(w.features._buttons) == [21, 22]
    assert "2 Features, 0 Stories (zuletzt geladen)" in w.features.status.text()
    assert "Demo-Plattform" in w.features._buttons[21].toolTip() and "2026-11-03" in w.features._buttons[21].toolTip()
    # liegt links neben der Schnellauswahl (gleiche Zeile, kleinere x-Position)
    w.show()
    qapp.processEvents()
    assert w.features.geometry().right() <= w.tiles.parentWidget().mapTo(w, w.tiles.parentWidget().rect().topLeft()).x()


def test_without_cache_hint_is_shown(qapp):
    w, svc = make(with_cache=False)
    assert w.features._buttons == {} and "Noch nicht geladen" in w.features.status.text()


def test_click_books_on_the_feature_as_a_normal_project(qapp):
    w, svc = make()
    w.features._buttons[21].click()
    pid = svc.find_project(number="21")
    run = svc.current()
    assert svc.project_name(pid) == "Waagen-Anbindung" and run.project_id == pid
    assert run.devops_id == 21 and run.note == ""                         # Notiz bleibt frei
    assert w.task_label.text() == "21  Waagen-Anbindung"                  # dort, wo sonst „Allgemein“ steht
    assert w.table.item(0, 4).text() == "21  Waagen-Anbindung"
    assert w.devops_box.isHidden()                                        # Feature = Projekt: keine Doppelanzeige
    assert w.features._buttons[21].isChecked() and not w.features._buttons[22].isChecked()
    assert next(p for p in svc.projects() if p["id"] == pid)["favorite"] == 0
    w.features._buttons[22].click()                                       # jedes Feature ist ein eigenes Projekt
    assert svc.current().project_id == svc.find_project(number="22") != pid
    assert w.features._buttons[22].isChecked() and not w.features._buttons[21].isChecked()
    w.features._buttons[21].click()                                       # nichts doppelt angelegt
    assert [p["number"] for p in svc.projects() if p["number"] in ("21", "22")].count("21") == 1


def test_click_reuses_existing_project_by_number_or_name(qapp):
    w, svc = make()
    existing = svc.add_project("Mein Waagen-Projekt", "21")              # gleiche Nummer
    w.features._buttons[21].click()
    assert svc.current().project_id == existing
    named = svc.add_project("Export nach Excel")                          # gleicher Name, noch ohne Nummer
    w.features._buttons[22].click()
    assert svc.current().project_id == named and svc.project_number(named) == "22"
    svc.devops_features_cache()
    other = svc.add_project("Anderes Feature", "99")
    assert svc.ensure_devops_project(100, "Anderes Feature") == (svc.find_project(number="100"), True)
    assert svc.project_name(svc.find_project(number="100")) == "Anderes Feature (100)"     # Name belegt, Nummer anders


def test_click_on_blank_running_time_assigns_the_feature(qapp):
    w, svc = make()
    w._start_blank()                                                     # Zeit läuft auf „Allgemein“, unbeschrieben
    first = svc.current().id
    w.features._buttons[22].click()
    assert svc.current().id == first                                     # kein neuer Eintrag, die Zeit gehört dem Feature
    assert svc.current().project_id == svc.find_project(number="22") and svc.current().devops_id == 22
    assert len(svc.day_entries(w.day)) == 1


def test_new_feature_project_shows_up_in_settings_lists(qapp):
    w, svc = make()
    w.features._buttons[21].click()
    assert any("Waagen-Anbindung" in w.master.projects.item(i).text() for i in range(w.master.projects.count()))
    assert w.report.project.findText("Waagen-Anbindung") >= 0


def test_tile_gets_color_of_its_project(qapp):
    w, svc = make()
    pid = svc.add_project("Waagen-Anbindung", "21")
    svc.db.update_project(pid, color="#ff0000")
    w._master_changed()
    assert "#ff0000" in w.features._buttons[21].styleSheet()
    assert "#c4cbd6" in w.features._buttons[22].styleSheet()   # ohne Projekt: neutrales Grau


class FakeClient:
    calls = []

    def __init__(self, org, project, team, pat):
        self.args = (org, project, team, pat)

    def fetch_features(self, only_mine):
        FakeClient.calls.append((self.args, only_mine))
        return [WorkItem(30, "Neues Feature", "Feature", "New", "", 3, "Epic X", "u30")]

    def fetch_stories(self, only_mine):
        return [WorkItem(31, "Story dazu", "User Story", "New", "", 30, "Neues Feature", "u31", 3, "Epic X")]


def test_auto_refresh_loads_and_caches_features(qapp):
    w, svc = make()
    svc.set_devops_config("o", "p", "t", True, "geheim")
    w.feed._factory = FakeClient
    FakeClient.calls = []
    w.feed.refresh()
    assert wait(qapp, lambda: sorted(w.features._buttons) == [30, 31])
    assert FakeClient.calls == [(("o", "p", "t", "geheim"), True)]
    assert [f["id"] for f in svc.devops_features_cache()] == [30, 31]   # Features und Stories fürs nächste Mal gemerkt
    assert "1 Features, 1 Stories ·" in w.features.status.text()
    assert wait(qapp, lambda: not w.feed._busy)


def test_refresh_reports_missing_token_and_errors_but_keeps_old_tiles(qapp):
    w, svc = make()
    svc.set_devops_config("o", "p", "t", True)                           # Adresse da, Token fehlt
    w.feed.refresh()
    assert wait(qapp, lambda: "Kein Token" in w.features.status.text())
    assert sorted(w.features._buttons) == [21, 22]                       # alte Kacheln bleiben

    svc.set_devops_config("o", "p", "t", True, "geheim")

    class Failing(FakeClient):
        def fetch_features(self, only_mine):
            raise DevOpsError("Anmeldung oder Berechtigung fehlgeschlagen")
    w.feed._factory = Failing
    w.feed.refresh()
    assert wait(qapp, lambda: "Anmeldung" in w.features.status.text())
    assert sorted(w.features._buttons) == [21, 22] and not w.feed._busy


def test_items_loaded_in_devops_tab_update_the_tiles_only_for_the_full_view(qapp):
    w, svc = make()
    items = [WorkItem(40, "Aus dem Tab", "Feature", "New", "", 3, "Epic", "u40"),
             WorkItem(41, "Story", "User Story", "New", "", 40, "Aus dem Tab", "u41", 3, "Epic")]
    w.devops._loaded_view = "stories"
    w.devops._on_loaded([items[1]], None)                                # nur Stories geladen: Kacheln bleiben
    assert sorted(w.features._buttons) == [21, 22]
    w.devops._loaded_view = "both"
    w.devops._on_loaded(items, None)
    assert sorted(w.features._buttons) == [40, 41]




STORIES = [{"id": 211, "title": "Waage lesen", "type": "story", "state": "Active", "parent_id": 21,
            "parent_title": "Waagen-Anbindung", "epic": "#3 Demo-Plattform", "start": "", "url": "u211"},
           {"id": 212, "title": "Waage kalibrieren", "type": "story", "state": "New", "parent_id": 21,
            "parent_title": "Waagen-Anbindung", "epic": "#3 Demo-Plattform", "start": "", "url": "u212"}]


def test_group_items_nests_stories_and_fills_missing_parents():
    from workplanner.ui.feature_panel import group_items
    groups, loose = group_items(FEATURES + STORIES)
    assert [(f["id"], [s["id"] for s in stories]) for f, stories in groups] == [(21, [211, 212]), (22, [])]
    orphan = {"id": 300, "title": "Fremdes Feature-Kind", "type": "story", "parent_id": 99, "parent_title": "Anderes Feature",
              "epic": "#7 E", "url": ""}
    lonely = {"id": 301, "title": "Ohne Feature", "type": "story", "parent_id": None, "parent_title": "", "url": ""}
    groups, loose = group_items(FEATURES + [orphan, lonely])
    assert [f["id"] for f, _ in groups] == [21, 22, 99]                   # Feature 99 wird aus der Story ergänzt
    assert groups[2][0]["title"] == "Anderes Feature" and groups[2][1] == [orphan]
    assert loose == [lonely]


def test_stories_are_indented_under_their_feature(qapp):
    w, svc = make()
    svc.set_devops_features_cache(FEATURES + STORIES)
    w2 = MainWindow(svc)
    assert sorted(w2.features._buttons) == [21, 22, 211, 212]
    assert "2 Features, 2 Stories (zuletzt geladen)" in w2.features.status.text()
    # Feature 21 hat am 03.11. (diese Woche) ein Datum und steht samt Stories zuerst, dann Feature 22
    assert w2.features.order == [21, 211, 212, 22] and w2.features.separator_pos == 3
    rows = {}
    for i in range(w2.features.tiles.count()):
        lay = w2.features.tiles.itemAt(i).layout()
        if lay is not None and lay.count():
            rows[lay.itemAt(0).widget()] = lay.contentsMargins().left()
    margins = [rows[w2.features._buttons[i]] for i in w2.features.order]
    assert margins == [0, 18, 18, 0]                                      # Stories eingerückt
    assert "Feature: Waagen-Anbindung" in w2.features._buttons[211].toolTip()


def test_click_on_story_books_on_its_feature_project_and_links_the_story(qapp):
    w, svc = make()
    svc.set_devops_features_cache(FEATURES + STORIES)
    w = MainWindow(svc)
    w.features._buttons[211].click()
    pid = svc.find_project(number="21")
    run = svc.current()
    assert svc.project_name(pid) == "Waagen-Anbindung" and run.project_id == pid   # das Feature ist das Projekt
    assert run.devops_id == 211 and run.note == ""                                 # die Story hängt darunter
    assert w.task_label.text() == "21  Waagen-Anbindung"                           # dort, wo sonst „Allgemein“ steht
    assert not w.devops_box.isHidden() and w.devops_label.text() == "#211 Waage lesen"   # Story als Verknüpfung
    assert w.table.item(0, 4).text() == "21  Waagen-Anbindung" and w.table.item(0, 6).text() == "#211"
    assert w.features._buttons[211].isChecked() and not w.features._buttons[21].isChecked()
    assert svc.find_project(number="211") is None                                  # keine Story-Projekte
    w.note.setPlainText("Schnittstelle gebaut")
    w._note_edited()
    assert svc.current().note == "Schnittstelle gebaut" and svc.current().devops_id == 211


def test_switching_between_stories_of_one_feature_keeps_the_project(qapp):
    w, svc = make()
    svc.set_devops_features_cache(FEATURES + STORIES)
    w = MainWindow(svc)
    w.features._buttons[211].click()
    svc._clock.set(10, 0)
    w.features._buttons[212].click()
    first, second = svc.day_entries(w.day)
    assert first.project_id == second.project_id == svc.find_project(number="21")
    assert (first.devops_id, second.devops_id) == (211, 212)
    assert len([p for p in svc.projects() if p["number"] == "21"]) == 1


def test_story_without_feature_uses_selected_or_default_project(qapp):
    w, svc = make()
    lonely = {"id": 301, "title": "Ohne Feature", "type": "story", "parent_id": None, "parent_title": "",
              "epic": "", "start": "", "url": ""}
    svc.set_devops_features_cache(FEATURES + [lonely])
    w = MainWindow(svc)
    w.features._buttons[301].click()
    assert svc.current().project_id == svc.default_project_id() and svc.current().devops_id == 301
    assert not w.devops_box.isHidden()


def test_story_of_a_feature_missing_in_the_list_still_gets_that_feature_as_project(qapp):
    w, svc = make()
    orphan = {"id": 300, "title": "Story", "type": "story", "parent_id": 99, "parent_title": "Fremdes Feature",
              "epic": "", "start": "", "url": ""}
    svc.set_devops_features_cache(FEATURES + [orphan])
    w = MainWindow(svc)
    w.features._buttons[300].click()
    assert svc.project_name(svc.find_project(number="99")) == "Fremdes Feature"
    assert svc.current().project_id == svc.find_project(number="99") and svc.current().devops_id == 300


def test_story_hours_go_to_the_story_in_devops(qapp):
    w, svc = make()
    svc.set_devops_features_cache(FEATURES + STORIES)
    w = MainWindow(svc)
    w.features._buttons[211].click()
    svc._clock.set(10, 0)                                                    # eine Stunde läuft auf der Story
    assert svc.devops_hours() == {211: 1.0}                                  # …und geht dort hin, nicht auf das Feature


# --- Sortierung: diese Woche zuerst, dann ein Strich, dann der Rest ---------------------------------

from workplanner.ui.feature_panel import group_items, split_by_week, week_bounds  # noqa: E402


def feat(i, start="", title=None):
    return {"id": i, "title": title or f"F{i}", "type": "feature", "epic": "", "start": start, "url": ""}


def story(i, parent, start=""):
    return {"id": i, "title": f"S{i}", "type": "story", "parent_id": parent, "parent_title": f"F{parent}",
            "epic": "", "start": start, "url": ""}


MONDAY = date(2026, 11, 2)


def test_week_bounds_are_monday_to_sunday():
    assert week_bounds(date(2026, 11, 2)) == (date(2026, 11, 2), date(2026, 11, 8))     # Montag
    assert week_bounds(date(2026, 11, 5)) == (date(2026, 11, 2), date(2026, 11, 8))     # Donnerstag
    assert week_bounds(date(2026, 11, 8)) == (date(2026, 11, 2), date(2026, 11, 8))     # Sonntag


def test_split_puts_dated_this_week_first_sorted_by_date():
    items = [feat(1), feat(2, "2026-11-06"), feat(3, "2026-10-20"), feat(4, "2026-11-02"), feat(5, "2026-11-09"),
             feat(6, "2026-11-08"), feat(7, "2026-11-01")]
    groups, loose = group_items(items)
    week, week_loose, others, other_loose = split_by_week(groups, loose, date(2026, 11, 4))
    assert [f["id"] for f, _ in week] == [4, 2, 6]                  # Mo, Fr, So – nach Datum
    assert [f["id"] for f, _ in others] == [1, 3, 5, 7]             # ohne Datum / andere Wochen: alte Reihenfolge
    assert week_loose == [] and other_loose == []


def test_a_dated_story_promotes_its_feature_and_loose_stories_are_split_too():
    items = [feat(1), feat(2, "2026-10-01"), story(21, 2, "2026-11-04"), story(31, None, "2026-11-03"),
             story(32, None), story(33, None, "2026-12-01")]
    groups, loose = group_items(items)
    week, week_loose, others, other_loose = split_by_week(groups, loose, MONDAY)
    assert [f["id"] for f, _ in week] == [2] and [s["id"] for s in week[0][1]] == [21]
    assert [f["id"] for f, _ in others] == [1]
    assert [s["id"] for s in week_loose] == [31] and [s["id"] for s in other_loose] == [32, 33]


def test_invalid_dates_are_treated_as_undated():
    groups, loose = group_items([feat(1, "kein Datum"), feat(2, "2026-13-45"), feat(3, "2026-11-03")])
    week, _, others, _ = split_by_week(groups, loose, MONDAY)
    assert [f["id"] for f, _ in week] == [3] and [f["id"] for f, _ in others] == [1, 2]


def panel_with(items, today):
    from workplanner.ui.feature_panel import FeaturePanel
    panel = FeaturePanel(lambda i: None, today=lambda: today)
    panel.set_items(items)
    return panel


def test_panel_shows_this_week_then_a_line_then_the_rest(qapp):
    from PySide6.QtWidgets import QFrame, QLabel
    panel = panel_with([feat(1), feat(2, "2026-11-05"), feat(3, "2026-11-03"), feat(4, "2026-10-01")], MONDAY)
    assert panel.order == [3, 2, 1, 4] and panel.separator_pos == 2
    kinds = []
    for i in range(panel.tiles.count()):
        it = panel.tiles.itemAt(i)
        if it.widget() is not None:
            w = it.widget()
            kinds.append(w.text() if isinstance(w, QLabel) else "Linie" if w.frameShape() == QFrame.HLine else "?")
        elif it.layout() is not None and it.layout().count():
            kinds.append("Kachel")
    assert kinds[0].startswith("<span") and "Diese Woche · KW 45" in kinds[0]       # Überschrift
    assert kinds[1:] == ["Kachel", "Kachel", "Linie", "Kachel", "Kachel"]            # 2 Wochen-Features, Strich, Rest


def test_panel_without_dated_items_has_no_header_and_no_line(qapp):
    from PySide6.QtWidgets import QFrame
    panel = panel_with([feat(1), feat(2, "2026-10-01")], MONDAY)
    assert panel.order == [1, 2] and panel.separator_pos is None
    assert not any(getattr(panel.tiles.itemAt(i).widget(), "frameShape", lambda: None)() == QFrame.HLine
                   for i in range(panel.tiles.count()))
    only_week = panel_with([feat(1, "2026-11-03")], MONDAY)
    assert only_week.order == [1] and only_week.separator_pos is None               # nichts darunter: keine Linie


def test_new_week_resorts_the_list(qapp):
    w, svc = make(with_cache=False)
    svc.set_devops_features_cache([feat(1, "2026-11-03"), feat(2, "2026-11-10")])
    w = MainWindow(svc)
    assert w.features.order == [1, 2] and w.features.separator_pos == 1
    from datetime import datetime
    svc._clock.t = datetime(2026, 11, 9, 8, 0)                           # Montag der nächsten Woche
    w._on_second()
    assert w.features.order == [2, 1] and w.features.separator_pos == 1  # jetzt steht Feature 2 oben
