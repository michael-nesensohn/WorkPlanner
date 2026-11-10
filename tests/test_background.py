"""Hintergrundarbeit in Dialogen: Der Thread darf nie ein Qt-Fenster festhalten oder zerstören."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import threading
import time
from datetime import date

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication

from test_excel_ui import setup as excel_setup
from test_service import Clock
from workplanner.db import Database
from workplanner.excel_timesheet import ExcelError
from workplanner.service import TimeService
from workplanner.ui.about_dialog import AboutDialog
from workplanner.ui.background import BackgroundRunner
from workplanner.ui.excel_dialog import ExcelExportDialog
from workplanner.ui.outlook_dialog import OutlookImportDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def pump(qapp, cond, seconds=3):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    return cond()


# --- der Helfer selbst ----------------------------------------------------------------------------

class Boom(Exception):
    pass


def test_result_error_and_progress_arrive_in_the_gui_thread(qapp):
    owner = QObject()
    bg = BackgroundRunner(owner)
    seen = []
    main = threading.main_thread()
    bg.run(lambda: 42, lambda v, e: seen.append(("ok", v, e, threading.current_thread() is main)))
    bg.run(lambda: (_ for _ in ()).throw(Boom("kaputt")), lambda v, e: seen.append(("exp", v, e)), expected=(Boom,))
    bg.run(lambda: 1 / 0, lambda v, e: seen.append(("unexp", v, e)), expected=(Boom,))
    steps = []

    def with_progress(report):
        report(1, 3)
        report(3, 3)
        return "fertig"
    bg.run(with_progress, lambda v, e: seen.append(("prog", v, e)), on_progress=lambda a, b: steps.append((a, b)))
    assert pump(qapp, lambda: len(seen) == 4 and not bg.busy)
    got = {s[0]: s for s in seen}
    assert got["ok"] == ("ok", 42, None, True)
    assert got["exp"] == ("exp", None, "kaputt")
    assert got["unexp"][1] is None and got["unexp"][2].startswith("Unerwarteter Fehler: ")
    assert got["prog"] == ("prog", "fertig", None) and steps == [(1, 3), (3, 3)]
    assert not bg._timer.isActive()                                  # nichts mehr zu tun: der Timer ruht


def test_results_for_a_deleted_owner_are_dropped_quietly(qapp):
    gate, called = threading.Event(), []
    owner = QObject()
    BackgroundRunner(owner).run(lambda: gate.wait(5), lambda v, e: called.append(v))
    del owner
    gc.collect()
    gate.set()
    time.sleep(0.1)
    qapp.processEvents()
    assert called == []


# --- Dialog schließen, während der Thread noch arbeitet -----------------------------------------------

def _drop_while_running(qapp, make, start, strict=True):
    """Der Dialog wird freigegeben, während sein Thread noch blockiert: er muss SOFORT im GUI-Thread zerstört werden
    (nicht erst, wenn der Thread fertig ist und dabei die letzte Referenz loslässt). `strict=False` für Dialoge, die sich
    selbst über eine Qt-Verbindung am Leben halten: dort wird nur geprüft, dass nichts im Hintergrund-Thread zerstört wird."""
    gate = threading.Event()
    dlg = make(gate)
    destroyed = []
    dlg.destroyed.connect(lambda *_: destroyed.append(threading.current_thread() is threading.main_thread()))
    start(dlg)
    time.sleep(0.05)                                                 # der Thread läuft und wartet am Tor
    qapp.processEvents()                                             # z. B. QTimer.singleShot beim Öffnen erledigen
    dlg.close()
    del dlg
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if strict:
        assert destroyed == [True], "Dialog lebt weiter, weil der Hintergrund-Thread ihn festhält"
    gate.set()                                                       # Thread darf jetzt weiterlaufen und enden
    time.sleep(0.1)
    for _ in range(5):
        qapp.processEvents()
    gc.collect()
    assert all(destroyed), "Der Dialog wurde im Hintergrund-Thread zerstört"


def test_about_dialog_closed_during_update_check(qapp):
    def fetch_blocking(gate):
        return lambda: (gate.wait(5), (_ for _ in ()).throw(RuntimeError("offline")))[1]
    _drop_while_running(qapp, lambda gate: AboutDialog(fetch=fetch_blocking(gate)), lambda d: d._check(),
                        strict=False)


def test_outlook_dialog_closed_while_outlook_is_read(qapp):
    svc = TimeService(Database(":memory:"), Clock(8, 0))

    def make(gate):
        return OutlookImportDialog(svc, date(2026, 11, 2), reader=lambda a, b: (gate.wait(5), [])[1])
    _drop_while_running(qapp, make, lambda d: d._load(), strict=False)


def test_excel_dialog_closed_while_excel_is_busy(qapp):
    svc = excel_setup()

    def make(gate):
        def factory(path, save=True):
            gate.wait(5)
            raise ExcelError("Excel antwortet nicht")
        return ExcelExportDialog(svc, workbook_factory=factory)
    _drop_while_running(qapp, make, lambda d: d._preview())


def test_open_dialog_still_gets_its_result_with_the_helper(qapp):
    """Gegenprobe: bleibt der Dialog offen, kommt das Ergebnis an (hier: Fehlertext des Updates)."""
    def failing_fetch():
        raise RuntimeError("offline")
    dlg = AboutDialog(fetch=failing_fetch)
    dlg._check()
    assert pump(qapp, lambda: "Unerwarteter Fehler: offline" in dlg.status.text())
    assert dlg.check_btn.isEnabled()
