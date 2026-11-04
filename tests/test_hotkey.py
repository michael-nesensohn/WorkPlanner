import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from test_service import Clock
from workplanner.app import seed
from workplanner.db import Database
from workplanner.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_hotkey
from workplanner.service import TimeService
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_parse_hotkey():
    assert parse_hotkey("Ctrl+Alt+W") == (MOD_CONTROL | MOD_ALT, 0x57)
    assert parse_hotkey("Ctrl+Shift+F9") == (MOD_CONTROL | MOD_SHIFT, 0x78)
    assert parse_hotkey("Alt+F1") == (MOD_ALT, 0x70) and parse_hotkey("Alt+F12") == (MOD_ALT, 0x7B)
    assert parse_hotkey("Meta+5") == (MOD_WIN, 0x35)
    assert parse_hotkey("Ctrl+Space") == (MOD_CONTROL, 0x20)


@pytest.mark.parametrize("text", ["", "W", "F9", "Shift", "Ctrl+Ä", "Ctrl+Return", "Ctrl+Tab"])
def test_parse_hotkey_rejects_unusable(text):
    assert parse_hotkey(text) is None


def test_default_hotkey_is_stored():
    svc = TimeService(Database(), Clock())
    assert svc.hotkey == "Ctrl+Alt+W"
    svc.set_hotkey("Ctrl+Alt+Z")
    assert svc.hotkey == "Ctrl+Alt+Z"


def test_toggle_minimizes_when_active_and_restores_otherwise(qapp):
    db = Database()
    seed(db)
    w = MainWindow(TimeService(db, Clock(9)))
    w.show()
    w.isActiveWindow = lambda: True
    w.toggle_window()
    assert w.isMinimized()
    w.isActiveWindow = lambda: False
    w.toggle_window()
    assert w.isVisible() and not w.isMinimized()


def test_settings_page_saves_hotkey_only_when_registration_works(qapp):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    page = MainWindow(svc).master
    page.hotkey_apply = lambda text: "Diese Kombination wird schon von einem anderen Programm benutzt."
    page._set_hotkey("Ctrl+Alt+Q")
    assert svc.hotkey == "Ctrl+Alt+W" and "schon von einem anderen" in page.hotkey_status.text()
    assert page.hotkey_edit.keySequence().toString() == "Ctrl+Alt+W"        # Anzeige zurückgesetzt
    page.hotkey_apply = lambda text: ""
    page._set_hotkey("Ctrl+Alt+Q")
    assert svc.hotkey == "Ctrl+Alt+Q" and "Aktiv" in page.hotkey_status.text()
    page._set_hotkey("")
    assert svc.hotkey == "" and "Aus" in page.hotkey_status.text()


def test_app_start_registers_hotkey_with_windows_and_releases_it_on_close(qapp):
    import sys
    if sys.platform != "win32":
        pytest.skip("nur unter Windows")
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(9))
    svc.set_hotkey("Ctrl+Alt+Shift+F12")           # bewusst ungewöhnlich, stört keine echte Nutzung
    w = MainWindow(svc, enable_hotkey=True)
    assert w.hotkey._id is not None and "Aktiv" in w.master.hotkey_status.text()
    other = MainWindow(svc, enable_hotkey=True)    # zweite Instanz: Kombination ist belegt
    assert other.hotkey._id is None and "schon von einem anderen" in other.master.hotkey_status.text()
    assert w.master._set_hotkey is not None
    w.close()
    assert w.hotkey._id is None                    # freigegeben
    third = MainWindow(svc, enable_hotkey=True)
    assert third.hotkey._id is not None
    third.close()
    other.close()
