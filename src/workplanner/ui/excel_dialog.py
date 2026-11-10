"""Stunden in den Excel-Stundenzettel eintragen: Zeitraum wählen, Vorschau prüfen, eintragen."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..excel_timesheet import (DayHours, ExcelError, ExcelWorkbook, Plan, aggregate, apply_plan, plan_all)
from ..service import TimeService
from .background import BackgroundRunner


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class ExcelExportDialog(QDialog):
    """Excel läuft im Hintergrund (siehe background.py: der Thread kennt den Dialog nicht)."""

    def __init__(self, service: TimeService, parent=None, workbook_factory=ExcelWorkbook):
        super().__init__(parent)
        self.svc, self._factory = service, workbook_factory
        self._items: list[DayHours] = []
        self._plan: Plan | None = None
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

        lay = QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addLayout(top)
        lay.addWidget(self.status)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.warnings)
        lay.addWidget(self.buttons)
        self._bg = BackgroundRunner(self)

    # --- Vorschau ------------------------------------------------------------------------------
    def _preview(self) -> None:
        first, last = self.first.date().toPython(), self.last.date().toPython()
        if last < first:
            self.status.setText("<span style='color:#c0392b'>⚠ „bis“ liegt vor „Von“.</span>")
            return
        self._items = aggregate(self.svc.report_rows(first, last))  # Datenbank nur im GUI-Thread lesen
        if not self._items:
            self.table.setRowCount(0)
            self.warnings.setText("")
            self.status.setText("Im Zeitraum sind keine Stunden gebucht.")
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
        self.table.setRowCount(len(plan.lines))
        replaced = 0
        for r, ln in enumerate(plan.lines):
            old = "" if ln.old is None else (f"{ln.old:g}" if isinstance(ln.old, (int, float)) else str(ln.old))
            vals = [f"{ln.day:%d.%m.%Y}", ln.project, f"{ln.hours:.2f}", f"{ln.sheet.strip()}  {ln.address}",
                    ln.action, old + ("  → ersetzt" if ln.overwrites else "")]
            replaced += ln.overwrites
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
                            + (f", <b>{replaced} vorhandene Werte werden ersetzt</b> (orange)" if replaced else "") + ".")
        self.warnings.setText("<b>Nicht eingetragen:</b><br>" + "<br>".join(plan.warnings) if plan.warnings else "")
        self.ok.setEnabled(plan.writable)
        self.ok.setText(f"{len(plan.lines)} Wert(e) in Excel eintragen")

    # --- Eintragen -----------------------------------------------------------------------------
    def _write(self) -> None:
        if not self._plan or not self._plan.writable:
            return
        path, save, items, profile = self.svc.excel_path, self.svc.excel_save, self._items, self.svc.excel_profile
        factory = self._factory
        self.ok.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.status.setText("Wird in Excel eingetragen …")

        def job():
            with factory(path, save=save) as book:
                fresh = plan_all(book, items, profile)  # neu planen: die Datei kann sich seit der Vorschau geändert haben
                return apply_plan(book, fresh), fresh.warnings
        self._bg.run(job, lambda value, error: self._on_written(*(value if error is None else (None, error))),
                     expected=(ExcelError,))

    def _on_written(self, written, info) -> None:
        self.preview_btn.setEnabled(True)
        if written is None:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {info}</span>")
            self.ok.setEnabled(True)
            return
        saved = "und gespeichert" if self.svc.excel_save else "(noch nicht gespeichert – in Excel speichern!)"
        self.status.setText(f"✓ {written} Wert(e) in Excel eingetragen {saved}.")
        self.ok.setEnabled(False)
