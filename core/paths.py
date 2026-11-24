"""Where Tribunal keeps its code, and where it keeps what it writes.

Two different places once Tribunal is installed as a program (docs/PACKAGING.md):

- CODE_ROOT — the code, the console's static files, the default config.yaml and companion.json. Read only.
- home()    — the records and the machine's own settings: data/ (database, missions, tokens, logs), runs/ (one folder
              per run), config.yaml / config.local.yaml / companion.local.json written by the person.

Run from a source checkout (how it is developed), home() IS the checkout, so data/ and runs/ stay exactly where they
always were. Installed (the code sits in a site-packages folder), home() is the platform's per-user data folder.
TRIBUNAL_HOME (an absolute path) chooses another place - for a portable copy or a test.

The finer overrides keep working on top: TRIBUNAL_DB_PATH moves the database and what lives next to it
(core/db_path.py), TRIBUNAL_RUNS_DIR moves runs/ (the demo console uses both).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Tribunal AI"


def installed() -> bool:
    """True when the code runs from an installed package rather than from a checkout of the repository."""
    return any(part in ("site-packages", "dist-packages") for part in CODE_ROOT.parts)


def platform_home() -> Path:
    """The per-user data folder this platform expects for an application."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "tribunal-ai"


def home() -> Path:
    chosen = os.environ.get("TRIBUNAL_HOME")
    if chosen:
        if not Path(chosen).is_absolute():          # never fall back to the real records by accident
            raise ValueError(f"TRIBUNAL_HOME must be an absolute path, got {chosen!r}")
        return Path(chosen)
    return platform_home() if installed() else CODE_ROOT


def data_dir() -> Path:
    return home() / "data"


def runs_dir() -> Path:
    elsewhere = os.environ.get("TRIBUNAL_RUNS_DIR")   # the demo console reads an invented set, never the real records
    return Path(elsewhere) if elsewhere else home() / "runs"


def code_file(*parts: str) -> Path:
    """A file that ships with the code (console page, default config, helper script)."""
    return CODE_ROOT.joinpath(*parts)
