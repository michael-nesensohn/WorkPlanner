"""Hauptfenster mit Heute-Ansicht."""
from __future__ import annotations

import ctypes
import os
import sys
from datetime import date, datetime, timedelta

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QSystemTrayIcon,
                               QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget, QHeaderView)

from ..devops_sync import item_id_from_note
from ..hotkey import GlobalHotkey
from ..icon import app_icon
from ..service import TimeService
from .. import demo as demo_data
from ..manual import manual_path
from ..outlook import read_appointments
from ..timeline import PAUSE, TimelineError, removed_entries
from .dialogs import CalendarDialog, EntryDialog, NoteEdit, RunningTimeDialog, fmt_duration, fmt_time, note_one_line
from .devops_page import DevOpsPage
from .feature_panel import FeatureFeed, FeaturePanel, to_cache
from .tiles import TileButton
from .note_task_dialog import NoteTaskDialog
from .outlook_dialog import OutlookImportDialog
from .outlook_panel import OutlookFeed, OutlookPanel
from .pages import MasterDataPage, ReportPage, WeekPage
from .._version import __version__
from ..call_monitor import CallMonitor
from .call_dialog import CallBanner, CallDialog
from .check_header import CheckHeader
from .about_dialog import AboutDialog
from .license_dialog import LicenseDialog
from .manual_window import ManualWindow
from .tray import TrayIcon

CLOCK_PX = 34  # muss zu QLabel#timer im Stylesheet passen
STYLE = """
QMainWindow, QWidget { font-size: 13px; }
QFrame#card { background: #f4f7fb; border: 1px solid #d5deea; border-radius: 10px; }
QLabel#timer { font-family: Consolas, "Courier New", monospace; font-size: 34px; font-weight: 600;
                color: #1f3a5f; }
QLabel#task { font-size: 16px; font-weight: 600; }
QPushButton#tile { text-align: left; padding: 2px 10px; border: 1px solid #c9d3e0; border-radius: 6px;
                   background: white; min-width: 120px; min-height: 19px; font-weight: 600; }
QPushButton#tile:hover { background: #eef3fa; }
QPushButton#tile:checked { background: #dce8fb; border: 2px solid #4f8cff; }
QPushButton#chip { padding: 4px 12px; border: 1px solid #c9d3e0; border-radius: 13px; background: white; }
QPushButton#chip:checked { background: #4f8cff; color: white; border-color: #4f8cff; }
QPushButton#stop { background: #d9534f; color: white; font-weight: 600; padding: 8px 18px; border-radius: 8px; }
QPushButton#new { background: #4f8cff; color: white; font-weight: 600; padding: 8px 18px; border-radius: 8px; }
QPushButton#start { background: #2ea36b; color: white; font-weight: 600; padding: 8px 18px; border-radius: 8px; }
QTableWidget { gridline-color: #e4e9f0; alternate-background-color: #fafbfd; }
"""


class ClockLabel(QLabel):
    """Die große Uhr; Doppelklick öffnet die Zeitanpassung."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()


class _SizedDialog(QDialog):
    """Dialog, der seine Größe merkt (wird kurz nach dem Ziehen gespeichert) und beim nächsten Öffnen wieder nimmt."""

    def __init__(self, parent, size: tuple[int, int], save):
        super().__init__(parent)
        self.resize(*size)
        self._save = save
        self._timer = QTimer(self, singleShot=True, interval=400)
        self._timer.timeout.connect(lambda: self._save(self.width(), self.height()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():  # nicht die Größe vor dem ersten Anzeigen speichern
            self._timer.start()


class WidgetGroup:
    """Mehrere Widgets gemeinsam ein- und ausblenden."""

    def __init__(self, *widgets):
        self.widgets = widgets

    def setVisible(self, visible: bool) -> None:
        for w in self.widgets:
            w.setVisible(visible)

    def isHidden(self) -> bool:
        return all(w.isHidden() for w in self.widgets)


class MainWindow(QMainWindow):
    def __init__(self, service: TimeService, enable_hotkey: bool = False, enable_tray: bool = False,
                 auto_features: bool = False, enable_calls: bool = False, enable_outlook: bool = False,
                 outlook_reader=read_appointments):
        super().__init__()
        self.svc = service
        self._quitting = False
        self._features_day = service.now().date()  # für die Neu-Sortierung der DevOps-Liste nach Datum
        self.tray = None  # wird weiter unten angelegt, refresh() läuft aber schon vorher
        self._integrated = enable_tray  # läuft als Tray-Programm: „Schließen“ beendet nicht von selbst
        self.day: date = service.now().date()
        self.sel_project: int | None = None
        self.sel_activity: int | None = None
        self._entries = []
        self._ticks = 0
        self.setWindowTitle(f"WorkPlanner  v{__version__}")
        self.setWindowIcon(app_icon())
        screen = QApplication.primaryScreen().availableGeometry()   # Standardgröße, auf kleinen Bildschirmen begrenzt
        self.resize(min(1650, screen.width()), min(950, screen.height()))
        self._geometry_saver = QTimer(self, singleShot=True, interval=500)  # Größe/Position kurz nach dem Ziehen merken
        self._geometry_saver.timeout.connect(self._save_geometry)
        self.svc.restore_window(self)
        self.setStyleSheet(STYLE)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.now_label = QLabel()  # aktuelle Uhrzeit oben rechts auf der Höhe der Reiter
        self.now_label.setStyleSheet("font-size:15px;font-weight:600;color:#2F5597;padding:0 14px")
        self.tabs.setCornerWidget(self.now_label, Qt.TopRightCorner)
        self.tabs.addTab(self._build_today(), "Heute")
        self.week = WeekPage(service)
        self.week.open_day.connect(self._open_day_from_week)
        self.report = ReportPage(service)
        self.master = MasterDataPage(service)
        self.tabs.addTab(self.week, "Woche")
        self.tabs.addTab(self.report, "Berichte")
        self.devops = DevOpsPage(service)
        self.devops.story_chosen.connect(self._start_story)
        self.devops.items_loaded.connect(self._tab_items_loaded)
        self.devops.projects_changed.connect(lambda: (self.master.reload(), self._master_changed()))
        self.tabs.addTab(self.devops, "DevOps")
        self._build_menu()
        self.master.changed.connect(self._master_changed)
        self.tabs.currentChanged.connect(self._tab_changed)

        self._shortcuts: list[QShortcut] = []
        self.svc.tick()
        self.now_label.setText(f"{self.svc.now():%H:%M:%S}")
        running = self.svc.current()
        if running and running.kind != PAUSE:
            self.sel_project, self.sel_activity = running.project_id, running.activity_id
        self._rebuild_tiles()
        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_second)
        self.timer.start(1000)
        self._auto_features = auto_features

        # DevOps-Features als Kacheln: sofort aus dem Zwischenspeicher, dann automatisch aktualisiert
        self.feed = FeatureFeed(self.svc, self)
        self.feed.loaded.connect(self._features_loaded)
        self.feed.failed.connect(lambda msg: self.features.set_status(f"⚠ {msg}"))
        self.features.refresh_requested.connect(self.feed.refresh)
        cached = self.svc.devops_features_cache()
        self.features.set_items(cached)
        self.features.set_status(self._feature_counts(cached) + " (zuletzt geladen)" if cached else "Noch nicht geladen.")
        self._feature_timer = QTimer(self, interval=15 * 60 * 1000)  # alle 15 Minuten aktualisieren
        self._feature_timer.timeout.connect(self.feed.refresh)
        if auto_features and self.svc.devops_enabled:
            QTimer.singleShot(1500, self.feed.refresh)
            self._feature_timer.start()

        # Outlook-Termine des angezeigten Tages (nur in der echten App: Outlook/COM wird im Hintergrund gelesen)
        self._manual_win: ManualWindow | None = None
        self._outlook_on = enable_outlook
        self._outlook_day: date | None = None
        self._outlook_items: list = []
        self.outlook_feed = OutlookFeed(self, reader=outlook_reader)
        self.outlook_feed.loaded.connect(self._outlook_loaded)
        self.outlook_feed.failed.connect(self._outlook_failed)
        self.outlook.refresh_requested.connect(self._outlook_reload)
        if enable_outlook:
            self._outlook_timer = QTimer(self, interval=10 * 60 * 1000)  # alle 10 Minuten aktualisieren
            self._outlook_timer.timeout.connect(self._outlook_reload)
            self._outlook_timer.start()
            QTimer.singleShot(800, self._sync_outlook)

        # Teams-Anrufe erkennen (über die Mikrofonnutzung von Windows) und nach dem Ende nachfragen
        self.calls = CallMonitor()
        self._call_dialog_open = False
        self.call_banner = CallBanner()
        if enable_calls:
            self._call_timer = QTimer(self, interval=5000)
            self._call_timer.timeout.connect(self._poll_call)
            self._call_timer.start()

        # Symbol im Tray (nur in der echten App, und nur wenn Windows einen Infobereich bietet)
        self.tray = TrayIcon(self) if enable_tray and QSystemTrayIcon.isSystemTrayAvailable() else None
        if self.tray:
            QApplication.instance().commitDataRequest.connect(lambda *_: setattr(self, "_quitting", True))

        # Globale Tastenkombination zum Minimieren/Öffnen (nur in der echten App, nicht in Tests)
        self.hotkey = GlobalHotkey(self.toggle_window)
        self.master.hotkey_apply = self._apply_hotkey if enable_hotkey else (lambda text: "")
        if enable_hotkey:
            error = self.hotkey.register(self.svc.hotkey)
            if error:
                self.master.hotkey_status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            else:
                self.master.show_hotkey_active(self.svc.hotkey)
        self.apply_devops()

    # --- Aufbau ----------------------------------------------------------------
    def _build_today(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        card = QFrame(objectName="card")
        left = QVBoxLayout(card)
        self.task_label = QLabel(objectName="task")
        self.note = NoteEdit(placeholder="Notiz zur laufenden Tätigkeit … (mehrere Zeilen möglich)")
        self.note.editingFinished.connect(self._note_edited)
        self.billable_cb = QCheckBox("verrechenbar")
        self.billable_cb.clicked.connect(self._billable_clicked)
        self.since_label = QLabel()
        self.since_label.setStyleSheet("color:#667")
        left.addWidget(self.task_label)
        noterow = QHBoxLayout()  # Notiz, Uhr und Knöpfe auf einer Höhe
        noterow.addWidget(self.note, 1)
        left.addLayout(noterow)
        row = QHBoxLayout()
        row.addWidget(self.billable_cb)
        row.addWidget(self.since_label, 1)
        self.time_btn = QPushButton("✎ Zeit ändern")
        self.time_btn.setToolTip("Startzeit oder bisher angefallene Zeit der laufenden Aufgabe anpassen")
        self.time_btn.clicked.connect(self._edit_running)
        row.addWidget(self.time_btn)
        left.addLayout(row)
        # Verknüpfung mit DevOps: sichtbar und unabhängig von der Notiz (die bleibt frei für die Beschreibung)
        self.devops_label = QLabel()
        self.devops_label.setStyleSheet("color:#2F5597;font-weight:600")
        self.unlink_btn = QPushButton("✕ lösen")
        self.unlink_btn.setToolTip("Verknüpfung mit DevOps entfernen (die Stunden werden dann nicht mehr übertragen)")
        self.unlink_btn.clicked.connect(self._unlink_devops)
        link_title = QLabel("🔗 DevOps:")
        drow = QHBoxLayout()
        drow.addWidget(link_title)
        drow.addWidget(self.devops_label, 1)
        drow.addWidget(self.unlink_btn)
        left.addLayout(drow)
        # Einzel-Widgets statt eines Containers (ein Container-Widget malte in der Karte einen weißen Block)
        self.devops_box = WidgetGroup(link_title, self.devops_label, self.unlink_btn)
        self.devops_box.setVisible(False)
        self.chips = QHBoxLayout()  # Tätigkeiten liegen im blauen Rahmen der Start-Karte
        left.addLayout(self.chips)
        self.timer_label = ClockLabel("00:00:00", objectName="timer")
        self.timer_label.setToolTip("Doppelklick: Start bzw. angefallene Zeit ändern")
        self.timer_label.doubleClicked.connect(self._edit_running)
        # Festbreitenschrift + feste Breite: die Uhr darf das Layout daneben nicht verschieben
        clock_font = QFont("Consolas")
        clock_font.setPixelSize(CLOCK_PX)
        clock_font.setWeight(QFont.DemiBold)
        self.timer_label.setFixedWidth(QFontMetrics(clock_font).horizontalAdvance("00:00:00") + 16)
        self.timer_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stop_btn = QPushButton("■  Stopp", objectName="stop")
        self.stop_btn.clicked.connect(lambda: self._guard(self.svc.stop))
        self.start_btn = QPushButton("▶  Start", objectName="start")
        self.start_btn.setToolTip("Zeit starten (Standardprojekt) – lässt sich später einem Projekt zuweisen")
        self.start_btn.clicked.connect(self._start_blank)
        noterow.addWidget(self.timer_label, 0, Qt.AlignVCenter)
        self.new_btn = QPushButton("＋  Neu", objectName="new")
        self.new_btn.setToolTip("Laufende Aufgabe beenden und sofort eine neue starten (Standardprojekt)")
        self.new_btn.clicked.connect(self._start_blank)
        for b in (self.start_btn, self.new_btn, self.stop_btn):
            noterow.addWidget(b, 0, Qt.AlignVCenter)
        lay.addWidget(card)

        left_box = QWidget()
        left = QVBoxLayout(left_box)
        left.setContentsMargins(0, 0, 0, 0)

        self.features = FeaturePanel(lambda fid: self.svc.project_color(self.svc.find_project(number=str(fid))),
                                     today=lambda: self.svc.now().date())
        self.features.feature_chosen.connect(self._start_devops_item)
        self.features.story_chosen.connect(self._start_devops_item)
        # Schnellauswahl: rechts, über die volle Höhe unter der Start-Karte
        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Schnellauswahl</b><br><span style='color:#667'>Strg+1 … Strg+9</span>"))
        self.tiles = QVBoxLayout()
        self.tiles.setSpacing(4)
        holder = QWidget()
        holder.setLayout(self.tiles)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        scroll.setMinimumWidth(150)
        side.addWidget(scroll, 1)
        side_box = QWidget()
        side_box.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        # Breite von DevOps-Features und Schnellauswahl per Maus verschiebbar; wird gespeichert
        self.body = QSplitter(Qt.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.outlook = OutlookPanel()   # Termine des angezeigten Tages; Klick = Eintrag
        self.outlook.appointment_chosen.connect(self._book_appointment)
        for w in (left_box, self.outlook, self.features, side_box):  # Outlook | DevOps-Features | Schnellauswahl
            self.body.addWidget(w)
        self.body.setStretchFactor(0, 1)
        for i in (1, 2, 3):
            self.body.setStretchFactor(i, 0)
        self._split_saver = QTimer(self, singleShot=True, interval=400)
        self._split_saver.timeout.connect(self._save_split)
        self.body.splitterMoved.connect(lambda *_: self._split_saver.start())
        self._split_restored = False
        lay.addWidget(self.body, 1)

        nav = QHBoxLayout()
        prev, nxt, today = QPushButton("◀"), QPushButton("▶"), QPushButton("Heute")
        prev.clicked.connect(lambda: self._go_day(-1))
        nxt.clicked.connect(lambda: self._go_day(1))
        today.clicked.connect(lambda: self._set_day(self.svc.now().date()))
        self.day_label = QLabel()
        self.day_label.setStyleSheet("font-size:16px;font-weight:600")
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-size:15px")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        cal = QPushButton("📅 Kalender")
        cal.setToolTip("Datum im Kalender auswählen")
        cal.clicked.connect(self._pick_date)
        for w in (prev, self.day_label, nxt, cal, today):
            nav.addWidget(w)
        nav.addStretch(1)
        self.end_label = QLabel()  # unter dem Soll: wann es voraussichtlich erreicht ist
        self.end_label.setStyleSheet("color:#2F5597")
        self.end_label.setAlignment(Qt.AlignRight)
        totals = QVBoxLayout()
        totals.setSpacing(0)
        totals.addWidget(self.total_label, 0, Qt.AlignRight)
        totals.addWidget(self.end_label, 0, Qt.AlignRight)
        nav.addLayout(totals)
        nav.addWidget(self.progress)
        left.addLayout(nav)

        self.table = QTableWidget(0, 8)
        self.check_header = CheckHeader(self.table)
        self.table.setHorizontalHeader(self.check_header)
        self.table.setHorizontalHeaderLabels(["      Start", "Ende", "Dauer", "Verr.", "Projekt", "Tätigkeit", "DevOps", "Notiz"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # mehrere mit Strg/Umschalt
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Interactive)   # Tätigkeit: feste Breite, Text bricht um
        hh.resizeSection(5, 110)
        hh.setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setWordWrap(True)  # lange Notizen werden umgebrochen, die Zeile wird entsprechend höher
        self.table.setTextElideMode(Qt.ElideNone)
        hh.sectionResized.connect(lambda *_: self.table.resizeRowsToContents())
        self._row_fit = QTimer(self, singleShot=True, interval=30)  # Zeilenhöhe folgt der Breite (Fenster, Trenner)
        self._row_fit.timeout.connect(self.table.resizeRowsToContents)
        self.table.viewport().installEventFilter(self)
        # Kästchen vor jedem Eintrag (= markiert) und ganz oben „Alle markieren“; Kästchen und Markierung hängen zusammen
        self._syncing = False
        self.table.itemChanged.connect(self._entry_checked)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._sync_checks())
        self.check_header.toggled.connect(self._check_all)
        self.table.doubleClicked.connect(lambda _: self._edit())
        QShortcut(QKeySequence(Qt.Key_Delete), self.table, activated=self._delete,
                  context=Qt.WidgetShortcut)
        left.addWidget(self.table, 1)

        # zwei Zeilen, damit die Tabelle schmal werden darf und die Schnellauswahl mehr Platz bekommt
        self.pause_btn = QPushButton()
        self.pause_btn.clicked.connect(self._toggle_pause)
        rows = (QHBoxLayout(), QHBoxLayout())
        for row, items in zip(rows, ((("Bearbeiten", self._edit), ("Eintrag hinzufügen", self._add),
                                      ("Löschen", self._delete)),
                                     (("Outlook-Termine importieren …", self._import_outlook),
                                      ("Notiz → DevOps-Task …", self._note_to_task)))):
            for text, fn in items:
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, f=fn: f())
                row.addWidget(b)
                if fn == self._note_to_task:
                    self.note_task_btn = b
            row.addStretch(1)
            left.addLayout(row)
        rows[1].addWidget(self.pause_btn)
        return page

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # bis zum eigentlichen Löschen nicht als Geisterbild sichtbar lassen
                item.widget().deleteLater()

    def _rebuild_tiles(self) -> None:
        self._clear(self.tiles)
        for s in self._shortcuts:
            s.setEnabled(False)
            s.deleteLater()
        self._shortcuts = []
        favorites = self.svc.projects(favorites_only=True)
        metrics = QFontMetrics(self.font())
        number_width = max((metrics.horizontalAdvance(p["number"]) for p in favorites if p["number"]),
                           default=0)
        number_width = number_width + 14 if number_width else 0   # Abstand zum Namen
        for i, p in enumerate(favorites, 1):
            b = TileButton(p["name"], str(i) if i <= 9 else "", number=p["number"] or "",
                           number_width=number_width)
            b.setCheckable(True)
            b.setProperty("pid", p["id"])
            b.setToolTip(f"Strg+{i}" if i <= 9 else "")
            b.setStyleSheet(f"QPushButton#tile {{ border-left: 6px solid {p['color']}; }}")
            b.clicked.connect(lambda _=False, pid=p["id"]: self._pick_project(pid))
            self.tiles.addWidget(b)
            if i <= 9:
                sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
                sc.activated.connect(lambda pid=p["id"]: self._pick_project(pid))
                self._shortcuts.append(sc)
        if not self.tiles.count():
            hint = QLabel("Noch keine Projekte.\nUnter Einstellungen → Stammdaten anlegen\n(Favoriten erscheinen hier).")
            hint.setStyleSheet("color:#7b8798")
            hint.setWordWrap(True)
            self.tiles.addWidget(hint)
        self.tiles.addStretch(1)
        self._rebuild_chips()

    def _rebuild_chips(self) -> None:
        self._clear(self.chips)
        self.chips.addWidget(QLabel("Tätigkeit:"))
        for a in self.svc.activities_for(self.sel_project):
            b = QPushButton(a["name"], objectName="chip")
            b.setCheckable(True)
            b.setChecked(a["id"] == self.sel_activity)
            b.clicked.connect(lambda _=False, aid=a["id"]: self._pick_activity(aid))
            self.chips.addWidget(b)
        self.chips.addStretch(1)

    # --- Aktionen --------------------------------------------------------------------
    def _guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except TimelineError as ex:
            QMessageBox.warning(self, "Nicht möglich", str(ex))
        self._set_day(self.svc.now().date()) if self.day != self.svc.now().date() else self.refresh()

    def _start_blank(self) -> None:
        """Zeit läuft auf dem Standardprojekt; die Zuordnung kann später erfolgen."""
        self.sel_project = self.svc.default_project_id()
        self.sel_activity = None
        self.note.clear()
        self._guard(self.svc.start_task, self.sel_project, None, "")
        self._rebuild_chips()

    def _unassigned_running(self):
        run = self.svc.current()
        if (run and run.kind != PAUSE and run.activity_id is None and not run.note.strip() and run.devops_id is None
                and run.project_id in (None, self.svc.default_project_id(create=False))):
            return run
        return None

    def _pick_project(self, pid: int) -> None:
        self.sel_project = pid
        valid = {a["id"] for a in self.svc.activities_for(pid)}
        if self.sel_activity not in valid:
            self.sel_activity = None
        run = self._unassigned_running()
        if run:  # bereits laufende Zeit bekommt das Projekt, kein neuer Eintrag
            self._guard(self.svc.edit_entry, run.id,
                        {"project_id": pid, "activity_id": self.sel_activity})
        else:
            self.note.clear()
            self._guard(self.svc.start_task, pid, self.sel_activity, "")
        self._rebuild_chips()

    @staticmethod
    def _feature_counts(items: list[dict]) -> str:
        stories = sum(1 for i in items if i.get("type") == "story")
        return f"{len(items) - stories} Features, {stories} Stories"

    def _features_loaded(self, items: list[dict]) -> None:
        self.svc.set_devops_features_cache(items)
        self.features.set_items(items)
        self.features.set_status(f"{self._feature_counts(items)} · {self.svc.now():%H:%M}")
        self._mark_running_feature()

    def _tab_items_loaded(self, items, view: str) -> None:
        """Hat der DevOps-Tab Features und Stories geladen, aktualisiert das die Kacheln gleich mit."""
        if view == "both" and items:
            self._features_loaded(to_cache(items))

    def _start_devops_item(self, item: dict) -> None:
        """Ein Klick auf ein Feature oder eine Story startet die Zeit. Das **Feature** ist das Projekt (bei
        Bedarf automatisch angelegt, Nummer = Feature-ID). Eine Story wird darunter verknüpft: Sie steht auf
        der Karte in der DevOps-Zeile, die Notiz bleibt frei für die Beschreibung, und die Stunden gehen über
        die Verknüpfung auf die Story in DevOps."""
        if item.get("type", "feature") == "story":
            if item.get("parent_id"):
                pid = self._devops_project(item["parent_id"], item.get("parent_title", ""))
            else:  # Story ohne Feature: auf das zuletzt gewählte bzw. das Standardprojekt
                pid = self.sel_project or self.svc.default_project_id()
        else:
            pid = self._devops_project(item["id"], item["title"])
        self._start_linked(item["id"], item["title"], pid)

    def _mark_running_feature(self) -> None:
        run = self.svc.current()
        linked = (run.devops_id or item_id_from_note(run.note)) if run and run.kind != PAUSE else None
        self.features.mark_running(linked)

    def _devops_project(self, item_id: int, title: str) -> int:
        """Das Projekt zum Feature bzw. zur Story (bei Bedarf automatisch angelegt) – es steht dann wie jedes
        Projekt auf der Karte und in der Tabelle."""
        pid, created = self.svc.ensure_devops_project(item_id, title)
        if created:
            self.master.reload()
            self._master_changed()
        return pid

    def _start_linked(self, item_id: int, title: str, pid: int) -> None:
        """Startet die Zeit für ein DevOps-Item. Die Verknüpfung ist ein eigenes Feld, die Notiz bleibt
        leer und frei für die Beschreibung. Läuft gerade unbeschriebene Zeit, bekommt sie die Verknüpfung."""
        self.sel_project = pid
        self.svc.remember_devops_title(item_id, title)
        run = self._unassigned_running()
        if run:
            self._guard(self.svc.edit_entry, run.id, {"devops_id": item_id, "project_id": pid})
        else:
            self.note.clear()
            self._guard(self.svc.start_task, pid, None, "", item_id)
        self._rebuild_chips()

    def _unlink_devops(self) -> None:
        run = self.svc.current()
        if run and run.devops_id:
            self._guard(self.svc.edit_entry, run.id, {"devops_id": None})

    def _start_story(self, item: dict) -> None:
        """Startet die Zeit für ein im DevOps-Tab gewähltes Feature bzw. eine Story (wie bei den Kacheln)."""
        self._start_devops_item(item)
        self.tabs.setCurrentIndex(0)

    def _pick_activity(self, aid: int) -> None:
        self.sel_activity = None if aid == self.sel_activity else aid
        run = self.svc.current()
        if run and run.kind != PAUSE and self.sel_activity is not None:
            if run.activity_id is None and not run.note.strip():
                self._guard(self.svc.edit_entry, run.id, {"activity_id": self.sel_activity})
            else:
                self.note.clear()
                self._guard(self.svc.start_task, run.project_id, self.sel_activity, "")
        self._rebuild_chips()
        self.refresh()

    def _edit_running(self) -> None:
        run = self.svc.current()
        if run and RunningTimeDialog(self.svc, run, self).exec():
            self._set_day(self.svc.now().date())

    def _billable_clicked(self, checked: bool) -> None:
        run = self.svc.current()
        if run and run.kind != PAUSE:
            self.svc.set_running_billable(checked)
            self.refresh()

    def _note_edited(self) -> None:
        run = self.svc.current()
        if run and run.kind != PAUSE:
            self.svc.set_running_note(self.note.toPlainText())
            self.refresh()

    def _entry_checked(self, item) -> None:
        """Kästchen angeklickt: Zeile markieren bzw. abwählen (andere Markierungen bleiben)."""
        if self._syncing or item.column() != 0:
            return
        idx = self.table.model().index(item.row(), 0)
        flag = QItemSelectionModel.Select if item.checkState() == Qt.Checked else QItemSelectionModel.Deselect
        self.table.selectionModel().select(idx, flag | QItemSelectionModel.Rows)

    def _check_all(self, on: bool) -> None:
        if on:
            self.table.selectAll()
        else:
            self.table.clearSelection()

    def _sync_checks(self) -> None:
        """Kästchen folgen der Markierung (auch bei Klick auf die Zeile, Strg/Umschalt oder Strg+A)."""
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        self._syncing = True
        try:
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 0)
                if it:
                    it.setCheckState(Qt.Checked if r in selected else Qt.Unchecked)
        finally:
            self._syncing = False
        n = self.table.rowCount()
        self.check_header.set_state(Qt.Unchecked if not selected else Qt.Checked if len(selected) == n
                                    else Qt.PartiallyChecked)

    def _selected_entries(self) -> list:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        ids = [self.table.item(r, 0).data(Qt.UserRole) for r in rows]
        return [e for e in self._entries if e.id in ids]

    def _selected_entry(self):
        chosen = self._selected_entries()
        return chosen[0] if chosen else None

    def _edit(self) -> None:
        if len(self._selected_entries()) > 1:
            QMessageBox.information(self, "Bearbeiten", "Bitte zum Bearbeiten genau einen Eintrag markieren.")
            return
        e = self._selected_entry()
        if e and EntryDialog(self.svc, self.day, e, parent=self).exec():
            self.refresh()

    def _add(self) -> None:
        last = self._entries[-1] if self._entries else None
        start = last.end if last and last.end else None
        if start is None:
            start = datetime.combine(self.day, datetime.min.time()).replace(hour=8) if not last else None
        if start is None:  # laufender Eintrag am Ende: vor dem laufenden einfügen
            start = last.start
        if EntryDialog(self.svc, self.day, None, start, self).exec():
            self.refresh()

    def _apply_hotkey(self, text: str) -> str:
        """Meldet eine neue Kombination an; bei einem Fehler bleibt die bisherige aktiv."""
        error = self.hotkey.register(text)
        if error:
            self.hotkey.register(self.svc.hotkey)  # alte Kombination wiederherstellen
        return error

    def toggle_window(self) -> None:
        """Vorn und aktiv -> minimieren, sonst wiederherstellen und nach vorn holen."""
        if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            self.hide() if self._tray_mode() else self.showMinimized()
            return
        self.show_window()

    def show_window(self) -> None:
        """Fenster wiederherstellen und nach vorn holen (auch aus dem Tray)."""
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        if sys.platform == "win32":  # Windows lässt das Vordergrundfenster sonst nur blinken
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))

    def _tray_mode(self) -> bool:
        return self.tray is not None and self.svc.tray_mode

    def tray_status(self) -> tuple[str, bool]:
        run = self.svc.current()
        if not run:
            return "Keine Aufgabe läuft", False
        return f"{self.task_label.text()} – {self.timer_label.text()}", True

    def tray_toggle_task(self) -> None:
        if self.svc.current():
            self._guard(self.svc.stop)
        else:
            self._start_blank()

    def quit_app(self) -> None:
        """Das Programm wirklich beenden (nicht nur ins Tray). Eine laufende Aufgabe läuft weiter."""
        self._quitting = True
        self.close()

    def _build_menu(self) -> None:
        """Menüleiste: Datei → Beenden; Einstellungen → Stammdaten (öffnet sie in einem eigenen Fenster)."""
        bar = self.menuBar()
        file_menu = bar.addMenu("&Datei")
        quit_action = file_menu.addAction("&Beenden")
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.quit_app)
        settings_menu = bar.addMenu("&Einstellungen")
        settings_action = settings_menu.addAction("&Einstellungen …  (Tastenkombination, Start und Tray, …)")
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(lambda: self.show_master(1))
        master_action = settings_menu.addAction("&Stammdaten …  (Projekte, Tätigkeiten)")
        master_action.triggered.connect(lambda: self.show_master(0))
        help_menu = bar.addMenu("&Hilfe")
        manual_action = help_menu.addAction("&Handbuch")
        manual_action.setShortcut(QKeySequence("F1"))
        manual_action.triggered.connect(lambda: self.open_manual(self._help_chapter()))
        help_menu.addAction("Handbuch im &PDF-Programm öffnen").triggered.connect(self.open_manual_external)
        help_menu.addSeparator()
        self.demo_add_action = help_menu.addAction("&Beispieldaten einfügen …")
        self.demo_add_action.triggered.connect(self.add_demo_data)
        self.demo_remove_action = help_menu.addAction("Beispieldaten &entfernen …")
        self.demo_remove_action.triggered.connect(self.remove_demo_data)
        help_menu.aboutToShow.connect(self._update_demo_actions)
        help_menu.addSeparator()
        help_menu.addAction("&Lizenz …").triggered.connect(lambda: LicenseDialog(self).exec())
        help_menu.addAction("&Über WorkPlanner / Updates …").triggered.connect(self.show_about)
        self.master_dialog = _SizedDialog(self, self.svc.master_size(), self.svc.set_master_size)
        self.master_dialog.setWindowTitle("Stammdaten und Einstellungen")
        box = QVBoxLayout(self.master_dialog)
        box.addWidget(self.master)
        QShortcut(QKeySequence("F1"), self.master_dialog, activated=lambda: self.open_manual("11"))

    # --- Beispieldaten ------------------------------------------------------------------------
    def _update_demo_actions(self) -> None:
        present = demo_data.has_demo(self.svc)
        self.demo_add_action.setEnabled(not present)
        self.demo_remove_action.setEnabled(present)

    def offer_demo(self) -> None:
        """Beim allerersten Start (leere Datenbank): einmal anbieten, mit Beispieldaten zu beginnen."""
        if not demo_data.needs_offer(self.svc):
            return
        demo_data.mark_offered(self.svc)  # nur einmal fragen, egal wie die Antwort ausfällt
        box = QMessageBox(QMessageBox.Question, "Willkommen bei WorkPlanner",
                          "Soll ich ein paar <b>Beispieldaten</b> einfügen (Projekte, Tätigkeiten und einen "
                          "Beispieltag), damit Sie sich alles in Ruhe ansehen können?<br><br>"
                          "Sie lassen sich jederzeit unter <b>Hilfe → Beispieldaten entfernen</b> wieder löschen; "
                          "eigene Daten werden dabei nicht angefasst.", QMessageBox.NoButton, self)
        yes = box.addButton("Beispieldaten einfügen", QMessageBox.AcceptRole)
        box.addButton("Leer starten", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.add_demo_data(announce=False)

    def add_demo_data(self, announce: bool = True) -> None:
        try:
            day = demo_data.add_demo(self.svc)
        except ValueError as ex:
            QMessageBox.information(self, "Beispieldaten", str(ex))
            return
        if day is not None:
            self.day = day
        self.tabs.setCurrentIndex(0)
        self._master_changed()
        if announce:
            QMessageBox.information(
                self, "Beispieldaten",
                "Die Beispieldaten sind eingefügt: Projekte, Tätigkeiten"
                + (f" und ein Beispieltag ({day:%d.%m.%Y}) auf der Seite „Heute“." if day else
                   " (für einen Beispieltag war in den letzten zwei Wochen kein freier Tag)."))

    def remove_demo_data(self) -> None:
        if not demo_data.has_demo(self.svc):
            QMessageBox.information(self, "Beispieldaten", "Es sind keine Beispieldaten vorhanden.")
            return
        if QMessageBox.question(self, "Beispieldaten entfernen",
                                "Die Beispiel-Projekte, -Tätigkeiten und den Beispieltag jetzt entfernen?\n"
                                "Eigene Daten bleiben unberührt.") != QMessageBox.Yes:
            return
        result = demo_data.remove_demo(self.svc)
        self._master_changed()
        extra = (f"\n{result['archived']} Beispiel-Projekt(e) bzw. -Tätigkeit(en) werden von eigenen Einträgen genutzt "
                 "und wurden nur archiviert." if result["archived"] else "")
        QMessageBox.information(self, "Beispieldaten", f"Entfernt: {result['entries']} Einträge, "
                                                       f"{result['projects']} Projekte, {result['activities']} Tätigkeiten."
                                + extra)

    def show_about(self) -> None:
        """Hilfe → Über WorkPlanner / Updates: Updates werden nur hier und nur auf Klick gesucht und installiert."""
        AboutDialog(self, install=self._install_update if self._integrated else None).exec()

    def _install_update(self, path) -> None:
        """Installer starten und WorkPlanner beenden; der Installer ersetzt die Dateien und startet das Programm neu."""
        from .. import updater
        updater.launch_installer(path)
        self.quit_app()

    def _help_chapter(self) -> str | None:
        """Kapitel des Handbuchs zu dem, womit man gerade arbeitet (F1)."""
        page = self.tabs.currentWidget()
        if page is self.week:
            return "9"
        if page is self.report:
            return "10"
        if page is self.devops:
            return "8"
        focus = QApplication.focusWidget()
        for panel, chapter in ((self.outlook, "6"), (self.features, "8"), (self.table, "5")):
            if focus is not None and (focus is panel or panel.isAncestorOf(focus)):
                return chapter
        return "4"

    def open_manual(self, chapter: str | None = None) -> None:
        """Hilfe → Handbuch: das PDF im eigenen Fenster; mit F1 springt es zum passenden Kapitel."""
        path = manual_path()
        if path is None:
            QMessageBox.information(self, "Handbuch", "Das Handbuch (PDF) liegt bei dieser Installation nicht bei.")
            return
        if self._manual_win is None:
            self._manual_win = ManualWindow(path, self.svc.manual_geometry(), self.svc.set_manual_geometry)
        self._manual_win.show()
        self._manual_win.raise_()
        self._manual_win.activateWindow()
        self._manual_win.show_chapter(chapter)

    def open_manual_external(self) -> None:
        """Hilfe → Handbuch im PDF-Programm öffnen (zum Drucken oder Weitergeben)."""
        path = manual_path()
        if path is None:
            QMessageBox.information(self, "Handbuch", "Das Handbuch (PDF) liegt bei dieser Installation nicht bei.")
            return
        try:
            os.startfile(str(path))  # noqa: S606 – öffnet mit dem unter Windows eingestellten PDF-Programm
        except OSError as ex:
            QMessageBox.warning(self, "Handbuch", f"Das Handbuch konnte nicht geöffnet werden:\n{ex}")

    def show_master(self, section: int = 0) -> None:
        """Öffnet das Fenster auf dem Reiter 0 = Stammdaten oder 1 = Einstellungen."""
        self.master.reload()
        self.master.sections.setCurrentIndex(section)
        self.master_dialog.show()
        self.master_dialog.raise_()
        self.master_dialog.activateWindow()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.table.viewport():
            self._row_fit.start()
        return super().eventFilter(obj, event)

    # --- Outlook-Termine ---------------------------------------------------------------
    def _outlook_reload(self) -> None:
        if self._outlook_on:
            self._outlook_day = self.day
            self.outlook.show_loading()
            self.outlook_feed.load(self.day)

    def _sync_outlook(self) -> None:
        """Beim Wechsel des Tages neu lesen, sonst nur die Kacheln auffrischen (Uhrzeit, Übernommenes)."""
        if not getattr(self, "_outlook_on", False):
            return
        if self.day != self._outlook_day:
            self._outlook_reload()
        else:
            self.outlook.set_items(self._outlook_items, self.svc.outlook_imported(), self.svc.now())

    def _outlook_loaded(self, day, appts) -> None:
        if day != self.day:  # inzwischen anderer Tag gewählt: neu lesen
            self._outlook_reload()
            return
        self._outlook_items = appts
        self.outlook.set_items(appts, self.svc.outlook_imported(), self.svc.now())

    def _outlook_failed(self, day, text: str) -> None:
        if day == self.day:
            self._outlook_items = []
            self.outlook.show_error(text)

    def _book_appointment(self, appt) -> None:
        """Ein Klick auf einen Termin: Eintrag mit Projekt/Tätigkeit der Termin-Voreinstellung (wie beim Import)."""
        pid, aid = self.svc.outlook_defaults()
        try:
            plan = self.svc.preview_import([appt], pid, aid)
            gone = [o for old, new in plan.values() for o in removed_entries(old, new)]
            if gone and QMessageBox.question(
                    self, "Termin eintragen",
                    f"„{appt.subject}“ überdeckt {len(gone)} bestehende(n) Eintrag/Einträge vollständig – "
                    "sie entfallen.\nTrotzdem eintragen?") != QMessageBox.Yes:
                return
            self.svc.apply_import([appt], pid, aid)
        except TimelineError as ex:
            QMessageBox.warning(self, "Termin eintragen", str(ex))
            return
        self.refresh()

    def _save_geometry(self) -> None:
        self.svc.save_window(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._geometry_saver.start()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible():
            self._geometry_saver.start()

    def _save_split(self) -> None:
        self.svc.set_split_widths(self.body.sizes()[1:])

    def showEvent(self, event):
        super().showEvent(event)
        if not self._split_restored:  # erst jetzt ist die Gesamtbreite bekannt
            self._split_restored = True
            QTimer.singleShot(0, self._restore_split)  # nach dem ersten Layout, wenn die Breite stimmt

    def _restore_split(self) -> None:
        outlook, features, tiles = self.svc.split_widths()
        self.body.setSizes([max(300, self.body.width() - outlook - features - tiles), outlook, features, tiles])

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized() and self._tray_mode():
            QTimer.singleShot(0, self.hide)  # Minimieren-Knopf: ins Tray statt in die Taskleiste

    def closeEvent(self, event):
        if self._tray_mode() and not self._quitting:
            event.ignore()
            self.hide()
            self.tray.hint_once()
            return
        self._save_geometry()
        if self._manual_win is not None:
            self._manual_win.close()
        self.hotkey.unregister()
        self.call_banner.close()
        if self.tray:
            self.tray.icon.hide()
        super().closeEvent(event)
        if self._integrated:
            QApplication.quit()

    def _note_to_task(self) -> None:
        chosen = self._selected_entries()
        if not chosen:
            QMessageBox.information(self, "DevOps-Task", "Bitte zuerst einen oder mehrere Einträge markieren, "
                                                         "deren Notiz als Task nach DevOps soll.")
            return
        NoteTaskDialog(self.svc, chosen, self).exec()
        self.refresh()

    def show_db_warning(self) -> None:
        """Beim Start: Hinweis, wenn die Datenbank zu groß geworden ist (mit Möglichkeit zum Komprimieren)."""
        text = self.svc.db_size_warning()
        if not text:
            return
        if not self.isVisible():  # Start im Tray: nur ein Hinweis am Symbol, das Fenster bleibt zu
            if self.tray:
                self.tray.icon.showMessage("WorkPlanner: Datenbank ist groß",
                                           text.splitlines()[0] + " Details im Fenster.", QSystemTrayIcon.Warning, 8000)
            return
        box = QMessageBox(QMessageBox.Warning, "Datenbank ist groß", text, QMessageBox.NoButton, self)
        compress = box.addButton("Komprimieren", QMessageBox.AcceptRole)
        box.addButton("OK", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is compress:
            before = self.svc.db.size_bytes()
            self.svc.db.vacuum()
            after = self.svc.db.size_bytes()
            QMessageBox.information(self, "Datenbank", f"Komprimiert: {before / 1024 / 1024:.1f} MB → "
                                                       f"{after / 1024 / 1024:.1f} MB.")

    def _poll_call(self) -> None:
        if not self.svc.call_monitor:
            self.call_banner.hide()
            self.calls = CallMonitor()  # ein beim Ausschalten laufender Anruf soll später nicht nachträglich fragen
            return
        call = self.calls.poll()
        if self.calls.active:
            self.call_banner.show_call(self.calls.since, self.svc.now())
        else:
            self.call_banner.hide()
        if call is not None:
            self._ask_call(call)

    def _ask_call(self, call) -> None:
        if self._call_dialog_open:
            return
        self._call_dialog_open = True
        try:
            if CallDialog(self.svc, call, self).exec():
                self.refresh()
        finally:
            self._call_dialog_open = False

    def _import_outlook(self) -> None:
        if OutlookImportDialog(self.svc, self.day, self).exec():
            self.refresh()

    def _delete(self) -> None:
        chosen = self._selected_entries()
        if not chosen:
            return
        if len(chosen) == 1:
            text = "Pause löschen?" if chosen[0].kind == PAUSE else \
                "Eintrag löschen? Alle Folgeeinträge rücken entsprechend nach vorn."
        else:
            text = (f"{len(chosen)} markierte Einträge löschen? "
                    "Alle Folgeeinträge rücken entsprechend nach vorn.")
        if QMessageBox.question(self, "Löschen", text) == QMessageBox.Yes:
            self._guard(self.svc.delete_entries, [e.id for e in chosen])

    def _toggle_pause(self) -> None:
        if self.svc.pause_disabled(self.day):
            self._guard(self.svc.restore_pause, self.day)
        else:
            self._guard(self.svc.remove_pause, self.day)

    def _pick_date(self) -> None:
        dlg = CalendarDialog(self.day, self)
        if dlg.exec():
            self._set_day(dlg.selected())

    def _open_day_from_week(self, day: date) -> None:
        """Doppelklick in der Wochenliste: den Tag in „Heute“ öffnen (dort lässt sich bearbeiten)."""
        self._set_day(day)
        self.tabs.setCurrentIndex(0)

    def _go_day(self, delta: int) -> None:
        self._set_day(self.day + timedelta(days=delta))

    def _set_day(self, d: date) -> None:
        self.day = d
        self.refresh()

    def apply_devops(self) -> None:
        """Alles zu DevOps ein- bzw. ausblenden: Reiter, Features auf „Heute“, Verknüpfungszeile, Spalten, Knöpfe."""
        on = self.svc.devops_enabled
        self.tabs.setTabVisible(self.tabs.indexOf(self.devops), on)
        self.features.setVisible(on)
        self.table.setColumnHidden(6, not on)
        self.week.entries.setColumnHidden(6, not on)
        self.note_task_btn.setVisible(on)
        self.report.apply_devops()
        if on:
            if self._auto_features and not self._feature_timer.isActive():
                self.feed.refresh()
                self._feature_timer.start()
        else:
            self._feature_timer.stop()
            self.devops_box.setVisible(False)

    def _master_changed(self) -> None:
        self.apply_devops()
        self.report.refresh_excel_button()
        self.features.set_items(self.svc.devops_features_cache())  # Projektfarben können sich geändert haben
        self._rebuild_tiles()
        self.report.reload_projects()
        self.refresh()

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is self.week:
            self.week.refresh()
        elif self.tabs.widget(idx) is self.report:
            self.report._update()

    def _on_second(self) -> None:
        self._ticks += 1
        today = self.svc.now().date()
        if today != self._features_day:  # neuer Tag (evtl. neue Woche): „diese Woche“ neu bestimmen
            self._features_day = today
            self.features.set_items(self.svc.devops_features_cache())
            self._mark_running_feature()
        if self._ticks % 5 == 0 and self.svc.tick():
            self.refresh()
            return
        self._update_live()

    # --- Anzeige -----------------------------------------------------------------------
    def refresh(self) -> None:
        now = self.svc.now()
        self._entries = self.svc.day_entries(self.day)
        weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        self.day_label.setText(f"{weekdays[self.day.weekday()]} {self.day:%d.%m.%Y}")

        keep = {e.id for e in self._selected_entries()}   # markierte Einträge bleiben nach dem Neuaufbau markiert
        self._syncing = True
        self.table.setRowCount(len(self._entries))
        windows = self.svc.lunch_windows(self._entries)
        for r, e in enumerate(self._entries):
            lunch = self.svc.lunch_overlap(e, windows[e.start.date()], now)
            vals = [fmt_time(e.start), fmt_time(e.end), fmt_duration(e.duration(now) - lunch),
                    "✓" if e.billable and e.kind != PAUSE else "",
                    "Pause" if e.kind == PAUSE else (self.svc.project_display(e.project_id) or "–"),
                    self.svc.activity_name(e.activity_id), (f"#{e.devops_id}" + (f" → Task #{e.devops_task_id}" if e.devops_task_id else "")) if e.devops_id else "",
                    note_one_line(e.note)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 7 and e.note:
                    it.setToolTip(e.note)
                if c == 6 and e.devops_id:
                    it.setToolTip(f"#{e.devops_id} {self.svc.devops_title(e.devops_id)}".strip())
                if c == 2 and lunch:
                    it.setToolTip(f"{fmt_duration(e.duration(now))} brutto, davon {fmt_duration(lunch)} "
                                  "Mittagspause (wird abgezogen)")
                if c == 3:
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    it.setData(Qt.UserRole, e.id)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Unchecked)
                if e.kind == PAUSE:
                    it.setForeground(QColor("#888"))
                elif e.running:
                    it.setForeground(QColor("#1b7f3b"))
                self.table.setItem(r, c, it)
        self._syncing = False
        self.table.resizeRowsToContents()
        self.table.clearSelection()
        for r, e in enumerate(self._entries):
            if e.id in keep:
                self.table.selectionModel().select(self.table.model().index(r, 0),
                                                   QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self._sync_checks()
        self.pause_btn.setText("Mittagspause wieder abziehen" if self.svc.pause_disabled(self.day)
                               else "Mittagspause für diesen Tag nicht abziehen")

        run = self.svc.current()
        for b in self._tile_buttons():
            b.setChecked(bool(run and run.kind != PAUSE and b.property("pid") == run.project_id))
        if run is None:
            self.task_label.setText("Keine Aufgabe läuft")
            self.since_label.setText("Auf Start klicken (bucht aufs Standardprojekt) oder unten ein Projekt wählen.")
            self.note.setEnabled(False)
            self.note.clear()
            self.billable_cb.setEnabled(False)
            self.billable_cb.setChecked(False)
        elif run.kind == PAUSE:
            self.task_label.setText("Pause")
            self.since_label.setText(f"seit {fmt_time(run.start)} – danach läuft die vorherige Aufgabe weiter")
            self.note.setEnabled(False)
            self.note.clear()
            self.billable_cb.setEnabled(False)
            self.billable_cb.setChecked(False)
        else:
            act = self.svc.activity_name(run.activity_id)
            proj = self.svc.project_display(run.project_id)
            if not proj and not act:
                self.task_label.setText("Ohne Aufgabe")
            else:
                self.task_label.setText((proj or "Ohne Projekt") + (f"  ›  {act}" if act else ""))
            self.since_label.setText(f"seit {fmt_time(run.start)}")
            self.note.setEnabled(True)
            self.billable_cb.setEnabled(True)
            self.billable_cb.setChecked(run.billable)
            if not self.note.hasFocus():
                self.note.set_text(run.note)
        self._mark_running_feature()
        self._sync_outlook()
        linked = run.devops_id if run and run.kind != PAUSE else None
        # Steht das Feature schon als Projekt oben, ist die Zeile überflüssig (nur bei Stories o. Ä. nötig)
        self.devops_box.setVisible(self.svc.devops_enabled and bool(linked)
                                   and self.svc.project_number(run.project_id) != str(linked))
        if linked:
            self.devops_label.setText(f"#{linked} {self.svc.devops_title(linked)}".strip())
        self.stop_btn.setVisible(run is not None)
        self.time_btn.setVisible(run is not None)
        self.new_btn.setVisible(run is not None)
        self.start_btn.setVisible(run is None)
        self._update_live()

    def _tile_buttons(self):
        return [self.tiles.itemAt(i).widget() for i in range(self.tiles.count())
                if isinstance(self.tiles.itemAt(i).widget(), QPushButton)]

    def _update_target_end(self, now: datetime, worked, target) -> None:
        """„Soll-Ende“ unter dem Soll; nur für heute sinnvoll."""
        if self.day != now.date() or not target:
            self.end_label.setText("")
            return
        end = self.svc.target_end(self._entries, now)
        if end is None:
            self.end_label.setText(f"Soll erreicht (+{fmt_duration(worked - target)} h)")
            return
        when = f"{end:%H:%M}" + (" (nächster Tag)" if end.date() != now.date() else "")
        hint = "" if self.svc.current() else " <span style='color:#667'>(wenn du jetzt startest)</span>"
        self.end_label.setText(f"Soll-Ende ca. <b>{when} Uhr</b>{hint}")

    def _update_live(self) -> None:
        now = self.svc.now()
        self.now_label.setText(f"{now:%H:%M:%S}")
        run = self.svc.current()
        if run:
            secs = int((now - run.start).total_seconds())
            self.timer_label.setText(f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
        else:
            self.timer_label.setText("00:00:00")
        worked = self.svc.work_total(self._entries, now)
        lunch = self.svc.lunch_total(self._entries, now)
        target = self.svc.daily_target
        pause_note = (f" <span style='color:#667'>(Pause −{fmt_duration(lunch)} abgezogen)</span>" if lunch else "")
        self.total_label.setText(f"Tag: <b>{fmt_duration(worked)} h</b>{pause_note}  /  Soll {fmt_duration(target)} h")
        pct = int(min(100, worked / target * 100)) if target else 0
        self.progress.setValue(pct)
        self._update_target_end(now, worked, target)
        if self.tray:
            self.tray.set_tooltip(f"WorkPlanner – {self.task_label.text()}  {self.timer_label.text()}"
                                  if run else "WorkPlanner – keine Aufgabe läuft")
        # Laufende Dauer in der Tabelle
        for r, e in enumerate(self._entries):
            if e.running and self.table.item(r, 2):
                self.table.item(r, 2).setText(fmt_duration(self.svc.net_duration(e, now)))
