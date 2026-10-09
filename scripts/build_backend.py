#!/usr/bin/env python3
"""Freeze the backend into a self-contained folder for the desktop installers.

PyInstaller bundles the interpreter, the dependencies, the `phonevitals`
package and backend/data into ui/build-backend/phonevitals-backend/, which
electron-builder ships as resources/backend. Run with the Python that has the
backend requirements and PyInstaller installed, on the platform and
architecture being packaged (PyInstaller does not cross-compile).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUT = ROOT / "ui" / "build-backend"


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    PyInstaller.__main__.run([
        str(BACKEND / "main.py"),
        "--name", "phonevitals-backend",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--console",
        "--distpath", str(OUT),
        "--workpath", str(OUT / "work"),
        "--specpath", str(OUT / "work"),
        "--paths", str(BACKEND),
        # Imported by name at runtime (uvicorn's protocol implementations)
        # or lazily inside functions (the demo, the store).
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "phonevitals",
        "--add-data", f"{BACKEND / 'data'}{os.pathsep}data",
        "--exclude-module", "tkinter",
    ])
    shutil.rmtree(OUT / "work", ignore_errors=True)
    print(f"backend frozen into {OUT / 'phonevitals-backend'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
