"""Kacheln der Schnellauswahl (Projekte und DevOps-Features)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton


class ElidedLabel(QLabel):
    """Einzeiliger Text, der bei Platzmangel mit „…“ gekürzt wird (statt die Kachel zu verbreitern)."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setMinimumWidth(10)

    def paintEvent(self, event):
        painter = QPainter(self)
        text = QFontMetrics(self.font()).elidedText(self.text(), Qt.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), int(Qt.AlignVCenter | Qt.AlignLeft), text)


class TileButton(QPushButton):
    """Kachel mit Name links und einem kleinen Hinweis (Tastenkürzel bzw. ID) rechts."""

    def __init__(self, text: str, key_hint: str, bold: bool = True, number: str = "", number_width: int = 0):
        super().__init__(objectName="tile")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        name = ElidedLabel(text)
        parts = []
        if number_width:  # Projektnummer in fester Spalte, damit alle Namen untereinander beginnen
            num = QLabel(number)
            num.setFixedWidth(number_width)
            num.setStyleSheet("color:#4a5568;font-weight:400;background:transparent")
            parts.append(num)
        name.setStyleSheet(f"font-weight:{600 if bold else 400};background:transparent")
        key = QLabel(key_hint)
        key.setStyleSheet("color:#7b8798;font-size:11px;font-weight:400;background:transparent")
        for w in (*parts, name, key):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        for w in parts:
            lay.addWidget(w)
        lay.addWidget(name, 1)
        lay.addWidget(key)
