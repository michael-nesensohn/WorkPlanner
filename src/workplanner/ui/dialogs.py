"""Dialog zum Bearbeiten und Anlegen von Einträgen, mit Vorschau der Verschiebung."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDate, Qt, QTime, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QCalendarWidget, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QRadioButton, QTimeEdit, QVBoxLayout)

from ..service import TimeService
from .feature_panel import group_items
from ..timeline import PAUSE, PUSH, SHORTEN, TimelineError, Entry, changed_times, removed_entries


def preview_html(svc: TimeService, old: list[Entry], new: list[Entry], own_id: int | None) -> str:
    """Vorschau: welche anderen Einträge sich verschieben bzw. entfallen."""
    def span(e: Entry) -> str:
        return f"{svc.entry_label(e)} {fmt_time(e.start)}–{fmt_time(e.end)}"

    html = ""
    moved = [f"{span(o)} → {fmt_time(n.start)}–{fmt_time(n.end)}"
             for o, n in changed_times(old, new) if o.id != own_id]
    if moved:
        html += "<b>Andere Einträge werden angepasst:</b><br>" + "<br>".join(moved)
    gone = [span(o) for o in removed_entries(old, new) if o.id != own_id]
    if gone:
        html += ("<br>" if html else "") + ("<span style='color:#b35c00'><b>Entfällt (vollständig überdeckt):"
                                            "</b><br>" + "<br>".join(gone) + "</span>")
    return html


NO_LINK = "– keine Verknüpfung –"


def ask_lunch_pause(parent, minutes: int, start: str) -> str:
    """Mittagszeit: „start“ (Pause jetzt eintragen), „later“ (in zehn Minuten wieder fragen), „skip“ (heute keine
    Mittagspause) oder „deduct“ (nur abziehen, nicht fragen)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Mittagspause")
    box.setText(f"Es ist Mittagszeit ({start}).\nPause jetzt starten?")
    box.setInformativeText(f"Die laufende Aufgabe wird beendet, die Pause ({minutes} min) als Eintrag angelegt und die "
                           "Aufgabe danach automatisch fortgesetzt.")
    buttons = {}
    for key, text, role in (("start", "Pause starten", QMessageBox.AcceptRole),
                            ("later", "In 10 Minuten erinnern", QMessageBox.ActionRole),
                            ("deduct", f"Nur {minutes} min abziehen", QMessageBox.ActionRole),
                            ("skip", "Heute keine Pause", QMessageBox.DestructiveRole)):
        buttons[key] = box.addButton(text, role)
    box.exec()
    clicked = box.clickedButton()
    return next((k for k, b in buttons.items() if b is clicked), "later")


def ask_overlap(parent, svc: TimeService, entry_id: int, changes: dict) -> str | None:
    """Reicht der neue Start in andere Einträge hinein, fragt der Dialog, was mit ihnen geschehen soll.
    Gibt PUSH/SHORTEN zurück, `None` bei Abbruch. Es entfällt nie ein Eintrag."""
    covered = svc.overlapped_entries(entry_id, changes)
    if not covered:
        return PUSH
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Zeiten überschneiden sich")
    listing = "<br>".join(f"• {fmt_time(e.start)}–{fmt_time(e.end)}  {svc.entry_label(e)}" for e in covered)
    box.setTextFormat(Qt.RichText)
    box.setText("<b>Der frühere Start überdeckt diese Einträge:</b><br>" + listing +
                "<br><br>Was soll mit ihnen geschehen?")
    box.setInformativeText("Behalten: Sie behalten ihre Dauer und rücken zeitlich nach hinten. "
                           "(Bei einer laufenden Aufgabe: Sie stoppt vor ihnen und läuft danach weiter.)\n\n"
                           "Kürzen: Sie werden kürzer und enden dort, wo dieser Eintrag beginnt.")
    keep = box.addButton("Behalten", QMessageBox.AcceptRole)
    cut = box.addButton("Kürzen", QMessageBox.AcceptRole)
    box.addButton("Abbrechen", QMessageBox.RejectRole)
    box.exec()
    return PUSH if box.clickedButton() is keep else SHORTEN if box.clickedButton() is cut else None


class CalendarDialog(QDialog):
    """Datumsauswahl per Kalender; Doppelklick auf einen Tag übernimmt ihn."""

    def __init__(self, current: date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datum wählen")
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setFirstDayOfWeek(Qt.Monday)
        self.calendar.setSelectedDate(QDate(current.year, current.month, current.day))
        self.calendar.activated.connect(lambda _: self.accept())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.calendar)
        lay.addWidget(bb)

    def selected(self) -> date:
        return self.calendar.selectedDate().toPython()


class RunningTimeDialog(QDialog):
    """Start oder angefallene Zeit der laufenden Aufgabe ändern; beides hängt zusammen
    (Dauer = jetzt − Start). Der Vorgänger passt sich an, die Vorschau zeigt wie."""

    def __init__(self, service: TimeService, entry: Entry, parent=None):
        super().__init__(parent)
        self.svc, self.entry = service, entry
        self.now = service.now().replace(second=0, microsecond=0)
        day_entries = service.day_entries(entry.start.date())
        idx = next((i for i, e in enumerate(day_entries) if e.id == entry.id), 0)
        self._prev = day_entries[idx - 1] if idx > 0 else None
        self.setWindowTitle("Laufende Zeit anpassen")
        self.setMinimumWidth(420)
        self.start = QTimeEdit()
        self.elapsed = QTimeEdit()
        for w in (self.start, self.elapsed):
            w.setDisplayFormat("HH:mm")
        self.elapsed.setToolTip("Bisher angefallene Zeit (Stunden:Minuten)")
        self.info = QLabel(f"{service.entry_label(entry)} – jetzt ist es {self.now:%H:%M}")
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)
        self._sync = False
        self._set_from_start(_qtime(entry.start))

        form = QFormLayout()
        form.addRow("Start", self.start)
        form.addRow("Angefallene Zeit (h:mm)", self.elapsed)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addLayout(form)
        lay.addWidget(self.preview)
        lay.addWidget(self.buttons)
        self.start.timeChanged.connect(self._start_changed)
        self.elapsed.timeChanged.connect(self._elapsed_changed)
        self._update()

    def _snap(self, dt: datetime) -> datetime:
        """Zeiten sind sekundengenau, die Eingabe nur minutengenau. Damit ein unveränderter Start
        (z. B. 10:32:58) nicht auf 10:32:00 rutscht und den Vorgänger überlappt, bleibt er exakt;
        ein Start in der Minute, in der der Vorgänger endet, rastet auf dessen Ende ein."""
        if dt == self.entry.start.replace(second=0, microsecond=0):
            return self.entry.start
        prev_end = self._prev.end if self._prev else None
        if prev_end and dt < prev_end and dt == prev_end.replace(second=0, microsecond=0):
            return prev_end
        return dt

    def _new_start(self) -> datetime:
        t = self.start.time()
        return self._snap(datetime.combine(self.entry.start.date(), time(t.hour(), t.minute())))

    def _set_from_start(self, start: QTime) -> None:
        self._sync = True
        self.start.setTime(start)
        minutes = max(0, int((self.now - datetime.combine(self.now.date(), time(start.hour(), start.minute())))
                             .total_seconds() // 60))
        self.elapsed.setTime(QTime(min(minutes // 60, 23), minutes % 60))
        self._sync = False

    def _start_changed(self, t: QTime) -> None:
        if not self._sync:
            self._set_from_start(t)
            self._update()

    def _elapsed_changed(self, t: QTime) -> None:
        if self._sync:
            return
        start = self.now - timedelta(hours=t.hour(), minutes=t.minute())
        self._sync = True
        if start.date() == self.now.date():
            self.start.setTime(QTime(start.hour, start.minute))
        else:  # vor Mitternacht: nicht erlaubt, Vorschau meldet es
            self.start.setTime(QTime(0, 0))
        self._sync = False
        self._update(override=self._snap(start))

    def _update(self, override: datetime | None = None) -> None:
        start = override or self._new_start()
        try:
            old, new = self.svc.preview_edit(self.entry.id, {"start": start})
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
            return
        self.preview.setText(preview_html(self.svc, old, new, self.entry.id))
        self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        self._pending = start

    def _save(self) -> None:
        changes = {"start": getattr(self, "_pending", self._new_start())}
        mode = ask_overlap(self, self.svc, self.entry.id, changes)
        if mode is None:
            return
        try:
            self.svc.edit_entry(self.entry.id, changes, mode)
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return
        self.accept()


class NoteEdit(QPlainTextEdit):
    """Mehrzeiliges Notizfeld; `editingFinished` kommt beim Verlassen des Feldes."""
    editingFinished = Signal()

    VISIBLE_LINES = 3

    def __init__(self, text: str = "", placeholder: str = "", parent=None):
        super().__init__(text, parent)
        self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # genau 3 Zeilen hoch, darüber hinaus scrollt das Feld
        lines = self.fontMetrics().lineSpacing() * self.VISIBLE_LINES
        self.setFixedHeight(int(lines + self.document().documentMargin() * 2 + 2 * self.frameWidth()))

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

    def set_text(self, text: str) -> None:
        if self.toPlainText() != text:
            self.setPlainText(text)


def note_one_line(text: str) -> str:
    return " ⏎ ".join(line.strip() for line in text.splitlines() if line.strip())


def fmt_time(dt: datetime | None) -> str:
    return "läuft" if dt is None else dt.strftime("%H:%M")


def fmt_duration(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _qtime(dt: datetime) -> QTime:
    return QTime(dt.hour, dt.minute)


def _to_dt(day: date, t: QTime) -> datetime:
    return datetime.combine(day, time(t.hour(), t.minute()))


class EntryDialog(QDialog):
    """Bearbeiten (entry gegeben) oder Neuanlegen (entry=None)."""

    def __init__(self, service: TimeService, day: date, entry: Entry | None = None,
                 default_start: datetime | None = None, parent=None):
        super().__init__(parent)
        self.svc, self.day, self.entry = service, day, entry
        self.setWindowTitle("Eintrag bearbeiten" if entry else "Eintrag hinzufügen")
        self.setMinimumWidth(520)
        is_pause = bool(entry and entry.kind == PAUSE)

        self.project = QComboBox()
        self.project.addItem("–", None)
        for p in service.projects():
            self.project.addItem(p["name"], p["id"])
        self.activity = QComboBox()
        self.note = NoteEdit(entry.note if entry else "", "Was wurde gemacht? (mehrere Zeilen möglich)")
        self.devops_id = self._build_devops_combo(entry.devops_id if entry else None)
        self.start = QTimeEdit()
        self.end = QTimeEdit()
        for w in (self.start, self.end):
            w.setDisplayFormat("HH:mm")
            w.setFixedWidth(72)   # „HH:mm“ braucht nicht mehr Platz
        self.from_prev = QPushButton("⇤ Ende des Vorgängers")
        self.from_prev.setToolTip("Start auf das Ende des vorherigen Eintrags setzen (lückenlos anschließen)")
        self.from_prev.clicked.connect(self._start_at_previous_end)
        self.billable = QCheckBox("verrechenbar")
        self.billable.setChecked(entry.billable if entry else False)
        self.running = QCheckBox("läuft noch")
        self.duration = QTimeEdit()
        self.duration.setDisplayFormat("HH:mm")
        self.duration.setFixedWidth(72)
        self.duration.setToolTip("Dauer von Start bis Ende (Std:Min). Ändert das Ende – bei einem laufenden "
                                 "Eintrag den Start; die anderen Einträge passen sich an.")
        self._sync = False  # verhindert Rückkopplung zwischen Start, Ende und Dauer
        # Markierung, von wo aus die Dauer gerechnet wird: der markierte Zeitpunkt bleibt, der andere wandert
        self.anchor_start = QRadioButton("Dauer ab hier")
        self.anchor_end = QRadioButton("Dauer bis hier")
        self.anchor_start.setToolTip("Eine neue Dauer ändert das Ende; der Start bleibt")
        self.anchor_end.setToolTip("Eine neue Dauer ändert den Start; das Ende bleibt")
        (self.anchor_end if service.duration_anchor == "end" else self.anchor_start).setChecked(True)
        self.anchor_start.clicked.connect(lambda: self.svc.set_duration_anchor("start"))
        self.anchor_end.clicked.connect(lambda: self.svc.set_duration_anchor("end"))
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)

        if entry:
            self.start.setTime(_qtime(entry.start))
            self.end.setTime(_qtime(entry.end or service.now()))
            self.running.setChecked(entry.running)
            self.running.setEnabled(False)
            self.end.setEnabled(not entry.running)
            if entry.running:  # ohne Ende gibt es nur eine Richtung: die Dauer reicht bis „jetzt“
                self.anchor_end.setChecked(True)
                self.anchor_start.setEnabled(False)
                self.anchor_end.setEnabled(False)
            self.project.setCurrentIndex(max(0, self.project.findData(entry.project_id)))
        else:
            s = default_start or service.now()
            self.start.setTime(_qtime(s))
            self.end.setTime(_qtime(s + timedelta(minutes=30)))
            self.running.setVisible(False)
        self._fill_activities(entry.activity_id if entry else None)
        self._show_duration()

        form = QFormLayout()
        if not is_pause:
            form.addRow("Projekt", self.project)
            form.addRow("Tätigkeit", self.activity)
            form.addRow("Notiz", self.note)
            if service.devops_enabled:
                form.addRow("DevOps-ID", self.devops_id)
            form.addRow("", self.billable)
        for label, widget, radio in (("Start", self.start, self.anchor_start), ("Ende", self.end, self.anchor_end)):
            row = QHBoxLayout()
            row.addWidget(widget)
            row.addWidget(radio)
            if widget is self.start:
                row.addWidget(self.from_prev)
            row.addStretch(1)
            form.addRow(label, row)
        form.addRow("", self.running)
        form.addRow("Dauer (Std:Min)", self.duration)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.preview)
        lay.addWidget(self.buttons)

        self.project.currentIndexChanged.connect(self._project_changed)
        self.billable.toggled.connect(lambda _: self._update())
        self.activity.currentIndexChanged.connect(lambda _: self._update())
        self.note.textChanged.connect(self._update)
        self.devops_id.currentTextChanged.connect(lambda _: self._update())
        self.devops_id.activated.connect(self._devops_selected)
        self.start.timeChanged.connect(self._on_times)
        self.end.timeChanged.connect(self._on_times)
        self.duration.timeChanged.connect(self._on_duration)
        self._update()

    def _previous_entry(self) -> Entry | None:
        """Der Eintrag, der zeitlich direkt vor diesem liegt (beim Neuanlegen: vor dem eingestellten Start)."""
        entries = [x for x in self.svc.day_entries(self.day) if x.end is not None]
        if self.entry is not None:
            entries = [x for x in entries if x.id != self.entry.id and x.start < self.entry.start]
        else:
            start = _to_dt(self.day, self.start.time())
            entries = [x for x in entries if x.start < start]
        return max(entries, key=lambda x: x.start, default=None)

    def _start_at_previous_end(self) -> None:
        prev = self._previous_entry()
        if prev is None:
            self.preview.setText("<span style='color:#b35c00'>Es gibt keinen vorherigen Eintrag.</span>")
            return
        self.start.setTime(_qtime(prev.end))

    def _project_changed(self, _=None) -> None:
        self._fill_activities(None)
        self.billable.setChecked(self.svc.project_billable(self.project.currentData()))
        self._update()

    def _fill_activities(self, selected: int | None) -> None:
        self.activity.blockSignals(True)
        self.activity.clear()
        self.activity.addItem("–", None)
        for a in self.svc.activities_for(self.project.currentData()):
            self.activity.addItem(a["name"], a["id"])
        if selected is not None:
            self.activity.setCurrentIndex(max(0, self.activity.findData(selected)))
        self.activity.blockSignals(False)

    # --- Werte -> Änderungen ------------------------------------------------
    def _build_devops_combo(self, current: int | None) -> QComboBox:
        """Auswahl der bekannten Features und Stories (aus dem Zwischenspeicher), durchsuchbar; eine ID
        lässt sich auch direkt eintippen."""
        box = QComboBox()
        box.setEditable(True)
        box.setInsertPolicy(QComboBox.NoInsert)
        box.lineEdit().setPlaceholderText("Feature/Story wählen, Titel suchen oder ID eingeben …")
        box.setToolTip("Verknüpft den Eintrag mit einem DevOps-Item; die Stunden gehen dorthin")
        completer = box.completer()
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        box.addItem(NO_LINK, None)
        groups, loose = group_items(self.svc.devops_features_cache())
        known = set()

        def add(item: dict, story: bool) -> None:
            box.addItem(("↳ " if story else "") + f"#{item['id']}  {item['title']}", item["id"])
            known.add(item["id"])
        for feature, stories in groups:
            add(feature, False)
            for s in stories:
                add(s, True)
        for s in loose:
            add(s, True)
        if current is not None and current not in known:  # z. B. früher verknüpft, aber nicht (mehr) in der Liste
            box.insertItem(1, f"#{current}  {self.svc.devops_title(current)}".rstrip(), current)
        box.setCurrentIndex(max(0, box.findData(current)))
        return box

    def _devops_state(self) -> tuple[int | None, bool]:
        """(ID, gültig). Gültig sind: leer/„keine Verknüpfung“, ein Eintrag der Liste oder eine reine Zahl."""
        text = self.devops_id.currentText().strip()
        if not text or text == NO_LINK:
            return None, True
        i = self.devops_id.findText(text, Qt.MatchFixedString)
        if i >= 0:
            return self.devops_id.itemData(i), True
        m = re.fullmatch(r"#?\s*(\d+)", text)
        return (int(m.group(1)), True) if m else (None, False)

    def _devops_id(self) -> int | None:
        return self._devops_state()[0]

    def _devops_selected(self, index: int) -> None:
        """Wer ein Feature/eine Story wählt, dessen Projekt wird gleich mit übernommen – sofern es das Feature
        schon als Projekt gibt (sonst bleibt das Projekt, wie es ist; es lässt sich oben ändern)."""
        item_id = self.devops_id.itemData(index)
        item = next((i for i in self.svc.devops_features_cache() if i["id"] == item_id), None)
        if item is None:
            return
        feature_id = item.get("parent_id") if item.get("type") == "story" else item["id"]
        pid = self.svc.find_project(number=str(feature_id)) if feature_id else None
        if pid is not None and self.project.findData(pid) >= 0:
            self.project.setCurrentIndex(self.project.findData(pid))

    def _changes(self) -> dict:
        e = self.entry
        start = _to_dt(self.day, self.start.time())
        end = _to_dt(self.day, self.end.time())
        if e is None:
            return {"start": start, "end": end}
        changes: dict = {}
        edited = start != e.start.replace(second=0) or (not e.running and end != e.end.replace(second=0))
        if edited:
            # Die Felder zeigen nur Minuten. Wer eine Zeit ändert, bekommt deshalb Start UND Ende minutengenau –
            # sonst ergäbe z. B. Start 10:32:58 + Ende 10:42 nur 9:02 („0:09“) statt der gewünschten 10 Minuten.
            if start != e.start:
                changes["start"] = start
            if not e.running and end != e.end:
                changes["end"] = end
        if e.kind != PAUSE:
            if self.project.currentData() != e.project_id:
                changes["project_id"] = self.project.currentData()
            if self.activity.currentData() != e.activity_id:
                changes["activity_id"] = self.activity.currentData()
            if self.note.toPlainText() != e.note:
                changes["note"] = self.note.toPlainText()
            if self._devops_id() != e.devops_id:
                changes["devops_id"] = self._devops_id()
            if self.billable.isChecked() != e.billable or "project_id" in changes:
                changes["billable"] = self.billable.isChecked()
        return changes

    def _compute(self):
        ch = self._changes()
        if self.entry is None:
            new = Entry(ch["start"], ch["end"], project_id=self.project.currentData(),
                        activity_id=self.activity.currentData(), note=self.note.toPlainText(),
                        billable=self.billable.isChecked(), devops_id=self._devops_id())
            return self.svc.preview_insert(new)
        return self.svc.preview_edit(self.entry.id, ch)

    # --- Start, Ende und Dauer hängen zusammen -------------------------------------------------
    def _is_running(self) -> bool:
        return bool(self.entry and self.entry.running)

    def _now_minute(self) -> datetime:
        return self.svc.now().replace(second=0, microsecond=0)

    def _span(self) -> tuple[datetime, datetime]:
        """Start und Ende laut Eingabe (bei laufenden Einträgen: jetzt)."""
        end = self._now_minute() if self._is_running() else _to_dt(self.day, self.end.time())
        return _to_dt(self.day, self.start.time()), end

    def _show_duration(self) -> None:
        s, e = self._span()
        minutes = min(max(0, int((e - s).total_seconds() // 60)), 23 * 60 + 59)
        self._sync = True
        self.duration.setTime(QTime(minutes // 60, minutes % 60))
        self._sync = False

    def _on_times(self, _=None) -> None:
        if not self._sync:
            self._show_duration()
            self._update()

    def _on_duration(self, t: QTime) -> None:
        """Neue Dauer: Der markierte Zeitpunkt bleibt, der andere wandert (jeweils nicht über den Tag hinaus).
        Bei einem laufenden Eintrag gibt es kein Ende, die Dauer reicht bis „jetzt“ und ändert den Start."""
        if self._sync:
            return
        dur = timedelta(hours=t.hour(), minutes=t.minute())
        day_start, day_end = datetime.combine(self.day, time.min), datetime.combine(self.day, time(23, 59))
        self._sync = True
        if self._is_running():
            self.start.setTime(_qtime(max(self._now_minute() - dur, day_start)))
        elif self.anchor_end.isChecked():
            self.start.setTime(_qtime(max(_to_dt(self.day, self.end.time()) - dur, day_start)))
        else:
            self.end.setTime(_qtime(min(_to_dt(self.day, self.start.time()) + dur, day_end)))
        self._sync = False
        self._show_duration()
        self._update()

    def _lunch_hint(self) -> str:
        if self.entry and self.entry.kind == PAUSE:
            return ""
        s, e = self._span()
        if e <= s:
            return ""
        lunch = self.svc.lunch_overlap(Entry(s, e), self.svc.lunch_window(self.day), self._now_minute())
        if not lunch:
            return ""
        return (f"<span style='color:#667'>Davon {fmt_duration(lunch)} Mittagspause – zählt "
                f"{fmt_duration(e - s - lunch)} h (wird abgezogen).</span>")

    def _update(self) -> None:
        if not self._devops_state()[1]:
            self.preview.setText("<span style='color:#c0392b'>⚠ Bitte ein Feature/eine Story aus der Liste wählen "
                                 "oder eine DevOps-ID eingeben.</span>")
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
            return
        try:
            old, new = self._compute()
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
            return
        text = preview_html(self.svc, old, new, self.entry.id if self.entry else None)
        hint = self._lunch_hint()
        self.preview.setText(text + ("<br>" if text and hint else "") + hint)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(True)

    def _save(self) -> None:
        try:
            if self.entry is None:
                ch = self._changes()
                self.svc.insert_entry(Entry(ch["start"], ch["end"],
                                            project_id=self.project.currentData(),
                                            activity_id=self.activity.currentData(),
                                            note=self.note.toPlainText(),
                                            billable=self.billable.isChecked(),
                                            devops_id=self._devops_id()))
            else:
                changes = self._changes()
                mode = ask_overlap(self, self.svc, self.entry.id, changes)
                if mode is None:
                    return
                self.svc.edit_entry(self.entry.id, changes, mode)
        except TimelineError as ex:
            self.preview.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return
        self.accept()
