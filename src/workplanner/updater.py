"""Updates aus den GitHub-Releases – immer nur auf ausdrücklichen Wunsch (Hilfe → Über WorkPlanner / Updates).

Ablauf: neuestes Release abfragen, Version vergleichen, Installer laden, SHA-256 prüfen, Installer starten. Es wird nur
von github.com/<REPO> geladen und nur gestartet, wenn die von GitHub gemeldete Prüfsumme der Datei stimmt."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ._version import __version__

REPO = "michael-nesensohn/WorkPlanner"
PAGE = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"{PAGE}/releases/download/"
INSTALLER = re.compile(r"^WorkPlanner-Setup-[\d.]+\.exe$")
TIMEOUT = 15


class UpdateError(Exception):
    """Fehler beim Prüfen oder Laden (mit lesbarer Meldung)."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    notes: str
    page: str
    asset: str      # Dateiname des Installers
    url: str
    sha256: str


def parse_version(text: str) -> tuple[int, ...]:
    """„v0.1.7“ oder „0.1.7“ -> (0, 1, 7); alles andere wirft UpdateError."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    if not m:
        raise UpdateError(f"Unbekannte Versionsangabe: {text!r}")
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _open(url: str, opener: Callable | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": f"WorkPlanner/{__version__}",
                                                   "Accept": "application/vnd.github+json"})
    return (opener or urllib.request.urlopen)(request, timeout=TIMEOUT)


def fetch_latest(opener: Callable | None = None) -> Release:
    """Neuestes veröffentlichtes Release. UpdateError, wenn GitHub nicht erreichbar ist oder das Release unbrauchbar ist."""
    try:
        with _open(API, opener) as response:
            data = json.load(response)
    except urllib.error.HTTPError as ex:
        raise UpdateError("Auf GitHub gibt es noch kein Release." if ex.code == 404 else
                          f"GitHub antwortet mit Fehler {ex.code}.") from ex
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as ex:
        raise UpdateError(f"GitHub ist nicht erreichbar ({getattr(ex, 'reason', ex)}).") from ex
    tag = str(data.get("tag_name", ""))
    version = ".".join(str(p) for p in parse_version(tag))
    asset = next((a for a in data.get("assets", []) if INSTALLER.match(str(a.get("name", "")))), None)
    if asset is None:
        raise UpdateError(f"Das Release {tag} enthält keinen Installer.")
    url = str(asset.get("browser_download_url", ""))
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("Der Installer liegt nicht im Repository von WorkPlanner; er wird nicht geladen.")
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        raise UpdateError("GitHub meldet keine Prüfsumme für den Installer; er wird nicht geladen.")
    return Release(tag, version, str(data.get("body") or "").strip(), str(data.get("html_url") or PAGE),
                   str(asset["name"]), url, digest.split(":", 1)[1].lower())


def download(release: Release, progress: Callable[[int, int], None] | None = None, opener: Callable | None = None,
            folder: Path | None = None) -> Path:
    """Lädt den Installer und prüft die Prüfsumme; bei Abweichung wird die Datei gelöscht und UpdateError geworfen."""
    folder = folder or Path(tempfile.gettempdir()) / "WorkPlanner-Update"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.asset
    sha = hashlib.sha256()
    try:
        with _open(release.url, opener) as response, open(target, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Der Download ist fehlgeschlagen ({getattr(ex, 'reason', ex)}).") from ex
    if sha.hexdigest() != release.sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("Die Prüfsumme der heruntergeladenen Datei stimmt nicht – der Installer wird nicht gestartet.")
    return target


def launch_installer(path: Path) -> subprocess.Popen:
    """Startet den Installer als Update: mit Fortschrittsanzeige (ohne Rückfragen) und startet WorkPlanner danach neu."""
    return subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"],
                            close_fds=True)
