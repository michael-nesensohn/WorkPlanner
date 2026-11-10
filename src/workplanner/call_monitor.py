r"""Erkennt Teams-Anrufe: Windows merkt sich je App, wann das Mikrofon zuletzt geöffnet und geschlossen wurde
(HKCU\...\CapabilityAccessManager\ConsentStore\microphone). Solange Teams das Mikrofon offen hat, läuft
ein Anruf bzw. eine Besprechung – auch bei stummgeschaltetem Mikrofon."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
_FILETIME_UNIX = 116444736000000000  # 100-ns-Schritte zwischen 1601 und 1970
MIN_CALL = timedelta(seconds=5)       # kürzere Mikrofon-Zugriffe (Klingeln, Pegeltest) werden ignoriert


@dataclass(frozen=True)
class Call:
    start: datetime
    end: datetime

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def _from_filetime(value: int) -> datetime:
    return datetime.fromtimestamp((value - _FILETIME_UNIX) / 1e7)  # lokale Zeit, ohne Zeitzone wie der Rest der App


def read_mic_usage() -> tuple[datetime | None, bool]:
    """(Beginn der laufenden bzw. letzten Teams-Nutzung, Mikrofon gerade offen?). Ohne Windows/Teams: (None, False)."""
    try:
        import winreg
    except ImportError:
        return None, False
    best: tuple[datetime, int, int] | None = None
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STORE)
    except OSError:
        return None, False
    with root:
        for parent in ("", "NonPackaged"):
            try:
                holder = winreg.OpenKey(root, parent) if parent else root
            except OSError:
                continue
            with holder:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(holder, i)
                    except OSError:
                        break
                    i += 1
                    if "teams" not in name.lower():
                        continue
                    try:
                        with winreg.OpenKey(holder, name) as key:
                            start = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
                            stop = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
                    except OSError:
                        continue
                    if start and (best is None or start > best[1]):
                        best = (_from_filetime(start), start, stop)
    if best is None:
        return None, False
    start_dt, start, stop = best
    return start_dt, stop == 0 or stop < start


class CallMonitor:
    """`poll()` regelmäßig aufrufen; liefert den Anruf, sobald er beendet ist."""

    def __init__(self, reader: Callable[[], tuple[datetime | None, bool]] = read_mic_usage,
                 clock: Callable[[], datetime] = datetime.now):
        self._reader, self._clock = reader, clock
        self._since: datetime | None = None   # Beginn des laufenden Anrufs

    @property
    def since(self) -> datetime | None:
        return self._since

    @property
    def active(self) -> bool:
        return self._since is not None

    def poll(self) -> Call | None:
        start, open_ = self._reader()
        now = self._clock()
        if open_ and start is not None:
            if self._since is None:
                self._since = start
            return None
        if self._since is None:
            return None
        began, self._since = self._since, None
        call = Call(began, now)
        return call if call.duration >= MIN_CALL else None
