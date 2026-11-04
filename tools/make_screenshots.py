"""Erzeugt die Bildschirmfotos für die README (docs/screenshots/*.png) aus der echten Oberfläche mit Beispieldaten.

    python tools/make_screenshots.py

Nutzt tools/manual_screens.py (nur Beispieldaten, nie echte) und schneidet leere Flächen ab. Nach einer Änderung der
Oberfläche neu ausführen und die Bilder mit einchecken.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "screenshots"
# Name in der README: (Quelle, Höhe in Pixeln oder None = ganz)
PICTURES = {
    "heute": ("heute", None),
    "woche": ("woche_eintraege", 360),
    "berichte": ("berichte", 560),
    "einstellungen": ("einstellungen", 480),
    "outlook-import": ("outlook_import", None),
    "teams-anruf": ("call_dialog", None),
}

if __name__ == "__main__":
    TARGET.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(ROOT / "tools" / "manual_screens.py"), tmp], check=True)
        for name, (source, height) in PICTURES.items():
            with Image.open(Path(tmp) / f"{source}.png") as im:
                if height and height < im.height:
                    im = im.crop((0, 0, im.width, height))
                im.convert("RGB").save(TARGET / f"{name}.png", optimize=True)
    for f in sorted(TARGET.glob("*.png")):
        print(f.name, f"{f.stat().st_size // 1024} KB")
