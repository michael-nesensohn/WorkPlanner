import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from test_service import Clock
from workplanner import autostart, single_instance
from workplanner.app import seed
from workplanner.db import Database
from workplanner.icon import app_icon, make_pixmap
from workplanner.service import TimeService
from workplanner.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)  # wie in der echten App; sonst gilt Qt nach dem letzten close() als beendet
    return app


def make_window(clock_hm=(9, 0)):
    db = Database()
    seed(db)
    svc = TimeService(db, Clock(*clock_hm))
    return MainWindow(svc), svc


class FakeTray:
    def __init__(self):
        self.hinted, self.hidden, self.tooltip = 0, False, ""
        self.icon = SimpleNamespace(hide=lambda: setattr(self, "hidden", True))

    def hint_once(self):
        self.hinted += 1

    def set_tooltip(self, text):
        self.tooltip = text


# --- Autostart (echte Registry, eigener Testname) ---------------------------------------

def test_autostart_command_uses_pythonw_and_absolute_main_py():
    cmd = autostart.command(tray=True)
    assert cmd.endswith(" --tray") and "main.py" in cmd
    assert cmd.split('"')[1].lower().endswith(("pythonw.exe", "python.exe"))
    assert not autostart.command(tray=False).endswith("--tray")
    assert os.path.exists(cmd.split('"')[3])        # Pfad zu src/main.py stimmt


@pytest.mark.skipif(sys.platform != "win32", reason="nur Windows")
def test_autostart_enable_disable_roundtrip():
    name = "WorkPlannerAutostartTest"
    try:
        assert not autostart.is_enabled(name)
        autostart.enable(True, name)
        assert autostart.is_enabled(name)
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
            assert winreg.QueryValueEx(key, name)[0] == autostart.command(True)
        autostart.disable(name)
        assert not autostart.is_enabled(name)
        autostart.disable(name)                      # zweites Mal: kein Fehler
    finally:
        autostart.disable(name)


# --- Einstellungen ---------------------------------------------------------------------

def test_settings_page_autostart_checkboxes(qapp):
    w, svc = make_window()
    calls = []
    fake = SimpleNamespace(is_enabled=lambda: bool(calls and calls[-1][0] == "on"),
                           enable=lambda tray: calls.append(("on", tray)),
                           disable=lambda: calls.append(("off",)))
    page = w.master
    page.autostart = fake
    page.reload()
    assert not page.autostart_cb.isChecked() and not page.start_tray_cb.isEnabled()
    page.autostart_cb.click()
    assert calls[-1] == ("on", True) and page.start_tray_cb.isEnabled()      # Standard: im Tray starten
    page.start_tray_cb.click()                                               # Häkchen weg
    assert svc.start_in_tray is False and calls[-1] == ("on", False)         # Eintrag neu geschrieben
    page.autostart_cb.click()
    assert calls[-1] == ("off",) and not page.start_tray_cb.isEnabled()
    assert svc.tray_mode is True
    page.tray_cb.click()
    assert svc.tray_mode is False


def test_autostart_error_is_shown_and_checkbox_reset(qapp):
    w, svc = make_window()

    def boom(tray):
        raise PermissionError("Zugriff verweigert")
    page = w.master
    page.autostart = SimpleNamespace(is_enabled=lambda: False, enable=boom, disable=lambda: None)
    page.reload()                                    # liest den (Fake-)Stand: aus, unabhängig von der echten Registry
    assert not page.autostart_cb.isChecked()
    page.autostart_cb.click()
    assert not page.autostart_cb.isChecked() and "Zugriff verweigert" in page.autostart_status.text()


# --- Tray-Verhalten ---------------------------------------------------------------------

def test_close_and_minimize_go_to_tray_when_enabled(qapp):
    w, svc = make_window()
    w.tray = FakeTray()
    w.show()
    w.close()                                        # Schließen-Knopf
    assert not w.isVisible() and w.tray.hinted == 1 and not w.tray.hidden
    w.show_window()
    assert w.isVisible()
    w.isActiveWindow = lambda: True
    w.toggle_window()                                # Tastenkombination: ins Tray statt Taskleiste
    assert not w.isVisible() and not w.isMinimized()
    w.show_window()
    w.close()
    assert w.tray.hinted == 2                        # jedes Verstecken ruft hint_once; das „nur einmal“ steckt im TrayIcon


def test_quit_really_closes_and_removes_tray_icon(qapp):
    w, svc = make_window()
    w.tray = FakeTray()
    w.show()
    w.quit_app()
    assert not w.isVisible() and w.tray.hidden


def test_tray_mode_off_closes_normally(qapp):
    w, svc = make_window()
    w.tray = FakeTray()
    svc.set_tray_mode(False)
    w.show()
    w.close()
    assert w.tray.hidden and w.tray.hinted == 0


def test_tray_status_start_stop_and_tooltip(qapp):
    w, svc = make_window()
    w.tray = FakeTray()
    assert w.tray_status() == ("Keine Aufgabe läuft", False)
    w.tray_toggle_task()                              # Start (Standardprojekt)
    text, running = w.tray_status()
    assert running and text.startswith("Allgemein – ")
    assert w.tray.tooltip.startswith("WorkPlanner – Allgemein")
    w.tray_toggle_task()                              # Stopp
    assert svc.current() is None and w.tray_status()[1] is False
    assert w.tray.tooltip == "WorkPlanner – keine Aufgabe läuft"


# --- Eine Instanz ---------------------------------------------------------------------

def test_second_start_wakes_first_instance(qapp):
    """Wie im Alltag: die zweite Instanz ist ein eigener Prozess und meldet sich bei der ersten."""
    import subprocess
    import time
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src"
    name = "WorkPlanner-test-instance"
    assert not single_instance.notify_running_instance(name)         # noch niemand da
    hits = []
    server = single_instance.InstanceServer(lambda: hits.append(1), name)
    assert server.listening
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from PySide6.QtWidgets import QApplication;"
            "app = QApplication([]); from workplanner import single_instance as si;"
            "sys.exit(0 if si.notify_running_instance(sys.argv[2]) else 1)")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.Popen([sys.executable, "-c", code, str(src), name], env=env)
    deadline = time.time() + 10
    while proc.poll() is None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert proc.poll() == 0 and hits == [1]          # zweite Instanz fand die erste und beendet sich
    server.close()


# --- Symbol ---------------------------------------------------------------------------

def test_icon_is_drawn_and_can_be_saved_as_ico(qapp, tmp_path):
    icon = app_icon()
    assert not icon.isNull() and 16 in [s.width() for s in icon.availableSizes()]
    pix = make_pixmap(64)
    assert not pix.isNull() and pix.toImage().pixelColor(32, 32).alpha() == 255   # Mitte gefüllt
    assert pix.toImage().pixelColor(0, 0).alpha() == 0                            # Ecke durchsichtig
    out = tmp_path / "i.ico"
    assert make_pixmap(256).save(str(out), "ICO") and out.stat().st_size > 100
