"""Einstiegspunkt."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ._version import __version__
from .db import Database, default_db_path
from .service import TimeService
from . import autostart, single_instance
from .ui.main_window import MainWindow

SAMPLE_PROJECTS = [("Projekt A", "#4f8cff"), ("Projekt B", "#2ea36b"), ("Intern", "#e8a33d"),
                   ("Support", "#c05cc0"), ("Meeting", "#d9534f")]
SAMPLE_ACTIVITIES = ["Programmierung", "Test", "Dokumentation", "Besprechung", "Fehlersuche"]


def seed(db: Database) -> None:
    """Beispiel-Stammdaten (nur für Tests und Vorführungen). Die App ruft das NICHT auf: Nach einer
    Neuinstallation ist die Datenbank leer, Projekte und Tätigkeiten legt man unter „Stammdaten“ an."""
    if db.list_projects(include_archived=True):
        return
    for name, color in SAMPLE_PROJECTS:
        db.add_project(name, color)
    for name in SAMPLE_ACTIVITIES:
        db.add_activity(name)


def open_database(db_path=None) -> Database:
    r"""Öffnet die Datenbank. Beim ersten Start ist sie leer (keine Beispieldaten); ein Update des Programms
    lässt die vorhandene Datenbank unberührt (sie liegt in %APPDATA%\WorkPlanner, nicht im Programmordner)."""
    return Database(db_path or default_db_path())


def isolated_mode() -> bool:
    """WORKPLANNER_ISOLATED=1: Testlauf ohne Einbindung in Windows – keine Tastenkombination, kein Tray, keine
    „nur eine Instanz“-Sperre, kein automatisches Laden aus DevOps. So stört er die echte Installation nicht."""
    return os.environ.get("WORKPLANNER_ISOLATED", "") not in ("", "0")


def main(db_path=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    isolated = isolated_mode()
    if not isolated and single_instance.notify_running_instance():  # läuft schon (z. B. im Tray): dessen Fenster zeigen
        return 0
    app.setQuitOnLastWindowClosed(isolated)  # sonst im Tray weiterlaufen; echtes Beenden regelt das Fenster
    db = open_database(db_path)
    window = MainWindow(TimeService(db), enable_hotkey=not isolated, enable_tray=not isolated,
                        auto_features=not isolated, enable_calls=True, enable_outlook=True)
    window.setWindowTitle(f"WorkPlanner v{__version__}  –  TESTLAUF (eigene Daten)" if isolated
                           else f"WorkPlanner v{__version__}")
    server = None if isolated else single_instance.InstanceServer(window.show_window)  # lauscht bis zum Ende
    if not (autostart.TRAY_FLAG in sys.argv and window.tray is not None):
        window.show()
    QTimer.singleShot(400, window.offer_demo)  # nur beim allerersten Start mit leerer Datenbank
    QTimer.singleShot(600, window.show_db_warning)  # Hinweis, wenn die Datenbank zu groß geworden ist
    code = app.exec()
    del server
    return code
