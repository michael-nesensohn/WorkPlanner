import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_service import Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.service import TimeService
from workplanner.timeline import PAUSE, Entry
from workplanner.ui.main_window import MainWindow
from workplanner.ui.pages import WeekPage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def dt(day, h, m=0):
    return datetime(2026, 11, day, h, m)


def week_setup(clock_day=6, clock_h=18):
    db = Database()
    seed(db)
    clock = Clock(clock_h, 0)
    clock.t = datetime(2026, 11, clock_day, clock_h, 0)            # Freitag 06.11.2026 (Woche 02.–08.11.)
    svc = TimeService(db, clock)
    a = db.add_project("Waagen-Anbindung", number="21", billable=True)
    b = db.add_project("Hausintern")
    act = db.add_activity("Programmierung")
    db.save_day(date(2026, 11, 2), [
        Entry(dt(2, 8), dt(2, 9, 30), project_id=a, activity_id=act, note="Schnittstelle gebaut\nTests laufen noch",
              billable=True, devops_id=211),
        Entry(dt(2, 9, 30), dt(2, 11), project_id=b, note="Team-Meeting"),
        Entry(dt(2, 11), dt(2, 12), kind=PAUSE, auto_pause=True)])
    db.save_day(date(2026, 11, 4), [Entry(dt(4, 10), dt(4, 11, 15), project_id=a, note="Review", billable=True)])
    return svc, WeekPage(svc)


def cell(page, row, col):
    it = page.entries.item(row, col)
    return it.text() if it else None


def test_every_day_with_its_bookings_like_the_day_table(qapp):
    svc, page = week_setup()
    t = page.entries
    texts = [cell(page, r, 0) for r in range(t.rowCount())]
    # Mo mit 2 Einträgen (die Pause ist ausgeblendet), Di leer, Mi mit 1, Do/Fr leer, Wochenende wird ausgelassen
    assert texts[0].startswith("Montag 02.11.2026") and "Gearbeitet 3:00 h" in texts[0] and "verrechenbar 1:30 h" in texts[0]
    assert cell(page, 1, 0) == "08:00" and cell(page, 1, 1) == "09:30" and cell(page, 1, 2) == "1:30"
    assert cell(page, 1, 3) == "✓" and cell(page, 1, 4) == "21  Waagen-Anbindung"
    assert cell(page, 1, 5) == "Programmierung" and cell(page, 1, 6) == "#211"
    assert cell(page, 1, 7) == "Schnittstelle gebaut\nTests laufen noch"          # Notiz vollständig, mehrzeilig
    assert cell(page, 2, 4) == "Hausintern" and cell(page, 2, 7) == "Team-Meeting" and cell(page, 2, 3) == ""
    assert not any(cell(page, r, 4) == "Mittagspause" for r in range(t.rowCount()))      # Pausen-Einträge: nur unter „Heute“
    assert texts[3].startswith("Dienstag 03.11.2026") and "nichts gebucht" in texts[3]
    assert texts[4].startswith("Mittwoch 04.11.2026") and "Gearbeitet 1:15 h" in texts[4]
    assert cell(page, 5, 7) == "Review"
    assert texts[6].startswith("Donnerstag") and texts[7].startswith("Freitag")
    assert not any(x and x.startswith(("Samstag", "Sonntag")) for x in texts)       # Wochenende leer: ausgelassen
    assert texts[-1] == ("Woche gesamt: 4:15 h   ·   davon verrechenbar 2:45 h   ·   "
                         "Wochenstunden Soll 40:00 h   ·   Differenz –35:45 h")
    assert "Soll 8:00 h" in texts[0] and "Differenz –5:00 h" in texts[0]


def test_weekend_days_appear_when_something_was_booked(qapp):
    svc, page = week_setup()
    pid = svc.projects()[0]["id"]
    svc.db.save_day(date(2026, 11, 7), [Entry(dt(7, 9), dt(7, 10), project_id=pid, note="Samstagsarbeit")])
    page.refresh()
    texts = [cell(page, r, 0) for r in range(page.entries.rowCount())]
    assert any(x and x.startswith("Samstag 07.11.2026") for x in texts)
    assert not any(x and x.startswith("Sonntag") for x in texts)


def test_durations_are_net_of_the_lunch_break_with_tooltip(qapp):
    svc, page = week_setup()
    pid = svc.projects()[0]["id"]
    svc.db.save_day(date(2026, 11, 5), [Entry(dt(5, 11), dt(5, 14), project_id=pid, note="über Mittag")])
    page.refresh()
    row = next(r for r in range(page.entries.rowCount()) if cell(page, r, 7) == "über Mittag")
    assert cell(page, row, 2) == "2:30" and "3:00 brutto" in page.entries.item(row, 2).toolTip()


def test_running_entry_shows_live_and_navigation_changes_the_week(qapp):
    svc, page = week_setup(clock_day=6, clock_h=15)
    svc.start_task(svc.projects()[0]["id"], None, "läuft gerade")
    svc._clock.t = datetime(2026, 11, 6, 16, 0)
    page.refresh()
    row = next(r for r in range(page.entries.rowCount()) if cell(page, r, 7) == "läuft gerade")
    assert cell(page, row, 1) == "läuft" and cell(page, row, 2) == "1:00"
    page._go(7)                                                      # nächste Woche: nichts gebucht
    assert page.title.text() == "09.11. – 15.11.2026"
    assert all("nichts gebucht" in cell(page, r, 0) or "Woche gesamt" in cell(page, r, 0)
               for r in range(page.entries.rowCount()))
    page._go(-14)                                                    # Vorwoche
    assert page.title.text() == "26.10. – 01.11.2026"


def test_overview_tab_is_unchanged(qapp):
    svc, page = week_setup()
    assert page.views.tabText(0) == "Übersicht" and page.views.tabText(1) == "Einträge"
    assert page.days.item(0, 1).text() == "3:00" and page.days.item(7, 1).text() == "4:15"
    assert page.projects.rowCount() == 2


def test_notes_are_fully_visible_row_height_follows_text(qapp):
    svc, page = week_setup()
    t = page.entries
    assert t.wordWrap() and t.rowHeight(1) > t.rowHeight(2)           # mehrzeilige Notiz -> höhere Zeile


def test_double_click_opens_the_day_in_the_today_tab(qapp):
    svc, _ = week_setup()
    w = MainWindow(svc)
    w.tabs.setCurrentWidget(w.week)
    w.week.refresh()
    assert w.day == date(2026, 11, 6)
    row = next(r for r in range(w.week.entries.rowCount()) if cell(w.week, r, 7) == "Review")
    w.week.entries.cellDoubleClicked.emit(row, 4)                    # Eintrag vom 04.11.
    assert w.day == date(2026, 11, 4) and w.tabs.currentIndex() == 0
    assert w.table.rowCount() == 1 and w.table.item(0, 7).text() == "Review"
    w.tabs.setCurrentWidget(w.week)
    head = next(r for r in range(w.week.entries.rowCount()) if (cell(w.week, r, 0) or "").startswith("Montag"))
    w.week.entries.cellDoubleClicked.emit(head, 0)                   # Tageszeile
    assert w.day == date(2026, 11, 2)


def test_week_pauses_hidden_by_default_and_summed_in_the_overview(qapp):
    svc, page = week_setup()
    assert not page.show_pauses.isChecked()
    assert page.days.item(0, 5).text() == "1:00" and page.days.item(7, 5).text() == "1:00"   # Pausensumme immer da
    assert not any(cell(page, r, 4) == "Mittagspause" for r in range(page.entries.rowCount()))
    page.show_pauses.setChecked(True)                                                       # auf Wunsch sichtbar
    t = page.entries
    assert any(cell(page, r, 4) == "Mittagspause" for r in range(t.rowCount()))
    assert "Pausen 1:00 h" in cell(page, 0, 0) and "Pausen 1:00 h" in cell(page, t.rowCount() - 1, 0)
    assert page.days.item(0, 1).text() == "3:00"                                            # Arbeitszeit bleibt gleich
