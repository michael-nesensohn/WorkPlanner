"""Stunden in den Excel-Stundenzettel eintragen: Zeitraum wählen, Vorschau prüfen, eintragen."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QMessageBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..excel_timesheet import (DayHours, ExcelError, ExcelWorkbook, Plan, aggregate, apply_plan, plan_all,
                               read_sheet_view)
from ..service import TimeService
from .background import BackgroundRunner
from .sheet_preview import SheetPreview


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class ExcelExportDialog(QDialog):
    """Excel läuft im Hintergrund (siehe background.py: der Thread kennt den Dialog nicht)."""

    def __init__(self, service: TimeService, parent=None, workbook_factory=ExcelWorkbook, view_loader=read_sheet_view):
        super().__init__(parent)
        self.svc, self._factory, self._view_loader = service, workbook_factory, view_loader
        self._items: list[DayHours] = []
        self._plan: Plan | None = None
        self._skipped = 0
        self.setWindowTitle("In Excel-Stundenzettel eintragen")
        self.resize(980, 560)
        today = service.now().date()
        monday = today - timedelta(days=today.weekday())

        self.first, self.last = QDateEdit(_qdate(monday)), QDateEdit(_qdate(today))
        for w in (self.first, self.last):
            w.setCalendarPopup(True)
            w.setFixedWidth(120)
            w.setDisplayFormat("dd.MM.yyyy")
        self.preview_btn = QPushButton("Vorschau")
        self.preview_btn.clicked.connect(self._preview)
        top = QHBoxLayout()
        for w in (QLabel("Von"), self.first, QLabel("bis"), self.last, self.preview_btn):
            top.addWidget(w)
        top.addStretch(1)

        self.conflict = QComboBox()
        for value, text in (("ask", "nachfragen"), ("tool", "WorkPlanner hat Vorrang (ersetzen)"),
                            ("excel", "Excel hat Vorrang (behalten)")):
            self.conflict.addItem(text, value)
        self.conflict.setCurrentIndex(max(0, self.conflict.findData(service.excel_conflict)))
        self.conflict.setToolTip("Was passiert, wenn in einer Excel-Zelle schon ein anderer Wert steht?")
        self.conflict.currentIndexChanged.connect(self._conflict_changed)
        self.skip_done = QCheckBox("Schon eingetragene Tage überspringen")
        self.skip_done.setChecked(True)
        self.skip_done.setToolTip("WorkPlanner merkt sich, was es in diese Datei eingetragen hat. Unveränderte Werte "
                                  "werden nicht noch einmal eingetragen; geänderte schon.")
        reset = QPushButton("Merker zurücksetzen")
        reset.setToolTip("Vergisst, was im gewählten Zeitraum schon eingetragen wurde (z. B. wenn du Werte in Excel "
                         "gelöscht hast)")
        reset.clicked.connect(self._reset_marks)
        options = QHBoxLayout()
        for w in (QLabel("Steht schon ein Wert in Excel:"), self.conflict, self.skip_done, reset):
            options.addWidget(w)
        options.addStretch(1)
        self.info = QLabel(f"Datei: <b>{service.excel_path or '(nicht eingestellt)'}</b> · Vorlage: <b>{service.excel_profile.name}</b><br>"
                           "Pro Projekt und Tag werden die Stunden (ohne Mittagspause) in die Tagesspalte des "
                           "Blatts des jeweiligen Monats eingetragen.")
        self.info.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Datum", "Projekt", "Stunden", "Blatt / Zelle", "Aktion", "Bisher"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color:#8a5a00")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        self.ok = self.buttons.button(QDialogButtonBox.Ok)
        self.ok.setText("In Excel eintragen")
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self._write)
        self.buttons.rejected.connect(self.accept)

        # zweite Ansicht: das Blatt wie in Excel, mit den geplanten Werten darin (Liste bleibt die erste Ansicht)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._load_sheet_view)
        legend = QLabel("<span style='background:#c6efce'>&nbsp;neu&nbsp;</span> "
                        "<span style='background:#fcd9a6'>&nbsp;ersetzt vorhandenen Wert&nbsp;</span> "
                        "<span style='background:#e2f0d9'>&nbsp;neue Projektzeile&nbsp;</span> "
                        "· alles andere bleibt, wie es in der Datei steht (zuletzt gespeicherter Stand)")
        self.sheet_note = QLabel()
        self.sheet_view = SheetPreview()
        excel_tab = QWidget()
        el = QVBoxLayout(excel_tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Blatt"))
        row.addWidget(self.sheet_combo)
        row.addWidget(legend, 1)
        el.addLayout(row)
        el.addWidget(self.sheet_note)
        el.addWidget(self.sheet_view, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Liste")
        self.tabs.addTab(excel_tab, "So sieht es in Excel aus")
        self.tabs.currentChanged.connect(self._load_sheet_view)

        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addLayout(top)
        lay.addLayout(options)
        lay.addWidget(self.status)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.warnings)
        lay.addWidget(self.buttons)
        self._bg = BackgroundRunner(self)

    # --- Vorschau ------------------------------------------------------------------------------
    def _preview(self) -> None:
        first, last = self.first.date().toPython(), self.last.date().toPython()
        if last < first:
            self.status.setText("<span style='color:#c0392b'>⚠ „bis“ liegt vor „Von“.</span>")
            return
        items = aggregate(self.svc.report_rows(first, last), self.svc.excel_include_pause)  # Datenbank nur im GUI-Thread lesen
        done = self.svc.excel_exported(first, last) if self.skip_done.isChecked() else {}
        self._items = [it for it in items if abs(done.get((it.day.isoformat(), self._mark_key(it)), -1) - it.hours) > 1e-6]
        self._skipped = len(items) - len(self._items)
        if not self._items:
            self.table.setRowCount(0)
            self.warnings.setText("")
            self.status.setText("Im Zeitraum sind keine Stunden gebucht." if not items else
                                f"Alles im Zeitraum ist schon eingetragen ({self._skipped} Werte übersprungen). "
                                "Geänderte Einträge erscheinen hier automatisch wieder.")
            self.ok.setEnabled(False)
            return
        path, items, profile, factory = self.svc.excel_path, self._items, self.svc.excel_profile, self._factory
        self.preview_btn.setEnabled(False)
        self.ok.setEnabled(False)
        self.status.setText("Excel wird gelesen … (Excel startet dafür unsichtbar im Hintergrund)")

        def job():
            with factory(path, save=False) as book:
                return plan_all(book, items, profile)
        self._bg.run(job, self._on_planned, expected=(ExcelError,))

    def _on_planned(self, plan, error) -> None:
        self.preview_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            self.table.setRowCount(0)
            return
        self._plan = plan
        self._views: dict[str, object] = {}   # Blattansichten gelten nur für diese Vorschau
        names = list(dict.fromkeys(ln.sheet for ln in plan.lines))
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        for name in names:
            self.sheet_combo.addItem(name.strip(), name)
        self.sheet_combo.blockSignals(False)
        self.sheet_note.setText("")
        self.sheet_view.clearContents()
        self.table.setRowCount(len(plan.lines))
        replaced = 0
        for r, ln in enumerate(plan.lines):
            old = "" if ln.old is None else (f"{ln.old:g}" if isinstance(ln.old, (int, float)) else str(ln.old))
            vals = [f"{ln.day:%d.%m.%Y}", ln.project, f"{ln.hours:.2f}", f"{ln.sheet.strip()}  {ln.address}",
                    ln.action, old + ("  → ersetzt" if ln.overwrites else "")]
            replaced += ln.overwrites
            if ln.overwrites and self.conflict.currentData() == "excel":
                vals[5] = old + "  → bleibt (Excel hat Vorrang)"
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if ln.overwrites:
                    it.setBackground(QColor("#fde8c8"))
                if c == 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        new_rows = len(plan.setups)
        self.status.setText(f"{len(plan.lines)} Eintrag/Einträge für {len({ln.sheet for ln in plan.lines})} Blatt/Blätter"
                            + (f", {new_rows} neue Projektzeile(n)" if new_rows else "")
                            + (f", <b>{replaced} vorhandene Werte werden ersetzt</b> (orange)" if replaced else "")
                            + (f", {self._skipped} schon eingetragene übersprungen" if self._skipped else "") + ".")
        self.warnings.setText("<b>Nicht eingetragen:</b><br>" + "<br>".join(plan.warnings) if plan.warnings else "")
        self.ok.setEnabled(plan.writable)
        self.ok.setText(f"{len(plan.lines)} Wert(e) in Excel eintragen")
        self._conflict_changed()

    # --- Ansicht „wie in Excel“ ----------------------------------------------------------------
    def _load_sheet_view(self, *_) -> None:
        """Liest das gewählte Blatt aus der Datei (ohne Excel zu starten) und legt die geplanten Werte darüber."""
        if self.tabs.currentIndex() != 1 or self._plan is None or self.sheet_combo.currentIndex() < 0:
            return
        sheet = self.sheet_combo.currentData()
        if sheet in self._views:
            self._show_sheet(sheet)
            return
        path, loader = self.svc.excel_path, self._view_loader
        self.sheet_note.setText("Blatt wird gelesen …")

        def job():
            return loader(path, sheet)
        self._bg.run(job, lambda view, error, s=sheet: self._on_sheet_loaded(s, view, error))

    def _on_sheet_loaded(self, sheet: str, view, error) -> None:
        if error:
            self.sheet_note.setText(f"<span style='color:#c0392b'>⚠ Blatt nicht lesbar: {error}</span>")
            return
        self._views[sheet] = view
        if self.sheet_combo.currentData() == sheet:
            self._show_sheet(sheet)

    def _show_sheet(self, sheet: str) -> None:
        plan = self._plan
        lines = [ln for ln in plan.lines if ln.sheet == sheet]
        setups = [s for s in plan.setups if s.sheet == sheet]
        self.sheet_view.show_plan(self._views[sheet], lines, setups)
        replaced = sum(ln.overwrites for ln in lines)
        self.sheet_note.setText(f"{len(lines)} Wert(e) auf diesem Blatt" + (f", {len(setups)} neue Projektzeile(n)" if setups else "")
                                + (f", <b>{replaced} ersetzen vorhandene Werte</b>" if replaced else "") + ".")

    # --- Vorrang, Merker -------------------------------------------------------------------------
    @staticmethod
    def _mark_key(it: DayHours) -> str:
        return "|".join(it.key)

    def _conflict_changed(self, *_) -> None:
        mode = self.conflict.currentData()
        if self.svc.excel_conflict != mode:
            self.svc.set_excel_conflict(mode)
        if self._plan is not None:
            keep = sum(ln.overwrites for ln in self._plan.lines) if mode == "excel" else 0
            count = len(self._plan.lines) - keep
            self.ok.setText(f"{count} Wert(e) in Excel eintragen")
            self.ok.setEnabled(count > 0)

    def _reset_marks(self) -> None:
        n = self.svc.clear_excel_exported(self.first.date().toPython(), self.last.date().toPython())
        self.status.setText(f"{n} Merker für den Zeitraum zurückgesetzt – die Werte gelten wieder als nicht eingetragen.")

    def _ask_conflict(self, count: int) -> str | None:
        """Wer hat Vorrang, wenn schon Werte in Excel stehen? Gibt „tool“, „excel“ oder `None` (Abbruch) zurück."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Werte stehen schon in Excel")
        box.setText(f"In Excel stehen schon {count} andere Werte an den Stellen, die eingetragen würden.")
        box.setInformativeText("WorkPlanner hat Vorrang: die Werte aus WorkPlanner ersetzen die in Excel.\n"
                               "Excel hat Vorrang: die vorhandenen Werte in Excel bleiben, nur Leeres wird gefüllt.")
        tool = box.addButton("WorkPlanner hat Vorrang", QMessageBox.AcceptRole)
        excel = box.addButton("Excel hat Vorrang", QMessageBox.AcceptRole)
        box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.exec()
        return "tool" if box.clickedButton() is tool else "excel" if box.clickedButton() is excel else None

    # --- Eintragen -----------------------------------------------------------------------------
    def _write(self) -> None:
        if not self._plan or not self._plan.writable:
            return
        conflicts = sum(ln.overwrites for ln in self._plan.lines)
        mode = self.conflict.currentData()
        if conflicts and mode == "ask":
            mode = self._ask_conflict(conflicts)
            if mode is None:
                return
        keep_existing = mode == "excel"
        path, save, items, profile = self.svc.excel_path, self.svc.excel_save, self._items, self.svc.excel_profile
        factory = self._factory
        self.ok.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.status.setText("Wird in Excel eingetragen …")

        def job():
            with factory(path, save=save) as book:
                fresh = plan_all(book, items, profile)  # neu planen: die Datei kann sich seit der Vorschau geändert haben
                if keep_existing:
                    fresh.lines = [ln for ln in fresh.lines if not ln.overwrites]
                return apply_plan(book, fresh), (fresh.warnings, [(ln.day, ln.project) for ln in fresh.lines])
        self._bg.run(job, lambda value, error: self._on_written(*(value if error is None else (None, error))),
                     expected=(ExcelError,))

    def _on_written(self, written, info) -> None:
        self.preview_btn.setEnabled(True)
        if written is None:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {info}</span>")
            self.ok.setEnabled(True)
            return
        _, written_lines = info
        done = set(written_lines)   # nur was wirklich geschrieben wurde, wird als eingetragen gemerkt
        self.svc.mark_excel_exported([(it.day, self._mark_key(it), it.hours) for it in self._items
                                      if (it.day, it.label) in done])
        saved = "und gespeichert" if self.svc.excel_save else "(noch nicht gespeichert – in Excel speichern!)"
        self.status.setText(f"✓ {written} Wert(e) in Excel eingetragen {saved}.")
        self.ok.setEnabled(False)
