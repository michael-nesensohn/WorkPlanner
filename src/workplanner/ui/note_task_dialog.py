"""Notizen von Zeiteinträgen auf Wunsch als Task unter der DevOps-Story anlegen."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..devops import DevOpsClient, DevOpsError
from ..devops_sync import task_title
from ..service import TimeService
from ..timeline import WORK, Entry
from .dialogs import fmt_duration, fmt_time


def skip_reason(e: Entry) -> str:
    """Warum ein Eintrag nicht als Task gesendet werden kann (leer = möglich)."""
    if e.kind != WORK:
        return "keine Arbeitszeit"
    if not e.devops_id:
        return "nicht mit einer Story verknüpft"
    if not e.note.strip():
        return "keine Notiz"
    if e.devops_task_id:
        return f"schon als Task #{e.devops_task_id} gesendet"
    return ""


class NoteTaskDialog(QDialog):
    _done = Signal(object)  # [(entry_id, WorkItem | None, Fehlertext | None)]

    def __init__(self, service: TimeService, entries: list[Entry], parent=None, client_factory=DevOpsClient):
        super().__init__(parent)
        self.svc, self._factory, self._entries = service, client_factory, entries
        self.setWindowTitle("Notizen als Task in DevOps anlegen")
        self.resize(900, 420)
        info = QLabel("Zu jedem markierten Eintrag wird unter seiner <b>Story</b> ein Task angelegt: Titel ist die "
                      "erste Zeile der Notiz, die ganze Notiz die Beschreibung. Die <b>Stunden</b> bleiben auf der "
                      "Story (Übertragung wie bisher) und werden nicht doppelt gebucht.")
        info.setWordWrap(True)
        self.table = QTableWidget(len(entries), 5)
        self.table.setHorizontalHeaderLabels(["", "Zeit", "Story", "Task-Titel", "Hinweis"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        now = service.now()
        for r, e in enumerate(entries):
            reason = skip_reason(e)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if not reason else Qt.NoItemFlags)
            check.setCheckState(Qt.Unchecked if reason else Qt.Checked)
            self.table.setItem(r, 0, check)
            story = f"#{e.devops_id} {service.devops_title(e.devops_id)}".strip() if e.devops_id else ""
            vals = [f"{e.start:%d.%m.} {fmt_time(e.start)}–{fmt_time(e.end)} ({fmt_duration(e.duration(now))})",
                    story, task_title(e.note) if e.note.strip() else "", reason]
            for c, v in enumerate(vals, 1):
                it = QTableWidgetItem(v)
                if reason:
                    it.setForeground(Qt.gray)
                self.table.setItem(r, c, it)
        self.table.itemChanged.connect(lambda _: self._update())
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        self.ok = self.buttons.button(QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self._create)
        self.buttons.rejected.connect(self.accept)  # „Schließen“: Hauptfenster aktualisiert sich danach
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)
        self._done.connect(self._on_done)
        self._update()

    def selected(self) -> list[Entry]:
        return [e for r, e in enumerate(self._entries)
                if not skip_reason(e) and self.table.item(r, 0).checkState() == Qt.Checked]

    def _update(self) -> None:
        n = len(self.selected())
        self.ok.setText(f"{n} Task(s) in DevOps anlegen")
        self.ok.setEnabled(n > 0)

    def _create(self) -> None:
        chosen = self.selected()
        try:
            client = self.svc.devops_client(self._factory)
        except DevOpsError as ex:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return
        self.ok.setEnabled(False)
        self.table.setEnabled(False)
        self.status.setText("Tasks werden angelegt …")

        def work():
            results = []
            for e in chosen:
                try:
                    results.append((e.id, client.create_task(e.devops_id, task_title(e.note), e.note), None))
                except DevOpsError as ex:
                    results.append((e.id, None, str(ex)))
                except Exception as ex:  # noqa: BLE001
                    results.append((e.id, None, f"Unerwarteter Fehler: {ex}"))
            try:
                self._done.emit(results)
            except RuntimeError:  # Dialog wurde inzwischen geschlossen
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, results) -> None:
        failed = []
        for entry_id, task, error in results:
            if task is not None:
                self.svc.mark_entry_task(entry_id, task.id)  # merken, damit nichts doppelt gesendet wird
            else:
                failed.append(error)
        ok = len(results) - len(failed)
        text = f"✓ {ok} Task(s) in DevOps angelegt."
        if failed:
            text += "<br><span style='color:#c0392b'>⚠ Fehlgeschlagen: " + "; ".join(failed) + "</span>"
        self.status.setText(text)
        self.ok.setVisible(False)  # nur noch „Schließen“
