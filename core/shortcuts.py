"""Icons that open Tribunal AI without a terminal (docs/PACKAGING.md, phase 3).

    macOS    ~/Applications/Tribunal AI.app            (Spotlight and Launchpad find it there)
    Windows  Start menu and Desktop: Tribunal AI.lnk
    Linux    ~/.local/share/applications/tribunal-ai.desktop   (the desktop's application menu)

Each one runs `<this Python> -I -m tribunal_cli app --from-shortcut`: start the console if needed, open it in a window
(phase 4; the browser on Linux), and show a dialog instead of a terminal message when something goes wrong. Every shortcut carries MARK, and removing
only ever touches a file with that mark, so a file of the same name made by someone else is left alone.

TRIBUNAL_SHORTCUTS_HOME (an absolute path) puts every shortcut under that folder instead - for the tests and the
installer's own check, never the real Desktop.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

NAME = "Tribunal AI"
MARK = "tribunal-ai-shortcut"
BUNDLE_ID = "io.github.01-june-0.tribunal-ai"
LAUNCHER = "tribunal-launch"            # the program inside the macOS app


def icon(kind: str) -> Path:
    """The app icon that ships with the code (console/icons, made by scripts/make_icons.py): icns, ico or png."""
    from core.paths import code_file
    return code_file("console", "icons", {"icns": "tribunal.icns", "ico": "tribunal.ico", "png": "tribunal-512.png"}[kind])


def system() -> str:
    if sys.platform == "darwin":
        return "mac"
    return "windows" if os.name == "nt" else "linux"


def _test_home() -> Optional[Path]:
    chosen = os.environ.get("TRIBUNAL_SHORTCUTS_HOME")
    if not chosen:
        return None
    if not Path(chosen).is_absolute():
        raise ValueError(f"TRIBUNAL_SHORTCUTS_HOME must be an absolute path, got {chosen!r}")
    return Path(chosen)


def _windows_folder(csidl: int, fallback: Path) -> Path:
    """A Windows shell folder by its CSIDL number: the Desktop may be moved into OneDrive or carry a translated name."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return fallback


def locations(sysname: Optional[str] = None) -> List[Path]:
    """Where the shortcuts go on this system."""
    sysname = sysname or system()
    base = _test_home()
    if sysname == "mac":
        return [(base or Path.home()) / "Applications" / f"{NAME}.app"]
    if sysname == "windows":
        if base:
            return [base / "Start Menu" / f"{NAME}.lnk", base / "Desktop" / f"{NAME}.lnk"]
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        programs = _windows_folder(0x02, roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs")   # CSIDL_PROGRAMS
        desktop = _windows_folder(0x10, Path.home() / "Desktop")                                         # CSIDL_DESKTOPDIRECTORY
        return [programs / f"{NAME}.lnk", desktop / f"{NAME}.lnk"]
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return [(base / ".local" / "share" if base else data) / "applications" / "tribunal-ai.desktop"]


def launch_command(sysname: Optional[str] = None) -> List[str]:
    """The program and arguments a shortcut runs. On Windows the window-less Python of the same environment, so no
    console window stays open while the console starts."""
    sysname = sysname or system()
    python = Path(sys.executable)
    if sysname == "windows":
        quiet = python.with_name("pythonw.exe")
        if quiet.is_file():
            python = quiet
    # -I: never the current folder, PYTHONPATH or the user's site folder - a tribunal_cli.py or yaml.py lying in the
    # folder an icon starts in (the home folder) must not be imported instead of the installed code.
    return [str(python), "-I", "-m", "tribunal_cli", "app", "--from-shortcut"]


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _desktop_quote(text: str) -> str:
    """One argument of a .desktop Exec line. Desktop Entry spec: inside quotes \\ " ` $ take a backslash, % is doubled -
    and the value is a string first, whose own unescaping halves every backslash, so each backslash is written twice."""
    inner = "".join("\\" + c if c in '\\"`$' else c for c in text).replace("%", "%%")
    return '"' + inner.replace("\\", "\\\\") + '"'


def mac_files(command: List[str]) -> Dict[str, str]:
    script = ("#!/bin/sh\n"
              f"# {MARK}: opens Tribunal AI. Made by `tribunal shortcut`; `tribunal shortcut --remove` takes it away.\n"
              "exec " + " ".join(_sh_quote(part) for part in command) + "\n")
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{NAME}</string>
  <key>CFBundleDisplayName</key><string>{NAME}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>{LAUNCHER}</string>
  <key>CFBundleIconFile</key><string>tribunal</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>TribunalShortcut</key><string>{MARK}</string>
</dict>
</plist>
"""
    return {"Contents/Info.plist": plist, f"Contents/MacOS/{LAUNCHER}": script}


def desktop_entry(command: List[str], icon_path: Optional[Path] = None) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={NAME}\n"
            + (f"Icon={icon_path}\n" if icon_path else "") +
            "Comment=Claude Code, Codex and Antigravity as one coding team\n"
            "Comment[ko]=Claude Code · Codex · Antigravity를 한 팀으로 부리는 코딩 도구\n"
            "Exec=" + " ".join(_desktop_quote(part) for part in command) + "\n"
            "Terminal=false\n"
            "Categories=Development;\n"
            f"X-Tribunal-Shortcut={MARK}\n")


def _is_ours(path: Path) -> bool:
    try:
        if path.is_symlink():
            return False
        if path.suffix == ".app":
            plist = path / "Contents" / "Info.plist"
            return plist.is_file() and MARK in plist.read_text(encoding="utf-8", errors="replace")
        data = path.read_bytes()
        return MARK.encode("utf-8") in data or MARK.encode("utf-16-le") in data     # a .lnk keeps its text in UTF-16
    except OSError:
        return False


def _write_lnk(path: Path, command: List[str]) -> None:
    """A Windows shortcut through the shell's own COM object. The values travel in environment variables, so no path
    is ever pasted into PowerShell code."""
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TRIBUNAL_LNK); "
              "$s.TargetPath = $env:TRIBUNAL_LNK_TARGET; $s.Arguments = $env:TRIBUNAL_LNK_ARGS; "
              "$s.WorkingDirectory = $env:USERPROFILE; $s.Description = $env:TRIBUNAL_LNK_MARK; "
              "if ($env:TRIBUNAL_LNK_ICON) { $s.IconLocation = $env:TRIBUNAL_LNK_ICON + ',0' }; $s.Save()")
    ico = icon("ico")
    env = dict(os.environ, TRIBUNAL_LNK=str(path), TRIBUNAL_LNK_TARGET=command[0],
               TRIBUNAL_LNK_ICON=str(ico) if ico.is_file() else "",
               TRIBUNAL_LNK_ARGS=subprocess.list2cmdline(command[1:]), TRIBUNAL_LNK_MARK=f"{NAME} ({MARK})")
    shell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL)
    if done.returncode != 0 or not path.is_file():
        raise OSError(f"could not make {path}: {(done.stderr or done.stdout).strip()[:300]}")


def create(sysname: Optional[str] = None) -> Dict[str, List[str]]:
    """Make (or remake) the shortcuts. A file of the same name that is not ours is skipped, never replaced."""
    sysname = sysname or system()
    command = launch_command(sysname)
    made, skipped = [], []
    for path in locations(sysname):
        if (path.exists() or path.is_symlink()) and not _is_ours(path):
            skipped.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if sysname == "mac":
            if path.exists():
                shutil.rmtree(path)
            for rel, text in mac_files(command).items():
                target = path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            (path / "Contents" / "MacOS" / LAUNCHER).chmod(0o755)
            if icon("icns").is_file():
                (path / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(icon("icns"), path / "Contents" / "Resources" / "tribunal.icns")
            os.utime(path)                       # Finder and the Dock read the icon again
        elif sysname == "windows":
            if path.exists():
                path.unlink()
            _write_lnk(path, command)
        else:
            path.write_text(desktop_entry(command, icon("png") if icon("png").is_file() else None), encoding="utf-8")
            path.chmod(0o755)
        made.append(str(path))
    return {"made": made, "skipped": skipped}


def remove(sysname: Optional[str] = None) -> Dict[str, List[str]]:
    """Take away the shortcuts this program made. Anything else at those places stays."""
    removed, kept = [], []
    for path in locations(sysname):
        if not (path.exists() or path.is_symlink()):
            continue
        if not _is_ours(path):
            kept.append(str(path))
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    return {"removed": removed, "kept": kept}


# ---- what a shortcut-started console needs ------------------------------------------------------------------------

_MARKER = "__TRIBUNAL_PATH__"


def login_shell_path(timeout: float = 8.0) -> Optional[str]:
    """PATH as the person's own terminal has it. A program opened from an icon gets the system's short PATH
    (/usr/bin:/bin:/usr/sbin:/sbin on macOS), without Homebrew or ~/.local/bin where git and the AI CLIs live."""
    if os.name == "nt":
        return None                       # Windows gives icons the person's full PATH already
    shell = os.environ.get("SHELL") or ("/bin/zsh" if system() == "mac" else "/bin/sh")
    if not os.path.isabs(shell) or not os.access(shell, os.X_OK):
        return None
    probe = f'printf "{_MARKER}%s{_MARKER}" "$PATH"'
    for flags in ("-ilc", "-lc"):          # interactive first: many people set PATH in ~/.zshrc or ~/.bashrc
        try:
            out = subprocess.run([shell, flags, probe], capture_output=True, text=True, timeout=timeout,
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        parts = (out.stdout or "").split(_MARKER)
        if len(parts) >= 3 and parts[1].strip():
            return parts[1].strip()
    return None


def widen_path() -> None:
    """Before the console starts from an icon: the terminal's PATH first, then what this process had, then the folders
    installers are known to use (core/setup.py). Nothing on the old PATH goes away."""
    current = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    login = [d for d in (login_shell_path() or "").split(os.pathsep) if d]
    merged, seen = [], set()
    for d in login + current:
        key = os.path.normcase(d)
        if key not in seen:
            seen.add(key); merged.append(d)
    os.environ["PATH"] = os.pathsep.join(merged)
    from core import setup
    setup.refresh_path()


def show_error(message: str) -> None:
    """A dialog for someone who opened Tribunal from an icon: there is no terminal to print to."""
    sysname = system()
    try:
        if sysname == "mac":
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            'display alert "Tribunal AI" message (item 1 of argv) as critical', "-e", "end run", message],
                           capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
        elif sysname == "windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, NAME, 0x10)
        else:
            for argv in (["zenity", "--error", "--no-markup", "--title", NAME, "--text", message],
                         ["kdialog", "--title", NAME, "--error", message],
                         ["notify-send", NAME, message]):
                if shutil.which(argv[0]):
                    subprocess.run(argv, capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
                    return
    except Exception:
        pass                              # nothing more can be done without a screen to show it on
