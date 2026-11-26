"""First-run helper (docs/PACKAGING.md §5): what this machine still needs before Tribunal can work, and the official
command for each missing piece.

Rules, the same as for sign-in (core/cli_accounts.py):
  * The commands are a fixed list kept here. The page names an item ("git", "claude", ...); the command for it comes
    from this list and never from a request.
  * Nothing is installed without the person seeing the exact command and pressing a button. A command runs in a new
    terminal window on this machine, where the person watches it and answers any question (a password included).
    Tribunal reads nothing typed there.
  * Linux desktops differ too much to open a terminal reliably: the command is shown to be pasted instead.

Antigravity, Claude Code and Codex now ship native installers that need no Node.js. The npm route for Codex remains
as an alternative; Node.js is offered only on that route, when npm is missing.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.paths import data_dir, runs_dir

CLIS = ("claude", "openai", "antigravity")           # the keys core/cli_accounts.py uses
EXE = {"claude": "claude", "openai": "codex", "antigravity": "agy"}
LINKS = {
    "git": "https://git-scm.com/downloads",
    "claude": "https://code.claude.com/docs/en/setup",
    "openai": "https://github.com/openai/codex",
    "antigravity": "https://antigravity.google/docs/getting-started?tab=cli",
    "node": "https://nodejs.org/en/download",
}
LINKS["openai-npm"] = LINKS["openai"]


def _ps(url: str) -> str:
    """A PowerShell installer started from cmd. The quotes keep cmd away from the pipe."""
    return f'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm {url} | iex"'


# (item, system) -> the command. "posix" covers macOS and Linux. Fixed: nothing from a request ever reaches it.
COMMANDS = {
    ("git", "mac"): "xcode-select --install",
    ("git", "win"): "winget install --id Git.Git -e --source winget",
    ("git", "linux"): "sudo apt install git",
    ("claude", "posix"): "curl -fsSL https://claude.ai/install.sh | bash",
    ("claude", "win"): _ps("https://claude.ai/install.ps1"),
    ("openai", "posix"): "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    ("openai", "win"): _ps("https://chatgpt.com/codex/install.ps1"),
    ("antigravity", "posix"): "curl -fsSL https://antigravity.google/cli/install.sh | bash",
    ("antigravity", "win"): _ps("https://antigravity.google/cli/install.ps1"),
    ("openai-npm", "posix"): "npm install -g @openai/codex",
    ("openai-npm", "win"): "npm install -g @openai/codex",
    ("node", "mac"): "brew install node",             # only offered when Homebrew is there
    ("node", "win"): "winget install --id OpenJS.NodeJS.LTS -e --source winget",
}
ITEMS = ("git", "claude", "openai", "antigravity", "node", "openai-npm")
PENDING_SECONDS = 900                                 # an install started this long ago is still watched closely
_LOCK = threading.Lock()
_VERSIONS: Dict[tuple, Optional[str]] = {}            # (path, mtime) -> version text
_STARTED: Dict[str, float] = {}                       # item -> when its terminal was opened


def system() -> str:
    return "win" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux"


# ------------------------------------------------------------------ what is there
def _version_of(path: Optional[str], arg: str = "--version") -> Optional[str]:
    """The version a program reports, asked once per file (a new file after an update is asked again)."""
    if not path:
        return None
    try:
        key = (path, os.stat(path).st_mtime)
    except OSError:
        return None
    with _LOCK:
        if key in _VERSIONS:
            return _VERSIONS[key]
    from core.env_utils import probe_version
    text = probe_version(path, timeout=10.0, arg=arg)
    found = re.search(r"\d+\.\d+(?:\.\d+)?", text or "")
    version = found.group(0) if found else None
    with _LOCK:
        _VERSIONS[key] = version
    return version


def _known_dirs() -> list:
    """Folders official installers put programs in that a console started earlier may not have on its PATH: an installer
    changes the saved PATH (Windows registry, shell profiles), never the PATH of a program already running."""
    if os.name == "nt":
        dirs = []
        try:
            import winreg
            for root, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                try:
                    with winreg.OpenKey(root, key) as handle:
                        value = winreg.QueryValueEx(handle, "Path")[0]
                    dirs += [os.path.expandvars(d) for d in str(value).split(os.pathsep) if d.strip()]
                except OSError:
                    continue
        except ImportError:
            pass
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        return dirs + [os.path.join(program_files, "Git", "cmd"), os.path.join(program_files, "nodejs")]
    return ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")]


def refresh_path() -> None:
    """Put the folders of newly installed programs on this process's PATH (and so on the terminals it opens)."""
    current = os.environ.get("PATH", "").split(os.pathsep)
    seen = {os.path.normcase(d) for d in current}
    extra = []
    for d in _known_dirs():
        if d and os.path.normcase(d) not in seen and os.path.isdir(d):
            extra.append(d); seen.add(os.path.normcase(d))
    if extra:
        os.environ["PATH"] = os.pathsep.join(current + extra)        # after what is there: nothing already found changes


def _git() -> Optional[str]:
    """Path of a git that really works. On macOS /usr/bin/git is a stub until the developer tools are installed, and
    running it would pop up Apple's install dialog on every check: it counts only when xcode-select has a folder."""
    path = shutil.which("git")
    if path and system() == "mac" and os.path.realpath(path) == "/usr/bin/git":
        try:
            ok = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, timeout=10,
                                stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if not ok:
            path = next((p for p in ("/opt/homebrew/bin/git", "/usr/local/bin/git") if os.access(p, os.X_OK)), None)
    return path


def _ack_path() -> Path:
    return data_dir() / "setup.json"


def acknowledged() -> Dict[str, Any]:
    try:
        data = json.loads(_ack_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# The terms the person agrees to before the agent-mode Maker may run commands on this computer (docs/AGENT_MODE.md).
# Changing what the Maker may do without asking means a new date here: everyone is asked again.
AGENT_TERMS = "2026-11-26"


AGENT_TERMS_TEXT = """Tribunal AI 이용 동의 / Agreement ({date})

[한국어]
- Tribunal의 제작 AI는 작업 폴더 안에서 직접 명령을 실행하고, 필요한 라이브러리를 설치하고, 파일을 고칩니다. 그때마다 묻지 않습니다.
- 작업은 프로젝트와 분리된 작업 폴더에서 하고, 적용을 누를 때만 프로젝트에 반영됩니다.
- 시스템 전체 설치, 돈·자격 증명, 되돌릴 수 없는 작업은 먼저 묻습니다. AI 설정의 권한에서 바꿀 수 있습니다.
- 완전히 격리된 환경(컨테이너)은 아닙니다. AI가 실행한 명령은 이 컴퓨터에서 실행됩니다.
- AI 사용량은 각 AI 계정의 요금제에서 차감됩니다.

[English]
- Tribunal's Maker AI runs commands, installs the libraries it needs and edits files in a work folder by itself. It does not ask each time.
- It works in a folder separate from your project. Your project changes only when you press Apply.
- System-wide installs, money and credentials, and things that cannot be undone are asked about first. You can change this under Permissions in AI settings.
- This is not a fully isolated environment (a container). Commands the AI runs run on this computer.
- AI use counts against the plan of each AI account.
""".format(date=AGENT_TERMS)


def agent_consented() -> bool:
    return acknowledged().get("agent_terms") == AGENT_TERMS


def acknowledge(what: str) -> Dict[str, Any]:
    """Remember that the cost notice was read ("cost"), that the helper was finished ("done"), or that the person
    agreed to the agent-mode terms ("agent": recorded with the terms' date, from the helper or an installer)."""
    if what not in ("cost", "done", "agent"):
        raise ValueError("Unknown acknowledgement")
    data = acknowledged()
    data[what] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if what == "agent":
        data["agent_terms"] = AGENT_TERMS
    path = _ack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


def _has_history() -> bool:
    """Someone already worked with this copy (a run on record): the helper does not open by itself for them."""
    try:
        return any(p.name.startswith("RUN-") for p in runs_dir().iterdir())
    except OSError:
        return False


def _command(item: str, sysname: str) -> Optional[str]:
    if item == "node" and sysname == "mac" and not shutil.which("brew"):
        return None                                   # no Homebrew: the official download page instead
    if sysname == "win" and COMMANDS.get((item, "win"), "").startswith("winget") and not shutil.which("winget"):
        return None
    return COMMANDS.get((item, sysname)) or COMMANDS.get((item, "posix" if sysname != "win" else ""))


def commands(sysname: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """What the page shows for each item on this system: the command exactly as it would run, the shell it runs in,
    whether Tribunal can open the terminal for it, and the official page."""
    sysname = sysname or system()
    out = {}
    for item in ITEMS:
        cmd = _command(item, sysname)
        out[item] = {"command": cmd, "link": LINKS[item], "runnable": bool(cmd) and sysname != "linux",
                     "shell": "cmd" if sysname == "win" else "terminal"}
    return out


EMPTY_START = "Tribunal AI: empty starting point"     # core/bootstrap.py's first commit in a folder it made a project


def practice_name(lang: str = "ko", sysname: Optional[str] = None) -> str:
    """A Korean name only where it is safe everywhere: Windows' cmd scripts (run_preview) handle a plain name best."""
    return "Tribunal 연습" if lang == "ko" and (sysname or system()) != "win" else "Tribunal Practice"


def _made_by_us(path: Path) -> bool:
    try:
        first = subprocess.run(["git", "-C", str(path), "log", "--reverse", "--format=%s"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return first.returncode == 0 and first.stdout.split("\n", 1)[0].strip() == EMPTY_START


def practice_folder(lang: str = "ko") -> Path:
    """Where the practice project goes: a new folder in the home folder. An existing folder of that name is used only
    when it is empty or a practice project Tribunal made before; a link, or anyone's own folder, is left alone and the
    next free name is taken."""
    base = practice_name(lang)
    for n in range(1, 20):
        path = Path.home() / (base if n == 1 else f"{base} {n}")
        if path.is_symlink():
            continue
        if not path.exists():
            return path
        if path.is_dir() and (not any(path.iterdir()) or ((path / ".git").is_dir() and _made_by_us(path))):
            return path
    raise ValueError("no free name for a practice folder")


def status(accounts: Optional[Callable[[], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Everything the helper shows, read from this machine. Cheap enough to ask every few seconds: versions are asked
    once per installed file, sign-in states come from core/cli_accounts.py's cache."""
    from core.env_utils import resolve_cli
    refresh_path()
    sysname = system()
    git = _git()
    clis = {}
    for cli in CLIS:
        path = resolve_cli(EXE[cli])
        clis[cli] = {"installed": bool(path), "version": _version_of(path) if path else None}
    now = time.time()
    with _LOCK:
        for item, since in list(_STARTED.items()):
            done = (item == "git" and git) or (item in clis and clis[item]["installed"]) or \
                   (item == "openai-npm" and clis["openai"]["installed"]) or (item == "node" and shutil.which("npm"))
            if done or now - since > PENDING_SECONDS:
                _STARTED.pop(item, None)
        started = sorted(_STARTED)
    if accounts is None:
        from core import cli_accounts
        accounts = cli_accounts.snapshot
    ack = acknowledged()
    return {
        "system": sysname,
        "git": {"installed": bool(git), "version": _version_of(git) if git else None},
        "clis": clis,
        "npm": bool(shutil.which("npm")),
        "accounts": accounts(),
        "commands": commands(sysname),
        "started": started,
        "acknowledged": {**{k: bool(ack.get(k)) for k in ("cost", "done")}, "agent": ack.get("agent_terms") == AGENT_TERMS},
        "agent_terms": AGENT_TERMS,
        "practice": {lang: "~/" + practice_name(lang, sysname) for lang in ("ko", "en")},
        # also for someone who finished the helper before: the new terms are asked once
        "auto_open": (not ack.get("cost") and not _has_history()) or ack.get("agent_terms") != AGENT_TERMS,
    }


def refresh() -> None:
    """"Look again": versions are asked anew and sign-in states read again."""
    with _LOCK:
        _VERSIONS.clear()
    try:
        from core import cli_accounts
        for cli in cli_accounts.CLIS:          # read again; a sign-in under way stays shown as under way
            cli_accounts.clear_cache(cli)
    except Exception:
        pass


# ------------------------------------------------------------------ running one
def posix_script(command: str) -> str:
    lines = ["#!/bin/sh", "# Tribunal AI: runs one official install command, exactly as shown before it started.",
             'cd "$HOME" || exit 1',
             f"echo {shlex.quote('[Tribunal AI] 명령 / command: ' + command)}", "echo",
             command, "echo",
             "printf '%s' " + shlex.quote("[Tribunal AI] 끝났습니다. Enter를 누르면 창이 닫힙니다. / Done - press Enter to close. "),
             "read _"]
    return "\n".join(lines) + "\n"


def _echo_text(text: str) -> str:
    """Text cmd's echo shows as it is. Inside double quotes cmd takes ^ literally, so only what is outside them is
    escaped; % is doubled everywhere (a .cmd file expands %NAME% even inside quotes)."""
    out, quoted = [], False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == "%":
            out.append("%%")
        elif not quoted and ch in "&|<>^()":
            out.append("^" + ch)
        else:
            out.append(ch)
    return "".join(out)


def windows_script(command: str) -> str:
    # chcp 65001: the lines after it are read as UTF-8. `call`: npm is itself a batch file, and a batch file run
    # without it never comes back, so the closing lines would not run.
    body = ["@echo off", "chcp 65001 >nul", 'cd /d "%USERPROFILE%"', "echo [Tribunal AI] " + _echo_text(command), "echo.",
            "call " + command, "echo.", "echo [Tribunal AI] Done - you can close this window.", "pause"]
    return "\r\n".join(body) + "\r\n"


def _open_terminal(item: str, command: str) -> bool:
    from core.cli_accounts import _write_script
    name = f"install-{item}-{time.strftime('%H%M%S')}"
    if sys.platform == "darwin":                     # a .command file opens in Terminal without asking for automation rights
        path = _write_script(name + ".command", posix_script(command), folder="setup-scripts")
        subprocess.run(["/usr/bin/open", str(path)], check=True, timeout=15, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if os.name == "nt":
        path = _write_script(name + ".cmd", windows_script(command), folder="setup-scripts")
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", str(path)], stdin=subprocess.DEVNULL)
        return True
    return False


def run(item: str, expected_command: str, launcher: Optional[Callable[[str, str], bool]] = None) -> Dict[str, Any]:
    """Open a terminal with the official command for one item. `expected_command` is what the page showed: when this
    machine's command differs (Homebrew appeared, say), nothing runs and the page is told to look again."""
    if item not in ITEMS:
        raise ValueError("Unknown item")
    refresh_path()
    sysname = system()
    command = _command(item, sysname)
    if not command:
        return {"status": "unavailable", "link": LINKS[item]}
    if command != (expected_command or ""):
        return {"status": "stale", "reason": "the command changed since it was shown; look again"}
    if item == "openai-npm" and not shutil.which("npm"):
        return {"status": "needs", "item": "node"}
    if sysname == "linux":
        return {"status": "manual", "command": command}
    if not (launcher or _open_terminal)(item, command):
        return {"status": "manual", "command": command}
    with _LOCK:
        _STARTED[item] = time.time()
    return {"status": "started", "command": command}


def make_practice(lang: str = "ko", select: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Create the practice folder as a git project and make it the console's project."""
    refresh_path()
    if not _git():
        return {"status": "needs", "item": "git"}
    path = practice_folder(lang)
    from core.bootstrap import prepare_project
    root = prepare_project(str(path))
    if select is None:
        import dashboard_server
        select = dashboard_server.set_project
    message = select(str(root))
    if not str(message).startswith("PROJECT_SELECTED"):
        return {"status": "refused", "reason": str(message)[:300]}
    return {"status": "ready", "path": str(root)}
