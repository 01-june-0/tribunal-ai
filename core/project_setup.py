"""Installing a project's dependencies inside the project, the way the agent-mode Maker did in its worktree.

The Maker's node_modules and .venv stay in its worktree (they are ignored, never applied), so once a result is
applied the project needs the same packages before its tests can be run again there. What is installed is read from
the project's own files, not from anything the Maker said: requirements.txt or pyproject.toml into ./.venv (plus
pytest when the tests use it), package.json with npm into ./node_modules. Nothing is installed outside the project.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

TIMEOUT = 900


def _venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _uses_pytest(root: Path) -> bool:
    for name in ("pytest.ini", "conftest.py"):
        if (root / name).exists():
            return True
    tests = root / "tests"
    return tests.is_dir() and any(p.name.startswith("test_") and p.suffix == ".py" for p in tests.rglob("*.py"))


def steps(root: Path) -> List[List[str]]:
    """The commands that would install this project's dependencies, in order (empty when there is nothing to do)."""
    from core.pythons import tribunal_python
    root = Path(root)
    out: List[List[str]] = []
    py = _venv_python(root)
    wants_python = (root / "requirements.txt").is_file() or (root / "pyproject.toml").is_file()
    if wants_python:
        if not py.is_file():
            out.append([tribunal_python(), "-m", "venv", ".venv"])
        pip = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
        if (root / "requirements.txt").is_file():
            out.append(pip + ["-r", "requirements.txt"])
        elif "[project]" in (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace"):
            out.append(pip + ["-e", "."])
        if _uses_pytest(root):
            out.append(pip + ["pytest"])
    package = root / "package.json"
    if package.is_file() and not (root / "node_modules").is_dir():
        import json
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict) and (data.get("dependencies") or data.get("devDependencies")):
            npm = shutil.which("npm")
            if npm:
                out.append([npm, "ci" if (root / "package-lock.json").is_file() else "install", "--no-audit", "--no-fund"])
    return out


def install(root: Path, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Runs steps(root) in the project. Returns {"ran": [...], "ok": bool, "output": tail}; a failure stops there."""
    from core.env_utils import get_sanitized_env
    ran, tail = [], ""
    for argv in steps(Path(root)):
        try:
            res = subprocess.run(argv, cwd=str(root), env=env or get_sanitized_env(), capture_output=True, text=True,
                                 timeout=TIMEOUT, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ran": ran + [" ".join(argv)], "ok": False, "output": str(exc)[-2000:]}
        ran.append(" ".join(argv))
        tail = ((res.stdout or "") + (res.stderr or ""))[-2000:]
        if res.returncode != 0:
            return {"ran": ran, "ok": False, "output": tail}
    return {"ran": ran, "ok": True, "output": tail}
