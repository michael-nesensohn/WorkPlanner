"""Hintergrundarbeit für Dialoge, ohne dass ein Thread je ein Qt-Objekt anfasst.

Warum so: Qt-Fenster dürfen nur im GUI-Thread zerstört werden. Hält ein Hintergrund-Thread über seine Funktion oder über
ein Signal eine Referenz auf den Dialog, kann er die letzte Referenz freigeben, wenn der Dialog währenddessen geschlossen
wurde, und zerstört das Fenster im falschen Thread (zufällige Abstürze). Hier kennt der Thread nur eine Warteschlange.
Ein Timer im GUI-Thread holt die Ergebnisse ab und ruft die Rückruffunktionen dort auf.

Regel für `job`: keine Verweise auf den Dialog (`self`) oder andere Qt-Objekte – alles Nötige vorher in lokale Variablen.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer


class BackgroundRunner(QObject):
    """Gehört dem Dialog (`parent`) und wird mit ihm zusammen zerstört; danach ankommende Ergebnisse verfallen."""

    def __init__(self, parent: QObject, interval_ms: int = 30):
        super().__init__(parent)
        self._queue: "queue.SimpleQueue[tuple[int, str, tuple]]" = queue.SimpleQueue()
        self._jobs: dict[int, tuple[Callable, Callable | None]] = {}
        self._next = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    @property
    def busy(self) -> bool:
        return bool(self._jobs)

    def run(self, job: Callable[..., Any], on_done: Callable[[Any, str | None], None], *,
            on_progress: Callable[..., None] | None = None, expected: tuple[type[BaseException], ...] = ()) -> None:
        """Führt `job` in einem Thread aus und ruft danach im GUI-Thread `on_done(wert, fehlertext)` auf.

        * `expected`: erwartete Fehler; ihr Text kommt unverändert als Fehlertext. Alles andere wird als
          „Unerwarteter Fehler: …“ gemeldet, der Thread stirbt also nie still.
        * `on_progress`: dann bekommt `job` eine Funktion `report(*args)` übergeben; ihre Argumente erreichen
          `on_progress(*args)` im GUI-Thread.
        """
        jid, self._next = self._next, self._next + 1
        self._jobs[jid] = (on_done, on_progress)
        q = self._queue   # der Thread bekommt nur die Warteschlange, nie den Dialog

        def work():
            try:
                value = job(lambda *args: q.put((jid, "progress", args))) if on_progress else job()
                q.put((jid, "done", (value, None)))
            except expected as ex:
                q.put((jid, "done", (None, str(ex))))
            except Exception as ex:  # noqa: BLE001
                q.put((jid, "done", (None, f"Unerwarteter Fehler: {ex}")))
        self._timer.start()
        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        while True:
            try:
                jid, kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            handlers = self._jobs.get(jid)
            if handlers is None:
                continue
            if kind == "progress":
                if handlers[1]:
                    handlers[1](*payload)
            else:
                del self._jobs[jid]
                handlers[0](*payload)
        if not self._jobs:
            self._timer.stop()
