"""Termine aus dem klassischen Outlook auswählen und als Zeiteinträge übernehmen."""
from __future__ import annotations

import threading
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..outlook import Appointment, OutlookError, read_appointments
from ..service import TimeService
from ..timeline import TimelineError, changed_times, removed_entries
from .dialogs import fmt_duration, fmt_time

PREFERRED_PROJECTS = ("meeting", "besprechung", "termine")
PREFERRED_ACTIVITIES = ("besprechung", "meeting")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class OutlookImportDialog(QDialog):
    _loaded = Signal(object, object)  # (Termine | None, Fehlertext | None)

    def __init__(self, service: TimeService, day: date, parent=None, reader=read_appointments):
        super().__init__(parent)
        self.svc, self._reader = service, reader
        self._raw: list[Appointment] = []   # alles, was Outlook geliefert hat
        self._appts: list[Appointment] = []  # davon angezeigt (ohne ganztägige, falls ausgeblendet)
        self._eligible: list[bool] = []
        self._auto_loaded = False
        self.setWindowTitle("Termine aus Outlook importieren")
        self.resize(940, 560)

        self.first, self.last = QDateEdit(_qdate(day)), QDateEdit(_qdate(day))
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd.MM.yyyy")
        self.all_day = QCheckBox("Ganztägige Termine anzeigen")
        self.load_btn = QPushButton("Neu laden")
        self.load_btn.setToolTip("Termine erneut aus Outlook lesen")
        self.load_btn.clicked.connect(self._load)
        top = QHBoxLayout()
        for w in (QLabel("Von"), self.first, QLabel("bis"), self.last, self.all_day, self.load_btn):
            top.addWidget(w)
        top.addStretch(1)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Datum", "Zeit", "Dauer", "Betreff", "Ort", "Hinweis"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.itemChanged.connect(lambda _: self._update())

        self.project = QComboBox()
        for p in service.projects():
            self.project.addItem(service.project_display(p["id"]), p["id"])
        self.activity = QComboBox()
        self.project.currentIndexChanged.connect(lambda _: (self._fill_activities(), self._update()))
        self.activity.currentIndexChanged.connect(lambda _: self._update())
        self._preselect()
        form = QFormLayout()
        form.addRow("Buchen auf Projekt", self.project)
        form.addRow("Tätigkeit", self.activity)

        self.all_btn = QPushButton("Alle wählen")
        self.none_btn = QPushButton("Keine")
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        sel = QHBoxLayout()
        sel.addWidget(self.all_btn)
        sel.addWidget(self.none_btn)
        sel.addStretch(1)

        self.status = QLabel("Termine werden aus Outlook geladen …")
        self.status.setWordWrap(True)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("Importieren")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self._import)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.status)
        lay.addLayout(sel)
        lay.addWidget(self.table, 1)
        lay.addLayout(form)
        lay.addWidget(self.preview)
        lay.addWidget(self.buttons)
        self._loaded.connect(self._on_loaded)
        # Beim Öffnen und bei geändertem Zeitraum automatisch laden (kurz gebündelt, Outlook ist träge)
        self._reload_timer = QTimer(self, singleShot=True, interval=400)
        self._reload_timer.timeout.connect(self._load)
        self.first.dateChanged.connect(lambda _: self._reload_timer.start())
        self.last.dateChanged.connect(lambda _: self._reload_timer.start())
        self.all_day.toggled.connect(lambda _: self._populate())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._auto_loaded:
            self._auto_loaded = True
            QTimer.singleShot(0, self._load)

    # --- Projekt/Tätigkeit vorbelegen ------------------------------------------------------
    def _preselect(self) -> None:
        idx = next((i for i in range(self.project.count())
                    if self.svc.project_name(self.project.itemData(i)).casefold() in PREFERRED_PROJECTS), -1)
        if idx < 0:
            idx = max(0, self.project.findData(self.svc.default_project_id(create=False)))
        self.project.blockSignals(True)
        self.project.setCurrentIndex(idx)
        self.project.blockSignals(False)
        self._fill_activities()

    def _fill_activities(self) -> None:
        self.activity.blockSignals(True)
        self.activity.clear()
        self.activity.addItem("–", None)
        for a in self.svc.activities_for(self.project.currentData()):
            self.activity.addItem(a["name"], a["id"])
        idx = next((i for i in range(1, self.activity.count())
                    if self.activity.itemText(i).casefold() in PREFERRED_ACTIVITIES), 0)
        self.activity.setCurrentIndex(idx)
        self.activity.blockSignals(False)

    # --- Laden --------------------------------------------------------------------------
    def _load(self) -> None:
        first, last = self.first.date().toPython(), self.last.date().toPython()
        if last < first:
            self.status.setText("<span style='color:#c0392b'>⚠ „bis“ liegt vor „Von“.</span>")
            return
        self.load_btn.setEnabled(False)
        self.status.setText("Outlook wird gelesen … (Outlook muss dafür laufen bzw. starten)")

        def work():
            try:
                result, error = self._reader(first, last), None
            except OutlookError as ex:
                result, error = None, str(ex)
            except Exception as ex:  # noqa: BLE001
                result, error = None, f"Unerwarteter Fehler: {ex}"
            try:
                self._loaded.emit(result, error)
            except RuntimeError:  # Dialog wurde inzwischen geschlossen
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, appts, error) -> None:
        self.load_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        self._raw = appts
        self._populate()

    def _populate(self) -> None:
        self._appts = [a for a in self._raw if self.all_day.isChecked() or not a.all_day]
        imported, now = self.svc.outlook_imported(), self.svc.now()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._appts))
        self._eligible = []
        for r, a in enumerate(self._appts):
            ongoing = a.start <= now < a.end
            note = ("bereits importiert" if a.key in imported else
                    "abgesagt" if a.declined else
                    "noch nicht begonnen" if a.start > now else
                    "läuft gerade – danach geht die Aufgabe weiter" if ongoing else
                    "ganztägig" if a.all_day else
                    "als „Frei“ markiert" if a.free else "")
            eligible = (a.end <= now or ongoing) and not a.declined and a.key not in imported
            self._eligible.append(eligible)
            check = QTableWidgetItem()
            flags = Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if eligible else Qt.NoItemFlags
            check.setFlags(flags)
            check.setCheckState(Qt.Checked if eligible and not a.free and not a.all_day and not ongoing
                                else Qt.Unchecked)  # laufende Termine greifen ein: nur auf Wunsch
            self.table.setItem(r, 0, check)
            vals = [f"{a.start:%d.%m.%Y}", f"{fmt_time(a.start)}–{fmt_time(a.end)}",
                    fmt_duration(a.end - a.start), a.subject, a.location, note]
            for c, v in enumerate(vals, 1):
                it = QTableWidgetItem(v)
                if not eligible:
                    it.setForeground(Qt.gray)
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        ready = sum(self._eligible)
        self.status.setText(f"{len(self._appts)} Termine gefunden, {ready} davon importierbar.")
        self._update()

    def _set_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for r, ok in enumerate(self._eligible):
            if ok:
                self.table.item(r, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update()

    # --- Vorschau und Import --------------------------------------------------------------
    def selected(self) -> list[Appointment]:
        return [a for r, a in enumerate(self._appts)
                if self._eligible[r] and self.table.item(r, 0).checkState() == Qt.Checked]

    def _update(self) -> None:
        items = self.selected()
        self.ok.setEnabled(False)
        self.ok.setText("Importieren")
        if not items:
            self.preview.setText("")
            return
        try:
            plan = self.svc.preview_import(items, self.project.currentData(), self.activity.currentData())
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return
        trimmed, gone = [], []
        for old, new in plan.values():
            trimmed += [f"{self.svc.entry_label(o)} {fmt_time(o.start)}–{fmt_time(o.end)} → "
                        f"{fmt_time(n.start)}–{fmt_time(n.end)}" for o, n in changed_times(old, new)]
            gone += [f"{self.svc.entry_label(o)} {fmt_time(o.start)}–{fmt_time(o.end)}"
                     for o in removed_entries(old, new)]
        html = f"<b>{len(items)} Termin(e)</b> werden als Zeiteinträge angelegt."
        if trimmed:
            html += f"<br>Bestehende Einträge werden gekürzt: {len(trimmed)}<br>" + "<br>".join(trimmed[:6])
            html += "<br>…" if len(trimmed) > 6 else ""
        if gone:
            html += (f"<br><span style='color:#b35c00'><b>Entfällt (vollständig überdeckt): {len(gone)}</b><br>"
                     + "<br>".join(gone[:6]) + ("<br>…" if len(gone) > 6 else "") + "</span>")
        now, current = self.svc.now(), self.svc.current()
        for a in (a for a in items if a.end > now):
            task = (self.svc.project_display(current.project_id) or "Die laufende Aufgabe") \
                if current and current.kind != "pause" else None
            html += (f"<br><b>„{a.subject}“ läuft gerade:</b> "
                     + (f"{task} wird unterbrochen und läuft nach dem Terminende ({fmt_time(a.end)}) "
                        "automatisch weiter." if task else f"er läuft bis {fmt_time(a.end)} mit."))
        self.preview.setText(html)
        self.ok.setText(f"{len(items)} Termin(e) importieren")
        self.ok.setEnabled(True)

    def _import(self) -> None:
        items = self.selected()
        try:
            self.svc.apply_import(items, self.project.currentData(), self.activity.currentData())
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return
        self.accept()
