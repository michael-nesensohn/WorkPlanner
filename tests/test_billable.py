import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import timedelta

import pytest
from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from test_service import DAY, Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.export import ALL_COLUMNS, export_excel
from workplanner.service import TimeService
from workplanner.ui.dialogs import EntryDialog
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env():
    db = Database()
    clock = Clock()
    svc = TimeService(db, clock)
    paid = db.add_project("Kunde", billable=True)
    free = db.add_project("Intern", billable=False)
    return svc, clock, db, paid, free


def test_entry_takes_billable_default_from_project(env):
    svc, clock, db, paid, free = env
    svc.start_task(paid, None)
    clock.set(9)
    svc.start_task(free, None)
    clock.set(10)
    e = svc.day_entries(DAY)
    assert [x.billable for x in e] == [True, False]


def test_billable_can_be_overridden_per_entry(env):
    svc, clock, db, paid, free = env
    svc.start_task(free, None)
    svc.set_running_billable(True)
    clock.set(13)
    svc.tick()
    entries = svc.day_entries(DAY)
    assert [(x.kind, x.billable) for x in entries] == [("work", True)]       # nichts wird mehr zerteilt


def test_changing_project_resets_billable_to_project_default(env):
    svc, clock, db, paid, free = env
    svc.start_task(free, None)
    clock.set(9)
    svc.stop()
    eid = svc.day_entries(DAY)[0].id
    svc.edit_entry(eid, {"project_id": paid})
    assert svc.day_entries(DAY)[0].billable is True
    svc.edit_entry(eid, {"billable": False})
    assert svc.day_entries(DAY)[0].billable is False


def test_dialog_checkbox_follows_project_and_saves(qapp, env):
    svc, clock, db, paid, free = env
    svc.start_task(free, None)
    clock.set(9)
    svc.stop()
    entry = svc.day_entries(DAY)[0]
    dlg = EntryDialog(svc, DAY, entry)
    assert not dlg.billable.isChecked()
    dlg.project.setCurrentIndex(dlg.project.findData(paid))
    assert dlg.billable.isChecked()
    dlg._save()
    assert svc.day_entries(DAY)[0].billable is True


def test_main_window_column_and_checkbox(qapp, env):
    svc, clock, db, paid, free = env
    w = MainWindow(svc)
    w._pick_project(paid)
    clock.set(9)
    w.refresh()
    assert w.table.item(0, 3).text() == "✓" and w.billable_cb.isChecked()
    w.billable_cb.click()
    assert svc.current().billable is False
    assert w.table.item(0, 3).text() == ""
    # Tätigkeiten liegen im Rahmen der Start-Karte
    card = w.findChild(type(w.task_label.parentWidget()), "card")
    assert card is not None and card.isAncestorOf(w.billable_cb)


def test_export_billable_columns(tmp_path, env):
    svc, clock, db, paid, free = env
    svc.start_task(paid, None)
    clock.set(10)
    svc.start_task(free, None)
    clock.set(11)
    svc.stop()
    path = tmp_path / "b.xlsx"
    export_excel(path, svc.report_rows(DAY, DAY), svc.daily_target, ALL_COLUMNS)
    wb = load_workbook(path)
    e = wb["Einträge"]
    assert [e["E2"].value, e["E3"].value] == ["Ja", "Nein"]
    assert wb["Tagessummen"]["D2"].value == timedelta(hours=2)
    p = wb["Projektsummen"]
    assert {p["B2"].value: p["E2"].value, p["B4"].value: p["E4"].value} == {
        "Intern": timedelta(0), "Kunde": timedelta(hours=2)}
