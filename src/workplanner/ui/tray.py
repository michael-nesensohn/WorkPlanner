"""Symbol im Infobereich der Taskleiste (Tray) mit Menü."""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..icon import app_icon


class TrayIcon(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._hinted = False
        self.icon = QSystemTrayIcon(app_icon(), self)
        self.menu = QMenu()
        self.title_action = self.menu.addAction("WorkPlanner")
        self.title_action.setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("Fenster öffnen", window.show_window)
        self.toggle_action = self.menu.addAction("", window.tray_toggle_task)
        self.menu.addSeparator()
        self.menu.addAction("Beenden", window.quit_app)
        self.menu.aboutToShow.connect(self.refresh)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.icon.show()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.toggle_window()

    def refresh(self) -> None:
        text, running = self.window.tray_status()
        self.title_action.setText(text)
        self.toggle_action.setText("■  Stopp" if running else "▶  Start")

    def set_tooltip(self, text: str) -> None:
        if self.icon.toolTip() != text:
            self.icon.setToolTip(text)

    def hint_once(self) -> None:
        """Beim ersten Verstecken kurz erklären, wo WorkPlanner geblieben ist."""
        if not self._hinted:
            self._hinted = True
            self.icon.showMessage("WorkPlanner läuft weiter",
                                  "Das Symbol im Infobereich öffnet das Fenster; „Beenden“ steht im Menü.",
                                  QSystemTrayIcon.Information, 4000)
