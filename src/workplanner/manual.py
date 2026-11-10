"""Wo liegt das Handbuch (PDF)? Der Installer legt es neben das Programm, beim Entwickeln liegt es unter docs/."""
from __future__ import annotations

import sys
from pathlib import Path

NAME = "WorkPlanner-Handbuch.pdf"


def manual_path() -> Path | None:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "Handbuch" / NAME)
    candidates.append(Path(__file__).resolve().parents[2] / "docs" / NAME)
    return next((p for p in candidates if p.exists()), None)
