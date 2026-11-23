"""The three roles were renamed: HEAD / BUILDER / REVIEWER -> ARCHITECT / MAKER / INSPECTOR.

Everything written before the rename still has the old words in it: rows in the database, the role settings file,
config files, mission records and the files of earlier runs. This module is the one place that knows the old names;
the rest of the code only speaks the new ones. Nothing here touches free text (a sentence that says "HEAD" may mean
git's HEAD), only keys, role codes and whole-token identifiers.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

ROLES = ("ARCHITECT", "MAKER", "INSPECTOR")
OLD_TO_NEW = {"HEAD": "ARCHITECT", "BUILDER": "MAKER", "REVIEWER": "INSPECTOR"}
# keys that contain "head" in git's sense and were never role names
_KEEP = {"head_exists", "head_commit", "head_before", "head_line", "results_head", "with_head", "expected_head", "main_head",
         "wt_head", "source_head_unchanged"}
_ROLE_LIST = re.compile(r"^\s*(HEAD|BUILDER|REVIEWER|ARCHITECT|MAKER|INSPECTOR|BACKUP|NONE|UNKNOWN)(\s*[,·]\s*"
                        r"(HEAD|BUILDER|REVIEWER|ARCHITECT|MAKER|INSPECTOR|BACKUP|NONE|UNKNOWN))*\s*$")
_CODE = re.compile(r"(?<![A-Za-z])(HEAD|BUILDER|REVIEWER)(?=_[A-Z])")          # REVIEWER_FAIL_CLOSED, HEAD_EXCEPTION ...
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_VERBATIM = {"projects", "commands", "verify", "verification"}      # user data below these keys: paths, command lines
OLD_FILES = {"maker.json": "builder.json", "maker_attempts.json": "builder_attempts.json",
             "maker_cli.json": "builder_cli.json", "maker_cli_attempts.json": "builder_cli_attempts.json"}


def rename_key(key: str) -> str:
    """An identifier or key in the new spelling ('head_provider' -> 'architect_provider', 'builder' -> 'maker')."""
    if not isinstance(key, str) or key in _KEEP or not _IDENT.match(key):      # a path or a sentence is not a name
        return key
    out = key.replace("BUILDER", "MAKER").replace("Builder", "Maker").replace("builder", "maker")
    out = out.replace("REVIEWER", "INSPECTOR").replace("Reviewer", "Inspector").replace("reviewer", "inspector")
    out = re.sub(r"(?<![A-Za-z])HEAD(?![A-Za-z])", "ARCHITECT", out)
    out = re.sub(r"Head(?![a-z])", "Architect", out)
    return re.sub(r"(?<![A-Za-z])head(?![a-z])", "architect", out)


def canon_role(value: Any) -> Any:
    """A role code, or a list of them as text ('HEAD, REVIEWER'), in the new names. Anything else is returned as is."""
    if isinstance(value, str) and _ROLE_LIST.match(value):
        return re.sub(r"HEAD|BUILDER|REVIEWER", lambda m: OLD_TO_NEW[m.group(0)], value)
    return value


def canon_codes(text: Any) -> Any:
    """Reason codes inside a line of text (REVIEWER_FAIL_CLOSED -> INSPECTOR_FAIL_CLOSED). Plain words are left alone."""
    return _CODE.sub(lambda m: OLD_TO_NEW[m.group(1)], text) if isinstance(text, str) else text


def canon(data: Any) -> Any:
    """A record read from an older file: keys renamed, role codes renamed, everything else untouched.
    When a record has both spellings of a key, the new one wins."""
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            new = rename_key(key) if isinstance(key, str) else key
            if new != key and new in data:
                continue
            out[new] = value if new in _VERBATIM else canon(value)
        return out
    if isinstance(data, list):
        return [canon(item) for item in data]
    return canon_role(data)


def old_file(directory: Path, name: str) -> Optional[Path]:
    """The file of an earlier run that holds what `name` holds now (builder.json for maker.json), if it is there."""
    old = OLD_FILES.get(name)
    path = Path(directory) / old if old else None
    return path if path and path.exists() else None


# ------------------------------------------------------------------ the database
_COLUMNS = (("chat_sessions", "head_provider", "architect_provider"), ("result_state", "reviewer_state", "inspector_state"))
_ROLE_VALUES = (("ai_usage", "role"), ("chat_messages", "role"))
_WATCHED = {"chat_sessions", "result_state", "ai_usage", "chat_messages", "provider_health"}
_DONE: set = set()


def migrate_db(conn: sqlite3.Connection) -> None:
    """Bring a database written before the rename up to date. Safe to call every time a store opens: it looks first and
    changes only what still carries an old name. Tables that do not exist yet are skipped."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        where = conn.execute("PRAGMA database_list").fetchone()[2]
    except Exception:
        where = ""
    seen = (where, frozenset(tables & _WATCHED))
    if where and seen in _DONE:
        return
    for table, old, new in _COLUMNS:
        if table in tables:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if old in columns and new not in columns:
                try:
                    conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
                except sqlite3.OperationalError:       # another process renamed it between the look and the change
                    if new not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
                        raise
    for table, column in _ROLE_VALUES:
        if table in tables:
            for old, new in OLD_TO_NEW.items():
                conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old))
    if "provider_health" in tables:                    # 'HEAD, REVIEWER' style lists
        rows = conn.execute("SELECT provider, current_role FROM provider_health WHERE current_role LIKE '%HEAD%' "
                            "OR current_role LIKE '%BUILDER%' OR current_role LIKE '%REVIEWER%'").fetchall()
        for provider, role in rows:
            conn.execute("UPDATE provider_health SET current_role=? WHERE provider=?", (canon_role(role), provider))
    conn.commit()
    _DONE.add(seen)
