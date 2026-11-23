"""Root launcher script for TuxHarbor (also used as PyInstaller entry point)."""

from tuxharbor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
