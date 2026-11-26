"""Kleine Linien-Symbole für Knöpfe, mit QPainter gezeichnet (unabhängig von Schriftarten, scharf auf jedem Bildschirm)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

ACCENT = "#2F5597"
_SIZE = 96   # Zeichenfläche; Qt skaliert beim Anzeigen herunter (scharf auch bei hoher Bildschirmauflösung)


def _poly(*pts: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in pts])


def line_icon(kind: str, color: str | None = None) -> QIcon:
    """kind: "edit" (Stift), "to_previous" (Pfeil zum Ende des Vorgängers), "calendar", "list", "plan"."""
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
    elif kind == "calendar":
        p.drawRoundedRect(QRectF(14, 22, 68, 60), 12, 12)                         # Blatt
        p.drawLine(QPointF(14, 42), QPointF(82, 42))                              # Kopfleiste
        p.drawLine(QPointF(32, 12), QPointF(32, 30))                              # Ringe
        p.drawLine(QPointF(64, 12), QPointF(64, 30))
        p.setBrush(QColor(color))
        for x, y in ((30, 56), (48, 56), (66, 56), (30, 70), (48, 70)):           # Tage
            p.drawEllipse(QPointF(x, y), 3.2, 3.2)
    elif kind == "list":
        for y in (26, 48, 70):                                                    # drei Zeilen mit Punkt davor
            p.drawLine(QPointF(36, y), QPointF(82, y))
            p.drawPoint(QPointF(16, y))
    elif kind == "plan":
        p.drawLine(QPointF(14, 14), QPointF(14, 82))                              # Zeitachse
        p.drawRoundedRect(QRectF(28, 16, 54, 22), 7, 7)                           # Blöcke auf der Zeitachse
        p.drawRoundedRect(QRectF(28, 50, 54, 30), 7, 7)
    else:
        raise ValueError(kind)
    p.end()
    return QIcon(pm)


def toggle_icon(kind: str, normal: str | None = None, checked: str = "#ffffff") -> QIcon:
    """Symbol für einen umschaltbaren Knopf: in `normal` (Akzentblau), im eingeschalteten Zustand weiß auf blauem Grund."""
    icon = QIcon()
    icon.addPixmap(line_icon(kind, normal).pixmap(_SIZE, _SIZE), QIcon.Normal, QIcon.Off)
    icon.addPixmap(line_icon(kind, checked).pixmap(_SIZE, _SIZE), QIcon.Normal, QIcon.On)
    icon.addPixmap(line_icon(kind, checked).pixmap(_SIZE, _SIZE), QIcon.Active, QIcon.On)
    return icon
