"""Trying out a finished result: how it is started, and starting it where the person can see it.

Nothing here runs on its own. The console asks for a plan (what would run, and where), shows it, and only after the
person confirms does it ask to start that exact plan - in a new terminal window, never inside Tribunal.

How a result is started comes from the Maker's "run" field when it gave one (the newest step that did), and otherwise
from a look at the files (package.json, an index.html, a Python file with a main block). Before a result is applied it
runs in a throw-away COPY of its worktree: applying writes what the worktree holds, so whatever the program creates
(node_modules, __pycache__, save files) must never land there. After applying it runs in the project itself.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional

KINDS = ("web", "gui", "terminal")
MAX_COMMAND = 300
MAX_COPY_FILES = 20_000
PORT = "<port>"                     # the free port a static page is served on, chosen when it starts
LOCAL_URL = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d{1,5})?(/[^\s\"'`$\\]*)?$")
GUI_MODULES = ("tkinter", "pygame", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "kivy", "flet", "arcade", "pyglet")
WEB_MODULES = ("flask", "fastapi", "django", "streamlit", "gradio", "bottle", "aiohttp")
PY_ENTRY = ("main.py", "app.py", "run.py", "game.py", "gui.py", "server.py", "manage.py")
HTML_DIRS = ("", "public", "src", "web", "site", "dist")
SKIP_DIRS = {".git", ".director_worktrees", "node_modules", ".venv", "venv", "env", "__pycache__", "tests", "test", "build", "dist"}
NOT_ENTRY_DIRS = {"scripts", "script", "tools", "bin", "migrations", "docs", "examples", "benchmarks"}


# ------------------------------------------------------------------ what the Maker said

def clean_spec(raw: Any) -> Optional[Dict[str, str]]:
    """The Maker's "run" field, kept only when it is safe to show and use: one line, short, a local URL, a relative
    .html file. Anything else is dropped (the files are looked at instead)."""
    if not isinstance(raw, dict):
        return None
    command = raw.get("command") if isinstance(raw.get("command"), str) else ""
    command = command.strip()
    if command and (len(command) > MAX_COMMAND or "\n" in command or "\r" in command or "\0" in command):
        return None
    opened = raw.get("open") if isinstance(raw.get("open"), str) else ""
    opened = opened.strip().replace("\\", "/")
    if opened and not _relative_html(opened):
        opened = ""
    url = raw.get("url") if isinstance(raw.get("url"), str) else ""
    url = url.strip() if LOCAL_URL.match(url.strip()) else ""
    if not command and not opened:
        return None
    kind = raw.get("kind") if raw.get("kind") in KINDS else ("web" if url or opened else "terminal")
    return {"command": command, "kind": kind, "url": url, "open": opened}


def _relative_html(rel: str) -> bool:
    p = PurePosixPath(rel)
    return (not p.is_absolute() and ".." not in p.parts and not re.match(r"^[A-Za-z]:", rel)
            and p.suffix.lower() in (".html", ".htm") and len(rel) <= 200)


def recorded_spec(run_dirs: List[Path]) -> Optional[Dict[str, str]]:
    """The newest step's "run" field (a repair round or a later step may leave it out)."""
    for folder in run_dirs:
        try:
            maker = json.loads((folder / "maker.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        spec = clean_spec((maker or {}).get("run"))
        if spec:
            return spec
    return None


# ------------------------------------------------------------------ what the files say

def _python(root: Path) -> str:
    """The project's own virtual environment when it has one, else the system Python."""
    for rel in ((".venv", "Scripts", "python.exe"), ("venv", "Scripts", "python.exe")) if os.name == "nt" else \
            ((".venv", "bin", "python"), ("venv", "bin", "python")):
        if (root.joinpath(*rel)).is_file():
            return str(PurePosixPath(*rel)) if os.name != "nt" else "\\".join(rel)
    return "python" if os.name == "nt" else "python3"


def _imports(text: str, names) -> bool:
    return any(re.search(rf"^\s*(?:import|from)\s+{re.escape(n)}\b", text, re.M) for n in names)


def guess(root: Path) -> Optional[Dict[str, str]]:
    """How a person would start what is in this folder, read from its files. None when nothing looks startable."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data = data if isinstance(data, dict) else {}
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        deps = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(data.get(key), dict):
                deps.update(data[key])
        script = next((s for s in ("dev", "start", "serve", "preview") if isinstance(scripts.get(s), str)), None)
        if script:
            run = "npm start" if script == "start" else f"npm run {script}"
            prefix = "" if (root / "node_modules").is_dir() else "npm install && "
            return {"command": prefix + run, "kind": "gui" if "electron" in deps else "web", "url": "", "open": ""}
    named = [root / name for name in PY_ENTRY if (root / name).is_file()]
    named += [root / "src" / name for name in PY_ENTRY if (root / "src" / name).is_file()]
    found = _python_entry(root, named)
    if found:
        return found
    for folder in HTML_DIRS:
        page = root / folder / "index.html"
        if page.is_file():
            return {"command": "", "kind": "web", "url": "", "open": str(PurePosixPath(folder, "index.html")) if folder else "index.html"}
    return _python_entry(root, _python_files(root))


def _python_files(root: Path) -> List[Path]:
    """Python files a person might start: in the project root, in src/ and one package below. Never scripts, tools,
    tests or anything a dependency brought; names that sound like an entry point first."""
    out: List[Path] = []
    for here, dirs, files in os.walk(root):
        rel = Path(here).relative_to(root)
        depth = len(rel.parts)
        dirs[:] = sorted(d for d in dirs if depth < 2 and d not in SKIP_DIRS and d not in NOT_ENTRY_DIRS
                         and not d.startswith((".", "test")))
        if depth and rel.parts[0] != "src" and depth > 1:
            continue
        out += [Path(here) / f for f in sorted(files) if f.endswith(".py") and not f.startswith(("test", "_", "conftest", "setup"))]
    wanted = re.compile(r"(main|app|cli|game|gui|ui|server|run|play)", re.I)
    return sorted(out, key=lambda p: (not wanted.search(p.stem), len(p.relative_to(root).parts), p.as_posix()))[:200]


def _python_entry(root: Path, candidates: List[Path]) -> Optional[Dict[str, str]]:
    """The first candidate with a main block, as a command that runs it from the project root."""
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        if not re.search(r"""^if\s+__name__\s*==\s*['"]__main__['"]\s*:""", text, re.M) and path.name != "manage.py":
            continue
        rel = path.relative_to(root)
        py = _python(root)
        if path.name == "manage.py" and len(rel.parts) == 1:
            return {"command": f"{py} manage.py runserver 127.0.0.1:8000", "kind": "web", "url": "http://127.0.0.1:8000/", "open": ""}
        if _imports(text, ("streamlit",)):
            return {"command": f"{py} -m streamlit run {shlex.quote(rel.as_posix())}", "kind": "web", "url": "", "open": ""}
        if len(rel.parts) == 1:
            target = shlex.quote(rel.as_posix())
        else:
            parts = rel.with_suffix("").parts
            if not all(re.fullmatch(r"[A-Za-z_]\w*", part) for part in parts):
                continue                             # a folder name a shell or Python would not take as it is
            target = "-m " + ".".join(parts)
        kind = "gui" if _imports(text, GUI_MODULES) else "web" if _imports(text, WEB_MODULES) else "terminal"
        return {"command": f"{py} {target}", "kind": kind, "url": "", "open": ""}
    return None


# ------------------------------------------------------------------ the plan the console shows

def plan(run_id: str, rm=None) -> Dict[str, Any]:
    """What "실행해 보기" would do for this result: {found, command, kind, url, open, where, folder, source} or
    {found: False, reason}. Read only."""
    from core.result_manager import ResultManager, RESULT_APPLIED, RESULT_DISCARDED
    rm = rm or ResultManager()
    run = rm.sm.get_run(run_id) or {}
    if not run:
        return {"found": False, "reason": "no such run"}
    state = rm.result_state(run_id).get("state")
    project, worktree = run.get("project_path") or "", run.get("worktree_path") or ""
    if state == RESULT_DISCARDED:
        return {"found": False, "reason": "discarded"}
    if state == RESULT_APPLIED:
        if not project or not (Path(project) / ".git").exists():
            return {"found": False, "reason": "project missing"}
        root, where = Path(project).resolve(), "project"
    else:
        if run.get("current_state") != "PASS":
            return {"found": False, "reason": "not a passed result"}
        if not worktree or not Path(worktree).is_dir() or not rm.worktree_contained(project, worktree):
            return {"found": False, "reason": "worktree missing"}
        root, where = Path(worktree).resolve(), "copy"
    spec = recorded_spec([rm.run_dir(r) for r in [run_id] + list(rm.builds_on(run_id))])
    source = "maker"
    if spec and spec["open"] and not (root / spec["open"]).is_file():
        spec = None                                  # the file it named is not there: look at the files instead
    if not spec:
        spec, source = guess(root), "guess"
    if not spec:
        return {"found": False, "reason": "nothing to start", "where": where, "folder": str(root)}
    command = spec["command"] or f"{_python(root)} -m http.server --bind 127.0.0.1 {PORT}"
    command, note = _real_python(command, root)
    if not note:
        command, note = _with_tk(command, root)
    return {"found": True, "command": command, "kind": spec["kind"], "url": spec["url"], "open": spec["open"],
            "where": where, "folder": str(root), "source": source, "note": note}


_TK: Dict[str, bool] = {}


def _has_tk(python: str) -> bool:
    """Whether this Python can import tkinter (Homebrew's python3 ships without it). Remembered per process."""
    if python not in _TK:
        import subprocess
        try:
            _TK[python] = subprocess.run([python, "-c", "import tkinter"], capture_output=True, timeout=15,
                                         stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _TK[python] = False
    return _TK[python]


def _uses_tk(root: Path) -> bool:
    for path in _python_files(root) + [root / n for n in PY_ENTRY if (root / n).is_file()]:
        try:
            if _imports(path.read_text(encoding="utf-8", errors="replace")[:200_000], ("tkinter",)):
                return True
        except OSError:
            continue
    return False


_VERSION: Dict[str, Optional[tuple]] = {}


def _version(python: str) -> Optional[tuple]:
    """(major, minor) of a Python, or None when it cannot be asked. Remembered per process."""
    if python not in _VERSION:
        import subprocess
        try:
            out = subprocess.run([python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                                 text=True, timeout=15, stdin=subprocess.DEVNULL)
            _VERSION[python] = tuple(int(x) for x in out.stdout.strip().split(".")) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            _VERSION[python] = None
    return _VERSION[python]


def _tk_fix(wanted: tuple) -> str:
    """The command that gives this machine's python3 its tkinter (Homebrew ships it separately)."""
    if sys.platform == "darwin" and shutil.which("brew"):
        return f"brew install python-tk@{wanted[0]}.{wanted[1]}"
    return "sudo apt install python3-tk" if sys.platform.startswith("linux") else ""


_RUNS: Dict[str, bool] = {}


def _runs(python: str) -> bool:
    """Does this interpreter really start? Windows' Microsoft Store stand-in (WindowsApps\\python.exe on a PC without
    Python) only prints "Python" and ends; a Python installed from the Store sits in the same folder and does run, so
    the folder alone does not tell. Asked once per console process."""
    if python not in _RUNS:
        try:
            _RUNS[python] = subprocess.run([python, "-c", "import sys"], capture_output=True, timeout=15,
                                           stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _RUNS[python] = False
    return _RUNS[python]


_PY_START = re.compile(r"(^|&&|\|\||;)(\s*)(python3|python|py)(?=\s)((?:\s+-(?:3(?:\.\d+)?|V:\S+))*)")


def _real_python(command: str, root: Path):
    """Each `python` / `python3` / `py` that starts the command (or a part after && || ;) and that this machine cannot
    run (not installed, or only the Store stand-in) becomes the project's environment or Tribunal's own Python, which
    every install has; the `py` launcher's version options (-3, -3.12, -V:...) go with it. The change is said in the
    plan. Anything else is left exactly as it was."""
    if not _PY_START.search(command):
        return command, None
    from core.pythons import project_python
    other = project_python(root)
    if os.name == "nt":
        quoted = '"' + other.replace("%", "%%") + '"'          # a .cmd file expands %NAME% even inside quotes
    else:
        quoted = shlex.quote(other)
    switched = []

    def swap(m):
        name = m.group(3)
        found = shutil.which(name)
        if found and _runs(found):
            return m.group(0)
        switched.append(name)
        return m.group(1) + m.group(2) + quoted

    command = _PY_START.sub(swap, command)
    if not switched:
        return command, None
    note = {"python": "switched", "from": switched[0], "to": other}
    if _uses_tk(root) and not _has_tk(other):
        note.update(tk="missing", fix=_tk_fix(tuple(sys.version_info[:2])))
    return command, note


def _with_tk(command: str, root: Path):
    """A windowed tkinter app started with a bare `python3` / `python` that cannot import tkinter gets a Python on
    this machine that can. The Maker writes for the Python it was told about (Tribunal's own), so a Python at least
    that new is preferred; an older one is used only with a warning (new syntax fails there at start). Every change
    and warning is said in the plan, so it is shown before anything runs. Anything else is left exactly as it was."""
    first, _, rest = command.partition(" ")
    if first not in ("python3", "python") or not rest or _has_tk(first) or not _uses_tk(root):
        return command, None
    wanted = tuple(sys.version_info[:2])
    found = []
    for other in [shutil.which(f"python3.{minor}") for minor in range(14, 8, -1)] + ["/usr/bin/python3"]:
        if other and other not in [f for f, _v in found] and Path(other).is_file() and _has_tk(other):
            found.append((other, _version(other)))
    fix = _tk_fix(wanted)
    new_enough = [(f, v) for f, v in found if v and v >= wanted]
    if new_enough:
        other, v = new_enough[0]
        return f"{shlex.quote(other)} {rest}", {"tk": "switched", "from": first, "to": other}
    if found:
        other, v = max(found, key=lambda fv: fv[1] or (0, 0))
        return f"{shlex.quote(other)} {rest}", {"tk": "old", "from": first, "to": other,
                                                 "version": ".".join(map(str, v)) if v else "?",
                                                 "wants": f"{wanted[0]}.{wanted[1]}", "fix": fix}
    return command, {"tk": "missing", "from": first, "fix": fix}


# ------------------------------------------------------------------ starting it

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _copy(root: Path) -> Path:
    """A fresh copy of the worktree to run in (old copies of earlier tries are removed after a day)."""
    parent = Path(tempfile.gettempdir()) / "tribunal-try"
    parent.mkdir(exist_ok=True)
    for old in parent.iterdir():
        try:
            if old.is_dir() and not old.is_symlink() and time.time() - old.stat().st_mtime > 86_400:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    count = 0
    for _r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", ".director_worktrees")]
        count += len(files)
        if count > MAX_COPY_FILES:
            raise OSError("too many files to copy")
    holder = Path(tempfile.mkdtemp(prefix=root.name[:40] + "-", dir=parent))
    target = holder / root.name
    shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(".git", ".director_worktrees"))
    return target


def page_of(url: str, opened: str, port: Optional[int]) -> str:
    """The page to show in the browser once the program is up ('' for a program without one)."""
    return f"http://127.0.0.1:{port}/" + (opened or "") if port is not None else url


def posix_script(folder: Path, command: str, page: str) -> str:
    """The shell script the terminal runs. The command runs exactly as shown; the window waits at the end so an
    error can be read."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    lines = ["#!/bin/sh", "# Tribunal AI: tries out a result. The command below is the one shown before it started.",
             f"cd {shlex.quote(str(folder))} || exit 1",
             f"echo {shlex.quote('[Tribunal AI] 폴더 / folder: ' + str(folder))}",
             f"echo {shlex.quote('[Tribunal AI] 명령 / command: ' + command)}", "echo"]
    if page:
        lines.append(f"( sleep 3; {opener} {shlex.quote(page)} ) &")
    lines += [command, "echo",
              "printf '%s' " + shlex.quote("[Tribunal AI] 끝났습니다. Enter를 누르면 창이 닫힙니다. / Done - press Enter to close. "),
              "read _"]
    return "\n".join(lines) + "\n"


def _cmd_text(text: str) -> str:
    """Text cmd shows with echo as it is: its own operators escaped, % doubled (a .cmd file expands %NAME%)."""
    return re.sub(r"([&|<>^()])", r"^\1", text.replace("%", "%%"))


def windows_script(folder: Path, command: str, page: str) -> str:
    body = ["@echo off", "chcp 65001 >nul", 'cd /d "' + str(folder).replace("%", "%%") + '"', "echo [Tribunal AI] " + _cmd_text(command), "echo."]
    if page:                                         # no reliable delayed open in cmd: the address is shown instead
        body.append("echo [Tribunal AI] " + _cmd_text("open in a browser: " + page))
    body += [command, "echo.", "pause"]
    return "\r\n".join(body) + "\r\n"


def start(run_id: str, expected_command: str, launcher: Optional[Callable[[str, Path, str, str], bool]] = None, rm=None,
          expected_folder: Optional[str] = None) -> Dict[str, Any]:
    """Start the plan the person saw. Refused when the plan changed since: another command, or another place (applied
    meanwhile, so it would run in the project instead of a copy), or the worktree gone."""
    p = plan(run_id, rm=rm)
    if not p.get("found"):
        return {"status": "refused", "reason": p.get("reason", "nothing to start")}
    if p["command"] != (expected_command or "") or (expected_folder is not None and expected_folder != p["where"] + ":" + p["folder"]):
        return {"status": "stale", "reason": "the plan changed since it was shown; look again"}
    folder = Path(p["folder"])
    if p["where"] == "copy":
        try:
            folder = _copy(folder)
        except OSError as exc:
            return {"status": "refused", "reason": f"could not copy the result: {exc}"}
    port = _free_port() if PORT in p["command"] else None
    command = p["command"].replace(PORT, str(port)) if port is not None else p["command"]
    manual = {"status": "manual", "command": f"cd {shlex.quote(str(folder))} && {command}", "folder": str(folder)}
    if (launcher or _open_terminal)(run_id, folder, command, page_of(p["url"], p["open"], port)):
        return {"status": "started", "where": p["where"], "folder": str(folder), "command": command}
    return manual                                    # e.g. Linux: desktops differ too much to open a terminal


def _open_terminal(run_id: str, folder: Path, command: str, page: str) -> bool:
    import subprocess
    from core.cli_accounts import _write_script
    name = f"try-{run_id[-12:]}-{time.strftime('%H%M%S')}"
    if sys.platform == "darwin":                     # a .command file opens in Terminal without asking for automation rights
        path = _write_script(name + ".command", posix_script(folder, command, page), folder="run-scripts")
        subprocess.run(["/usr/bin/open", str(path)], check=True, timeout=15, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if os.name == "nt":
        path = _write_script(name + ".cmd", windows_script(folder, command, page), folder="run-scripts")
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", str(path)], stdin=subprocess.DEVNULL)
        return True
    return False
