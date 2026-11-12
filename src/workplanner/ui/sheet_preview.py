"""Ein Excel-Blatt so gezeigt, wie es aussieht – mit den geplanten Einträgen darüber (nur Anzeige, nichts wird geschrieben).

Grün: neuer Wert in einer leeren Zelle · Orange: ersetzt einen vorhandenen Wert (der alte steht dahinter) ·
Hellgrün (Name/Nummer): neue Projektzeile. Alles andere bleibt unverändert, wie es in der Datei steht."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from ..excel_timesheet import GRID_COLS, GRID_ROWS, PlanLine, RowSetup, SheetView, col_letter, display_text

NEW_BG, REPLACE_BG, SETUP_BG = QColor("#c6efce"), QColor("#fcd9a6"), QColor("#e2f0d9")


def _number(v: float) -> str:
    return f"{v:g}".replace(".", ",")


class SheetPreview(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(GRID_ROWS, GRID_COLS, parent)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setHorizontalHeaderLabels([col_letter(c) for c in range(1, GRID_COLS + 1)])
        self.setVerticalHeaderLabels([str(r) for r in range(1, GRID_ROWS + 1)])
        self.setSelectionMode(QTableWidget.NoSelection)

    def show_plan(self, view: SheetView, lines: list[PlanLine], setups: list[RowSetup]) -> None:
        """`lines`/`setups` nur für dieses Blatt."""
        self.clearSpans()
        self.clearContents()
        for c in range(1, GRID_COLS + 1):
            self.setColumnWidth(c - 1, view.col_px.get(c, 78) or 0)
        for r in range(1, GRID_ROWS + 1):
            self.setRowHeight(r - 1, view.row_px.get(r, 22))
        over: dict[tuple[int, int], tuple[str, QColor, str]] = {}   # Zelle -> (Text, Farbe, Hinweis)
        for s in setups:
            over[s.row, s.col] = (s.value, SETUP_BG, "neue Projektzeile")
        for ln in lines:
            if ln.overwrites:
                over[ln.row, ln.col] = (f"{_number(ln.hours)}  (bisher {display_text(ln.old)})", REPLACE_BG,
                                        f"ersetzt {display_text(ln.old)} durch {_number(ln.hours)}: {ln.project}")
            else:
                over[ln.row, ln.col] = (_number(ln.hours), NEW_BG, f"neu: {ln.project}")
        for r, row in enumerate(view.grid, 1):
            for c, value in enumerate(row, 1):
                style, mark = view.styles.get((r, c)), over.get((r, c))
                text = mark[0] if mark else display_text(value)
                if not (text or style):
                    continue
                item = QTableWidgetItem(text)
                bg = QColor(mark[1]) if mark else QColor(style.bg) if style and style.bg else None
                if bg is not None:
                    item.setBackground(QBrush(bg))
                if mark:
                    item.setForeground(QBrush(QColor("#1b1b1b")))
                    item.setToolTip(mark[2])
                    font = QFont(self.font())
                    font.setBold(True)
                    item.setFont(font)
                    item.setTextAlignment(Qt.AlignCenter)
                elif style:
                    item.setToolTip(text)
                    if style.fg:
                        item.setForeground(QBrush(QColor(style.fg)))
                    if style.bold or style.italic:
                        font = QFont(self.font())
                        font.setBold(style.bold)
                        font.setItalic(style.italic)
                        item.setFont(font)
                    if style.align in ("left", "center", "right"):
                        item.setTextAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
                                               "right": Qt.AlignRight}[style.align] | Qt.AlignVCenter)
                self.setItem(r - 1, c - 1, item)
        for r1, c1, r2, c2 in view.merges:
            self.setSpan(r1 - 1, c1 - 1, r2 - r1 + 1, c2 - c1 + 1)
        if over:   # zur ersten Änderung blättern
            r, c = min(over)
            self.scrollToItem(self.item(r - 1, c - 1) or self.item(r - 1, 0), QTableWidget.PositionAtCenter)
