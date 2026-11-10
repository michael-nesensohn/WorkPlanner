r"""Versteckte Einstellungen aus einer optionalen `workplanner.ini` im Datenordner (%APPDATA%\WorkPlanner, bzw.
WORKPLANNER_DATA). Sie gibt es in der Oberfläche absichtlich nicht; wer sie braucht, legt die Datei von Hand an:

    [export]
    show_start_end = 1      ; blendet die Export-Spalten „Start“ und „Ende“ ein
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path


def ini_path() -> Path:
    custom = os.environ.get("WORKPLANNER_DATA")
    return (Path(custom) if custom else Path(os.environ.get("APPDATA") or Path.home()) / "WorkPlanner") / "workplanner.ini"


def _flag(section: str, key: str) -> bool:
    """Fehlende, unlesbare oder fehlerhafte Datei = aus."""
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    try:
        parser.read(ini_path(), encoding="utf-8")
        return parser.getboolean(section, key, fallback=False)
    except (OSError, configparser.Error, ValueError):
        return False


def export_start_end_enabled() -> bool:
    return _flag("export", "show_start_end")
