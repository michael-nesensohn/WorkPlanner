"""Erhöht die Patch-Version (x.y.z -> x.y.z+1) in pyproject.toml und schreibt sie nach src/workplanner/_version.py.

Die Build-Skripte rufen das vor jedem Bau auf, damit Programm und Installer immer eine neue Version tragen.
`--keep` schreibt nur _version.py aus pyproject.toml (ohne zu erhöhen)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
VERSION_PY = ROOT / "src" / "workplanner" / "_version.py"


def main(keep: bool = False) -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.M)
    if not m:
        raise SystemExit("version = \"x.y.z\" in pyproject.toml nicht gefunden")
    major, minor, patch = map(int, m.groups())
    version = f"{major}.{minor}.{patch if keep else patch + 1}"
    if not keep:
        PYPROJECT.write_text(text[:m.start()] + f'version = "{version}"' + text[m.end():], encoding="utf-8", newline="")
    VERSION_PY.write_text(f'"""Wird von tools/bump_version.py geschrieben."""\n__version__ = "{version}"\n',
                          encoding="utf-8")
    return version


if __name__ == "__main__":
    print(main("--keep" in sys.argv))
