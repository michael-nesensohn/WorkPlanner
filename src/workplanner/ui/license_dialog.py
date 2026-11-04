"""„Hilfe → Lizenz“ und „Hilfe → Über WorkPlanner“."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout

from .._version import __version__
from ..license_text import LICENSE_TEXT, SUMMARY_DE, THIRD_PARTY


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lizenz")
        self.resize(720, 560)
        summary = QLabel(SUMMARY_DE)
        summary.setWordWrap(True)
        text = QPlainTextEdit(LICENSE_TEXT.rstrip() + "\n\n" + THIRD_PARTY)
        text.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(summary)
        lay.addWidget(text, 1)
        lay.addWidget(buttons)
        self.text = text


def show_about(parent=None) -> None:
    QMessageBox.about(
        parent, "Über WorkPlanner",
        f"<b>WorkPlanner</b> {__version__}<br>Zeiterfassung und Tätigkeitsdokumentation<br><br>"
        "Copyright (c) 2026 Michael Nesensohn<br>MIT-Lizenz – kostenlos nutzbar, veränderbar und weitergebbar, "
        "<b>ohne Gewährleistung und ohne Haftung</b> des Autors.<br>Den vollständigen Text zeigt „Hilfe → Lizenz“.")
