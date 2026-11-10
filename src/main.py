"""Startskript (auch für PyInstaller)."""
import sys

from workplanner.app import main

if __name__ == "__main__":
    sys.exit(main())
