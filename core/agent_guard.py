"""What the Maker may do on its own in agent mode, and the few things it must ask about first.

In agent mode the Maker CLI runs commands, installs packages and edits files in the run's worktree without asking
(the person agreed to that when installing). Three kinds of action still wait for the person, each switchable in the
console (all on by default):

  system_install  - installs outside the project: sudo, brew, apt, winget, npm -g, pip outside a virtual environment
  money_credentials - payment and secret tools (stripe, op, gh auth token); in code, the LIVE_MONEY_CODE and
                    USER_DECISION_REQUIRED gates
  irreversible    - publishing and deploying (git push, npm publish, gh pr create, vercel ...), deleting outside the
                    project

The commands are caught by small stand-ins put first on the Maker's PATH. A stand-in does not run a caught command:
it records it and tells the Maker; after the step Tribunal stops the run and asks the person, and an allowed command
runs when the step is done again. Everything else is passed to the real program unchanged. A command called by its
full path (/usr/bin/sudo) gets past the stand-ins, so the step's output is searched for such calls afterwards. This is
a guard, not isolation: the consent screen says so.

This file is also the stand-in itself (`python agent_guard.py shim <name> args...`), so that part uses only the
standard library and nothing from Tribunal.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

CATEGORIES = ("system_install", "money_credentials", "irreversible")

SYSTEM_TOOLS = {"sudo", "doas", "su", "brew", "port", "apt", "apt-get", "aptitude", "dnf", "yum", "pacman", "zypper",
                "snap", "flatpak", "winget", "choco", "scoop", "softwareupdate", "installer", "msiexec"}
GLOBAL_INSTALLERS = {"pipx": {"install", "inject", "upgrade"}, "cargo": {"install"}, "gem": {"install", "update"},
                     "go": {"install"}}
NODE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
PIPS = {"pip", "pip3"}
PYTHONS = {"python", "python3", "py"}
DEPLOY_ANY = {"heroku", "aws", "gcloud", "az", "surge"}       # every use but help/version counts
DEPLOY_VERBS = {"netlify": {"deploy"}, "firebase": {"deploy"}, "fly": {"deploy"}, "flyctl": {"deploy"},
                "wrangler": {"deploy", "publish"}, "railway": {"up", "deploy"}, "twine": {"upload"},
                "docker": {"push"}, "kubectl": {"apply", "create", "delete", "patch", "replace", "rollout", "scale"},
                "terraform": {"apply", "destroy", "import"}}
VERCEL_SAFE = {"--version", "-v", "help", "--help", "whoami", "ls", "list", "inspect", "logs", "dev", "build", "pull"}
GH_WRITES = {"pr": {"create", "merge", "close", "edit", "comment", "review", "reopen", "ready"},
             "release": {"create", "delete", "upload", "edit"},
             "repo": {"create", "delete", "edit", "rename", "archive", "fork"},
             "issue": {"create", "close", "edit", "comment", "delete", "reopen", "transfer"},
             "gist": {"create", "delete", "edit"}, "secret": {"set", "delete"},
             "variable": {"set", "delete"}, "workflow": {"run", "enable", "disable"}}
MONEY_TOOLS = {"stripe", "op"}
REMOVERS = {"rm", "rmdir"}
BREW_READ = {"list", "ls", "info", "search", "--prefix", "--version", "config", "doctor", "deps", "outdated", "leaves",
             "--cellar", "--repository", "home", "desc", "help"}
VERSIONED = [f"{base}3.{minor}" for base in ("python", "pip") for minor in range(8, 16)]
SHIMMED = sorted(SYSTEM_TOOLS | set(GLOBAL_INSTALLERS) | NODE_MANAGERS | PIPS | PYTHONS | DEPLOY_ANY | set(DEPLOY_VERBS)
                 | {"git", "gh", "vercel", "uv"} | MONEY_TOOLS | REMOVERS | set(VERSIONED))
# Not caught: macOS `security`. The CLIs run with the same PATH and Claude Code reads its own sign-in from the keychain
# with it; a stand-in refusing it signed the Maker out (found in the first real run, 2026-11-26). The Maker is told
# not to read stored secrets instead.

LABELS = {"system_install": "시스템 전체 설치", "money_credentials": "돈·자격 증명", "irreversible": "되돌릴 수 없는 작업"}
REFUSED_EXIT = 126


# ------------------------------------------------------------------ settings

def _settings_path() -> Path:
    from core.paths import data_dir
    return data_dir() / "permissions.json"


def permissions() -> Dict[str, bool]:
    """Whether each category is asked about (True) or let through (False). Missing or unreadable: all asked."""
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    return {c: saved.get(c) is not False for c in CATEGORIES}


def set_permission(category: str, ask: bool) -> Dict[str, bool]:
    if category not in CATEGORIES:
        raise ValueError("unknown permission category")
    current = permissions()
    current[category] = bool(ask)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return current


# ------------------------------------------------------------------ deciding

def _norm(name: str) -> str:
    base = os.path.basename(str(name)).lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return re.sub(r"^(python|pip)3\.\d+$", r"\g<1>3", base)          # python3.12 is python3


def _words(args: Iterable[str]) -> List[str]:
    return [a for a in args if not a.startswith("-")]


def _git_subcommand(args: List[str]) -> str:
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return ""


def _in_venv(python_or_pip: Optional[str]) -> bool:
    """Whether a pip/python program belongs to a virtual environment (a pyvenv.cfg one or two folders up)."""
    if os.environ.get("VIRTUAL_ENV"):
        return True
    if not python_or_pip:
        return False
    p = Path(python_or_pip)
    return any((d / "pyvenv.cfg").is_file() for d in (p.parent, p.parent.parent))


def _inside(base: str, full: Path) -> bool:
    try:
        b = Path(base).resolve()
    except (OSError, ValueError):
        return False
    return full == b or b in full.parents


def _outside(root: Optional[str], cwd: str, target: str) -> bool:
    """Whether a path a command names lies outside the project (the system temp folder counts as inside)."""
    if not root or target.startswith("-"):
        return False
    try:
        full = (Path(cwd) / os.path.expanduser(target)).resolve()
    except (OSError, ValueError):
        return True
    return not (_inside(root, full) or _inside(tempfile.gettempdir(), full))


def _option_value(args: List[str], *names: str) -> Optional[str]:
    """The value of --name=value / --name value / -n value (the first of `names` found)."""
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if n.startswith("--") and a.startswith(n + "="):
                return a[len(n) + 1:]
            if not n.startswith("--") and a.startswith(n) and len(a) > len(n):
                return a[len(n):]
    return None


def classify(name: str, args: List[str], root: Optional[str] = None, cwd: Optional[str] = None,
             real: Optional[str] = None) -> Optional[str]:
    """The category a command belongs to, or None when the Maker may run it without asking."""
    tool = _norm(name)
    args = [str(a) for a in args]
    words = _words(args)
    first = words[0].lower() if words else ""
    cwd = cwd or os.getcwd()
    if tool == "brew" and (first in BREW_READ or (not words and any(a in BREW_READ for a in args))):
        return None
    if tool in SYSTEM_TOOLS:
        return "system_install"
    if tool == "uv":
        if words[:2] == ["tool", "install"] or (words[:2] == ["pip", "install"] and "--system" in args) \
                or words[:2] == ["python", "install"]:
            return "system_install"
        return None
    if tool in GLOBAL_INSTALLERS and first in GLOBAL_INSTALLERS[tool]:
        return "system_install"
    if tool in NODE_MANAGERS:
        if any(a in ("-g", "--global", "--location=global") for a in args) or _option_value(args, "--location") == "global" \
                or (tool in ("yarn", "pnpm") and first == "global") or (tool == "npm" and first in ("link", "ln") and len(words) == 1):
            return "system_install"
        if first == "publish":
            return "irreversible"
        return None
    module_at = next((i for i, a in enumerate(args) if a == "-m" or (a.startswith("-m") and len(a) > 2)), None)
    module = None
    if tool in PYTHONS and module_at is not None:
        module = args[module_at][2:] or (args[module_at + 1] if module_at + 1 < len(args) else "")
    if tool in PIPS or module in ("pip", "pip3"):
        rest = args if tool in PIPS else args[module_at + (1 if len(args[module_at]) > 2 else 2):]
        rest_words = _words(rest)
        if rest_words[:1] == ["install"]:
            if "--user" in rest or "--break-system-packages" in rest:
                return "system_install"
            target = _option_value(rest, "--target", "--prefix", "--root", "-t")
            if target is not None:                    # a folder of its own: fine inside the project only
                return None if not _outside(root, cwd, target) else "system_install"
            if not _in_venv(real):
                return "system_install"
        return None
    if tool == "git":
        return "irreversible" if _git_subcommand(args) == "push" else None
    if tool == "gh":
        if first == "auth" and ((len(words) > 1 and words[1] == "token") or "--show-token" in args or "-t" in args):
            return "money_credentials"
        if first == "api":
            method = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-X", "--method")), "GET")
            writes = any(a in ("-f", "-F", "--field", "--raw-field", "--input") for a in args)
            return "irreversible" if writes or method.upper() != "GET" else None
        if first in GH_WRITES and len(words) > 1 and words[1] in GH_WRITES[first]:
            return "irreversible"
        return None
    if tool == "vercel":
        return None if (not words and any(a in VERCEL_SAFE for a in args)) or first in VERCEL_SAFE else "irreversible"
    if tool in DEPLOY_VERBS:
        return "irreversible" if first in DEPLOY_VERBS[tool] else None
    if tool in DEPLOY_ANY:
        return None if first in ("", "help", "version") or "--version" in args or "--help" in args else "irreversible"
    if tool in MONEY_TOOLS:
        return "money_credentials"
    if tool in REMOVERS:
        return "irreversible" if any(_outside(root, cwd, a) for a in args if not a.startswith("-")) else None
    return None


def command_text(name: str, args: List[str]) -> str:
    return " ".join([_norm(name), *(shlex.quote(a) for a in args)])


# ------------------------------------------------------------------ setting up a step

def _shim_dir() -> Path:
    from core.paths import data_dir
    return data_dir() / "guard-bin"


def _write(path: Path, text: str, executable: bool) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\r\n" if path.suffix == ".cmd" else "\n")   # text uses \n only
    if executable:
        tmp.chmod(0o755)
    os.replace(tmp, path)


def install_shims(python: Optional[str] = None) -> Path:
    """(Re)writes one stand-in per caught program. Cheap, so done before every step: a moved install never leaves
    stand-ins pointing at an old Python."""
    from core.pythons import tribunal_python
    python = python or tribunal_python()
    here = str(Path(__file__).resolve())
    folder = _shim_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name in SHIMMED:
        if os.name == "nt":                            # cmd and PowerShell find name.cmd; Git Bash runs the plain script
            _write(folder / f"{name}.cmd", f'@"{python}" -I "{here}" shim {name} %*\n@exit /b %ERRORLEVEL%\n', False)
        posix_python = python.replace("\\", "/") if os.name == "nt" else python
        _write(folder / name, f'#!/bin/sh\nexec {shlex.quote(posix_python)} -I {shlex.quote(here.replace(os.sep, "/"))} shim {name} "$@"\n', True)
    _write_login_files(folder)
    keep = set(SHIMMED) | {f"{n}.cmd" for n in SHIMMED} | {"zdotdir", "bash_env.sh"}
    for old in folder.iterdir():                       # a stand-in an older version made and this one does not
        if old.name not in keep and not old.name.endswith(".tmp"):
            try:
                old.unlink()
            except OSError:
                pass
    return folder


def _write_login_files(folder: Path) -> None:
    """A login shell (zsh -lc, as the CLIs run commands on macOS) reads the person's profile, and macOS path_helper
    and `brew shellenv` there put /usr/bin and Homebrew back in front of the stand-ins. With ZDOTDIR pointing here,
    zsh reads these files instead: each runs the person's own file, then puts the stand-ins first again. bash gets
    the same through BASH_ENV for `bash -c`; `bash -l` reads only the person's own files (see docs/AGENT_MODE.md)."""
    zdot = folder / "zdotdir"
    zdot.mkdir(exist_ok=True)
    again = 'export PATH="$TRIBUNAL_GUARD_BIN:$PATH"\n'
    for name in (".zshenv", ".zprofile", ".zshrc", ".zlogin"):
        own = '[ -f "${TRIBUNAL_REAL_ZDOTDIR:-$HOME}/' + name + '" ] && ZDOTDIR="${TRIBUNAL_REAL_ZDOTDIR:-$HOME}" . "${TRIBUNAL_REAL_ZDOTDIR:-$HOME}/' + name + '"\n'
        _write(zdot / name, "# Tribunal AI (core/agent_guard.py)\n" + own + 'ZDOTDIR="' + str(zdot).replace('"', '') + '"\n' + again, False)
    _write(folder / "bash_env.sh", "# Tribunal AI (core/agent_guard.py)\n" + again, False)


def step_env(base: Dict[str, str], root: str, log: Path, allowed: Iterable[str] = (),
             ask: Optional[Dict[str, bool]] = None) -> Dict[str, str]:
    """The environment a Maker step runs with: stand-ins first on PATH, and what they need to decide."""
    folder = install_shims()
    env = dict(base)
    env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
    env["TRIBUNAL_GUARD_BIN"] = str(folder)
    env["TRIBUNAL_GUARD_ROOT"] = str(Path(root).resolve())
    env["TRIBUNAL_GUARD_LOG"] = str(log)
    env["TRIBUNAL_GUARD_ASK"] = json.dumps(ask if ask is not None else permissions())
    env["TRIBUNAL_GUARD_ALLOW"] = json.dumps(sorted(set(allowed)))
    env.pop("VIRTUAL_ENV", None)                      # the console's own environment is not the project's
    if os.environ.get("ZDOTDIR"):
        env["TRIBUNAL_REAL_ZDOTDIR"] = os.environ["ZDOTDIR"]
    env["ZDOTDIR"] = str(folder / "zdotdir")
    env["BASH_ENV"] = str(folder / "bash_env.sh")
    return env


def requests(log: Path) -> List[Dict[str, Any]]:
    """The commands a step was not allowed to run, each once, in order."""
    seen, out = set(), []
    try:
        lines = Path(log).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("command") and item["command"] not in seen:
            seen.add(item["command"])
            out.append(item)
    return out


_FULL_PATH = re.compile(r"(?:^|[\s\"'`;&|(])((?:/usr)?(?:/local)?/s?bin/(?:sudo|doas|apt-get|apt|dnf|yum|pacman|zypper|snap)"
                        r"|/opt/homebrew/bin/brew|/usr/local/bin/brew|/home/linuxbrew/\.linuxbrew/bin/brew)(?=\s)")


def full_path_calls(text: str) -> List[str]:
    """System installers called by their full path in a step's output (they get past the stand-ins)."""
    return sorted({m.group(1) for m in _FULL_PATH.finditer(text or "")})


# ------------------------------------------------------------------ the stand-in

def _real(name: str) -> Optional[str]:
    folder = os.environ.get("TRIBUNAL_GUARD_BIN", "")
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                           if p and os.path.normcase(os.path.abspath(p)) != os.path.normcase(os.path.abspath(folder or "\0")))
    return shutil.which(name, path=path)


def shim(name: str, args: List[str]) -> int:
    real = _real(name)
    category = classify(name, args, os.environ.get("TRIBUNAL_GUARD_ROOT"), os.getcwd(), real)
    try:
        ask = json.loads(os.environ.get("TRIBUNAL_GUARD_ASK") or "{}")
        allowed = set(json.loads(os.environ.get("TRIBUNAL_GUARD_ALLOW") or "[]"))
    except ValueError:
        ask, allowed = {}, set()
    text = command_text(name, args)
    if category and ask.get(category, True) and text not in allowed:
        log = os.environ.get("TRIBUNAL_GUARD_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"category": category, "command": text, "cwd": os.getcwd(),
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
        sys.stderr.write(f"[Tribunal] `{text}` was NOT run: it needs the user's approval ({category}). Continue without "
                         "it. After this step Tribunal asks the user; if they allow it, this step runs again and the "
                         "command will work then.\n")
        return REFUSED_EXIT
    if not real:
        sys.stderr.write(f"{name}: command not found\n")
        return 127
    if os.name == "nt":
        return subprocess.call([real, *args])
    os.execv(real, [real, *args])
    return 0                                           # not reached


if __name__ == "__main__" and len(sys.argv) >= 3 and sys.argv[1] == "shim":
    sys.exit(shim(sys.argv[2], sys.argv[3:]))
