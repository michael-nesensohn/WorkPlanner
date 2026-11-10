"""Erzeugt assets/workplanner.ico (mehrere Größen) aus dem gezeichneten Uhr-Symbol (src/workplanner/icon.py).

Windows zeigt je nach Ort 16 bis 256 px (Taskleiste, Explorer, Startmenü, Installer); jede Größe wird
einzeln gezeichnet, damit sie scharf bleibt, statt eine große herunterzurechnen.
"""
import sys
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QGuiApplication

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from workplanner.icon import make_pixmap  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]

app = QGuiApplication([])
out = root / "assets" / "workplanner.ico"
out.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    images = []
    for size in SIZES:
        png = Path(tmp) / f"{size}.png"
        if not make_pixmap(size).save(str(png), "PNG"):
            raise SystemExit(f"Symbol {size}px konnte nicht gezeichnet werden.")
        images.append(Image.open(png).convert("RGBA"))
    images[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    for im in images:
        im.close()
print("geschrieben:", out, f"({out.stat().st_size // 1024} KB, Größen {SIZES})")
