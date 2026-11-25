"""`tribunal` — the command an installed Tribunal AI is used with (docs/PACKAGING.md).

    tribunal            start the console if it is not running, and open it in the browser
    tribunal app        the same in a window of its own (macOS, Windows); closing it turns the console off
    tribunal start      start the console in the background (prints its address)
    tribunal stop       stop it (records and working copies stay)
    tribunal serve      run the console in this window (Ctrl+C stops it)
    tribunal doctor     what is installed, signed in, and where the records are
    tribunal shortcut   make the icons that open it (--remove takes them away)
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
    """Whether that process is a Tribunal console (never stop or trust any other program by its number alone): the
    server script, or an AppImage running the console in its own process (`tribunal_cli app --foreground`)."""
    try:
        import psutil
        line = psutil.Process(pid).cmdline()
        return any("companion_server.py" in part for part in line) or ("tribunal_cli" in line and "--foreground" in line)
    except Exception:
        return False


def _recorded_pids() -> list:
    """The console's process number as recorded: data/companion.pid (written when it starts in the background) and
    data/companion.port (written by the console itself, also when started with `tribunal serve`)."""
    pids = []
    try:
        pids.append(int(_pid_file().read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        pass
    try:
        pids.append(int(json.loads((data_dir() / "companion.port").read_text(encoding="utf-8"))["pid"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return list(dict.fromkeys(pids))


def _running_pid() -> Optional[int]:
    return next((pid for pid in _recorded_pids() if _ours(pid)), None)


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


def _spawn_flags() -> dict:
    if os.name == "nt":
        # A new process group, no window - but not DETACHED_PROCESS: a console-less server would make every git,
        # CLI and test run it starts open a console window of its own (CREATE_NO_WINDOW is ignored with it).
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}             # outlives this command and the terminal it was typed in


def start_console(wait: float = 30.0) -> str:
    """Start the console in the background unless it already runs; returns its address. A console that runs but is
    slow to answer is waited for, never started twice."""
    running = _running_pid()
    if running:
        deadline = time.time() + wait
        while time.time() < deadline:
            url = _url()
            if url:
                return url
            time.sleep(0.5)
        raise click.ClickException(f"콘솔이 켜져 있지만(PID {running}) 응답하지 않습니다. `tribunal stop` 뒤에 다시 시작하세요.")
    data_dir().mkdir(parents=True, exist_ok=True)
    log, err = data_dir() / "companion.log", data_dir() / "companion.err"
    with open(log, "w", encoding="utf-8") as out, open(err, "a", encoding="utf-8") as errs:
        proc = subprocess.Popen([tribunal_python(), str(CODE_ROOT / "companion_server.py")], cwd=str(home()),
                                stdout=out, stderr=errs, stdin=subprocess.DEVNULL, **_spawn_flags())
    deadline = time.time() + wait
    while time.time() < deadline:
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        found = READY.search(text)
        if found:
            if "already running" not in found.group(0):     # ours: record it (a lost race leaves the other's record)
                _pid_file().write_text(str(proc.pid), encoding="utf-8")
            return found.group(1)
        if proc.poll() is not None:
            tail = (err.read_text(encoding="utf-8", errors="replace")[-600:] if err.exists() else "").strip()
            raise click.ClickException("콘솔을 시작하지 못했습니다 / the console did not start:\n" + (tail or text[-600:]))
        time.sleep(0.3)
    raise click.ClickException(f"콘솔이 {int(wait)}초 안에 준비되지 않았습니다. 기록: {log}")


def stop_console() -> bool:
    import psutil
    pid = _running_pid()
    if not pid:
        _pid_file().unlink(missing_ok=True)
        return False
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass                                        # ended meanwhile, or not ours to end
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
@click.option("--from-shortcut", is_flag=True, hidden=True)
def open_cmd(from_shortcut=False):
    """Start the console if needed and open it in the browser."""
    if not from_shortcut:
        url = start_console()
        click.echo(f"Tribunal AI: {url}")
        webbrowser.open(url)
        return
    from core import shortcuts                      # opened from an icon: no terminal, and the system's short PATH
    try:
        shortcuts.widen_path()
        webbrowser.open(start_console())
    except Exception as exc:                        # a ClickException or anything else: say it on the screen
        detail = exc.format_message() if isinstance(exc, click.ClickException) else f"{type(exc).__name__}: {exc}"
        shortcuts.show_error("Tribunal AI를 열지 못했습니다 / could not open Tribunal AI.\n\n"
                             f"{detail[:800]}\n\n기록 / log: {data_dir()}")
        sys.exit(1)


def _detach_app() -> None:
    """Start `tribunal app` on its own and return at once (the installers use it: the terminal must not wait for the
    window). It is the icon's own command, so a failure shows a dialog too."""
    from core import shortcuts
    app = shortcuts.locations()[0]
    if sys.platform == "darwin" and app.is_dir():
        # Opened as the app it is, the Dock shows "Tribunal AI" and its icon; started directly it would be "Python".
        subprocess.run(["open", str(app)], check=False, stdin=subprocess.DEVNULL, timeout=30)
        return
    subprocess.Popen(shortcuts.launch_command(), cwd=str(Path.home()), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **_spawn_flags())


@cli.command()
@click.option("--from-shortcut", is_flag=True, hidden=True)
@click.option("--detach", is_flag=True, help="Start it and return at once")
@click.option("--smoke", is_flag=True, hidden=True, envvar="TRIBUNAL_APP_SMOKE")      # the installer check (CI)
@click.option("--foreground", is_flag=True, hidden=True)   # the Linux AppImage: the console must live in this process
def app(from_shortcut=False, detach=False, smoke=False, foreground=False):
    """Open the console in its own window (macOS, Windows; Linux opens the browser). Closing the last window turns
    the console off, if a window started it."""
    from core import app_window, shortcuts
    if detach:
        if app_window.unavailable():                 # Linux: no window to wait for - open as before, the address shows
            open_cmd.callback()
        else:
            _detach_app()
        return
    try:
        if from_shortcut:
            shortcuts.widen_path()
        reason = app_window.unavailable()
        if reason and foreground and smoke:
            click.echo(reason)
            sys.exit(3)                              # the AppImage check: browser fallback, nothing left running
        if reason and foreground and not _running_pid():
            _serve_and_open()
            return
        if reason:
            url = start_console()
            click.echo(f"{reason}\nTribunal AI: {url}")
            if smoke:
                sys.exit(3)                          # the installer check: this system falls back to the browser
            webbrowser.open(url)
            return
        _run_app_window(smoke)
    except Exception as exc:
        if not from_shortcut or smoke or isinstance(exc, SystemExit):
            raise                                    # a check never waits on a dialog nobody will close
        detail = exc.format_message() if isinstance(exc, click.ClickException) else f"{type(exc).__name__}: {exc}"
        shortcuts.show_error("Tribunal AI를 열지 못했습니다 / could not open Tribunal AI.\n\n"
                             f"{detail[:800]}\n\n기록 / log: {data_dir()}")
        sys.exit(1)


def _serve_and_open() -> None:
    """Run the console in this process and open it in the browser once it answers. An AppImage's files exist only
    while the process that mounted them runs, so a console started in the background would lose its own code."""
    import threading

    def open_when_ready() -> None:
        for _ in range(120):
            url = _url()
            if url:
                webbrowser.open(url)
                return
            time.sleep(0.5)
    threading.Thread(target=open_when_ready, name="tribunal-open-browser", daemon=True).start()
    sys.path.insert(0, str(CODE_ROOT))
    import companion_server
    companion_server.run()
    url = _url()                                 # it was already running after all (a race): just open that one
    if url:
        webbrowser.open(url)


def _run_app_window(smoke: bool) -> None:
    from core import app_window
    already = _running_pid()
    me = os.getpid()
    if already and not app_window.other_windows(me):
        app_window.release()                         # an owner record left by a window that ended without cleaning up
    url = start_console()
    if not already:
        app_window.claim(_running_pid())             # this window started it: the last window to close turns it off
    app_window.register(me)
    shown = False
    state: dict = {}
    try:
        state = app_window.show(url, lambda: app_window.owned(_running_pid()) and not app_window.other_windows(me),
                                smoke=smoke)
        shown = True
    except Exception as exc:                         # no window after all (WebView2 missing, …): the browser instead
        if smoke:
            raise
        click.echo(f"창을 열지 못해 브라우저로 엽니다 / no window, opening the browser: {type(exc).__name__}: {exc}")
        webbrowser.open(url)
        if not already and not app_window.other_windows(me):
            app_window.release()                     # the browser uses it now: nobody turns it off by closing
    finally:
        last = not app_window.other_windows(me)
        app_window.unregister(me)
    if shown and last and app_window.owned(_running_pid()):
        # Work still running (a quit that bypassed the question, or no answer when it was asked) is stopped the clean
        # way first: turning the console off alone would leave its AI processes running.
        if not state.get("stopped_work") and app_window.busy(url) is not False and not app_window.stop_work(url):
            click.echo("작업을 정지하지 못해 콘솔을 켜 둡니다 / could not stop the work; the console stays on.")
            app_window.release()
        else:
            stop_console()
            app_window.release()
    if smoke:
        click.echo(f"smoke: {state.get('smoke')!r}")
        sys.exit(0 if state.get("smoke") else 1)


@cli.command()
@click.option("--remove", is_flag=True, help="Take the shortcuts away again")
def shortcut(remove):
    """Make the icons that open Tribunal AI (macOS: Applications, Windows: Start menu and Desktop, Linux: app menu)."""
    from core import shortcuts
    if remove:
        done = shortcuts.remove()
        for path in done["removed"]:
            click.echo(f"지움 / removed: {path}")
        for path in done["kept"]:
            click.echo(f"Tribunal이 만든 것이 아니라 두었습니다 / not ours, kept: {path}")
        if not done["removed"] and not done["kept"]:
            click.echo("지울 바로 가기가 없습니다 / no shortcuts to remove.")
        return
    done = shortcuts.create()
    for path in done["made"]:
        click.echo(f"바로 가기 / shortcut: {path}")
    for path in done["skipped"]:
        click.echo(f"같은 이름의 다른 파일이 있어 건너뜀 / something else has this name, skipped: {path}")


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
    from core import updates
    report["version"] = updates.check()
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    ok, no = "✓", "✗"
    version = report["version"]
    click.echo(f"Tribunal AI {version['current']} · Python {report['python']} · {'설치본' if report['installed'] else '저장소에서 실행'}")
    if version.get("newer"):
        click.echo(f"  새 버전이 있습니다 / a newer release: {version['latest']} · {version['url']}")
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


def safe_console() -> None:
    """Korean text and ✓ / ✗ must never stop a command. A terminal shows them as they are; output that goes to a pipe
    or a file is UTF-8; a code page that still cannot show a character gets a placeholder instead of an error
    (found by the Windows test run: cp1252 raised UnicodeEncodeError in `tribunal doctor`)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
            elif stream is not None:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> None:
    safe_console()
    cli()


if __name__ == "__main__":
    main()
