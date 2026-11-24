"""`tribunal` — the command an installed Tribunal AI is used with (docs/PACKAGING.md).

    tribunal            start the console if it is not running, and open it in the browser
    tribunal start      start the console in the background (prints its address)
    tribunal stop       stop it (records and working copies stay)
    tribunal serve      run the console in this window (Ctrl+C stops it)
    tribunal doctor     what is installed, signed in, and where the records are
    tribunal do / mission / run / status / resume / clean-worktrees   the same commands as `director.py`

The same on macOS, Windows and Linux: no shell script is involved. Run from a source checkout it manages the same
console as start-companion.sh (same data/companion.pid), so the two can be mixed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

import click

from core.paths import CODE_ROOT, data_dir, home, installed
from core.pythons import tribunal_python

READY = re.compile(r"Tribunal AI (?:console|already running) (http://127\.0\.0\.1:\d+)")


def _pid_file() -> Path:
    return data_dir() / "companion.pid"


def _ours(pid: int) -> bool:
    """Whether that process is a Tribunal console (never stop or trust any other program by its number alone)."""
    try:
        import psutil
        return any("companion_server.py" in part for part in psutil.Process(pid).cmdline())
    except Exception:
        return False


def _running_pid() -> Optional[int]:
    try:
        pid = int(_pid_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if _ours(pid) else None


def _url() -> Optional[str]:
    """The address of this home's console when it answers, else None."""
    from core.companion_config import recorded_port
    port = recorded_port(home())
    if not port:
        return None
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{port}/ops/hello", timeout=3) as r:
            if r.status == 200:
                return f"http://127.0.0.1:{port}"
    except Exception:
        return None
    return None


def start_console(wait: float = 30.0) -> str:
    """Start the console in the background unless it already runs; returns its address."""
    if _running_pid() and _url():
        return _url() or ""
    data_dir().mkdir(parents=True, exist_ok=True)
    log, err = data_dir() / "companion.log", data_dir() / "companion.err"
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) \
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True              # outlives this command and the terminal it was typed in
    with open(log, "w", encoding="utf-8") as out, open(err, "a", encoding="utf-8") as errs:
        proc = subprocess.Popen([tribunal_python(), str(CODE_ROOT / "companion_server.py")], cwd=str(home()),
                                stdout=out, stderr=errs, stdin=subprocess.DEVNULL, **kw)
    _pid_file().write_text(str(proc.pid), encoding="utf-8")
    deadline = time.time() + wait
    while time.time() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        found = READY.search(text)
        if found:
            if "already running" in found.group(0):          # another start won: that one is the console
                _pid_file().unlink(missing_ok=True)
            return found.group(1)
        if proc.poll() is not None:
            tail = (err.read_text(encoding="utf-8", errors="replace")[-600:] if err.exists() else "").strip()
            _pid_file().unlink(missing_ok=True)
            raise click.ClickException("콘솔을 시작하지 못했습니다 / the console did not start:\n" + (tail or text[-600:]))
        time.sleep(0.3)
    raise click.ClickException(f"콘솔이 {int(wait)}초 안에 준비되지 않았습니다. 기록: {log}")


def stop_console() -> bool:
    pid = _running_pid()
    if not pid:
        _pid_file().unlink(missing_ok=True)
        return False
    import psutil
    proc = psutil.Process(pid)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()
    for name in ("companion.pid", "companion.port"):
        (data_dir() / name).unlink(missing_ok=True)
    return True


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Tribunal AI — three subscription AI coding CLIs as one team. Without a command: open the console."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(open_cmd)


@cli.command("open")
def open_cmd():
    """Start the console if needed and open it in the browser."""
    url = start_console()
    click.echo(f"Tribunal AI: {url}")
    webbrowser.open(url)


@cli.command()
def start():
    """Start the console in the background."""
    click.echo(f"Tribunal AI: {start_console()}")


@cli.command()
def stop():
    """Stop the console. Records and working copies stay."""
    click.echo("Tribunal AI를 껐습니다 / stopped." if stop_console() else "켜져 있는 콘솔이 없습니다 / not running.")


@cli.command()
def serve():
    """Run the console in this window (Ctrl+C stops it)."""
    sys.path.insert(0, str(CODE_ROOT))
    import companion_server
    companion_server.run()


def _version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        return (out.stdout or out.stderr).strip().splitlines()[0][:80] if out.returncode == 0 else "응답 없음 / no answer"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "응답 없음 / no answer"


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def doctor(as_json):
    """What is installed and where the records are."""
    report = {"installed": installed(), "home": str(home()), "code": str(CODE_ROOT), "python": sys.version.split()[0],
              "console": _url(), "git": None, "clis": {}}
    git = shutil.which("git")
    report["git"] = _version(git) if git else None
    for name in ("claude", "codex", "agy"):
        exe = shutil.which(name)
        report["clis"][name] = _version(exe) if exe else None
    ready = sum(1 for v in report["clis"].values() if v)
    report["ready"] = bool(report["git"]) and ready >= 2
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    ok, no = "✓", "✗"
    click.echo(f"Tribunal AI · Python {report['python']} · {'설치본' if report['installed'] else '저장소에서 실행'}")
    click.echo(f"  기록 위치 / records : {report['home']}")
    click.echo(f"  콘솔 / console      : {report['console'] or '꺼져 있음 / not running'}")
    click.echo(f"  {ok if report['git'] else no} git        {report['git'] or '없음 — git을 설치하세요 / install git'}")
    for name, version in report["clis"].items():
        click.echo(f"  {ok if version else no} {name:<10} {version or '없음 / not installed'}")
    click.echo("준비됨: git과 AI CLI 둘 이상이 있습니다." if report["ready"] else
               "아직 준비되지 않음: git과 AI CLI가 둘 이상 있어야 작업을 시킬 수 있습니다.")


def _director_commands() -> None:
    """`tribunal do …`, `tribunal mission …` and the rest: the commands of director.py, unchanged."""
    import director
    for name, command in director.cli.commands.items():
        if name not in cli.commands:
            cli.add_command(command, name)


_director_commands()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
