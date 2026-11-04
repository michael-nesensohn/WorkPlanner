"""Tabellenkopf mit „Alle markieren“-Kästchen in der ersten Spalte."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionButton


class CheckHeader(QHeaderView):
    toggled = Signal(bool)  # True = alle markieren, False = alle abwählen

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._state = Qt.Unchecked
        self.setSectionsClickable(True)

    def set_state(self, state: Qt.CheckState) -> None:
        if state != self._state:
            self._state = state
            self.viewport().update()

    def _box(self) -> QRect:
        return QRect(self.sectionViewportPosition(0) + 6, (self.height() - 13) // 2, 13, 13)

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0:
            return
        opt = QStyleOptionButton()
        opt.rect = self._box()
        opt.state = QStyle.State_Enabled | {Qt.Checked: QStyle.State_On, Qt.PartiallyChecked: QStyle.State_NoChange,
                                            Qt.Unchecked: QStyle.State_Off}[self._state]
        self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, painter, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._box().adjusted(-3, -3, 3, 3).contains(event.position().toPoint()):
            self.toggled.emit(self._state != Qt.Checked)
            return
        super().mousePressEvent(event)
