"""DevOps-Features mit ihren Stories als Kacheln neben der Schnellauswahl; füllt sich automatisch."""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from ..devops import DevOpsClient, DevOpsError, WorkItem
from ..service import TimeService
from .tiles import TileButton

INDENT = 18


def to_cache(items: list[WorkItem]) -> list[dict]:
    """Nur, was die Kacheln brauchen; wird als JSON gemerkt, damit sie auch offline da sind."""
    return [{"id": w.id, "title": w.title, "type": "feature" if w.is_feature else "story", "state": w.state,
             "parent_id": w.parent_id, "parent_title": w.parent_title, "epic": w.epic,
             "start": w.start_date.isoformat() if w.start_date else "", "url": w.url} for w in items]


def group_items(items: list[dict]) -> tuple[list[tuple[dict, list[dict]]], list[dict]]:
    """([(Feature, [Stories])], Stories ohne Feature). Fehlt zu einer Story das Feature in der Liste
    (z. B. bei „nur mir zugewiesene“), wird es aus den Daten der Story ergänzt."""
    features: dict[int, dict] = {}
    stories: list[dict] = []
    for it in items:
        if it.get("type", "feature") == "story":
            stories.append(it)
        else:
            features[it["id"]] = it
    for s in stories:
        pid = s.get("parent_id")
        if pid and pid not in features:
            features[pid] = {"id": pid, "title": s.get("parent_title", ""), "type": "feature", "epic": s.get("epic", ""),
                             "start": "", "url": "", "state": ""}
    children: dict[int, list[dict]] = defaultdict(list)
    loose: list[dict] = []
    for s in stories:
        (children[s["parent_id"]] if s.get("parent_id") else loose).append(s)
    return [(f, children.get(f["id"], [])) for f in features.values()], loose


def parse_day(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def week_bounds(today: date) -> tuple[date, date]:
    """Montag und Sonntag der Woche, in der `today` liegt."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def split_by_week(groups: list[tuple[dict, list[dict]]], loose: list[dict], today: date):
    """Teilt in „diese Woche“ und „weitere“.

    Zu „diese Woche“ gehört ein Feature, wenn es selbst oder eine seiner Stories ein Startdatum in dieser Woche
    hat (Montag bis Sonntag); sie stehen nach Datum sortiert (früheste zuerst). Alles andere, auch Einträge ohne
    Datum oder mit Datum in anderen Wochen, bleibt in der bisherigen Reihenfolge.
    Rückgabe: (Features diese Woche, Stories ohne Feature diese Woche, weitere Features, weitere Stories)."""
    monday, sunday = week_bounds(today)

    def week_date(item: dict) -> date | None:
        d = parse_day(item.get("start"))
        return d if d is not None and monday <= d <= sunday else None

    def group_date(group) -> date | None:
        feature, stories = group
        dates = [d for d in [week_date(feature)] + [week_date(s) for s in stories] if d is not None]
        return min(dates) if dates else None

    dated = sorted(((group_date(g), n, g) for n, g in enumerate(groups) if group_date(g) is not None),
                   key=lambda t: (t[0], t[1]))
    this_week = [g for _, _, g in dated]
    others = [g for g in groups if group_date(g) is None]
    loose_week = sorted((s for s in loose if week_date(s) is not None), key=lambda s: week_date(s))
    loose_other = [s for s in loose if week_date(s) is None]
    return this_week, loose_week, others, loose_other


class FeatureFeed(QObject):
    """Lädt Features und Stories im Hintergrund (ohne die Oberfläche zu blockieren)."""
    loaded = Signal(object)  # list[dict]
    failed = Signal(str)

    def __init__(self, service: TimeService, parent=None, client_factory=DevOpsClient):
        super().__init__(parent)
        self.svc, self._factory, self._busy = service, client_factory, False
        self.loaded.connect(self._idle)
        self.failed.connect(self._idle)

    def _idle(self, *_):
        self._busy = False

    def refresh(self) -> None:
        if self._busy:
            return
        try:
            client = self.svc.devops_client(self._factory)  # liest die Datenbank nur im GUI-Thread
        except DevOpsError as ex:
            self.failed.emit(str(ex))
            return
        only_mine = self.svc.devops_config()["only_mine"]
        self._busy = True

        def work():
            try:
                self.loaded.emit(to_cache(client.fetch_features(only_mine) + client.fetch_stories(only_mine)))
            except DevOpsError as ex:
                self.failed.emit(str(ex))
            except Exception as ex:  # noqa: BLE001 – den Thread nie still sterben lassen
                self.failed.emit(f"Unerwarteter Fehler: {ex}")
        threading.Thread(target=work, daemon=True).start()


class FeaturePanel(QWidget):
    feature_chosen = Signal(object)  # dict aus `to_cache`
    story_chosen = Signal(object)
    refresh_requested = Signal()

    def __init__(self, color_for: Callable[[int], str | None], today: Callable[[], date] = date.today):
        super().__init__()
        self._color_for = color_for
        self._today = today
        self.order: list[int] = []            # IDs in der angezeigten Reihenfolge
        self.separator_pos: int | None = None  # Trennlinie steht nach so vielen Einträgen
        self._items: list[dict] = []
        self._buttons: dict[int, QPushButton] = {}

        head = QHBoxLayout()
        head.addWidget(QLabel("<b>DevOps</b>"), 1)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Features und Stories jetzt neu von DevOps laden")
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
        self.resize(270, self.height())

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _clear(self, layout) -> None:
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().hide()  # bis zum eigentlichen Löschen nicht als Geisterbild sichtbar lassen
                it.widget().deleteLater()
            elif it.layout():
                self._clear(it.layout())

    def _add(self, item: dict, indent: int) -> None:
        story = item.get("type", "feature") == "story"
        b = TileButton(item["title"], f"#{item['id']}", bold=not story)
        b.setCheckable(True)
        tip = [f"{'Story' if story else 'Feature'} #{item['id']} – {item['title']}"]
        if story and item.get("parent_title"):
            tip.append(f"Feature: {item['parent_title']}")
        if item.get("epic"):
            tip.append(f"Epic: {item['epic']}")
        if item.get("state"):
            tip.append(f"Status: {item['state']}")
        if item.get("start"):
            tip.append(f"Start: {item['start']}")
        b.setToolTip("\n".join(tip))
        b.setStyleSheet(f"QPushButton#tile {{ border-left: 6px solid {self._color_for(item['id']) or '#c4cbd6'}; }}")
        b.clicked.connect(lambda _=False, it=item: (self.story_chosen if story else self.feature_chosen).emit(it))
        row = QHBoxLayout()
        row.setContentsMargins(indent * INDENT, 0, 0, 0)
        row.addWidget(b)
        self.tiles.addLayout(row)
        self._buttons[item["id"]] = b
        self.order.append(item["id"])

    def set_items(self, items: list[dict]) -> None:
        self._items = items
        self._clear(self.tiles)
        self._buttons, self.order, self.separator_pos = {}, [], None
        today = self._today()
        groups, loose = group_items(items)
        week_groups, week_loose, other_groups, other_loose = split_by_week(groups, loose, today)
        if week_groups or week_loose:  # zuerst, was diese Woche ein Datum hat
            kw = today.isocalendar()[1]
            self.tiles.addWidget(QLabel(f"<span style='color:#2F5597;font-size:11px'>Diese Woche · KW {kw}</span>"))
            self._render(week_groups, week_loose)
            if other_groups or other_loose:  # …dann, mit einem Strich getrennt, der Rest
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("color:#b8c1ce")
                self.tiles.addSpacing(4)
                self.tiles.addWidget(line)
                self.tiles.addSpacing(4)
                self.separator_pos = len(self.order)
        self._render(other_groups, other_loose)
        self.tiles.addStretch(1)

    def _render(self, groups: list[tuple[dict, list[dict]]], loose: list[dict]) -> None:
        for feature, stories in groups:
            self._add(feature, 0)
            for s in stories:
                self._add(s, 1)  # Stories eingerückt unter ihrem Feature
        if loose:
            self.tiles.addWidget(QLabel("<span style='color:#888'>ohne Feature</span>"))
            for s in loose:
                self._add(s, 1)

    def mark_running(self, item_id: int | None) -> None:
        for iid, b in self._buttons.items():
            b.setChecked(iid == item_id)
