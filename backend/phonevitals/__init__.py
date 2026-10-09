"""PhoneVitals backend."""

import os
from pathlib import Path


def _version() -> str:
    # Inside the snap, the version it was built as; in the packaged desktop
    # app, the one Electron passes; in a source checkout the VERSION file at
    # the repository root, the single source of truth.
    for name in ("SNAP_VERSION", "PHONEVITALS_VERSION"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


__version__ = _version()
