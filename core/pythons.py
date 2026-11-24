"""Which Python runs what (docs/PACKAGING.md 4절).

Two different needs that used to share `sys.executable`:

- tribunal_python() — Tribunal's own helpers (the folder dialog, a hook, a diagnostic probe). That is the interpreter
  running Tribunal; a bundled app (phase 5) will have to point this somewhere else, and only here.
- project_python(root) — the project's tests. The project's own virtual environment when it has one (its packages
  are there, not in Tribunal's), else Tribunal's interpreter as before (it has pytest).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

_MODULE: Dict[Tuple[str, str], bool] = {}
_VERSION: Dict[str, Optional[str]] = {}


def tribunal_python() -> str:
    if getattr(sys, "frozen", False):              # a bundled app: its own executable is not a Python
        return shutil.which("python3") or shutil.which("python") or sys.executable
    return sys.executable


def project_venv_python(root: Path) -> Optional[str]:
    """The interpreter of the project's own virtual environment (.venv or venv), or None."""
    names = (("Scripts", "python.exe"),) if os.name == "nt" else (("bin", "python"), ("bin", "python3"))
    for env in (".venv", "venv"):
        for parts in names:
            path = Path(root) / env / Path(*parts)
            if path.is_file():
                return str(path)
    return None


def has_module(python: str, module: str) -> bool:
    """Whether that interpreter can import the module (asked once per process)."""
    key = (python, module)
    if key not in _MODULE:
        try:
            _MODULE[key] = subprocess.run([python, "-c", f"import {module}"], capture_output=True, timeout=20,
                                          stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _MODULE[key] = False
    return _MODULE[key]


def project_python(root: Path, needs: Optional[str] = None) -> str:
    """The Python a project's own command should run with. `needs` (e.g. "pytest"): use the project's environment
    only if it has that module, so a project venv without pytest does not turn a passing test run into a failure."""
    own = project_venv_python(root)
    if own and (needs is None or has_module(own, needs)):
        return own
    return tribunal_python()


def version_of(python: str) -> Optional[str]:
    """"3.13.1" for that interpreter, or None when it cannot be asked."""
    if python not in _VERSION:
        if python == sys.executable:
            _VERSION[python] = sys.version.split()[0]
        else:
            try:
                out = subprocess.run([python, "-c", "import sys; print(sys.version.split()[0])"], capture_output=True,
                                     text=True, timeout=20, stdin=subprocess.DEVNULL)
                _VERSION[python] = out.stdout.strip() if out.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                _VERSION[python] = None
    return _VERSION[python]
