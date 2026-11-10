"""Start mit Windows über den Run-Schlüssel der aktuellen Benutzerin/des aktuellen Benutzers.

Es sind keine Administratorrechte nötig; der Eintrag gilt nur für das eigene Konto.
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "WorkPlanner"
TRAY_FLAG = "--tray"  # startet ohne sichtbares Fenster, nur als Symbol im Tray


def command(tray: bool) -> str:
    """Befehl für den Autostart: die .exe (gebaut) bzw. pythonw + main.py (aus dem Quelltext)."""
    if getattr(sys, "frozen", False):
        parts = [f'"{sys.executable}"']
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")  # ohne Konsolenfenster
        interpreter = pythonw if pythonw.exists() else Path(sys.executable)
        parts = [f'"{interpreter}"', f'"{Path(__file__).resolve().parents[1] / "main.py"}"']
    if tray:
        parts.append(TRAY_FLAG)
    return " ".join(parts)


def _winreg():
    import winreg
    return winreg


def is_enabled(name: str = APP_NAME) -> bool:
    if sys.platform != "win32":
        return False
    w = _winreg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY) as key:
            w.QueryValueEx(key, name)
        return True
    except FileNotFoundError:
        return False


def enable(tray: bool, name: str = APP_NAME) -> None:
    w = _winreg()
    with w.CreateKey(w.HKEY_CURRENT_USER, RUN_KEY) as key:
        w.SetValueEx(key, name, 0, w.REG_SZ, command(tray))


def disable(name: str = APP_NAME) -> None:
    if sys.platform != "win32":
        return
    w = _winreg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as key:
            w.DeleteValue(key, name)
    except FileNotFoundError:
        pass
