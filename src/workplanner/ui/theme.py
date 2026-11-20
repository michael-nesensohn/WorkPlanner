"""Helles und dunkles Design.

Alle Stilvorlagen der Oberfläche sind für das helle Design geschrieben. Für das dunkle Design werden ihre Farben beim
Setzen umgerechnet (`remap`), und die Qt-Palette (für alles ohne eigene Stilvorlage) wird dunkel gesetzt. So bleibt der
Quelltext der Fenster unverändert, und ein Wechsel wirkt sofort auf alle offenen Fenster."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

MODES = (("light", "Hell"), ("dark", "Dunkel"), ("system", "Wie Windows"))

# helle Farbe (klein geschrieben) -> dunkle Entsprechung
DARK: dict[str, str] = {
    # Flächen
    "#fafbfd": "#12161f", "#f8fafd": "#151a24", "#f6f8fc": "#1a202c", "#f4f7fb": "#1b2230", "#f4f6f9": "#1d2331",
    "#eef3fa": "#26304a", "#eef1f6": "#262f42", "#e8eef7": "#222b3d", "#e3e8f2": "#252f44", "#e4e7ee": "#2a3040",
    "#e8f1fc": "#1d2c47", "#e3eefb": "#223455", "#dce8fb": "#243a63", "#cfe0fb": "#2c4575", "#d5e1f3": "#2a3b5a",
    "#b9d2fb": "#34528a", "#1b1b1b": "#e5e9f2",
    # Linien
    "#c9d3e0": "#3a4660", "#c9d3e6": "#3a4660", "#d5deea": "#2f3a50", "#e4e9f0": "#2a3345", "#dde3ee": "#2a3345",
    "#e6ebf3": "#262f42", "#e1e6ee": "#2a3345", "#c3ccdd": "#3a4660", "#c4cbd6": "#46526c", "#c3cddb": "#46526c",
    "#b8c1ce": "#46526c", "#9db9e3": "#4a6aa3",
    # Text
    "#1f2937": "#e5e9f2", "#1f3a5f": "#dbe6fb", "#1f2a44": "#e0e7f5", "#445": "#c3cce0", "#667": "#98a3bd",
    "#66708a": "#98a3bd", "#5b6b82": "#9aa8c4", "#4a5a73": "#a9b6cf", "#4a5568": "#a9b6cf", "#5b647a": "#aab3c8",
    "#888": "#8d97ae", "#7b8798": "#8993ab", "#9aa6b6": "#6f7b95", "#9fb0c7": "#7f90ad", "#2f5597": "#8fb2f0",
    "#264a82": "#a9c4f2", "#3f7cf0": "#6a9cff",
    # Zustände
    "#c0392b": "#ff8a80", "#b00020": "#ff8a80", "#7b241c": "#ffb4ab", "#fdecea": "#3b2325", "#f9d6d2": "#4a2a2a",
    "#8a5a00": "#e6b05a", "#b35c00": "#e6a04f", "#3a2a00": "#f1d9a8", "#fde8c8": "#4a3a22", "#fcd9a6": "#5a4524",
    "#ffc866": "#8a6a2a", "#1e7e34": "#55c27a", "#1b7f3b": "#55c27a", "#2e7d32": "#55c27a", "#e2f0d9": "#22392a",
    "#c6efce": "#24402c", "#dcf2e1": "#22392a", "#e6dcf7": "#33294a",
}
_HEX = re.compile(r"#[0-9a-fA-F]{3,6}\b")
_WHITE_BG = re.compile(r"(background(?:-color)?\s*:\s*)(white|#fff(?:fff)?)\b", re.I)
PANEL = "#1a202c"

_state = {"dark": False}
_orig_set_style_sheet = QWidget.setStyleSheet


def is_dark() -> bool:
    return _state["dark"]


def remap(css: str) -> str:
    """Stilvorlage fürs helle Design in die dunkle umrechnen (im hellen Design unverändert)."""
    if not _state["dark"]:
        return css
    css = _WHITE_BG.sub(lambda m: m.group(1) + PANEL, css)
    return _HEX.sub(lambda m: DARK.get(m.group(0).lower(), m.group(0)), css)


def hexcolor(light: str) -> str:
    """Farbe für Zeichencode: die helle oder (im dunklen Design) ihre Entsprechung."""
    return DARK.get(light.lower(), light) if _state["dark"] else light


def qcolor(light: str) -> QColor:
    return QColor(hexcolor(light))


def _set_style_sheet(widget: QWidget, css: str) -> None:
    """Ersatz für QWidget.setStyleSheet: merkt sich die helle Vorlage und setzt die zum Design passende."""
    widget.setProperty("wpQss", css)
    _orig_set_style_sheet(widget, remap(css))


def install() -> None:
    """Einmal aufrufen, bevor Fenster ihre Stilvorlagen setzen."""
    if QWidget.setStyleSheet is not _set_style_sheet:
        QWidget.setStyleSheet = _set_style_sheet


def _palette(dark: bool, app: QApplication) -> QPalette:
    if not dark:
        return app.style().standardPalette()
    p = QPalette()
    roles = {QPalette.Window: "#12161f", QPalette.WindowText: "#e5e9f2", QPalette.Base: PANEL,
             QPalette.AlternateBase: "#171c27", QPalette.Text: "#e5e9f2", QPalette.Button: PANEL,
             QPalette.ButtonText: "#e5e9f2", QPalette.ToolTipBase: PANEL, QPalette.ToolTipText: "#dbe6fb",
             QPalette.Highlight: "#2F5597", QPalette.HighlightedText: "#ffffff", QPalette.Link: "#8fb2f0",
             QPalette.PlaceholderText: "#7f8aa3", QPalette.BrightText: "#ffffff"}
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#6f7b95"))
    return p


def resolve(mode: str, app: QApplication | None = None) -> bool:
    """True, wenn das dunkle Design gilt („system“ folgt Windows)."""
    if mode == "dark":
        return True
    if mode == "system":
        app = app or QApplication.instance()
        try:
            return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:   # ältere Qt-Version
            return False
    return False


def apply(app: QApplication, mode: str, base_css: str) -> bool:
    """Design setzen (Palette, Anwendungs-Stilvorlage und alle schon vorhandenen Fenster). True, wenn sich etwas
    geändert hat."""
    install()
    dark = resolve(mode, app)
    if dark == _state["dark"]:
        return False
    _state["dark"] = dark
    app.setPalette(_palette(dark, app))
    app.setStyleSheet(remap(base_css))
    for widget in app.allWidgets():
        css = widget.property("wpQss")
        if isinstance(css, str):
            _orig_set_style_sheet(widget, remap(css))
    return True
