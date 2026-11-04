"""Nach einem Teams-Anruf: Soll er als Zeiteintrag übernommen werden? Mit Notiz."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QTimeEdit,
                               QVBoxLayout)

from ..call_monitor import Call
from ..service import TimeService
from ..timeline import TimelineError
from .dialogs import NoteEdit, fmt_duration


class CallDialog(QDialog):
    def __init__(self, service: TimeService, call: Call, parent=None):
        super().__init__(parent)
        self.svc, self.call = service, call
        self.setWindowTitle("Teams-Anruf beendet")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # erscheint auch, wenn das Fenster im Tray ist

        self.info = QLabel(f"Ein Teams-Anruf von <b>{call.start:%H:%M}</b> bis <b>{call.end:%H:%M}</b> "
                           f"({fmt_duration(call.duration)} h) wurde erkannt.<br>Als Zeiteintrag übernehmen?")
        self.start, self.end = QTimeEdit(), QTimeEdit()
        start = call.start.replace(second=0, microsecond=0)
        end = max(call.end.replace(second=0, microsecond=0), start + timedelta(minutes=1))  # mindestens 1 Minute
        for w, dt in ((self.start, start), (self.end, end)):
            w.setDisplayFormat("HH:mm")
            w.setTime(QTime(dt.hour, dt.minute))
        times = QHBoxLayout()
        times.addWidget(self.start)
        times.addWidget(QLabel("bis"))
        times.addWidget(self.end)
        times.addStretch(1)

        self.project = QComboBox()
        self.project.addItem("–", None)
        for p in service.projects():
            self.project.addItem(p["name"], p["id"])
        self.activity = QComboBox()
        self.note = NoteEdit("", "Notiz zum Anruf (z. B. Thema, Teilnehmer)")
        pid, _ = service.call_defaults()
        self.project.setCurrentIndex(max(0, self.project.findData(pid)))
        self.project.currentIndexChanged.connect(lambda _=0: self._fill_activities())
        self._fill_activities()
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#c0392b")

        form = QFormLayout()
        form.addRow("Zeit", times)
        form.addRow("Projekt", self.project)
        form.addRow("Tätigkeit", self.activity)
        form.addRow("Notiz", self.note)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Eintragen", QDialogButtonBox.AcceptRole)
        self.skip = self.buttons.addButton("Nicht eintragen", QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(self.buttons)
        self.note.setFocus()

    def _fill_activities(self) -> None:
        """Die Tätigkeit ist immer „Telefonat“ (änderbar)."""
        selected = self.svc.call_activity_id(self.project.currentData())
        self.activity.clear()
        self.activity.addItem("–", None)
        for a in self.svc.activities_for(self.project.currentData()):
            self.activity.addItem(a["name"], a["id"])
        self.activity.setCurrentIndex(max(0, self.activity.findData(selected)))

    def _accept(self) -> None:
        day = self.call.start.date()
        start = datetime.combine(day, time(self.start.time().hour(), self.start.time().minute()))
        end = datetime.combine(day, time(self.end.time().hour(), self.end.time().minute()))
        if end <= start:  # mindestens eine Minute
            end = start + timedelta(minutes=1)
        pid, aid = self.project.currentData(), self.activity.currentData()
        try:
            self.svc.add_booking(start, end, self.note.toPlainText().strip(), pid, aid)
        except TimelineError as ex:
            self.error.setText(f"⚠ {ex}")
            return
        self.svc.remember_call_choice(pid)
        self.accept()


class CallBanner(QLabel):
    """Kleines Hinweisfenster unten rechts: „Anruf läuft“, solange Teams das Mikrofon offen hat (stiehlt keinen Fokus)."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("background:#c0392b;color:white;font-weight:600;padding:10px 16px;"
                           "border:1px solid #7b241c;border-radius:6px")

    def show_call(self, since: datetime, now: datetime) -> None:
        self.setText(f"●  Teams-Anruf läuft seit {since:%H:%M}  ({fmt_duration(now - since)} h)")
        self.adjustSize()
        area = self.screen().availableGeometry()
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)
        self.show()
