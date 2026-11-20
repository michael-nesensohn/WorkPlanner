"""Kleine Linien-Symbole für Knöpfe, mit QPainter gezeichnet (unabhängig von Schriftarten, scharf auf jedem Bildschirm)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

ACCENT = "#2F5597"
_SIZE = 96   # Zeichenfläche; Qt skaliert beim Anzeigen herunter (scharf auch bei hoher Bildschirmauflösung)


def _poly(*pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def line_icon(kind: str, color: str | None = None) -> QIcon:
    """kind: "edit" (Stift), "to_previous" (Pfeil zum Ende des Vorgängers)."""
    from . import theme
    color = color or theme.hexcolor(ACCENT)   # im dunklen Design das hellere Blau
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == "edit":
        p.drawPolygon(_poly((18, 78), (24, 56), (60, 20), (76, 36), (40, 72)))   # Stiftkörper mit Spitze unten links
        p.drawLine(QPointF(50, 30), QPointF(66, 46))                              # Zwinge
        p.drawLine(QPointF(24, 56), QPointF(40, 72))                              # Spitzenansatz
        p.drawLine(QPointF(14, 86), QPointF(82, 86))                              # Schreiblinie
    elif kind == "to_previous":
        p.drawLine(QPointF(20, 20), QPointF(20, 76))                              # Anschlag (Ende des Vorgängers)
        p.drawLine(QPointF(78, 48), QPointF(32, 48))                              # Pfeil nach links
        p.drawPolyline(_poly((50, 30), (32, 48), (50, 66)))
    else:
        raise ValueError(kind)
    p.end()
    return QIcon(pm)
