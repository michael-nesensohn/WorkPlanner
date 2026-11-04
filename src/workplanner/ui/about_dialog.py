"""„Hilfe → Über WorkPlanner / Updates“: Logo, Name, Link zum Projekt und die manuelle Update-Prüfung."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout)

from .. import updater
from .._version import __version__
from ..icon import make_pixmap
from .license_dialog import LicenseDialog


class AboutDialog(QDialog):
    _checked = Signal(object, object)     # (Release | None, Fehlertext | None)
    _progress = Signal(int, int)          # (geladen, gesamt)
    _downloaded = Signal(object, object)  # (Pfad | None, Fehlertext | None)

    def __init__(self, parent=None, fetch: Callable = updater.fetch_latest, download: Callable = updater.download,
                 install: Callable[[Path], None] | None = None):
        super().__init__(parent)
        self._fetch, self._download, self._install = fetch, download, install
        self.release: updater.Release | None = None
        self.setWindowTitle("Über WorkPlanner")
        self.setMinimumWidth(470)

        logo = QLabel()
        logo.setPixmap(make_pixmap(88))
        logo.setAlignment(Qt.AlignTop)
        name = QLabel("<span style='font-size:22px;font-weight:600'>WorkPlanner</span><br>"
                      f"Version {__version__}<br>"
                      "<span style='color:#667'>Zeiterfassung und Tätigkeitsdokumentation</span><br><br>"
                      "von <b>Michael Nesensohn</b><br>"
                      f"<a href='{updater.PAGE}'>github.com/{updater.REPO}</a><br>"
                      "<span style='color:#667'>MIT-Lizenz – ohne Gewährleistung und ohne Haftung</span>")
        name.setTextFormat(Qt.RichText)
        name.setOpenExternalLinks(True)
        name.setTextInteractionFlags(Qt.TextBrowserInteraction)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(logo)
        head.addWidget(name, 1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#c9d3e0")
        self.status = QLabel("Updates werden nur auf Wunsch gesucht.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(130)
        self.notes.hide()
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        self.check_btn = QPushButton("Nach Updates suchen")
        self.check_btn.clicked.connect(self._check)
        self.update_btn = QPushButton()
        self.update_btn.setStyleSheet("font-weight:600")
        self.update_btn.clicked.connect(self._start_update)
        self.update_btn.hide()
        license_btn = QPushButton("Lizenz …")
        license_btn.clicked.connect(lambda: LicenseDialog(self).exec())
        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_btn)
        buttons.addStretch(1)
        buttons.addWidget(license_btn)
        buttons.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(line)
        lay.addWidget(self.status)
        lay.addWidget(self.notes)
        lay.addWidget(self.bar)
        lay.addWidget(self.update_btn)   # eigene Zeile, damit der Knopftext nicht abgeschnitten wird
        lay.addLayout(buttons)
        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)

    # --- Prüfen --------------------------------------------------------------------------------
    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:  # Fenster wurde inzwischen geschlossen
            pass

    def _check(self) -> None:
        self.check_btn.setEnabled(False)
        self.update_btn.hide()
        self.notes.hide()
        self.status.setText("Suche nach Updates …")

        def work():
            try:
                self._emit(self._checked, self._fetch(), None)
            except updater.UpdateError as ex:
                self._emit(self._checked, None, str(ex))
            except Exception as ex:  # noqa: BLE001 – den Thread nie still sterben lassen
                self._emit(self._checked, None, f"Unerwarteter Fehler: {ex}")
        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, release, error) -> None:
        self.check_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        self.release = release
        if not updater.is_newer(release.version):
            self.status.setText(f"<span style='color:#1b7f3b'>WorkPlanner ist aktuell</span> "
                                f"(neueste Version: {release.version}).")
            return
        self.status.setText(f"<b>Version {release.version} ist verfügbar</b> (installiert: {__version__}). "
                            "Aktualisiert wird nur, wenn Sie unten auf den Knopf klicken.")
        self.notes.setPlainText(release.notes or "Keine Beschreibung zum Release.")
        self.notes.show()
        self.update_btn.setText(f"Jetzt auf Version {release.version} aktualisieren")
        self.update_btn.show()

    # --- Aktualisieren ---------------------------------------------------------------------------------
    def _start_update(self) -> None:
        if self.release is None:
            return
        release = self.release
        self.update_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText("Der Installer wird geladen und geprüft …")

        def work():
            try:
                path = self._download(release, progress=lambda done, total: self._emit(self._progress, done, total))
                self._emit(self._downloaded, path, None)
            except updater.UpdateError as ex:
                self._emit(self._downloaded, None, str(ex))
            except Exception as ex:  # noqa: BLE001
                self._emit(self._downloaded, None, f"Unerwarteter Fehler: {ex}")
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(done * 100 / total))

    def _on_downloaded(self, path, error) -> None:
        self.bar.hide()
        self.check_btn.setEnabled(True)
        self.update_btn.setEnabled(True)
        if error:
            self.status.setText(f"<span style='color:#c0392b'>⚠ {error}</span>")
            return
        if self._install is None:  # Testlauf: nichts installieren
            self.status.setText(f"Geladen und geprüft: {path}<br>(Im Testlauf wird der Installer nicht gestartet.)")
            return
        self.status.setText("Geprüft. Der Installer startet, WorkPlanner schließt sich dazu und öffnet sich danach "
                            "wieder. Ihre Daten bleiben erhalten.")
        self._install(path)
