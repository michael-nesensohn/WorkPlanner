"""Seiten: Stammdaten, Woche, Berichte."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, time, timedelta

from PySide6.QtCore import QDate, QTime, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from .. import autostart
from ..export import ALL_COLUMNS, COLUMNS, export_excel
from ..service import TimeService
from .dialogs import fmt_duration

PREVIEW_ROWS = 200
MONDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# --- Stammdaten ---------------------------------------------------------------

class ActivityDialog(QDialog):
    def __init__(self, service: TimeService, name: str = "", project_id: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tätigkeit")
        self.name = QLineEdit(name)
        self.project = QComboBox()
        self.project.addItem("Alle Projekte", None)
        for p in service.projects():
            self.project.addItem(p["name"], p["id"])
        self.project.setCurrentIndex(max(0, self.project.findData(project_id)))
        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow("Gilt für", self.project)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class ProjectDialog(QDialog):
    def __init__(self, name: str = "", number: str = "", billable: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Projekt")
        self.billable = QCheckBox("verrechenbar (Vorgabe für neue Einträge)")
        self.billable.setChecked(billable)
        self.number = QLineEdit(number)
        self.number.setPlaceholderText("z. B. 2026-014 (optional)")
        self.name = QLineEdit(name)
        form = QFormLayout(self)
        form.addRow("Projektnummer", self.number)
        form.addRow("Name", self.name)
        form.addRow("", self.billable)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class MasterDataPage(QWidget):
    changed = Signal()

    def __init__(self, service: TimeService):
        super().__init__()
        self.svc = service
        self.projects = QListWidget()
        self.activities = QListWidget()

        pbox = QGroupBox("Projekte (★ = in der Schnellauswahl)")
        pl = QVBoxLayout(pbox)
        pl.addWidget(self.projects)
        pl.addLayout(self._buttons([("Neu", self._new_project), ("Bearbeiten", self._edit_project),
                                    ("★ Favorit", self._toggle_favorite), ("Farbe", self._color_project),
                                    ("▲", lambda: self._move_project(-1)), ("▼", lambda: self._move_project(1)),
                                    ("Löschen", self._delete_project)]))
        abox = QGroupBox("Tätigkeiten")
        al = QVBoxLayout(abox)
        al.addWidget(self.activities)
        al.addLayout(self._buttons([("Neu", self._new_activity), ("Ändern", self._edit_activity),
                                    ("Löschen", self._delete_activity)]))

        sbox = QGroupBox("Einstellungen")
        sf = QFormLayout(sbox)
        self.pause_start = QTimeEdit()
        self.pause_start.setDisplayFormat("HH:mm")
        self.pause_min = QSpinBox()
        self.pause_min.setRange(0, 240)
        self.pause_min.setSuffix(" min  (0 = keine Pause)")
        self.lunch_mode = QComboBox()
        self.lunch_mode.addItem("Nur abziehen (automatisch)", "deduct")
        self.lunch_mode.addItem("Nachfragen und Pause als Eintrag anlegen", "ask")
        self.lunch_mode.setToolTip("Nachfragen: zur Mittagspause erscheint „Pause starten?“. Die Pause wird dann als "
                                   "Eintrag angelegt, die Aufgabe läuft danach weiter.")
        self.target = QTimeEdit()
        self.target.setDisplayFormat("HH:mm")
        self.default_project = QComboBox()
        sf.addRow("Standardprojekt (Start ohne Auswahl)", self.default_project)
        self.hotkey_edit = QKeySequenceEdit()
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setToolTip("Zum Ändern hineinklicken und die Tasten drücken")
        self.hotkey_off = QPushButton("Aus")
        self.hotkey_off.clicked.connect(lambda: self._set_hotkey(""))
        self.hotkey_status = QLabel()
        self.hotkey_status.setWordWrap(True)
        self.hotkey_apply = lambda text: ""   # vom Hauptfenster gesetzt: meldet die Kombination an
        hk = QHBoxLayout()
        hk.addWidget(self.hotkey_edit, 1)
        hk.addWidget(self.hotkey_off)
        sf.addRow("Tastenkombination (Fenster minimieren/öffnen)", hk)
        sf.addRow("", self.hotkey_status)
        self.autostart = autostart  # austauschbar für Tests
        self.autostart_cb = QCheckBox("Mit Windows starten")
        self.start_tray_cb = QCheckBox("… dabei nur im Tray starten (Fenster bleibt zu)")
        self.tray_cb = QCheckBox("Schließen und Minimieren schicken das Fenster in den Tray")
        self.devops_cb = QCheckBox("DevOps-Funktionen verwenden (Reiter „DevOps“, Features auf „Heute“, Verknüpfungen)")
        self.devops_cb.setToolTip("Ausgeschaltet verschwindet alles zu DevOps aus der Oberfläche; Daten bleiben erhalten")
        self.call_cb = QCheckBox("Nach einem Teams-Anruf fragen, ob er eingetragen werden soll")
        self.call_cb.setToolTip("Erkennt Anrufe und Besprechungen daran, dass Teams das Mikrofon öffnet")
        self.autostart_status = QLabel()
        self.autostart_status.setWordWrap(True)
        sf.addRow("Start und Tray", self.autostart_cb)
        sf.addRow("", self.start_tray_cb)
        sf.addRow("", self.tray_cb)
        sf.addRow("DevOps", self.devops_cb)
        sf.addRow("Teams-Anrufe", self.call_cb)
        self.db_warn = QSpinBox()
        self.db_warn.setRange(0, 100000)
        self.db_warn.setSuffix(" MB  (0 = nie)")
        self.db_warn.setToolTip("Ist die Datenbankdatei größer, erscheint beim Start ein Hinweis")
        self.db_size = QLabel()
        self.db_size.setStyleSheet("color:#667")
        row = QHBoxLayout()
        row.addWidget(self.db_warn)
        row.addWidget(self.db_size, 1)
        sf.addRow("Hinweis bei Datenbank größer als", row)
        sf.addRow("", self.autostart_status)
        sf.addRow("Mittagspause ab (wird abgezogen)", self.pause_start)
        sf.addRow("Pausendauer", self.pause_min)
        sf.addRow("Mittagspause", self.lunch_mode)
        sf.addRow("Soll-Arbeitszeit pro Tag (Std:Min)", self.target)

        top = QHBoxLayout()
        top.addWidget(pbox, 1)
        top.addWidget(abox, 1)
        # Zwei Reiter: „Stammdaten“ (Projekte, Tätigkeiten) und „Einstellungen“ (Tastenkombination, Start und Tray, …)
        self.sections = QTabWidget()
        master = QWidget()
        QVBoxLayout(master).addLayout(top)
        settings = QWidget()
        lay = QVBoxLayout(settings)
        lay.addWidget(sbox)
        self.sections.addTab(master, "Stammdaten")
        self.sections.addTab(settings, "Einstellungen")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.sections)

        # Excel-Stundenzettel: in diese Datei werden Stunden je Projekt und Tag eingetragen (Berichte → „In Excel eintragen“)
        xbox = QGroupBox("Excel-Stundenzettel")
        xl = QFormLayout(xbox)
        self.excel_path = QLineEdit()
        self.excel_path.setPlaceholderText("z. B. C:\\Users\\…\\Stunden_2026.xlsx (ein Blatt je Monat)")
        browse = QPushButton("…")
        browse.setToolTip("Datei auswählen")
        browse.clicked.connect(self._browse_excel)
        check = QPushButton("Prüfen")
        check.setToolTip("Prüft, ob die Datei die Monatsblätter enthält")
        check.clicked.connect(self._check_excel)
        prow = QHBoxLayout()
        prow.addWidget(self.excel_path, 1)
        prow.addWidget(browse)
        prow.addWidget(check)
        self.excel_save = QCheckBox("Datei nach dem Eintragen speichern")
        self.excel_pause = QCheckBox("Pausen mit in den Stundenzettel eintragen (als Zeile „Pause“)")
        self.excel_pause.setToolTip("Aus: nur Arbeitszeit geht nach Excel. An: die als Eintrag angelegten Pausen werden "
                                    "unter dem Namen „Pause“ eingetragen (die Vorlage braucht dafür eine Zeile „Pause“).")
        self.excel_status = QLabel("Eintragen: Berichte → „In Excel-Stundenzettel eintragen …“. Excel muss installiert sein.")
        self.excel_status.setWordWrap(True)
        self.excel_status.setStyleSheet("color:#667")
        self.excel_profile_label = QLabel()
        self.excel_profile_label.setStyleSheet("color:#667")
        profile_btn = QPushButton("Vorlage zuordnen …")
        profile_btn.setToolTip("Aufbau deiner Excel-Vorlage festlegen (Assistent); Profile lassen sich exportieren "
                               "und importieren")
        profile_btn.clicked.connect(self._edit_excel_profile)
        qrow = QHBoxLayout()
        qrow.addWidget(profile_btn)
        qrow.addWidget(self.excel_profile_label, 1)
        xl.addRow("Datei", prow)
        xl.addRow("Vorlage", qrow)
        xl.addRow("", self.excel_save)
        xl.addRow("", self.excel_pause)
        xl.addRow("", self.excel_status)
        lay.addWidget(xbox)
        lay.addStretch(1)
        self.reload()
        for w in (self.pause_start,):
            w.timeChanged.connect(self._save_settings)
        self.pause_min.valueChanged.connect(self._save_settings)
        self.target.timeChanged.connect(self._save_settings)
        self.default_project.currentIndexChanged.connect(self._save_settings)
        self.excel_path.editingFinished.connect(self._save_excel)
        self.excel_save.clicked.connect(lambda _: self._save_excel())
        self.excel_pause.clicked.connect(lambda _: self._save_excel())
        self.lunch_mode.currentIndexChanged.connect(self._save_settings)
        self.autostart_cb.clicked.connect(self._autostart_changed)
        self.start_tray_cb.clicked.connect(self._start_tray_changed)
        self.tray_cb.clicked.connect(lambda on: self.svc.set_tray_mode(on))
        self.call_cb.clicked.connect(lambda on: self.svc.set_call_monitor(on))
        self.devops_cb.clicked.connect(self._devops_toggled)
        self.db_warn.valueChanged.connect(lambda mb: self.svc.set_db_warn_mb(mb))
        self.hotkey_edit.editingFinished.connect(
            lambda: self._set_hotkey(self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)))

    @staticmethod
    def _buttons(items):
        row = QHBoxLayout()
        for text, fn in items:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        return row

    def reload(self) -> None:
        self.projects.clear()
        for p in self.svc.projects():
            it = QListWidgetItem(("★ " if p["favorite"] else "☆ ") + self.svc.project_display(p["id"])
                                 + ("   [verrechenbar]" if p["billable"] else ""))
            it.setData(256, p["id"])
            it.setForeground(QColor(p["color"]))
            self.projects.addItem(it)
        self.activities.clear()
        for a in self.svc.db.list_activities():
            scope = self.svc.project_name(a["project_id"]) if a["project_id"] else "alle Projekte"
            it = QListWidgetItem(f"{a['name']}   ({scope})")
            it.setData(256, a["id"])
            self.activities.addItem(it)
        for w in (self.pause_start, self.pause_min, self.target, self.default_project, self.lunch_mode):
            w.blockSignals(True)
        self.default_project.clear()
        current = self.svc.default_project_id(create=False)
        if current is None:  # noch keins festgelegt: „Allgemein“ entsteht beim ersten Start der Zeit
            self.default_project.addItem("Allgemein (wird beim ersten Start angelegt)", None)
        for p in self.svc.projects():
            self.default_project.addItem(p["name"], p["id"])
        self.default_project.setCurrentIndex(max(0, self.default_project.findData(current)))
        self._show_hotkey(self.svc.hotkey)
        self.excel_path.setText(self.svc.excel_path)
        self.excel_save.setChecked(self.svc.excel_save)
        self.excel_pause.setChecked(self.svc.excel_include_pause)
        self.excel_profile_label.setText(self.svc.excel_profile.name)
        self.db_warn.blockSignals(True)
        self.db_warn.setValue(self.svc.db_warn_mb)
        self.db_size.setText(f"aktuell {self.svc.db.size_bytes() / 1024 / 1024:.1f} MB")
        self.db_warn.blockSignals(False)
        for cb, value in ((self.autostart_cb, self.autostart.is_enabled()),
                          (self.start_tray_cb, self.svc.start_in_tray), (self.tray_cb, self.svc.tray_mode),
                          (self.call_cb, self.svc.call_monitor), (self.devops_cb, self.svc.devops_enabled)):
            cb.setChecked(value)
        self.start_tray_cb.setEnabled(self.autostart_cb.isChecked())
        s = self.svc.pause_start
        self.pause_start.setTime(QTime(s.hour, s.minute))
        self.pause_min.setValue(int(self.svc.pause_length.total_seconds() // 60))
        self.lunch_mode.setCurrentIndex(max(0, self.lunch_mode.findData(self.svc.lunch_mode)))
        tm = int(self.svc.daily_target.total_seconds() // 60)
        self.target.setTime(QTime(tm // 60, tm % 60))
        for w in (self.pause_start, self.pause_min, self.target, self.default_project, self.lunch_mode):
            w.blockSignals(False)

    def _save_excel(self) -> None:
        self.svc.set_excel(self.excel_path.text(), self.excel_save.isChecked())
        self.svc.set_excel_include_pause(self.excel_pause.isChecked())
        self.changed.emit()  # die Berichte-Seite aktiviert ihren Knopf, sobald eine Datei eingestellt ist

    def _browse_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Excel-Stundenzettel wählen", self.excel_path.text(),
                                              "Excel (*.xlsx *.xlsm)")
        if path:
            self.excel_path.setText(path)
            self._save_excel()
            self._check_excel()

    def _edit_excel_profile(self) -> None:
        from .excel_profile_dialog import ExcelProfileDialog
        self._save_excel()
        if ExcelProfileDialog(self.svc, self.window()).exec():
            self.reload()
            self.changed.emit()

    def _check_excel(self) -> None:
        """Schnelle Prüfung ohne Excel zu starten: Gibt es die Datei und die Monatsblätter laut Profil?"""
        path = self.excel_path.text().strip()
        try:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, keep_links=False)
            names = {n.strip().casefold() for n in wb.sheetnames}
            wb.close()
        except Exception as ex:  # noqa: BLE001 – nicht vorhanden, keine Excel-Datei, gesperrt …
            self.excel_status.setText(f"<span style='color:#c0392b'>⚠ Datei nicht lesbar: {ex}</span>")
            return
        profile, year = self.svc.excel_profile, self.svc.now().year
        wanted = [profile.sheet_name_for(m, year) for m in range(1, 13)]
        missing = [w for w in wanted if w.strip().casefold() not in names]
        self.excel_status.setText("✓ Alle 12 Monatsblätter gefunden." if not missing else
                                  "<span style='color:#8a5a00'>Es fehlen Blätter: " + ", ".join(missing) + "</span>")

    def _devops_toggled(self, on: bool) -> None:
        self.svc.set_devops_enabled(on)
        self.changed.emit()  # das Hauptfenster blendet Reiter, Kacheln und Spalten ein bzw. aus

    def _autostart_changed(self, on: bool) -> None:
        try:
            if on:
                self.autostart.enable(self.svc.start_in_tray)
            else:
                self.autostart.disable()
        except OSError as ex:
            self.autostart_status.setText(f"<span style='color:#c0392b'>⚠ Konnte nicht geändert werden: {ex}</span>")
            self.autostart_cb.setChecked(self.autostart.is_enabled())
            return
        self.start_tray_cb.setEnabled(on)
        self.autostart_status.setText("✓ WorkPlanner startet künftig mit Windows." if on
                                      else "Autostart ist aus.")

    def _start_tray_changed(self, on: bool) -> None:
        self.svc.set_start_in_tray(on)
        if self.autostart_cb.isChecked():  # Befehl im Autostart-Eintrag anpassen
            self._autostart_changed(True)

    def _show_hotkey(self, text: str) -> None:
        self.hotkey_edit.blockSignals(True)
        self.hotkey_edit.setKeySequence(QKeySequence(text))
        self.hotkey_edit.blockSignals(False)

    def _set_hotkey(self, text: str) -> None:
        """Meldet die Kombination an; nur bei Erfolg wird sie gespeichert, sonst bleibt die alte."""
        error = self.hotkey_apply(text)
        if error:
            self.hotkey_status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            self._show_hotkey(self.svc.hotkey)
            return
        self.svc.set_hotkey(text)
        self._show_hotkey(text)
        self.show_hotkey_active(text)

    def show_hotkey_active(self, text: str) -> None:
        self.hotkey_status.setText(f"✓ Aktiv: {QKeySequence(text).toString(QKeySequence.NativeText)}"
                                   if text else "Aus – keine Tastenkombination.")

    def _save_settings(self) -> None:
        t = self.pause_start.time()
        self.svc.set_pause(time(t.hour(), t.minute()), self.pause_min.value())
        self.svc.set_lunch_mode(self.lunch_mode.currentData())
        self.svc.set_daily_target(self.target.time().hour() * 60 + self.target.time().minute())
        if self.default_project.currentData() is not None:
            self.svc.set_default_project(self.default_project.currentData())
        self.changed.emit()

    def _sel(self, lst: QListWidget) -> int | None:
        it = lst.currentItem()
        return it.data(256) if it else None

    def _done(self) -> None:
        self.reload()
        self.changed.emit()

    def _new_project(self) -> None:
        dlg = ProjectDialog(parent=self)
        if dlg.exec() and dlg.name.text().strip():
            try:
                self.svc.db.add_project(dlg.name.text().strip(), number=dlg.number.text().strip(),
                                        billable=dlg.billable.isChecked())
            except Exception:
                QMessageBox.warning(self, "Projekt", "Ein Projekt mit diesem Namen existiert bereits.")
            self._done()

    def _edit_project(self) -> None:
        pid = self._sel(self.projects)
        if pid is None:
            return
        dlg = ProjectDialog(self.svc.project_name(pid), self.svc.project_number(pid),
                            self.svc.project_billable(pid), self)
        if dlg.exec() and dlg.name.text().strip():
            try:
                self.svc.db.update_project(pid, name=dlg.name.text().strip(),
                                           number=dlg.number.text().strip(),
                                           billable=dlg.billable.isChecked())
            except Exception:
                QMessageBox.warning(self, "Projekt", "Ein Projekt mit diesem Namen existiert bereits.")
            self._done()

    def _toggle_favorite(self) -> None:
        pid = self._sel(self.projects)
        if pid is not None:
            fav = next(p["favorite"] for p in self.svc.projects() if p["id"] == pid)
            self.svc.db.update_project(pid, favorite=not fav)
            self._done()

    def _color_project(self) -> None:
        pid = self._sel(self.projects)
        if pid is None:
            return
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self.svc.db.update_project(pid, color=color.name())
            self._done()

    def _move_project(self, step: int) -> None:
        ids = [p["id"] for p in self.svc.projects()]
        pid = self._sel(self.projects)
        if pid is None:
            return
        i = ids.index(pid)
        j = i + step
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for order, p in enumerate(ids):
                self.svc.db.update_project(p, sort_order=order)
            self._done()
            self.projects.setCurrentRow(j)

    def _delete_project(self) -> None:
        pid = self._sel(self.projects)
        if pid is not None and QMessageBox.question(
                self, "Projekt", "Projekt ausblenden? Bestehende Einträge bleiben erhalten.") \
                == QMessageBox.Yes:
            self.svc.db.update_project(pid, archived=True)
            self._done()

    def _new_activity(self) -> None:
        dlg = ActivityDialog(self.svc, parent=self)
        if dlg.exec() and dlg.name.text().strip():
            self.svc.db.add_activity(dlg.name.text().strip(), dlg.project.currentData())
            self._done()

    def _edit_activity(self) -> None:
        aid = self._sel(self.activities)
        if aid is None:
            return
        a = next(x for x in self.svc.db.list_activities() if x["id"] == aid)
        dlg = ActivityDialog(self.svc, a["name"], a["project_id"], self)
        if dlg.exec() and dlg.name.text().strip():
            self.svc.db.update_activity(aid, name=dlg.name.text().strip(), project_id=dlg.project.currentData())
            self._done()

    def _delete_activity(self) -> None:
        aid = self._sel(self.activities)
        if aid is not None:
            self.svc.db.update_activity(aid, archived=1)
            self._done()


# --- Woche ----------------------------------------------------------------------

DAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
ENTRY_COLUMNS = ["Start", "Ende", "Dauer", "Verr.", "Projekt", "Tätigkeit", "DevOps", "Notiz"]


class WeekPage(QWidget):
    """Woche: „Übersicht“ (Summen je Tag und Projekt) und „Einträge“ (jeder Tag mit allen Buchungen und Notizen)."""
    open_day = Signal(object)  # date: Doppelklick auf einen Tag bzw. Eintrag

    def __init__(self, service: TimeService):
        super().__init__()
        self.svc = service
        self.monday = _monday(service.now().date())
        self.title = QLabel()
        self.title.setStyleSheet("font-size:16px;font-weight:600")
        prev, nxt = QPushButton("◀"), QPushButton("▶")
        prev.clicked.connect(lambda: self._go(-7))
        nxt.clicked.connect(lambda: self._go(7))
        nav = QHBoxLayout()
        nav.addWidget(prev)
        nav.addWidget(self.title)       # Pfeile direkt neben dem Datum, nicht am Fensterrand
        nav.addWidget(nxt)
        nav.addStretch(1)
        self.show_pauses = QCheckBox("Pausen anzeigen")
        self.show_pauses.setToolTip("Zeigt unter „Einträge“ die Pausen und ihre Summe. Die Spalte „Pausen“ in der "
                                    "Übersicht ist immer da (Pausen-Einträge plus abgezogene Mittagspause).")
        self.show_pauses.toggled.connect(lambda _: self.refresh())
        nav.addWidget(self.show_pauses)

        # Übersicht
        self.days = QTableWidget(0, 6)
        self.days.setHorizontalHeaderLabels(["Tag", "Gearbeitet", "davon verrechenbar", "Soll", "Differenz", "Pausen"])
        self.projects = QTableWidget(0, 2)
        self.projects.setHorizontalHeaderLabels(["Projekt", "Stunden"])
        for t in (self.days, self.projects):
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.horizontalHeader().setStretchLastSection(True)
            t.verticalHeader().setVisible(False)
        overview = QWidget()
        ol = QVBoxLayout(overview)
        ol.addWidget(self.days)
        ol.addWidget(self.projects)

        # Einträge: jeder Tag mit seinen Buchungen, wie in der Heute-Tabelle (Notiz vollständig)
        self.entries = QTableWidget(0, len(ENTRY_COLUMNS))
        self.entries.setHorizontalHeaderLabels(ENTRY_COLUMNS)
        self.entries.setEditTriggers(QTableWidget.NoEditTriggers)
        self.entries.setSelectionBehavior(QTableWidget.SelectRows)
        self.entries.setWordWrap(True)
        self.entries.setToolTip("Doppelklick öffnet den Tag in „Heute“ (dort lässt sich der Eintrag bearbeiten)")
        self.entries.verticalHeader().setVisible(False)
        hh = self.entries.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(len(ENTRY_COLUMNS) - 1, QHeaderView.Stretch)
        hh.sectionResized.connect(lambda *_: self.entries.resizeRowsToContents())  # Zeilenhöhe folgt dem Notiztext
        self.entries.cellDoubleClicked.connect(self._entry_double_clicked)

        self.views = QTabWidget()
        self.views.addTab(overview, "Übersicht")
        self.views.addTab(self.entries, "Einträge")
        lay = QVBoxLayout(self)
        lay.addLayout(nav)
        lay.addWidget(self.views, 1)
        self.refresh()

    def _go(self, days: int) -> None:
        self.monday += timedelta(days=days)
        self.refresh()

    def refresh(self) -> None:
        last = self.monday + timedelta(days=6)
        self.title.setText(f"{self.monday:%d.%m.} – {last:%d.%m.%Y}")
        all_rows = self.svc.report_rows(self.monday, last)
        show = self.show_pauses.isChecked()
        pause_day: dict[date, timedelta] = defaultdict(timedelta)   # Pausen-Einträge plus abgezogene Mittagspause
        for r in all_rows:
            pause_day[r["date"]] += r["duration"] if r["kind"] == "pause" else r["lunch"]
        rows = all_rows if show else [r for r in all_rows if r["kind"] != "pause"]   # Pausen nur auf Wunsch
        per_day: dict[date, timedelta] = defaultdict(timedelta)
        per_project: dict[str, timedelta] = defaultdict(timedelta)
        billable_day: dict[date, timedelta] = defaultdict(timedelta)
        for r in rows:
            if r["kind"] == "work":
                per_day[r["date"]] += r["duration"]
                if r["billable"]:
                    billable_day[r["date"]] += r["duration"]
                per_project[r["project"]] += r["duration"]
        self.days.setRowCount(8)
        total = timedelta()
        for i in range(7):
            d = self.monday + timedelta(days=i)
            worked = per_day[d]
            target = self.svc.daily_target if d.weekday() < 5 else timedelta()
            total += worked
            self._row(self.days, i, [f"{MONDAY_NAMES[i]} {d:%d.%m.}", fmt_duration(worked),
                                     fmt_duration(billable_day[d]), fmt_duration(target),
                                     self._diff(worked - target), fmt_duration(pause_day[d])])
        week_target = self.svc.daily_target * 5
        self._row(self.days, 7, ["Summe", fmt_duration(total),
                                 fmt_duration(sum(billable_day.values(), timedelta())),
                                 fmt_duration(week_target), self._diff(total - week_target),
                                 fmt_duration(sum(pause_day.values(), timedelta()))], bold=True)
        self.projects.setRowCount(len(per_project))
        for i, (name, dur) in enumerate(sorted(per_project.items())):
            self._row(self.projects, i, [name, fmt_duration(dur)])
        self._fill_entries(rows, per_day, billable_day, total, pause_day, show)

    def _fill_entries(self, rows: list[dict], per_day, billable_day, total: timedelta, pause_day, show: bool) -> None:
        by_day: dict[date, list[dict]] = defaultdict(list)
        for r in rows:
            by_day[r["date"]].append(r)
        t = self.entries
        t.setRowCount(0)
        header_bg = QColor("#e8eef7")

        def add_row() -> int:
            t.insertRow(t.rowCount())
            return t.rowCount() - 1

        for i in range(7):
            d = self.monday + timedelta(days=i)
            entries = by_day.get(d, [])
            if not entries and d.weekday() >= 5:
                continue  # Wochenende nur zeigen, wenn dort etwas gebucht wurde
            r = add_row()
            text = f"{DAY_NAMES[i]} {d:%d.%m.%Y}"
            target = self.svc.daily_target if d.weekday() < 5 else timedelta()
            text += (f"   ·   Gearbeitet {fmt_duration(per_day[d])} h   ·   davon verrechenbar "
                     f"{fmt_duration(billable_day[d])} h   ·   Soll {fmt_duration(target)} h   ·   "
                     f"Differenz {self._diff(per_day[d] - target)}"
                     f" h{f'   ·   Pausen {fmt_duration(pause_day[d])} h' if show else ''}"
                     if entries else "   ·   nichts gebucht")
            head = QTableWidgetItem(text)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            head.setBackground(header_bg)
            head.setData(Qt.UserRole, d)
            if not entries:
                head.setForeground(QColor("#888"))
            t.setItem(r, 0, head)
            t.setSpan(r, 0, 1, t.columnCount())
            for e in entries:
                r = add_row()
                pause = e["kind"] == "pause"
                project = "Pause" if pause else (f"{e['project_number']}  {e['project']}" if e["project_number"]
                                                 else e["project"])
                devops = f"#{e['devops_id']}" if e["devops_id"] else ""
                vals = [f"{e['start']:%H:%M}", "läuft" if e["running"] else f"{e['end']:%H:%M}",
                        fmt_duration(e["duration"]), "✓" if e["billable"] else "", project, e["activity"], devops,
                        e["note"]]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    it.setData(Qt.UserRole, d)
                    if c == 3:
                        it.setTextAlignment(Qt.AlignCenter)
                    if c == 2 and e["lunch"]:
                        it.setToolTip(f"{fmt_duration(e['duration'] + e['lunch'])} brutto, davon "
                                      f"{fmt_duration(e['lunch'])} Mittagspause (abgezogen)")
                    if pause:
                        it.setForeground(QColor("#888"))
                    elif e["running"]:
                        it.setForeground(QColor("#1b7f3b"))
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    t.setItem(r, c, it)
        r = add_row()
        week_target = self.svc.daily_target * 5
        tot = QTableWidgetItem(f"Woche gesamt: {fmt_duration(total)} h   ·   davon verrechenbar "
                               f"{fmt_duration(sum(billable_day.values(), timedelta()))} h   ·   "
                               f"Wochenstunden Soll {fmt_duration(week_target)} h   ·   "
                               f"Differenz {self._diff(total - week_target)} h"
                               + (f"   ·   Pausen {fmt_duration(sum(pause_day.values(), timedelta()))} h"
                                  if show else ""))
        font = tot.font()
        font.setBold(True)
        tot.setFont(font)
        tot.setBackground(QColor("#d5e1f3"))
        t.setItem(r, 0, tot)
        t.setSpan(r, 0, 1, t.columnCount())
        t.resizeRowsToContents()

    def _entry_double_clicked(self, row: int, _column: int) -> None:
        item = self.entries.item(row, 0)
        day = item.data(Qt.UserRole) if item else None
        if day is not None:
            self.open_day.emit(day)

    @staticmethod
    def _diff(td: timedelta) -> str:
        return ("+" if td >= timedelta() else "–") + fmt_duration(abs(td))

    @staticmethod
    def _row(table: QTableWidget, row: int, values: list[str], bold: bool = False) -> None:
        for c, v in enumerate(values):
            it = QTableWidgetItem(v)
            if bold:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            table.setItem(row, c, it)


# --- Berichte -------------------------------------------------------------------------

class ReportPage(QWidget):
    def __init__(self, service: TimeService):
        super().__init__()
        self.svc = service
        today = service.now().date()
        first = today.replace(day=1)
        self.first = QDateEdit(QDate(first.year, first.month, first.day))
        self.last = QDateEdit(QDate(today.year, today.month, today.day))
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setFixedWidth(120)
            w.setDisplayFormat("dd.MM.yyyy")
            w.dateChanged.connect(self._update)
        self.project = QComboBox()
        self.project.currentIndexChanged.connect(self._update)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-size:15px")
        export = QPushButton("Nach Excel exportieren …")
        export.setStyleSheet("padding:8px 16px;font-weight:600")
        export.clicked.connect(self._export)
        self.to_excel = QPushButton("In Excel-Stundenzettel eintragen …")
        self.to_excel.setStyleSheet("padding:8px 16px;font-weight:600")
        self.to_excel.clicked.connect(self._to_excel)
        form = QFormLayout()
        form.addRow("Von", self.first)
        form.addRow("Bis", self.last)
        form.addRow("Projekt", self.project)
        self.show_pauses = QCheckBox("Pausen-Einträge anzeigen und exportieren")
        self.show_pauses.setToolTip("Aus (Standard): die Pausen fehlen in der Vorschau und im Blatt „Einträge“. "
                                    "Die Tagesübersicht zählt sie immer.")
        self.show_pauses.toggled.connect(self._update)
        form.addRow("", self.show_pauses)
        box = QGroupBox("Spalten im Export (Blatt „Einträge“)")
        grid = QHBoxLayout(box)
        chosen = self.svc.export_columns
        self.column_boxes: dict[str, QCheckBox] = {}
        for key in self.svc.available_export_columns:
            cb = QCheckBox(COLUMNS[key][0])
            cb.setChecked(key in chosen)
            cb.toggled.connect(self._save_columns)
            self.column_boxes[key] = cb
            grid.addWidget(cb)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.summary)
        lay.addWidget(box)
        lay.addWidget(export)
        lay.addWidget(self.to_excel)
        self.preview = QTableWidget(0, 0)
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.verticalHeader().setVisible(False)
        self.preview_note = QLabel()
        lay.addWidget(QLabel("<b>Vorschau Export</b>"))
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.preview_note)
        self.reload_projects()

    def refresh_excel_button(self) -> None:
        has = bool(self.svc.excel_path)
        self.to_excel.setEnabled(has)
        self.to_excel.setToolTip("Trägt die Stunden je Projekt und Tag in den Excel-Stundenzettel ein" if has else
                                 "Zuerst unter Einstellungen → Stammdaten → Excel-Stundenzettel die Datei einstellen")

    def _to_excel(self) -> None:
        from .excel_dialog import ExcelExportDialog
        ExcelExportDialog(self.svc, self.window()).exec()

    def reload_projects(self) -> None:
        self.refresh_excel_button()
        self.project.blockSignals(True)
        self.project.clear()
        self.project.addItem("Alle Projekte", None)
        for p in self.svc.projects():
            self.project.addItem(p["name"], p["id"])
        self.project.blockSignals(False)
        self._update()

    def _range(self) -> tuple[date, date]:
        return self.first.date().toPython(), self.last.date().toPython()

    def _rows(self, with_pauses: bool | None = None) -> list[dict]:
        a, b = self._range()
        rows = self.svc.report_rows(a, b, self.project.currentData())
        shown = self.show_pauses.isChecked() if with_pauses is None else with_pauses
        return rows if shown else [r for r in rows if r["kind"] != "pause"]

    def _fill_preview(self, rows: list[dict]) -> None:
        cols = self._columns()
        shown = rows[:PREVIEW_ROWS]
        self.preview.setColumnCount(len(cols))
        self.preview.setHorizontalHeaderLabels([COLUMNS[c][0] for c in cols])
        self.preview.setRowCount(len(shown))
        for i, r in enumerate(shown):
            for n, c in enumerate(cols):
                v = COLUMNS[c][2](r)
                text = (f"{v:%d.%m.%Y}" if isinstance(v, date) else f"{v:%H:%M}" if isinstance(v, time) else
                        fmt_duration(v) if isinstance(v, timedelta) else str(v))
                self.preview.setItem(i, n, QTableWidgetItem(text.splitlines()[0] if text else text if c == "note" else text))
        self.preview.resizeColumnsToContents()
        self.preview_note.setText(f"Es werden nur die ersten {PREVIEW_ROWS} von {len(rows)} Einträgen angezeigt."
                                  if len(rows) > PREVIEW_ROWS else "")

    def _update(self) -> None:
        rows = self._rows()
        self._fill_preview(rows)
        work = sum((r["duration"] for r in rows if r["kind"] == "work"), timedelta())
        billable = sum((r["duration"] for r in rows if r["kind"] == "work" and r["billable"]), timedelta())
        self.summary.setText(f"{len(rows)} Einträge, Arbeitszeit gesamt: <b>{fmt_duration(work)} h</b>, "
                             f"davon verrechenbar: <b>{fmt_duration(billable)} h</b>")

    def apply_devops(self) -> None:
        """Ohne DevOps gibt es auch keine Export-Spalte „DevOps“."""
        on = self.svc.devops_enabled
        self.column_boxes["devops"].setVisible(on)
        self._fill_preview(self._rows())

    def _columns(self) -> list[str]:
        on = self.svc.devops_enabled
        return [k for k in ALL_COLUMNS if k in self.column_boxes and self.column_boxes[k].isChecked()
                and (on or k != "devops")]

    def _save_columns(self) -> None:
        self.svc.set_export_columns(self._columns())
        self._fill_preview(self._rows())

    def _export(self) -> None:
        if not self._columns():
            QMessageBox.warning(self, "Export", "Bitte mindestens eine Spalte auswählen.")
            return
        a, b = self._range()
        path, _ = QFileDialog.getSaveFileName(self, "Excel-Export", f"Zeiten_{a:%Y%m%d}_{b:%Y%m%d}.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            export_excel(path, self._rows(with_pauses=True), self.svc.daily_target, self._columns(),
                         show_pauses=self.show_pauses.isChecked())
        except OSError as ex:
            QMessageBox.warning(self, "Export", f"Datei konnte nicht geschrieben werden:\n{ex}")
            return
        QMessageBox.information(self, "Export", f"Gespeichert:\n{path}")
