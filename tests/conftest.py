"""Gemeinsames Aufräumen für alle Oberflächen-Tests.

Viele Tests erzeugen Fenster (MainWindow, Dialoge) mit Timern und Hintergrund-Threads. Bleiben sie bis zum Ende
des Python-Prozesses liegen, werden sie erst im Interpreter-Abbau zerstört, wenn die QApplication schon weg ist.
Das stürzt beim Beenden ab (Exit-Code 0xC0000409), obwohl alle Tests bestanden haben. Deshalb wird hier am Ende
der Sitzung geordnet aufgeräumt: erst Fenster schließen und löschen, dann Threads und Python-Objekte freigeben.
"""
import gc
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _qt_cleanup_at_end():
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    # Hintergrund-Threads der Tests (Fake-Clients usw.) kurz zu Ende laufen lassen
    deadline = time.time() + 3
    while time.time() < deadline and any(t.is_alive() and t.daemon and t is not threading.current_thread()
                                         for t in threading.enumerate()):
        app.processEvents()
        time.sleep(0.02)
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def _no_blocking_overlap_question(monkeypatch):
    """Die Rückfrage „Dauer beibehalten / Kürzen“ würde im Test blockieren: Standard ist „beibehalten“."""
    try:
        from workplanner.ui import dialogs
    except ImportError:
        return
    monkeypatch.setattr(dialogs, "ask_overlap", lambda parent, svc, entry_id, changes: "push")
