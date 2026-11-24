"""
Canonical DB path resolver for TRIBUNAL AI.

Every component (StateMachine, ChatManager, ProviderManager, dashboard) must obtain the
SQLite path through get_db_path(). The path is absolute and anchored at Tribunal's home (the source
checkout, or the per-user data folder of an installed copy - core/paths.py), so running the dashboard or CLI from a different cwd can never create a split-brain DB.

Test isolation: when DIRECTOR_TESTING=1 and TEST_DB_PATH is set, that path is returned instead.
Another data set: TRIBUNAL_DB_PATH (an absolute path) moves the DB and what is kept next to it — missions, locks,
call traces. It does NOT move runs/, role settings or the bridge token, so it is not a way to run a second real
console; scripts/demo_console.py uses it, behind a read-only server, to show invented data.
"""
import os
from pathlib import Path

from core.paths import CODE_ROOT as SOURCE_ROOT, data_dir

DEFAULT_DB_PATH = data_dir() / "director.db"       # the checkout's data/ when run from source (core/paths.py)


def get_db_path() -> Path:
    if os.environ.get("DIRECTOR_TESTING") == "1" and os.environ.get("TEST_DB_PATH"):
        return Path(os.environ["TEST_DB_PATH"]).resolve()
    override = os.environ.get("TRIBUNAL_DB_PATH")
    if override:
        if not Path(override).is_absolute():       # never fall back to the real records by accident
            raise ValueError(f"TRIBUNAL_DB_PATH must be an absolute path, got {override!r}")
        return Path(override)
    return DEFAULT_DB_PATH


def get_lock_dir() -> Path:
    """Directory for cross-process lock files (next to the DB; isolated under TEST_DB_PATH in tests)."""
    return get_db_path().parent / "locks"
