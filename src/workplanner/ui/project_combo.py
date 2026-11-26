"""Projektauswahl mit Spalten: „Nummer | Name“, Nummern und Namen stehen in der aufgeklappten Liste untereinander."""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QApplication, QComboBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem

ROLE_NUMBER = Qt.UserRole + 20
ROLE_NAME = Qt.UserRole + 21
GAP = 10


class ProjectComboDelegate(QStyledItemDelegate):
    """Zeichnet die Einträge der aufgeklappten Liste als Spalten: Nummer, Trennstrich, Name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.number_width = 0

    def sizeHint(self, option, index):
        fm = QFontMetrics(option.font)
        width = self.number_width + 2 * GAP + fm.horizontalAdvance("|") + fm.horizontalAdvance(index.data(ROLE_NAME) or "")
        return QSize(width + 12, max(fm.height() + 8, super().sizeHint(option, index).height()))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.State_Selected)
        painter.save()
        fm = QFontMetrics(opt.font)
        rect = opt.rect.adjusted(6, 0, -6, 0)
        x = rect.left()
        painter.setPen(QColor("#ffffff") if selected else QColor("#1f2937"))
        painter.drawText(QRect(x, rect.top(), self.number_width, rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
                         index.data(ROLE_NUMBER) or "")
        x += self.number_width + GAP
        painter.setPen(QColor("#ffffff") if selected else QColor("#8a94a6"))
        painter.drawText(QRect(x, rect.top(), fm.horizontalAdvance("|"), rect.height()), Qt.AlignVCenter | Qt.AlignLeft, "|")
        x += fm.horizontalAdvance("|") + GAP
        painter.setPen(QColor("#ffffff") if selected else QColor("#1f2937"))
        painter.drawText(QRect(x, rect.top(), rect.right() - x, rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
                         index.data(ROLE_NAME) or "")
        painter.restore()


def fill_project_combo(combo: QComboBox, projects: list[tuple[int, str, str]]) -> None:
    """Füllt die Auswahl mit (id, Nummer, Name). Der gewählte Eintrag zeigt „Nummer | Name“; die aufgeklappte Liste zeigt
    Nummer und Name in Spalten. Ohne Nummer bleibt die Nummernspalte leer, damit alle Namen untereinander stehen."""
    delegate = ProjectComboDelegate(combo)
    fm = QFontMetrics(combo.font())
    delegate.number_width = max((fm.horizontalAdvance(nr) for _, nr, _ in projects), default=0)
    combo.clear()
    for pid, number, name in projects:
        combo.addItem(f"{number} | {name}" if number else name, pid)
        combo.setItemData(combo.count() - 1, number, ROLE_NUMBER)
        combo.setItemData(combo.count() - 1, name, ROLE_NAME)
    combo.setItemDelegate(delegate)
    widest = max((fm.horizontalAdvance(n) for _, _, n in projects), default=0)
    combo.view().setMinimumWidth(delegate.number_width + widest + 2 * GAP + fm.horizontalAdvance("|") + 40)
