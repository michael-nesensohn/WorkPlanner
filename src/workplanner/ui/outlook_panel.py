"""Outlook-Termine des angezeigten Tages als Kacheln neben den DevOps-Features: ein Klick legt den Eintrag an."""
from __future__ import annotations

import threading
from datetime import date, datetime

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
                               QWidget)

from ..outlook import Appointment, OutlookError, read_appointments
from .dialogs import fmt_duration, fmt_time
from .tiles import ElidedLabel


class OutlookFeed(QObject):
    """Liest die Termine eines Tages im Hintergrund (Outlook/COM ist träge und darf die Oberfläche nicht blockieren)."""
    loaded = Signal(object, object)  # (Tag, Termine)
    failed = Signal(object, str)     # (Tag, Fehlertext)

    def __init__(self, parent=None, reader=read_appointments):
        super().__init__(parent)
        self._reader, self._busy, self._again = reader, False, None
        self.loaded.connect(self._idle)
        self.failed.connect(self._idle)

    def _idle(self, *_):
        self._busy = False
        if self._again is not None:  # während des Ladens wurde ein anderer Tag gewünscht
            day, self._again = self._again, None
            self.load(day)

    def load(self, day: date) -> None:
        if self._busy:
            self._again = day
            return
        self._busy = True

        def work():
            try:
                self.loaded.emit(day, self._reader(day, day))
            except OutlookError as ex:
                self.failed.emit(day, str(ex))
            except Exception as ex:  # noqa: BLE001 – den Thread nie still sterben lassen
                self.failed.emit(day, f"Unerwarteter Fehler: {ex}")
        threading.Thread(target=work, daemon=True).start()


class _Tile(QPushButton):
    """Zeile 1: Zeit und Dauer, Zeile 2: Betreff (gekürzt, voller Text im Tooltip)."""

    def __init__(self, appt: Appointment, state: str):
        super().__init__(objectName="tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 3, 8, 3)
        lay.setSpacing(0)
        when = QLabel(f"{fmt_time(appt.start)}–{fmt_time(appt.end)}  ·  {fmt_duration(appt.end - appt.start)} h"
                      + (f"   {state}" if state else ""))
        when.setStyleSheet("color:#7b8798;font-size:11px;font-weight:400;background:transparent")
        subject = ElidedLabel(appt.subject)
        subject.setStyleSheet("font-weight:600;background:transparent")
        for w in (when, subject):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)

    def sizeHint(self) -> QSize:  # zwei Zeilen hoch (das Stylesheet der Kacheln kennt nur einzeiligen Text)
        return QSize(super().sizeHint().width(), 46)

    def minimumSizeHint(self) -> QSize:
        return QSize(10, 46)


class OutlookPanel(QWidget):
    appointment_chosen = Signal(object)  # Appointment
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self._signature = None
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Outlook</b>"), 1)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Termine jetzt neu aus Outlook lesen")
        refresh.clicked.connect(self.refresh_requested)
        head.addWidget(refresh)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#667;font-size:11px")
        self.tiles = QVBoxLayout()
        self.tiles.setSpacing(4)
        holder = QWidget()
        holder.setLayout(self.tiles)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(head)
        lay.addWidget(self.status)
        lay.addWidget(scroll, 1)
        self.setMinimumWidth(180)
        self.set_status("Outlook ist nicht aktiv.")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _clear(self) -> None:
        self._signature = None
        while self.tiles.count():
            it = self.tiles.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()

    def show_loading(self) -> None:
        self._clear()
        self.set_status("Termine werden aus Outlook gelesen …")

    def show_error(self, text: str) -> None:
        self._clear()
        self.set_status(f"<span style='color:#c0392b'>⚠ {text}</span>")

    def set_items(self, appts: list[Appointment], imported: set[str], now: datetime) -> None:
        """Zeichnet die Kacheln neu – aber nur, wenn sich etwas geändert hat (Minute, Termine, Übernommenes)."""
        shown = sorted((a for a in appts if not a.all_day and not a.declined), key=lambda a: (a.start, a.end))
        signature = (tuple(a.key for a in shown), frozenset(imported), now.replace(second=0, microsecond=0))
        if signature == self._signature:
            return
        self._clear()
        self._signature = signature
        for a in shown:
            if a.key in imported:
                state, enabled, tip = "✓ eingetragen", False, "Bereits als Zeiteintrag übernommen"
            elif a.start > now:
                state, enabled, tip = "noch nicht begonnen", False, "Liegt noch in der Zukunft"
            elif a.end > now:
                state, enabled, tip = "läuft", True, "Klick: Eintrag anlegen – die laufende Aufgabe wird unterbrochen"
            else:
                state, enabled, tip = "", True, "Klick: als Zeiteintrag übernehmen"
            b = _Tile(a, state)
            b.setEnabled(enabled)
            b.setToolTip(f"{a.subject}\n{a.location}\n{tip}".replace("\n\n", "\n").strip())
            b.clicked.connect(lambda _=False, appt=a: self.appointment_chosen.emit(appt))
            self.tiles.addWidget(b)
        self.tiles.addStretch(1)
        self.set_status(f"{len(shown)} Termin(e)" if shown else "Keine Termine an diesem Tag.")
