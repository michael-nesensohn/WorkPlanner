"""Globale Tastenkombination (Windows): funktioniert auch, wenn ein anderes Programm vorn ist."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, Qt
from PySide6.QtGui import QKeySequence

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
QT_F1 = int(Qt.Key_F1.value)
VK_F1 = 0x70


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """„Ctrl+Alt+W“ -> (Windows-Modifikatoren, virtueller Tastencode); None, wenn nicht nutzbar.

    Erlaubt sind Buchstaben, Ziffern, F1–F12 und Leertaste, jeweils mit mindestens einem
    Modifikator (Strg, Alt, Umschalt, Windows), damit normales Tippen nicht abgefangen wird."""
    seq = QKeySequence(text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    mods, key = combo.keyboardModifiers(), int(combo.key().value)
    win_mods = ((MOD_CONTROL if mods & Qt.ControlModifier else 0) | (MOD_ALT if mods & Qt.AltModifier else 0)
                | (MOD_SHIFT if mods & Qt.ShiftModifier else 0) | (MOD_WIN if mods & Qt.MetaModifier else 0))
    if not win_mods:
        return None
    if 0x41 <= key <= 0x5A or 0x30 <= key <= 0x39 or key == 0x20:   # A–Z, 0–9, Leertaste: Qt = VK
        return win_mods, key
    if QT_F1 <= key <= QT_F1 + 11:
        return win_mods, VK_F1 + key - QT_F1
    return None


class GlobalHotkey(QAbstractNativeEventFilter):
    """Meldet eine Kombination bei Windows an und ruft `callback` (im GUI-Thread) bei Druck."""
    _next_id = 0xB000

    def __init__(self, callback: Callable[[], None]):
        super().__init__()
        self._callback = callback
        self._id: int | None = None
        self._filter_installed = False

    def register(self, text: str) -> str:
        """Meldet die Kombination an. Rückgabe: leer bei Erfolg, sonst eine lesbare Fehlermeldung."""
        self.unregister()
        if not text:
            return ""
        parsed = parse_hotkey(text)
        if parsed is None:
            return "Bitte eine Taste (Buchstabe, Ziffer, F1–F12) zusammen mit Strg, Alt, Umschalt oder Windows wählen."
        if sys.platform != "win32":
            return "Globale Tastenkombinationen gibt es nur unter Windows."
        GlobalHotkey._next_id += 1
        hotkey_id = GlobalHotkey._next_id
        if not ctypes.windll.user32.RegisterHotKey(None, hotkey_id, parsed[0] | MOD_NOREPEAT, parsed[1]):
            if ctypes.GetLastError() == ERROR_HOTKEY_ALREADY_REGISTERED:
                return "Diese Kombination wird schon von einem anderen Programm benutzt."
            return "Die Kombination konnte nicht angemeldet werden."
        self._id = hotkey_id
        if not self._filter_installed:
            QCoreApplication.instance().installNativeEventFilter(self)
            self._filter_installed = True
        return ""

    def unregister(self) -> None:
        if self._id is not None and sys.platform == "win32":
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
        self._id = None

    def nativeEventFilter(self, event_type, message):
        if self._id is not None and bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                self._callback()
                return True, 0
        return False, 0
