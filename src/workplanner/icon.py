"""Das Programmsymbol (Uhr), zur Laufzeit gezeichnet – so braucht es keine Bilddatei."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def make_pixmap(size: int = 256) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    c, r = size / 2, size * 0.46
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2F5597"))
    p.drawEllipse(QPointF(c, c), r, r)
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(c, c), r * 0.82, r * 0.82)
    pen = QPen(QColor("#2F5597"), size * 0.07, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(c, c), QPointF(c, c - r * 0.55))             # Minutenzeiger
    p.drawLine(QPointF(c, c), QPointF(c + r * 0.38, c + r * 0.12))  # Stundenzeiger
    p.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(make_pixmap(size))
    return icon
