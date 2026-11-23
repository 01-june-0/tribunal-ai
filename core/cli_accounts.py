"""Which account each CLI is signed in with, and how to sign in, switch or sign out.

Tribunal never sees a password or a token. It only
  * asks each CLI who is signed in (`claude auth status`, `codex login status` + `codex app-server` account/read), and
  * starts the CLI's own sign-in command in a terminal window on this machine, where the user finishes it in the browser.

Antigravity's CLI has no sign-in or sign-out command and does not say which account it uses; for it the only thing
offered is opening `agy` in a terminal. An e-mail address is kept in memory for a short while and never written to disk;
`snapshot()` gives it out masked, `reveal()` in full (the console asks for that with the bridge token).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

CLIS = ("claude", "openai", "antigravity")
EXE = {"claude": "claude", "openai": "codex", "antigravity": "agy"}
# what the console may ask for, and what it runs. Fixed lists: nothing from a request ever reaches a command line.
TERMINAL = {                                    # finished by the user in a terminal window
    ("claude", "login"): [["auth", "login"]],
    ("claude", "switch"): [["auth", "logout"], ["auth", "login"]],
    ("openai", "login"): [["login"]],
    ("openai", "switch"): [["logout"], ["login"]],
    ("antigravity", "open"): [[]],
}
DIRECT = {("claude", "logout"): ["auth", "logout"], ("openai", "logout"): ["logout"]}   # quick, no questions asked
PENDING_SECONDS = 600                           # how long a started sign-in is shown as "in progress"
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}                     # cli -> (time, account)
_PENDING: Dict[str, Dict[str, Any]] = {}        # cli -> {"since": time, "was": identity before}
_REFRESHING: set = set()                        # CLIs being asked right now (one background thread each)


def _testing() -> bool:
    return os.environ.get("DIRECTOR_TESTING") == "1"


def mask_email(email: Optional[str]) -> Optional[str]:
    """'user@example.com' -> 'u•••@e•••.com': enough to tell two accounts apart, not enough to read off a screen."""
    if not isinstance(email, str) or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    host, dot, tld = domain.rpartition(".")
    if not dot:
        host, tld = domain, ""
    return (name[:1] or "•") + "•••@" + (host[:1] or "•") + "•••" + (("." + tld) if tld else "")


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


def mask_text(text: Optional[str]) -> Optional[str]:
    """A label that may contain an address (Claude names a personal organisation after it)."""
    return _EMAIL.sub(lambda m: mask_email(m.group(0)) or "•••", text)[:80] if isinstance(text, str) and text else None


def _run(argv: List[str], timeout: float) -> subprocess.CompletedProcess:
    from core.cli_limits import _run as run
    return run(argv, timeout)


def _claude(exe: str) -> Dict[str, Any]:
    from core.cli_limits import _json_tail
    data = _json_tail(_run([exe, "auth", "status"], 15).stdout)
    if not data.get("loggedIn"):
        return {"signed_in": False}
    method = {"claude.ai": "subscription", "console": "api_console"}.get(str(data.get("authMethod") or ""), "other")
    return {"signed_in": True, "email": data.get("email") if isinstance(data.get("email"), str) else None,
            "method": method, "org": data.get("orgName") if isinstance(data.get("orgName"), str) else None}


def _codex(exe: str) -> Dict[str, Any]:
    done = _run([exe, "login", "status"], 15)
    text = (done.stdout + done.stderr).lower()
    if done.returncode != 0 or "not logged in" in text:
        return {"signed_in": False}
    method = "subscription" if "chatgpt" in text else "api_key" if "api key" in text else "other"
    email = None
    if method == "subscription":                # the address comes from the CLI's own account answer
        from core.cli_limits import _codex_rpc
        account = (_codex_rpc({1: ("account/read", {"refreshToken": False})}).get(1) or {}).get("account") or {}
        email = account.get("email") if isinstance(account, dict) and isinstance(account.get("email"), str) else None
    return {"signed_in": True, "email": email, "method": method, "org": None}


def _read(cli: str) -> Dict[str, Any]:
    from core.env_utils import resolve_cli
    exe = resolve_cli(EXE[cli])
    if not exe:
        return {"installed": False, "signed_in": None}
    if cli == "antigravity":                    # the CLI does not say; the console fills this in from its quota answer
        return {"installed": True, "signed_in": None}
    try:
        return {"installed": True, **(_claude(exe) if cli == "claude" else _codex(exe))}
    except Exception as exc:                    # a CLI that cannot be asked is "unknown", never an error page
        return {"installed": True, "signed_in": None, "error": type(exc).__name__}


def account(cli: str, max_age: float = 30.0, wait: bool = False) -> Dict[str, Any]:
    if cli not in CLIS:
        raise ValueError("Unknown AI")
    if _testing():
        return {"installed": True, "signed_in": None}
    with _LOCK:
        hit = _CACHE.get(cli)
        fresh = bool(hit) and time.time() - hit[0] < max_age
        if wait and not fresh:
            hit = None
        elif not fresh and cli not in _REFRESHING:
            _REFRESHING.add(cli)
            threading.Thread(target=_refresh, args=(cli,), name="account-" + cli, daemon=True).start()
        if hit:
            return hit[1]
        if not wait:
            return {"installed": True, "signed_in": None, "loading": True}     # first look: the answer arrives with the next poll
    return _refresh(cli, background=False)


def _refresh(cli: str, background: bool = True) -> Dict[str, Any]:
    try:
        value = _read(cli)
        with _LOCK:
            _CACHE[cli] = (time.time(), value)
        return value
    finally:
        if background:
            with _LOCK:
                _REFRESHING.discard(cli)


def clear_cache(cli: Optional[str] = None) -> None:
    with _LOCK:
        if cli:
            _CACHE.pop(cli, None)
        else:
            _CACHE.clear(); _PENDING.clear()


def _identity(acc: Dict[str, Any]) -> tuple:
    return (acc.get("signed_in"), acc.get("email"), acc.get("method"))


def _pending(cli: str, acc: Dict[str, Any]) -> bool:
    """True while a sign-in started from the console has neither changed the account nor run out of time."""
    with _LOCK:
        mark = _PENDING.get(cli)
        if not mark:
            return False
        changed = mark["was"] is not None and acc.get("signed_in") is True and _identity(acc) != mark["was"]
        if not changed and time.time() - mark["since"] <= PENDING_SECONDS:
            return True
        _PENDING.pop(cli, None)
    if changed:                                 # another account now: its plan and limits are different too
        try:
            from core import cli_limits
            cli_limits.refresh_now()
        except Exception:
            pass
    return False


def public(cli: str, acc: Dict[str, Any], quota_ok: Optional[bool] = None) -> Dict[str, Any]:
    """What the console may show: no full address, and only the actions this CLI really has."""
    signed = acc.get("signed_in")
    if cli == "antigravity" and signed is None and quota_ok:
        signed = True                           # it answered a quota question, so someone is signed in
    actions = [a for (c, a) in list(TERMINAL) + list(DIRECT) if c == cli] if acc.get("installed", True) else []
    if signed is False:
        actions = [a for a in actions if a in ("login", "open")]
    elif signed:
        actions = [a for a in actions if a != "login"]
    return {"installed": acc.get("installed", True), "signed_in": signed, "email_masked": mask_email(acc.get("email")),
            "has_email": bool(acc.get("email")), "method": acc.get("method"), "org": mask_text(acc.get("org")),
            "identity_known": cli != "antigravity", "actions": [] if acc.get("loading") else actions,
            "loading": bool(acc.get("loading")),
            "pending": _pending(cli, acc)}


def snapshot(limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {}
    for cli in CLIS:
        acc = account(cli, 5.0 if cli in _PENDING else 30.0)       # look more often while a sign-in is under way
        out[cli] = public(cli, acc, quota_ok=((limits or {}).get(cli) or {}).get("state") == "ok")
    return out


def reveal(cli: str) -> Optional[str]:
    return account(cli, wait=True).get("email")


# ------------------------------------------------------------------ doing it
def work_in_progress() -> bool:
    """An AI call is running or a mission is live: signing out now would break it."""
    try:
        from core import usage
        if usage.running_now():
            return True
        from core.mission import MissionStore
        return any(m.get("status") == "RUNNING" and m.get("owner_pid") and usage._pid_alive(m["owner_pid"]) for m in MissionStore().all())
    except Exception:
        return True                             # cannot tell: be careful


def command_line(cli: str, action: str) -> str:
    """The command the user would type themselves (shown when no terminal can be opened)."""
    return " && ".join(" ".join([EXE[cli]] + part) for part in TERMINAL[(cli, action)])


def _script(exe: str, parts: List[List[str]]) -> str:
    lines = ["#!/bin/sh", "# Tribunal AI: runs the CLI's own sign-in. Nothing typed here is seen by Tribunal.", "cd \"$HOME\" || exit 1"]
    for part in parts[:-1]:
        lines.append(shlex.join([exe] + part))
    lines.append(shlex.join([exe] + parts[-1]))
    lines += ["echo", "echo '[Tribunal AI] 끝났으면 이 창을 닫아도 됩니다. / You can close this window.'"]
    return "\n".join(lines) + "\n"


def _open_terminal(exe: str, parts: List[List[str]], cli: str, action: str) -> bool:
    """Open a terminal window on this machine that runs the command. False when this system has no known way."""
    if sys.platform == "darwin":                # a .command file opens in Terminal without asking for automation rights
        path = _write_script(f"{cli}-{action}.command", _script(exe, parts))
        subprocess.run(["/usr/bin/open", str(path)], check=True, timeout=15, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if os.name == "nt":                         # a .cmd file: cmd does not understand list2cmdline's \" quoting
        lines = ["@echo off"] + ['"' + exe + '" ' + " ".join(part) for part in parts] + ["echo.", "echo [Tribunal AI] You can close this window."]
        path = _write_script(f"{cli}-{action}.cmd", "\r\n".join(lines) + "\r\n")
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", str(path)], stdin=subprocess.DEVNULL)
        return True
    return False                                # Linux desktops differ too much: show the command instead


def _write_script(name: str, text: str) -> Path:
    """Write the script into a folder of our own, as a new file: never through a link someone left there."""
    from core.db_path import get_db_path
    folder = Path(get_db_path()).parent / "login-scripts"
    if folder.is_symlink():
        raise OSError("login-scripts must not be a link")
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        folder.chmod(0o700)
    path = folder / name
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o700)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def start(cli: str, action: str, launcher: Optional[Callable[..., bool]] = None, busy: Optional[bool] = None) -> Dict[str, Any]:
    """Run one of the fixed actions. Returns {"status": started | done | manual | busy | unavailable, ...}."""
    if cli in CLIS and action == "check":         # "look again": forget what was read and any sign-in in progress
        with _LOCK:
            _CACHE.pop(cli, None); _PENDING.pop(cli, None)
        return {"status": "checked"}
    if cli not in CLIS or ((cli, action) not in TERMINAL and (cli, action) not in DIRECT):
        raise ValueError("Unknown account action")
    from core.env_utils import resolve_cli
    exe = resolve_cli(EXE[cli])
    if not exe:
        return {"status": "unavailable", "message": EXE[cli] + " CLI is not installed"}
    current = account(cli, 0, wait=True)
    harmless = action == "open" or (action == "login" and current.get("signed_in") is False)
    if not harmless and (work_in_progress() if busy is None else busy):
        return {"status": "busy"}
    before = _identity(current) if not _testing() else None
    if (cli, action) in DIRECT:
        done = _run([exe] + DIRECT[(cli, action)], 30)
        clear_cache(cli)
        return {"status": "done" if done.returncode == 0 else "failed", "code": done.returncode}
    opened = (launcher or _open_terminal)(exe, TERMINAL[(cli, action)], cli, action)
    if not opened:
        return {"status": "manual", "command": command_line(cli, action)}
    with _LOCK:
        _PENDING[cli] = {"since": time.time(), "was": before if action != "open" else None}
        _CACHE.pop(cli, None)
    return {"status": "started", "command": command_line(cli, action)}
