"""Seite „DevOps“: Features und Stories aus dem Azure-DevOps-Backlog holen,
daraus Projekte anlegen oder Aufgaben starten."""
from __future__ import annotations

import json
import threading
from collections import defaultdict
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..devops import DevOpsClient, DevOpsError, WorkItem, backlog_url, parse_backlog_url
from ..devops_sync import PlanItem, apply_plan, build_plan
from ..service import TimeService
from .dialogs import NoteEdit
from .pages import ProjectDialog

DEFAULT_WIDTHS = [340, 70, 95, 80, 90, 140, 170]  # Titel, ID, Typ, Status, Start, Zugewiesen an, Projekt
VIEWS = [("Features", "features"), ("Stories", "stories"), ("Features und Stories", "both")]


class StoryDialog(QDialog):
    """Titel und Beschreibung einer neuen Story."""

    def __init__(self, feature_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Story in DevOps anlegen")
        self.setMinimumWidth(520)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Titel der Story")
        self.description = NoteEdit(placeholder="Beschreibung (optional, mehrere Zeilen möglich)")
        self.assign = QCheckBox("mir zuweisen")
        self.assign.setChecked(True)
        form = QFormLayout()
        form.addRow("Feature", QLabel(feature_text))
        form.addRow("Titel", self.title)
        form.addRow("Beschreibung", self.description)
        form.addRow("", self.assign)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Anlegen")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.title.textChanged.connect(lambda t: self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(t.strip())))
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.buttons)


class SyncDialog(QDialog):
    """Vorschau der Stunden, die nach DevOps übertragen würden."""

    def __init__(self, plan: list[PlanItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stunden nach DevOps übertragen")
        self.resize(900, 420)
        ok = [p for p in plan if not p.skip_reason]
        skipped = [p for p in plan if p.skip_reason]
        info = QLabel("Es wird nur die <b>Differenz</b> zum letzten Mal in das Feld „Completed Work“ "
                      "geschrieben. Stunden anderer Personen bleiben erhalten.")
        info.setWordWrap(True)
        table = QTableWidget(len(ok), 7)
        table.setHorizontalHeaderLabels(["Story", "In WorkPlanner", "schon übertragen", "neu",
                                         "Ziel in DevOps", "DevOps vorher", "DevOps nachher"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, p in enumerate(ok):
            vals = [f"#{p.item_id} {p.title}", f"{p.total_h:.2f} h", f"{p.synced_h:.2f} h",
                    f"{p.delta_h:+.2f} h", p.target, f"{p.current_h:.2f} h", f"{p.new_h:.2f} h"]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(v))
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(f"{len(ok)} Eintrag/Einträge übertragen")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(ok))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(table, 1)
        if skipped:
            note = QLabel("<b>Übersprungen:</b><br>" + "<br>".join(
                f"#{p.item_id} {p.title}: {p.skip_reason}" for p in skipped))
            note.setStyleSheet("color:#8a5a00")
            note.setWordWrap(True)
            lay.addWidget(note)
        lay.addWidget(self.buttons)


class DevOpsPage(QWidget):
    story_chosen = Signal(object)       # {"id", "title", "type", "parent_id", "parent_title"}
    projects_changed = Signal()         # es wurden Projekte angelegt
    _loaded = Signal(object, object)    # (Liste | None, Fehlertext | None)
    items_loaded = Signal(object, str)  # (list[WorkItem], Ansicht) – füllt die DevOps-Kacheln
    _created = Signal(object, object)   # (WorkItem | None, Fehlertext | None)
    _planned = Signal(object, object)   # (Plan | None, Fehlertext | None)
    _applied = Signal(object, object)   # (Ergebnisse | None, Fehlertext | None)
    _tested = Signal(str)

    def __init__(self, service: TimeService):
        super().__init__()
        self.svc = service
        self._items: list[WorkItem] = []
        self._loaded_view = "both"

        cfg = service.devops_config()
        self.url = QLineEdit(backlog_url(cfg["org"], cfg["project"], cfg["team"]))
        self.url.setPlaceholderText("Backlog-Adresse aus dem Browser einfügen (https://dev.azure.com/…)")
        self.pat = QLineEdit()
        self.pat.setEchoMode(QLineEdit.Password)
        self.pat.setPlaceholderText("gespeichert" if cfg["has_pat"] else
                                    "Persönliches Zugriffstoken (PAT) mit „Work Items: Read“")
        self.scope = QComboBox()  # Abfrage: nur mir zugewiesen oder alle
        self.scope.addItem("Nur mir zugewiesene", True)
        self.scope.addItem("Alle", False)
        self.scope.setCurrentIndex(0 if cfg["only_mine"] else 1)
        self.scope.currentIndexChanged.connect(
            lambda _: self.svc.db.set_setting("devops_only_mine", "1" if self.only_mine else "0"))
        self.view = QComboBox()
        for text, key in VIEWS:
            self.view.addItem(text, key)
        self.view.setCurrentIndex(2)  # Baum: Epic → Feature → Story
        self.status = QLabel()
        self.status.setWordWrap(True)

        save = QPushButton("Speichern")
        save.clicked.connect(self._save)
        test = QPushButton("Verbindung testen")
        test.clicked.connect(self._test)
        box = QGroupBox("Verbindung")
        form = QFormLayout(box)
        form.addRow("Adresse", self.url)
        form.addRow("Token (PAT)", self.pat)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addWidget(test)
        row.addStretch(1)
        form.addRow(row)

        self._nodes: list[WorkItem] = []
        self.tree = QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(["Titel", "ID", "Typ", "Status", "Start", "Zugewiesen an", "Projekt"])
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setExpandsOnDoubleClick(False)  # Doppelklick startet die Aufgabe
        self.tree.setIndentation(22)
        hh = self.tree.header()
        hh.setSectionResizeMode(QHeaderView.Interactive)  # Spaltenbreite per Maus verschiebbar
        hh.setStretchLastSection(True)
        hh.setMinimumSectionSize(40)
        for i, w in enumerate(self._saved_widths()):
            self.tree.setColumnWidth(i, w)
        self._save_timer = QTimer(self, singleShot=True, interval=500)
        self._save_timer.timeout.connect(self._store_widths)
        hh.sectionResized.connect(lambda *_: self._save_timer.start())
        self.tree.itemDoubleClicked.connect(lambda *_: self._start())

        self.reload_btn = QPushButton("Laden")
        self.reload_btn.clicked.connect(self.reload)
        self.create_btn = QPushButton("＋  Projekt aus Feature anlegen")
        self.create_btn.setToolTip("Legt aus den markierten Features Projekte an "
                                   "(Name = Titel, Projektnummer = Feature-ID)")
        self.create_btn.clicked.connect(self._create_projects)
        start = QPushButton("▶  Aufgabe starten")
        start.setToolTip("Startet die Zeit mit dem Eintrag in der Notiz (Doppelklick geht auch)")
        start.clicked.connect(self._start)
        browser = QPushButton("Im Browser öffnen")
        browser.clicked.connect(self._open)
        self.story_btn = QPushButton("＋  Story in DevOps anlegen …")
        self.story_btn.setToolTip("Legt eine neue Story unter dem markierten Feature an (schreibt in DevOps)")
        self.story_btn.clicked.connect(self._create_story)
        self.sync_btn = QPushButton("⇪  Stunden nach DevOps übertragen …")
        self.sync_btn.setToolTip("Überträgt die gebuchten Stunden (Notiz beginnt mit #ID) als Completed Work")
        self.sync_btn.clicked.connect(self._sync_hours)
        btns2 = QHBoxLayout()
        btns2.addWidget(self.story_btn)
        btns2.addWidget(self.sync_btn)
        btns2.addStretch(1)
        btns = QHBoxLayout()
        btns.addWidget(QLabel("Anzeigen:"))
        btns.addWidget(self.view)
        btns.addWidget(QLabel("Zuweisung:"))
        btns.addWidget(self.scope)
        btns.addWidget(self.reload_btn)
        btns.addSpacing(16)
        btns.addWidget(self.create_btn)
        btns.addWidget(start)
        btns.addWidget(browser)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addWidget(self.status)
        lay.addLayout(btns)
        lay.addLayout(btns2)
        lay.addWidget(self.tree, 1)

        self._loaded.connect(self._on_loaded)
        self._created.connect(self._on_created)
        self._planned.connect(self._on_planned)
        self._applied.connect(self._on_applied)
        self._tested.connect(self.status.setText)

    def _saved_widths(self) -> list[int]:
        try:
            widths = json.loads(self.svc.db.get_setting("devops_col_widths"))
            if isinstance(widths, list) and len(widths) == len(DEFAULT_WIDTHS):
                return [max(40, int(w)) for w in widths]
        except (ValueError, TypeError):
            pass
        return DEFAULT_WIDTHS

    def _store_widths(self) -> None:
        self.svc.db.set_setting("devops_col_widths", json.dumps(
            [self.tree.columnWidth(i) for i in range(self.tree.columnCount())]))

    # --- Konfiguration --------------------------------------------------------
    def _save(self) -> bool:
        try:
            parts = parse_backlog_url(self.url.text())
        except DevOpsError as ex:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {ex}</span>")
            return False
        self.svc.set_devops_config(parts["org"], parts["project"], parts["team"],
                                   self.only_mine, self.pat.text() or None)
        if self.pat.text():
            self.pat.clear()
            self.pat.setPlaceholderText("gespeichert")
        team = f", Team „{parts['team']}“" if parts["team"] else ""
        self.status.setText(f"Gespeichert: {parts['org']} / {parts['project']}{team}")
        return True

    def _client(self) -> DevOpsClient | None:
        if not self._save():
            return None
        cfg = self.svc.devops_config()
        pat = self.svc.devops_pat()
        if not pat:
            self.status.setText("<span style='color:#c0392b'>⚠ Bitte zuerst ein Token (PAT) eingeben.</span>")
            return None
        return DevOpsClient(cfg["org"], cfg["project"], cfg["team"], pat)

    @staticmethod
    def _background(fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _test(self) -> None:
        client = self._client()
        if not client:
            return
        self.status.setText("Verbindung wird getestet …")

        def work():
            try:
                self._tested.emit(f"✓ Verbindung zu Projekt „{client.test_connection()}“ funktioniert.")
            except DevOpsError as ex:
                self._tested.emit(f"<span style='color:#c0392b'>⚠ {ex}</span>")
        self._background(work)

    # --- Laden ----------------------------------------------------------------------
    def reload(self) -> None:
        client = self._client()
        if not client:
            return
        self.reload_btn.setEnabled(False)
        self.status.setText("Daten werden geladen …")
        only_mine, view = self.only_mine, self.view.currentData()
        self._loaded_view = view

        def work():
            try:
                self._loaded.emit(self.load_items(client, view, only_mine), None)
            except DevOpsError as ex:
                self._loaded.emit(None, str(ex))
            except Exception as ex:  # noqa: BLE001 – den Thread nie still sterben lassen
                self._loaded.emit(None, f"Unerwarteter Fehler: {ex}")
        self._background(work)

    @property
    def only_mine(self) -> bool:
        return bool(self.scope.currentData())

    @staticmethod
    def load_items(client, view: str, only_mine: bool) -> list[WorkItem]:
        """Features und/oder Stories laden; die Zuweisung gilt für beide Ebenen."""
        items: list[WorkItem] = []
        if view in ("features", "both"):
            items += client.fetch_features(only_mine)
        if view in ("stories", "both"):
            items += client.fetch_stories(only_mine)
        return items

    def _on_loaded(self, items, error) -> None:
        self.reload_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        self._items = items
        self._fill()
        features = [w for w in items if w.is_feature]
        self.status.setText(f"{len(features)} Features und {len(items) - len(features)} Stories geladen.")
        self.items_loaded.emit(items, self._loaded_view)

    def _fill(self) -> None:
        """Baut den Baum Epic → Feature → Story auf. Fehlt zu einer Story das Feature (oder zu einem
        Feature das Epic) in der Ladeliste, wird der Knoten aus den Elterndaten ergänzt."""
        self.tree.clear()
        self._nodes = []
        features: dict[int, WorkItem] = {w.id: w for w in self._items if w.is_feature}
        stories = [w for w in self._items if not w.is_feature]
        base = lambda url, i: url.rsplit("/", 1)[0] + f"/{i}"  # noqa: E731
        for st in stories:
            if st.parent_id and st.parent_id not in features:
                features[st.parent_id] = WorkItem(
                    st.parent_id, st.parent_title, "Feature", "", "", st.grandparent_id,
                    st.grandparent_title, base(st.url, st.parent_id),
                    start_date=st.parent_start, parent_start=st.grandparent_start)
        by_feature: dict[int, list[WorkItem]] = defaultdict(list)
        loose = []
        for st in stories:
            (by_feature[st.parent_id] if st.parent_id else loose).append(st)

        epic_nodes: dict[int | None, QTreeWidgetItem] = {}
        for f in features.values():
            if f.parent_id not in epic_nodes:
                epic = (WorkItem(f.parent_id, f.parent_title, "Epic", "", "", None, "", base(f.url, f.parent_id),
                                 start_date=f.parent_start)
                        if f.parent_id else None)
                epic_nodes[f.parent_id] = self._node(self.tree.invisibleRootItem(), epic, "(ohne Epic)")
            fnode = self._node(epic_nodes[f.parent_id], f)
            for st in by_feature.get(f.id, []):
                self._node(fnode, st)
        if loose:
            group = self._node(self.tree.invisibleRootItem(), None, "(ohne Feature)")
            for st in loose:
                self._node(group, st)
        self.tree.expandAll()

    def _node(self, parent: QTreeWidgetItem, w: WorkItem | None, group_title: str = "") -> QTreeWidgetItem:
        if w is None:  # reiner Gruppenknoten
            it = QTreeWidgetItem(parent, [group_title])
            it.setData(0, Qt.UserRole, -1)
            it.setForeground(0, QColor("#888"))
            return it
        existing = self.svc.find_project(number=str(w.id)) if w.is_feature else None
        project = f"✓ {self.svc.project_name(existing)}" if existing is not None else ""
        start = f"{w.start_date:%d.%m.%Y}" if w.start_date else ""
        it = QTreeWidgetItem(parent, [w.title, str(w.id), w.type, w.state, start, w.assigned_to, project])
        it.setData(0, Qt.UserRole, len(self._nodes))
        self._nodes.append(w)
        it.setToolTip(0, f"{w.type} #{w.id} – {w.url}")
        font = it.font(0)
        if w.is_feature or w.type == "Epic":
            font.setBold(True)
            it.setFont(0, font)
        if w.type == "Epic":
            it.setForeground(0, QColor("#667"))
        return it

    # --- Aktionen ---------------------------------------------------------------------
    def _selected(self) -> list[WorkItem]:
        out = []
        for it in self.tree.selectedItems():
            idx = it.data(0, Qt.UserRole)
            if idx is not None and idx >= 0:
                out.append(self._nodes[idx])
        return out

    def _create_projects(self) -> None:
        chosen = self._selected()
        features = [w for w in chosen if w.is_feature]
        if not features:
            QMessageBox.information(self, "DevOps", "Bitte mindestens ein Feature markieren "
                                                    "(Anzeige „Features“ wählen).")
            return
        created = skipped = 0
        if len(features) == 1:  # einzeln: Name, Nummer und verrechenbar noch anpassbar
            w = features[0]
            if self.svc.find_project(number=str(w.id)) is not None:
                skipped = 1
            else:
                dlg = ProjectDialog(w.title, str(w.id), False, self)
                if not dlg.exec() or not dlg.name.text().strip():
                    return
                if self.svc.add_project(dlg.name.text().strip(), dlg.number.text().strip(),
                                        dlg.billable.isChecked()) is None:
                    skipped = 1
                else:
                    created = 1
        else:
            names = "\n".join(f"  {w.id}  {w.title}" for w in features)
            if QMessageBox.question(self, "Projekte anlegen",
                                    f"{len(features)} Projekte anlegen (Projektnummer = Feature-ID)?\n\n{names}"
                                    ) != QMessageBox.Yes:
                return
            for w in features:
                if self.svc.add_project(w.title, str(w.id)) is None:
                    skipped += 1
                else:
                    created += 1
        self._fill()
        if created:
            self.projects_changed.emit()
        text = f"{created} Projekt(e) angelegt"
        if skipped:
            text += f", {skipped} gab es schon (gleicher Name oder gleiche Nummer)"
        self.status.setText(text + ".")

    # --- Schreiben nach DevOps ------------------------------------------------------------
    def _create_story(self) -> None:
        sel = self._selected()
        parent_id, feature_text = None, "ohne Feature (nichts oder kein Feature markiert)"
        if sel and sel[0].is_feature:
            parent_id, feature_text = sel[0].id, f"#{sel[0].id} {sel[0].title}"
        elif sel and sel[0].parent_id:
            parent_id, feature_text = sel[0].parent_id, f"#{sel[0].parent_id} {sel[0].parent_title}"
        dlg = StoryDialog(feature_text, self)
        if not dlg.exec():
            return
        title, description, assign = dlg.title.text().strip(), dlg.description.toPlainText(), dlg.assign.isChecked()
        cfg = self.svc.devops_config()
        if QMessageBox.question(
                self, "In Azure DevOps anlegen",
                f"Diese Story wird in Azure DevOps angelegt:\n\nTitel: {title}\nFeature: {feature_text}\n"
                f"Projekt: {cfg['org']} / {cfg['project']}\nZuweisung: {'mir' if assign else 'niemand'}\n\n"
                "Fortfahren?") != QMessageBox.Yes:
            return
        client = self._client()
        if not client:
            return
        self.story_btn.setEnabled(False)
        self.status.setText("Story wird angelegt …")

        def work():
            try:
                self._created.emit(client.create_story(title, description, parent_id, assign), None)
            except DevOpsError as ex:
                self._created.emit(None, str(ex))
            except Exception as ex:  # noqa: BLE001
                self._created.emit(None, f"Unerwarteter Fehler: {ex}")
        self._background(work)

    def _on_created(self, item, error) -> None:
        self.story_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        self.reload()
        self.status.setText(f"✓ Story #{item.id} „{item.title}“ angelegt – Liste wird neu geladen.")

    def _sync_hours(self) -> None:
        totals, synced = self.svc.devops_hours(), self.svc.devops_synced()
        if not any(abs(round(h - synced.get(i, 0.0), 2)) >= 0.01 for i, h in totals.items()):
            self.status.setText("Keine neuen Stunden zum Übertragen. (Gebucht wird, wenn die Notiz mit "
                                "#ID beginnt, z. B. „#4411 Waage“.)")
            return
        client = self._client()
        if not client:
            return
        self.sync_btn.setEnabled(False)
        self.status.setText("Stand in DevOps wird gelesen …")

        def work():
            try:
                self._planned.emit(build_plan(client, totals, synced), None)
            except DevOpsError as ex:
                self._planned.emit(None, str(ex))
            except Exception as ex:  # noqa: BLE001
                self._planned.emit(None, f"Unerwarteter Fehler: {ex}")
        self._background(work)

    def _on_planned(self, plan, error) -> None:
        self.sync_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        dlg = SyncDialog(plan, self)
        if not (plan and dlg.exec()):
            self.status.setText("Nichts übertragen.")
            return
        client = self._client()
        if not client:
            return
        self.sync_btn.setEnabled(False)
        self.status.setText("Stunden werden übertragen …")

        def work():
            try:
                self._applied.emit(apply_plan(client, plan), None)
            except Exception as ex:  # noqa: BLE001
                self._applied.emit(None, f"Unerwarteter Fehler: {ex}")
        self._background(work)

    def _on_applied(self, results, error) -> None:
        self.sync_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        failed = []
        for p, err in results:
            if err:
                failed.append(f"#{p.item_id}: {err}")
            else:
                self.svc.devops_mark_synced(p.item_id, p.total_h)  # nur bei Erfolg merken
        ok = len(results) - len(failed)
        text = f"✓ {ok} Eintrag/Einträge nach DevOps übertragen."
        if failed:
            text += "<br><span style='color:#c0392b'>⚠ Fehlgeschlagen: " + "; ".join(failed) + "</span>"
        self.status.setText(text)

    def _start(self) -> None:
        chosen = self._selected()
        if chosen:
            w = chosen[0]
            self.story_chosen.emit({"id": w.id, "title": w.title, "type": "feature" if w.is_feature else "story",
                                    "parent_id": w.parent_id, "parent_title": w.parent_title})
        else:
            QMessageBox.information(self, "DevOps", "Bitte zuerst einen Eintrag auswählen.")

    def _open(self) -> None:
        chosen = self._selected()
        if chosen:
            webbrowser.open(chosen[0].url)
