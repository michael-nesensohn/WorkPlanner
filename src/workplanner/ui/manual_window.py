"""Handbuch im Programm: das PDF in einem eigenen Fenster mit Inhaltsverzeichnis, Suche und Zoom."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPointF, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtPdf import QPdfBookmarkModel, QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton, QSplitter, QStackedWidget,
                               QToolButton, QTreeView, QVBoxLayout, QWidget)

MAX_HITS = 200


def _one_line(text) -> str:
    """Treffer-Ausschnitt in eine Zeile (die PDF-Textsuche liefert Zeilenumbrüche als eigenes Zeichen)."""
    return " ".join(str(text or "").replace("⏎", " ").split())


class ManualWindow(QWidget):
    """Eigenständiges Fenster (kein Dialog): lässt sich neben der Arbeit offen halten und merkt sich seine Größe."""

    def __init__(self, path: Path, geometry: bytes | None = None, save_geometry=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("WorkPlanner – Handbuch")
        self.resize(1100, 800)
        self._save_geometry = save_geometry
        self.doc = QPdfDocument(self)
        self.doc.load(str(path))

        self.view = QPdfView()
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        # Inhaltsverzeichnis (aus den Lesezeichen des PDFs)
        self.bookmarks = QPdfBookmarkModel(self)
        self.bookmarks.setDocument(self.doc)
        self.toc = QTreeView()
        self.toc.setModel(self.bookmarks)
        self.toc.setHeaderHidden(True)
        self.toc.setEditTriggers(QTreeView.NoEditTriggers)
        self.toc.clicked.connect(self._toc_clicked)

        # Suche: die Treffer ersetzen das Verzeichnis, solange etwas im Suchfeld steht
        self.search_model = QPdfSearchModel(self)
        self.search_model.setDocument(self.doc)
        self.view.setSearchModel(self.search_model)
        self.hits_model = QStandardItemModel(self)
        self.hits = QListView()
        self.hits.setModel(self.hits_model)
        self.hits.setEditTriggers(QListView.NoEditTriggers)
        self.hits.setWordWrap(True)
        self.hits.clicked.connect(self._hit_clicked)
        self.left = QStackedWidget()
        self.left.addWidget(self.toc)
        self.left.addWidget(self.hits)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen …")
        self.search.setClearButtonEnabled(True)
        self.status = QLabel()
        self.status.setStyleSheet("color:#667")
        self._search_timer = QTimer(self, singleShot=True, interval=300)
        self._search_timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.search.returnPressed.connect(self._next_hit)
        self.search_model.modelReset.connect(self._fill_hits)
        self.search_model.rowsInserted.connect(lambda *_: self._hits_changed.start())
        self._hits_changed = QTimer(self, singleShot=True, interval=150)
        self._hits_changed.timeout.connect(self._fill_hits)

        minus, plus = QToolButton(), QToolButton()
        minus.setText("–")
        plus.setText("+")
        minus.setToolTip("Verkleinern")
        plus.setToolTip("Vergrößern")
        minus.clicked.connect(lambda: self._zoom(1 / 1.15))
        plus.clicked.connect(lambda: self._zoom(1.15))
        fit = QPushButton("Seitenbreite")
        fit.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth))
        self.page_label = QLabel()
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        for w in (minus, plus, fit):
            bar.addWidget(w)
        bar.addWidget(self.page_label)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.left)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 840])
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

        QShortcut(QKeySequence.Find, self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        nav = self.view.pageNavigator()
        nav.currentPageChanged.connect(self._page_changed)
        self._page_changed(0)
        if geometry:
            self.restoreGeometry(geometry)

    # --- Verzeichnis ----------------------------------------------------------------------------
    def _toc_clicked(self, index: QModelIndex) -> None:
        self._goto_bookmark(index)

    def _goto_bookmark(self, index: QModelIndex) -> None:
        page = self.bookmarks.data(index, QPdfBookmarkModel.Role.Page.value)
        if page is None:
            return
        where = self.bookmarks.data(index, QPdfBookmarkModel.Role.Location.value)
        self._jump(int(page), where.y() if isinstance(where, QPointF) else 0.0)

    def goto_page(self, page: int) -> None:
        self.view.pageNavigator().jump(page, QPointF(0, 0), 0)

    def _jump(self, page: int, y: float) -> None:
        """Zur Seite springen und bis zur Höhe `y` (in Punkten ab Seitenanfang) weiterscrollen. QPdfView springt von sich aus nur
        an den Seitenanfang; der Maßstab ergibt sich aus dem Abstand zweier Seitenanfänge."""
        nav, bar = self.view.pageNavigator(), self.view.verticalScrollBar()
        nav.jump(page, QPointF(0, 0), 0)
        top = bar.value()
        if y > 0 and page + 1 < self.doc.pageCount():
            nav.jump(page + 1, QPointF(0, 0), 0)
            scale = (bar.value() - top - self.view.pageSpacing()) / self.doc.pagePointSize(page).height()
            bar.setValue(int(top + y * scale - 16))
        else:
            bar.setValue(top)

    def _chapter_index(self, number: str) -> QModelIndex | None:
        for row in range(self.bookmarks.rowCount(QModelIndex())):
            index = self.bookmarks.index(row, 0, QModelIndex())
            title = str(self.bookmarks.data(index, QPdfBookmarkModel.Role.Title.value))
            if re.match(rf"{re.escape(number)}\D", title):
                return index
        return None

    def chapter_page(self, number: str) -> int | None:
        """Seite (ab 0) des Kapitels „<number>  Titel“ laut Lesezeichen."""
        index = self._chapter_index(number)
        return None if index is None else int(self.bookmarks.data(index, QPdfBookmarkModel.Role.Page.value))

    def show_chapter(self, number: str | None) -> None:
        """Springt zur Überschrift des Kapitels (nicht nur an den Seitenanfang)."""
        index = self._chapter_index(number) if number else None
        if index is not None:
            self._goto_bookmark(index)

    # --- Suche ------------------------------------------------------------------------------------
    def _run_search(self) -> None:
        text = self.search.text().strip()
        self.search_model.setSearchString(text)
        if not text:
            self.left.setCurrentWidget(self.toc)
            self.status.setText("")
            self.hits_model.clear()
            return
        self.left.setCurrentWidget(self.hits)
        self._hits_changed.start()

    def _fill_hits(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        n = self.search_model.rowCount(QModelIndex())
        self.hits_model.clear()
        role = QPdfSearchModel.Role
        for row in range(min(n, MAX_HITS)):
            index = self.search_model.index(row, 0, QModelIndex())
            before = _one_line(self.search_model.data(index, role.ContextBefore.value))
            after = _one_line(self.search_model.data(index, role.ContextAfter.value))
            page = int(self.search_model.data(index, role.Page.value)) + 1
            item = QStandardItem(f"S. {page}: …{before[-30:]} {text} {after[:40]}…")
            item.setData(row, Qt.UserRole)
            self.hits_model.appendRow(item)
        self.status.setText(f"{n} Treffer" if n else "keine Treffer")

    def _hit_clicked(self, index: QModelIndex) -> None:
        self.view.setCurrentSearchResultIndex(int(index.data(Qt.UserRole)))

    def _next_hit(self) -> None:
        n = self.hits_model.rowCount()
        if n:
            current = self.hits.currentIndex().row()
            row = (current + 1) % n
            self.hits.setCurrentIndex(self.hits_model.index(row, 0))
            self.view.setCurrentSearchResultIndex(row)

    # --- Zoom und Seite -------------------------------------------------------------------------------
    def _zoom(self, factor: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.3, min(4.0, self.view.zoomFactor() * factor)))

    def _page_changed(self, page: int) -> None:
        self.page_label.setText(f"Seite {page + 1} / {max(self.doc.pageCount(), 1)}")

    def closeEvent(self, event):
        if self._save_geometry:
            self._save_geometry(bytes(self.saveGeometry()))
        super().closeEvent(event)
